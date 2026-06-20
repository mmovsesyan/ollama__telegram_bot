"""RSS-based news aggregator with optional DuckDuckGo / Ollama / SearXNG fallback.

The goal is to give the bot a stable source of fresh, Russian-language tech/business
news without relying solely on Ollama's web_search endpoint, which tends to return
the same generic results (e.g. Wiktionary, RBC, dp.ru) for short queries.

Architecture:
- Fetch a configurable list of RSS feeds.
- Filter by recency (default 48h), topic keywords, and language.
- De-duplicate against already-shown URLs per user (stored in SQLite).
- If RSS yields nothing, fall back to a web-search provider.
- Format results as Telegram-friendly snippets.
"""

import asyncio
import html
import logging
import re
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import urlparse

import aiohttp
import feedparser

from bot.settings import (
    DUCKDUCKGO_REGION,
    NEWS_LANGUAGE,
    RSS_FEEDS,
    RSS_NEWS_HOURS,
    RSS_TOPIC_FEEDS,
    SEARXNG_URL,
    WEB_SEARCH_PROVIDER,
)

logger = logging.getLogger(__name__)

db: Any = None  # injected at startup by bot.__init__


class NewsItem:
    def __init__(
        self,
        title: str,
        url: str,
        summary: str = "",
        published: datetime | None = None,
        source: str = "",
        image_url: str | None = None,
    ):
        self.title = title.strip()
        self.url = url.strip()
        self.summary = summary.strip()
        self.published = published
        self.source = source.strip()
        self.image_url = image_url.strip() if image_url else None

    def to_dict(self) -> dict:
        return {
            "title": self.title,
            "url": self.url,
            "summary": self.summary,
            "published": self.published.isoformat() if self.published else None,
            "source": self.source,
            "image_url": self.image_url,
        }


def _clean_text(text: str | None, max_len: int = 300) -> str:
    if not text:
        return ""
    text = html.unescape(text)
    # Strip HTML tags conservatively.
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) > max_len:
        text = text[:max_len].rsplit(" ", 1)[0] + "..."
    return text


def _parse_rss_date(entry: Any) -> datetime | None:
    """Best-effort parse of RSS/Atom published date."""
    for attr in ("published_parsed", "updated_parsed", "created_parsed"):
        value = getattr(entry, attr, None)
        if value:
            try:
                # feedparser returns time.struct_time in UTC.
                return datetime(*value[:6], tzinfo=timezone.utc)
            except (TypeError, ValueError) as exc:
                logger.debug(
                    "Failed to parse RSS date %s for %s: %s",
                    attr,
                    getattr(entry, "link", ""),
                    exc,
                )
    # Fallback: try raw strings.
    for attr in ("published", "updated", "created", "date"):
        raw = getattr(entry, attr, None)
        if raw:
            try:
                dt = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                return dt
            except ValueError as exc:
                logger.debug("Failed to parse RSS raw date %s %r: %s", attr, raw, exc)
    return None


def _extract_source_from_url(url: str) -> str:
    try:
        domain = urlparse(url).netloc.replace("www.", "")
        return domain
    except ValueError as exc:
        logger.debug("Failed to parse source URL %r: %s", url, exc)
        return ""


def _is_recent(published: datetime | None, hours: int) -> bool:
    if published is None:
        # Accept entries without a date; caller may decide to drop them.
        return True
    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
    return published >= cutoff


def _extract_image_url(entry: Any) -> str | None:
    """Try common RSS/Atom image sources: media:thumbnail, media:content,
    enclosure, og:image via description, image."""
    try:
        # feedparser exposes media:thumbnail as entry.media_thumbnail list
        media = getattr(entry, "media_thumbnail", None) or []
        if media:
            return media[0].get("url") or media[0].get("href")
    except (AttributeError, KeyError, TypeError) as exc:
        logger.debug(
            "Failed to read media_thumbnail for %s: %s", getattr(entry, "link", ""), exc
        )
    try:
        content = getattr(entry, "media_content", None) or []
        for c in content:
            if c.get("type", "").startswith("image/"):
                return c.get("url") or c.get("href")
    except (AttributeError, KeyError, TypeError) as exc:
        logger.debug(
            "Failed to read media_content for %s: %s", getattr(entry, "link", ""), exc
        )
    try:
        enc = getattr(entry, "enclosures", None) or []
        for e in enc:
            if (e.get("type") or "").startswith("image/"):
                return e.get("href") or e.get("url")
    except (AttributeError, KeyError, TypeError) as exc:
        logger.debug(
            "Failed to read enclosures for %s: %s", getattr(entry, "link", ""), exc
        )
    try:
        return getattr(entry, "image", None) or None
    except (AttributeError, TypeError) as exc:
        logger.debug(
            "Failed to read entry image for %s: %s", getattr(entry, "link", ""), exc
        )
    return None


