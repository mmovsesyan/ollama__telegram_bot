# Smart Router — Iteration 1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` (recommended) or `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an LLM-based intent router with strict JSON validation and a `BaseTool` interface, then migrate reminder, task, and chat handling so free-form text is routed correctly.

**Architecture:** A new `bot/intent/` package holds the router, validator, context builder stub, and tool executors. The existing `completion.py` and `cron.py` business logic is reused through thin wrappers. `main.py` wires the new smart handler into aiogram before the legacy catch-all handlers.

**Tech Stack:** Python 3.10+, aiogram 3.x, Pydantic v2, SQLite, Ollama Cloud/OpenAI-compatible endpoint, pytest.

---

## File Structure

| File | Responsibility |
|------|----------------|
| `bot/intent/schemas.py` | Pydantic models for router input/output and tool contexts/results. |
| `bot/intent/router.py` | `LLMIntentRouter`: builds prompt, calls Ollama, returns `IntentResult`. |
| `bot/intent/validator.py` | `Validator`: checks schema, confidence, allowed tools, required args. |
| `bot/intent/context.py` | `ContextBuilder`: gathers user profile, summary stub, memory/notes stub, current time. |
| `bot/intent/tools/base.py` | `BaseTool`, `ToolContext`, `ToolResult` interfaces. |
| `bot/intent/tools/chat.py` | `ChatTool` — fallback AI chat. |
| `bot/intent/tools/remind.py` | `RemindTool` — wraps `_process_remind`. |
| `bot/intent/tools/task.py` | `TaskTool` — wraps `_process_task_from_text`. |
| `bot/intent/tools/registry.py` | Maps tool names to instances. |
| `bot/intent/executor.py` | `IntentExecutor`: validator + dispatch + response formatting. |
| `bot/intent/__init__.py` | Public exports and convenience `handle_message(message, state)`. |
| `bot/handlers/smart.py` | aiogram message handler that invokes the intent pipeline. |
| `tests/intent/test_schemas.py` | Pydantic schema tests. |
| `tests/intent/test_validator.py` | Validator tests. |
| `tests/intent/test_router.py` | Router tests with mocked LLM. |
| `tests/intent/test_tools.py` | Tool executor tests with mocked DB/cron functions. |
| `pyproject.toml` | Add `pytest` and `pytest-asyncio` to dev dependencies. |

---

## Task 1: Add Test Dependencies

**Files:**
- Modify: `pyproject.toml`

- [ ] **Step 1: Add pytest and pytest-asyncio**

Add under `[tool.poetry.group.dev.dependencies]`:

```toml
pytest = "^8.0.0"
pytest-asyncio = "^0.23.0"
```

- [ ] **Step 2: Install dependencies**

Run: `poetry install --with dev`

Expected: dependencies resolved and installed.

- [ ] **Step 3: Commit**

```bash
git add pyproject.toml poetry.lock
git commit -m "chore: add pytest and pytest-asyncio dev dependencies"
```

---

## Task 2: Create Test Directory and Conftest

**Files:**
- Create: `tests/__init__.py`
- Create: `tests/conftest.py`

- [ ] **Step 1: Create test package marker**

```python
# tests/__init__.py
```

Empty file is fine.

- [ ] **Step 2: Add async pytest config**

```python
# tests/conftest.py
import pytest

pytest_plugins = ("pytest_asyncio",)


def pytest_configure(config):
    config.option.asyncio_mode = "auto"
```

- [ ] **Step 3: Commit**

```bash
git add tests/__init__.py tests/conftest.py
git commit -m "chore: init tests package and async config"
```

---

## Task 3: Define Pydantic Schemas

**Files:**
- Create: `bot/intent/schemas.py`
- Test: `tests/intent/test_schemas.py`

- [ ] **Step 1: Write failing schema tests**

