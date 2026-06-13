from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties

from bot.settings import TELEGRAM_TOKEN

dp = Dispatcher()


def get_bot() -> Bot:
    """Return the real Bot instance. main.py must load .env before importing this module."""
    return bot


# Real Bot instance for aiogram 3.x compatibility.
# main.py loads .env into os.environ BEFORE importing bot.bot, so TELEGRAM_TOKEN is always set here.
if not TELEGRAM_TOKEN:
    raise RuntimeError("TELEGRAM_TOKEN is not set. Create .env file.")

bot: Bot = Bot(token=TELEGRAM_TOKEN, default=DefaultBotProperties(parse_mode=None))
