import asyncio
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
        """Heuristic intent detection used when the LLM is unreachable.

        We can't fail to chat — half the user's commands are obvious from
        keywords ("напомни", "поставь задачу", "погода в москве", "поищи").
        If we detect one, route to the matching tool with high confidence
        so the validator doesn't reject it.

        Order matters. The tests in test_regression.py codify the priority:
        cancel > monitor > task-with-schedule > task > remind > weather >
        news > search > note > memory > monitor-vague > chat.
        """
        t = message_text.lower().strip()

        # 1.5 KB search — "что я говорил про X", "найди у меня про X",
        #    "из моей базы X". Comes before generic search/news so the
        #    user's stored knowledge wins.
        m = re.search(
            r"(?:что\s+я\s+говорил\s+про|что\s+у\s+меня\s+про|"
            r"найди\s+у\s+меня(?:\s+про)?|найди\s+в\s+базе|"
            r"поищи\s+в\s+базе|из\s+(?:моей\s+)?базы|в\s+(?:моей\s+)?базе)\s+(.+)",
            t,
        )
        if m:
            kb_query = m.group(1).strip()
            return IntentResult(
                intent="kb_search",
                tool="kb_search",
                args=IntentArgs(query=kb_query),
                confidence=0.9,
            )

        # 1. Cancel — must come first so "отмени напоминание" doesn't route
        #    to remind. We don't have a cancel tool yet, so route to chat
        #    and let the LLM (or the user via /reminders) handle it.
        if re.search(r"\b(отмени|отменить|cancel|удали|delete)\b", t):
            return IntentResult(
                intent="cancel",
                tool="chat",
                args=IntentArgs(content=message_text),
                confidence=0.95,
            )

        # 2. Monitor — uses a stem match ("мониторинг", "мониторить") and
        #    catches URLs. Comes before search so "мониторинг google.com"
        #    isn't intercepted by the "google" search keyword.
        if re.search(r"\b(монитор\w*|следи\s+за|monitor\w*)\b", t) or re.search(r"https?://\S+", t):
            return IntentResult(
                intent="add_monitor",
                tool="monitor",
                args=IntentArgs(content=message_text),
                confidence=0.9,
            )

        # 3. Explicit reminder/task keyword wins over implicit schedule.
        #    "напомни о встрече завтра в 15:00" → reminder, not task.
        if re.search(r"\b(поставь\s+задачу|задач[ау]|добавь\s+задачу|создай\s+задачу|запланируй\s+задачу|task)\b", t):
            return IntentResult(
                intent="create_task",
                tool="task",
                args=IntentArgs(content=message_text),
                confidence=0.9,
            )

        if re.search(r"\b(напомни|напоминание|напомнить|remind)\b", t):
            return IntentResult(
                intent="create_reminder",
                tool="remind",
                args=IntentArgs(content=message_text),
                confidence=0.9,
            )

        # 4. Schedule-only phrases ("каждое утро в 8 погода в москве",
        #    "завтра в 9 позвонить брокеру") with no explicit
        #    reminder/task keyword. If the schedule wraps an action verb
        #    (погода/поищи/новости), treat as task (AI-executed). Otherwise
        #    a plain reminder.
        schedule_re = (
            r"\b(?:кажд(?:ый|ое|ую)|ежедневно|еженедельно|ежемесячно|"
            r"по\s+будням|по\s+выходным|раз\s+в\s+\d+|через\s+\d+|"
            r"завтра\s+в|сегодня\s+в|every\s+(?:day|week|month))\b"
        )
        if re.search(schedule_re, t):
            action_re = r"\b(погод|weather|поищи|найди|загугли|search|новост|news|температур|прогноз)\w*\b"
            is_task = bool(re.search(action_re, t))
            if is_task:
                return IntentResult(
                    intent="create_task",
                    tool="task",
                    args=IntentArgs(content=message_text),
                    confidence=0.9,
                )
            return IntentResult(
                intent="create_reminder",
                tool="remind",
                args=IntentArgs(content=message_text),
                confidence=0.85,
            )

        # 6. Weather — extract city after "в"/"in"/"для". Strip time
        # phrases first so 'погода на неделю в москве' doesn't latch
        # onto 'на' as the city.
        from bot.intent.tools.weather import _detect_days
        days = _detect_days(message_text)
        weather_text = re.sub(
            r"на\s+(?:неделю|месяц|выходные|завтра|послезавтра|ближайш\w+|\d+\s*(?:день|дня|дней|сутки|суток))|"
            r"\b(?:неделю|неделя|месяц|выходные|завтра|послезавтра|tomorrow)\b|"
            r"\d+\s*(?:день|дня|дней|сутки|суток)|"
            r"this\s+week|this\s+month|next\s+\d+\s+days?",
            " ",
            t,
            flags=re.IGNORECASE,
        )
        # First, drop a leading 'погод(ы|у|а|...)' / 'прогноз(а)?' chain
        # so the city extractor isn't tempted to grab 'погоды' as a city.
        weather_text = re.sub(
            r"\b(?:прогноз\w*\s+)?(?:погод\w*|weather|температур\w*|прогноз\w*|forecast)\b",
            "WX",
            weather_text,
            count=1,
            flags=re.IGNORECASE,
        )
        m = re.search(
            r"WX\s*(?:в|in|для|по|for)?\s*([\wа-яА-ЯёЁ\-]+)?",
            weather_text,
        )
        if m:
            city = (m.group(1) or "").strip()
            if city.lower() in {"на", "по", "для", "в", "с", "за", "и", "the", "a", "in", "for"}:
                city = ""
            return IntentResult(
                intent="weather",
                tool="weather",
                args=IntentArgs(
                    city=city.capitalize() if city else None,
                    days=days,
                ),
                confidence=0.9 if city else 0.5,
            )

        # 7. News — extract optional topic ("новости про ИИ" → query="ИИ").
        m = re.search(r"\b(?:новост[иь]|news)\b\s*(?:про|об?|по|on|about)?\s*(.*)", t)
        if m:
            topic = m.group(1).strip()
            return IntentResult(
                intent="news",
                tool="news",
                args=IntentArgs(query=topic if topic else None),
                confidence=0.9,
            )

        # 8. Search — but skip if "google" appears only inside a URL we already
        #    handled above. After monitor priority, this is safe.
        m = re.search(r"\b(?:поищи|найди|загугли|погугли|ищи|search|google)\b\s*(.*)", t)
        if m:
            query = m.group(1).strip() or message_text
            return IntentResult(
                intent="search",
                tool="search",
                args=IntentArgs(query=query),
                confidence=0.9,
            )

        # 9. Note.
        if re.search(r"\b(заметка|сделай\s+заметку|запиши\s+заметку|note)\b", t):
            return IntentResult(
                intent="add_note",
                tool="note",
                args=IntentArgs(content=message_text),
                confidence=0.9,
            )

        # 10. Memory.
        if re.search(r"\b(запомни|добавь\s+факт|запиши\s+что|факт)\b", t):
            return IntentResult(
                intent="add_memory",
                tool="memory",
                args=IntentArgs(content=message_text),
                confidence=0.9,
            )

        # 11. Default: free-form chat.
        return IntentResult(
            intent="chat",
            tool="chat",
            args=IntentArgs(content=message_text),
            confidence=0.95,
        )

    @classmethod
    async def route(cls, user_id: int, message_text: str) -> IntentResult:
        # Fast path: regex catches obvious commands ("напомни", "погода в Москве",
        # "поищи Tesla") in microseconds. Skip the LLM round-trip for these —
        # large models like kimi-k2.6 can take 10+ seconds and time out, leaving
        # the user staring at "confidence 0.0".
        fast = cls._fallback(message_text)
        if fast.confidence >= 0.9 and fast.tool != "chat":
            return fast

        # Slow path: ambiguous text — let the LLM do the routing. If it fails
        # or times out, _fallback runs again and either picks a tool from the
        # regex hints or falls through to chat.
        context = await ContextBuilder.build(user_id=user_id, message_text=message_text)
        messages = [
            OllamaChatMessage(role="system", content=cls._build_system_prompt(context)),
            OllamaChatMessage(role="user", content=message_text),
        ]

        raw_response = ""
        try:
            async with asyncio.timeout(15):
                async for is_done, chunk in generate_chat_completion(
                    messages, OLLAMA_MODEL, temperature=0
                ):
                    if is_done:
                        continue
                    if isinstance(chunk, OllamaErrorChunk):
                        logger.warning(f"LLM error while routing intent: {chunk.error}")
                        return cls._fallback(message_text)
                    raw_response += getattr(chunk.message, "content", "") or ""
        except asyncio.TimeoutError:
            logger.warning("Intent routing timed out after 15s")
            return cls._fallback(message_text)
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
