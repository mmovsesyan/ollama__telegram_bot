import os
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from bot.services import documents as documents_module
from bot.db import Database


def _write_file(path: str, content: str):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)


class _FakeDb:
    def __init__(self):
        self._docs = {}
        self._chunks = []
        self._next_id = 1

    def add_document(self, user_id, telegram_file_id, local_path, filename, mime_type, extracted_text, summary):
        doc_id = self._next_id
        self._next_id += 1
        self._docs[doc_id] = {
            "id": doc_id,
            "user_id": user_id,
            "telegram_file_id": telegram_file_id,
            "local_path": local_path,
            "filename": filename,
            "mime_type": mime_type,
            "extracted_text": extracted_text,
            "summary": summary,
        }
        return doc_id

    def get_document(self, doc_id):
        return self._docs.get(doc_id)

    def get_documents(self, user_id):
        return [d for d in self._docs.values() if d["user_id"] == user_id]

    def get_document(self, doc_id):
        return self._docs.get(doc_id)

    def delete_document(self, doc_id):
        self._chunks = [c for c in self._chunks if c.get("document_id") != doc_id]
        return self._docs.pop(doc_id, None) is not None

    def add_document_chunks(self, doc_id, user_id, chunks):
        for chunk in chunks:
            self._chunks.append({"document_id": doc_id, "user_id": user_id, "chunk": chunk})

    def search_document_chunks(self, user_id, query, limit=5):
        # Simple substring match for testing.
        results = []
        for c in self._chunks:
            if c["user_id"] == user_id and query.lower() in c["chunk"].lower():
                results.append({"document_id": c["document_id"], "chunk": c["chunk"]})
        return results[:limit]


@pytest.fixture(autouse=True)
def reset_documents_module():
    documents_module.db = None
    documents_module._document_message_map.clear()
    yield
    documents_module.db = None
    documents_module._document_message_map.clear()


def test_detect_suffix_from_filename():
    assert documents_module._detect_suffix("report.pdf", None) == ".pdf"
    assert documents_module._detect_suffix("notes.txt", "text/plain") == ".txt"
    assert documents_module._detect_suffix(None, "application/pdf") == ".pdf"
    assert documents_module._detect_suffix("weird", None) == ".bin"


def test_extract_text_from_txt(tmp_path):
    path = tmp_path / "doc.txt"
    path.write_text("Hello world", encoding="utf-8")
    assert documents_module._extract_text_from_file(str(path), ".txt") == "Hello world"


def test_chunk_text_with_overlap():
    text = "\n\n".join([f"Paragraph {i}" for i in range(20)])
    chunks = documents_module._chunk_text(text, chunk_size=100, overlap=20)
    assert len(chunks) > 1
    assert all(len(c) <= 120 for c in chunks)


def test_chunk_text_short_returns_single():
    assert documents_module._chunk_text("short", chunk_size=1000) == ["short"]


@pytest.mark.asyncio
async def test_summarize_text_uses_llm(tmp_path):
    documents_module.db = _FakeDb()
    text = "This is a long document about artificial intelligence and machine learning."
    with patch.object(
        documents_module,
        "_ollama_simple_prompt",
        new=AsyncMock(return_value="AI overview"),
    ):
        summary = await documents_module.summarize_text(text)
    assert summary == "AI overview"


@pytest.mark.asyncio
async def test_summarize_text_fallback_when_llm_fails():
    with patch.object(
        documents_module,
        "_ollama_simple_prompt",
        new=AsyncMock(return_value=""),
    ):
        summary = await documents_module.summarize_text("Line one.\nLine two.\nLine three.")
    assert "Line one" in summary


@pytest.mark.asyncio
async def test_save_document_creates_file_and_indexes(tmp_path):
    documents_module.db = _FakeDb()
    source = tmp_path / "source.txt"
    source.write_text("Alpha beta gamma delta epsilon zeta", encoding="utf-8")

    with patch.object(
        documents_module,
        "summarize_text",
        new=AsyncMock(return_value="Summary text"),
    ):
        doc = await documents_module.save_document(
            user_id=1,
            telegram_file_id="file_1",
            filename="source.txt",
            mime_type="text/plain",
            source_path=str(source),
            base_dir=str(tmp_path / "docs"),
        )

    assert doc["filename"] == "source.txt"
    assert doc["summary"] == "Summary text"
    assert Path(doc["local_path"]).exists()
    assert doc["chunk_count"] > 0


