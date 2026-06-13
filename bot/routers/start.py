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
        "• «каждое утро в 9 покажи новости»\n"
        "• «запомни, я люблю краткие ответы»\n"
        "• «поищи последние новости Tesla»\n\n"
        "Кнопки внизу — быстрый доступ к частым действиям.\n"
        "Нажми /help для примеров и команд.",
        reply_markup=command_keyboard,
    )
