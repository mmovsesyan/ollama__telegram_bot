import sys
from types import ModuleType

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

# bot.bot raises at import if TELEGRAM_TOKEN is missing; provide a fake module
# before importing the completion router used by _persist_exchange.
if "bot.bot" not in sys.modules:
    _fake_bot_module = ModuleType("bot.bot")
    _fake_bot_module.bot = MagicMock()
    sys.modules["bot.bot"] = _fake_bot_module

from bot.handlers.smart import _persist_exchange, smart_message_handler
from bot.keyboards.reply import command_keyboard
from bot.routers import completion as completion_module


def _make_message(text: str = "hello world") -> MagicMock:
    message = MagicMock()
    message.from_user = MagicMock(id=42)
    message.text = text
    message.answer = AsyncMock()
    message.bot = MagicMock()
    message.bot.send_chat_action = AsyncMock()
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
    message.bot.send_chat_action.assert_not_awaited()


@pytest.mark.asyncio
async def test_handler_sends_typing_action_early():
    message = _make_message()
    with patch(
        "bot.handlers.smart.LLMIntentRouter.route", new_callable=AsyncMock
    ) as mock_route, patch(
        "bot.handlers.smart.IntentExecutor.execute", new_callable=AsyncMock
    ) as mock_exec:
        mock_route.return_value = MagicMock()
        mock_exec.return_value = MagicMock(text="ok", success=True, reply_markup=None)
        await smart_message_handler(message, state=None)
    message.bot.send_chat_action.assert_awaited_once_with(
        chat_id=42, action="typing"
    )


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
    message.bot.send_chat_action.assert_not_awaited()


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
        user_id=42,
        message_text="remind me to test",
        intent_result=intent,
        db=None,
        state=None,
        message=message,
    )
    message.answer.assert_awaited_once_with("done", reply_markup=command_keyboard)


@pytest.mark.asyncio
async def test_handler_ignores_slash_commands():
    message = _make_message("/help")
    with patch(
        "bot.handlers.smart.LLMIntentRouter.route", new_callable=AsyncMock
    ) as mock_route, patch(
        "bot.handlers.smart.IntentExecutor.execute", new_callable=AsyncMock
    ) as mock_exec:
        await smart_message_handler(message, state=None)
    mock_route.assert_not_awaited()
    mock_exec.assert_not_awaited()
    message.answer.assert_not_awaited()


@pytest.mark.asyncio
async def test_handler_ignores_reply_buttons():
    message = _make_message("❓ Помощь")
    with patch(
        "bot.handlers.smart.LLMIntentRouter.route", new_callable=AsyncMock
    ) as mock_route, patch(
        "bot.handlers.smart.IntentExecutor.execute", new_callable=AsyncMock
    ) as mock_exec:
        await smart_message_handler(message, state=None)
    mock_route.assert_not_awaited()
    mock_exec.assert_not_awaited()
    message.answer.assert_not_awaited()


@pytest.mark.asyncio
async def test_handler_blocks_unauthorized_user():
    message = _make_message("hello")
    message.from_user = MagicMock(id=999)
    with patch(
        "bot.handlers.smart.is_allowed", return_value=False
    ), patch(
        "bot.handlers.smart.LLMIntentRouter.route", new_callable=AsyncMock
    ) as mock_route:
        await smart_message_handler(message, state=None)
    mock_route.assert_not_awaited()
    message.answer.assert_not_awaited()


@pytest.mark.asyncio
async def test_handler_passes_db_attribute_to_executor():
    message = _make_message("hello")
    fake_db = object()
    import bot.handlers.smart as smart_module
    smart_module.db = fake_db
    intent = MagicMock()
    result = MagicMock()
    result.text = "done"
    result.success = True
    result.reply_markup = None
    try:
        with patch(
            "bot.handlers.smart.LLMIntentRouter.route", new_callable=AsyncMock, return_value=intent
        ), patch(
            "bot.handlers.smart.IntentExecutor.execute", new_callable=AsyncMock, return_value=result
        ) as mock_exec:
            await smart_message_handler(message, state=None)
        assert mock_exec.await_args.kwargs["db"] is fake_db
    finally:
        smart_module.db = None  # restore module state


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


@pytest.mark.filterwarnings("ignore:coroutine 'AsyncMockMixin._execute_mock_call' was never awaited:RuntimeWarning")
class TestPersistExchange:
    @pytest.fixture(autouse=True)
    def reset_state(self, monkeypatch):
        import bot.handlers.smart as smart_module
        smart_module.db = None
        completion_module.chats.clear()
        completion_module.db = None
        yield
        smart_module.db = None
        completion_module.chats.clear()
        completion_module.db = None

    def _patch_completion(self, chat=None):
        completion_module.chats = {1: chat} if chat else {}
        completion_module._create_chat = MagicMock()
        completion_module.refresh_system_prompt = MagicMock()

    @pytest.mark.asyncio
    async def test_persist_exits_when_db_none(self):
        import bot.handlers.smart as smart_module
        smart_module.db = None
        self._patch_completion()
        _persist_exchange(1, "hi", "ok")
        completion_module._create_chat.assert_not_called()

    @pytest.mark.asyncio
    async def test_persist_saves_messages_and_extracts_facts(self):
        import bot.handlers.smart as smart_module
        fake_db = MagicMock()
        fake_db.save_message = MagicMock()
        smart_module.db = fake_db

        chat = MagicMock()
        chat.session_id = 10
        chat.selected_model = "model"
        chat.ollama_chat.messages = []

        self._patch_completion(chat)

        with patch("bot.services.kb_extract.extract_facts_from_exchange", new=AsyncMock()) as mock_extract:
            with patch("asyncio.create_task") as mock_create_task:
                _persist_exchange(1, "user text", "assistant text", save_messages=True)

        fake_db.save_message.assert_any_call(1, 10, "user", "user text", "model")
        fake_db.save_message.assert_any_call(1, 10, "assistant", "assistant text", "model")
        mock_extract.assert_called_once_with(fake_db, 1, "user text", "assistant text")
        mock_create_task.assert_called_once()
        completion_module.refresh_system_prompt.assert_called_once_with(1)

    @pytest.mark.asyncio
    async def test_persist_skips_saving_for_chat_path(self):
        import bot.handlers.smart as smart_module
        fake_db = MagicMock()
        smart_module.db = fake_db

        chat = MagicMock()
        chat.session_id = 10
        chat.selected_model = "model"
        chat.ollama_chat.messages = []

        self._patch_completion(chat)

        with patch("bot.services.kb_extract.extract_facts_from_exchange", new=AsyncMock()):
            with patch("asyncio.create_task"):
                _persist_exchange(1, "hi", "", save_messages=False)

        fake_db.save_message.assert_not_called()
        completion_module.refresh_system_prompt.assert_called_once_with(1)

    @pytest.mark.asyncio
    async def test_persist_uses_chat_assistant_when_text_empty(self):
        import bot.handlers.smart as smart_module
        fake_db = MagicMock()
        smart_module.db = fake_db

        chat = MagicMock()
        chat.session_id = 10
        chat.selected_model = "model"
        chat.ollama_chat.messages = [
            MagicMock(role="user", content="hi"),
            MagicMock(role="assistant", content="streamed reply"),
        ]

        self._patch_completion(chat)

        with patch("bot.services.kb_extract.extract_facts_from_exchange", new=AsyncMock()) as mock_extract:
            with patch("asyncio.create_task"):
                _persist_exchange(1, "hi", "", save_messages=False)

        mock_extract.assert_called_once_with(fake_db, 1, "hi", "streamed reply")
