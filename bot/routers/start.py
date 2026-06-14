import logging

from aiogram import Router
from aiogram.filters.command import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import Message

from bot.keyboards.reply import cancel_keyboard, command_keyboard
from bot.security import is_allowed
from bot.services.profile import resolve_timezone, now_in_tz
from bot.states import BotStates

logger = logging.getLogger(__name__)

router = Router()
db = None  # injected from bot.__init__


@router.message(CommandStart())
async def start_command(message: Message, state: FSMContext) -> None:
    """First-run onboarding asks for name and country to set timezone.
    Returning users skip straight to the main menu."""
    if message.from_user is None:
        return
    user_id = message.from_user.id
    if not is_allowed(user_id):
        return

    prefs = db.get_user_prefs(user_id) if db else None
    if prefs and prefs.get("name") and prefs.get("timezone"):
        await message.answer(
            f"С возвращением, {prefs['name']}.\n"
            f"Часовой пояс: {prefs['timezone']}\n\n"
            "Просто **напиши** или **скажи голосом**, что нужно:\n"
            "• «погода в Москве»\n"
            "• «напомни через 5 минут позвонить»\n"
            "• «задача каждое утро в 9 покажи новости»\n\n"
            "Или используй кнопки внизу. Нажми /help для примеров.",
            reply_markup=command_keyboard,
            parse_mode="Markdown",
        )
        return

    await state.clear()
    await message.answer(
        "Привет. Я AI-бот на базе Ollama.\n\n"
        "Чтобы напоминания и задачи работали в твоём часовом поясе, "
        "давай быстро настроим профиль (займёт 20 секунд).\n\n"
        "Как тебя зовут?",
        reply_markup=cancel_keyboard,
    )
    await state.set_state(BotStates.onboarding_name)


@router.message(BotStates.onboarding_name)
async def onboarding_name(message: Message, state: FSMContext) -> None:
    if message.from_user is None or message.text is None:
        await state.clear()
        return
    text = message.text.strip()
    if text == "❌ Отмена":
        await state.clear()
        await message.answer(
            "Ок, настрою позже. Можешь сразу пользоваться: «погода в Москве», "
            "«напомни через 5 минут позвонить». Время будет в UTC, "
            "пока не настроишь часовой пояс через /start.",
            reply_markup=command_keyboard,
        )
        return
    if not text or len(text) > 50:
        await message.answer(
            "Введи имя (до 50 символов).",
            reply_markup=cancel_keyboard,
        )
        return

    if db:
        db.set_user_prefs(message.from_user.id, name=text)

    await state.update_data(onboarding_name=text)
    await state.set_state(BotStates.onboarding_country)
    await message.answer(
        f"Приятно, {text}.\n\n"
        "В какой стране или городе ты живёшь? "
        "Я подберу часовой пояс.\n\n"
        "Примеры: «Россия», «Москва», «Армения», «Germany», «UTC».",
        reply_markup=cancel_keyboard,
    )


@router.message(BotStates.onboarding_country)
async def onboarding_country(message: Message, state: FSMContext) -> None:
    if message.from_user is None or message.text is None:
        await state.clear()
        return
    text = message.text.strip()
    if text == "❌ Отмена":
        await state.clear()
        await message.answer(
            "Ок, оставлю UTC по умолчанию. Изменишь позже через /start.",
            reply_markup=command_keyboard,
        )
        return

    tz_name = resolve_timezone(text)
    if not tz_name:
        await message.answer(
            "Не нашёл такой часовой пояс. Попробуй название страны "
            "(«Россия», «USA») или IANA-формат («Europe/Moscow», «Asia/Tokyo»).",
            reply_markup=cancel_keyboard,
        )
        return

    if db:
        db.set_user_prefs(message.from_user.id, timezone=tz_name)

    data = await state.get_data()
    user_name = data.get("onboarding_name", "друг")
    local_now = now_in_tz(tz_name).strftime("%H:%M")

    await message.answer(
        f"✅ Готово, {user_name}.\n"
        f"Часовой пояс: {tz_name}\n"
        f"Локальное время сейчас: {local_now}\n\n"
        "Теперь напоминания и задачи будут срабатывать в твоём времени.\n\n"
        "Что я умею:\n"
        "• «погода в Москве»\n"
        "• «напомни через 5 минут позвонить»\n"
        "• «задача каждое утро в 9 покажи новости»\n"
        "• «заметка: купить акции TSLA»\n\n"
        "Кнопки снизу или просто пиши/говори. /help — примеры.",
        reply_markup=command_keyboard,
    )
    await state.clear()
