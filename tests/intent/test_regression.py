import pytest
from unittest.mock import AsyncMock, patch

from bot.intent.router import LLMIntentRouter


class _FakeAsyncIterator:
    """Helper that makes a list of items drivable by `async for`."""

    def __init__(self, items):
        self._items = list(items)
        self._index = 0

    def __aiter__(self):
        return self

    async def __anext__(self):
        if self._index >= len(self._items):
            raise StopAsyncIteration
        item = self._items[self._index]
        self._index += 1
        return item


def _make_chunk(content: str):
    """Build a fake Ollama chat chunk with the given content string."""
    return type(
        "Chunk",
        (object,),
        {"message": type("Message", (object,), {"content": content})},
    )


# Each tuple: (user_message, llm_json_response, expected_intent, expected_tool, expected_args_checks)
# expected_args_checks is a dict mapping IntentArgs attribute names to expected values.
REGRESSION_CASES = [
    # --- chat / chat ---
    (
        "привет",
        '{"intent":"chat","tool":"chat","args":{"content":"привет"},"confidence":0.99}',
        "chat",
        "chat",
        {"content": "привет"},
    ),
    (
        "как дела?",
        '{"intent":"chat","tool":"chat","args":{},"confidence":0.95,"response_tone":"friendly"}',
        "chat",
        "chat",
        {},
    ),
    (
        "отчёт за сегодня",
        '{"intent":"chat","tool":"chat","args":{"content":"отчёт за сегодня"},"confidence":0.88}',
        "chat",
        "chat",
        {"content": "отчёт за сегодня"},
    ),
    (
        "расскажи анекдот",
        '{"intent":"chat","tool":"chat","args":{},"confidence":0.91}',
        "chat",
        "chat",
        {},
    ),
    # --- create_reminder / remind ---
    (
        "завтра в 9 позвонить брокеру",
        '{"intent":"create_reminder","tool":"remind","args":{"content":"позвонить брокеру","trigger_at":"2026-06-15T09:00:00+00:00"},"confidence":0.95}',
        "create_reminder",
        "remind",
        {"content": "позвонить брокеру"},
    ),
    (
        "напомни купить молока вечером",
        '{"intent":"create_reminder","tool":"remind","args":{"content":"купить молока","trigger_at":"2026-06-14T19:00:00+00:00"},"confidence":0.92}',
        "create_reminder",
        "remind",
        {"content": "купить молока"},
    ),
    (
        "напомни о встрече завтра в 15:00",
        '{"intent":"create_reminder","tool":"remind","args":{"content":"встреча","trigger_at":"2026-06-15T15:00:00+00:00"},"confidence":0.94}',
        "create_reminder",
        "remind",
        {"content": "встреча"},
    ),
    (
        "позвонить маме через час",
        '{"intent":"create_reminder","tool":"remind","args":{"content":"позвонить маме","trigger_at":"2026-06-14T13:00:00+00:00"},"confidence":0.90}',
        "create_reminder",
        "remind",
        {"content": "позвонить маме"},
    ),
    # --- create_task / task ---
    (
        "каждое утро в 8 погода в москве",
        '{"intent":"create_task","tool":"task","args":{"content":"погода в москве","trigger_at":"08:00","recurring":"daily"},"confidence":0.92}',
        "create_task",
        "task",
        {"content": "погода в москве", "recurring": "daily"},
    ),
    (
        "задача: проверить почту каждый час",
        '{"intent":"create_task","tool":"task","args":{"content":"проверить почту","recurring":"hourly"},"confidence":0.89}',
        "create_task",
        "task",
        {"content": "проверить почту", "recurring": "hourly"},
    ),
    (
        "ежедневная задача пить воду",
        '{"intent":"create_task","tool":"task","args":{"content":"пить воду","recurring":"daily"},"confidence":0.87}',
        "create_task",
        "task",
        {"content": "пить воду", "recurring": "daily"},
    ),
    (
        "каждую пятницу отчёт по портфелю",
        '{"intent":"create_task","tool":"task","args":{"content":"отчёт по портфелю","recurring":"weekly"},"confidence":0.90}',
        "create_task",
        "task",
        {"content": "отчёт по портфелю", "recurring": "weekly"},
    ),
    # --- add_memory / memory ---
    (
        "запомни, я люблю краткие ответы",
        '{"intent":"add_memory","tool":"memory","args":{"content":"любит краткие ответы"},"confidence":0.96}',
        "add_memory",
        "memory",
        {"content": "любит краткие ответы"},
    ),
    (
        "запомни мой любимый цвет синий",
        '{"intent":"add_memory","tool":"memory","args":{"content":"любимый цвет синий"},"confidence":0.93}',
        "add_memory",
        "memory",
        {"content": "любимый цвет синий"},
    ),
    (
        "я инвестор с умеренным риском",
        '{"intent":"add_memory","tool":"memory","args":{"content":"инвестор с умеренным риском"},"confidence":0.91}',
        "add_memory",
        "memory",
        {"content": "инвестор с умеренным риском"},
    ),
    # --- add_note / note ---
    (
        "заметка: идея для стартапа",
        '{"intent":"add_note","tool":"note","args":{"content":"идея для стартапа"},"confidence":0.88}',
        "add_note",
        "note",
        {"content": "идея для стартапа"},
    ),
    (
        "запиши: адрес офиса ул. Ленина 1",
        '{"intent":"add_note","tool":"note","args":{"content":"адрес офиса ул. Ленина 1"},"confidence":0.89}',
        "add_note",
        "note",
        {"content": "адрес офиса ул. Ленина 1"},
    ),
    (
        "сохрани заметку номер счёта 40817",
        '{"intent":"add_note","tool":"note","args":{"content":"номер счёта 40817"},"confidence":0.85}',
        "add_note",
        "note",
        {"content": "номер счёта 40817"},
    ),
    # --- search / search ---
    (
        "поиск: рецепт пельменей",
        '{"intent":"search","tool":"search","args":{"query":"рецепт пельменей"},"confidence":0.93}',
        "search",
        "search",
        {"query": "рецепт пельменей"},
    ),
    (
        "найди в интернете лучшие акции",
        '{"intent":"search","tool":"search","args":{"query":"лучшие акции"},"confidence":0.90}',
        "search",
        "search",
        {"query": "лучшие акции"},
    ),
    (
        "покажи курс доллара",
        '{"intent":"search","tool":"search","args":{"query":"курс доллара"},"confidence":0.86}',
        "search",
        "search",
        {"query": "курс доллара"},
    ),
    # --- weather / weather ---
    (
        "погода в москве",
        '{"intent":"weather","tool":"weather","args":{"city":"Москва"},"confidence":0.94}',
        "weather",
        "weather",
        {"city": "Москва"},
    ),
    (
        "какая погода в санкт-петербурге?",
        '{"intent":"weather","tool":"weather","args":{"city":"Санкт-Петербург"},"confidence":0.93}',
        "weather",
        "weather",
        {"city": "Санкт-Петербург"},
    ),
    (
        "погода в лондоне",
        '{"intent":"weather","tool":"weather","args":{"city":"Лондон"},"confidence":0.92}',
        "weather",
        "weather",
        {"city": "Лондон"},
    ),
    # --- news / news ---
    (
        "новости",
        '{"intent":"news","tool":"news","args":{},"confidence":0.88}',
        "news",
        "news",
        {},
    ),
    (
        "новости экономики",
        '{"intent":"news","tool":"news","args":{},"confidence":0.87}',
        "news",
        "news",
        {},
    ),
    (
        "последние технологические новости",
        '{"intent":"news","tool":"news","args":{},"confidence":0.86}',
        "news",
        "news",
        {},
    ),
    # Topic-only fast path: short subjects bypass the LLM router entirely.
    (
        "игры",
        '{"intent":"news","tool":"news","args":{"query":"игры"},"confidence":0.9}',
        "news",
        "news",
        {"query": "игры"},
    ),
    (
        "Tesla",
        '{"intent":"news","tool":"news","args":{"query":"Tesla"},"confidence":0.9}',
        "news",
        "news",
        {"query": "Tesla"},
    ),
    (
        "ai",
        '{"intent":"news","tool":"news","args":{"query":"ai"},"confidence":0.9}',
        "news",
        "news",
        {"query": "ai"},
    ),
    (
        "биткоин",
        '{"intent":"news","tool":"news","args":{"query":"биткоин"},"confidence":0.9}',
        "news",
        "news",
        {"query": "биткоин"},
    ),
    # --- add_monitor / monitor ---
    (
        "следи за сайтом example.com",
        '{"intent":"add_monitor","tool":"monitor","args":{"name":"example.com","url":"https://example.com","interval":5},"confidence":0.89}',
        "add_monitor",
        "monitor",
        {"name": "example.com", "url": "https://example.com", "interval": 5},
    ),
    (
        "мониторинг https://google.com каждые 5 минут",
        '{"intent":"add_monitor","tool":"monitor","args":{"name":"google.com","url":"https://google.com","interval":5},"confidence":0.84}',
        "add_monitor",
        "monitor",
        {"name": "google.com", "url": "https://google.com", "interval": 5},
    ),
    # --- generate_plan / plan ---
    (
        "план на неделю",
        '{"intent":"generate_plan","tool":"plan","args":{"plan_text":"план на неделю"},"confidence":0.90}',
        "generate_plan",
        "plan",
        {"plan_text": "план на неделю"},
    ),
    (
        "план на день",
        '{"intent":"generate_plan","tool":"plan","args":{"plan_text":"план на день"},"confidence":0.89}',
        "generate_plan",
        "plan",
        {"plan_text": "план на день"},
    ),
    (
        "составь план тренировок на месяц",
        '{"intent":"generate_plan","tool":"plan","args":{"plan_text":"план тренировок на месяц"},"confidence":0.88}',
        "generate_plan",
        "plan",
        {"plan_text": "план тренировок на месяц"},
    ),
    # --- clarify / chat ---
    (
        "не понял",
        '{"intent":"clarify","tool":"chat","args":{},"confidence":0.80,"clarification_needed":true,"clarification_question":"Что именно вас интересует?"}',
        "clarify",
        "chat",
        {"clarification_needed": True},
    ),
    (
        "уточни что имел в виду",
        '{"intent":"clarify","tool":"chat","args":{},"confidence":0.78,"clarification_needed":true,"clarification_question":"Можете переформулировать?"}',
        "clarify",
        "chat",
        {"clarification_needed": True},
    ),
    # --- cancel / chat ---
    (
        "отмени последнее напоминание",
        '{"intent":"cancel","tool":"chat","args":{"content":"отменить последнее напоминание"},"confidence":0.82}',
        "cancel",
        "chat",
        {"content": "отменить последнее напоминание"},
    ),
    (
        "отмени всё",
        '{"intent":"cancel","tool":"chat","args":{},"confidence":0.81}',
        "cancel",
        "chat",
        {},
    ),
    # --- help / chat ---
    (
        "помощь",
        '{"intent":"help","tool":"chat","args":{},"confidence":0.97}',
        "help",
        "chat",
        {},
    ),
    (
        "что ты умеешь?",
        '{"intent":"help","tool":"chat","args":{"content":"что ты умеешь"},"confidence":0.96}',
        "help",
        "chat",
        {"content": "что ты умеешь"},
    ),
]


