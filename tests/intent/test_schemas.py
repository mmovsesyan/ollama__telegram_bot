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

    def test_invalid_confidence_rejected(self):
        data = {
            "intent": "create_reminder",
            "tool": "remind",
            "args": {"content": "test"},
            "confidence": 1.5,
        }
        with pytest.raises(ValueError):
            IntentResult.model_validate(data)

    def test_invalid_intent_rejected(self):
        data = {
            "intent": "not_allowed",
            "tool": "chat",
            "confidence": 0.8,
        }
        with pytest.raises(ValueError):
            IntentResult.model_validate(data)

    def test_invalid_tool_rejected(self):
        data = {
            "intent": "chat",
            "tool": "not_allowed",
            "confidence": 0.8,
        }
        with pytest.raises(ValueError):
            IntentResult.model_validate(data)

    def test_tool_result(self):
        tr = ToolResult(text="Reminder created", success=True)
        assert tr.text == "Reminder created"
        assert tr.success is True


class TestIntentArgs:
    def test_default_intent_args(self):
        args = IntentArgs()
        assert args.content is None
        assert args.trigger_at is None
        assert args.recurring is None
        assert args.query is None
        assert args.city is None
        assert args.url is None
        assert args.name is None
        assert args.interval is None
        assert args.plan_text is None


class TestToolContext:
    def test_tool_context_creation(self):
        intent_result = IntentResult(
            intent="chat", tool="chat", confidence=0.9
        )
        args = IntentArgs(content="hello")
        ctx = ToolContext(
            user_id=123,
            message_text="hello",
            args=args,
            intent_result=intent_result,
        )
        assert ctx.user_id == 123
        assert ctx.message_text == "hello"
        assert ctx.args.content == "hello"
        assert ctx.intent_result.intent == "chat"
        assert ctx.intent_result.tool == "chat"
