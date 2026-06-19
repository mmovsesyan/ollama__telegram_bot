import tempfile

import pytest

from bot.db import Database
from bot.services import reminder_completion as completion_module


@pytest.fixture(autouse=True)
def reset_completion_module():
    completion_module.db = None
    yield
    completion_module.db = None


@pytest.fixture
def real_db():
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
        db = Database(tmp.name)
        yield db


def test_looks_like_completion():
    assert completion_module.looks_like_completion("готово")
    assert completion_module.looks_like_completion("я сделал отчёт")
    assert completion_module.looks_like_completion("выполнено")
    assert completion_module.looks_like_completion("done with the report")
    assert completion_module.looks_like_completion("закрыл задачу")
    assert not completion_module.looks_like_completion("привет")
    assert not completion_module.looks_like_completion("что нового")


def test_find_matching_reminder_by_overlap(real_db):
    completion_module.db = real_db
    user_id = 42
    real_db.add_reminder(
        user_id=user_id,
        content="отправить отчёт по продажам",
        trigger_at="2025-01-01T10:00:00+00:00",
        action="notify",
    )

    match = completion_module.find_matching_reminder(user_id, "я сделал отчёт по продажам")
    assert match is not None
    assert "отчёт по продажам" in match["content"]


def test_find_matching_reminder_requires_completion_keyword(real_db):
    completion_module.db = real_db
    user_id = 42
    real_db.add_reminder(
        user_id=user_id,
        content="позвонить клиенту",
        trigger_at="2025-01-01T10:00:00+00:00",
        action="notify",
    )

    # Without completion keyword, even if content overlaps, no match.
    assert completion_module.find_matching_reminder(user_id, "расскажи про клиента") is None


def test_find_matching_reminder_wrong_user(real_db):
    completion_module.db = real_db
    real_db.add_reminder(
        user_id=1,
        content="купить молоко",
        trigger_at="2025-01-01T10:00:00+00:00",
        action="notify",
    )
    assert completion_module.find_matching_reminder(2, "я купил молоко") is None


def test_find_matching_reminder_no_active(real_db):
    completion_module.db = real_db
    assert completion_module.find_matching_reminder(1, "я всё сделал") is None


def test_complete_reminder(real_db):
    completion_module.db = real_db
    user_id = 7
    rid = real_db.add_reminder(
        user_id=user_id,
        content="проверить почту",
        trigger_at="2025-01-01T10:00:00+00:00",
        action="notify",
    )

    result = completion_module.complete_reminder(user_id, rid)
    assert "Закрыл" in result
    assert real_db.get_reminder(rid) is None


def test_complete_reminder_wrong_user(real_db):
    completion_module.db = real_db
    rid = real_db.add_reminder(
        user_id=1,
        content="позвонить",
        trigger_at="2025-01-01T10:00:00+00:00",
        action="notify",
    )

    result = completion_module.complete_reminder(2, rid)
    assert "нет доступа" in result


def test_maybe_offer_completion_returns_keyboard(real_db):
    completion_module.db = real_db
    user_id = 5
    real_db.add_reminder(
        user_id=user_id,
        content="написать письмо заказчику",
        trigger_at="2025-01-01T10:00:00+00:00",
        action="notify",
    )

    offer = completion_module.maybe_offer_completion(user_id, "готово, написал письмо заказчику")
    assert offer is not None
    text, keyboard = offer
    assert "закрыть" in text.lower()
    assert any(
        btn.callback_data == f"reminder_done:{real_db.get_user_reminders(user_id)[0]['id']}"
        for row in keyboard.inline_keyboard for btn in row
    )


def test_maybe_offer_completion_no_match(real_db):
    completion_module.db = real_db
    assert completion_module.maybe_offer_completion(1, "привет") is None
