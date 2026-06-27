import sys
from types import ModuleType

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

# bot.bot raises at import if TELEGRAM_TOKEN is missing.
if "bot.bot" not in sys.modules:
    _fake_bot_module = ModuleType("bot.bot")
    _fake_bot_module.bot = MagicMock()
    sys.modules["bot.bot"] = _fake_bot_module

from bot.intent.schemas import IntentArgs, IntentResult, ToolContext
from bot.intent.tools.chat import ChatTool
from bot.intent.tools.remind import RemindTool
from bot.intent.tools.task import TaskTool
from bot.intent.tools.registry import ToolRegistry
from bot.intent.tools.search import (
    NewsTool,
    SearchTool,
    _clean_snippet,
    _format_results,
    _format_search_item,
)
from bot.intent.tools.persistence import MemoryTool, NoteTool
from bot.routers import completion as completion_module


class TestChatTool:
    @pytest.mark.asyncio
    async def test_chat_tool_returns_text(self):
        # ChatTool delegates to bot.routers.completion.generate when a Message
        # is attached, and falls back to a non-streaming completion otherwise.
        # Test the fallback path: no message attached, mock generate_chat_completion
        # at its actual import site (bot.ollama).
        tool = ChatTool()
        ctx = ToolContext(
            user_id=1,
            message_text="hello",
            args=IntentArgs(content="hello"),
            intent_result=IntentResult(intent="chat", tool="chat", confidence=0.95),
        )
        async def _fake_gen(*args, **kwargs):
            yield (False, type("C", (), {"message": type("M", (), {"content": "Hi there"})})())

        with patch("bot.ollama.generate_chat_completion", side_effect=_fake_gen):
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
    async def test_remind_tool_calls_service_with_full_message(self):
        # Tool always passes the full user message, not args.content, so the
        # downstream parser sees time tokens like "через 5 минут".
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
        assert result.text == ""
        mock_process.assert_awaited_once_with(
            user_id=1, text="напомни через 5 минут позвонить", action="notify"
        )

    @pytest.mark.asyncio
    async def test_remind_tool_uses_message_text_when_args_empty(self):
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
        mock_process.assert_awaited_once_with(
            user_id=2, text="напомни завтра в 9:00 отчёт", action="notify"
        )

    @pytest.mark.asyncio
    async def test_remind_tool_returns_failure_when_message_empty(self):
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
    async def test_task_tool_calls_service_with_full_message(self):
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
        assert result.text == ""
        mock_process.assert_awaited_once_with(
            user_id=1, text="задача через час погода в Москве"
        )

    @pytest.mark.asyncio
    async def test_task_tool_returns_failure_when_message_empty(self):
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


class TestSearchFormatting:
    def test_clean_snippet_collapses_and_truncates(self):
        raw = "Line\none\ntwo " + "x" * 300
        out = _clean_snippet(raw, max_len=50)
        assert "\n" not in out
        assert out.endswith("...")

    def test_format_search_item_full(self):
        item = {
            "title": "Title",
            "url": "https://example.com/page",
            "body": "Snippet text here",
        }
        text = _format_search_item(item, 1)
        assert "1. Title" in text
        assert "example.com" in text
        assert "Snippet text here" in text
        assert "https://example.com/page" in text

    def test_format_search_item_falls_back_to_href_and_content(self):
        item = {"title": "T", "href": "https://x.com", "content": "body", "source": "x.com"}
        text = _format_search_item(item, 2)
        assert "https://x.com" in text
        assert "x.com" in text

    def test_format_results_includes_header_and_caps_at_five(self):
        items = [{"title": f"R{i}", "url": f"https://r{i}.com", "body": "b"} for i in range(10)]
        text = _format_results("query", items, "🔍")
        assert "🔍 query" in text
        assert "5. R4" in text
        assert "6. R5" not in text

    def test_format_results_empty(self):
        assert _format_results("q", [], "🔍") == ""


