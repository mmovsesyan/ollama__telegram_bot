import pytest
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

from bot.services import briefing as briefing_module
from bot.services.profile import local_to_utc, utc_to_local


class _FakeDb:
    def __init__(
        self,
        prefs=None,
        reminders=None,
        memories=None,
    ):
        self._prefs = prefs or {}
        self._reminders = reminders or []
        self._memories = memories or []

    def get_user_prefs(self, user_id):
        return {**self._prefs, "user_id": user_id}

    def get_user_reminders(self, user_id):
        return list(self._reminders)

    def get_memories(self, user_id):
        return list(self._memories)


@pytest.fixture(autouse=True)
def reset_briefing_db():
    briefing_module.db = None
    yield
    briefing_module.db = None


@pytest.mark.asyncio
async def test_build_briefing_composes_all_blocks():
    prefs = {
        "timezone": "Europe/Moscow",
        "briefing_city": "Москва",
        "news_categories": "tech,ai",
    }
    tz = "Europe/Moscow"
    now_local = datetime.now(timezone.utc).astimezone(__import__("zoneinfo").ZoneInfo(tz))
    today_start = now_local.replace(hour=0, minute=0, second=0, microsecond=0)
    reminder_utc = local_to_utc(today_start.replace(hour=10, minute=30), tz).isoformat()

    reminders = [
        {"content": "позвонить брокеру", "trigger_at": reminder_utc, "enabled": 1, "action": "notify"},
        {"content": "отчёт по Tesla", "trigger_at": reminder_utc, "enabled": 1, "action": "execute"},
    ]
    memories = [{"content": "инвестирую в акции"}, {"content": "люблю краткие ответы"}]
    briefing_module.db = _FakeDb(prefs=prefs, reminders=reminders, memories=memories)

    with patch("bot.services.weather.get_weather", new=AsyncMock(return_value=("☀️ Москва, +20°", None))):
        with patch(
            "bot.services.rss_news.get_fresh_news",
            new=AsyncMock(return_value=("📌 TECH\nНовость 1", [], "rss")),
        ):
            text = await briefing_module.build_briefing(1)

    assert "Доброе утро" in text
    assert "Москва" in text
    assert "позвонить брокеру" in text
    assert "отчёт по Tesla" in text
    assert "Новость 1" in text
    assert "инвестирую в акции" in text


def test_default_city_for_tz():
    assert briefing_module._default_city_for_tz("Europe/Moscow") == "Москва"
    assert briefing_module._default_city_for_tz("Asia/Yerevan") == "Ереван"
    assert briefing_module._default_city_for_tz("America/New_York") == "Нью-Йорк"
    assert briefing_module._default_city_for_tz(None) == briefing_module.DEFAULT_BRIEFING_CITY


def test_todays_reminders_filters_today_only():
    tz = "Europe/Moscow"
    today = datetime.now(timezone.utc).astimezone(__import__("zoneinfo").ZoneInfo(tz))
    today_10 = local_to_utc(today.replace(hour=10, minute=0, second=0, microsecond=0), tz).isoformat()
    tomorrow_10 = local_to_utc(
        (today + timedelta(days=1)).replace(hour=10, minute=0, second=0, microsecond=0), tz
    ).isoformat()
    reminders = [
        {"content": "сегодня", "trigger_at": today_10, "enabled": 1, "action": "notify"},
        {"content": "завтра", "trigger_at": tomorrow_10, "enabled": 1, "action": "notify"},
    ]
    briefing_module.db = _FakeDb(prefs={"timezone": tz}, reminders=reminders)
    rems, tasks = briefing_module._todays_reminders(1)
    assert len(rems) == 1
    assert rems[0]["content"] == "сегодня"
    assert len(tasks) == 0


def test_category_topics_mapping():
    assert "технологии" in briefing_module.CATEGORY_TOPICS["tech"]
    assert "интеллект" in briefing_module.CATEGORY_TOPICS["ai"]
    # Unknown category falls back to itself.
    assert briefing_module.CATEGORY_TOPICS.get("foo", "foo") == "foo"


@pytest.mark.asyncio
async def test_send_briefing_swallows_errors(monkeypatch):
    prefs = {"timezone": "UTC", "briefing_city": "Москва", "news_categories": "tech"}
    briefing_module.db = _FakeDb(prefs=prefs)

    monkeypatch.setattr(
        "bot.services.briefing.build_briefing",
        lambda uid: (_ for _ in ()).throw(RuntimeError("boom")),
    )

    fake_bot = MagicMock()
    fake_bot.send_message = AsyncMock()
    await briefing_module.send_briefing(1, fake_bot)
    fake_bot.send_message.assert_awaited_once()
    args, kwargs = fake_bot.send_message.call_args
    assert "Не удалось собрать" in kwargs["text"]
