"""Tests for SQLite FTS5 knowledge base search and memory enrichment."""

import os
import tempfile
from unittest.mock import patch

import pytest

from bot.db import Database
from bot.intent.schemas import IntentArgs, IntentResult, ToolContext
from bot.intent.tools.kb_search import KbSearchTool
from bot.services import kb as kb_service
from bot.services.kb import _format_hit, _format_web_fallback_item
from bot.services.kb_extract import _looks_skippable, _parse_facts


@pytest.fixture
def db():
    """Fresh in-memory-like Database for each test (uses a temp file)."""
    f = tempfile.NamedTemporaryFile(delete=False, suffix=".db").name
    instance = Database(f)
    try:
        yield instance
    finally:
        os.unlink(f)


class TestMemoriesFts:
    def test_fresh_db_has_fts_table(self, db):
        # If migrations didn't run, search returns empty rather than crashing
        assert db.search_memories(1, "anything") == []

    def test_add_and_search_exact(self, db):
        db.add_memory(42, "fact", "Tesla стоит 250 долларов за акцию")
        hits = db.search_memories(42, "Tesla")
        assert len(hits) == 1
        assert hits[0]["content"].startswith("Tesla")
        assert hits[0]["category"] == "fact"

    def test_search_isolated_per_user(self, db):
        db.add_memory(1, "fact", "только пользователь 1 знает это")
        db.add_memory(2, "fact", "и только пользователь 2 знает то")
        u1_hits = db.search_memories(1, "знает")
        u2_hits = db.search_memories(2, "знает")
        assert len(u1_hits) == 1 and "только пользователь 1" in u1_hits[0]["content"]
        assert len(u2_hits) == 1 and "только пользователь 2" in u2_hits[0]["content"]

    def test_prefix_matches_inflected_form(self, db):
        # 'яблок' should hit 'яблоки' via FTS5 prefix wildcard
        db.add_memory(1, "note", "купить яблоки и хлеб")
        hits = db.search_memories(1, "яблок")
        assert len(hits) == 1

    def test_multiple_tokens_or_match(self, db):
        # 'Tesla 300' should hit even when '300' isn't in the row,
        # because at least one token matches and OR is the default.
        db.add_memory(1, "fact", "Tesla стоит 250 долларов за акцию")
        hits = db.search_memories(1, "Tesla 300")
        assert len(hits) == 1

    def test_empty_query_returns_empty(self, db):
        db.add_memory(1, "fact", "что-то")
        assert db.search_memories(1, "") == []
        assert db.search_memories(1, "   ") == []

    def test_no_match_returns_empty(self, db):
        db.add_memory(1, "fact", "что-то про Tesla")
        assert db.search_memories(1, "никаких таких слов") == []

    def test_delete_removes_from_index(self, db):
        mid = db.add_memory(1, "fact", "уникальное слово вилявка")
        assert len(db.search_memories(1, "вилявка")) == 1
        db.remove_memory(mid)
        assert db.search_memories(1, "вилявка") == []

    def test_summary_indexed_alongside_content(self, db):
        long_content = "очень длинная заметка про мармелад и зефир " * 20
        mid = db.add_memory(1, "note", long_content)
        # Summary contains a different keyword; both should be findable
        db.update_memory_summary(mid, "сладости и переработка сахара")
        assert len(db.search_memories(1, "мармелад")) == 1
        assert len(db.search_memories(1, "сладости")) == 1


class TestKbServiceFallback:
    @pytest.mark.asyncio
    async def test_local_hit_returns_kb_text(self, db):
        kb_service.db = db
        db.add_memory(7, "fact", "Tesla — электромобили из Калифорнии")
        text, hits, used_web = await kb_service.search_kb_with_web_fallback(7, "Tesla")
        assert "Tesla" in text
        assert "из твоей базы" in text.lower()
        assert len(hits) == 1
        assert used_web is False

    @pytest.mark.asyncio
    async def test_empty_kb_falls_back_to_web(self, db):
        kb_service.db = db
        # No memories. Mock ollama_web_search to return one item.
        async def fake_search(query, max_results=5):
            return ({"results": [{"title": "Wiki", "url": "https://x.com", "content": "Some text"}]}, None)
        with patch("bot.routers.cron.ollama_web_search", side_effect=fake_search):
            text, hits, used_web = await kb_service.search_kb_with_web_fallback(8, "anything")
        assert used_web is True
        assert hits == []
        assert "интернет" in text.lower()

    @pytest.mark.asyncio
    async def test_both_empty_returns_empty(self, db):
        kb_service.db = db
        async def fake_search(query, max_results=5):
            return ({"results": []}, None)
        with patch("bot.routers.cron.ollama_web_search", side_effect=fake_search):
            text, hits, used_web = await kb_service.search_kb_with_web_fallback(9, "nothing")
        assert text == ""
        assert hits == []
        assert used_web is True


class TestKbSearchTool:
    @pytest.mark.asyncio
    async def test_tool_strips_trigger_phrases(self, db):
        kb_service.db = db
        db.add_memory(5, "fact", "Армения — горная страна")
        ctx = ToolContext(
            user_id=5,
            message_text="что я говорил про Армения",
            args=IntentArgs(query="что я говорил про Армения"),
            intent_result=IntentResult(intent="kb_search", tool="kb_search", confidence=0.9),
        )
        result = await KbSearchTool().execute(ctx)
        # Trigger phrase stripped → search uses just "Армения"
        assert result.success is True
        assert "Армения" in result.text

    @pytest.mark.asyncio
    async def test_tool_handles_empty_query(self, db):
        kb_service.db = db
        ctx = ToolContext(
            user_id=5,
            message_text="",
            args=IntentArgs(query=""),
            intent_result=IntentResult(intent="kb_search", tool="kb_search", confidence=0.9),
        )
        result = await KbSearchTool().execute(ctx)
        assert result.success is False


