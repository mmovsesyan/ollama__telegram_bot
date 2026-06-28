import logging
from datetime import timedelta

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)

from bot.keyboards.inline import reminder_quick_keyboard
from bot.keyboards.reply import cancel_keyboard, command_keyboard
from bot.security import is_allowed as _is_allowed
from bot.services import reminders as reminders_service
from bot.services.profile import local_to_utc, now_in_tz
from bot.states import BotStates
from bot.routers.common import (
    _BUTTON_HANDLERS,
    _fsm_guard,
    _format_trigger,
    _user_tz,
)

router = Router()
logger = logging.getLogger(__name__)

# Injected from bot/__init__.py at startup.
db = None


@router.message(
    lambda m: m.text and (m.text == "/remind" or m.text.startswith("/remind "))
)
async def cmd_remind(message: Message, state: FSMContext):
    await state.clear()
    if message.from_user is None:
        return
    if not _is_allowed(message.from_user.id):
        return
    if db is None:
        await message.answer("База данных недоступна.", reply_markup=command_keyboard)
        return

    parts = message.text.split(maxsplit=1)
    if len(parts) < 2:
        await message.answer(
            "⏰ Чего напомнить?\n" "Например: позвонить брокеру",
            reply_markup=cancel_keyboard,
        )
        await state.set_state(BotStates.waiting_remind)
        return

    await message.answer("⏰ Добавляю напоминание...")
    await reminders_service._process_remind(message.from_user.id, parts[1])


@router.message(F.text == "⏰ Напомнить")
async def btn_remind(message: Message, state: FSMContext):
    await state.clear()
    if message.from_user is None:
        return
    if not _is_allowed(message.from_user.id):
        return
    if db is None:
        await message.answer("База данных недоступна.", reply_markup=command_keyboard)
        return

    await message.answer(
        "⏰ Чего напомнить?\n" "Например: позвонить брокеру",
        reply_markup=cancel_keyboard,
    )
    await state.set_state(BotStates.waiting_remind)


@router.message(BotStates.waiting_remind)
async def process_remind(message: Message, state: FSMContext):
    if message.from_user is None:
        await state.clear()
        return
    if message.text is None:
        await message.answer("Ожидался текст.", reply_markup=cancel_keyboard)
        await state.clear()
        return
    if await _fsm_guard(message, state):
        return
    content = message.text.strip()
    if not content:
        await message.answer("Введи текст напоминания.", reply_markup=cancel_keyboard)
        return
    await state.update_data(remind_content=content)
    await state.set_state(BotStates.waiting_remind_time)
    await message.answer(
        f"⏰ Напомнить: {content}\n\nКогда?",
        reply_markup=reminder_quick_keyboard(),
    )


@router.callback_query(F.data.startswith("remind_quick:"))
async def cb_remind_quick(callback: CallbackQuery, state: FSMContext):
    if not callback.from_user:
        return
    if not _is_allowed(callback.from_user.id):
        await callback.answer("Нет доступа", show_alert=True)
        return
    mode = callback.data.split(":", 1)[1]
    data = await state.get_data()
    content = data.get("remind_content", "")
    if not content:
        await callback.answer("Ошибка: нет текста", show_alert=True)
        await state.clear()
        return

    if db is None:
        await callback.answer("База данных недоступна", show_alert=True)
        await state.clear()
        return

    tz_name = _user_tz(callback.from_user.id)
    now_local = now_in_tz(tz_name)
    trigger_at_local = now_local
    recurring = None

    if mode == "5m":
        trigger_at_local = now_local + timedelta(minutes=5)
    elif mode == "tomorrow9":
        trigger_at_local = (now_local + timedelta(days=1)).replace(
            hour=9, minute=0, second=0, microsecond=0
        )
    elif mode == "daily9":
        trigger_at_local = now_local.replace(hour=9, minute=0, second=0, microsecond=0)
        if trigger_at_local <= now_local:
            trigger_at_local += timedelta(days=1)
        recurring = "daily"
    elif mode == "auto":
        await state.set_state(BotStates.waiting_remind_time)
        await callback.message.answer(
            "⏰ Когда напомнить?\n"
            "Например: через 5 минут, завтра в 9:00, каждый день в 7:00",
            reply_markup=cancel_keyboard,
        )
        await callback.answer("Введи время")
        return
    else:
        trigger_at_local = now_local + timedelta(minutes=5)

    trigger_at = local_to_utc(trigger_at_local, tz_name)

    db.add_reminder(
        user_id=callback.from_user.id,
        content=content,
        trigger_at=trigger_at.isoformat(),
        recurring=recurring,
        action="notify",
    )
    rec_label = f" ({recurring})" if recurring else ""
    await callback.message.answer(
        f"✅ Напоминание добавлено\n"
        f"🕐 Сработает: {_format_trigger(trigger_at, callback.from_user.id)}{rec_label}\n"
        f"📝 Текст: {content}",
        reply_markup=command_keyboard,
    )
    await state.clear()
    await callback.answer("Напоминание создано")


