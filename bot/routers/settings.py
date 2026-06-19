"""User settings: morning briefing, proactive mode, news categories."""

import re

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from bot.db import Database
from bot.keyboards.reply import command_keyboard
from bot.security import is_allowed
from bot.services import briefing as briefing_service
from bot.services.profile import now_in_tz
from bot.states import BotStates

router = Router()

db: Database | None = None  # injected in bot.__init__


def _ensure_prefs(user_id: int) -> None:
    """Create a default user_prefs row if the user has never configured."""
    if db is None:
        return
    existing = db.get_user_prefs(user_id)
    if not existing:
        db.set_user_prefs(user_id, timezone="UTC")


def _user_prefs(user_id: int) -> dict:
    if db is None:
        return {}
    _ensure_prefs(user_id)
    return db.get_user_prefs(user_id) or {}


def _bool_label(value) -> str:
    return "включено" if value else "выключено"


def _settings_keyboard(prefs: dict) -> InlineKeyboardMarkup:
    briefing_on = bool(prefs.get("briefing_enabled", 1))
    proactive_on = bool(prefs.get("proactive_enabled", 1))
    voice_on = bool(prefs.get("voice_output_enabled", 0))
    smart_reminders_on = bool(prefs.get("smart_reminders_enabled", 1))
    digest_on = bool(prefs.get("digest_enabled", 0))
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=f"🔔 Брифинг: {_bool_label(briefing_on)}",
                    callback_data="settings:toggle_briefing",
                ),
                InlineKeyboardButton(text="🕐 Время", callback_data="settings:set_time"),
            ],
            [
                InlineKeyboardButton(text="📰 Категории", callback_data="settings:set_categories"),
                InlineKeyboardButton(text="🏙 Город", callback_data="settings:set_city"),
            ],
            [
                InlineKeyboardButton(
                    text=f"🔕 Проактивность: {_bool_label(proactive_on)}",
                    callback_data="settings:toggle_proactive",
                ),
                InlineKeyboardButton(
                    text=f"🗣 Голос: {_bool_label(voice_on)}",
                    callback_data="settings:toggle_voice",
                ),
            ],
            [
                InlineKeyboardButton(
                    text=f"🧠 Умные напоминания: {_bool_label(smart_reminders_on)}",
                    callback_data="settings:toggle_smart_reminders",
                ),
                InlineKeyboardButton(
                    text=f"🌙 Дайджест: {_bool_label(digest_on)}",
                    callback_data="settings:toggle_digest",
                ),
            ],
            [
                InlineKeyboardButton(text="🕙 Время дайджеста", callback_data="settings:set_digest_time"),
                InlineKeyboardButton(text="❌ Закрыть", callback_data="settings:close"),
            ],
        ]
    )


def _settings_text(prefs: dict) -> str:
    return (
        "⚙️ Настройки\n\n"
        f"🔔 Утренний брифинг: {_bool_label(prefs.get('briefing_enabled', 1))}\n"
        f"🕐 Время брифинга: {prefs.get('briefing_time', '08:00')}\n"
        f"📰 Категории: {prefs.get('news_categories', 'tech,markets,ai')}\n"
        f"🏙 Город: {prefs.get('briefing_city') or briefing_service._default_city_for_tz(prefs.get('timezone'))}\n"
        f"🔕 Проактивность: {_bool_label(prefs.get('proactive_enabled', 1))}\n"
        f"🧠 Умные напоминания: {_bool_label(prefs.get('smart_reminders_enabled', 1))}\n"
        f"🗣 Голосовой ответ: {_bool_label(prefs.get('voice_output_enabled', 0))}\n"
        f"🌙 Вечерний дайджест: {_bool_label(prefs.get('digest_enabled', 0))}\n"
        f"🕙 Время дайджеста: {prefs.get('digest_time', '20:00')}"
    )


