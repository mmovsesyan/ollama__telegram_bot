import pytest
from bot.intent.schemas import IntentArgs, IntentResult, ToolContext, ToolResult


class TestIntentResult:
    def test_valid_intent_result(self):
        data = {
            "intent": "create_reminder",
            "tool": "remind",
            "args": {"content": "test", "trigger_at": "2026-06-15T07:30:00+00:00"},
            "confidence": 0.92,
            "clarification_needed": False,
        }
        result = IntentResult.model_validate(data)
        assert result.intent == "create_reminder"
        assert result.confidence == 0.92

    def test_invalid_tool_rejected(self):
        data = {
            "intent": "create_reminder",
            "tool": "remind",
            "args": {"content": "test"},
            "confidence": 1.5,
        }
        with pytest.raises(ValueError):
            IntentResult.model_validate(data)

    def test_tool_result(self):
        tr = ToolResult(text="Reminder created", success=True)
        assert tr.text == "Reminder created"
        assert tr.success is True
