import pytest
from unittest.mock import AsyncMock, MagicMock

from bot.intent.executor import IntentExecutor
from bot.intent.schemas import IntentArgs, IntentResult, ToolContext, ToolResult


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

        mock_tool = AsyncMock()
        mock_tool.execute.return_value = expected
        registry = MagicMock()
        registry.get.return_value = mock_tool

        executor = IntentExecutor(registry=registry)
        tool_result = await executor.execute(
            user_id=1,
            message_text="remind me",
            intent_result=intent_result,
        )

        registry.get.assert_called_once_with("remind")
        mock_tool.execute.assert_awaited_once()
        assert tool_result.text == "done"

        context = mock_tool.execute.call_args[0][0]
        assert isinstance(context, ToolContext)
        assert context.user_id == 1
        assert context.message_text == "remind me"
        assert context.args.content == "test"
        assert context.intent_result is intent_result

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

        assert "Не уверен" in tool_result.text
        assert tool_result.success is True
        assert "reason" in tool_result.extra
        assert tool_result.extra["reason"]
        registry.get.assert_not_called()

    @pytest.mark.asyncio
    async def test_unknown_tool_routes_to_chat_fallback(self):
        intent_result = IntentResult(
            intent="news",
            tool="news",
            args=IntentArgs(),
            confidence=0.95,
        )
        executor = IntentExecutor()
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

        assert "Не уверен" in tool_result.text
        assert "missing required arg" in tool_result.extra["reason"]
        registry.get.assert_not_called()

    def test_executor_uses_injected_registry(self):
        registry = MagicMock()
        executor = IntentExecutor(registry=registry)
        assert executor.registry is registry
