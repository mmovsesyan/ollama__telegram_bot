from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties

from bot.settings import TELEGRAM_TOKEN

bot = Bot(token=TELEGRAM_TOKEN, default=DefaultBotProperties(parse_mode=None))
dp = Dispatcher()
