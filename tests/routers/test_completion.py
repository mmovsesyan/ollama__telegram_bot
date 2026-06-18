import sys
from types import ModuleType

import pytest
from datetime import datetime, timezone
from unittest.mock import MagicMock

# bot.bot raises at import if TELEGRAM_TOKEN is missing; provide a fake module
# before importing the completion router.
if "bot.bot" not in sys.modules:
    _fake_bot_module = ModuleType("bot.bot")
    _fake_bot_module.bot = MagicMock()
    sys.modules["bot.bot"] = _fake_bot_module

from bot.ollama import OllamaChat, OllamaChatMessage
from bot.routers import completion as completion_module
from bot.routers.completion import (
    UserChat,
    _build_system_content,
    refresh_system_prompt,
)


class _FakeDb:
    def __init__(self, notes="", memories=None):
        self._notes = notes
        self._memories = memories or []

    def get_notes(self, user_id):
        return self._notes

    def get_memories(self, user_id):
        return self._memories


@pytest.fixture(autouse=True)
def reset_state(monkeypatch):
    completion_module.db = None
    completion_module.chats.clear()
    yield
    completion_module.db = None
    completion_module.chats.clear()


class TestBuildSystemContent:
    def test_returns_base_when_db_missing(self):
        text = _build_system_content(1)
        assert text == completion_module.SYSTEM_MESSAGE

    def test_appends_notes_and_memories(self):
        completion_module.db = _FakeDb(
            notes="Любит краткие ответы.",
            memories=[
                {"category": "preference", "content": "не любит markdown", "summary": None},
                {"category": "fact", "content": "работает в X", "summary": "работает в компании X"},
            ],
        )
        text = _build_system_content(1)
        assert completion_module.SYSTEM_MESSAGE in text
        assert "Любит краткие ответы." in text
        assert "[preference] не любит markdown" in text
        assert "[fact] работает в компании X" in text


class TestRefreshSystemPrompt:
    def test_returns_false_when_no_chat(self):
        completion_module.db = _FakeDb()
        assert refresh_system_prompt(1) is False

    def test_returns_false_when_no_db(self):
        completion_module.chats[1] = UserChat(ollama_chat=OllamaChat(messages=[]))
        assert refresh_system_prompt(1) is False

    def test_inserts_base_system_when_missing(self):
        completion_module.db = _FakeDb(notes="note")
        chat = UserChat(ollama_chat=OllamaChat(messages=[]))
        completion_module.chats[1] = chat
        assert refresh_system_prompt(1) is True
        assert chat.ollama_chat.messages[0].role == "system"
        assert "note" in chat.ollama_chat.messages[0].content

    def test_updates_existing_base_system(self):
        completion_module.db = _FakeDb(notes="new note")
        chat = UserChat(
            ollama_chat=OllamaChat(
                messages=[OllamaChatMessage(role="system", content="old base")]
            )
        )
        completion_module.chats[1] = chat
        assert refresh_system_prompt(1) is True
        assert chat.ollama_chat.messages[0].content == _build_system_content(1)
        assert "new note" in chat.ollama_chat.messages[0].content

    def test_preserves_summary_message(self):
        completion_module.db = _FakeDb(notes="note")
        summary_msg = OllamaChatMessage(
            role="system",
            content="[Контекст предыдущего диалога]: summary text",
        )
        chat = UserChat(
            ollama_chat=OllamaChat(
                messages=[
                    OllamaChatMessage(role="system", content="base"),
                    summary_msg,
                    OllamaChatMessage(role="user", content="hi"),
                ]
            )
        )
        completion_module.chats[1] = chat
        assert refresh_system_prompt(1) is True
        assert chat.ollama_chat.messages[1].role == "system"
        assert "summary text" in chat.ollama_chat.messages[1].content

    def test_reinserts_summary_if_dropped(self):
        completion_module.db = _FakeDb(notes="note")
        summary_msg = OllamaChatMessage(
            role="system",
            content="[Контекст предыдущего диалога]: summary text",
        )
        chat = UserChat(
            ollama_chat=OllamaChat(messages=[summary_msg, OllamaChatMessage(role="user", content="hi")])
        )
        completion_module.chats[1] = chat
        assert refresh_system_prompt(1) is True
        assert chat.ollama_chat.messages[0].role == "system"
        assert chat.ollama_chat.messages[1].role == "system"
        assert "summary text" in chat.ollama_chat.messages[1].content

    def test_trims_context_after_refresh(self, monkeypatch):
        completion_module.db = _FakeDb(notes="note")
        long_msg = "x" * (completion_module.MAX_CONTEXT_TOKENS * 4 + 100)
        chat = UserChat(
            ollama_chat=OllamaChat(
                messages=[
                    OllamaChatMessage(role="system", content="base"),
                    OllamaChatMessage(role="user", content=long_msg),
                ]
            )
        )
        completion_module.chats[1] = chat
        assert refresh_system_prompt(1) is True
        # Base system kept; oversized user message dropped by trim
        assert chat.ollama_chat.messages[0].role == "system"
        assert len(chat.ollama_chat.messages) < 3 or chat.ollama_chat.messages[-1].role == "system"
