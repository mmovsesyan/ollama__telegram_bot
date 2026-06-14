from bot.intent.schemas import ToolContext, ToolResult
from bot.intent.tools.base import BaseTool


class ChatTool(BaseTool):
    name = "chat"

    async def execute(self, context: ToolContext) -> ToolResult:
        # If a real Telegram Message is attached, delegate to the
        # persistence-aware generate() in completion.py so the smart pipeline
        # shares chat history, DB persistence, and compaction with /clear.
        msg = context.message
        if msg is not None:
            try:
                from aiogram.types import Message  # local import: aiogram may not be available in some test paths
                if isinstance(msg, Message):
                    from bot.routers.completion import generate
                    await generate(msg, context.user_id, context.message_text)
                    return ToolResult(text="", success=True)
            except Exception:
                # Fall through to non-streaming completion below.
                pass

        # Fallback: non-streaming completion if no message is attached or the
        # streaming path failed. Avoids importing bot.bot which requires a
        # real TELEGRAM_TOKEN.
        from bot.ollama import OllamaChatMessage, generate_chat_completion
        from bot.ollama.dto import OllamaErrorChunk
        from bot.settings import OLLAMA_MODEL, SYSTEM_MESSAGE

        messages = [
            OllamaChatMessage(role="system", content=SYSTEM_MESSAGE),
            OllamaChatMessage(role="user", content=context.message_text),
        ]
        response = ""
        async for is_done, chunk in generate_chat_completion(messages, OLLAMA_MODEL):
            if is_done:
                break
            if isinstance(chunk, OllamaErrorChunk):
                response = f"[Ошибка Ollama: {chunk.error}]"
                break
            response += chunk.message.content
        if not response.strip():
            response = "(пустой ответ от модели)"
        return ToolResult(text=response[:3800])