def _matches_topic(text: str, topic: str | None) -> bool:
    if not topic:
        return True
    topic = topic.lower().strip()
    if not topic:
        return True
    # Multi-word topics are matched as a phrase or by whole words; single-word
    # topics require a whole-word match. This prevents short Russian substrings
    # like "ии" from matching inside unrelated words ("отношении", "российских").
    words = topic.split()
    text_lower = text.lower()
    if len(words) == 1:
        return bool(re.search(rf"\b{re.escape(topic)}\b", text_lower))
    if topic in text_lower:
        return True
    return all(bool(re.search(rf"\b{re.escape(word)}\b", text_lower)) for word in words)


def _looks_russian(text: str) -> bool:
    """Heuristic: enough Cyrillic to treat as Russian-language content."""
    if not text:
        return False
    cyrillic = sum(1 for ch in text if "Ѐ" <= ch <= "ӿ")
    return cyrillic > max(3, len(text) * 0.05)


def _looks_like_english_query(text: str | None) -> bool:
    """Return True when the query is Latin-script (English/brand names/etc.)."""
    if not text:
        return False
    cleaned = re.sub(r"[^\w\s]", "", text)
    if not cleaned:
        return False
    latin = sum(1 for ch in cleaned if ch.isascii() and ch.isalpha())
    cyrillic = sum(1 for ch in cleaned if "Ѐ" <= ch <= "ӿ")
    return latin > 0 and cyrillic == 0


async def _fetch_feed(
    session: aiohttp.ClientSession, url: str, timeout: int = 15
) -> str | None:
    try:
        async with session.get(
            url, timeout=aiohttp.ClientTimeout(total=timeout)
        ) as resp:
            if resp.status == 200:
                return await resp.text()
            logger.warning("[RSS] %s returned HTTP %s", url, resp.status)
    except Exception as e:
        logger.warning("[RSS] Failed to fetch %s: %s", url, e)
    return None


def _feeds_for_topic(topic: str | None) -> list[str]:
    """Return topic-tuned feeds if a topic hints at a known category.

    Falls back to the full RSS_FEEDS list for generic or unknown topics.
    """
    if not topic:
        return RSS_FEEDS
    lowered = topic.lower().strip()
    # Exact topic match first.
    exact = RSS_TOPIC_FEEDS.get(lowered)
    if exact:
        return exact
    # Multi-word topic: if any known keyword appears, union matching feeds.
    matched: set[str] = set()
    for keyword, urls in RSS_TOPIC_FEEDS.items():
        if keyword in lowered:
            matched.update(urls)
    return list(matched) if matched else RSS_FEEDS


async def _parse_feeds(
    feed_urls: list[str],
    topic: str | None = None,
    hours: int = RSS_NEWS_HOURS,
    limit: int = 20,
    require_russian: bool = True,
) -> list[NewsItem]:
    items: list[NewsItem] = []
    seen_urls: set[str] = set()
    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)

    async with aiohttp.ClientSession() as session:
        tasks = [_fetch_feed(session, url) for url in feed_urls]
        raw_feeds = await asyncio.gather(*tasks)

    for url, raw in zip(feed_urls, raw_feeds):
        if not raw:
            continue
        try:
            parsed = feedparser.parse(raw)
        except Exception as e:
            logger.warning("[RSS] Parse error for %s: %s", url, e)
            continue

        for entry in parsed.entries:
            title = _clean_text(getattr(entry, "title", None), max_len=300)
            link = getattr(entry, "link", None)
            if not title or not link:
                continue
            if link in seen_urls:
                continue
            seen_urls.add(link)

            summary = _clean_text(
                getattr(entry, "summary", None) or getattr(entry, "description", None),
                max_len=400,
            )
            published = _parse_rss_date(entry)
            if published and published < cutoff:
                continue

            combined = f"{title} {summary}"
            if (
                require_russian
                and NEWS_LANGUAGE == "ru"
                and not _looks_russian(combined)
            ):
                continue
            if not _matches_topic(combined, topic):
                continue

            source = _extract_source_from_url(link)
            image_url = _extract_image_url(entry)
            items.append(NewsItem(title, link, summary, published, source, image_url))

    # Sort by recency, newest first, and cap early so downstream filters work on a bounded set.
    items.sort(
        key=lambda x: x.published or datetime.min.replace(tzinfo=timezone.utc),
        reverse=True,
    )
    return items[:limit]


