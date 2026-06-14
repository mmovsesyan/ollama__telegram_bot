import json
import re
import typing
from logging import getLogger

from bot.intent.context import ContextBuilder
from bot.intent.schemas import (
    ALLOWED_INTENTS,
    ALLOWED_TOOLS,
    IntentArgs,
    IntentResult,
)
from bot.ollama import OllamaChatMessage, generate_chat_completion
from bot.ollama.dto import OllamaErrorChunk
from bot.settings import OLLAMA_MODEL

logger = getLogger(__name__)

_INTENTS = list(typing.get_args(ALLOWED_INTENTS))
_TOOLS = list(typing.get_args(ALLOWED_TOOLS))

_SCHEMA = {
    "intent": _INTENTS,
    "tool": _TOOLS,
    "args": {
        "content": "string | null",
        "trigger_at": "string | null",
        "recurring": "string | null",
        "query": "string | null",
        "city": "string | null",
        "url": "string | null",
        "name": "string | null",
        "interval": "integer | null",
        "plan_text": "string | null",
    },
    "confidence": "float 0.0..1.0",
    "clarification_needed": "boolean",
    "clarification_question": "string | null",
    "proactive_suggestion": "object | null",
    "response_tone": "friendly | neutral | concise",
}

_SYSTEM_PROMPT_TEMPLATE = """You are an intent router for a Telegram assistant.
Analyze the user's message and choose the best intent and tool from the available lists.

Available intents: {intents}
Available tools: {tools}

Respond ONLY with a single JSON object matching this schema:
{schema}

Do not add markdown formatting, explanations, or commentary outside the JSON.
"""


class LLMIntentRouter:
    """Route a user message to an intent/tool using an LLM."""

    @classmethod
    def _build_system_prompt(cls, context: dict) -> str:
        prompt = _SYSTEM_PROMPT_TEMPLATE.format(
            intents=json.dumps(_INTENTS, ensure_ascii=False),
            tools=json.dumps(_TOOLS, ensure_ascii=False),
            schema=json.dumps(_SCHEMA, indent=2, ensure_ascii=False),
        )
        prompt += f"\n\nCurrent context:\n{json.dumps(context, ensure_ascii=False, default=str)}"
        return prompt

    @classmethod
    def _extract_json(cls, text: str) -> str:
        text = text.strip()
        # Remove markdown code fences if present.
        if text.startswith("```"):
            text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.IGNORECASE)
            text = re.sub(r"\s*```$", "", text)
        # Extract the first JSON object if the model added extra text.
        match = re.search(r"\{.*\}", text, re.DOTALL)
        if match:
            text = match.group(0)
        return text.strip()

    @classmethod
    def _fallback(cls, message_text: str) -> IntentResult:
        return IntentResult(
            intent="chat",
            tool="chat",
            args=IntentArgs(content=message_text),
            confidence=0.0,
        )

    @classmethod
    async def route(cls, user_id: int, message_text: str) -> IntentResult:
        context = await ContextBuilder.build(user_id=user_id, message_text=message_text)
        messages = [
            OllamaChatMessage(role="system", content=cls._build_system_prompt(context)),
            OllamaChatMessage(role="user", content=message_text),
        ]

        raw_response = ""
        try:
            async for is_done, chunk in generate_chat_completion(
                messages, OLLAMA_MODEL, temperature=0
            ):
                if is_done:
                    continue
                if isinstance(chunk, OllamaErrorChunk):
                    logger.warning(f"LLM error while routing intent: {chunk.error}")
                    return cls._fallback(message_text)
                raw_response += getattr(chunk.message, "content", "") or ""
        except Exception as e:
            logger.warning(f"Intent routing generation failed: {e}")
            return cls._fallback(message_text)

        return cls._parse_response(raw_response, message_text)

    @classmethod
    def _parse_response(cls, raw_response: str, message_text: str) -> IntentResult:
        if not raw_response.strip():
            logger.warning("Empty routing response from LLM")
            return cls._fallback(message_text)

        json_text = cls._extract_json(raw_response)
        try:
            data = json.loads(json_text)
        except (json.JSONDecodeError, ValueError) as e:
            logger.warning(f"Failed to parse routing JSON: {e}. Raw: {raw_response!r}")
            return cls._fallback(message_text)

        args_data = data.get("args")
        if isinstance(args_data, dict):
            args = IntentArgs.model_validate(args_data)
        else:
            args = IntentArgs()

        data["args"] = args.model_dump()

        try:
            return IntentResult.model_validate(data)
        except Exception as e:
            logger.warning(f"Invalid IntentResult from LLM: {e}. Data: {data!r}")
            return cls._fallback(message_text)
