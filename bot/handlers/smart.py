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

# Injected from bot.__init__ at startup; tools that need DB access read this.
db = None

# Texts that are handled by reply-button or explicit-command routers should not
# be processed by the free-form smart pipeline.
_BUTTON_COMMANDS = {
    "🔍 Поиск",
    "🌤 Погода",
    "📰 Новости",
    "⏰ Напомнить",
    "📋 Задача",
    "📝 Заметка",
    "📒 Список",
    "🧠 Память",
    "📚 База",
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
            db=db,
            state=state,
            message=message,
        )
    except Exception:
        logger.exception("Smart handler failed for user_id=%s", user_id)
        await message.answer(
            "⚠️ Что-то пошло не так. Попробуй ещё раз или используй /help.",
            reply_markup=command_keyboard,
        )
        return

    # Tools that send their own Telegram messages return an empty text
    # (e.g. RemindTool, TaskTool — _process_remind/_process_task_from_text
    # already replied via aiogram_bot.send_message).
    if not result.text and result.success:
        _persist_exchange(user_id, text, "")
        return

    markup = result.reply_markup if result.reply_markup is not None else command_keyboard
    await message.answer(result.text, reply_markup=markup)
    _persist_exchange(user_id, text, result.text)


def _persist_exchange(user_id: int, user_text: str, assistant_text: str) -> None:
    """Save a smart-pipeline exchange to the messages table so the LLM has
    context across tool calls. Without this, free-form chats forget the user
    just asked for weather / set a reminder / saved a note.
    """
    if db is None:
        return
    try:
        from bot.routers import completion
        # Reuse completion's session machinery so chat and tool calls share
        # one session per user. _create_chat is idempotent and bootstraps.
        completion._create_chat(user_id)
        chat = completion.chats.get(user_id)
        if chat and chat.session_id:
            db.save_message(user_id, chat.session_id, "user", user_text, chat.selected_model)
            if assistant_text:
                db.save_message(user_id, chat.session_id, "assistant", assistant_text, chat.selected_model)
    except Exception:
        logger.exception("Failed to persist smart-pipeline exchange for user_id=%s", user_id)

