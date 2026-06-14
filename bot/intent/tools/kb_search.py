from bot.intent.schemas import ToolContext, ToolResult
from bot.intent.tools.base import BaseTool


class KbSearchTool(BaseTool):
    """Knowledge base search: matches against the user's stored memories
    first, falls back to web search if nothing local matches.

    Triggers via free-form intent ("что я говорил про X", "найди у меня
    про X", "из моей базы X") or via the dedicated 📚 База button."""

    name = "kb_search"
    required_args = ("query",)

    async def execute(self, context: ToolContext) -> ToolResult:
        query = (context.args.query or context.message_text or "").strip()
        if not query:
            return ToolResult(
                text="📚 Что найти в базе? Скажи слово или фразу.",
                success=False,
            )
        # Strip kb-trigger phrases so we search the actual subject.
        for prefix in (
            "найди у меня про ",
            "что я говорил про ",
            "что у меня про ",
            "из моей базы ",
            "в моей базе ",
            "найди в базе ",
            "поищи в базе ",
            "из базы ",
        ):
            if query.lower().startswith(prefix):
                query = query[len(prefix):]
                break

        from bot.services.kb import search_kb_with_web_fallback
        text, hits, used_web = await search_kb_with_web_fallback(
            context.user_id, query, limit=5
        )
        if not text:
            return ToolResult(
                text=f"📚 Ни в твоей базе, ни в интернете ничего по «{query}» не нашёл.",
            )
        return ToolResult(text=text, extra={"used_web": used_web, "hits": len(hits)})