def _filter_unshown(user_id: int, items: list[NewsItem], limit: int) -> list[NewsItem]:
    if db is None:
        return items[:limit]
    fresh: list[NewsItem] = []
    for item in items:
        if db.is_news_shown(user_id, item.url):
            continue
        fresh.append(item)
        if len(fresh) >= limit:
            break
    return fresh


def _mark_shown(user_id: int, items: list[NewsItem]) -> None:
    if db is None:
        return
    for item in items:
        try:
            db.mark_news_shown(user_id, item.url, item.title)
        except Exception as exc:
            logger.warning(
                "Failed to mark news shown for %s %r: %s", user_id, item.url, exc
            )


def _source_emoji(source: str) -> str:
    """Small visual source hint."""
    if not source:
        return "🌐"
    domain = source.lower()
    if any(d in domain for d in ("habr.com", "vc.ru")):
        return "💻"
    if any(d in domain for d in ("cnews.ru", "ixbt.com", "iguides.ru")):
        return "📡"
    if any(
        d in domain
        for d in (
            "kommersant.ru",
            "vedomosti.ru",
            "rbc.ru",
            "bloomberg.com",
            "reuters.com",
            "ft.com",
            "wsj.com",
        )
    ):
        return "📈"
    if "meduza.io" in domain:
        return "🗞"
    if any(d in domain for d in ("bbc.com", "bbc.co.uk")):
        return "📻"
    if any(d in domain for d in ("igromania.ru", "stopgame.ru", "dtf.ru", "kanobu.ru")):
        return "🎮"
    if any(d in domain for d in ("techcrunch.com", "theverge.com")):
        return "🔬"
    return "🌐"


def _format_rss_item(item: NewsItem, idx: int) -> str:
    """Format a single news item as a compact rich card.

    Layout:
    {idx}. {emoji} {title}
    🕐 {date} · 🌐 {source}
    {snippet}
    🔗 {url}
    """
    lines: list[str] = [f"{idx}. {_source_emoji(item.source)} {item.title}"]

    meta_parts: list[str] = []
    if item.published:
        try:
            date_str = item.published.strftime("%d %b · %H:%M")
        except Exception:
            date_str = str(item.published)[:16]
        meta_parts.append(f"🕐 {date_str}")
    if item.source:
        meta_parts.append(f"🌐 {item.source}")
    if meta_parts:
        lines.append("   " + " · ".join(meta_parts))

    if item.summary:
        snippet = item.summary[:180]
        if len(item.summary) > 180:
            snippet = snippet.rsplit(" ", 1)[0] + "..."
        lines.append(f"   {snippet}")

    if item.url:
        lines.append(f"   🔗 {item.url}")

    return "\n".join(lines)


def render_news(items: list[NewsItem], header: str = "📰 Новости") -> str:
    """Render a list of news items into a clean Telegram message."""
    if not items:
        return ""
    blocks: list[str] = [f"*{header}*", ""]
    for i, item in enumerate(items, 1):
        blocks.append(_format_rss_item(item, i))
        blocks.append("")
    return "\n".join(blocks)[:4096]


async def _search_duckduckgo(
    query: str,
    max_results: int = 5,
    timelimit: str = "d",
    region: str | None = None,
) -> list[dict]:
    """Run DuckDuckGo text search and normalize results."""
    try:
        from duckduckgo_search import DDGS
    except Exception as e:
        logger.warning("[DDG] duckduckgo_search not available: %s", e)
        return []

    try:
        with DDGS() as ddgs:
            results = ddgs.text(
                query,
                region=region or DUCKDUCKGO_REGION,
                safesearch="off",
                timelimit=timelimit,
                max_results=max_results,
            )
            return list(results or [])
    except Exception as e:
        logger.warning("[DDG] Search failed: %s", e)
        return []


async def _search_duckduckgo_news(
    query: str,
    max_results: int = 5,
    timelimit: str = "d",
    region: str | None = None,
) -> list[dict]:
    """Run DuckDuckGo news search and normalize results."""
    try:
        from duckduckgo_search import DDGS
    except Exception as e:
        logger.warning("[DDG] duckduckgo_search not available: %s", e)
        return []

    try:
        with DDGS() as ddgs:
            results = ddgs.news(
                query,
                region=region or DUCKDUCKGO_REGION,
                safesearch="off",
                timelimit=timelimit,
                max_results=max_results,
            )
            return list(results or [])
    except Exception as e:
        logger.warning("[DDG] News search failed: %s", e)
        return []


