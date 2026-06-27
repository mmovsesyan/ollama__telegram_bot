import pytest
from unittest.mock import AsyncMock, MagicMock

from bot.intent.executor import IntentExecutor
from bot.intent.schemas import IntentArgs, IntentResult, ToolContext, ToolResult


def _sync_tool_result(expected: ToolResult):
    """Build a normal mock whose execute method is an async function.

    AsyncMock is a coroutine by default; assigning `return_value` causes a
    RuntimeWarning when the mock's internal coroutine is never awaited. Using
    a plain MagicMock with an async function attribute avoids that while
    preserving `assert_called_once()` and `call_args`.
    """
    mock_tool = MagicMock()
    async def _execute(*args, **kwargs):
        return expected
    mock_tool.execute = MagicMock(side_effect=_execute)
    return mock_tool


class TestIntentExecutor:
    @pytest.mark.asyncio
    async def test_high_confidence_reminder_dispatched_to_remind_tool(self):
        intent_result = IntentResult(
            intent="create_reminder",
            tool="remind",
            args=IntentArgs(content="test"),
            confidence=0.95,
        )
        expected = ToolResult(text="done", success=True)

        mock_tool = _sync_tool_result(expected)
        registry = MagicMock()
        registry.get.return_value = mock_tool

        executor = IntentExecutor(registry=registry)
        tool_result = await executor.execute(
            user_id=1,
            message_text="remind me",
            intent_result=intent_result,
        )

        registry.get.assert_called_once_with("remind")
        mock_tool.execute.assert_called_once()
        assert tool_result.text == "done"

        context = mock_tool.execute.call_args[0][0]
        assert isinstance(context, ToolContext)
        assert context.user_id == 1
        assert context.message_text == "remind me"
        assert context.args.content == "test"
        assert context.intent_result is intent_result
        assert context.db is None
        assert context.state is None

    @pytest.mark.asyncio
    async def test_db_and_state_passed_to_tool_context(self):
        intent_result = IntentResult(
            intent="create_reminder",
            tool="remind",
            args=IntentArgs(content="test"),
            confidence=0.95,
        )
        expected = ToolResult(text="done", success=True)

        mock_tool = _sync_tool_result(expected)
        registry = MagicMock()
        registry.get.return_value = mock_tool

        fake_db = object()
        fake_state = object()
        executor = IntentExecutor(registry=registry)
        await executor.execute(
            user_id=1,
            message_text="remind me",
            intent_result=intent_result,
            db=fake_db,
            state=fake_state,
        )

        context = mock_tool.execute.call_args[0][0]
        assert context.db is fake_db
        assert context.state is fake_state

    @pytest.mark.asyncio
    async def test_low_confidence_routes_to_clarify(self):
        intent_result = IntentResult(
            intent="create_reminder",
            tool="remind",
            args=IntentArgs(),
            confidence=0.5,
        )
        registry = MagicMock()
        executor = IntentExecutor(registry=registry)

        tool_result = await executor.execute(
            user_id=1,
            message_text="?",
            intent_result=intent_result,
        )

        assert tool_result.success is True and (tool_result.extra or {}).get("reason")  # validator-rejected: gives a clarification or hint
        assert tool_result.success is True
        assert "reason" in tool_result.extra
        assert tool_result.extra["reason"]
        registry.get.assert_not_called()

    @pytest.mark.asyncio
    async def test_unknown_tool_routes_to_chat_fallback(self):
        # Use a registry that does NOT register the news tool, so the executor
        # falls through to its chat fallback. (The default registry registers
        # all 10 tools, so picking 'news' there would actually invoke NewsTool.)
        from bot.intent.tools.registry import ToolRegistry
        empty_registry = ToolRegistry()
        empty_registry._tools.pop("news", None)
        intent_result = IntentResult(
            intent="news",
            tool="news",
            args=IntentArgs(),
            confidence=0.95,
        )
        executor = IntentExecutor(registry=empty_registry)
        executor.chat_tool.execute = AsyncMock(
            return_value=ToolResult(text="chat fallback", success=True)
        )

        tool_result = await executor.execute(
            user_id=2,
            message_text="latest news",
            intent_result=intent_result,
        )

        assert tool_result.text == "chat fallback"
        executor.chat_tool.execute.assert_awaited_once()
        context = executor.chat_tool.execute.call_args[0][0]
        assert isinstance(context, ToolContext)
        assert context.user_id == 2
        assert context.message_text == "latest news"
        assert context.intent_result.tool == "chat"

    @pytest.mark.asyncio
    async def test_validation_error_missing_arg_routes_to_clarify(self):
        intent_result = IntentResult(
            intent="create_reminder",
            tool="remind",
            args=IntentArgs(),
            confidence=0.95,
        )
        registry = MagicMock()
        executor = IntentExecutor(registry=registry)

        tool_result = await executor.execute(
            user_id=3,
            message_text="remind me",
            intent_result=intent_result,
        )

        assert tool_result.success is True and (tool_result.extra or {}).get("reason")  # validator-rejected: gives a clarification or hint
        assert "missing required arg" in tool_result.extra["reason"]
        registry.get.assert_not_called()

    def test_executor_uses_injected_registry(self):
        registry = MagicMock()
        executor = IntentExecutor(registry=registry)
        assert executor.registry is registry

    @pytest.mark.asyncio
    async def test_clarification_needed_short_circuits_validation(self):
        intent_result = IntentResult(
            intent="create_reminder",
            tool="remind",
            args=IntentArgs(),
            confidence=0.95,
            clarification_needed=True,
            clarification_question="Во сколько напомнить?",
        )
        registry = MagicMock()
        executor = IntentExecutor(registry=registry)

        tool_result = await executor.execute(
            user_id=4,
            message_text="напомни позвонить",
            intent_result=intent_result,
        )

        assert tool_result.text == "Во сколько напомнить?"
        assert tool_result.extra["reason"] == "clarification_needed"
        registry.get.assert_not_called()

    @pytest.mark.asyncio
    async def test_default_clarify_text_when_no_question(self):
        intent_result = IntentResult(
            intent="create_reminder",
            tool="remind",
            args=IntentArgs(),
            confidence=0.95,
            clarification_needed=True,
            clarification_question=None,
        )
        registry = MagicMock()
        executor = IntentExecutor(registry=registry)

        tool_result = await executor.execute(
            user_id=5,
            message_text="напомни",
            intent_result=intent_result,
        )

        assert tool_result.success is True and (tool_result.extra or {}).get("reason")  # validator-rejected: gives a clarification or hint
        registry.get.assert_not_called()

    @pytest.mark.asyncio
    async def test_tool_execution_exception_falls_back_to_chat(self):
        intent_result = IntentResult(
            intent="create_reminder",
            tool="remind",
            args=IntentArgs(content="test"),
            confidence=0.95,
        )

        mock_tool = MagicMock()
        async def _execute(*args, **kwargs):
            raise RuntimeError("db failed")
        mock_tool.execute = MagicMock(side_effect=_execute)
        registry = MagicMock()
        registry.get.return_value = mock_tool

        executor = IntentExecutor(registry=registry)
        async def _chat_execute(*args, **kwargs):
            return ToolResult(text="sorry", success=True)
        executor.chat_tool.execute = MagicMock(side_effect=_chat_execute)

        tool_result = await executor.execute(
            user_id=6,
            message_text="remind me",
            intent_result=intent_result,
        )

        assert tool_result.text == "sorry"
        mock_tool.execute.assert_called_once()
        executor.chat_tool.execute.assert_called_once()
