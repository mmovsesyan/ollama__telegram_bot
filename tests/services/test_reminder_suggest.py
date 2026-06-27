import pytest
from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

from bot.services import reminder_suggest as rs_module


class _FakeDb:
    def __init__(self, prefs=None, messages=None, memories=None, reminders=None):
        self._prefs = prefs or {}
        self._messages = messages or []
        self._memories = memories or []
        self._reminders = reminders or []
        self._notes = []
        self._reminders_added = []

    def get_user_prefs(self, user_id):
        return {**self._prefs, "user_id": user_id}

    def get_session_messages(self, user_id, limit=20):
        return list(self._messages)

    def get_memories(self, user_id):
        return list(self._memories)

    def get_user_reminders(self, user_id):
        return list(self._reminders)

    def add_reminder(self, *, user_id, content, trigger_at, recurring=None, action="notify"):
        self._reminders_added.append({
            "user_id": user_id,
            "content": content,
            "trigger_at": trigger_at,
            "recurring": recurring,
            "action": action,
        })

    def add_note(self, user_id, note):
        self._notes.append(note)


class _FakeRemindersService:
    @staticmethod
    def parse_reminder_strict(text, tz_name=None):
        # Simulate parsing by returning a fixed UTC time when text looks like a time.
        if "9" in text or "утра" in text or "завтра" in text or "через" in text:
            return datetime(2026, 6, 18, 9, 0, tzinfo=timezone.utc), None, True
        return datetime(2026, 6, 18, 12, 0, tzinfo=timezone.utc), None, False


@pytest.fixture(autouse=True)
def reset_rs_module():
    rs_module.db = None
    rs_module.reminders_service = None
    rs_module._state.clear()
    yield
    rs_module.db = None
    rs_module.reminders_service = None
    rs_module._state.clear()


def test_record_interaction_counts_and_should_analyze_respects_threshold():
    rs_module.db = _FakeDb(prefs={"smart_reminders_enabled": 1})
    for _ in range(rs_module.SMART_REMINDERS_MESSAGE_THRESHOLD - 1):
        rs_module.record_interaction(1)
    assert not rs_module.should_analyze(1)
    rs_module.record_interaction(1)
    assert rs_module.should_analyze(1)


def test_should_analyze_disabled_by_env():
    with patch.object(rs_module, "SMART_REMINDERS_ENABLED", False):
        rs_module.db = _FakeDb(prefs={"smart_reminders_enabled": 1})
        rs_module.record_interaction(1)
        assert not rs_module.should_analyze(1)


def test_should_analyze_disabled_by_user_pref():
    rs_module.db = _FakeDb(prefs={"smart_reminders_enabled": 0})
    for _ in range(rs_module.SMART_REMINDERS_MESSAGE_THRESHOLD):
        rs_module.record_interaction(2)
    assert not rs_module.should_analyze(2)


def test_extract_json_pulls_array():
    text = "```json\n[{\"type\": \"note\", \"content\": \"hello\"}]\n```"
    result = rs_module._extract_json(text)
    assert result == [{"type": "note", "content": "hello"}]


def test_extract_json_returns_empty_for_invalid():
    assert rs_module._extract_json("not json") == []
    assert rs_module._extract_json("{}") == []


def test_is_duplicate_detects_overlap():
    assert rs_module._is_duplicate("buy milk", ["buy milk"], ["call mom"])
    assert not rs_module._is_duplicate("buy milk", ["call mom"], ["eggs"])


def test_escape_for_callback_is_safe_and_short():
    assert ":" not in rs_module._escape_for_callback("a:b")
    assert len(rs_module._escape_for_callback("x" * 200)) <= 40


