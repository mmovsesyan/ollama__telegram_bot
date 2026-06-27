"""Local process supervisor for the bot.

Provides a minimal cross-platform watchdog that:
- starts the bot in a child process,
- restarts it on unexpected exit,
- exposes status / stop / restart / logs actions,
- writes a pidfile and captures logs.

Used by the Telegram admin control panel and by the CLI menu so there is a
single source of truth for whether the bot is running.
"""

import asyncio
import logging
import os
import platform
import shutil
import signal
import subprocess
import sys
from pathlib import Path

logger = logging.getLogger(__name__)

PID_FILE = Path("bot.pid")
LOG_FILE = Path("bot.log")


def _project_root() -> Path:
    return Path(__file__).resolve().parent.parent.parent


def _python_cmd() -> list[str]:
    """Return the command to run main.py via poetry."""
    poetry = shutil.which("poetry")
    if poetry:
        return [poetry, "run", "python", str(_project_root() / "main.py")]
    # Fallback: run with the same interpreter if dependencies are installed.
    return [sys.executable, str(_project_root() / "main.py")]


async def is_running() -> bool:
    if not PID_FILE.exists():
        return False
    try:
        pid = int(PID_FILE.read_text().strip())
    except Exception:
        return False
    if pid <= 0:
        return False
    # Cross-platform "is process alive" check.
    if platform.system() == "Windows":
        try:
            import ctypes

            kernel32 = ctypes.windll.kernel32
            handle = kernel32.OpenProcess(1, False, pid)  # PROCESS_TERMINATE = 1
            if not handle:
                return False
            kernel32.CloseHandle(handle)
            return True
        except Exception:
            return False
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except Exception:
        return False


async def read_pid() -> int | None:
    if not PID_FILE.exists():
        return None
    try:
        return int(PID_FILE.read_text().strip())
    except Exception:
        return None


async def start() -> tuple[bool, str]:
    if await is_running():
        return False, f"Бот уже запущен (PID {await read_pid()})."

    env = os.environ.copy()
    env["BOT_SUPERVISED"] = "1"

    # Rotate log if it grows too large (keep one backup).
    if LOG_FILE.exists() and LOG_FILE.stat().st_size > 10 * 1024 * 1024:
        backup = LOG_FILE.with_suffix(".log.1")
        if backup.exists():
            backup.unlink()
        LOG_FILE.rename(backup)

    cmd = _python_cmd()
    try:
        log_fp = LOG_FILE.open("ab")
    except Exception as exc:
        logger.exception("Failed to open log file")
        return False, f"Не удалось открыть лог-файл: {exc}"

    try:
        # Command is constructed from hard-coded paths and the Poetry binary
        # discovered on PATH; no user input is passed to the shell.
        proc = subprocess.Popen(  # nosec B603
            cmd,
            cwd=_project_root(),
            stdout=log_fp,
            stderr=subprocess.STDOUT,
            env=env,
            start_new_session=True,
        )
    except Exception as exc:
        log_fp.close()
        logger.exception("Failed to start bot")
        return False, f"Не удалось запустить бота: {exc}"

    # Don't let the log file descriptor leak in the supervisor process; the
    # child inherited it via Popen and will keep writing to it.
    try:
        log_fp.close()
    except Exception:
        pass

    # Wait briefly to catch immediate startup failure.
    await asyncio.sleep(2)
    if proc.poll() is not None:
        return False, f"Процесс завершился сразу (код {proc.poll()}). Смотри {LOG_FILE}."

    PID_FILE.write_text(str(proc.pid))
    return True, f"Бот запущен (PID {proc.pid})."


async def stop() -> tuple[bool, str]:
    pid = await read_pid()
    if pid is None:
        # Also try to kill any stray process matching main.py.
        await _kill_stragglers()
        return True, "Бот не был запущен (PID-файл отсутствовал)."

    if not await is_running():
        PID_FILE.unlink(missing_ok=True)
        await _kill_stragglers()
        return True, "Бот не работал (PID-файл устарел)."

    try:
        await _graceful_stop(pid)
    except Exception as exc:
        logger.warning("Graceful stop failed for PID %s: %s", pid, exc)
        return False, f"Не удалось остановить бота: {exc}"

    PID_FILE.unlink(missing_ok=True)
    await _kill_stragglers()
    return True, "Бот остановлен."


async def _graceful_stop(pid: int) -> None:
    if platform.system() == "Windows":
        import ctypes

        kernel32 = ctypes.windll.kernel32
        handle = kernel32.OpenProcess(1, False, pid)
        if handle:
            kernel32.TerminateProcess(handle, 0)
            kernel32.CloseHandle(handle)
        return

    os.kill(pid, signal.SIGTERM)
    # Wait up to 10 seconds for graceful shutdown.
    deadline = asyncio.get_event_loop().time() + 10
    while asyncio.get_event_loop().time() < deadline:
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return
        except PermissionError:
            return
        await asyncio.sleep(0.2)
    os.kill(pid, signal.SIGKILL)


async def _kill_stragglers() -> None:
    """Kill any python process running this project's main.py."""
    main_py = str(_project_root() / "main.py")
    if platform.system() == "Windows":
        return  # pgrep not available; rely on pidfile.
    pgrep = shutil.which("pgrep")
    if not pgrep:
        return
    try:
        result = subprocess.run(
            [pgrep, "-f", f"python.*{main_py}"],  # nosec B603
            capture_output=True,
            text=True,
            check=False,
        )
    except FileNotFoundError:
        logger.debug("pgrep not found, skipping stray process cleanup")
        return
    for line in result.stdout.splitlines():
        pid_str = line.strip()
        if not pid_str:
            continue
        try:
            pid = int(pid_str)
            if pid == os.getpid():
                continue
            os.kill(pid, signal.SIGTERM)
        except (ProcessLookupError, PermissionError):
            # Process already gone or not ours; safe to ignore.
            pass
        except Exception as exc:
            logger.warning("Failed to kill stray bot process %s: %s", pid_str, exc)


async def restart() -> tuple[bool, str]:
    await stop()
    ok, msg = await start()
    return ok, f"Рестарт: {msg}"


async def status() -> str:
    if not await is_running():
        return "❌ Бот не запущен"
    pid = await read_pid()
    return f"✅ Бот работает (PID {pid})"


async def tail_logs(lines: int = 30) -> str:
    if not LOG_FILE.exists():
        return "Лог-файл пока не создан."
    try:
        with LOG_FILE.open("r", encoding="utf-8", errors="replace") as f:
            all_lines = f.readlines()
    except Exception as exc:
        return f"Не удалось прочитать лог: {exc}"
    tail = all_lines[-lines:]
    if not tail:
        return "Лог пуст."
    # Telegram message limit is ~4096 chars; truncate if needed.
    text = "".join(tail)
    if len(text) > 3800:
        text = text[-3800:]
    return f"<pre>{text}</pre>"


def ensure_running() -> None:
    """Called on startup when the bot itself is supervised.

    This is a no-op placeholder; the real watchdog runs in a separate process
    (see scripts/supervisor_watchdog.py) so the bot process stays simple.
    """
    pass
