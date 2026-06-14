import logging
from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import Message

from bot.intent.executor import IntentExecutor
from bot.intent.router import LLMIntentRouter
from bot.keyboards.reply import command_keyboard
from bot.security import is_allowed

logger = logging.getLogger(__name__)

router = Router()
_default_executor = IntentExecutor()

# Texts that are handled by reply-button or explicit-command routers should not
# be processed by the free-form smart pipeline.
_BUTTON_COMMANDS = {
    "💬 Чат",
    "🔍 Поиск",
    "🌤 Погода",
    "⏰ Напомнить",
    "📋 Задача",
    "📝 Заметка",
    "🧠 Память",
    "📊 Отчёт",
    "❓ Помощь",
    "🗑 Очистить",
    "🤖 Модели",
}


def _looks_like_command(text: str) -> bool:
    return text.startswith("/") or text in _BUTTON_COMMANDS


@router.message(F.text)
async def smart_message_handler(message: Message, state: FSMContext | None = None):
    """Handle free-form text through the smart intent pipeline."""
    if message.from_user is None or message.text is None:
        return

    user_id = message.from_user.id
    if not is_allowed(user_id):
        logger.warning("Smart handler blocked unauthorized user_id=%s", user_id)
        return

    text = message.text.strip()
    if _looks_like_command(text):
        # Let cron/completion routers handle explicit commands and button presses.
        return

    # Clear any stuck FSM state before processing a new free-form request.
    if state is not None:
        await state.clear()

    # Broad catch-all keeps the Telegram handler from crashing on any pipeline bug;
    # individual tools already have their own exception handling.
    try:
        intent_result = await LLMIntentRouter.route(user_id=user_id, message_text=text)
        result = await _default_executor.execute(
            user_id=user_id,
            message_text=text,
            intent_result=intent_result,
            db=getattr(smart_message_handler, "db", None),
            state=state,
        )
    except Exception:
        logger.exception("Smart handler failed for user_id=%s", user_id)
        await message.answer(
            "⚠️ Что-то пошло не так. Попробуй ещё раз или используй /help.",
            reply_markup=command_keyboard,
        )
        return

    # Tools that send their own Telegram messages return an empty text.
    if not result.text and result.success:
        return

    markup = result.reply_markup if result.reply_markup is not None else command_keyboard
    await message.answer(result.text, reply_markup=markup)
