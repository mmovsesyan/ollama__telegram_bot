from pathlib import Path

import pytest

from bot.services import supervisor as supervisor_module


@pytest.fixture(autouse=True)
def reset_pidfile():
    supervisor_module.PID_FILE = Path("bot.pid")
    supervisor_module.LOG_FILE = Path("bot.log")
    if supervisor_module.PID_FILE.exists():
        supervisor_module.PID_FILE.unlink()
    yield
    if supervisor_module.PID_FILE.exists():
        supervisor_module.PID_FILE.unlink()


@pytest.mark.asyncio
async def test_status_when_not_running():
    assert "не запущен" in await supervisor_module.status()


@pytest.mark.asyncio
async def test_read_pid_none_when_missing():
    assert await supervisor_module.read_pid() is None


@pytest.mark.asyncio
async def test_is_running_false_when_pidfile_missing():
    assert await supervisor_module.is_running() is False


@pytest.mark.asyncio
async def test_start_writes_pidfile_and_stops(monkeypatch):
    """Start a tiny dummy python process, verify pidfile, then stop."""
    dummy = ["python", "-c", "import time; time.sleep(60)"]
    monkeypatch.setattr(supervisor_module, "_python_cmd", lambda: dummy)

    ok, msg = await supervisor_module.start()
    assert ok, msg
    assert supervisor_module.PID_FILE.exists()
    pid = await supervisor_module.read_pid()
    assert pid is not None
    assert await supervisor_module.is_running() is True

    ok, msg = await supervisor_module.stop()
    assert ok, msg
    assert not await supervisor_module.is_running()


@pytest.mark.asyncio
async def test_stop_cleans_stale_pidfile():
    supervisor_module.PID_FILE.write_text("99999")
    ok, msg = await supervisor_module.stop()
    assert ok
    assert not supervisor_module.PID_FILE.exists()


@pytest.mark.asyncio
async def test_start_refuses_when_already_running(monkeypatch):
    dummy = ["python", "-c", "import time; time.sleep(60)"]
    monkeypatch.setattr(supervisor_module, "_python_cmd", lambda: dummy)

    ok, _msg = await supervisor_module.start()
    assert ok
    ok2, msg2 = await supervisor_module.start()
    assert not ok2
    assert "уже запущен" in msg2
    await supervisor_module.stop()


@pytest.mark.asyncio
async def test_restart_stops_and_starts(monkeypatch):
    dummy = ["python", "-c", "import time; time.sleep(60)"]
    monkeypatch.setattr(supervisor_module, "_python_cmd", lambda: dummy)

    ok, _msg = await supervisor_module.start()
    assert ok
    first_pid = await supervisor_module.read_pid()

    ok, msg = await supervisor_module.restart()
    assert ok, msg
    assert await supervisor_module.is_running()
    assert await supervisor_module.read_pid() != first_pid

    await supervisor_module.stop()