@pytest.mark.asyncio
async def test_analyze_filters_by_confidence_and_dedup():
    rs_module.db = _FakeDb(
        messages=[
            {"role": "user", "content": " remind me to call mom"},
            {"role": "assistant", "content": "ok"},
        ],
        memories=[{"content": "buy milk"}],
        reminders=[{"content": "dentist at 3"}],
    )
    raw = '[{"type": "note", "content": "buy milk", "confidence": 0.9}, {"type": "reminder", "content": "call mom tomorrow 9", "time": "завтра в 9", "confidence": 0.85}]'
    async def fake_gen(*args, **kwargs):
        try:
            async for item in _async_gen(raw):
                yield item
        finally:
            pass

    with patch(
        "bot.services.reminder_suggest.generate_chat_completion",
        new=fake_gen,
    ):
        result = await rs_module.analyze(1)

    assert len(result) == 1
    assert result[0]["content"] == "call mom tomorrow 9"


@pytest.mark.asyncio
async def test_analyze_returns_empty_on_llm_error():
    rs_module.db = _FakeDb(messages=[{"role": "user", "content": "hello"}])
    async def fake_err_gen(*args, **kwargs):
        try:
            async for item in _async_gen_error():
                yield item
        finally:
            pass

    with patch(
        "bot.services.reminder_suggest.generate_chat_completion",
        new=fake_err_gen,
    ):
        result = await rs_module.analyze(1)
    assert result == []


def test_suggestion_text_and_keyboard():
    suggestions = [
        {"type": "reminder", "content": "call mom", "time": "завтра в 9", "reason": "important"},
        {"type": "note", "content": "idea", "time": "", "reason": ""},
    ]
    text = rs_module.suggestion_text(suggestions)
    assert "call mom" in text
    assert "idea" in text
    keyboard = rs_module.suggestion_keyboard(suggestions, 1)
    assert len(keyboard.inline_keyboard) == 3  # 2 suggestions + dismiss


@pytest.mark.asyncio
async def test_create_reminder_parses_time_and_stores():
    rs_module.db = _FakeDb(prefs={"timezone": "UTC"})
    rs_module.reminders_service = _FakeRemindersService()
    result = await rs_module.create_reminder(1, "call mom", "завтра в 9")
    assert "Напоминание добавлено" in result
    assert rs_module.db._reminders_added[0]["content"] == "call mom"


@pytest.mark.asyncio
async def test_create_reminder_fallback_when_time_unparseable():
    rs_module.db = _FakeDb(prefs={"timezone": "UTC"})
    rs_module.reminders_service = _FakeRemindersService()
    result = await rs_module.create_reminder(1, "call mom", "???")
    assert "Не удалось понять время" in result
    assert not rs_module.db._reminders_added


@pytest.mark.asyncio
async def test_create_task_stores_execute_action():
    rs_module.db = _FakeDb(prefs={"timezone": "UTC"})
    rs_module.reminders_service = _FakeRemindersService()
    result = await rs_module.create_task(1, "check Tesla", "через час")
    assert "Задача добавлена" in result
    assert rs_module.db._reminders_added[0]["action"] == "execute"




@pytest.mark.asyncio
async def test_analyze_and_suggest_resets_state_and_sends():
    rs_module.db = _FakeDb(prefs={"smart_reminders_enabled": 1})
    for _ in range(rs_module.SMART_REMINDERS_MESSAGE_THRESHOLD):
        rs_module.record_interaction(1)

    send = AsyncMock()
    suggestion = {"type": "note", "content": "save idea", "time": "", "confidence": 0.9, "reason": "good idea"}
    with patch.object(rs_module, "analyze", new=AsyncMock(return_value=[suggestion])):
        await rs_module.analyze_and_suggest(1, send)

    send.assert_awaited_once()
    # Counter should be reset.
    assert rs_module._user_state(1)["message_count"] == 0


def _async_gen(text):
    class _Chunk:
        message = type("M", (), {"content": text})()
    class _Final:
        message = type("M", (), {"content": ""})()
    return _AsyncIter([_Chunk(), _Final()])


def _async_gen_error():
    class _Err:
        error = "boom"
    return _AsyncIter([_Err()])


class _AsyncIter:
    def __init__(self, items):
        self._items = items
        self._idx = 0

    def __aiter__(self):
        return self

    async def __anext__(self):
        if self._idx >= len(self._items):
            raise StopAsyncIteration
        item = self._items[self._idx]
        self._idx += 1
        return (self._idx == len(self._items), item)
