from aiogram import Router
from aiogram.filters.command import CommandStart
from aiogram.types import Message

from bot.keyboards.reply import command_keyboard

router = Router()


@router.message(CommandStart())
async def start_command(message: Message) -> None:
    await message.answer(
        "Привет! Я AI-бот на базе Ollama.\n\n"
        "Просто **напиши** или **скажи голосом**, что нужно:\n"
        "• «погода в Москве»\n"
        "• «напомни через 5 минут позвонить»\n"
        "• «задача каждое утро в 9 покажи новости»\n"
        "• «заметка: купить акции TSLA»\n"
        "• «запомни, я люблю краткие ответы»\n"
        "• «поищи последние новости Tesla»\n\n"
        "Или используй кнопки внизу.\n"
        "Нажми /help для примеров и команд.",
        reply_markup=command_keyboard,
    )
