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
        with pytest.raises(ValidationError, match="confidence 0.5 below threshold 0.7"):
            Validator.validate(result)

    def test_missing_required_arg_fails(self):
        result = IntentResult(
            intent="create_reminder",
            tool="remind",
            args=IntentArgs(),
            confidence=0.92,
        )
        with pytest.raises(ValidationError, match="tool 'remind' missing required arg 'content'"):
            Validator.validate(result)

    def test_empty_string_content_fails(self):
        result = IntentResult(
            intent="create_reminder",
            tool="remind",
            args=IntentArgs(content=""),
            confidence=0.92,
        )
        with pytest.raises(ValidationError, match="tool 'remind' missing required arg 'content'"):
            Validator.validate(result)

    def test_unknown_tool_fails(self):
        result = IntentResult.model_construct(
            intent="chat",
            tool="unknown",
            args=IntentArgs(),
            confidence=0.9,
        )
        with pytest.raises(ValidationError, match="unknown tool: unknown"):
            Validator.validate(result)

    @pytest.mark.parametrize(
        "tool, field, valid_args",
        [
            ("remind", "content", {"content": "call broker"}),
            ("task", "content", {"content": "buy milk"}),
            ("memory", "content", {"content": "broker number"}),
            ("note", "content", {"content": "meeting notes"}),
            ("search", "query", {"query": "AAPL news"}),
            ("weather", "city", {"city": "New York"}),
            ("monitor", "name", {"name": "AAPL", "url": "https://example.com"}),
            ("monitor", "url", {"name": "AAPL", "url": "https://example.com"}),
        ],
    )
    def test_required_arg_missing_fails(self, tool, field, valid_args):
        args = valid_args.copy()
        args.pop(field)
        result = IntentResult(
            intent="chat",
            tool=tool,
            args=IntentArgs(**args),
            confidence=0.9,
        )
        with pytest.raises(ValidationError, match=rf"tool '{tool}' missing required arg '{field}'"):
            Validator.validate(result)

    @pytest.mark.parametrize(
        "tool, valid_args",
        [
            ("remind", {"content": "call broker"}),
            ("task", {"content": "buy milk"}),
            ("memory", {"content": "broker number"}),
            ("note", {"content": "meeting notes"}),
            ("search", {"query": "AAPL news"}),
            ("weather", {"city": "New York"}),
            ("monitor", {"name": "AAPL", "url": "https://example.com"}),
        ],
    )
    def test_required_args_valid_passes(self, tool, valid_args):
        result = IntentResult(
            intent="chat",
            tool=tool,
            args=IntentArgs(**valid_args),
            confidence=0.9,
        )
        Validator.validate(result)

    def test_threshold_exact_0_7_passes(self):
        result = IntentResult(
            intent="create_reminder",
            tool="remind",
            args=IntentArgs(content="call broker"),
            confidence=0.7,
        )
        Validator.validate(result, confidence_threshold=0.7)

    def test_threshold_0_69_fails(self):
        result = IntentResult(
            intent="create_reminder",
            tool="remind",
            args=IntentArgs(content="call broker"),
            confidence=0.69,
        )
        with pytest.raises(ValidationError, match="confidence 0.69 below threshold 0.7"):
            Validator.validate(result, confidence_threshold=0.7)

    def test_threshold_0_0_passes(self):
        result = IntentResult(
            intent="create_reminder",
            tool="remind",
            args=IntentArgs(content="call broker"),
            confidence=0.0,
        )
        Validator.validate(result, confidence_threshold=0.0)

    def test_threshold_0_0_without_explicit_threshold_fails(self):
        result = IntentResult(
            intent="create_reminder",
            tool="remind",
            args=IntentArgs(content="call broker"),
            confidence=0.0,
        )
        with pytest.raises(ValidationError, match="confidence 0.0 below threshold 0.7"):
            Validator.validate(result)

    def test_threshold_none_falls_back_to_default(self):
        result_below = IntentResult(
            intent="create_reminder",
            tool="remind",
            args=IntentArgs(content="call broker"),
            confidence=0.69,
        )
        with pytest.raises(ValidationError, match="confidence 0.69 below threshold 0.7"):
            Validator.validate(result_below, confidence_threshold=None)

        result_at = IntentResult(
            intent="create_reminder",
            tool="remind",
            args=IntentArgs(content="call broker"),
            confidence=0.7,
        )
        Validator.validate(result_at, confidence_threshold=None)
