import time
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from bot.services import rss_news as rss_module
from bot.services.rss_news import (
    NewsItem,
    _clean_text,
    _extract_source_from_url,
    _filter_unshown,
    _format_rss_item,
    _is_recent,
    _looks_russian,
    _mark_shown,
    _matches_topic,
    _parse_feeds,
    _parse_rss_date,
    _web_fallback,
    get_fresh_news,
    render_news,
)


class TestNewsItem:
    def test_to_dict_serializes_fields(self):
        published = datetime(2026, 6, 18, 12, 0, 0, tzinfo=timezone.utc)
        item = NewsItem(
            "Title",
            "https://x.com/a",
            "summary",
            published,
            "x.com",
            "https://x.com/a.jpg",
        )
        assert item.to_dict() == {
            "title": "Title",
            "url": "https://x.com/a",
            "summary": "summary",
            "published": "2026-06-18T12:00:00+00:00",
            "source": "x.com",
            "image_url": "https://x.com/a.jpg",
        }

    def test_to_dict_none_published(self):
        item = NewsItem("Title", "https://x.com/a")
        assert item.to_dict()["published"] is None


class TestTextHelpers:
    def test_clean_text_strips_html_and_truncates(self):
        raw = "<p>Hello&nbsp;world</p> " + "x" * 500
        out = _clean_text(raw, max_len=50)
        assert "<p>" not in out
        assert "Hello world" in out
        assert out.endswith("...")
        assert len(out) <= 53

    def test_clean_text_empty(self):
        assert _clean_text(None) == ""
        assert _clean_text("   ") == ""

    def test_extract_source_from_url_strips_www(self):
        assert _extract_source_from_url("https://www.rbc.ru/business") == "rbc.ru"
        assert _extract_source_from_url("http://habr.com") == "habr.com"
        assert _extract_source_from_url("not-url") == ""

    def test_is_recent_within_window(self):
        now = datetime.now(timezone.utc)
        assert _is_recent(now, hours=48) is True
        assert _is_recent(now - timedelta(hours=49), hours=48) is False
        assert _is_recent(None, hours=48) is True

    def test_matches_topic_single_word(self):
        assert _matches_topic("Apple выпустила iPhone", "apple") is True
        assert _matches_topic("Apple выпустила iPhone", "samsung") is False

    def test_matches_topic_phrase(self):
        assert _matches_topic("новый iPhone 16 Pro", "iphone 16") is True
        assert _matches_topic("новый iPhone 16 Pro", "iphone 17") is False

    def test_matches_topic_short_russian_word_uses_whole_word(self):
        # "ии" must not match as a substring inside unrelated words.
        assert _matches_topic("Новости об ИИ: GPT-5", "ии") is True
        assert _matches_topic("Медведев: правил в отношении Киева", "ии") is False
        assert _matches_topic("российских городах ничего не нашлось", "ии") is False

    def test_matches_topic_multi_word_matches_any_synonym(self):
        # Category-like multi-word topics are treated as synonyms: any hit is
        # enough, so "игры Steam консоли гейминг" still matches "инди-игр".
        assert (
            _matches_topic(
                "искусственный интеллект меняет мир", "искусственный интеллект"
            )
            is True
        )
        assert (
            _matches_topic(
                "искусственный интеллект меняет мир",
                "искусственный интеллект нейросети",
            )
            is True
        )

    def test_matches_topic_digit_queries_require_all_parts(self):
        # Specific model/version queries must match every part.
        assert _matches_topic("новый iPhone 16 Pro", "iphone 16") is True
        assert _matches_topic("новый iPhone 16 Pro", "iphone 17") is False

    def test_matches_topic_no_topic(self):
        assert _matches_topic("anything", None) is True
        assert _matches_topic("anything", "") is True

    def test_looks_russian_positive(self):
        assert _looks_russian("Привет, это новости из Москвы") is True

    def test_looks_russian_negative(self):
        assert _looks_russian("Hello world") is False
        assert _looks_russian("hi") is False

    def test_looks_like_english_query(self):
        from bot.services.rss_news import _looks_like_english_query

        assert _looks_like_english_query("steam") is True
        assert _looks_like_english_query("Tesla") is True
        assert _looks_like_english_query("AI news") is True
        assert _looks_like_english_query("игры") is False
        assert _looks_like_english_query("биткоин") is False
        assert _looks_like_english_query("") is False