@router.message(lambda m: m.text and (m.text == "/settings" or m.text.startswith("/settings ")))
async def cmd_settings(message: Message, state: FSMContext):
    await state.clear()
    if message.from_user is None:
        return
    if not is_allowed(message.from_user.id):
        return
    if db is None:
        await message.answer("База данных недоступна.", reply_markup=command_keyboard)
        return

    prefs = _user_prefs(message.from_user.id)
    await message.answer(_settings_text(prefs), reply_markup=_settings_keyboard(prefs))


@router.callback_query(F.data == "settings:close")
async def cb_settings_close(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    if callback.message:
        try:
            await callback.message.edit_reply_markup(reply_markup=None)
        except Exception:
            pass
    await callback.answer("Закрыто")


@router.callback_query(F.data == "settings:toggle_briefing")
async def cb_toggle_briefing(callback: CallbackQuery):
    if not callback.from_user:
        return
    if not is_allowed(callback.from_user.id):
        await callback.answer("Нет доступа", show_alert=True)
        return
    if db is None:
        await callback.answer("База данных недоступна", show_alert=True)
        return
    prefs = _user_prefs(callback.from_user.id)
    new_val = 0 if prefs.get("briefing_enabled", 1) else 1
    db.set_user_prefs(callback.from_user.id, briefing_enabled=new_val)
    prefs = _user_prefs(callback.from_user.id)
    try:
        await callback.message.edit_text(_settings_text(prefs), reply_markup=_settings_keyboard(prefs))
    except Exception:
        pass
    await callback.answer(f"Брифинг {_bool_label(new_val)}")


@router.callback_query(F.data == "settings:toggle_proactive")
async def cb_toggle_proactive(callback: CallbackQuery):
    if not callback.from_user:
        return
    if not is_allowed(callback.from_user.id):
        await callback.answer("Нет доступа", show_alert=True)
        return
    if db is None:
        await callback.answer("База данных недоступна", show_alert=True)
        return
    prefs = _user_prefs(callback.from_user.id)
    new_val = 0 if prefs.get("proactive_enabled", 1) else 1
    db.set_user_prefs(callback.from_user.id, proactive_enabled=new_val)
    prefs = _user_prefs(callback.from_user.id)
    try:
        await callback.message.edit_text(_settings_text(prefs), reply_markup=_settings_keyboard(prefs))
    except Exception:
        pass
    await callback.answer(f"Проактивность {_bool_label(new_val)}")


@router.callback_query(F.data == "settings:toggle_voice")
async def cb_toggle_voice(callback: CallbackQuery):
    if not callback.from_user:
        return
    if not is_allowed(callback.from_user.id):
        await callback.answer("Нет доступа", show_alert=True)
        return
    if db is None:
        await callback.answer("База данных недоступна", show_alert=True)
        return
    prefs = _user_prefs(callback.from_user.id)
    new_val = 0 if prefs.get("voice_output_enabled", 0) else 1
    db.set_user_prefs(callback.from_user.id, voice_output_enabled=new_val)
    prefs = _user_prefs(callback.from_user.id)
    try:
        await callback.message.edit_text(_settings_text(prefs), reply_markup=_settings_keyboard(prefs))
    except Exception:
        pass
    await callback.answer(f"Голосовой ответ {_bool_label(new_val)}")


@router.callback_query(F.data == "settings:toggle_smart_reminders")
async def cb_toggle_smart_reminders(callback: CallbackQuery):
    if not callback.from_user:
        return
    if not is_allowed(callback.from_user.id):
        await callback.answer("Нет доступа", show_alert=True)
        return
    if db is None:
        await callback.answer("База данных недоступна", show_alert=True)
        return
    prefs = _user_prefs(callback.from_user.id)
    new_val = 0 if prefs.get("smart_reminders_enabled", 1) else 1
    db.set_user_prefs(callback.from_user.id, smart_reminders_enabled=new_val)
    prefs = _user_prefs(callback.from_user.id)
    try:
        await callback.message.edit_text(_settings_text(prefs), reply_markup=_settings_keyboard(prefs))
    except Exception:
        pass
    await callback.answer(f"Умные напоминания {_bool_label(new_val)}")


@router.callback_query(F.data == "settings:toggle_digest")
async def cb_toggle_digest(callback: CallbackQuery):
    if not callback.from_user:
        return
    if not is_allowed(callback.from_user.id):
        await callback.answer("Нет доступа", show_alert=True)
        return
    if db is None:
        await callback.answer("База данных недоступна", show_alert=True)
        return
    prefs = _user_prefs(callback.from_user.id)
    new_val = 0 if prefs.get("digest_enabled", 0) else 1
    db.set_user_prefs(callback.from_user.id, digest_enabled=new_val)
    prefs = _user_prefs(callback.from_user.id)
    try:
        await callback.message.edit_text(_settings_text(prefs), reply_markup=_settings_keyboard(prefs))
    except Exception:
        pass
    await callback.answer(f"Вечерний дайджест {_bool_label(new_val)}")


@router.callback_query(F.data == "settings:set_time")
async def cb_set_time(callback: CallbackQuery, state: FSMContext):
    if not callback.from_user:
        return
    if not is_allowed(callback.from_user.id):
        await callback.answer("Нет доступа", show_alert=True)
        return
    await state.set_state(BotStates.waiting_briefing_time)
    await callback.message.answer(
        "🕐 Во сколько присылать брифинг?\nОтветь в формате HH:MM, например: 08:00",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[[InlineKeyboardButton(text="❌ Отмена", callback_data="settings:close_input")]]
        ),
    )
    await callback.answer("Введи время")


