"""Knowledge base search, summary, and web fallback."""

import asyncio
import logging
from typing import Any
from urllib.parse import urlparse

from bot.ollama import OllamaChatMessage, generate_chat_completion
from bot.ollama.dto import OllamaErrorChunk
from bot.settings import OLLAMA_MODEL

# Forward-declared db reference; set by bot.__init__ at startup.
db: Any = None

logger = logging.getLogger(__name__)

_MAX_SUMMARY_MEMORIES = 50
_MAX_SUMMARY_CHARS = 4000


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


def _format_memory_for_summary(m: dict, idx: int) -> str:
    cat = m.get("category", "fact")
    content = m.get("summary") or m.get("content") or ""
    return f"{idx}. [{cat}] {content.strip()}"


async def summarize_kb(user_id: int) -> str:
    """Generate a short Russian profile summary from the user's memories.

    Uses the local Ollama model. Falls back gracefully if the model is
    unavailable or the user has too few memories.
    """
    if db is None:
        return "⚠️ База данных недоступна."
    try:
        memories = db.get_memories(user_id)
    except Exception as e:
        logger.warning("[KB SUMMARY] failed to load memories for %s: %s", user_id, e)
        return "⚠️ Не удалось загрузить память."

    if not memories or len(memories) < 3:
        return "🧠 Пока недостаточно данных для профиля. Сохрани несколько фактов через /memory."

    memories = memories[:_MAX_SUMMARY_MEMORIES]
    lines = [_format_memory_for_summary(m, i) for i, m in enumerate(memories, 1)]
    memories_text = "\n".join(lines)
    if len(memories_text) > _MAX_SUMMARY_CHARS:
        memories_text = memories_text[:_MAX_SUMMARY_CHARS].rsplit("\n", 1)[0] + "\n..."

    prompt = (
        "Ты — личный ассистент. На основе записей о пользователе составь краткий профиль "
        "на русском языке: 5–7 пунктов, без воды. Сгруппируй факты по темам "
        "(чем занимается, интересы, предпочтения, важные заметки).\n\n"
        f"ЗАПИСИ:\n{memories_text}\n\n"
        "ПРОФИЛЬ:"
    )

    messages = [OllamaChatMessage(role="user", content=prompt)]
    output = ""
    try:
        async with asyncio.timeout(60):
            async for is_done, chunk in generate_chat_completion(
                messages, OLLAMA_MODEL, temperature=0.4
            ):
                if is_done:
                    break
                if isinstance(chunk, OllamaErrorChunk):
                    logger.warning("[KB SUMMARY] LLM error: %s", chunk.error)
                    return "⚠️ Модель вернула ошибку. Попробуй позже."
                output += chunk.message.content
    except asyncio.TimeoutError:
        logger.info("[KB SUMMARY] timed out for user_id=%s", user_id)
        return "⚠️ Модель долго думает. Попробуй позже."
    except Exception as e:
        logger.warning("[KB SUMMARY] failed for user_id=%s: %s", user_id, e)
        return "⚠️ Не удалось составить профиль. Попробуй позже."

    summary = output.strip()
    if not summary:
        return "⚠️ Модель вернула пустой ответ. Попробуй позже."
    return f"🧠 Профиль на основе памяти:\n\n{summary[:3500]}"


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
        except ValueError as exc:
            logger.debug("Failed to parse web result URL %r: %s", url, exc)

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
        from bot.routers.common import ollama_web_search
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