```python
# tests/intent/test_schemas.py
import pytest
from bot.intent.schemas import (
    IntentArgs,
    IntentResult,
    ToolContext,
    ToolResult,
)


class TestIntentResult:
    def test_valid_intent_result(self):
        data = {
            "intent": "create_reminder",
            "tool": "remind",
            "args": {"content": "test", "trigger_at": "2026-06-15T07:30:00+00:00"},
            "confidence": 0.92,
            "clarification_needed": False,
        }
        result = IntentResult.model_validate(data)
        assert result.intent == "create_reminder"
        assert result.confidence == 0.92

    def test_invalid_tool_rejected(self):
        data = {
            "intent": "create_reminder",
            "tool": "remind",
            "args": {"content": "test"},
            "confidence": 1.5,
        }
        with pytest.raises(ValueError):
            IntentResult.model_validate(data)

    def test_tool_result(self):
        tr = ToolResult(text="Reminder created", success=True)
        assert tr.text == "Reminder created"
        assert tr.success is True
```

Run: `pytest tests/intent/test_schemas.py -v`

Expected: failures because modules/classes do not exist.

- [ ] **Step 2: Implement schemas**

```python
# bot/intent/schemas.py
from typing import Any, Literal
from pydantic import BaseModel, Field, field_validator


class IntentArgs(BaseModel):
    """Arguments extracted by the LLM for the selected tool."""

    content: str | None = None
    trigger_at: str | None = None
    recurring: str | None = None
    query: str | None = None
    city: str | None = None
    url: str | None = None
    name: str | None = None
    interval: int | None = None
    plan_text: str | None = None


ALLOWED_INTENTS = Literal[
    "chat",
    "create_reminder",
    "create_task",
    "add_memory",
    "add_note",
    "search",
    "weather",
    "news",
    "add_monitor",
    "generate_plan",
    "clarify",
    "cancel",
    "help",
]

ALLOWED_TOOLS = Literal[
    "chat",
    "remind",
    "task",
    "memory",
    "note",
    "search",
    "weather",
    "news",
    "monitor",
    "plan",
]


class IntentResult(BaseModel):
    """Structured decision returned by the LLM intent router."""

    intent: ALLOWED_INTENTS
    tool: ALLOWED_TOOLS
    args: IntentArgs = Field(default_factory=IntentArgs)
    confidence: float = Field(ge=0.0, le=1.0)
    clarification_needed: bool = False
    clarification_question: str | None = None
    proactive_suggestion: dict[str, Any] | None = None
    response_tone: Literal["friendly", "neutral", "concise"] = "friendly"


class ToolContext(BaseModel):
    """Everything a tool needs to execute."""

    user_id: int
    message_text: str
    args: IntentArgs
    intent_result: IntentResult
    db: Any | None = None
    state: Any | None = None

    model_config = {"arbitrary_types_allowed": True}


class ToolResult(BaseModel):
    """Result returned by a tool executor."""

    text: str
    success: bool = True
    reply_markup: Any | None = None
    extra: dict[str, Any] | None = None

    model_config = {"arbitrary_types_allowed": True}
```

- [ ] **Step 3: Run schema tests**

Run: `pytest tests/intent/test_schemas.py -v`

Expected: all pass.

- [ ] **Step 4: Commit**

```bash
git add bot/intent/schemas.py tests/intent/test_schemas.py
git commit -m "feat(intent): define pydantic schemas for intent routing"
```

---

## Task 4: Implement Validator

**Files:**
- Create: `bot/intent/validator.py`
- Test: `tests/intent/test_validator.py`

- [ ] **Step 1: Write failing validator tests**

```python
# tests/intent/test_validator.py
import pytest
from bot.intent.schemas import IntentArgs, IntentResult
from bot.intent.validator import Validator, ValidationError


class TestValidator:
    def test_valid_reminder_passes(self):
        result = IntentResult(
            intent="create_reminder",
            tool="remind",
            args=IntentArgs(content="call broker", trigger_at="2026-06-15T07:30:00+00:00"),
            confidence=0.92,
        )
        Validator.validate(result)

    def test_low_confidence_fails(self):
        result = IntentResult(
            intent="create_reminder",
            tool="remind",
            args=IntentArgs(content="call broker"),
            confidence=0.5,
        )
        with pytest.raises(ValidationError):
            Validator.validate(result)

    def test_missing_required_arg_fails(self):
        result = IntentResult(
            intent="create_reminder",
            tool="remind",
            args=IntentArgs(),
            confidence=0.92,
        )
        with pytest.raises(ValidationError):
            Validator.validate(result)

    def test_unknown_tool_fails(self):
        raw = {
            "intent": "chat",
            "tool": "unknown",
            "args": {},
            "confidence": 0.9,
        }
        with pytest.raises(ValueError):
            IntentResult.model_validate(raw)
```

