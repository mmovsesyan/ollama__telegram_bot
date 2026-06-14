import logging
from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import Message

from bot.intent.executor import IntentExecutor
from bot.intent.router import LLMIntentRouter
from bot.keyboards.reply import command_keyboard

logger = logging.getLogger(__name__)

router = Router()
_default_executor = IntentExecutor()


@router.message(F.text)
async def smart_message_handler(message: Message, state: FSMContext | None = None):
    """Handle free-form text through the smart intent pipeline."""
    if message.from_user is None or message.text is None:
        return

    # Clear any stuck FSM state before processing a new free-form request.
    if state is not None:
        await state.clear()

    user_id = message.from_user.id
    text = message.text.strip()

    # Broad catch-all keeps the Telegram handler from crashing on any pipeline bug;
    # individual tools already have their own exception handling.
    try:
        intent_result = await LLMIntentRouter.route(user_id=user_id, message_text=text)
        result = await _default_executor.execute(
            user_id=user_id,
            message_text=text,
            intent_result=intent_result,
        )
    except Exception:
        logger.exception("Smart handler failed for user_id=%s", user_id)
        await message.answer(
            "⚠️ Что-то пошло не так. Попробуй ещё раз или используй /help.",
            reply_markup=command_keyboard,
        )
        return

    # Tools that send their own Telegram messages may return an empty text.
    if not result.text and result.success:
        return

    markup = result.reply_markup if result.reply_markup is not None else command_keyboard
    await message.answer(result.text, reply_markup=markup)