class TestKbExtractHelpers:
    def test_skip_short_exchange(self):
        assert _looks_skippable("привет", "Здравствуй!")

    def test_skip_acknowledgement(self):
        assert _looks_skippable(
            "запомни что я люблю краткие ответы",
            "✅ Заметка сохранена. AI будет помнить это.",
        )

    def test_keep_real_exchange(self):
        # User shares real info; assistant gives a real answer
        assert not _looks_skippable(
            "Я работаю над проектом X с командой 5 человек",
            "Понял. Расскажи подробнее про команду — кто чем занимается?",
        )

    def test_parse_facts_basic(self):
        raw = "[fact] Я работаю над проектом X\n[preference] Люблю краткие ответы\n[note] Купить хлеб"
        facts = _parse_facts(raw)
        assert len(facts) == 3
        assert facts[0] == ("fact", "Я работаю над проектом X")
        assert facts[1] == ("preference", "Люблю краткие ответы")
        assert facts[2] == ("note", "Купить хлеб")

    def test_parse_facts_handles_net(self):
        assert _parse_facts("НЕТ") == []
        assert _parse_facts("") == []

    def test_parse_facts_skips_malformed(self):
        # Mix of valid and invalid lines
        raw = "[fact] valid line\nthis line has no brackets\n[note] another valid"
        facts = _parse_facts(raw)
        assert len(facts) == 2
        assert facts[0] == ("fact", "valid line")
        assert facts[1] == ("note", "another valid")

    def test_parse_facts_coerces_unknown_category(self):
        facts = _parse_facts("[opinion] I think Python is good")
        assert len(facts) == 1
        assert facts[0][0] == "note"  # coerced from 'opinion'


class TestKbFormatting:
    def test_format_hit_truncates_long_text(self):
        hit = {"category": "fact", "content": "x" * 400}
        text = _format_hit(hit, 1)
        assert text.startswith("1. 📌")
        assert len(text) < 350

    def test_format_hit_uses_summary(self):
        hit = {"category": "note", "content": "long", "summary": "short"}
        text = _format_hit(hit, 2)
        assert "short" in text
        assert "long" not in text

    def test_format_web_fallback_item_full(self):
        item = {
            "title": "Wiki",
            "url": "https://ru.wikipedia.org/wiki/Python",
            "body": "Python is a language.\nMore text.",
        }
        text = _format_web_fallback_item(item, 1)
        assert "1. Wiki" in text
        assert "ru.wikipedia.org" in text
        assert "Python is a language. More text." in text
        assert "https://ru.wikipedia.org/wiki/Python" in text

    def test_format_web_fallback_item_without_url(self):
        item = {"title": "No link", "content": "body"}
        text = _format_web_fallback_item(item, 2)
        assert "2. No link" in text
        assert "body" in text
        assert "🔗" not in text

    @pytest.mark.asyncio
    async def test_web_fallback_uses_clean_format(self, db):
        kb_service.db = db

        async def fake_search(query, max_results=5):
            return (
                {
                    "results": [
                        {
                            "title": "Result",
                            "url": "https://example.com/a",
                            "body": "snippet line\nnext",
                        }
                    ]
                },
                None,
            )

        with patch("bot.routers.cron.ollama_web_search", side_effect=fake_search):
            text, hits, used_web = await kb_service.search_kb_with_web_fallback(11, "x")
        assert used_web is True
        assert "интернет" in text.lower()
        assert "snippet line next" in text
        assert "example.com" in text


class TestKbExtractIntegration:
    @pytest.mark.asyncio
    async def test_extract_saves_new_facts(self, db):
        from bot.services.kb_extract import extract_facts_from_exchange

        async def fake_gen(*args, **kwargs):
            yield (False, type("C", (), {"message": type("M", (), {"content": "[fact] Пользователь любит Python"})})())

        with patch("bot.services.kb_extract.generate_chat_completion", side_effect=fake_gen):
            saved = await extract_facts_from_exchange(
                db, 1,
                "я программирую на Python уже 10 лет",
                "Здорово! Какие у тебя любимые библиотеки?",
            )
        assert saved == 1
        memories = db.get_memories(1)
        assert len(memories) == 1
        assert memories[0]["source"] == "auto-extract"

    @pytest.mark.asyncio
    async def test_extract_dedupes(self, db):
        from bot.services.kb_extract import extract_facts_from_exchange

        # Pre-populate with the same fact LLM will "extract"
        db.add_memory(1, "fact", "Пользователь любит Python")

        async def fake_gen(*args, **kwargs):
            yield (False, type("C", (), {"message": type("M", (), {"content": "[fact] пользователь любит python"})})())

        with patch("bot.services.kb_extract.generate_chat_completion", side_effect=fake_gen):
            saved = await extract_facts_from_exchange(
                db, 1,
                "я люблю Python", "Окей.",
            )
        # Same content (case-insensitive) → not saved again
        assert saved == 0
        assert len(db.get_memories(1)) == 1