async def _search_ollama(query: str, max_results: int = 5) -> list[dict]:
    try:
        from bot.routers.cron import ollama_web_search
    except Exception as e:
        logger.warning("[OllamaSearch] import failed: %s", e)
        return []
    result, error = await ollama_web_search(query, max_results=max_results)
    if error or not result:
        return []
    return list((result or {}).get("results", []))


async def _search_searxng(query: str, max_results: int = 5) -> list[dict]:
    if not SEARXNG_URL:
        return []
    params = {
        "q": query,
        "format": "json",
        "language": NEWS_LANGUAGE,
        "time_range": "day",
    }
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                f"{SEARXNG_URL}/search",
                params=params,
                timeout=aiohttp.ClientTimeout(total=20),
            ) as resp:
                if resp.status != 200:
                    return []
                data = await resp.json()
                return list((data or {}).get("results", []))[:max_results]
    except Exception as e:
        logger.warning("[SearXNG] search failed: %s", e)
        return []


async def _web_fallback(
    user_id: int,
    query: str,
    limit: int = 5,
    require_russian: bool = True,
) -> list[NewsItem]:
    """Try configured web-search providers in priority order."""
    provider = WEB_SEARCH_PROVIDER
    results: list[dict] = []

    # For English/brand queries, search worldwide and widen the time window.
    region = "wt-wt" if not require_russian else DUCKDUCKGO_REGION
    timelimit = "w" if not require_russian else "d"

    if provider == "duckduckgo":
        results = await _search_duckduckgo_news(
            query, max_results=limit, timelimit=timelimit, region=region
        )
        if not results:
            results = await _search_duckduckgo(
                query, max_results=limit, timelimit=timelimit, region=region
            )
    elif provider == "searxng":
        results = await _search_searxng(query, max_results=limit)
    elif provider == "ollama":
        results = await _search_ollama(query, max_results=limit)
    else:
        # Unknown provider: try DuckDuckGo as safe default.
        results = await _search_duckduckgo_news(
            query, max_results=limit, timelimit=timelimit, region=region
        )

    items: list[NewsItem] = []
    seen: set[str] = set()
    for r in results:
        url = r.get("url") or r.get("href", "")
        if not url or url in seen:
            continue
        seen.add(url)
        title = _clean_text(r.get("title", "Без названия"))
        summary = _clean_text(r.get("body") or r.get("content", ""), max_len=400)
        if (
            require_russian
            and NEWS_LANGUAGE == "ru"
            and not _looks_russian(f"{title} {summary}")
        ):
            continue
        source = r.get("source") or _extract_source_from_url(url)
        published = None
        if r.get("date"):
            published = _parse_rss_date(r)
        items.append(NewsItem(title, url, summary, published, source))

    return _filter_unshown(user_id, items, limit)


async def get_fresh_news(
    user_id: int,
    topic: str | None = None,
    limit: int = 5,
    hours: int = RSS_NEWS_HOURS,
) -> tuple[str, list[NewsItem], str]:
    """Return (rendered_text, items, source_label) for the freshest news.

    - First tries RSS feeds with topic/time filters and per-user de-duplication.
    - If RSS returns nothing fresh/unseen, falls back to web search.
    - Marks returned items as shown in the DB.
    """
    items: list[NewsItem] = []
    source = "rss"

    # For English/brand queries (e.g. "steam", "Tesla", "AI") don't require
    # Russian language, otherwise most web/RSS results get filtered out.
    require_russian = not _looks_like_english_query(topic)

    feed_urls = _feeds_for_topic(topic)
    if feed_urls:
        items = await _parse_feeds(
            feed_urls, topic=topic, hours=hours, require_russian=require_russian
        )
        items = _filter_unshown(user_id, items, limit)

    if not items:
        query = topic.strip() if topic else "последние новости"
        items = await _web_fallback(
            user_id, query, limit=limit, require_russian=require_russian
        )
        source = (
            WEB_SEARCH_PROVIDER
            if WEB_SEARCH_PROVIDER in ("duckduckgo", "searxng", "ollama")
            else "duckduckgo"
        )

    if items:
        _mark_shown(user_id, items)

    header = f"📰 Новости: {topic}" if topic else "📰 Топ-новости"
    text = render_news(items, header=header)
    return text, items, source
