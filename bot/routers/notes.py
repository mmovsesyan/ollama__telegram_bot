import logging

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from bot.keyboards.reply import cancel_keyboard, command_keyboard
from bot.security import is_allowed as _is_allowed
from bot.states import BotStates
from bot.routers.common import (
    _fsm_guard,
    _refresh_completion_system_prompt,
)

router = Router()
logger = logging.getLogger(__name__)

# Injected from bot/__init__.py at startup.
db = None


@router.message(lambda m: m.text and m.text.startswith("/note"))
async def cmd_note(message: Message, state: FSMContext):
    await state.clear()
    if message.from_user is None:
        return
    if not _is_allowed(message.from_user.id):
        return
    if db is None:
        await message.answer("База данных недоступна.", reply_markup=command_keyboard)
        return

    parts = message.text.split(maxsplit=1)
    if len(parts) < 2:
        notes = db.get_notes(message.from_user.id)
        if notes:
            await message.answer(
                f"📝 Твои заметки:\n{notes}", reply_markup=command_keyboard
            )
        else:
            await message.answer(
                "📝 Что записать?\n" "Пример: купить акции TSLA",
                reply_markup=cancel_keyboard,
            )
            await state.set_state(BotStates.waiting_note)
        return

    db.add_note(message.from_user.id, parts[1])
    _refresh_completion_system_prompt(message.from_user.id)
    await message.answer(
        f"✅ Заметка сохранена. AI будет помнить это.\n\n📝 {parts[1]}",
        reply_markup=command_keyboard,
    )


@router.callback_query(F.data == "note_quick:manual")
async def cb_note_manual(callback: CallbackQuery, state: FSMContext):
    if not callback.from_user:
        return
    if not _is_allowed(callback.from_user.id):
        await callback.answer("Нет доступа", show_alert=True)
        return
    await callback.message.answer(
        "📝 Что записать?",
        reply_markup=cancel_keyboard,
    )
    await state.set_state(BotStates.waiting_note)
    await callback.answer("Введи заметку")


@router.message(BotStates.waiting_note)
async def process_note(message: Message, state: FSMContext):
    if message.from_user is None:
        await state.clear()
        return
    if message.text is None:
        await message.answer("Ожидался текст.", reply_markup=cancel_keyboard)
        await state.clear()
        return
    if await _fsm_guard(message, state):
        return
    if db is None:
        await message.answer("База данных недоступна.", reply_markup=command_keyboard)
        await state.clear()
        return
    db.add_note(message.from_user.id, message.text)
    _refresh_completion_system_prompt(message.from_user.id)
    await message.answer(
        f"✅ Заметка сохранена. AI будет помнить это.\n\n📝 {message.text}",
        reply_markup=command_keyboard,
    )
    await state.clear()
