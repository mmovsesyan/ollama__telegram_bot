import logging

import aiohttp
from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)

from bot.keyboards.inline import monitor_interval_keyboard
from bot.keyboards.reply import cancel_keyboard, command_keyboard
from bot.security import is_allowed as _is_allowed
from bot.states import BotStates
from bot.routers.common import (
    _format_interval,
    _fsm_guard,
    _is_safe_monitor_url_async,
    _normalize_url,
    _parse_interval,
)

router = Router()
logger = logging.getLogger(__name__)

# Injected from bot/__init__.py at startup.
db = None


@router.message(lambda m: m.text and m.text.startswith("/monitor_add"))
async def cmd_monitor_add(message: Message, state: FSMContext):
    await state.clear()
    if message.from_user is None:
        return
    if not _is_allowed(message.from_user.id):
        return
    if db is None:
        await message.answer("База данных недоступна.", reply_markup=command_keyboard)
        return

    parts = message.text.split(maxsplit=3)
    if len(parts) >= 3:
        await _process_monitor_add(
            message,
            message.from_user.id,
            parts[1],
            _normalize_url(parts[2]),
            _parse_interval(parts[3]) if len(parts) >= 4 else 300,
        )
        return

    await message.answer(
        "🔍 Название монитора?\n" "Например: Google",
        reply_markup=cancel_keyboard,
    )
    await state.set_state(BotStates.waiting_monitor_name)


@router.message(BotStates.waiting_monitor_name)
async def process_monitor_name(message: Message, state: FSMContext):
    if message.from_user is None:
        await state.clear()
        return
    if message.text is None:
        await message.answer("Ожидался текст.", reply_markup=cancel_keyboard)
        await state.clear()
        return
    if await _fsm_guard(message, state):
        return
    name = message.text.strip()
    if not name:
        await message.answer("Введи название монитора.", reply_markup=cancel_keyboard)
        return
    await state.update_data(monitor_name=name)
    await state.set_state(BotStates.waiting_monitor_url)
    await message.answer(
        f"🔍 Монитор: {name}\n\nВведи URL:\n"
        "Например: google.com или https://google.com",
        reply_markup=cancel_keyboard,
    )


@router.message(BotStates.waiting_monitor_url)
async def process_monitor_url(message: Message, state: FSMContext):
    if message.from_user is None:
        await state.clear()
        return
    if message.text is None:
        await message.answer("Ожидался текст.", reply_markup=cancel_keyboard)
        await state.clear()
        return
    if await _fsm_guard(message, state):
        return
    url = _normalize_url(message.text.strip())
    if not url:
        await message.answer("Введи URL.", reply_markup=cancel_keyboard)
        return
    await state.update_data(monitor_url=url)
    await state.set_state(BotStates.waiting_monitor_interval)
    await message.answer(
        "🔍 Интервал проверки?\n" "Например: 5m, 1h, или 300 (секунд)",
        reply_markup=monitor_interval_keyboard(),
    )


@router.callback_query(F.data.startswith("mon_int:"))
async def cb_monitor_interval(callback: CallbackQuery, state: FSMContext):
    if not callback.from_user:
        return
    if not _is_allowed(callback.from_user.id):
        await callback.answer("Нет доступа", show_alert=True)
        return
    interval_text = callback.data.split(":", 1)[1]
    await state.update_data(monitor_interval=_parse_interval(interval_text))
    await _finish_monitor_add(callback.message, state, callback.from_user.id)
    await callback.answer("Монитор добавлен")


@router.message(BotStates.waiting_monitor_interval)
async def process_monitor_interval(message: Message, state: FSMContext):
    if message.from_user is None:
        await state.clear()
        return
    if message.text is None:
        await message.answer("Ожидался текст.", reply_markup=cancel_keyboard)
        await state.clear()
        return
    if await _fsm_guard(message, state):
        return
    interval = _parse_interval(message.text.strip())
    await state.update_data(monitor_interval=interval)
    await _finish_monitor_add(message, state, message.from_user.id)


