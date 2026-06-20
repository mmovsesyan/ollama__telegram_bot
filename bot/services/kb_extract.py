"""LLM-driven enrichment for the knowledge base.

Two background jobs:
1. extract_facts_from_exchange — after every (user, assistant) turn,
   pull out 0-3 important facts and store them as memories.
2. compress_pending_memories — for memories > 500 chars without a
   summary, generate one so search/display are cheaper.

Both jobs are fire-and-forget (asyncio.create_task) and survive errors
silently — the bot must keep working if the LLM is slow or down.
"""

import asyncio
import logging
import re
from typing import Any

from bot.ollama import OllamaChatMessage, generate_chat_completion
from bot.ollama.dto import OllamaErrorChunk
from bot.settings import OLLAMA_MODEL

logger = logging.getLogger(__name__)

# Hard cap on extraction-prompt length so a runaway message doesn't burn
# 100k tokens. Truncated input is still useful — most facts surface in
# the first few hundred chars anyway.
_MAX_EXTRACT_INPUT = 4000

# Skip extraction if the assistant reply is just a tool acknowledgement.
# These don't contain user-relevant facts.
_SKIP_PHRASES = (
    "✅ напоминание",
    "✅ задача",
    "✅ заметка сохранена",
    "✅ сохранено:",
    "📰 ищу",
    "🌤 ищу",
    "🔍 ищу",
    "⏳ подождите",
    "⚠️",
    "❌",
    "думаю...",
    "(пустой ответ",
)


def _looks_skippable(user_text: str, assistant_text: str) -> bool:
    if not user_text or not assistant_text:
        return True
    # Very short exchanges rarely have facts ("привет", "ок", "спасибо").
    if len(user_text) < 8 and len(assistant_text) < 30:
        return True
    al = assistant_text.strip().lower()
    if any(al.startswith(p) for p in _SKIP_PHRASES):
        return True
    return False


_TOKEN_RE = re.compile(r"\w+", re.UNICODE)
_STOPWORDS = frozenset(
    {
        "и",
        "в",
        "на",
        "по",
        "с",
        "у",
        "о",
        "об",
        "за",
        "из",
        "для",
        "к",
        "до",
        "от",
        "что",
        "как",
        "это",
        "тот",
        "эта",
        "его",
        "её",
        "the",
        "a",
        "an",
        "of",
        "to",
        "in",
        "on",
        "at",
        "for",
        "is",
        "are",
    }
)


def _stem(tok: str) -> str:
    """Crude RU/EN stemmer: chop trailing inflection so 'погоду' / 'погода' /
    'погоды' all collapse to 'погод'. Not linguistically perfect but good
    enough for paraphrase detection without pymorphy2."""
    if len(tok) <= 4:
        return tok
    # Common Russian endings (longest first) + a couple of English ones.
    for suf in (
        "ятся",
        "иться",
        "ться",
        "ются",
        "ями",
        "ями",
        "ого",
        "его",
        "ему",
        "ому",
        "ыми",
        "ими",
        "ее",
        "ой",
        "ый",
        "ий",
        "ая",
        "яя",
        "ое",
        "ие",
        "ые",
        "ам",
        "ям",
        "ах",
        "ях",
        "ом",
        "ем",
        "ой",
        "ей",
        "у",
        "ю",
        "а",
        "я",
        "ы",
        "и",
        "е",
        "о",
        "ь",
        "ing",
        "ed",
        "es",
        "s",
    ):
        if tok.endswith(suf) and len(tok) - len(suf) >= 3:
            return tok[: -len(suf)]
    return tok


def _tokenize(s: str) -> set[str]:
    return {
        _stem(t)
        for t in _TOKEN_RE.findall(s.lower())
        if t not in _STOPWORDS and len(t) > 2
    }


