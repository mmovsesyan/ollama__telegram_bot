import pytest
from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

from bot.services import news_categories as nc_module
from bot.services.rss_news import NewsItem


class _FakeDb:
    def __init__(self, prefs=None):
        self._prefs = prefs or {}
        self._stored = {}

    def get_user_prefs(self, user_id):
        return {
            **self._prefs,
            "user_id": user_id,
            **self._stored,
        }

    def set_user_prefs(self, user_id, **kwargs):
        self._stored.update(kwargs)


@pytest.fixture(autouse=True)
def reset_nc_db():
    nc_module.db = None
    yield
    nc_module.db = None


def test_user_categories_defaults_to_first_three():
    assert nc_module._user_categories(1) == ["tech", "markets", "ai"]


def test_user_categories_reads_db_prefs():
    nc_module.db = _FakeDb(prefs={"news_categories": "crypto,world"})
    assert nc_module._user_categories(1) == ["crypto", "world"]


def test_user_categories_empty_defaults_to_first_three():
    nc_module.db = _FakeDb(prefs={"news_categories": ""})
    assert nc_module._user_categories(1) == ["tech", "markets", "ai"]


def test_normalize_category_aliases():
    assert nc_module._normalize_category("акции") == "markets"
    assert nc_module._normalize_category("ИИ") == "ai"
    assert nc_module._normalize_category("TECH") == "tech"
    assert nc_module._normalize_category("unknown") == "unknown"


def test_set_user_categories_filters_unknown_and_dedupes():
    nc_module.db = _FakeDb()
    result = nc_module.set_user_categories(1, ["акции", "финансы", "foo"])
    assert result == ["markets"]
    assert nc_module.db._stored["news_categories"] == "markets"


def test_add_user_category_persists():
    nc_module.db = _FakeDb(prefs={"news_categories": "tech"})
    cats, added = nc_module.add_user_category(1, "markets")
    assert added is True
    assert cats == ["tech", "markets"]


def test_add_user_category_unknown_returns_false():
    nc_module.db = _FakeDb(prefs={"news_categories": "tech"})
    cats, added = nc_module.add_user_category(1, "foo")
    assert added is False
    assert cats == ["tech"]


def test_add_user_category_duplicate_returns_false():
    nc_module.db = _FakeDb(prefs={"news_categories": "tech"})
    cats, added = nc_module.add_user_category(1, "tech")
    assert added is False
    assert cats == ["tech"]


def test_remove_user_category_keeps_at_least_default():
    nc_module.db = _FakeDb(prefs={"news_categories": "tech"})
    cats, removed = nc_module.remove_user_category(1, "tech")
    assert removed is True
    assert cats == ["tech"]


def test_remove_user_category_not_in_list_returns_false():
    nc_module.db = _FakeDb(prefs={"news_categories": "tech"})
    cats, removed = nc_module.remove_user_category(1, "markets")
    assert removed is False
    assert cats == ["tech"]


def test_score_item_prefers_recent_quality_and_topic_match():
    now = datetime.now(timezone.utc)
    fresh = NewsItem(
        title="Apple запускает ИИ-чип",
        url="https://habr.com/post/1",
        summary="Новый чип для нейросетей",
        published=now,
        source="habr.com",
    )
    stale = NewsItem(
        title="Старый обзор ноутбука",
        url="https://example.com/old",
        summary="Процессор и экран",
        published=now - __import__("datetime").timedelta(days=7),
        source="example.com",
    )
    assert nc_module._score_item(fresh, "ai") > nc_module._score_item(stale, "ai")


@pytest.mark.asyncio
async def test_get_personalized_digest_builds_blocks():
    nc_module.db = _FakeDb(prefs={"news_categories": "ai"})
    now = datetime.now(timezone.utc)
    item = NewsItem(
        title="Новость ИИ",
        url="https://habr.com/ai",
        summary="Краткое содержание",
        published=now,
        source="habr.com",
    )
    with patch(
        "bot.services.news_categories.rss_news_service.get_fresh_news",
        new=AsyncMock(return_value=("text", [item], "rss")),
    ):
        text = await nc_module.get_personalized_digest(1)

    assert "Персональный дайджест" in text
    assert "AI" in text
    assert "Новость ИИ" in text


@pytest.mark.asyncio
async def test_get_personalized_digest_no_items_returns_fallback():
    nc_module.db = _FakeDb(prefs={"news_categories": "ai"})
    with patch(
        "bot.services.news_categories.rss_news_service.get_fresh_news",
        new=AsyncMock(return_value=("", [], "rss")),
    ):
        text = await nc_module.get_personalized_digest(1)

    assert "ничего не нашёл" in text


@pytest.mark.asyncio
async def test_get_personalized_digest_truncates_to_4096():
    nc_module.db = _FakeDb(prefs={"news_categories": "tech"})
    long_item = NewsItem(
        title="X" * 500,
        url="https://example.com/" + "x" * 500,
        summary="Y" * 500,
        published=datetime.now(timezone.utc),
        source="example.com",
    )
    with patch(
        "bot.services.news_categories.rss_news_service.get_fresh_news",
        new=AsyncMock(return_value=("", [long_item], "rss")),
    ):
        text = await nc_module.get_personalized_digest(1)

    assert len(text) <= 4096
