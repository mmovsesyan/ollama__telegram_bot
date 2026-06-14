from bot.ollama import OllamaChatMessage, generate_chat_completion
from bot.ollama.dto import OllamaErrorChunk
from bot.intent.schemas import ToolContext, ToolResult
from bot.intent.tools.base import BaseTool
from bot.settings import OLLAMA_MODEL, SYSTEM_MESSAGE


class ChatTool(BaseTool):
    name = "chat"

    async def execute(self, context: ToolContext) -> ToolResult:
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
