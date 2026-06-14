import pytest
from bot.intent.schemas import IntentArgs, IntentResult
from bot.intent.validator import Validator, ValidationError


class TestValidator:
    def test_valid_reminder_passes(self):
        result = IntentResult(
            intent="create_reminder",
            tool="remind",
            args=IntentArgs(content="call broker", trigger_at="2026-06-15T07:30:00+00:00"),
            confidence=0.92,
        )
        Validator.validate(result)

    def test_low_confidence_fails(self):
        result = IntentResult(
            intent="create_reminder",
            tool="remind",
            args=IntentArgs(content="call broker"),
            confidence=0.5,
        )
        with pytest.raises(ValidationError):
            Validator.validate(result)

    def test_missing_required_arg_fails(self):
        result = IntentResult(
            intent="create_reminder",
            tool="remind",
            args=IntentArgs(),
            confidence=0.92,
        )
        with pytest.raises(ValidationError):
            Validator.validate(result)

    def test_unknown_tool_fails(self):
        raw = {
            "intent": "chat",
            "tool": "unknown",
            "args": {},
            "confidence": 0.9,
        }
        with pytest.raises(ValueError):
            IntentResult.model_validate(raw)
