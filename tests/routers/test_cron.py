from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from bot.db import Database
from bot.routers import cron as cron_module
from bot.services import news_categories as nc_module
from bot.states import BotStates


def _message(user_id: int = 42, text: str = ""):
    msg = MagicMock()
    msg.from_user = MagicMock()
    msg.from_user.id = user_id
    msg.text = text
    msg.answer = AsyncMock()
    return msg


@pytest.fixture
def fresh_db(tmp_path):
    db_path = tmp_path / "test.db"
    db = Database(str(db_path))
    cron_module.db = db
    nc_module.db = db
    yield db
    cron_module.db = None
    nc_module.db = None


@pytest.fixture(autouse=True)
def reset_state():
    cron_module.db = None
    nc_module.db = None
    yield
    cron_module.db = None
    nc_module.db = None


@pytest.mark.asyncio
async def test_cmd_news_subscribe_adds_category(fresh_db):
    fresh_db.set_user_prefs(42, news_categories="tech")
    msg = _message(text="/news_subscribe markets")
    state = MagicMock()
    state.clear = AsyncMock()

    await cron_module.cmd_news_subscribe(msg, state)

    msg.answer.assert_awaited_once()
    text = msg.answer.await_args.args[0]
    assert "Добавлено" in text
    assert "markets" in text
    prefs = fresh_db.get_user_prefs(42)
    assert prefs["news_categories"] == "tech,markets"


@pytest.mark.asyncio
async def test_cmd_news_subscribe_without_category_asks(fresh_db):
    msg = _message(text="/news_subscribe")
    state = MagicMock()
    state.clear = AsyncMock()

    await cron_module.cmd_news_subscribe(msg, state)

    text = msg.answer.await_args.args[0]
    assert "Какую категорию добавить" in text


@pytest.mark.asyncio
async def test_cmd_news_unsubscribe_removes_category(fresh_db):
    fresh_db.set_user_prefs(42, news_categories="tech,markets")
    msg = _message(text="/news_unsubscribe markets")
    state = MagicMock()
    state.clear = AsyncMock()

    await cron_module.cmd_news_unsubscribe(msg, state)

    text = msg.answer.await_args.args[0]
    assert "Убрано" in text
    assert fresh_db.get_user_prefs(42)["news_categories"] == "tech"


@pytest.mark.asyncio
async def test_process_news_digest(fresh_db):
    msg = _message(text="дайджест")
    state = MagicMock()
    state.clear = AsyncMock()
    state.get_data = AsyncMock(return_value={})

    with patch(
        "bot.services.news_categories.rss_news_service.get_fresh_news",
        new=AsyncMock(return_value=("", [], "rss")),
    ):
        await cron_module.process_news(msg, state)

    text = msg.answer.await_args.args[0]
    assert "ничего не нашёл" in text or "Персональный дайджест" in text


@pytest.mark.asyncio
async def test_cmd_news_topic_triggers_search(fresh_db):
    msg = _message(text="/news Tesla")
    state = MagicMock()
    state.clear = AsyncMock()

    with patch(
        "bot.services.rss_news.get_fresh_news",
        new=AsyncMock(return_value=("Новость Tesla", [], "rss")),
    ):
        await cron_module.cmd_news(msg, state)

    text = msg.answer.await_args.args[0]
    assert "Tesla" in text or "Ищу новости" in text