async def _finish_monitor_add(
    message: Message, state: FSMContext, user_id: int | None = None
):
    data = await state.get_data()
    name = data.get("monitor_name", "")
    url = data.get("monitor_url", "")
    interval = data.get("monitor_interval", 300)
    if not name or not url:
        await message.answer(
            "Ошибка: не хватает данных для монитора.", reply_markup=command_keyboard
        )
        await state.clear()
        return
    # For callback-driven flows callback.message.from_user is the bot, not the
    # user, so the caller must pass the real user_id explicitly.
    if user_id is None and message.from_user is not None:
        user_id = message.from_user.id
    await _process_monitor_add(message, user_id, name, url, interval)
    await state.clear()


async def _process_monitor_add(
    message: Message,
    user_id: int,
    name: str,
    url: str,
    interval: int,
    expected_status: int = 200,
):
    if db is None:
        await message.answer("База данных недоступна.", reply_markup=command_keyboard)
        return

    safe, reason = await _is_safe_monitor_url_async(url)
    if not safe:
        await message.answer(
            f"⚠️ URL не разрешён: {reason}",
            reply_markup=command_keyboard,
        )
        return

    # Defensive floor: never let a monitor poll faster than once a minute,
    # regardless of how the caller parsed the interval.
    interval = max(60, int(interval))

    status_text = "⏳ Проверяю..."
    status_msg = await message.answer(status_text)
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                url, timeout=aiohttp.ClientTimeout(total=10)
            ) as resp:
                status = resp.status
                if status == expected_status:
                    status_text = f"✅ HTTP {status} — сайт доступен"
                else:
                    status_text = f"⚠️ HTTP {status} (ожидался {expected_status})"
    except Exception as e:
        status_text = (
            f"⚠️ Ошибка: {str(e)[:100]}\nМонитор добавлен, но URL может быть недоступен."
        )

    mid = db.add_monitor(
        user_id=user_id,
        name=name,
        url=url,
        expected_status=expected_status,
        interval=interval,
    )
    await status_msg.edit_text(
        f"✅ Монитор #{mid} добавлен\n"
        f"📝 Имя: {name}\n"
        f"🔗 URL: {url}\n"
        f"📊 Проверка: {status_text}\n"
        f"🕐 Интервал: {_format_interval(interval)}"
    )
    await message.answer(
        "Монитор активен. Я пришлю уведомление, если сайт станет недоступен.",
        reply_markup=command_keyboard,
    )


@router.message(lambda m: m.text and m.text == "/monitors")
async def cmd_monitors(message: Message, state: FSMContext):
    await state.clear()
    if message.from_user is None:
        return
    if not _is_allowed(message.from_user.id):
        return
    if db is None:
        await message.answer("База данных недоступна.", reply_markup=command_keyboard)
        return

    monitors = db.get_monitors(message.from_user.id)
    if not monitors:
        await message.answer(
            "Нет активных мониторов.",
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[
                    [
                        InlineKeyboardButton(
                            text="➕ Добавить монитор", callback_data="add_monitor"
                        )
                    ]
                ]
            ),
        )
        return

    text = "🔍 Активные мониторы:\n\n"
    buttons = []
    for idx, m in enumerate(monitors, 1):
        ls = m.get("last_status")
        expected = m.get("expected_status", 200)
        if ls is None or ls == "":
            status = "⏳ не проверялся"
        elif ls == 0:
            status = "❌ недоступен"
        elif ls == expected:
            status = f"✅ HTTP {ls}"
        else:
            status = f"⚠️ HTTP {ls} (ожидался {expected})"
        interval_str = _format_interval(m.get("check_interval", 300))
        text += f"#{idx} | {m['name']}\n"
        text += f"   {status} | {interval_str} | {m['url']}\n\n"
        buttons.append(
            [
                InlineKeyboardButton(
                    text=f"🗑 Удалить #{idx}", callback_data=f"del_monitor:{m['id']}"
                )
            ]
        )

    buttons.append(
        [InlineKeyboardButton(text="➕ Добавить монитор", callback_data="add_monitor")]
    )
    await message.answer(
        text.strip(), reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons)
    )
    await message.answer("Главное меню:", reply_markup=command_keyboard)