class TestSearchAndNewsTools:
    @pytest.mark.asyncio
    async def test_search_tool_formats_results(self):
        async def fake_search(query, max_results=5):
            return (
                {
                    "results": [
                        {"title": "R", "url": "https://r.com", "body": "body"}
                    ]
                },
                None,
            )

        tool = SearchTool()
        ctx = ToolContext(
            user_id=1,
            message_text="find x",
            args=IntentArgs(query="find x"),
            intent_result=IntentResult(intent="search", tool="search", confidence=0.9),
        )
        with patch("bot.routers.common.ollama_web_search", side_effect=fake_search):
            result = await tool.execute(ctx)
        assert result.success is True
        assert "R" in result.text
        assert "https://r.com" in result.text

    @pytest.mark.asyncio
    async def test_search_tool_returns_error_when_search_fails(self):
        tool = SearchTool()
        ctx = ToolContext(
            user_id=1,
            message_text="q",
            args=IntentArgs(query="q"),
            intent_result=IntentResult(intent="search", tool="search", confidence=0.9),
        )
        with patch("bot.routers.common.ollama_web_search", return_value=(None, "timeout")):
            result = await tool.execute(ctx)
        assert result.success is False
        assert "timeout" in result.text

    @pytest.mark.asyncio
    async def test_news_tool_returns_rendered_news(self):
        tool = NewsTool()
        ctx = ToolContext(
            user_id=1,
            message_text="новости",
            args=IntentArgs(),
            intent_result=IntentResult(intent="news", tool="news", confidence=0.9),
        )

        async def fake_get_fresh_news(user_id, topic=None, limit=5, hours=48):
            return "📰 Новости:\n\n1. Title\n   https://x.com", [], "rss"

        with patch("bot.services.rss_news.get_fresh_news", side_effect=fake_get_fresh_news):
            result = await tool.execute(ctx)
        assert result.success is True
        assert "Title" in result.text
        assert "(источник: rss)" in result.text

    @pytest.mark.asyncio
    async def test_news_tool_returns_not_found_when_empty(self):
        tool = NewsTool()
        ctx = ToolContext(
            user_id=1,
            message_text="новости Tesla",
            args=IntentArgs(query="Tesla"),
            intent_result=IntentResult(intent="news", tool="news", confidence=0.9),
        )

        async def fake_get_fresh_news(user_id, topic=None, limit=5, hours=48):
            return "", [], "rss"

        with patch("bot.services.rss_news.get_fresh_news", side_effect=fake_get_fresh_news):
            result = await tool.execute(ctx)
        assert "ничего не найдено" in result.text


class TestPersistenceTools:
    @pytest.fixture(autouse=True)
    def reset_completion(self):
        completion_module.refresh_system_prompt = completion_module.refresh_system_prompt
        # We will replace the function with a MagicMock in each test, so stash
        # nothing; the module is reloaded between sessions.
        yield
        completion_module.refresh_system_prompt = completion_module.refresh_system_prompt

    def _fake_db(self):
        db = MagicMock()
        db.add_note = MagicMock()
        db.add_memory = MagicMock(return_value=42)
        return db

    @pytest.mark.asyncio
    async def test_note_tool_saves_and_refreshes(self, monkeypatch):
        db = self._fake_db()
        monkeypatch.setattr(completion_module, "refresh_system_prompt", MagicMock())

        tool = NoteTool()
        ctx = ToolContext(
            user_id=1,
            message_text="заметка: купить хлеб",
            args=IntentArgs(content="купить хлеб"),
            intent_result=IntentResult(intent="add_note", tool="note", confidence=0.9),
            db=db,
        )
        result = await tool.execute(ctx)
        db.add_note.assert_called_once_with(1, "купить хлеб")
        completion_module.refresh_system_prompt.assert_called_once_with(1)
        assert result.success is True

    @pytest.mark.asyncio
    async def test_note_tool_requires_content(self):
        tool = NoteTool()
        ctx = ToolContext(
            user_id=1,
            message_text="  ",
            args=IntentArgs(content=""),
            intent_result=IntentResult(intent="add_note", tool="note", confidence=0.9),
            db=self._fake_db(),
        )
        result = await tool.execute(ctx)
        assert result.success is False

    @pytest.mark.asyncio
    async def test_memory_tool_classifies_saves_and_refreshes(self, monkeypatch):
        db = self._fake_db()
        monkeypatch.setattr(completion_module, "refresh_system_prompt", MagicMock())

        tool = MemoryTool()
        ctx = ToolContext(
            user_id=2,
            message_text="запомни, я люблю Python",
            args=IntentArgs(content="я люблю Python"),
            intent_result=IntentResult(intent="add_memory", tool="memory", confidence=0.9),
            db=db,
        )
        with patch("bot.routers.common._classify_memory", new=AsyncMock(return_value="preference")):
            result = await tool.execute(ctx)

        db.add_memory.assert_called_once_with(2, "preference", "я люблю Python")
        completion_module.refresh_system_prompt.assert_called_once_with(2)
        assert "Python" in result.text
        assert result.success is True

    @pytest.mark.asyncio
    async def test_memory_tool_requires_content(self):
        tool = MemoryTool()
        ctx = ToolContext(
            user_id=1,
            message_text="",
            args=IntentArgs(content=""),
            intent_result=IntentResult(intent="add_memory", tool="memory", confidence=0.9),
            db=self._fake_db(),
        )
        result = await tool.execute(ctx)
        assert result.success is False
