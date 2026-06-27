import logging
from datetime import timedelta

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from bot.keyboards.inline import task_quick_keyboard
from bot.keyboards.reply import cancel_keyboard, command_keyboard
from bot.security import is_allowed as _is_allowed
from bot.services import reminders as reminders_service
from bot.services.profile import local_to_utc, now_in_tz
from bot.states import BotStates
from bot.routers.common import _fsm_guard, _format_trigger, _user_tz

router = Router()
logger = logging.getLogger(__name__)

# Injected from bot/__init__.py at startup.
db = None


@router.message(lambda m: m.text and m.text == "/task")
async def cmd_task(message: Message, state: FSMContext):
    """Task creation via explicit /task command (button removed from main menu)."""
    await state.clear()
    if message.from_user is None:
        return
    if not _is_allowed(message.from_user.id):
        return
    if db is None:
        await message.answer("База данных недоступна.", reply_markup=command_keyboard)
        return

    await message.answer(
        "📋 Какую задачу выполнить?\n"
        "Я сам выполню её в указанное время.\n\n"
        "Примеры:\n"
        "• пришли погоду в Москве\n"
        "• поищи последние новости Tesla\n"
        "• составь краткий отчёт",
        reply_markup=cancel_keyboard,
    )
    await state.set_state(BotStates.waiting_task_text)


@router.message(BotStates.waiting_task_text)
async def process_task_text(message: Message, state: FSMContext):
    if message.from_user is None:
        await state.clear()
        return
    if message.text is None:
        await message.answer("Ожидался текст.", reply_markup=cancel_keyboard)
        await state.clear()
        return
    if await _fsm_guard(message, state):
        return
    await state.update_data(task_content=message.text.strip(), task_action="execute")
    await state.set_state(BotStates.waiting_task_time)
    await message.answer(
        "📋 Задача будет выполнена через AI при срабатывании.\n\nКогда выполнить?",
        reply_markup=task_quick_keyboard(),
    )


@router.message(BotStates.waiting_task_time)
async def process_task_time_manual(message: Message, state: FSMContext):
    if message.from_user is None:
        await state.clear()
        return
    if message.text is None:
        await message.answer("Ожидался текст.", reply_markup=cancel_keyboard)
        await state.clear()
        return
    if await _fsm_guard(message, state):
        return
    data = await state.get_data()
    content = data.get("task_content", "")
    time_str = message.text.strip()
    trigger_at, recurring, parsed = reminders_service.parse_reminder_strict(
        time_str, tz_name=_user_tz(message.from_user.id)
    )
    if not parsed:
        await message.answer(
            "❓ Не понял время. Примеры: `через 5 минут`, `завтра в 9:00`, `каждый день в 7:00`, `2026-06-15 09:00`.",
            reply_markup=cancel_keyboard,
        )
        return
    if db is None:
        await message.answer("База данных недоступна.", reply_markup=command_keyboard)
        await state.clear()
        return
    db.add_reminder(
        user_id=message.from_user.id,
        content=content,
        trigger_at=trigger_at.isoformat(),
        recurring=recurring,
        action="execute",
    )
    rec_label = f" ({recurring})" if recurring else ""
    await message.answer(
        f"✅ Задача добавлена\n"
        f"🕐 Сработает: {_format_trigger(trigger_at, message.from_user.id)}{rec_label}\n"
        f"🤖 Режим: AI-выполнение\n"
        f"📝 Текст: {content}",
        reply_markup=command_keyboard,
    )
    await state.clear()


@router.callback_query(F.data.startswith("task_time:"))
async def cb_select_task_time(callback: CallbackQuery, state: FSMContext):
    if not callback.from_user:
        return
    if not _is_allowed(callback.from_user.id):
        await callback.answer("Нет доступа", show_alert=True)
        return
    mode = callback.data.split(":", 1)[1]
    data = await state.get_data()
    content = data.get("task_content", "")
    if not content:
        await callback.answer("Ошибка: нет текста задачи", show_alert=True)
        await state.clear()
        return

    tz_name = _user_tz(callback.from_user.id)
    now_local = now_in_tz(tz_name)
    trigger_at_local = now_local
    recurring = None

    if mode == "5m":
        trigger_at_local = now_local + timedelta(minutes=5)
    elif mode == "1h":
        trigger_at_local = now_local + timedelta(hours=1)
    elif mode == "tomorrow9":
        trigger_at_local = (now_local + timedelta(days=1)).replace(
            hour=9, minute=0, second=0, microsecond=0
        )
    elif mode == "daily7":
        trigger_at_local = now_local.replace(hour=7, minute=0, second=0, microsecond=0)
        if trigger_at_local <= now_local:
            trigger_at_local += timedelta(days=1)
        recurring = "daily"
    elif mode == "weekday9":
        trigger_at_local = now_local.replace(hour=9, minute=0, second=0, microsecond=0)
        if trigger_at_local <= now_local or trigger_at_local.weekday() >= 5:
            trigger_at_local += timedelta(days=1)
            while trigger_at_local.weekday() >= 5:
                trigger_at_local += timedelta(days=1)
        recurring = "weekday"
    elif mode == "friday18":
        days_ahead = (4 - now_local.weekday()) % 7
        if (
            days_ahead == 0
            and now_local.replace(hour=18, minute=0, second=0, microsecond=0)
            <= now_local
        ):
            days_ahead = 7
        trigger_at_local = now_local + timedelta(days=days_ahead)
        trigger_at_local = trigger_at_local.replace(
            hour=18, minute=0, second=0, microsecond=0
        )
        recurring = "friday"
    elif mode == "manual":
        await state.set_state(BotStates.waiting_task_time)
        await callback.message.answer(
            "⏰ Введи время задачи:\n"
            "Примеры:\n"
            "  через 5 минут\n"
            "  завтра в 9:00\n"
            "  каждый будний день в 7:00\n"
            "  понедельник в 10:00\n"
            "  еженедельно в пятницу 18:00",
            reply_markup=cancel_keyboard,
        )
        await callback.answer("Введи время вручную")
        return
    else:
        trigger_at_local = now_local + timedelta(minutes=5)

    trigger_at = local_to_utc(trigger_at_local, tz_name)

    if db is None:
        await callback.answer("База данных недоступна", show_alert=True)
        await state.clear()
        return
    db.add_reminder(
        user_id=callback.from_user.id,
        content=content,
        trigger_at=trigger_at.isoformat(),
        recurring=recurring,
        action="execute",
    )
    rec_label = f" ({recurring})" if recurring else ""
    from bot.bot import bot as aiogram_bot

    await aiogram_bot.send_message(
        chat_id=callback.from_user.id,
        text=f"✅ Задача добавлена\n"
        f"🕐 Сработает: {_format_trigger(trigger_at, callback.from_user.id)}{rec_label}\n"
        f"🤖 Режим: AI-выполнение\n"
        f"📝 Текст: {content}",
        reply_markup=command_keyboard,
    )
    await state.clear()
    await callback.answer("Задача создана")