@router.message(BotStates.waiting_remind_time)
async def process_remind_time(message: Message, state: FSMContext):
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
    content = data.get("remind_content", "")
    if not content:
        await message.answer(
            "Ошибка: не найден текст напоминания.", reply_markup=cancel_keyboard
        )
        await state.clear()
        return
    time_text = message.text.strip()
    trigger_at, recurring, parsed = reminders_service.parse_reminder_strict(
        time_text, tz_name=_user_tz(message.from_user.id)
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
        action="notify",
    )
    rec_label = f" ({recurring})" if recurring else ""
    await message.answer(
        f"✅ Напоминание добавлено\n"
        f"🕐 Сработает: {_format_trigger(trigger_at, message.from_user.id)}{rec_label}\n"
        f"📝 Текст: {content}",
        reply_markup=command_keyboard,
    )
    await state.clear()


@router.message(lambda m: m.text and m.text == "/reminders")
@router.message(F.text == "📒 Список")
async def cmd_reminders(message: Message, state: FSMContext):
    await state.clear()
    if message.from_user is None:
        return
    if not _is_allowed(message.from_user.id):
        return
    if db is None:
        await message.answer("База данных недоступна.", reply_markup=command_keyboard)
        return

    reminders = db.get_user_reminders(message.from_user.id)
    if not reminders:
        await message.answer(
            "📒 Нет активных напоминаний и задач.\n\nДобавь через ⏰ Напомнить или 📋 Задача.",
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[
                    [
                        InlineKeyboardButton(
                            text="➕ Добавить напоминание", callback_data="add_reminder"
                        )
                    ],
                ]
            ),
        )
        return

    text = "📒 Активные напоминания и задачи:\n\n"
    buttons = []
    for idx, r in enumerate(reminders, 1):
        time_str = _format_trigger(r.get("trigger_at"), message.from_user.id)
        content = r.get("content", "")
        rec = r.get("recurring")
        is_task = r.get("action") == "execute"
        mode = "🤖 Задача" if is_task else "⏰ Напоминание"
        rec_label = f" 🔁 {rec}" if rec else ""
        text += f"#{idx} {mode}{rec_label}\n🕐 {time_str}\n📝 {content}\n\n"
        buttons.append(
            [
                InlineKeyboardButton(
                    text=f"✏️ #{idx}", callback_data=f"edit_reminder:{r['id']}"
                ),
                InlineKeyboardButton(
                    text=f"❌ #{idx}", callback_data=f"del_reminder:{r['id']}"
                ),
            ]
        )

    buttons.append(
        [
            InlineKeyboardButton(
                text="➕ Добавить напоминание", callback_data="add_reminder"
            )
        ]
    )
    await message.answer(
        text.strip(), reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons)
    )


@router.message(lambda m: m.text and m.text.startswith("/remind_cancel"))
async def cmd_remind_cancel(message: Message, state: FSMContext):
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
            "❌ Введи ID напоминания для отмены:\n" "Пример: 3",
            reply_markup=cancel_keyboard,
        )
        await state.set_state(BotStates.waiting_remind_cancel)
        return

    try:
        rid = int(parts[1])
        user_reminders = db.get_user_reminders(message.from_user.id)
        if not any(r["id"] == rid for r in user_reminders):
            await message.answer(
                "Нет доступа к этому напоминанию.", reply_markup=command_keyboard
            )
            return
        db.disable_reminder(rid)
        await message.answer("✅ Напоминание удалено.", reply_markup=command_keyboard)
    except ValueError:
        await message.answer(
            "Укажи числовой ID напоминания.", reply_markup=command_keyboard
        )


