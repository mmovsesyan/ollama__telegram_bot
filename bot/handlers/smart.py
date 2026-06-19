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

    # Reply-based photo Q&A: if the user replies to an image description
    # message from the bot, answer the question about that specific photo.
    reply_to = message.reply_to_message
    if reply_to and reply_to.message_id:
        from bot.services import images as images_service
        image_id = images_service.image_id_for_message(reply_to.message_id)
        if image_id is not None:
            answer = await images_service.answer_question(user_id, image_id, text)
            if answer:
                await message.answer(answer, reply_markup=command_keyboard)
            else:
                await message.answer(
                    "⚠️ Не удалось получить ответ по фото.", reply_markup=command_keyboard
                )
            return

    # Smart reminder completion: "сделал/готово/выполнил ... напоминание".
    from bot.services import reminder_completion as reminder_completion_service
    completion_offer = reminder_completion_service.maybe_offer_completion(user_id, text)
    if completion_offer is not None:
        offer_text, offer_keyboard = completion_offer
        await message.answer(offer_text, reply_markup=offer_keyboard)
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
        # For non-chat tools we still save the exchange and try to extract facts
        # from any assistant reply that is already in the chat context.
        _persist_exchange(user_id, text, "", save_messages=True)
        return

    # ChatTool streams through completion.generate(), which already saves
    # user/assistant messages to the DB. Avoid duplicate rows here.
    is_chat_path = intent_result.tool == "chat"
    markup = result.reply_markup if result.reply_markup is not None else command_keyboard

    from bot.services.voice import voice_output_enabled as _voice_output_enabled
    if _voice_output_enabled(user_id) and is_chat_path:
        from bot.services.voice import send_voice_reply
        await send_voice_reply(message, result.text, bot=message.bot)
    else:
        await message.answer(result.text, reply_markup=markup)
    _persist_exchange(user_id, text, result.text, save_messages=not is_chat_path)

    # Background smart-reminder suggestion after enough chat turns.
    try:
        from bot.services import reminder_suggest as reminder_suggest_service
        reminder_suggest_service.record_interaction(user_id)
        if reminder_suggest_service.should_analyze(user_id):
            import asyncio as _asyncio
            _asyncio.create_task(
                reminder_suggest_service.analyze_and_suggest(
                    user_id,
                    lambda msg, **kwargs: message.answer(msg, **kwargs),
                )
            )
    except Exception:
        logger.exception("Smart reminder suggestion failed for user_id=%s", user_id)


def _persist_exchange(
    user_id: int,
    user_text: str,
    assistant_text: str,
    *,
    save_messages: bool = True,
) -> None:
    """Persist a smart-pipeline exchange and refresh in-memory context.

    - For chat/free-form paths the messages are already saved by
      completion.generate() when ChatTool streams a reply, so this function
      only extracts facts. For other tools (remind, task, weather, ...) it
      also stores the exchange so the next LLM call has continuity.
    - After persisting, refreshes the active chat's system prompt so newly
      saved notes/memories are visible immediately.
    """
    if db is None:
        return
    try:
        from bot.routers import completion
        completion._create_chat(user_id)
        chat = completion.chats.get(user_id)
        if chat and chat.session_id:
            if save_messages:
                db.save_message(user_id, chat.session_id, "user", user_text, chat.selected_model)
                if assistant_text:
                    db.save_message(user_id, chat.session_id, "assistant", assistant_text, chat.selected_model)

        # Use the actual streamed assistant reply when the caller passed an
        # empty placeholder (ChatTool returns empty text after streaming).
        effective_assistant = assistant_text
        if not effective_assistant and chat and chat.ollama_chat.messages:
            for m in reversed(chat.ollama_chat.messages):
                if m.role == "assistant":
                    effective_assistant = m.content
                    break

        # Fire-and-forget fact extraction. Cheap LLM call, runs in background
        # so the user's response isn't delayed. Errors are silent.
        if effective_assistant:
            import asyncio as _asyncio
            from bot.services.kb_extract import extract_facts_from_exchange
            _asyncio.create_task(
                extract_facts_from_exchange(db, user_id, user_text, effective_assistant)
            )

        # Refresh the system prompt in the active chat so new memories/notes
        # are picked up immediately.
        completion.refresh_system_prompt(user_id)
    except Exception:
        logger.exception("Failed to persist smart-pipeline exchange for user_id=%s", user_id)