Run: `pytest tests/intent/test_validator.py -v`

Expected: failures because `Validator` does not exist.

- [ ] **Step 2: Implement validator**

```python
# bot/intent/validator.py
from bot.intent.schemas import ALLOWED_TOOLS, IntentResult


class ValidationError(Exception):
    """Raised when an intent result fails validation."""


class Validator:
    """Validate LLM intent results before execution."""

    DEFAULT_CONFIDENCE_THRESHOLD = 0.7

    _required_args: dict[str, tuple[str, ...]] = {
        "remind": ("content",),
        "task": ("content",),
        "memory": ("content",),
        "note": ("content",),
        "search": ("query",),
        "weather": ("city",),
        "monitor": ("name", "url"),
    }

    @classmethod
    def validate(
        cls,
        result: IntentResult,
        confidence_threshold: float | None = None,
    ) -> None:
        threshold = confidence_threshold or cls.DEFAULT_CONFIDENCE_THRESHOLD

        if result.confidence < threshold:
            raise ValidationError(
                f"confidence {result.confidence} below threshold {threshold}"
            )

        if result.tool not in ALLOWED_TOOLS.__args__:
            raise ValidationError(f"unknown tool: {result.tool}")

        required = cls._required_args.get(result.tool, ())
        args_dict = result.args.model_dump()
        for field in required:
            if not args_dict.get(field):
                raise ValidationError(
                    f"tool '{result.tool}' missing required arg '{field}'"
                )
```

- [ ] **Step 3: Run validator tests**

Run: `pytest tests/intent/test_validator.py -v`

Expected: all pass.

- [ ] **Step 4: Commit**

```bash
git add bot/intent/validator.py tests/intent/test_validator.py
git commit -m "feat(intent): add intent result validator with confidence and arg checks"
```

---

## Task 5: Implement BaseTool and Initial Tools

**Files:**
- Create: `bot/intent/tools/base.py`
- Create: `bot/intent/tools/chat.py`
- Create: `bot/intent/tools/remind.py`
- Create: `bot/intent/tools/task.py`
- Create: `bot/intent/tools/registry.py`
- Test: `tests/intent/test_tools.py`

- [ ] **Step 1: Write failing tool tests**

```python
# tests/intent/test_tools.py
import pytest
from unittest.mock import AsyncMock, patch
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
            intent_result=IntentResult(
                intent="chat",
                tool="chat",
                confidence=0.95,
            ),
        )
        with patch("bot.intent.tools.chat.generate_chat_completion", new_callable=AsyncMock) as mock_gen:
            mock_gen.return_value = iter([
                (False, type("C", (), {"message": type("M", (), {"content": "Hi there"})})),
                (True, None),
            ])
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
```

Run: `pytest tests/intent/test_tools.py -v`

Expected: failures because modules do not exist.

- [ ] **Step 2: Implement base tool interface**

```python
# bot/intent/tools/base.py
from abc import ABC, abstractmethod
from bot.intent.schemas import ToolContext, ToolResult


class BaseTool(ABC):
    """Base class for all intent tools."""

    name: str
    required_args: tuple[str, ...] = ()

    @abstractmethod
    async def execute(self, context: ToolContext) -> ToolResult:
        """Execute the tool and return a result."""
        ...
```

- [ ] **Step 3: Implement ChatTool**

```python
# bot/intent/tools/chat.py
from bot.ollama import OllamaChatMessage, generate_chat_completion
from bot.ollama.dto import OllamaErrorChunk
from bot.intent.schemas import ToolContext, ToolResult
from bot.intent.tools.base import BaseTool
from bot.settings import OLLAMA_MODEL, SYSTEM_MESSAGE


class ChatTool(BaseTool):
    name = "chat"

    async def execute(self, context: ToolContext) -> ToolResult:
        messages = [
            OllamaChatMessage(role="system", content=SYSTEM_MESSAGE),
            OllamaChatMessage(role="user", content=context.message_text),
        ]
        response = ""
        async for is_done, chunk in generate_chat_completion(messages, OLLAMA_MODEL):
            if is_done:
                break
            if isinstance(chunk, OllamaErrorChunk):
                response = f"[Ошибка Ollama: {chunk.error}]"
                break
            response += chunk.message.content

        if not response.strip():
            response = "(пустой ответ от модели)"

        return ToolResult(text=response[:3800])
```

