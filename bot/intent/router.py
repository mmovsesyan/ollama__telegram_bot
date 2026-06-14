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
    "type": "object",
    "properties": {
        "intent": {"type": "string", "enum": _INTENTS},
        "tool": {"type": "string", "enum": _TOOLS},
        "args": {
            "type": "object",
            "properties": {
                "content": {"type": ["string", "null"]},
                "trigger_at": {"type": ["string", "null"]},
                "recurring": {"type": ["string", "null"]},
                "query": {"type": ["string", "null"]},
                "city": {"type": ["string", "null"]},
                "url": {"type": ["string", "null"]},
                "name": {"type": ["string", "null"]},
                "interval": {"type": ["integer", "null"]},
                "plan_text": {"type": ["string", "null"]},
            },
            "additionalProperties": False,
        },
        "confidence": {"type": "number", "minimum": 0.0, "maximum": 1.0},
        "clarification_needed": {"type": "boolean"},
        "clarification_question": {"type": ["string", "null"]},
        "proactive_suggestion": {"type": ["object", "null"], "additionalProperties": True},
        "response_tone": {"type": "string", "enum": ["friendly", "neutral", "concise"]},
    },
    "required": ["intent", "tool", "args", "confidence"],
    "additionalProperties": False,
}

_SYSTEM_PROMPT_TEMPLATE = """You are an intent router for a Telegram assistant.
Analyze the user's message and choose the best intent and tool from the available lists.

Available intents: {intents}
Available tools: {tools}

Respond ONLY with a single JSON object matching this schema:
{schema}

Do not add markdown formatting, explanations, or commentary outside the JSON.
"""

_STATIC_SYSTEM_PROMPT = _SYSTEM_PROMPT_TEMPLATE.format(
    intents=json.dumps(_INTENTS, ensure_ascii=False),
    tools=json.dumps(_TOOLS, ensure_ascii=False),
    schema=json.dumps(_SCHEMA, indent=2, ensure_ascii=False),
)


class LLMIntentRouter:
    """Route a user message to an intent/tool using an LLM."""

    @classmethod
    def _build_system_prompt(cls, context: dict) -> str:
        return (
            _STATIC_SYSTEM_PROMPT
            + f"\n\nCurrent context:\n{json.dumps(context, ensure_ascii=False, default=str)}"
        )

    @classmethod
    def _extract_json(cls, text: str) -> str:
        text = text.strip()
        # Remove markdown code fences if present.
        if text.startswith("```"):
            text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.IGNORECASE)
            text = re.sub(r"\s*```$", "", text)
        text = text.strip()

        # Find the first balanced {...} block that parses as JSON.
        start = 0
        while True:
            first_brace = text.find("{", start)
            if first_brace == -1:
                return text

            candidate = cls._extract_balanced_json(text, first_brace)
            try:
                json.loads(candidate)
                return candidate
            except (json.JSONDecodeError, ValueError):
                # Not valid JSON here; keep searching from the next character.
                start = first_brace + 1
                continue

    @classmethod
    def _extract_balanced_json(cls, text: str, first_brace: int) -> str:
        depth = 0
        in_string = False
        escaped = False
        for i, char in enumerate(text[first_brace:], start=first_brace):
            if escaped:
                escaped = False
                continue
            if char == "\\":
                escaped = True
                continue
            if char == '"':
                in_string = not in_string
                continue
            if in_string:
                continue
            if char == "{":
                depth += 1
            elif char == "}":
                depth -= 1
                if depth == 0:
                    return text[first_brace : i + 1].strip()
        return text

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