class TestDateParsing:
    def test_parse_rss_date_from_struct_time(self):
        st = time.struct_time((2026, 6, 18, 10, 30, 0, 0, 0, 0))
        entry = SimpleNamespace(published_parsed=st)
        dt = _parse_rss_date(entry)
        assert dt == datetime(2026, 6, 18, 10, 30, 0, tzinfo=timezone.utc)

    def test_parse_rss_date_from_iso_string(self):
        entry = SimpleNamespace(published="2026-06-18T10:30:00Z")
        dt = _parse_rss_date(entry)
        assert dt == datetime(2026, 6, 18, 10, 30, 0, tzinfo=timezone.utc)

    def test_parse_rss_date_returns_none_when_missing(self):
        assert _parse_rss_date(SimpleNamespace()) is None


class TestFormatting:
    def test_format_rss_item_includes_all_parts(self):
        item = NewsItem(
            "Заголовок",
            "https://habr.com/news/1",
            "Краткое содержание",
            datetime(2026, 6, 18, 12, 0, 0, tzinfo=timezone.utc),
            "habr.com",
        )
        text = _format_rss_item(item, 1)
        assert "1. 💻 Заголовок" in text
        assert "habr.com" in text
        assert "18 июн" in text or "18 Jun" in text
        assert "Краткое" in text

        # HTML variant embeds the URL as a clickable link.
        html = _format_rss_item(item, 1, html=True)
        assert 'href="https://habr.com/news/1"' in html
        assert "💻 Заголовок" in html

    def test_format_rss_item_without_date(self):
        item = NewsItem("Title", "https://x.com/a", "Snippet", None, "")
        text = _format_rss_item(item, 2)
        assert "2. 🌐 Title" in text
        assert "Snippet" in text

    def test_format_rss_item_uses_source_emoji(self):
        item = NewsItem("Habr News", "https://habr.com/1", "Summary", None, "habr.com")
        text = _format_rss_item(item, 1)
        assert "1. 💻 Habr News" in text

    def test_render_news_empty(self):
        assert render_news([]) == ""

    def test_render_news_capped_at_4096(self):
        items = [NewsItem("x" * 200, "https://x.com/a", "y" * 500) for _ in range(20)]
        text = render_news(items)
        assert len(text) <= 4096


class TestDedupe:
    def test_filter_unshown_without_db(self):
        items = [NewsItem("A", "https://a.com"), NewsItem("B", "https://b.com")]
        assert _filter_unshown(1, items, 5) == items

    def test_filter_unshown_with_db(self):
        items = [
            NewsItem("A", "https://a.com"),
            NewsItem("B", "https://b.com"),
            NewsItem("C", "https://c.com"),
        ]
        fake_db = MagicMock()
        fake_db.is_news_shown = lambda uid, url: url == "https://b.com"
        rss_module.db = fake_db
        try:
            assert _filter_unshown(1, items, 5) == [items[0], items[2]]
        finally:
            rss_module.db = None

    def test_filter_unshown_respects_limit(self):
        items = [NewsItem("A", f"https://a{i}.com") for i in range(10)]
        fake_db = MagicMock()
        fake_db.is_news_shown.return_value = False
        rss_module.db = fake_db
        try:
            assert len(_filter_unshown(1, items, 3)) == 3
        finally:
            rss_module.db = None

    def test_mark_shown_calls_db_for_each(self):
        items = [NewsItem("A", "https://a.com"), NewsItem("B", "https://b.com")]
        fake_db = MagicMock()
        rss_module.db = fake_db
        try:
            _mark_shown(1, items)
            assert fake_db.mark_news_shown.call_count == 2
            fake_db.mark_news_shown.assert_any_call(1, "https://a.com", "A")
        finally:
            rss_module.db = None

    def test_mark_shown_no_db_is_noop(self):
        rss_module.db = None
        _mark_shown(1, [NewsItem("A", "https://a.com")])


