"""Telegram admin control panel for the bot process.

Only users whose Telegram ID is in ADMIN_TELEGRAM_IDS can use these commands.
Provides start/stop/restart/status/logs actions so the owner can manage the
bot remotely without SSH.
"""

import logging

from aiogram import Router
from aiogram.fsm.context import FSMContext
from aiogram.types import Message

from bot.keyboards.reply import command_keyboard
from bot.routers.common import _typing_until
from bot.services import supervisor
from bot.settings import ADMIN_IDS

router = Router()
logger = logging.getLogger(__name__)


def _is_bot_admin(user_id: int | None) -> bool:
    if user_id is None:
        return False
    if not ADMIN_IDS:
        return False
    return user_id in ADMIN_IDS


async def _run_supervisor(message: Message, coro, action: str):
    """Acknowledge the admin command, keep typing alive, and run a supervisor coroutine."""
    if message.from_user is None:
        return
    user_id = message.from_user.id
    status_msg = await message.answer(f"🛠 {action}...")
    try:
        result = await _typing_until(user_id, coro)
        if isinstance(result, tuple) and len(result) == 2:
            ok, msg = result
            await status_msg.edit_text(("✅ " if ok else "❌ ") + msg)
        else:
            await status_msg.edit_text(str(result))
    except Exception as e:
        logger.exception("Supervisor command failed for %s", action)
        await status_msg.edit_text(f"❌ Ошибка: {str(e)[:200]}")


@router.message(lambda m: m.text and m.text.startswith("/bot_status"))
async def cmd_bot_status(message: Message, state: FSMContext):
    await state.clear()
    if message.from_user is None:
        return
    if not _is_bot_admin(message.from_user.id):
        return
    await _run_supervisor(message, supervisor.status(), "Получаю статус")


@router.message(lambda m: m.text and m.text.startswith("/bot_start"))
async def cmd_bot_start(message: Message, state: FSMContext):
    await state.clear()
    if message.from_user is None:
        return
    if not _is_bot_admin(message.from_user.id):
        return
    await _run_supervisor(message, supervisor.start(), "Запускаю бота")


@router.message(lambda m: m.text and m.text.startswith("/bot_stop"))
async def cmd_bot_stop(message: Message, state: FSMContext):
    await state.clear()
    if message.from_user is None:
        return
    if not _is_bot_admin(message.from_user.id):
        return
    await _run_supervisor(message, supervisor.stop(), "Останавливаю бота")


@router.message(lambda m: m.text and m.text.startswith("/bot_restart"))
async def cmd_bot_restart(message: Message, state: FSMContext):
    await state.clear()
    if message.from_user is None:
        return
    if not _is_bot_admin(message.from_user.id):
        return
    await _run_supervisor(message, supervisor.restart(), "Перезапускаю бота")


@router.message(lambda m: m.text and m.text.startswith("/bot_logs"))
async def cmd_bot_logs(message: Message, state: FSMContext):
    await state.clear()
    if message.from_user is None:
        return
    if not _is_bot_admin(message.from_user.id):
        return
    text = await _typing_until(
        message.from_user.id, supervisor.tail_logs(lines=30)
    )
    # If the log is wrapped in <pre>, use HTML parse mode; otherwise plain text.
    parse_mode = "HTML" if text.startswith("<pre>") else None
    await message.answer(text, reply_markup=command_keyboard, parse_mode=parse_mode)


@router.message(lambda m: m.text and m.text.startswith("/bot_help"))
async def cmd_bot_help(message: Message, state: FSMContext):
    await state.clear()
    if message.from_user is None:
        return
    if not _is_bot_admin(message.from_user.id):
        return
    await message.answer(
        "🛠 *Управление ботом*\n\n"
        "/bot_status — статус\n"
        "/bot_start — запустить\n"
        "/bot_stop — остановить\n"
        "/bot_restart — перезапустить\n"
        "/bot_logs — последние строки лога",
        reply_markup=command_keyboard,
        parse_mode="Markdown",
    )