def _is_near_duplicate(content: str, others: list[str]) -> bool:
    """True if `content` shares enough meaningful stemmed tokens with any
    item in `others` to count as a paraphrase. Catches cases like
    'погода в Москве в 7:30' vs 'ежедневная задача: погода в Москве в 7:30'.

    Heuristic: ≥60% overlap on the smaller token set, AND no high-signal
    proper-noun/number disagreement (so 'погода в Москве' != 'погода в Питере')."""
    a = _tokenize(content)
    if not a:
        return False
    a_signals = _signal_tokens(content)
    for other in others:
        b = _tokenize(other)
        if not b:
            continue
        smaller = a if len(a) <= len(b) else b
        overlap = len(a & b) / max(1, len(smaller))
        if overlap < 0.6:
            continue
        # Block dedup when each side has a signal token (proper noun,
        # number) absent from the other — different cities, dates, or
        # entities should never collapse.
        b_signals = _signal_tokens(other)
        if (a_signals - b_signals) and (b_signals - a_signals):
            continue
        return True
    return False


_SIGNAL_RE = re.compile(r"(?<=[a-zа-яё\s,;:—-])\b([A-ZА-ЯЁ][a-zа-яё]{2,}|\d+[:.\d]*)\b")


def _signal_tokens(s: str) -> set[str]:
    """Mid-sentence capitalized words and numbers — high-signal tokens
    that should block dedup when they differ (e.g. 'Москве' vs 'Питере',
    '7:30' vs '9:00'). Sentence-initial capitals are ignored — they're
    just grammar, not entity markers."""
    return {m.group(1).lower() for m in _SIGNAL_RE.finditer(s)}


def _parse_facts(raw: str) -> list[tuple[str, str]]:
    """Parse LLM output of `[category] content` lines.

    Accepts: [fact], [preference], [note]. Other categories are coerced
    to 'note'. Lines without brackets are skipped."""
    out: list[tuple[str, str]] = []
    for line in (raw or "").strip().split("\n"):
        line = line.strip()
        if not line or line.upper() == "НЕТ":
            continue
        if not line.startswith("["):
            continue
        m = re.match(r"^\[(\w+)\]\s*(.+)", line)
        if not m:
            continue
        cat = m.group(1).lower().strip()
        content = m.group(2).strip()
        if not content or len(content) > 500:
            continue
        if cat not in ("fact", "preference", "note"):
            cat = "note"
        out.append((cat, content))
    return out


