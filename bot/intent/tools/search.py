from urllib.parse import urlparse

from bot.intent.schemas import ToolContext, ToolResult
from bot.intent.tools.base import BaseTool


def _extract_source(url: str) -> str:
    try:
        return urlparse(url).netloc.replace("www.", "")
    except Exception:
        return ""


def _clean_snippet(text: str, max_len: int = 220) -> str:
    if not text:
        return ""
    text = text.strip().replace("\n", " ")
    if len(text) > max_len:
        text = text[:max_len].rsplit(" ", 1)[0] + "..."
    return text


def _format_search_item(item: dict, idx: int) -> str:
    """Format a single web-search result as a clean copy-paste block.

    Layout:
    {idx}. {title}
    🌐 {source}
    {snippet}
    🔗 {url}
    """
    title = item.get("title", "Без названия").strip()
    url = item.get("url", item.get("href", "")).strip()
    body = item.get("body") or item.get("content") or item.get("snippet", "")
    source = item.get("source") or _extract_source(url)

    lines: list[str] = [f"{idx}. {title}"]
    if source:
        lines.append(f"   🌐 {source}")
    snippet = _clean_snippet(body)
    if snippet:
        lines.append(f"   {snippet}")
    if url:
        lines.append(f"   🔗 {url}")
    return "\n".join(lines)


def _format_results(query: str, items: list[dict], header: str) -> str:
    """Render web-search results as a clean Telegram message."""
    if not items:
        return ""
    text = f"{header} {query}\n\n" if query else f"{header}\n\n"
    blocks: list[str] = []
    for i, item in enumerate(items[:5], 1):
        blocks.append(_format_search_item(item, i))
        blocks.append("")
    text += "\n".join(blocks)
    return text[:4096]


class SearchTool(BaseTool):
    name = "search"
    required_args = ("query",)

    async def execute(self, context: ToolContext) -> ToolResult:
        query = (context.args.query or context.message_text).strip()
        if not query:
            return ToolResult(text="🔍 Что искать?", success=False)
        from bot.routers.common import ollama_web_search
        result, error = await ollama_web_search(query, max_results=5)
        if error:
            return ToolResult(text=f"❌ Ошибка поиска: {error}", success=False)
        items = (result or {}).get("results", [])
        if not items:
            return ToolResult(text="Ничего не найдено.")
        return ToolResult(text=_format_results(query, items, "🔍"))


class NewsTool(BaseTool):
    name = "news"
    required_args = ()

    async def execute(self, context: ToolContext) -> ToolResult:
        from bot.services.rss_news import get_fresh_news
        topic = (context.args.query or "").strip()
        text, _items, source = await get_fresh_news(
            context.user_id, topic=topic or None, limit=5
        )
        if not text:
            return ToolResult(
                text=f"По запросу «{topic or 'новости'}» ничего не найдено."
            )
        footer = f"\n\n(источник: {source})" if source else ""
        full_text = text + footer
        if len(full_text) > 4096:
            full_text = full_text[:4090] + "..."
        return ToolResult(text=full_text)