class TestParseFeeds:
    @pytest.mark.asyncio
    async def test_parse_feeds_filters_by_topic_and_recency(self, monkeypatch):
        now = datetime.now(timezone.utc)
        recent = now - timedelta(hours=1)
        old = now - timedelta(hours=100)

        async def _fake_fetch(session, url, timeout=15):
            return "<rss/>"

        def _fake_parse(raw):
            entries = [
                SimpleNamespace(
                    title="Apple news",
                    link="https://a.com/1",
                    summary="something",
                    published_parsed=recent.timetuple(),
                ),
                SimpleNamespace(
                    title="Samsung news",
                    link="https://a.com/2",
                    summary="else",
                    published_parsed=recent.timetuple(),
                ),
                SimpleNamespace(
                    title="Apple old",
                    link="https://a.com/3",
                    summary="old",
                    published_parsed=old.timetuple(),
                ),
            ]
            return SimpleNamespace(entries=entries)

        monkeypatch.setattr(rss_module, "_fetch_feed", _fake_fetch)
        monkeypatch.setattr(rss_module.feedparser, "parse", _fake_parse)
        monkeypatch.setattr(rss_module, "NEWS_LANGUAGE", "en")

        items = await _parse_feeds(["https://feed"], topic="apple", hours=48, limit=5)
        assert len(items) == 1
        assert items[0].title == "Apple news"

    @pytest.mark.asyncio
    async def test_parse_feeds_extracts_image_url(self, monkeypatch):
        async def _fake_fetch(session, url, timeout=15):
            return "<rss/>"

        def _fake_parse(raw):
            entries = [
                SimpleNamespace(
                    title="With image",
                    link="https://a.com/1",
                    summary="summary",
                    published_parsed=datetime.now(timezone.utc).timetuple(),
                    media_thumbnail=[{"url": "https://a.com/img.jpg"}],
                ),
                SimpleNamespace(
                    title="Without image",
                    link="https://a.com/2",
                    summary="summary",
                    published_parsed=datetime.now(timezone.utc).timetuple(),
                ),
            ]
            return SimpleNamespace(entries=entries)

        monkeypatch.setattr(rss_module, "_fetch_feed", _fake_fetch)
        monkeypatch.setattr(rss_module.feedparser, "parse", _fake_parse)
        monkeypatch.setattr(rss_module, "NEWS_LANGUAGE", "en")

        items = await _parse_feeds(["https://feed"], limit=5)
        assert len(items) == 2
        assert items[0].image_url == "https://a.com/img.jpg"
        assert items[1].image_url is None

    @pytest.mark.asyncio
    async def test_parse_feeds_deduplicates_links(self, monkeypatch):
        async def _fake_fetch(session, url, timeout=15):
            return "<rss/>"

        def _fake_parse(raw):
            entries = [
                SimpleNamespace(
                    title="A",
                    link="https://x.com/1",
                    summary="s1",
                    published_parsed=None,
                ),
                SimpleNamespace(
                    title="B",
                    link="https://x.com/1",
                    summary="s2",
                    published_parsed=None,
                ),
            ]
            return SimpleNamespace(entries=entries)

        monkeypatch.setattr(rss_module, "_fetch_feed", _fake_fetch)
        monkeypatch.setattr(rss_module.feedparser, "parse", _fake_parse)
        monkeypatch.setattr(rss_module, "NEWS_LANGUAGE", "en")

        items = await _parse_feeds(["https://feed"])
        assert len(items) == 1


