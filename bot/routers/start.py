from aiogram import Router
from aiogram.filters.command import CommandStart
from aiogram.types import Message

from bot.keyboards.reply import base_keyboard

router = Router()


@router.message(CommandStart())
async def start_command(message: Message) -> None:
    await message.answer(
        "Привет! Я AI-бот на базе Ollama.\n\n"
        "Команды:\n"
        "/models — список доступных моделей\n"
        "/model <name> — сменить модель\n"
        "/clear — очистить историю\n"
        "/help — помощь\n\n"
        "Напишите что угодно, чтобы начать разговор.",
        reply_markup=base_keyboard,
    )