@pytest.mark.asyncio
async def test_save_document_avoids_overwrite(tmp_path):
    documents_module.db = _FakeDb()
    base = tmp_path / "docs"
    existing = base / "1" / "docs" / "file_1_source.txt"
    _write_file(str(existing), "existing")

    source = tmp_path / "source.txt"
    source.write_text("new content", encoding="utf-8")

    with patch.object(
        documents_module,
        "summarize_text",
        new=AsyncMock(return_value="Summary"),
    ):
        doc = await documents_module.save_document(
            user_id=1,
            telegram_file_id="file_1",
            filename="source.txt",
            mime_type="text/plain",
            source_path=str(source),
            base_dir=str(base),
        )

    assert doc["local_path"] != str(existing)
    assert Path(doc["local_path"]).exists()


def test_map_summary_message_and_lookup():
    documents_module.map_summary_message(123, 456)
    assert documents_module.doc_id_for_message(123) == 456
    assert documents_module.doc_id_for_message(999) is None


@pytest.mark.asyncio
async def test_answer_question_with_doc_id():
    documents_module.db = _FakeDb()
    source_path = tempfile.mktemp(suffix=".txt")
    with open(source_path, "w", encoding="utf-8") as f:
        f.write("The capital of France is Paris.")
    with patch.object(
        documents_module,
        "summarize_text",
        new=AsyncMock(return_value="Summary"),
    ):
        doc = await documents_module.save_document(
            user_id=1,
            telegram_file_id="file_q",
            filename="q.txt",
            mime_type="text/plain",
            source_path=source_path,
            base_dir="data",
        )

    with patch.object(
        documents_module,
        "_ollama_simple_prompt",
        new=AsyncMock(return_value="Paris is the capital of France."),
    ) as mock_prompt:
        answer = await documents_module.answer_question(1, "France", doc["id"])

    assert "Paris" in answer
    # Ensure the prompt included the chunk context.
    prompt = mock_prompt.await_args.args[1]
    assert "France" in prompt
    os.unlink(source_path)


@pytest.mark.asyncio
async def test_answer_question_no_results():
    documents_module.db = _FakeDb()
    answer = await documents_module.answer_question(1, "unknown query")
    assert "ничего не нашёл" in answer


def test_delete_document_removes_file(tmp_path):
    documents_module.db = _FakeDb()
    path = tmp_path / "todelete.txt"
    path.write_text("data", encoding="utf-8")
    doc_id = documents_module.db.add_document(
        user_id=1,
        telegram_file_id=None,
        local_path=str(path),
        filename="todelete.txt",
        mime_type="text/plain",
        extracted_text="data",
        summary="summary",
    )
    assert documents_module.delete_document(doc_id)
    assert not path.exists()


def test_delete_document_unknown_returns_false():
    documents_module.db = _FakeDb()
    assert not documents_module.delete_document(999)


@pytest.mark.asyncio
async def test_integration_with_real_db(tmp_path):
    db_path = tmp_path / "test.db"
    real_db = Database(str(db_path))
    documents_module.db = real_db

    source = tmp_path / "report.txt"
    source.write_text(
        "Company revenue grew by 42 percent in 2025. " * 50,
        encoding="utf-8",
    )

    with patch.object(
        documents_module,
        "summarize_text",
        new=AsyncMock(return_value="Revenue grew."),
    ):
        doc = await documents_module.save_document(
            user_id=42,
            telegram_file_id="f42",
            filename="report.txt",
            mime_type="text/plain",
            source_path=str(source),
            base_dir=str(tmp_path / "data"),
        )

    docs = documents_module.get_user_documents(42)
    assert len(docs) == 1
    assert docs[0]["filename"] == "report.txt"

    results = real_db.search_document_chunks(42, "revenue grew")
    assert len(results) > 0
    assert any("revenue" in r["chunk"].lower() for r in results)
