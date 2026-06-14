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

    def test_tools_returns_copy(self):
        registry = ToolRegistry()
        tools_copy = registry.tools
        tools_copy["new"] = ChatTool()
        assert "new" not in registry.tools


class TestRemindTool:
    @pytest.mark.asyncio
    async def test_remind_tool_calls_service_and_returns_success(self):
        tool = RemindTool()
        ctx = ToolContext(
            user_id=1,
            message_text="напомни через 5 минут позвонить",
            args=IntentArgs(content="позвонить"),
            intent_result=IntentResult(intent="create_reminder", tool="remind", confidence=0.95),
        )
        with patch("bot.intent.tools.remind._process_remind") as mock_process:
            result = await tool.execute(ctx)
        assert result.success is True
        assert result.text == "reminder_created"
        mock_process.assert_awaited_once_with(user_id=1, text="позвонить", action="notify")

    @pytest.mark.asyncio
    async def test_remind_tool_falls_back_to_message_text(self):
        tool = RemindTool()
        ctx = ToolContext(
            user_id=2,
            message_text="напомни завтра в 9:00 отчёт",
            args=IntentArgs(),
            intent_result=IntentResult(intent="create_reminder", tool="remind", confidence=0.95),
        )
        with patch("bot.intent.tools.remind._process_remind") as mock_process:
            result = await tool.execute(ctx)
        assert result.success is True
        mock_process.assert_awaited_once_with(user_id=2, text="напомни завтра в 9:00 отчёт", action="notify")

    @pytest.mark.asyncio
    async def test_remind_tool_returns_failure_when_content_missing(self):
        tool = RemindTool()
        ctx = ToolContext(
            user_id=1,
            message_text="",
            args=IntentArgs(),
            intent_result=IntentResult(intent="create_reminder", tool="remind", confidence=0.95),
        )
        with patch("bot.intent.tools.remind._process_remind") as mock_process:
            result = await tool.execute(ctx)
        assert result.success is False
        assert "текст напоминания" in result.text
        mock_process.assert_not_awaited()


class TestTaskTool:
    @pytest.mark.asyncio
    async def test_task_tool_calls_service_and_returns_success(self):
        tool = TaskTool()
        ctx = ToolContext(
            user_id=1,
            message_text="задача через час погода в Москве",
            args=IntentArgs(content="погода в Москве"),
            intent_result=IntentResult(intent="create_task", tool="task", confidence=0.95),
        )
        with patch("bot.intent.tools.task._process_task_from_text") as mock_process:
            result = await tool.execute(ctx)
        assert result.success is True
        assert result.text == "task_created"
        mock_process.assert_awaited_once_with(user_id=1, text="погода в Москве")

    @pytest.mark.asyncio
    async def test_task_tool_returns_failure_when_content_missing(self):
        tool = TaskTool()
        ctx = ToolContext(
            user_id=1,
            message_text="",
            args=IntentArgs(),
            intent_result=IntentResult(intent="create_task", tool="task", confidence=0.95),
        )
        with patch("bot.intent.tools.task._process_task_from_text") as mock_process:
            result = await tool.execute(ctx)
        assert result.success is False
        assert "текст задачи" in result.text
        mock_process.assert_not_awaited()
