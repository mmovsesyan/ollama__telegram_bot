#!/usr/bin/env python3
"""Interactive setup for .env file. Keeps asking until required keys are provided."""
import os
import re


REQUIRED_PLACEHOLDERS = {
    "TELEGRAM_TOKEN": ["your_telegram_bot_token_here", ""],
    "OLLAMA_API_KEY": ["your_ollama_api_key_here", ""],
}


def prompt(text: str, default: str = "") -> str:
    value = input(f"{text} [{default}]: ").strip()
    return value if value else default


def validate_token(token: str) -> bool:
    return bool(re.match(r"^\d+:[A-Za-z0-9_-]+$", token))


def is_placeholder(value: str, key: str) -> bool:
    if not value:
        return True
    lower = value.lower()
    if "your" in lower and key.lower().replace("_", " ") in lower:
        return True
    return value in REQUIRED_PLACEHOLDERS.get(key, [])


def main() -> None:
    print("⚙️  Interactive setup for Ollama Telegram Bot")
    print("   Required: Telegram Bot Token + Ollama API Key")
    print("   Press Ctrl+C to cancel.\n")

    token = ""
    while not validate_token(token):
        token = prompt("Telegram Bot Token from @BotFather")
        if not validate_token(token):
            print("   ❌ Invalid format. Example: 123456789:ABC...")
            print("   Please try again.\n")

    api_key = ""
    while not api_key:
        api_key = prompt("Ollama API key")
        if not api_key:
            print("   ❌ API key is required. Please try again.\n")

    allowed = prompt("Allowed Telegram user IDs (comma-separated, leave empty for any)")
    host = prompt("Ollama API host", default="https://api.ollama.com")
    model = prompt("Ollama model name", default="kimi-k2.7-code:cloud")

    web_key = prompt("Ollama Web Search API key (optional, falls back to OLLAMA_API_KEY)")
    if not web_key:
        web_key = api_key

    env_content = f"""TELEGRAM_TOKEN={token}
ALLOWED_CHAT_IDS={allowed}
OLLAMA_API_HOST={host}
OLLAMA_BOT_MODEL={model}
OLLAMA_API_KEY={api_key}
OLLAMA_WEB_API_KEY={web_key}
WHISPER_MODEL=tiny
WHISPER_DEVICE=auto
WHISPER_COMPUTE_TYPE=default
"""

    with open(".env", "w", encoding="utf-8") as f:
        f.write(env_content)

    print("\n✅ .env created successfully.")
    print("   Start the bot: poetry run python main.py")


def ensure_env_file() -> None:
    """Create .env if missing or if required keys are empty/placeholder."""
    if os.path.exists(".env"):
        from dotenv import dotenv_values
        env = dotenv_values(".env")
        missing = [
            key for key in REQUIRED_PLACEHOLDERS
            if is_placeholder(env.get(key, ""), key)
        ]
        if not missing:
            return
        print(f"⚠️  .env exists but missing/placeholder values for: {', '.join(missing)}")
        print("   Let's recreate it.\n")
    main()


if __name__ == "__main__":
    ensure_env_file()