@router.callback_query(F.data == "settings:set_categories")
async def cb_set_categories(callback: CallbackQuery, state: FSMContext):
    if not callback.from_user:
        return
    if not is_allowed(callback.from_user.id):
        await callback.answer("Нет доступа", show_alert=True)
        return
    await state.set_state(BotStates.waiting_briefing_categories)
    await callback.message.answer(
        "📰 Какие категории новостей включить?\n"
        "Перечисли через запятую. Доступны:\n"
        "tech, markets, ai, science, crypto, world",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[[InlineKeyboardButton(text="❌ Отмена", callback_data="settings:close_input")]]
        ),
    )
    await callback.answer("Введи категории")


@router.callback_query(F.data == "settings:set_city")
async def cb_set_city(callback: CallbackQuery, state: FSMContext):
    if not callback.from_user:
        return
    if not is_allowed(callback.from_user.id):
        await callback.answer("Нет доступа", show_alert=True)
        return
    await state.set_state(BotStates.waiting_briefing_city)
    await callback.message.answer(
        "🏙 Для какого города показывать погоду?\nНапример: Москва",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[[InlineKeyboardButton(text="❌ Отмена", callback_data="settings:close_input")]]
        ),
    )
    await callback.answer("Введи город")


@router.callback_query(F.data == "settings:close_input")
async def cb_close_input(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    if callback.from_user and callback.message:
        prefs = _user_prefs(callback.from_user.id)
        await callback.message.answer(_settings_text(prefs), reply_markup=_settings_keyboard(prefs))
    await callback.answer("Отменено")


@router.message(BotStates.waiting_briefing_time)
async def process_briefing_time(message: Message, state: FSMContext):
    if message.from_user is None:
        await state.clear()
        return
    if db is None:
        await message.answer("База данных недоступна.", reply_markup=command_keyboard)
        await state.clear()
        return
    text = (message.text or "").strip()
    if not re.fullmatch(r"([01]?\d|2[0-3]):([0-5]\d)", text):
        await message.answer(
            "❌ Неверный формат. Введи время как HH:MM, например 08:00.",
            reply_markup=command_keyboard,
        )
        return
    db.set_user_prefs(message.from_user.id, briefing_time=text)
    await state.clear()
    prefs = _user_prefs(message.from_user.id)
    await message.answer("✅ Время сохранено.", reply_markup=command_keyboard)
    await message.answer(_settings_text(prefs), reply_markup=_settings_keyboard(prefs))


@router.message(BotStates.waiting_briefing_categories)
async def process_briefing_categories(message: Message, state: FSMContext):
    if message.from_user is None:
        await state.clear()
        return
    if db is None:
        await message.answer("База данных недоступна.", reply_markup=command_keyboard)
        await state.clear()
        return
    text = (message.text or "").strip()
    cats = [c.strip().lower() for c in text.split(",") if c.strip()]
    if not cats:
        await message.answer(
            "❌ Не распознал категории. Пример: tech, markets, ai",
            reply_markup=command_keyboard,
        )
        return
    db.set_user_prefs(message.from_user.id, news_categories=",".join(cats))
    await state.clear()
    prefs = _user_prefs(message.from_user.id)
    await message.answer("✅ Категории сохранены.", reply_markup=command_keyboard)
    await message.answer(_settings_text(prefs), reply_markup=_settings_keyboard(prefs))


@router.message(BotStates.waiting_briefing_city)
async def process_briefing_city(message: Message, state: FSMContext):
    if message.from_user is None:
        await state.clear()
        return
    if db is None:
        await message.answer("База данных недоступна.", reply_markup=command_keyboard)
        await state.clear()
        return
    city = (message.text or "").strip()
    if not city or len(city) > 100:
        await message.answer("❌ Введи название города.", reply_markup=command_keyboard)
        return
    db.set_user_prefs(message.from_user.id, briefing_city=city)
    await state.clear()
    prefs = _user_prefs(message.from_user.id)
    await message.answer("✅ Город сохранён.", reply_markup=command_keyboard)
    await message.answer(_settings_text(prefs), reply_markup=_settings_keyboard(prefs))


@router.callback_query(F.data == "settings:set_digest_time")
async def cb_set_digest_time(callback: CallbackQuery, state: FSMContext):
    if not callback.from_user:
        return
    if not is_allowed(callback.from_user.id):
        await callback.answer("Нет доступа", show_alert=True)
        return
    await state.set_state(BotStates.waiting_digest_time)
    await callback.message.answer(
        "🕙 Во сколько присылать вечерний дайджест?\nОтветь в формате HH:MM, например: 20:00",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[[InlineKeyboardButton(text="❌ Отмена", callback_data="settings:close_input")]]
        ),
    )
    await callback.answer("Введи время")