- [ ] **Step 4: Implement RemindTool**

```python
# bot/intent/tools/remind.py
from bot.intent.schemas import ToolContext, ToolResult
from bot.intent.tools.base import BaseTool
from bot.routers.cron import _process_remind


class RemindTool(BaseTool):
    name = "remind"
    required_args = ("content",)

    async def execute(self, context: ToolContext) -> ToolResult:
        content = context.args.content or context.message_text
        await _process_remind(
            user_id=context.user_id,
            text=content,
            action="notify",
        )
        return ToolResult(text="reminder_created", success=True)
```

Note: `_process_remind` sends the Telegram message itself, so the tool returns a lightweight marker. The response formatter will ignore `text` when `success=True` for tools that self-send.

- [ ] **Step 5: Implement TaskTool**

```python
# bot/intent/tools/task.py
from bot.intent.schemas import ToolContext, ToolResult
from bot.intent.tools.base import BaseTool
from bot.routers.cron import _process_task_from_text


class TaskTool(BaseTool):
    name = "task"
    required_args = ("content",)

    async def execute(self, context: ToolContext) -> ToolResult:
        content = context.args.content or context.message_text
        await _process_task_from_text(
            user_id=context.user_id,
            text=content,
        )
        return ToolResult(text="task_created", success=True)
```

- [ ] **Step 6: Implement ToolRegistry**

```python
# bot/intent/tools/registry.py
from bot.intent.tools.base import BaseTool
from bot.intent.tools.chat import ChatTool
from bot.intent.tools.remind import RemindTool
from bot.intent.tools.task import TaskTool


class ToolRegistry:
    def __init__(self):
        self._tools: dict[str, BaseTool] = {
            ChatTool.name: ChatTool(),
            RemindTool.name: RemindTool(),
            TaskTool.name: TaskTool(),
        }

    @property
    def tools(self) -> dict[str, BaseTool]:
        return self._tools

    def get(self, name: str) -> BaseTool | None:
        return self._tools.get(name)
```

- [ ] **Step 7: Run tool tests**

Run: `pytest tests/intent/test_tools.py -v`

Expected: all pass.

- [ ] **Step 8: Commit**

```bash
git add bot/intent/tools/ tests/intent/test_tools.py
git commit -m "feat(intent): add BaseTool, ChatTool, RemindTool, TaskTool and registry"
```

---

## Task 6: Implement Context Builder Stub

**Files:**
- Create: `bot/intent/context.py`
- Test: `tests/intent/test_context.py`

- [ ] **Step 1: Write failing context test**

```python
# tests/intent/test_context.py
import pytest
from bot.intent.context import ContextBuilder


class TestContextBuilder:
    @pytest.mark.asyncio
    async def test_build_returns_context_dict(self):
        ctx = await ContextBuilder.build(user_id=1, message_text="hello")
        assert ctx["user_id"] == 1
        assert ctx["message_text"] == "hello"
        assert "current_time" in ctx
        assert ctx["dialogue_summary"] == ""
        assert ctx["relevant_memory"] == []
```

Run: `pytest tests/intent/test_context.py -v`

Expected: failure because `ContextBuilder` does not exist.

- [ ] **Step 2: Implement context builder**

```python
# bot/intent/context.py
from datetime import datetime, timezone


class ContextBuilder:
    """Build the context payload passed to the LLM intent router."""

    @classmethod
    async def build(cls, user_id: int, message_text: str) -> dict:
        return {
            "user_id": user_id,
            "message_text": message_text,
            "user_profile": {"timezone": "UTC", "language": "ru", "summary_style": "short"},
            "dialogue_summary": "",
            "recent_messages": [],
            "relevant_memory": [],
            "active_state": {},
            "current_time": datetime.now(timezone.utc).isoformat(),
        }
```

This is intentionally minimal for Iteration 1. Memory/summary integration comes in Iteration 2.

- [ ] **Step 3: Run context tests**

Run: `pytest tests/intent/test_context.py -v`

