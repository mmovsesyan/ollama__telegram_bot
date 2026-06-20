import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from bot.services import voice as voice_module


@pytest.fixture(autouse=True)
def reset_voice_module(monkeypatch):
    voice_module._whisper_model_instance = None
    voice_module.db = None
    yield
    voice_module._whisper_model_instance = None
    voice_module.db = None


@pytest.fixture
def fake_voice():
    v = MagicMock()
    v.file_id = "voice_file_123"
    v.file_size = 1024 * 1024  # 1 MB
    return v


@pytest.mark.asyncio
async def test_transcribe_voice_missing_whisper(fake_voice):
    with patch.object(voice_module, "_WHISPER_AVAILABLE", False):
        text, error = await voice_module.transcribe_voice(MagicMock(), fake_voice)
    assert text is None
    assert "faster-whisper" in error


@pytest.mark.asyncio
async def test_transcribe_voice_file_too_large(fake_voice):
    fake_voice.file_size = 21 * 1024 * 1024
    with patch.object(voice_module, "_WHISPER_AVAILABLE", True):
        text, error = await voice_module.transcribe_voice(MagicMock(), fake_voice)
    assert text is None
    assert "20" in error


@pytest.mark.asyncio
async def test_transcribe_voice_success(fake_voice, monkeypatch, tmp_path):
    fake_bot = MagicMock()
    fake_bot.get_file = AsyncMock(return_value=MagicMock(file_path="voice/file.ogg"))
    fake_bot.download_file = AsyncMock()

    fake_model = MagicMock()
    fake_segment = MagicMock()
    fake_segment.text = "привет бот"
    fake_model.transcribe.return_value = ([fake_segment], None)
    monkeypatch.setattr(voice_module, "_whisper_model_instance", fake_model)
    monkeypatch.setattr(voice_module, "_WHISPER_AVAILABLE", True)

    local_path = str(tmp_path / "voice.ogg")
    with patch.object(
        voice_module, "_download_tg_file", new=AsyncMock(return_value=(local_path, ""))
    ):
        text, error = await voice_module.transcribe_voice(fake_bot, fake_voice)

    assert error is None
    assert "привет бот" in text


@pytest.mark.asyncio
async def test_transcribe_voice_ffmpeg_error(fake_voice, monkeypatch, tmp_path):
    fake_bot = MagicMock()
    fake_bot.get_file = AsyncMock(return_value=MagicMock(file_path="voice/file.ogg"))
    fake_bot.download_file = AsyncMock()

    fake_model = MagicMock()
    fake_model.transcribe.side_effect = RuntimeError("ffmpeg command not found")
    monkeypatch.setattr(voice_module, "_whisper_model_instance", fake_model)
    monkeypatch.setattr(voice_module, "_WHISPER_AVAILABLE", True)

    local_path = str(tmp_path / "voice.ogg")
    with patch.object(
        voice_module, "_download_tg_file", new=AsyncMock(return_value=(local_path, ""))
    ):
        text, error = await voice_module.transcribe_voice(fake_bot, fake_voice)

    assert text is None
    assert "ffmpeg" in error


def test_voice_file_size_mb():
    v = MagicMock()
    v.file_size = 2 * 1024 * 1024
    assert voice_module._voice_file_size_mb(v) == 2.0


@pytest.mark.asyncio
async def test_send_voice_reply_disabled():
    voice_module.db = MagicMock()
    voice_module.db.get_user_prefs.return_value = {"voice_output_enabled": 0}
    msg = MagicMock()
    msg.from_user = MagicMock(id=42)
    msg.answer = AsyncMock()
    await voice_module.send_voice_reply(msg, "текст", MagicMock())
    msg.answer.assert_awaited_once_with("текст")


@pytest.mark.asyncio
async def test_send_voice_reply_enabled_but_no_tts(monkeypatch):
    voice_module.db = MagicMock()
    voice_module.db.get_user_prefs.return_value = {"voice_output_enabled": 1}
    msg = MagicMock()
    msg.from_user = MagicMock(id=42)
    msg.answer = AsyncMock()
    monkeypatch.setenv("PIPER_MODEL", "")
    await voice_module.send_voice_reply(msg, "текст", MagicMock())
    text = msg.answer.await_args.args[0]
    assert "piper-tts" in text


@pytest.mark.asyncio
async def test_send_voice_reply_with_local_tts(monkeypatch, tmp_path):
    voice_module.db = MagicMock()
    voice_module.db.get_user_prefs.return_value = {"voice_output_enabled": 1}

    # Prepare fake piper model
    model_dir = tmp_path / "piper"
    model_dir.mkdir()
    model_path = model_dir / "model.onnx"
    model_path.write_text("fake")
    monkeypatch.setenv("PIPER_MODEL", "model.onnx")
    monkeypatch.setenv("PIPER_MODEL_DIR", str(model_dir))

    async def fake_tts(text):
        out = tmp_path / "out.wav"
        out.write_text("wav")
        return str(out)

    monkeypatch.setattr(voice_module, "_run_tts_local", fake_tts)

    fake_bot = MagicMock()
    msg = MagicMock()
    msg.from_user = MagicMock(id=42)
    msg.answer_voice = AsyncMock()
    msg.answer = AsyncMock()
    await voice_module.send_voice_reply(msg, "текст", fake_bot)
    msg.answer_voice.assert_awaited_once()