class TestIntentRegression:
    @pytest.fixture(autouse=True)
    def mock_context_builder(self):
        with patch(
            "bot.intent.router.ContextBuilder.build",
            new_callable=AsyncMock,
            return_value={},
        ) as mock:
            yield mock

    @pytest.mark.parametrize(
        "text,json_response,expected_intent,expected_tool,expected_args_checks",
        REGRESSION_CASES,
    )
    @pytest.mark.asyncio
    async def test_routing(
        self,
        text,
        json_response,
        expected_intent,
        expected_tool,
        expected_args_checks,
    ):
        # The router has a regex fast-path that intercepts obvious commands
        # ("напомни", "погода в Москве", "поищи Tesla") before calling the LLM.
        # When fast-path fires, the args come from the user text, not from the
        # mocked LLM JSON — so we only verify intent/tool match for those cases.
        # The fast-path mapping is documented in router.LLMIntentRouter._fallback.
        FAST_PATH_INTENTS = {
            "create_reminder", "create_task", "weather", "news",
            "search", "add_note", "add_memory", "add_monitor",
        }
        with patch(
            "bot.intent.router.generate_chat_completion",
            return_value=_FakeAsyncIterator(
                [(False, _make_chunk(json_response)), (True, None)]
            ),
        ):
            result = await LLMIntentRouter.route(user_id=1, message_text=text)

        assert result.intent == expected_intent
        assert result.tool == expected_tool

        # Skip args verification for fast-path intents — the user text shape
        # determines args, not the mocked LLM JSON.
        if expected_intent in FAST_PATH_INTENTS:
            return

        for attr, expected in expected_args_checks.items():
            # Some attributes belong to IntentResult, not IntentArgs.
            target = result if hasattr(result, attr) else result.args
            actual = getattr(target, attr)
            assert actual == expected, (
                f"For message {text!r}, {attr} expected {expected!r}, got {actual!r}"
            )