async def extract_facts_from_exchange(
    db: Any,
    user_id: int,
    user_text: str,
    assistant_text: str,
) -> int:
    """Extract 0-3 facts from a single user/assistant exchange.

    Returns the number of new memories saved (0 if nothing or duplicate).
    Designed to be cheap: one LLM call with a tight prompt and a 12-second
    timeout. Gracefully degrades if the LLM is slow/down."""
    if db is None or _looks_skippable(user_text, assistant_text):
        return 0

    convo = f"Пользователь: {user_text[:2000]}\n\nАссистент: {assistant_text[:2000]}"
    if len(convo) > _MAX_EXTRACT_INPUT:
        convo = convo[:_MAX_EXTRACT_INPUT]

    prompt = (
        "Извлеки 0-3 ВАЖНЫХ факта о пользователе из обмена. Сохраняем только то, "
        "что полезно знать через недели/месяцы.\n\n"
        "Категории:\n"
        "- fact: устойчивый факт о пользователе (имя, профессия, образование, "
        "город, владение языками, навыки)\n"
        "- preference: устойчивое предпочтение (формат ответов, стиль, любимые темы)\n"
        "- note: заметка, которую пользователь явно попросил сохранить\n\n"
        "НЕ СОХРАНЯЙ:\n"
        "- Намерения и разовые запросы («хочу найти X», «покажи Y», «ищет книги»)\n"
        "- Напоминания и задачи (они уже в отдельных таблицах: «напомни», "
        "«каждое утро в 9», «по будням в 7:30»)\n"
        "- Действия пользователя в чате («загрузил файл», «отправил фото», "
        "«нажал кнопку», «попросил проанализировать»)\n"
        "- Болтовню, погоду, новости, ответы ассистента\n"
        "- Дубликаты и переформулировки одного и того же факта\n\n"
        "Формат (одна строка на факт):\n"
        "[category] content\n"
        "Если ничего достойного — ответь: НЕТ\n\n"
        f"ДИАЛОГ:\n{convo}\n\n"
        "ФАКТЫ:"
    )
    try:
        async with asyncio.timeout(12):
            messages = [
                OllamaChatMessage(
                    role="system", content="Ты извлекаешь факты для базы знаний."
                ),
                OllamaChatMessage(role="user", content=prompt),
            ]
            raw = ""
            async for is_done, chunk in generate_chat_completion(
                messages, OLLAMA_MODEL, temperature=0.2
            ):
                if is_done:
                    break
                if isinstance(chunk, OllamaErrorChunk):
                    return 0
                raw += chunk.message.content
    except asyncio.TimeoutError:
        logger.info("[KB EXTRACT] timed out for user_id=%s", user_id)
        return 0
    except Exception as e:
        logger.warning("[KB EXTRACT] failed for user_id=%s: %s", user_id, e)
        return 0

    facts = _parse_facts(raw)
    if not facts:
        return 0

    try:
        existing = db.get_memories(user_id)
    except Exception:
        existing = []
    existing_contents = [(m.get("content") or "") for m in existing]
    saved_contents: list[str] = []
    saved = 0
    for cat, content in facts[:3]:
        if _is_near_duplicate(content, existing_contents):
            continue
        if _is_near_duplicate(content, saved_contents):
            continue
        try:
            db.add_memory(user_id, cat, content, source="auto-extract")
            saved += 1
            saved_contents.append(content)
        except Exception as e:
            logger.warning("[KB EXTRACT] add_memory failed: %s", e)
    if saved:
        logger.info("[KB EXTRACT] saved %d new memories for user_id=%s", saved, user_id)
        # Refresh the active chat's system prompt so auto-extracted facts are
        # visible in the current session without a restart or /clear.
        try:
            from bot.routers import completion

            completion.refresh_system_prompt(user_id)
        except Exception as exc:
            logger.warning(
                "Failed to refresh system prompt after extraction %s: %s", user_id, exc
            )
    return saved


async def compress_memory_dict(db: Any, memory: dict) -> bool:
    """Compress a long memory to a 1-2 sentence summary. Returns True
    when a summary was saved."""
    if db is None or not memory:
        return False
    if memory.get("summary"):
        return False
    content = (memory.get("content") or "").strip()
    if len(content) < 500:
        return False

    prompt = (
        "Сожми заметку до 1-2 коротких предложений. Сохрани ключевые "
        "имена, даты, числа. Без вступлений, только сжатый текст.\n\n"
        f"ЗАМЕТКА:\n{content[:3000]}\n\n"
        "СЖАТО:"
    )
    try:
        async with asyncio.timeout(15):
            messages = [
                OllamaChatMessage(
                    role="system", content="Ты сжимаешь заметки до сути."
                ),
                OllamaChatMessage(role="user", content=prompt),
            ]
            raw = ""
            async for is_done, chunk in generate_chat_completion(
                messages, OLLAMA_MODEL, temperature=0.2
            ):
                if is_done:
                    break
                if isinstance(chunk, OllamaErrorChunk):
                    return False
                raw += chunk.message.content
    except asyncio.TimeoutError:
        return False
    except Exception:
        return False

    summary = raw.strip()
    if not summary or len(summary) > 400:
        return False
    try:
        db.update_memory_summary(memory["id"], summary)
        return True
    except Exception:
        return False


async def compress_pending_memories(db: Any, user_id: int, limit: int = 5) -> int:
    """Walk the user's memories and compress long ones that lack a
    summary. Bounded so a backlog doesn't burn tokens in one call."""
    if db is None:
        return 0
    try:
        memories = db.get_memories(user_id)
    except Exception:
        return 0
    pending = [
        m
        for m in memories
        if not m.get("summary") and len((m.get("content") or "")) >= 500
    ]
    saved = 0
    for mem in pending[:limit]:
        if await compress_memory_dict(db, mem):
            saved += 1
    return saved