@router.message(BotStates.waiting_digest_time)
async def process_digest_time(message: Message, state: FSMContext):
    if message.from_user is None:
        await state.clear()
        return
    if db is None:
        await message.answer("База данных недоступна.", reply_markup=command_keyboard)
        await state.clear()
        return
    text = (message.text or "").strip()
    if not re.fullmatch(r"([01]?\d|2[0-3]):([0-5]\d)", text):
        await message.answer(
            "❌ Неверный формат. Введи время как HH:MM, например 20:00.",
            reply_markup=command_keyboard,
        )
        return
    db.set_user_prefs(message.from_user.id, digest_time=text)
    await state.clear()
    prefs = _user_prefs(message.from_user.id)
    await message.answer("✅ Время дайджеста сохранено.", reply_markup=command_keyboard)
    await message.answer(_settings_text(prefs), reply_markup=_settings_keyboard(prefs))


@router.message(lambda m: m.text and (m.text == "/briefing" or m.text.startswith("/briefing")))
async def cmd_briefing(message: Message, state: FSMContext):
    """Send the morning briefing on demand."""
    await state.clear()
    if message.from_user is None:
        return
    if not is_allowed(message.from_user.id):
        return
    await message.answer("🌅 Собираю брифинг...")
    from bot.bot import bot as aiogram_bot
    await briefing_service.send_briefing(message.from_user.id, aiogram_bot)


@router.message(lambda m: m.text and (m.text == "/digest" or m.text.startswith("/digest")))
async def cmd_digest(message: Message, state: FSMContext):
    """Send the evening digest on demand."""
    await state.clear()
    if message.from_user is None:
        return
    if not is_allowed(message.from_user.id):
        return
    await message.answer("🌙 Собираю вечерний дайджест...")
    from bot.bot import bot as aiogram_bot
    from bot.services import digest as digest_service
    await digest_service.send_digest(message.from_user.id, aiogram_bot)
