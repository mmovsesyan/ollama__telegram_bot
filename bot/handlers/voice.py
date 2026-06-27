"""Voice/audio message handler.

Routes incoming voice notes through transcription and then into the smart
intent pipeline, so commands, memory, search etc. work via voice too.
"""

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import Message

from bot.handlers.smart import smart_message_handler
from bot.security import is_allowed
from bot.services.voice import transcribe_voice

router = Router()


async def _voice_file_size_mb(voice) -> float:
    return (voice.file_size or 0) / (1024 * 1024)


def _looks_like_command(text: str) -> bool:
    return text.startswith("/")


async def _route_transcribed_text(message: Message, state: FSMContext, text: str) -> None:
    from copy import copy
    voice_msg = copy(message)
    voice_msg.text = text
    await smart_message_handler(voice_msg, state=state)


async def _handle_voice_or_audio(message: Message, state: FSMContext, file_id: str, suffix: str, label: str):
    if message.from_user is None:
        return
    user_id = message.from_user.id
    if not is_allowed(user_id):
        return

    status_msg = await message.answer("🎤 Слушаю и распознаю речь...")
    voice = message.voice if message.voice else message.audio
    text, error = await transcribe_voice(message.bot, voice)
    if text is None:
        await status_msg.edit_text(error)
        return

    if not text:
        await status_msg.edit_text("❌ Не удалось распознать речь. Попробуй ещё раз.")
        return

    await status_msg.edit_text(f"🎤 Распознано: {text}")
    await _route_transcribed_text(message, state, text)


@router.message(F.voice)
async def handle_voice(message: Message, state: FSMContext):
    voice = message.voice
    if voice is None:
        return
    await _handle_voice_or_audio(message, state, voice.file_id, ".ogg", "голосового сообщения")


@router.message(F.audio)
async def handle_audio(message: Message, state: FSMContext):
    audio = message.audio
    if audio is None:
        return
    suffix = ".mp3" if (audio.file_name or "").lower().endswith(".mp3") else ".audio"
    await _handle_voice_or_audio(message, state, audio.file_id, suffix, "аудио")