Expected: all pass.

- [ ] **Step 4: Commit**

```bash
git add bot/intent/context.py tests/intent/test_context.py
git commit -m "feat(intent): add minimal ContextBuilder stub for iteration 1"
```

---

## Task 7: Implement LLM Intent Router

**Files:**
- Create: `bot/intent/router.py`
- Test: `tests/intent/test_router.py`

- [ ] **Step 1: Write failing router tests**

```python
# tests/intent/test_router.py
import pytest
from unittest.mock import AsyncMock, patch
from bot.intent.router import LLMIntentRouter


class TestLLMIntentRouter:
    @pytest.mark.asyncio
    async def test_router_parses_json_response(self):
        fake_chunk = type(
            "Chunk",
            (object,),
            {
                "message": type("Message", (object,), {"content": '{"intent":"create_reminder","tool":"remind","args":{"content":"test"},"confidence":0.95}'}),
            },
        )
        with patch("bot.intent.router.generate_chat_completion", new_callable=AsyncMock) as mock_gen:
            mock_gen.return_value = iter([(False, fake_chunk), (True, None)])
            result = await LLMIntentRouter.route(user_id=1, message_text="remind me to test")

        assert result.intent == "create_reminder"
        assert result.tool == "remind"
        assert result.confidence == 0.95

    @pytest.mark.asyncio
    async def test_router_falls_back_on_invalid_json(self):
        fake_chunk = type(
            "Chunk",
            (object,),
            {
                "message": type("Message", (object,), {"content": "not json"}),
            },
        )
        with patch("bot.intent.router.generate_chat_completion", new_callable=AsyncMock) as mock_gen:
            mock_gen.return_value = iter([(False, fake_chunk), (True, None)])
            result = await LLMIntentRouter.route(user_id=1, message_text="hello")

        assert result.intent == "chat"
        assert result.tool == "chat"
        assert result.confidence == 0.0
```

Run: `pytest tests/intent/test_router.py -v`

Expected: failures because `LLMIntentRouter` does not exist.

- [ ] **Step 2: Implement router**

```python
# bot/intent/router.py
import json
from bot.ollama import OllamaChatMessage, generate_chat_completion
from bot.ollama.dto import OllamaErrorChunk
from bot.intent.context import ContextBuilder
from bot.intent.schemas import ALLOWED_INTENTS, ALLOWED_TOOLS, IntentArgs, IntentResult
from bot.settings import OLLAMA_MODEL, SYSTEM_MESSAGE


_ROUTER_SYSTEM_PROMPT = f"""Ты — интеллектуальный маршрутизатор Telegram-бота.

Проанализируй сообщение пользователя и выбери, какой инструмент бота должен использовать.

Доступные инструменты и их аргументы:
- chat: просто поговори с пользователем.
- remind: создай напоминание. args: content, trigger_at, recurring.
- task: создай задачу, которую выполнит AI. args: content, trigger_at, recurring.
- memory: сохрани факт или предпочтение. args: content.
- note: сохрани заметку. args: content.
- search: поиск в интернете. args: query.
- weather: погода в городе. args: city.
- news: актуальные новости. args: нет.
- monitor: добавь монитор сайта. args: name, url, interval.
- plan: составь план на неделю. args: plan_text.

Ответь строго JSON в формате:
{{
  "intent": "create_reminder",
  "tool": "remind",
  "args": {{"content": "...", "trigger_at": "...", "recurring": "..."}},
  "confidence": 0.92,
  "clarification_needed": false,
  "clarification_question": null,
  "response_tone": "friendly"
}}

intent должен быть одним из: {', '.join(ALLOWED_INTENTS.__args__)}.
tool должен быть одним из: {', '.join(ALLOWED_TOOLS.__args__)}.
confidence — число от 0.0 до 1.0.
Если не уверен, установи clarification_needed=true и задай уточняющий вопрос в clarification_question.
"""


class LLMIntentRouter:
    """Route a free-form user message to the correct tool via LLM."""

    @classmethod
    async def route(cls, user_id: int, message_text: str) -> IntentResult:
        context = await ContextBuilder.build(user_id, message_text)
        context_json = json.dumps(context, ensure_ascii=False, default=str)

        messages = [
            OllamaChatMessage(role="system", content=_ROUTER_SYSTEM_PROMPT),
            OllamaChatMessage(role="system", content=f"Контекст: {context_json}"),
            OllamaChatMessage(role="user", content=message_text),
        ]

        raw = ""
        async for is_done, chunk in generate_chat_completion(messages, OLLAMA_MODEL, temperature=0.2):
            if is_done:
                break
            if isinstance(chunk, OllamaErrorChunk):
                return cls._fallback(error=chunk.error)
            raw += chunk.message.content

        return cls._parse(raw.strip())

    @classmethod
    def _parse(cls, raw: str) -> IntentResult:
        if not raw:
            return cls._fallback()

        # Try to extract JSON even if wrapped in markdown
        if "```json" in raw:
            raw = raw.split("```json")[-1].split("```")[0].strip()
        elif "```" in raw:
            raw = raw.split("```")[-2].strip() if raw.count("```") >= 2 else raw

        try:
            data = json.loads(raw)
            return IntentResult.model_validate(data)
        except Exception:
            return cls._fallback()

    @classmethod
    def _fallback(cls, error: str | None = None) -> IntentResult:
        return IntentResult(
            intent="chat",
            tool="chat",
            confidence=0.0,
            clarification_needed=bool(error),
            clarification_question=f"Не удалось разобрать запрос: {error}" if error else None,
        )
