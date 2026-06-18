"""Voice pipeline: download, transcribe with faster-whisper, optional TTS reply.

Design principles:
- Local by default: faster-whisper runs locally. TTS uses Telegram's voice-note
  synthesis (cloud, but audio is not persisted by the bot) only when the user
  explicitly enables it; local piper-tts is the preferred local path when
  installed.
- Failures degrade gracefully: missing model, ffmpeg not found, too-large file —
  all return a clear text message instead of crashing the handler.
- Voice is routed into the same smart pipeline as text after transcription so
  commands, memory, search, etc. work identically.
"""

import asyncio
import logging
import os
import tempfile
from pathlib import Path
from typing import Any

from aiogram.types import FSInputFile, Message, Voice

from bot.settings import WHISPER_MODEL, WHISPER_DEVICE, WHISPER_COMPUTE_TYPE

logger = logging.getLogger(__name__)

db: Any = None  # injected in bot.__init__

MAX_VOICE_MB = 20
MAX_VOICE_BYTES = MAX_VOICE_MB * 1024 * 1024

_TTS_ENABLED = False

try:
    from faster_whisper import WhisperModel

    _WHISPER_AVAILABLE = True
except Exception as exc:  # pragma: no cover - environment dependent
    WhisperModel = None  # type: ignore[misc,assignment]
    _WHISPER_AVAILABLE = False
    logger.debug("faster-whisper not available: %s", exc)

_whisper_model_instance: Any | None = None


def _get_whisper_model() -> Any:
    global _whisper_model_instance
    if _whisper_model_instance is not None:
        return _whisper_model_instance
    if not _WHISPER_AVAILABLE or WhisperModel is None:
        raise RuntimeError("faster-whisper не установлен.")
    _whisper_model_instance = WhisperModel(
        WHISPER_MODEL,
        device=WHISPER_DEVICE,
        compute_type=WHISPER_COMPUTE_TYPE,
    )
    return _whisper_model_instance


def _voice_file_size_mb(voice: Voice) -> float:
    return (voice.file_size or 0) / (1024 * 1024)


async def _download_tg_file(bot, file_id: str, suffix: str) -> tuple[str, str]:
    tg_file = await bot.get_file(file_id)
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        tmp_path = tmp.name
    await bot.download_file(tg_file.file_path, tmp_path)
    return tmp_path, tg_file.file_path or ""


def _transcribe_audio(file_path: str) -> str:
    model = _get_whisper_model()
    segments, _info = model.transcribe(file_path, beam_size=5, vad_filter=True)
    return " ".join(segment.text for segment in segments).strip()


async def transcribe_voice(
    bot,
    voice: Voice,
) -> tuple[str | None, str | None]:
    """Return (transcription, error_message). error is None on success."""
    if not _WHISPER_AVAILABLE:
        return None, (
            "🎤 Распознавание голоса недоступно. "
            "Установи faster-whisper: poetry install"
        )

    if (voice.file_size or 0) > MAX_VOICE_BYTES:
        return None, f"🎤 Голосовое сообщение больше {MAX_VOICE_MB} МБ. Telegram не позволяет скачать его."

    tmp_path = None
    try:
        tmp_path, _ = await _download_tg_file(bot, voice.file_id, ".ogg")
        text = await asyncio.to_thread(_transcribe_audio, tmp_path)
        return text, None
    except Exception as e:
        err = str(e)
        if "ffmpeg" in err.lower() or "command not found" in err.lower():
            return None, (
                "❌ Для распознавания голоса нужен ffmpeg.\n"
                "macOS: brew install ffmpeg\n"
                "Linux: sudo apt install ffmpeg"
            )
        logger.warning("[VOICE] Transcription failed: %s", e)
        return None, f"❌ Ошибка распознавания голоса: {err[:200]}"
    finally:
        if tmp_path and os.path.exists(tmp_path):
            try:
                os.unlink(tmp_path)
            except Exception:
                pass


async def _run_tts_local(text: str) -> str | None:
    """Run local piper-tts if installed. Return path to WAV file or None."""
    try:
        import subprocess  # noqa: S404
    except Exception:
        return None

    model_name = os.getenv("PIPER_MODEL")
    if not model_name:
        return None

    model_path = Path(os.getenv("PIPER_MODEL_DIR", "data/piper")) / model_name
    if not model_path.exists():
        logger.debug("[TTS] piper model not found at %s", model_path)
        return None

    with tempfile.NamedTemporaryFile(delete=False, suffix=".wav") as out:
        out_path = out.name

    try:
        proc = await asyncio.create_subprocess_exec(
            "piper-tts",
            "--model", str(model_path),
            "--output_file", out_path,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        await proc.communicate(text.encode("utf-8"))
        if proc.returncode != 0 or not os.path.exists(out_path) or os.path.getsize(out_path) == 0:
            return None
        return out_path
    except Exception as e:
        logger.warning("[TTS] piper failed: %s", e)
        if os.path.exists(out_path):
            os.unlink(out_path)
        return None


async def send_voice_reply(message: Message, text: str, bot) -> None:
    """Send text as a voice note if the user enabled voice output and we can
    synthesize it locally; otherwise send plain text."""
    if not message.from_user:
        return
    user_id = message.from_user.id

    if db is not None:
        prefs = db.get_user_prefs(user_id) or {}
    else:
        prefs = {}

    if not prefs.get("voice_output_enabled"):
        await message.answer(text)
        return

    tts_path = await _run_tts_local(text)
    if tts_path:
        try:
            voice_file = FSInputFile(tts_path)
            await message.answer_voice(voice=voice_file, caption=text[:1024])
        except Exception as e:
            logger.warning("[TTS] send_voice failed: %s", e)
            await message.answer(text)
        finally:
            if os.path.exists(tts_path):
                os.unlink(tts_path)
        return

    # Fallback: text-only with explanation if local TTS isn't configured.
    await message.answer(text + "\n\n_Голосовой ответ доступен только с локальным piper-tts._")


def voice_output_enabled(user_id: int) -> bool:
    if db is None:
        return False
    prefs = db.get_user_prefs(user_id) or {}
    return bool(prefs.get("voice_output_enabled", 0))
