from bot.intent.schemas import ToolContext, ToolResult
from bot.intent.tools.base import BaseTool


class NoteTool(BaseTool):
    name = "note"
    required_args = ("content",)

    async def execute(self, context: ToolContext) -> ToolResult:
        content = (context.args.content or context.message_text).strip()
        if not content:
            return ToolResult(text="📝 Что записать?", success=False)
        if context.db is None:
            return ToolResult(text="База данных недоступна.", success=False)
        context.db.add_note(context.user_id, content)
        _refresh_active_chat_system_prompt(context.user_id)
        return ToolResult(text=f"✅ Заметка сохранена.\n\n📝 {content}")


class MemoryTool(BaseTool):
    name = "memory"
    required_args = ("content",)

    async def execute(self, context: ToolContext) -> ToolResult:
        content = (context.args.content or "").strip()
        if not content:
            return ToolResult(text="🧠 Что запомнить?", success=False)
        if context.db is None:
            return ToolResult(text="База данных недоступна.", success=False)
        # Late import to avoid circular: cron.py imports services, which imports tools.
        from bot.routers.cron import _classify_memory

        category = await _classify_memory(content)
        mid = context.db.add_memory(context.user_id, category, content)
        _refresh_active_chat_system_prompt(context.user_id)
        cat_names = {
            "fact": "📌 Факт",
            "preference": "❤️ Предпочтение",
            "note": "📝 Заметка",
        }
        return ToolResult(
            text=f"✅ Сохранено: {cat_names.get(category, category)}\n#{mid} | {content}",
        )


def _refresh_active_chat_system_prompt(user_id: int) -> None:
    """Best-effort refresh of the live chat's system prompt after mutating
    notes or memories. The import is deferred to avoid circular imports at
    module load time."""
    try:
        from bot.routers import completion

        completion.refresh_system_prompt(user_id)
    except Exception:
        pass


class MonitorTool(BaseTool):
    name = "monitor"
    required_args = ("name", "url")

    async def execute(self, context: ToolContext) -> ToolResult:
        name = (context.args.name or "").strip()
        url = (context.args.url or "").strip()
        if not name or not url:
            return ToolResult(
                text="🔍 Не хватает данных. Скажи имя и URL: «следи за Google по адресу google.com»",
                success=False,
            )
        if context.db is None:
            return ToolResult(text="База данных недоступна.", success=False)
        if "://" not in url:
            url = f"http://{url}"
        # Late import to avoid circular imports at module load time.
        from bot.routers.cron import _is_safe_monitor_url

        safe, reason = _is_safe_monitor_url(url)
        if not safe:
            return ToolResult(text=f"⚠️ URL не разрешён: {reason}", success=False)
        # Clamp interval: never let APScheduler poll faster than once a minute,
        # else a hostile/buggy LLM response could trigger a tight loop.
        raw_interval = context.args.interval if context.args.interval else 300
        interval = max(60, int(raw_interval))
        mid = context.db.add_monitor(
            user_id=context.user_id,
            name=name,
            url=url,
            interval=interval,
        )
        return ToolResult(
            text=f"✅ Монитор #{mid} добавлен\n📡 {name} → {url}\n⏱ Каждые {interval} сек.",
        )


class PlanTool(BaseTool):
    """Generic plan/intent that the router emits when it wants the LLM to draft text.

    Falls through to ChatTool semantics: just LLM-answer the user message verbatim.
    """

    name = "plan"
    required_args = ()

    async def execute(self, context: ToolContext) -> ToolResult:
        # Delegate to ChatTool to avoid duplicating the streaming logic.
        from bot.intent.tools.chat import ChatTool

        return await ChatTool().execute(context)
