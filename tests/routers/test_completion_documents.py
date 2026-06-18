import sys
import tempfile
from pathlib import Path
from types import ModuleType
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

if "bot.bot" not in sys.modules:
    _fake_bot_module = ModuleType("bot.bot")
    _fake_bot_module.bot = MagicMock()
    sys.modules["bot.bot"] = _fake_bot_module

from bot.db import Database
from bot.routers import completion as completion_module
from bot.services import documents as documents_module


def _message(user_id: int = 42, text: str = "", reply_to=None):
    msg = MagicMock()
    msg.from_user = MagicMock()
    msg.from_user.id = user_id
    msg.text = text
    msg.answer = AsyncMock()
    msg.reply_to_message = reply_to
    return msg


def _document(file_id: str = "doc1", file_name: str = "report.txt", mime_type: str = "text/plain"):
    doc = MagicMock()
    doc.file_id = file_id
    doc.file_name = file_name
    doc.mime_type = mime_type
    return doc


@pytest.fixture
def fresh_db(tmp_path):
    db_path = tmp_path / "test.db"
    db = Database(str(db_path))
    completion_module.db = db
    documents_module.db = db
    yield db
    completion_module.db = None
    documents_module.db = None


@pytest.fixture(autouse=True)
def reset_state():
    completion_module.db = None
    documents_module.db = None
    documents_module._document_message_map.clear()
    yield
    completion_module.db = None
    documents_module.db = None
    documents_module._document_message_map.clear()


@pytest.mark.asyncio
async def test_handle_document_persists_and_summarizes(fresh_db, tmp_path):
    source = tmp_path / "report.txt"
    source.write_text("Company revenue grew by 42 percent in 2025.", encoding="utf-8")

    msg = _message()
    msg.document = _document()
    state = MagicMock()
    state.clear = AsyncMock()

    with patch.object(completion_module.aiogram_bot, "get_file", new=AsyncMock()) as get_file_mock:
        fake_file = MagicMock()
        fake_file.file_path = "report.txt"
        get_file_mock.return_value = fake_file
        with patch.object(completion_module.aiogram_bot, "download_file", new=AsyncMock()) as download_mock:

            def capture_download(_, dest):
                Path(dest).parent.mkdir(parents=True, exist_ok=True)
                Path(dest).write_text(source.read_text(), encoding="utf-8")

            download_mock.side_effect = capture_download
            with patch.object(
                documents_module,
                "summarize_text",
                new=AsyncMock(return_value="Revenue grew 42%."),
            ):
                await completion_module.handle_document(msg, state)

    msg.answer.assert_awaited()
    text = msg.answer.await_args.args[0]
    assert "Сохранил" in text
    assert "Revenue grew 42%" in text

    docs = fresh_db.get_documents(42)
    assert len(docs) == 1
    assert docs[0]["filename"] == "report.txt"


@pytest.mark.asyncio
async def test_answer_document_question_via_reply(fresh_db):
    source = tempfile.mktemp(suffix=".txt")
    with open(source, "w", encoding="utf-8") as f:
        f.write("The capital of France is Paris.")

    with patch.object(
        documents_module,
        "summarize_text",
        new=AsyncMock(return_value="Summary"),
    ):
        doc = await documents_module.save_document(
            user_id=42,
            telegram_file_id="doc_q",
            filename="france.txt",
            mime_type="text/plain",
            source_path=source,
            base_dir="data",
        )

    summary_message_id = 100
    documents_module.map_summary_message(summary_message_id, doc["id"])

    reply_to = MagicMock()
    reply_to.message_id = summary_message_id
    msg = _message(text="What is the capital?", reply_to=reply_to)
    state = MagicMock()

    with patch.object(
        documents_module,
        "answer_question",
        new=AsyncMock(return_value="Paris is the capital of France."),
    ):
        result = await completion_module.answer_document_question(msg, 42, msg.text, summary_message_id)

    assert result is True
    msg.answer.assert_awaited_once()
    assert "Paris" in msg.answer.await_args.args[0]


@pytest.mark.asyncio
async def test_answer_document_question_unknown_reply_returns_false():
    msg = _message(text="What?", reply_to=None)
    result = await completion_module.answer_document_question(msg, 42, msg.text, 999)
    assert result is False
    msg.answer.assert_not_awaited()
