"""
Ollama API client.

Supports:
- Local Ollama (http://localhost:11434)
- Ollama Cloud (https://api.ollama.com or custom host)
- OpenAI-compatible endpoints as fallback (/v1/chat/completions, /v1/models)
"""

import time
from json import loads
from logging import getLogger
from typing import Any, AsyncGenerator, Optional

import aiohttp

from bot.services.ollama_semaphore import ollama_semaphore
from bot.settings import OLLAMA_API_HOST, OLLAMA_API_KEY, OLLAMA_KEEP_ALIVE

from .dto import (
    OllamaChatMessage,
    OllamaCompletionFinalChunk,
    OllamaCompletionResponseChunk,
    OllamaErrorChunk,
    OllamaModelTag,
)

logger = getLogger("ollama.api")

# Async-safe TTL cache for models
_models_cache: list[OllamaModelTag] | None = None
_models_cache_time: float = 0
CACHE_TTL_SECONDS: float = 300


def _headers() -> dict[str, str]:
    headers = {"Content-Type": "application/json"}
    if OLLAMA_API_KEY:
        headers["Authorization"] = f"Bearer {OLLAMA_API_KEY}"
    return headers


def _session() -> aiohttp.ClientSession:
    return aiohttp.ClientSession(headers=_headers())


def _normalize_host(host: str) -> str:
    host = host.rstrip("/")
    # If host looks like bare ollama.com without api path, prefer api.ollama.com
    if host == "https://ollama.com":
        return "https://api.ollama.com"
    return host


def _reset_models_cache() -> None:
    global _models_cache, _models_cache_time
    _models_cache = None
    _models_cache_time = 0


async def _try_get_ollama_models(session: aiohttp.ClientSession) -> list[OllamaModelTag] | None:
    host = _normalize_host(OLLAMA_API_HOST)
    try:
        async with session.get(f"{host}/api/tags", timeout=aiohttp.ClientTimeout(total=20)) as resp:
            if resp.status == 200:
                data = await resp.json()
                return [OllamaModelTag.model_validate(tag) for tag in data.get("models", [])]
    except Exception as e:
        logger.debug(f"/api/tags failed: {e}")
    return None


async def _try_get_openai_models(session: aiohttp.ClientSession) -> list[OllamaModelTag] | None:
    host = _normalize_host(OLLAMA_API_HOST)
    try:
        async with session.get(f"{host}/v1/models", timeout=aiohttp.ClientTimeout(total=20)) as resp:
            if resp.status == 200:
                data = await resp.json()
                models = data.get("data", [])
                result = []
                for m in models:
                    name = m.get("id") or m.get("name")
                    if not name:
                        continue
                    result.append(
                        OllamaModelTag(
                            name=name,
                            modified_at=m.get("created_at", ""),
                            size=0,
                            digest="",
                            details={
                                "format": "",
                                "family": m.get("owned_by", ""),
                                "parameter_size": "",
                                "quantization_level": "",
                            },
                        )
                    )
                return result
    except Exception as e:
        logger.debug(f"/v1/models failed: {e}")
    return None


async def get_installed_models(*, cache_ttl: float | None = None) -> list[OllamaModelTag]:
    global _models_cache, _models_cache_time
    ttl = cache_ttl if cache_ttl is not None else CACHE_TTL_SECONDS
    now = time.time()
    if _models_cache is not None and (now - _models_cache_time) < ttl:
        return _models_cache

    async with _session() as session:
        models = await _try_get_ollama_models(session)
        if models is None:
            models = await _try_get_openai_models(session)
        if models is None:
            models = []

    _models_cache = models
    _models_cache_time = now
    return _models_cache


async def model_is_installed(model_id: str) -> bool:
    if not model_id:
        return False
    models = await get_installed_models()
    for model in models:
        if model.name in (model_id, f"{model_id}:latest"):
            return True
    return False


async def ollama_is_healthy() -> bool:
    try:
        await get_installed_models(cache_ttl=0)
        return True
    except Exception as e:
        logger.warning(f"Ollama health check failed: {e}")
        return False


def _build_ollama_chat_payload(
    messages: list[OllamaChatMessage],
    model: str,
    options: dict[str, Any],
) -> dict[str, Any]:
    return {
        "model": model,
        "messages": [message.model_dump() for message in messages],
        "stream": True,
        "options": options,
        "keep_alive": OLLAMA_KEEP_ALIVE,
    }


def _build_openai_chat_payload(
    messages: list[OllamaChatMessage],
    model: str,
    options: dict[str, Any],
) -> dict[str, Any]:
    # Map Ollama options to OpenAI-compatible fields
    temperature = options.get("temperature", 1)
    return {
        "model": model,
        "messages": [message.model_dump() for message in messages],
        "stream": True,
        "temperature": temperature,
    }


