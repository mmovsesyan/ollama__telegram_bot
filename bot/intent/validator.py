from bot.intent.schemas import ALLOWED_TOOLS, IntentResult


class ValidationError(Exception):
    """Raised when an intent result fails validation."""


class Validator:
    """Validate LLM intent results before execution."""

    DEFAULT_CONFIDENCE_THRESHOLD = 0.7

    _required_args: dict[str, tuple[str, ...]] = {
        "remind": ("content",),
        "task": ("content",),
        "memory": ("content",),
        "note": ("content",),
        "search": ("query",),
        "weather": ("city",),
        "monitor": ("name", "url"),
    }

    @classmethod
    def validate(cls, result: IntentResult, confidence_threshold: float | None = None) -> None:
        threshold = confidence_threshold or cls.DEFAULT_CONFIDENCE_THRESHOLD
        if result.confidence < threshold:
            raise ValidationError(f"confidence {result.confidence} below threshold {threshold}")
        if result.tool not in ALLOWED_TOOLS.__args__:
            raise ValidationError(f"unknown tool: {result.tool}")
        required = cls._required_args.get(result.tool, ())
        args_dict = result.args.model_dump()
        for field in required:
            if not args_dict.get(field):
                raise ValidationError(f"tool '{result.tool}' missing required arg '{field}'")
