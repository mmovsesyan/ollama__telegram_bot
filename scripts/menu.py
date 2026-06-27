#!/usr/bin/env python3
"""Interactive CLI menu for managing the Ollama Telegram Bot.

Works on macOS, Linux and any terminal that supports ANSI escape codes.
Provides start / stop / restart / status / logs / install service actions.
"""

import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from bot.services.supervisor import start, stop, restart, status, tail_logs  # noqa: E402


def clear() -> None:
    # Use ANSI escape to clear screen without spawning a subprocess/shell.
    print("\033[2J\033[H", end="")


def header() -> None:
    clear()
    print("╔══════════════════════════════════════════╗")
    print("║     🤖 Ollama Telegram Bot Manager       ║")
    print("╚══════════════════════════════════════════╝")
    print(f"   📁 {ROOT}")
    print(f"   📊 {status()}")
    print()


def prompt() -> str:
    print(" [1] Старт      [2] Стоп      [3] Рестарт")
    print(" [4] Статус     [5] Логи      [6] Установить автостарт")
    print(" [0] Выход")
    print()
    return input("Выбор: ").strip()


def show_logs() -> None:
    print(tail_logs(lines=40))
    input("\nНажми Enter...")


def install_service() -> None:
    script = ROOT / "install_service.sh"
    if not script.exists():
        print("❌ install_service.sh не найден.")
        input("\nНажми Enter...")
        return
    shell = shutil.which("bash") or "/bin/bash"
    print("🔧 Запуск install_service.sh...")
    try:
        # Path is hard-coded inside project root; shell=False, no user input.
        result = subprocess.run([shell, str(script)], cwd=ROOT, check=False).returncode  # nosec B603
        print(f"Код возврата: {result}")
    except Exception as exc:
        print(f"❌ Ошибка: {exc}")
    input("\nНажми Enter...")


def main() -> None:
    # Graceful shutdown on Ctrl+C.
    signal.signal(signal.SIGINT, lambda _signum, _frame: sys.exit(0))

    while True:
        header()
        choice = prompt()

        if choice == "1":
            ok, msg = start()
            print(("✅ " if ok else "❌ ") + msg)
            time.sleep(1)
        elif choice == "2":
            ok, msg = stop()
            print(("✅ " if ok else "❌ ") + msg)
            time.sleep(1)
        elif choice == "3":
            ok, msg = restart()
            print(("✅ " if ok else "❌ ") + msg)
            time.sleep(1)
        elif choice == "4":
            print(status())
            input("\nНажми Enter...")
        elif choice == "5":
            show_logs()
        elif choice == "6":
            install_service()
        elif choice == "0":
            print("👋 Выход.")
            sys.exit(0)
        else:
            print("❌ Неверный выбор.")
            time.sleep(1)


if __name__ == "__main__":
    main()