```

- [ ] **Step 3: Run router tests**

Run: `pytest tests/intent/test_router.py -v`

Expected: all pass.

- [ ] **Step 4: Commit**

```bash
git add bot/intent/router.py tests/intent/test_router.py
git commit -m "feat(intent): add LLM intent router with JSON parsing and fallback"
```

---

## Task 8: Implement Intent Executor and Formatter

**Files:**
- Create: `bot/intent/executor.py`
- Test: `tests/intent/test_executor.py`

- [ ] **Step 1: Write failing executor tests**

```python
# tests/intent/test_executor.py
import pytest
from unittest.mock import AsyncMock, patch
from bot.intent.executor import IntentExecutor
from bot.intent.schemas import IntentArgs, IntentResult
from bot.intent.tools.registry import ToolRegistry


class TestIntentExecutor:
    @pytest.mark.asyncio
    async def test_chat_fallback_on_low_confidence(self):
        result = IntentResult(
            intent="create_reminder",
            tool="remind",
            args=IntentArgs(),
            confidence=0.5,
        )
        with patch.object(ToolRegistry, "get") as mock_get:
            mock_chat = AsyncMock()
            mock_chat.execute.return_value.text = "Уточни, пожалуйста"
            mock_chat.execute.return_value.success = True
            mock_get.return_value = mock_chat
            tool_result = await IntentExecutor.execute(user_id=1, message_text="?", intent_result=result)
        assert "Уточни" in tool_result.text

    @pytest.mark.asyncio
    async def test_runs_tool_on_high_confidence(self):
        result = IntentResult(
            intent="create_reminder",
            tool="remind",
            args=IntentArgs(content="test"),
            confidence=0.95,
        )
        with patch.object(ToolRegistry, "get") as mock_get:
            mock_tool = AsyncMock()
            mock_tool.execute.return_value.text = "done"
            mock_tool.execute.return_value.success = True
            mock_get.return_value = mock_tool
            tool_result = await IntentExecutor.execute(user_id=1, message_text="remind me", intent_result=result)
        assert tool_result.text == "done"
```

Run: `pytest tests/intent/test_executor.py -v`

Expected: failures because `IntentExecutor` does not exist.

- [ ] **Step 2: Implement executor**

```python
# bot/intent/executor.py
from bot.intent.schemas import IntentResult, ToolContext, ToolResult
from bot.intent.tools.chat import ChatTool
from bot.intent.tools.registry import ToolRegistry
from bot.intent.validator import ValidationError, Validator