@router.message(lambda m: m.text and m.text.startswith("/monitor_remove"))
async def cmd_monitor_remove(message: Message, state: FSMContext):
    await state.clear()
    if message.from_user is None:
        return
    if not _is_allowed(message.from_user.id):
        return
    if db is None:
        await message.answer("База данных недоступна.", reply_markup=command_keyboard)
        return

    parts = message.text.split()
    if len(parts) < 2:
        await message.answer(
            "🗑 Введи ID монитора для удаления:\n" "Пример: 2",
            reply_markup=cancel_keyboard,
        )
        await state.set_state(BotStates.waiting_monitor_remove)
        return

    try:
        mid = int(parts[1])
        user_monitors = db.get_monitors(message.from_user.id)
        if not any(m["id"] == mid for m in user_monitors):
            await message.answer(
                "Нет доступа к этому монитору.", reply_markup=command_keyboard
            )
            return
        db.remove_monitor(mid)
        await message.answer(
            f"✅ Монитор #{mid} удалён.", reply_markup=command_keyboard
        )
    except ValueError:
        await message.answer("Укажи числовой ID.", reply_markup=command_keyboard)


@router.message(BotStates.waiting_monitor_remove)
async def process_monitor_remove(message: Message, state: FSMContext):
    if message.from_user is None:
        await state.clear()
        return
    if message.text is None:
        await message.answer("Ожидался текст.", reply_markup=cancel_keyboard)
        await state.clear()
        return
    if await _fsm_guard(message, state):
        return
    try:
        mid = int(message.text.strip())
        user_monitors = db.get_monitors(message.from_user.id)
        if not any(m["id"] == mid for m in user_monitors):
            await message.answer(
                "Нет доступа к этому монитору.", reply_markup=cancel_keyboard
            )
            await state.clear()
            return
        db.remove_monitor(mid)
        await message.answer(
            f"✅ Монитор #{mid} удалён.", reply_markup=command_keyboard
        )
    except ValueError:
        await message.answer("Укажи числовой ID.", reply_markup=cancel_keyboard)
    await state.clear()


@router.callback_query(F.data.startswith("del_monitor:"))
async def cb_del_monitor(callback: CallbackQuery):
    if not callback.from_user or not callback.data:
        return
    if not _is_allowed(callback.from_user.id):
        await callback.answer("Нет доступа", show_alert=True)
        return
    if db is None:
        await callback.answer("База данных недоступна", show_alert=True)
        return
    try:
        mid = int(callback.data.split(":", 1)[1])
        user_monitors = db.get_monitors(callback.from_user.id)
        if not any(m["id"] == mid for m in user_monitors):
            await callback.answer("Нет доступа", show_alert=True)
            return
        db.remove_monitor(mid)
        await callback.answer(f"Монитор #{mid} удалён")
        try:
            await callback.message.edit_reply_markup(reply_markup=None)
        except TelegramBadRequest as exc:
            logger.warning(
                "Failed to clear monitor delete markup for %s: %s",
                callback.from_user.id,
                exc,
            )
        await callback.message.edit_text(f"✅ Монитор #{mid} удалён.")
    except Exception:
        await callback.answer("Ошибка удаления", show_alert=True)


@router.callback_query(F.data == "add_monitor")
async def cb_add_monitor(callback: CallbackQuery, state: FSMContext):
    if not callback.from_user:
        return
    if not _is_allowed(callback.from_user.id):
        await callback.answer("Нет доступа", show_alert=True)
        return
    await state.clear()
    await callback.answer("Добавление монитора")
    await callback.message.answer(
        "🔍 Название монитора?\n" "Например: Google",
        reply_markup=cancel_keyboard,
    )
    await state.set_state(BotStates.waiting_monitor_name)