def _openai_chunk_to_ollama(chunk: dict[str, Any], model: str) -> dict[str, Any]:
    """Convert OpenAI streaming chunk to Ollama-like segment."""
    choice = chunk.get("choices", [{}])[0]
    delta = choice.get("delta", {})
    content = delta.get("content") or ""
    finish_reason = choice.get("finish_reason")
    return {
        "model": model,
        "created_at": chunk.get("created", ""),
        "message": {"role": "assistant", "content": content},
        "done": finish_reason is not None,
    }


async def _stream_ollama_chat(
    session: aiohttp.ClientSession,
    messages: list[OllamaChatMessage],
    model: str,
    options: dict[str, Any],
) -> AsyncGenerator[dict[str, Any], Any]:
    host = _normalize_host(OLLAMA_API_HOST)
    payload = _build_ollama_chat_payload(messages, model, options)
    async with session.post(
        f"{host}/api/chat",
        json=payload,
        timeout=aiohttp.ClientTimeout(total=600),
    ) as response:
        if response.status >= 400:
            text = await response.text()
            raise aiohttp.ClientResponseError(
                request_info=response.request_info,
                history=response.history,
                status=response.status,
                message=text[:200],
            )
        async for segment in response.content:
            if not segment:
                continue
            raw = segment.decode("utf-8").strip()
            if raw:
                yield loads(raw)


async def _stream_openai_chat(
    session: aiohttp.ClientSession,
    messages: list[OllamaChatMessage],
    model: str,
    options: dict[str, Any],
) -> AsyncGenerator[dict[str, Any], Any]:
    host = _normalize_host(OLLAMA_API_HOST)
    payload = _build_openai_chat_payload(messages, model, options)
    async with session.post(
        f"{host}/v1/chat/completions",
        json=payload,
        timeout=aiohttp.ClientTimeout(total=600),
    ) as response:
        if response.status >= 400:
            text = await response.text()
            raise aiohttp.ClientResponseError(
                request_info=response.request_info,
                history=response.history,
                status=response.status,
                message=text[:200],
            )
        async for segment in response.content:
            if not segment:
                continue
            raw = segment.decode("utf-8").strip()
            if raw.startswith("data: "):
                raw = raw[6:]
            if raw == "[DONE]":
                continue
            if raw:
                chunk = loads(raw)
                yield _openai_chunk_to_ollama(chunk, model)


async def generate_raw_chat_completion(
    messages: list[OllamaChatMessage],
    model: str,
    **ollama_options: Any,
) -> AsyncGenerator[dict[str, Any], Any]:
    options = dict(ollama_options)
    async with ollama_semaphore:
        async with _session() as session:
            try:
                async for segment in _stream_ollama_chat(session, messages, model, options):
                    yield segment
                return
            except Exception as e:
                logger.warning(f"Ollama /api/chat failed, trying OpenAI-compatible: {e}")

            async for segment in _stream_openai_chat(session, messages, model, options):
                yield segment


async def generate_chat_completion(
    messages: list[OllamaChatMessage],
    model: str,
    **ollama_options: Any,
) -> AsyncGenerator[tuple[bool, OllamaCompletionResponseChunk | OllamaErrorChunk], Any]:
    try:
        async for raw_segment in generate_raw_chat_completion(messages, model, **ollama_options):
            if "error" in raw_segment:
                yield False, OllamaErrorChunk(error=raw_segment["error"])
                return

            segment_dto: type[OllamaCompletionResponseChunk] = OllamaCompletionResponseChunk
            if raw_segment.get("done", False):
                segment_dto = OllamaCompletionFinalChunk

            try:
                yield raw_segment.get("done", False), segment_dto.model_validate(raw_segment)
            except Exception as e:
                logger.error(f"Failed to validate segment: {raw_segment}. Error: {e}")
                yield False, OllamaErrorChunk(error=f"Invalid response segment: {e}")
                return
    except Exception as e:
        logger.error(f"Generation failed: {e}")
        yield False, OllamaErrorChunk(error=str(e))


async def validate_installation_with_configuration(
    required_model_id: Optional[str] = None,
) -> None:
    try:
        healthy = await ollama_is_healthy()
    except Exception as e:
        print(f"[WARNING] Ollama health check failed: {e}")
        healthy = False

    if not healthy:
        print(
            "[WARNING] Could not reach Ollama model list endpoint. "
            "Will try to chat anyway. Check OLLAMA_API_HOST and OLLAMA_API_KEY."
        )

    if required_model_id is None:
        return

    try:
        installed = await model_is_installed(required_model_id)
    except Exception as e:
        print(f"[WARNING] Could not verify model {required_model_id}: {e}")
        return

    if not installed:
        print(f"[WARNING] Model {required_model_id} not found in available models.")
        print("[WARNING] The bot will still try to use it; if chat fails, check the model name.")