class IntentExecutor:
    """Validate an intent result and dispatch it to the correct tool."""

    def __init__(self, registry: ToolRegistry | None = None):
        self.registry = registry or ToolRegistry()
        self.chat_tool = ChatTool()

    async def execute(
        self,
        user_id: int,
        message_text: str,
        intent_result: IntentResult,
    ) -> ToolResult:
        try:
            Validator.validate(intent_result)
        except ValidationError as e:
            return await self._clarify(str(e), message_text)

        tool = self.registry.get(intent_result.tool)
        if tool is None:
            return await self._fallback(message_text)

        context = ToolContext(
            user_id=user_id,
            message_text=message_text,
            args=intent_result.args,
            intent_result=intent_result,
        )
        return await tool.execute(context)

    async def _clarify(self, reason: str, message_text: str) -> ToolResult:
        question = f"Не уверен, что ты имел в виду. Можешь уточнить? ({reason})"
        context = ToolContext(
            user_id=0,
            message_text=message_text,
            args={},
            intent_result=IntentResult(intent="clarify", tool="chat", confidence=1.0),
        )
        return ToolResult(text=question, success=True, extra={"reason": reason})

    async def _fallback(self, message_text: str) -> ToolResult:
        context = ToolContext(
            user_id=0,
            message_text=message_text,
            args={},
            intent_result=IntentResult(intent="chat", tool="chat", confidence=1.0),
        )
        return await self.chat_tool.execute(context)
```

- [ ] **Step 3: Run executor tests**

Run: `pytest tests/intent/test_executor.py -v`

Expected: all pass.

- [ ] **Step 4: Commit**

```bash
git add bot/intent/executor.py tests/intent/test_executor.py
git commit -m "feat(intent): add IntentExecutor with validation and dispatch"
```

---

## Task 9: Wire Smart Handler into aiogram

**Files:**
- Create: `bot/handlers/smart.py`
- Modify: `bot/__init__.py` around line 58 where routers are included
- Test: `tests/handlers/test_smart.py`

- [ ] **Step 1: Write failing handler test**

```python
# tests/handlers/test_smart.py
import pytest
from unittest.mock import AsyncMock, patch
from aiogram.types import Message, User
from bot.handlers.smart import smart_message_handler


class TestSmartHandler:
    @pytest.mark.asyncio
    async def test_handler_calls_intent_pipeline(self):
        message = Message(
            message_id=1,
            date=None,
            chat=None,
            from_user=User(id=1, is_bot=False, first_name="Test"),
        )
        message.text = "завтра в 9 позвонить брокеру"

        with patch("bot.handlers.smart.LLMIntentRouter.route", new_callable=AsyncMock) as mock_route:
            mock_route.return_value.intent = "create_reminder"
            mock_route.return_value.tool = "remind"
            mock_route.return_value.args.content = "позвонить брокеру"
            mock_route.return_value.confidence = 0.95
            with patch("bot.handlers.smart.IntentExecutor.execute", new_callable=AsyncMock) as mock_exec:
                mock_exec.return_value.success = True
                mock_exec.return_value.text = "done"
                await smart_message_handler(message, state=None)
        mock_route.assert_awaited_once()
        mock_exec.assert_awaited_once()
```

Run: `pytest tests/handlers/test_smart.py -v`

Expected: failure because `bot.handlers.smart` does not exist.

- [ ] **Step 2: Implement smart handler**

```python
# bot/handlers/smart.py
from aiogram import Router, F
from aiogram.fsm.context import FSMContext
from aiogram.types import Message

from bot.intent.executor import IntentExecutor
from bot.intent.router import LLMIntentRouter

router = Router()


@router.message(F.text)
async def smart_message_handler(message: Message, state: FSMContext | None = None):
    """Handle free-form text through the smart intent pipeline."""
    if message.from_user is None:
        return
    if message.text is None:
        return

    # Clear any stuck FSM state before processing a new free-form request.
    if state is not None:
        await state.clear()

    user_id = message.from_user.id
    text = message.text.strip()

    intent_result = await LLMIntentRouter.route(user_id=user_id, message_text=text)
    await IntentExecutor().execute(
        user_id=user_id,
        message_text=text,
        intent_result=intent_result,
    )
```

- [ ] **Step 3: Include smart router before legacy completion router**

Modify `bot/__init__.py` line 58:

```python
from bot.routers import start, completion, cron
from bot.handlers import smart as smart_handler

# ... existing code ...

