"""News category subscription management and personalized digests.

Users subscribe to slugs like `tech`, `markets`, `ai`. The bot builds a
per-category query, fetches fresh items, and then re-ranks them with a
lightweight keyword/quality score so the most relevant articles win.
"""

import logging
from typing import Any

from bot.services import rss_news as rss_news_service

logger = logging.getLogger(__name__)

db: Any = None  # injected at startup

CATEGORY_TOPICS = {
    "tech": "технологии ИИ стартапы",
    "markets": "рынки акции финансы инвестиции",
    "ai": "искусственный интеллект нейросети",
    "science": "наука космос исследования",
    "crypto": "криптовалюта биткоин блокчейн",
    "world": "мир политика события",
    "games": "игры Steam консоли гейминг",
}

# Sources preferred over aggregator/no-name domains.
_SOURCE_QUALITY = {
    "habr.com": 3,
    "vc.ru": 3,
    "cnews.ru": 3,
    "kommersant.ru": 3,
    "vedomosti.ru": 3,
    "bloomberg.com": 3,
    "reuters.com": 3,
    "ft.com": 3,
    "wsj.com": 3,
    "tadviser.ru": 2,
    "iguides.ru": 2,
    "lenta.ru": 2,
    "rbc.ru": 2,
    "techcrunch.com": 2,
    "theverge.com": 2,
    "igromania.ru": 2,
    "stopgame.ru": 2,
    "dtf.ru": 2,
    "kanobu.ru": 2,
    "bbc.co.uk": 2,
    "bbc.com": 2,
    "meduza.io": 2,
}


def _user_categories(user_id: int) -> list[str]:
    if db is None:
        return list(CATEGORY_TOPICS.keys())[:3]
    try:
        prefs = db.get_user_prefs(user_id) or {}
    except Exception:
        return list(CATEGORY_TOPICS.keys())[:3]
    raw = prefs.get("news_categories") or "tech,markets,ai"
    return [c.strip().lower() for c in raw.split(",") if c.strip().lower()]


def _topic_for_category(cat: str) -> str:
    return CATEGORY_TOPICS.get(cat, cat)


def _score_item(item: rss_news_service.NewsItem, cat: str) -> float:
    """Quality score combining source reputation, recency, and category match."""
    score = 0.0
    source = (item.source or "").lower()
    for domain, bonus in _SOURCE_QUALITY.items():
        if domain in source:
            score += bonus
            break

    if item.published:
        from datetime import datetime, timezone
        age_hours = (datetime.now(timezone.utc) - item.published).total_seconds() / 3600
        if age_hours <= 6:
            score += 2
        elif age_hours <= 24:
            score += 1

    topic = _topic_for_category(cat)
    combined = f"{item.title} {item.summary}".lower()
    for word in topic.split():
        if word in combined:
            score += 0.5
    return score


async def get_personalized_digest(
    user_id: int,
    categories: list[str] | None = None,
    items_per_category: int = 3,
) -> str:
    """Build a personal news digest across the user's categories."""
    cats = categories or _user_categories(user_id)
    if not cats:
        cats = ["tech"]

    blocks: list[str] = ["📰 Персональный дайджест", ""]
    has_any = False
    for cat in cats:
        topic = _topic_for_category(cat)
        try:
            text, items, source = await rss_news_service.get_fresh_news(
                user_id,
                topic=topic,
                limit=items_per_category * 2,
            )
        except Exception as e:
            logger.warning("[NEWS_CAT] failed for %s: %s", cat, e)
            continue
        if not items:
            continue

        ranked = sorted(items, key=lambda item: _score_item(item, cat), reverse=True)
        top = ranked[:items_per_category]
        blocks.append(f"📌 {cat.upper()}")
        for i, item in enumerate(top, 1):
            blocks.append(rss_news_service._format_rss_item(item, i))
            blocks.append("")
        has_any = True

    if not has_any:
        return "📰 По твоим категориям сейчас ничего не нашёл. Попробуй позже или расширь список в /settings."
    return "\n".join(blocks)[:4096]


def _normalize_category(cat: str) -> str:
    cat = cat.strip().lower()
    if cat in CATEGORY_TOPICS:
        return cat
    aliases = {
        "технологии": "tech",
        "акции": "markets",
        "финансы": "markets",
        "рынки": "markets",
        "ии": "ai",
        "искусственный интеллект": "ai",
        "наука": "science",
        "крипта": "crypto",
        "биткоин": "crypto",
        "мир": "world",
        "игры": "games",
        "игровые": "games",
        "steam": "games",
        "гейминг": "games",
    }
    return aliases.get(cat, cat)


def set_user_categories(user_id: int, categories: list[str]) -> list[str]:
    """Persist normalized category list for the user."""
    normalized = []
    for c in categories:
        nc = _normalize_category(c)
        if nc in CATEGORY_TOPICS and nc not in normalized:
            normalized.append(nc)
    if db is None:
        return normalized
    db.set_user_prefs(user_id, news_categories=",".join(normalized))
    return normalized


def add_user_category(user_id: int, category: str) -> tuple[list[str], bool]:
    """Add a category to the user's subscriptions. Returns (new_list, added)."""
    current = _user_categories(user_id)
    cat = _normalize_category(category)
    if cat not in CATEGORY_TOPICS:
        return current, False
    if cat in current:
        return current, False
    new_list = current + [cat]
    set_user_categories(user_id, new_list)
    return new_list, True


def remove_user_category(user_id: int, category: str) -> tuple[list[str], bool]:
    """Remove a category from the user's subscriptions. Returns (new_list, removed)."""
    current = _user_categories(user_id)
    cat = _normalize_category(category)
    if cat not in current:
        return current, False
    new_list = [c for c in current if c != cat]
    if not new_list:
        new_list = ["tech"]
    set_user_categories(user_id, new_list)
    return new_list, True