@router.message(BotStates.waiting_remind_cancel)
async def process_remind_cancel(message: Message, state: FSMContext):
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
        rid = int(message.text.strip())
        user_reminders = db.get_user_reminders(message.from_user.id)
        if not any(r["id"] == rid for r in user_reminders):
            await message.answer(
                "Нет доступа к этому напоминанию.", reply_markup=cancel_keyboard
            )
            await state.clear()
            return
        db.disable_reminder(rid)
        await message.answer("✅ Напоминание удалено.", reply_markup=command_keyboard)
    except ValueError:
        await message.answer(
            "Укажи числовой ID напоминания.", reply_markup=cancel_keyboard
        )
    await state.clear()


@router.callback_query(F.data.startswith("del_reminder:"))
async def cb_del_reminder(callback: CallbackQuery):
    if not callback.from_user or not callback.data:
        return
    if not _is_allowed(callback.from_user.id):
        await callback.answer("Нет доступа", show_alert=True)
        return
    if db is None:
        await callback.answer("База данных недоступна", show_alert=True)
        return
    try:
        rid = int(callback.data.split(":", 1)[1])
        user_reminders = db.get_user_reminders(callback.from_user.id)
        if not any(r["id"] == rid for r in user_reminders):
            await callback.answer("Нет доступа", show_alert=True)
            return
        db.disable_reminder(rid)
        await callback.answer("Напоминание удалено")
        try:
            await callback.message.edit_reply_markup(reply_markup=None)
        except TelegramBadRequest as exc:
            logger.warning(
                "Failed to clear reminder delete markup for %s: %s",
                callback.from_user.id,
                exc,
            )
        await callback.message.edit_text("✅ Напоминание удалено.")
    except Exception:
        await callback.answer("Ошибка удаления", show_alert=True)


@router.callback_query(F.data.startswith("edit_reminder:"))
async def cb_edit_reminder(callback: CallbackQuery, state: FSMContext):
    """Show inline menu: edit content vs edit time vs cancel."""
    if not callback.from_user or not callback.data:
        return
    if not _is_allowed(callback.from_user.id):
        await callback.answer("Нет доступа", show_alert=True)
        return
    if db is None:
        await callback.answer("База данных недоступна", show_alert=True)
        return
    try:
        rid = int(callback.data.split(":", 1)[1])
    except ValueError:
        await callback.answer("Неверный ID", show_alert=True)
        return
    reminder = db.get_reminder(rid)
    if not reminder or reminder["user_id"] != callback.from_user.id:
        await callback.answer("Нет доступа", show_alert=True)
        return

    is_task = reminder.get("action") == "execute"
    label = "задачу" if is_task else "напоминание"
    await callback.message.answer(
        f"✏️ Редактировать {label}\n\n"
        f"📝 {reminder.get('content', '')}\n"
        f"🕐 {_format_trigger(reminder.get('trigger_at'), callback.from_user.id)}\n\n"
        f"Что менять?",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text="📝 Текст", callback_data=f"edit_rcontent:{rid}"
                    )
                ],
                [
                    InlineKeyboardButton(
                        text="🕐 Время", callback_data=f"edit_rtime:{rid}"
                    )
                ],
                [InlineKeyboardButton(text="❌ Отмена", callback_data="cancel")],
            ]
        ),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("edit_rcontent:"))
async def cb_edit_reminder_content(callback: CallbackQuery, state: FSMContext):
    if not callback.from_user or not callback.data:
        return
    if not _is_allowed(callback.from_user.id):
        await callback.answer("Нет доступа", show_alert=True)
        return
    rid = int(callback.data.split(":", 1)[1])
    await state.update_data(edit_reminder_id=rid)
    await state.set_state(BotStates.waiting_remind_edit_content)
    await callback.message.answer(
        "📝 Введи новый текст:",
        reply_markup=cancel_keyboard,
    )
    await callback.answer("Введи новый текст")


@router.callback_query(F.data.startswith("edit_rtime:"))
async def cb_edit_reminder_time(callback: CallbackQuery, state: FSMContext):
    if not callback.from_user or not callback.data:
        return
    if not _is_allowed(callback.from_user.id):
        await callback.answer("Нет доступа", show_alert=True)
        return
    rid = int(callback.data.split(":", 1)[1])
    await state.update_data(edit_reminder_id=rid)
    await state.set_state(BotStates.waiting_remind_edit_time)
    await callback.message.answer(
        "🕐 Введи новое время:\n"
        "Примеры: «через 5 минут», «завтра в 9:00», «каждый день в 7:00», «2026-06-15 09:00»",
        reply_markup=cancel_keyboard,
    )
    await callback.answer("Введи новое время")


