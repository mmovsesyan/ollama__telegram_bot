from urllib.parse import urlparse

from bot.intent.schemas import ToolContext, ToolResult
from bot.intent.tools.base import BaseTool


def _format_results(query: str, items: list[dict], header: str) -> str:
    # Late import to avoid circular: cron imports services indirectly.
    from bot.routers.cron import _extract_main_text
    text = f"{header} {query}\n\n" if query else f"{header}\n\n"
    for i, item in enumerate(items[:5], 1):
        title = item.get("title", "Без названия")
        url = item.get("url", "")
        # Use the same noise-stripped excerpt logic as legacy /search,
        # so smart-pipeline results match what users get from button-search.
        snippet = _extract_main_text(item.get("content", ""), max_len=200)
        source = ""
        if url:
            try:
                source = f" ({urlparse(url).netloc.replace('www.', '')})"
            except Exception:
                pass
        text += f"{i}. {title}{source}\n"
        if snippet:
            text += f"   {snippet}\n"
        if url:
            text += f"   {url}\n"
        text += "\n"
    return text[:4096]


class SearchTool(BaseTool):
    name = "search"
    required_args = ("query",)

    async def execute(self, context: ToolContext) -> ToolResult:
        query = (context.args.query or context.message_text).strip()
        if not query:
            return ToolResult(text="🔍 Что искать?", success=False)
        from bot.routers.cron import ollama_web_search
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
        from bot.routers.cron import ollama_web_search
        # If the LLM extracted a topic ("новости про ИИ" → query="ИИ"),
        # use it. Otherwise fall back to the generic top-news search.
        topic = (context.args.query or "").strip()
        if topic:
            query = topic
            header = f"📰 Новости: {topic}"
        else:
            query = "последние новости сегодня"
            header = "📰 Топ-новости"
        result, error = await ollama_web_search(query, max_results=5)
        if error:
            return ToolResult(text=f"❌ {error}", success=False)
        items = (result or {}).get("results", [])
        if not items:
            return ToolResult(text=f"По запросу «{topic or 'новости'}» ничего не найдено.")
        return ToolResult(text=_format_results("", items, header))
