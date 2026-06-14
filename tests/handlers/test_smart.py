import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from bot.handlers.smart import smart_message_handler
from bot.keyboards.reply import command_keyboard


def _make_message(text: str = "hello world") -> MagicMock:
    message = MagicMock()
    message.from_user = MagicMock(id=42)
    message.text = text
    message.answer = AsyncMock()
    return message


@pytest.mark.asyncio
async def test_handler_skips_missing_from_user():
    message = _make_message()
    message.from_user = None
    with patch(
        "bot.handlers.smart.LLMIntentRouter.route", new_callable=AsyncMock
    ) as mock_route:
        await smart_message_handler(message, state=None)
    mock_route.assert_not_awaited()
    message.answer.assert_not_awaited()


@pytest.mark.asyncio
async def test_handler_skips_missing_text():
    message = _make_message()
    message.text = None
    with patch(
        "bot.handlers.smart.IntentExecutor.execute", new_callable=AsyncMock
    ) as mock_exec:
        await smart_message_handler(message, state=None)
    mock_exec.assert_not_awaited()
    message.answer.assert_not_awaited()


@pytest.mark.asyncio
async def test_handler_clears_state_when_provided():
    message = _make_message()
    state = MagicMock()
    state.clear = AsyncMock()
    with patch(
        "bot.handlers.smart.LLMIntentRouter.route", new_callable=AsyncMock
    ) as mock_route, patch(
        "bot.handlers.smart.IntentExecutor.execute", new_callable=AsyncMock
    ) as mock_exec:
        mock_route.return_value = MagicMock()
        mock_exec.return_value = MagicMock(text="ok", success=True, reply_markup=None)
        await smart_message_handler(message, state=state)
    state.clear.assert_awaited_once()


@pytest.mark.asyncio
async def test_handler_calls_intent_pipeline_and_sends_answer():
    message = _make_message("  remind me to test  ")
    intent = MagicMock()
    result = MagicMock()
    result.text = "done"
    result.success = True
    result.reply_markup = None
    with patch(
        "bot.handlers.smart.LLMIntentRouter.route", new_callable=AsyncMock, return_value=intent
    ) as mock_route, patch(
        "bot.handlers.smart.IntentExecutor.execute", new_callable=AsyncMock, return_value=result
    ) as mock_exec:
        await smart_message_handler(message, state=None)
    mock_route.assert_awaited_once_with(user_id=42, message_text="remind me to test")
    mock_exec.assert_awaited_once_with(
        user_id=42, message_text="remind me to test", intent_result=intent
    )
    message.answer.assert_awaited_once_with("done", reply_markup=command_keyboard)


@pytest.mark.asyncio
async def test_handler_uses_tool_reply_markup():
    message = _make_message()
    custom_markup = MagicMock()
    result = MagicMock(text="ok", success=True, reply_markup=custom_markup)
    with patch(
        "bot.handlers.smart.LLMIntentRouter.route", new_callable=AsyncMock
    ), patch(
        "bot.handlers.smart.IntentExecutor.execute", new_callable=AsyncMock, return_value=result
    ):
        await smart_message_handler(message, state=None)
    message.answer.assert_awaited_once_with("ok", reply_markup=custom_markup)


@pytest.mark.asyncio
async def test_handler_skips_sending_when_success_and_empty_text():
    message = _make_message()
    result = MagicMock(text="", success=True, reply_markup=None)
    with patch(
        "bot.handlers.smart.LLMIntentRouter.route", new_callable=AsyncMock
    ), patch(
        "bot.handlers.smart.IntentExecutor.execute", new_callable=AsyncMock, return_value=result
    ):
        await smart_message_handler(message, state=None)
    message.answer.assert_not_awaited()


@pytest.mark.asyncio
async def test_handler_sends_error_on_exception():
    message = _make_message()
    with patch(
        "bot.handlers.smart.LLMIntentRouter.route",
        new_callable=AsyncMock,
        side_effect=RuntimeError("boom"),
    ):
        await smart_message_handler(message, state=None)
    message.answer.assert_awaited_once()
    call_args = message.answer.await_args
    assert "⚠️" in call_args.args[0]
    assert call_args.kwargs.get("reply_markup") is command_keyboard


@pytest.mark.asyncio
async def test_handler_sends_failed_result_text():
    message = _make_message()
    result = MagicMock(text="не удалось", success=False, reply_markup=None)
    with patch(
        "bot.handlers.smart.LLMIntentRouter.route", new_callable=AsyncMock
    ), patch(
        "bot.handlers.smart.IntentExecutor.execute", new_callable=AsyncMock, return_value=result
    ):
        await smart_message_handler(message, state=None)
    message.answer.assert_awaited_once_with("не удалось", reply_markup=command_keyboard)


@pytest.mark.asyncio
async def test_handler_error_does_not_call_executor():
    message = _make_message()
    with patch(
        "bot.handlers.smart.LLMIntentRouter.route",
        new_callable=AsyncMock,
        side_effect=RuntimeError("boom"),
    ), patch(
        "bot.handlers.smart.IntentExecutor.execute", new_callable=AsyncMock
    ) as mock_exec:
        await smart_message_handler(message, state=None)
    mock_exec.assert_not_awaited()