@router.message(BotStates.waiting_remind_edit_content)
async def process_edit_reminder_content(message: Message, state: FSMContext):
    if message.from_user is None:
        await state.clear()
        return
    if message.text is None:
        await message.answer("Ожидался текст.", reply_markup=cancel_keyboard)
        await state.clear()
        return
    if await _fsm_guard(message, state):
        return
    if db is None:
        await message.answer("База данных недоступна.", reply_markup=command_keyboard)
        await state.clear()
        return
    data = await state.get_data()
    rid = data.get("edit_reminder_id")
    reminder = db.get_reminder(rid) if rid else None
    if not reminder or reminder["user_id"] != message.from_user.id:
        await message.answer(
            "Нет доступа к этой записи.", reply_markup=command_keyboard
        )
        await state.clear()
        return
    new_content = message.text.strip()
    if not new_content:
        await message.answer(
            "Текст не может быть пустым.", reply_markup=cancel_keyboard
        )
        return
    db.update_reminder_content(rid, new_content)
    await message.answer(
        f"✅ Обновлено\n📝 {new_content}",
        reply_markup=command_keyboard,
    )
    await state.clear()


@router.message(BotStates.waiting_remind_edit_time)
async def process_edit_reminder_time(message: Message, state: FSMContext):
    if message.from_user is None:
        await state.clear()
        return
    if message.text is None:
        await message.answer("Ожидался текст.", reply_markup=cancel_keyboard)
        await state.clear()
        return
    if await _fsm_guard(message, state):
        return
    if db is None:
        await message.answer("База данных недоступна.", reply_markup=command_keyboard)
        await state.clear()
        return
    data = await state.get_data()
    rid = data.get("edit_reminder_id")
    reminder = db.get_reminder(rid) if rid else None
    if not reminder or reminder["user_id"] != message.from_user.id:
        await message.answer(
            "Нет доступа к этой записи.", reply_markup=command_keyboard
        )
        await state.clear()
        return
    trigger_at, recurring, parsed = reminders_service.parse_reminder_strict(
        message.text.strip(), tz_name=_user_tz(message.from_user.id)
    )
    if not parsed:
        await message.answer(
            "❓ Не понял время. Примеры: «через 5 минут», «завтра в 9:00», «каждый день в 7:00».",
            reply_markup=cancel_keyboard,
        )
        return
    db.update_reminder_schedule(rid, trigger_at.isoformat(), recurring)
    rec_label = f" 🔁 {recurring}" if recurring else ""
    await message.answer(
        f"✅ Обновлено\n🕐 {_format_trigger(trigger_at, message.from_user.id)}{rec_label}",
        reply_markup=command_keyboard,
    )
    await state.clear()


@router.callback_query(F.data == "add_reminder")
async def cb_add_reminder(callback: CallbackQuery, state: FSMContext):
    if not callback.from_user:
        return
    if not _is_allowed(callback.from_user.id):
        await callback.answer("Нет доступа", show_alert=True)
        return
    await state.clear()
    await callback.answer("Добавление напоминания")
    await callback.message.answer(
        "⏰ Чего напомнить?\n" "Например: позвонить брокеру",
        reply_markup=cancel_keyboard,
    )
    await state.set_state(BotStates.waiting_remind)


@router.callback_query(F.data.startswith("reminder_done:"))
async def cb_reminder_done(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    if not callback.from_user:
        return
    user_id = callback.from_user.id
    if not _is_allowed(user_id):
        await callback.answer("Нет доступа", show_alert=True)
        return
    if db is None:
        await callback.answer("База данных недоступна", show_alert=True)
        return

    data = callback.data
    from bot.services import reminder_completion as reminder_completion_service

    if data == "reminder_done:dismiss":
        await callback.message.edit_text("👌 Оставлю напоминание активным.")
        await callback.answer("Отменено")
        return

    try:
        reminder_id = int(data.split(":", 1)[1])
    except (ValueError, IndexError):
        await callback.answer("Ошибка данных", show_alert=True)
        return

    result = reminder_completion_service.complete_reminder(user_id, reminder_id)
    await callback.message.edit_text(result, reply_markup=command_keyboard)
    await callback.answer("Закрыто")


_BUTTON_HANDLERS.update(
    {
        "⏰ Напомнить": lambda msg, st: btn_remind(msg, st),
        "📒 Список": lambda msg, st: cmd_reminders(msg, st),
    }
)
