from aiogram import Router
from aiogram.filters.command import CommandStart
from aiogram.types import Message

from bot.keyboards.reply import base_keyboard

router = Router()


@router.message(CommandStart())
async def start_command(message: Message) -> None:
    await message.answer(
        "Привет! Я AI-бот на базе Ollama.\n\n"
        "🤖 Основные команды:\n"
        "/models — список моделей\n"
        "/model <name> — сменить модель\n"
        "/clear — очистить историю\n\n"
        "📝 Память и заметки:\n"
        "/note <текст> — сохранить заметку\n"
        "/memory_add [<категория>] <текст> — сохранить факт\n"
        "/memory — показать все факты\n\n"
        "⏰ Напоминания:\n"
        "/remind <время> <текст> — добавить напоминание\n"
        "/reminders — список напоминаний\n\n"
        "🔍 Мониторинг:\n"
        "/monitor_add <name> <url> [interval] — мониторинг сайта\n"
        "/monitors — список мониторов\n\n"
        "📊 Другое:\n"
        "/report — сводка\n"
        "/help — полная справка\n\n"
        "Напишите что угодно, чтобы начать разговор.",
        reply_markup=base_keyboard,
    )
