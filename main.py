import asyncio
import os
import re
import sys


def _env_file_valid() -> bool:
    """Check that .env exists and contains non-empty required keys."""
    if not os.path.exists(".env"):
        return False

    required = {
        "TELEGRAM_TOKEN": r"^\d+:[A-Za-z0-9_-]+$",
        "OLLAMA_API_KEY": r"^.+$",
    }

    values: dict[str, str] = {}
    with open(".env", "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            values[key.strip()] = value.strip()

    for key, pattern in required.items():
        value = values.get(key, "")
        if not value or "your" in value.lower() or not re.match(pattern, value):
            return False
    return True


def _run_setup() -> None:
    """Invoke interactive setup if dependencies are available."""
    try:
        from setup_env import ensure_env_file

        ensure_env_file()
    except ImportError:
        print("❌ .env is missing or invalid and setup_env.py is unavailable.")
        print("   Please create .env manually from .env.example")
        sys.exit(1)


if __name__ == "__main__":
    if not _env_file_valid():
        print("⚠️  .env is missing or required keys are empty/invalid.")
        _run_setup()
        if not _env_file_valid():
            print("❌ .env still invalid. Exiting.")
            sys.exit(1)

    from bot import main

    asyncio.run(main())
