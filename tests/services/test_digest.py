import pytest
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

from bot.services import digest as digest_module
from bot.services.profile import local_to_utc, utc_to_local


class _FakeDb:
    def __init__(self, prefs=None, reminders=None, memories=None):
        self._prefs = prefs or {}
        self._reminders = reminders or []
        self._memories = memories or []

    def get_user_prefs(self, user_id):
        return {**self._prefs, "user_id": user_id}

    def get_user_reminders(self, user_id):
        return list(self._reminders)

    def get_memories_for_date(self, user_id, start_utc, end_utc):
        return [m for m in self._memories if m.get("user_id") == user_id]


@pytest.fixture(autouse=True)
def reset_digest_db():
    digest_module.db = None
    yield
    digest_module.db = None


@pytest.mark.asyncio
async def test_build_digest_composes_all_blocks():
    tz = "Europe/Moscow"
    now_local = datetime.now(timezone.utc).astimezone(__import__("zoneinfo").ZoneInfo(tz))
    today_start = now_local.replace(hour=0, minute=0, second=0, microsecond=0)
    today_10 = local_to_utc(today_start.replace(hour=10, minute=30), tz).isoformat()
    tomorrow_10 = local_to_utc(
        (today_start + timedelta(days=1)).replace(hour=10, minute=0), tz
    ).isoformat()

    prefs = {
        "timezone": tz,
        "news_categories": "tech,ai",
        "notes": "- купить молоко",
    }
    reminders = [
        {"content": "позвонить брокеру", "trigger_at": today_10, "enabled": 1, "action": "notify"},
        {"content": "отчёт по Tesla", "trigger_at": today_10, "enabled": 1, "action": "execute"},
        {"content": "встреча с инвестором", "trigger_at": tomorrow_10, "enabled": 1, "action": "notify"},
    ]
    memories = [
        {"user_id": 1, "content": "инвестирую в акции", "created_at": datetime.now(timezone.utc).isoformat()},
    ]
    digest_module.db = _FakeDb(prefs=prefs, reminders=reminders, memories=memories)

    with patch("bot.services.briefing._get_news_text", new=AsyncMock(return_value="📌 TECH\nНовость 1")):
        with patch.object(
            digest_module,
            "_build_digest_advice",
            new=AsyncMock(return_value="Фокус на завтрашнюю встречу."),
        ):
            text = await digest_module.build_digest(1)

    assert "Добрый вечер" in text
    assert "позвонить брокеру" in text
    assert "отчёт по Tesla" in text
    assert "встреча с инвестором" in text
    assert "Новость 1" in text
    assert "купить молоко" in text
    assert "инвестирую в акции" in text
    assert "Фокус на завтрашнюю встречу." in text


def test_reminders_in_window_today_and_tomorrow():
    tz = "Europe/Moscow"
    now_local = datetime.now(timezone.utc).astimezone(__import__("zoneinfo").ZoneInfo(tz))
    today_start = now_local.replace(hour=0, minute=0, second=0, microsecond=0)
    today_10 = local_to_utc(today_start.replace(hour=10, minute=0), tz).isoformat()
    tomorrow_10 = local_to_utc(
        (today_start + timedelta(days=1)).replace(hour=10, minute=0), tz
    ).isoformat()

    reminders = [
        {"content": "сегодня", "trigger_at": today_10, "enabled": 1, "action": "notify"},
        {"content": "завтра", "trigger_at": tomorrow_10, "enabled": 1, "action": "notify"},
    ]
    digest_module.db = _FakeDb(prefs={"timezone": tz}, reminders=reminders)

    today_rems, today_tasks = digest_module._reminders_in_window(1, 0)
    assert len(today_rems) == 1
    assert today_rems[0]["content"] == "сегодня"
    assert len(today_tasks) == 0

    tomorrow_rems, tomorrow_tasks = digest_module._reminders_in_window(1, 1)
    assert len(tomorrow_rems) == 1
    assert tomorrow_rems[0]["content"] == "завтра"


def test_todays_memories_filters_by_user_id():
    tz = "UTC"
    digest_module.db = _FakeDb(
        prefs={"timezone": tz},
        memories=[
            {"user_id": 1, "content": "user1 fact", "created_at": datetime.now(timezone.utc).isoformat()},
            {"user_id": 2, "content": "user2 fact", "created_at": datetime.now(timezone.utc).isoformat()},
        ],
    )
    result = digest_module._todays_memories(1)
    assert len(result) == 1
    assert result[0]["content"] == "user1 fact"


@pytest.mark.asyncio
async def test_build_digest_advice_no_context():
    advice = await digest_module._build_digest_advice([], [], [], [], [])
    assert "Отдыхай" in advice


@pytest.mark.asyncio
async def test_send_digest_swallows_errors(monkeypatch):
    prefs = {"timezone": "UTC", "news_categories": "tech"}
    digest_module.db = _FakeDb(prefs=prefs)

    monkeypatch.setattr(
        "bot.services.digest.build_digest",
        lambda uid: (_ for _ in ()).throw(RuntimeError("boom")),
    )

    fake_bot = MagicMock()
    fake_bot.send_message = AsyncMock()
    await digest_module.send_digest(1, fake_bot)
    fake_bot.send_message.assert_awaited_once()
    args, kwargs = fake_bot.send_message.call_args
    assert "Не удалось собрать" in kwargs["text"]
