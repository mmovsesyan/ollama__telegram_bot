from pydantic import BaseModel


class OllamaChatMessage(BaseModel):
    role: str
    content: str
    images: list[str] | None = None


class OllamaChat(BaseModel):
    messages: list[OllamaChatMessage]


class OllamaCompletionResponseChunk(BaseModel):
    done: bool
    created_at: str
    model: str
    message: OllamaChatMessage


class OllamaErrorChunk(BaseModel):
    error: str


class OllamaCompletionFinalChunk(OllamaCompletionResponseChunk):
    context: list[str] | None = None
    total_duration: int | None = None
    prompt_eval_duration: int | None = None
    eval_count: int | None = None
    eval_duration: int | None = None
    prompt_eval_count: int | None = None


class OllamaModelTagDetails(BaseModel):
    format: str
    family: str
    families: None | list[str] = None
    parameter_size: str
    quantization_level: str


class OllamaModelTag(BaseModel):
    name: str
    modified_at: str
    size: int
    digest: str
    details: OllamaModelTagDetails
