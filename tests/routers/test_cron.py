from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from bot.db import Database
from bot.routers import cron as cron_module
from bot.services import news_categories as nc_module


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


def test_is_safe_monitor_url_accepts_public_and_blocks_internal():
    assert cron_module._is_safe_monitor_url("http://example.com")[0] is True
    assert cron_module._is_safe_monitor_url("https://example.com/path")[0] is True

    blocked = (
        "http://localhost",
        "http://127.0.0.1/health",
        "http://[::1]/",
        "http://192.168.1.1",
        "http://10.0.0.1",
        "http://169.254.169.254/latest/meta-data/",
        "ftp://example.com",
        "http://",
    )
    for url in blocked:
        ok, reason = cron_module._is_safe_monitor_url(url)
        assert ok is False, f"expected {url} to be blocked, got ok=True"
        assert reason, f"expected blocking reason for {url}"


@pytest.mark.asyncio
async def test_process_monitor_add_rejects_localhost(fresh_db):
    msg = _message(text="/monitor_add Test http://localhost")
    await cron_module._process_monitor_add(msg, "Test", "http://localhost", 300)

    assert fresh_db.get_monitors(42) == []
    msg.answer.assert_awaited()
    text = msg.answer.await_args.args[0]
    assert "URL не разрешён" in text


@pytest.mark.asyncio
async def test_process_monitor_add_accepts_public_url(fresh_db):
    msg = _message(text="/monitor_add Test http://example.com")

    mock_response = AsyncMock()
    mock_response.status = 200
    mock_response.__aenter__ = AsyncMock(return_value=mock_response)
    mock_response.__aexit__ = AsyncMock(return_value=False)

    mock_session = MagicMock()
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)
    mock_session.get = MagicMock(return_value=mock_response)

    with patch.object(cron_module.aiohttp, "ClientSession", return_value=mock_session):
        with patch.object(
            cron_module,
            "_is_safe_monitor_url_async",
            new=AsyncMock(return_value=(True, "")),
        ):
            await cron_module._process_monitor_add(
                msg, "Test", "http://example.com", 300
            )

    monitors = fresh_db.get_monitors(42)
    assert len(monitors) == 1
    assert monitors[0]["url"] == "http://example.com"
    msg.answer.assert_awaited()


@pytest.mark.asyncio
async def test_process_monitor_add_async_dns_rejects_private_resolution(fresh_db):
    msg = _message(text="/monitor_add Test http://rebind.example")

    with patch.object(
        cron_module,
        "_is_safe_monitor_url_async",
        new=AsyncMock(return_value=(False, "хост разрешается в запрещённый IP")),
    ):
        await cron_module._process_monitor_add(
            msg, "Test", "http://rebind.example", 300
        )

    assert fresh_db.get_monitors(42) == []
    msg.answer.assert_awaited()
    text = msg.answer.await_args.args[0]
    assert "URL не разрешён" in text
    assert "запрещённый IP" in text


@pytest.mark.asyncio
async def test_is_safe_monitor_url_async_blocks_private_dns_resolution():
    import socket

    with patch.object(
        socket,
        "getaddrinfo",
        return_value=[(socket.AF_INET, 0, 0, "", ("127.0.0.1", 0))],
    ):
        ok, reason = await cron_module._is_safe_monitor_url_async(
            "http://rebind.example"
        )
    assert ok is False
    assert "127.0.0.1" in reason


@pytest.mark.asyncio
async def test_is_safe_monitor_url_async_allows_public_dns_resolution():
    import socket

    with patch.object(
        socket,
        "getaddrinfo",
        return_value=[
            (socket.AF_INET, 0, 0, "", ("93.184.216.34", 0)),
            (socket.AF_INET6, 0, 0, "", ("2606:2800:220:1:248:1893:25c8:1946", 0)),
        ],
    ):
        ok, reason = await cron_module._is_safe_monitor_url_async("http://example.com")
    assert ok is True
    assert reason == ""
