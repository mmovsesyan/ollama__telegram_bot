import pytest
from unittest.mock import patch
from bot.intent.schemas import IntentArgs, IntentResult, ToolContext
from bot.intent.tools.chat import ChatTool
from bot.intent.tools.remind import RemindTool
from bot.intent.tools.task import TaskTool
from bot.intent.tools.registry import ToolRegistry


class TestChatTool:
    @pytest.mark.asyncio
    async def test_chat_tool_returns_text(self):
        tool = ChatTool()
        ctx = ToolContext(
            user_id=1,
            message_text="hello",
            args=IntentArgs(content="hello"),
            intent_result=IntentResult(intent="chat", tool="chat", confidence=0.95),
        )
        async def _fake_gen(*args, **kwargs):
            yield (False, type("C", (), {"message": type("M", (), {"content": "Hi there"})})())

        with patch("bot.intent.tools.chat.generate_chat_completion", side_effect=_fake_gen) as mock_gen:
            result = await tool.execute(ctx)
        assert result.success is True
        assert "Hi there" in result.text


class TestRegistry:
    def test_registry_has_expected_tools(self):
        registry = ToolRegistry()
        assert "chat" in registry.tools
        assert "remind" in registry.tools
        assert "task" in registry.tools

    def test_get_tool(self):
        registry = ToolRegistry()
        assert isinstance(registry.get("chat"), ChatTool)