class TestGetFreshNews:
    @pytest.mark.asyncio
    async def test_rss_hits_skip_web_fallback(self, monkeypatch):
        item = NewsItem("Title", "https://a.com", "Summary")
        monkeypatch.setattr(
            rss_module,
            "_parse_feeds",
            AsyncMock(return_value=[item]),
        )
        fallback = AsyncMock()
        monkeypatch.setattr(rss_module, "_web_fallback", fallback)
        monkeypatch.setattr(rss_module, "RSS_FEEDS", ["https://feed"])

        text, items, source = await get_fresh_news(1, topic="ai", limit=5)
        assert items == [item]
        assert source == "rss"
        assert "Title" in text
        fallback.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_rss_empty_uses_web_fallback(self, monkeypatch):
        fallback_item = NewsItem("Web Title", "https://web.com", "Web summary")
        captured = {}

        async def captured_web_fallback(user_id, query, limit=5, require_russian=True):
            captured["require_russian"] = require_russian
            return [fallback_item]

        monkeypatch.setattr(
            rss_module,
            "_parse_feeds",
            AsyncMock(return_value=[]),
        )
        monkeypatch.setattr(rss_module, "_web_fallback", captured_web_fallback)
        monkeypatch.setattr(rss_module, "RSS_FEEDS", ["https://feed"])
        monkeypatch.setattr(rss_module, "WEB_SEARCH_PROVIDER", "duckduckgo")

        text, items, source = await get_fresh_news(2, topic="криптовалюта", limit=5)
        assert items == [fallback_item]
        assert source == "duckduckgo"
        assert "Web Title" in text
        assert captured.get("require_russian") is True

    @pytest.mark.asyncio
    async def test_english_query_skips_russian_filter(self, monkeypatch):
        fallback_item = NewsItem("Steam News", "https://web.com/steam", "Steam snippet")
        captured = {}

        async def captured_web_fallback(user_id, query, limit=5, require_russian=True):
            captured["require_russian"] = require_russian
            return [fallback_item]

        monkeypatch.setattr(rss_module, "_parse_feeds", AsyncMock(return_value=[]))
        monkeypatch.setattr(rss_module, "_web_fallback", captured_web_fallback)
        monkeypatch.setattr(rss_module, "RSS_FEEDS", ["https://feed"])
        monkeypatch.setattr(rss_module, "WEB_SEARCH_PROVIDER", "duckduckgo")

        text, items, source = await get_fresh_news(2, topic="steam", limit=5)
        assert items == [fallback_item]
        assert captured.get("require_russian") is False


class TestWebFallback:
    @pytest.mark.asyncio
    async def test_duckduckgo_news_provider(self, monkeypatch):
        result = {
            "title": "DDG News",
            "url": "https://ddg.com/n",
            "body": "body text",
            "date": None,
        }
        monkeypatch.setattr(
            rss_module,
            "_search_duckduckgo_news",
            AsyncMock(return_value=[result]),
        )
        monkeypatch.setattr(rss_module, "WEB_SEARCH_PROVIDER", "duckduckgo")

        # English/brand queries bypass the Russian-language filter.
        items = await _web_fallback(1, "query", limit=5, require_russian=False)
        assert len(items) == 1
        assert items[0].title == "DDG News"
        assert items[0].url == "https://ddg.com/n"

    @pytest.mark.asyncio
    async def test_duckduckgo_text_fallback_when_news_empty(self, monkeypatch):
        monkeypatch.setattr(
            rss_module,
            "_search_duckduckgo_news",
            AsyncMock(return_value=[]),
        )
        text_result = {"title": "Text", "url": "https://t.com", "body": "b"}
        monkeypatch.setattr(
            rss_module,
            "_search_duckduckgo",
            AsyncMock(return_value=[text_result]),
        )
        monkeypatch.setattr(rss_module, "WEB_SEARCH_PROVIDER", "duckduckgo")

        items = await _web_fallback(1, "q", limit=5, require_russian=False)
        assert len(items) == 1
        assert items[0].title == "Text"

    @pytest.mark.asyncio
    async def test_web_fallback_filters_english_results_when_russian_required(
        self, monkeypatch
    ):
        result = {
            "title": "DDG News",
            "url": "https://ddg.com/n",
            "body": "body text",
            "date": None,
        }
        monkeypatch.setattr(
            rss_module,
            "_search_duckduckgo_news",
            AsyncMock(return_value=[result]),
        )
        monkeypatch.setattr(rss_module, "WEB_SEARCH_PROVIDER", "duckduckgo")

        items = await _web_fallback(1, "query", limit=5, require_russian=True)
        assert len(items) == 0
