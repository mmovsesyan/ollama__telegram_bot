"""Knowledge base search: full-text over user's memories with web fallback."""

from typing import Any
from urllib.parse import urlparse

# Forward-declared db reference; set by bot.__init__ at startup.
db: Any = None


def _format_hit(hit: dict, idx: int) -> str:
    cat_names = {"fact": "📌", "preference": "❤️", "note": "📝"}
    cat_icon = cat_names.get(hit.get("category", ""), "•")
    text = hit.get("summary") or hit.get("content") or ""
    if len(text) > 300:
        text = text[:300].rsplit(" ", 1)[0] + "..."
    return f"{idx}. {cat_icon} {text}"


def render_kb_results(query: str, hits: list[dict]) -> str:
    if not hits:
        return ""
    lines = [f"📚 Из твоей базы по запросу «{query}»:", ""]
    for i, hit in enumerate(hits, 1):
        lines.append(_format_hit(hit, i))
    return "\n".join(lines)


def search_kb(user_id: int, query: str, limit: int = 5) -> list[dict]:
    """Search the user's knowledge base. Empty list if nothing or db unset."""
    if db is None:
        return []
    return db.search_memories(user_id, query, limit=limit)


def _format_web_fallback_item(item: dict, idx: int) -> str:
    """Format a web result in the same clean style as search/news."""
    title = item.get("title", "Без названия").strip()
    url = item.get("url", "").strip()
    body = item.get("body") or item.get("content") or item.get("snippet", "")
    snippet = body.strip().replace("\n", " ")
    if len(snippet) > 220:
        snippet = snippet[:220].rsplit(" ", 1)[0] + "..."
    source = ""
    if url:
        try:
            source = f"🌐 {urlparse(url).netloc.replace('www.', '')}"
        except Exception:
            pass

    lines = [f"{idx}. {title}"]
    if source:
        lines.append(f"   {source}")
    if snippet:
        lines.append(f"   {snippet}")
    if url:
        lines.append(f"   🔗 {url}")
    return "\n".join(lines)


async def search_kb_with_web_fallback(
    user_id: int,
    query: str,
    limit: int = 5,
) -> tuple[str, list[dict], bool]:
    """KB-first search. Returns (rendered_text, hits, used_web).

    - hits: rows from the user's memories (may be empty).
    - used_web: True if we attempted a web fallback (regardless of whether
      it returned anything). False only when the KB had hits OR the web
      call itself errored.
    - rendered_text: human-readable result, or empty string if even web
      came back empty.
    """
    hits = search_kb(user_id, query, limit=limit)
    if hits:
        return render_kb_results(query, hits), hits, False

    # KB empty — fall back to web search via the existing helper.
    try:
        from bot.routers.cron import ollama_web_search
    except Exception:
        return "", [], False

    result, error = await ollama_web_search(query, max_results=limit)
    if error:
        # Web errored (no API key, network, etc) — still tell caller we
        # tried so the user can be told both sources are empty.
        return "", [], True
    items = (result or {}).get("results", [])
    if not items:
        return "", [], True

    lines = ["📚 В твоей базе ничего не нашёл, посмотрел в интернете:", ""]
    for i, item in enumerate(items[:limit], 1):
        lines.append(_format_web_fallback_item(item, i))
        lines.append("")
    return "\n".join(lines)[:4096], [], True
