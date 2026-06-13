from aiogram import Router
from aiogram.filters.command import CommandStart
from aiogram.types import Message, ReplyKeyboardRemove

from bot.keyboards.reply import command_keyboard

router = Router()


@router.message(CommandStart())
async def start_command(message: Message) -> None:
    await message.answer(
        "Привет! Я AI-бот на базе Ollama.\n\n"
        "Кнопки внизу — быстрый доступ к командам:\n\n"
        "🤖 AI:\n"
        "  🤖 Модели — список моделей\n"
        "  ❓ Помощь — справка\n"
        "  🗑 Очистить — сбросить чат\n\n"
        "🌐 Поиск:\n"
        "  🔍 Поиск — в интернете\n"
        "  🌤 Погода — по городу\n"
        "  📰 Новости — актуальные\n\n"
        "📝 Память:\n"
        "  🧠 Память — факты и заметки\n"
        "  📝 Заметка — сохранить мысль\n\n"
        "⏰ Напоминания:\n"
        "  ⏰ Напоминание — добавить\n\n"
        "🔍 Мониторинг:\n"
        "  ➕ Монитор — добавить сайт\n"
        "  🔍 Мониторы — список\n\n"
        "📊 Другое:\n"
        "  📊 Отчёт — сводка\n\n"
        "Или напишите что угодно для разговора с AI.",
    )