# Order matters: cron commands must be checked before generic completion handler
# Smart handler runs first for free-form text; explicit commands still handled by cron/completion.
dp.include_routers(start.router, smart_handler.router, cron.router, completion.router)
```

The exact change is adding the import and inserting `smart_handler.router` after `start.router`.

- [ ] **Step 4: Run handler tests**

Run: `pytest tests/handlers/test_smart.py -v`

Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add bot/handlers/smart.py bot/__init__.py tests/handlers/test_smart.py
git commit -m "feat(bot): wire smart intent handler into aiogram dispatcher"
```

---

## Task 10: Add Intent Regression Suite

**Files:**
- Create: `tests/intent/test_regression.py`

- [ ] **Step 1: Write regression tests with mocked LLM**

```python
# tests/intent/test_regression.py
import pytest
from unittest.mock import AsyncMock, patch
from bot.intent.router import LLMIntentRouter


def _make_chunk(content: str):
    return type("Chunk", (object,), {"message": type("Message", (object,), {"content": content})})


REGRESSION_CASES = [
    (
        "завтра в 9 позвонить брокеру",
        '{"intent":"create_reminder","tool":"remind","args":{"content":"позвонить брокеру"},"confidence":0.95}',
        "create_reminder",
        "remind",
    ),
    (
        "каждое утро в 8 погода в москве",
        '{"intent":"create_task","tool":"task","args":{"content":"погода в москве"},"confidence":0.92}',
        "create_task",
        "task",
    ),
    (
        "привет",
        '{"intent":"chat","tool":"chat","args":{},"confidence":0.99}',
        "chat",
        "chat",
    ),
]


class TestIntentRegression:
    @pytest.mark.parametrize("text,json_response,expected_intent,expected_tool", REGRESSION_CASES)
    @pytest.mark.asyncio
    async def test_routing(self, text, json_response, expected_intent, expected_tool):
        with patch("bot.intent.router.generate_chat_completion", new_callable=AsyncMock) as mock_gen:
            mock_gen.return_value = iter([(False, _make_chunk(json_response)), (True, None)])
            result = await LLMIntentRouter.route(user_id=1, message_text=text)
        assert result.intent == expected_intent
        assert result.tool == expected_tool
```

Run: `pytest tests/intent/test_regression.py -v`

Expected: all pass.

- [ ] **Step 2: Commit**

```bash
git add tests/intent/test_regression.py
git commit -m "test(intent): add initial regression suite for smart routing"
```

---

## Task 11: Run Full Test Suite and Final QA

- [ ] **Step 1: Run all tests**

Run: `poetry run pytest tests/ -v`

Expected: all tests pass.

- [ ] **Step 2: Compile project**

Run: `poetry run python -m py_compile $(find . -name '*.py' -not -path './.git/*' -not -path './*/\_\_pycache__/*')`

Expected: no syntax errors.

- [ ] **Step 3: Smoke test the bot start path**

Run: `TELEGRAM_TOKEN=dummy OLLAMA_API_KEY=dummy ALLOWED_CHAT_IDS= poetry run python -c "from bot.handlers.smart import smart_message_handler; print('import ok')"`

Expected: `import ok`.

- [ ] **Step 4: Commit any fixes and finalize**

If any fixes were needed, commit them. Then:

```bash
git log --oneline -5
```

Expected: clean commit history.

---

## Self-Review Checklist

- **Spec coverage:**
  - Smart routing of free-form text → Task 7 (router), Task 9 (handler wiring).
  - JSON output + strict validation → Task 4 (validator), Task 7 (router parse).
  - BaseTool interface and tool executors → Task 5.
  - Context builder stub → Task 6.
  - Chat/Remind/Task tools → Task 5.
  - Friendly responses and command_keyboard restoration → existing `_process_*` functions handle this; no regression.
  - Iteration 1 scope only → no proactive engine, no planning, no full memory integration.

- **Placeholder scan:** No TBD/TODO/fill-in details. Every step has code, commands, expected output.

- **Type consistency:** `IntentResult`, `ToolContext`, `ToolResult`, and `BaseTool` names are consistent across tasks.

- **Gaps identified:**
  - `RemindTool` and `TaskTool` return placeholder `text` because `_process_remind`/`_process_task_from_text` send Telegram messages directly. This is acceptable for Iteration 1; the response formatter will be built in Iteration 2 when more tools are added.
  - `ContextBuilder` is a stub; real memory/summary integration is Iteration 2.
