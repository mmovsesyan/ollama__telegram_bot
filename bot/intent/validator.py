import typing

from bot.intent.schemas import ALLOWED_TOOLS, IntentResult, ToolContext
from bot.intent.tools.base import BaseTool
from bot.intent.tools.registry import ToolRegistry


class ValidationError(Exception):
    """Raised when an intent result fails validation."""


class _DefaultTool(BaseTool):
    """Stub tool used by the default registry to expose required_args."""

    def __init__(self, name: str, required_args: tuple[str, ...]):
        self.name = name
        self.required_args = required_args

    async def execute(self, context: ToolContext) -> typing.Any:
        raise NotImplementedError


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

    _default_registry: ToolRegistry | None = None

    @classmethod
    def _get_default_registry(cls) -> ToolRegistry:
        if cls._default_registry is None:
            registry = ToolRegistry()
            for tool_name, required in cls._required_args.items():
                if registry.get(tool_name) is None:
                    registry.register(tool_name, _DefaultTool(tool_name, required))
            cls._default_registry = registry
        return cls._default_registry

    @classmethod
    def validate(
        cls,
        result: IntentResult,
        confidence_threshold: float | None = None,
        registry: ToolRegistry | None = None,
    ) -> None:
        threshold = (
            confidence_threshold
            if confidence_threshold is not None
            else cls.DEFAULT_CONFIDENCE_THRESHOLD
        )
        if result.confidence < threshold:
            raise ValidationError(f"confidence {result.confidence} below threshold {threshold}")
        if result.tool not in typing.get_args(ALLOWED_TOOLS):
            raise ValidationError(f"unknown tool: {result.tool}")
        tool_registry = registry or cls._get_default_registry()
        tool = tool_registry.get(result.tool)
        required = tool.required_args if tool else ()
        args_dict = result.args.model_dump()
        for field in required:
            value = args_dict.get(field)
            if value is None or value == "":
                raise ValidationError(f"tool '{result.tool}' missing required arg '{field}'")
