#!/usr/bin/env python3
"""Interactive setup for .env file."""
import os
import re


def prompt(text: str, default: str = "") -> str:
    value = input(f"{text} [{default}]: ").strip()
    return value if value else default


def validate_token(token: str) -> bool:
    return bool(re.match(r"^\d+:[A-Za-z0-9_-]+$", token))


def main() -> None:
    print("⚙️  Interactive setup for Ollama Telegram Bot\n")

    token = ""
    while not validate_token(token):
        token = prompt("Telegram Bot Token from @BotFather")
        if not validate_token(token):
            print("   Invalid format. Example: 123456789:ABC...")

    allowed = prompt("Allowed Telegram user IDs (comma-separated, leave empty for any)")

    host = prompt("Ollama API host", default="https://api.ollama.com")
    model = prompt("Ollama model name", default="kimi-k2.7-code:cloud")

    api_key = ""
    while not api_key:
        api_key = prompt("Ollama API key")
        if not api_key:
            print("   API key is required.")

    web_key = prompt("Ollama Web Search API key (optional, falls back to OLLAMA_API_KEY)")
    if not web_key:
        web_key = api_key

    env_content = f"""TELEGRAM_TOKEN={token}
ALLOWED_CHAT_IDS={allowed}
OLLAMA_API_HOST={host}
OLLAMA_BOT_MODEL={model}
OLLAMA_API_KEY={api_key}
OLLAMA_WEB_API_KEY={web_key}
"""

    with open(".env", "w", encoding="utf-8") as f:
        f.write(env_content)

    print("\n✅ .env created successfully.")
    print("   Start the bot: poetry run python main.py")


if __name__ == "__main__":
    main()
