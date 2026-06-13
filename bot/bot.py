from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties

from bot.settings import TELEGRAM_TOKEN

dp = Dispatcher()

_bot: Bot | None = None


def get_bot() -> Bot:
    global _bot
    if _bot is None:
        if not TELEGRAM_TOKEN:
            raise RuntimeError("TELEGRAM_TOKEN is not set. Create .env file.")
        _bot = Bot(token=TELEGRAM_TOKEN, default=DefaultBotProperties(parse_mode=None))
    return _bot


# Lazy module-level alias: importing the module does not require a token.
# Actual Bot instance is created on first attribute access.
class _LazyBot:
    def __getattr__(self, name: str):
        return getattr(get_bot(), name)


bot: Bot = _LazyBot()  # type: ignore[assignment]
