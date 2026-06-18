"""Image handling: download, vision description, OCR, persistence.

Photos sent by the user are stored under ``data/<user_id>/images/``. A local
Ollama vision model produces a description and extracts any visible text. The
user can then save the description to long-term memory.
"""

import asyncio
import base64
import logging
import os
import shutil
from pathlib import Path
from typing import Any

from bot.ollama import OllamaChatMessage, generate_chat_completion
from bot.ollama.dto import OllamaErrorChunk
from bot.settings import IMAGES_DIR, OLLAMA_MODEL, VISION_MODEL

logger = logging.getLogger(__name__)

db: Any = None  # injected at startup by bot.__init__


def _user_images_dir(base_dir: str | Path, user_id: int) -> Path:
    path = Path(base_dir) / str(user_id) / "images"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _largest_photo(photo_sizes: list[Any]) -> Any | None:
    """Return the largest photo from a Telegram PhotoSize list."""
    if not photo_sizes:
        return None
    return max(photo_sizes, key=lambda p: (p.width or 0) * (p.height or 0))


def _encode_image(path: str) -> str:
    """Encode an image file as base64 for the Ollama vision API."""
    with open(path, "rb") as f:
        return base64.b64encode(f.read()).decode("utf-8")


async def _vision_query(image_path: str, prompt: str, model: str | None = None) -> str:
    """Run a single vision prompt against a local Ollama multimodal model."""
    model = model or VISION_MODEL or OLLAMA_MODEL
    b64 = _encode_image(image_path)
    messages = [
        OllamaChatMessage(role="user", content=prompt, images=[b64]),
    ]
    output = ""
    try:
        async with asyncio.timeout(120):
            async for is_done, chunk in generate_chat_completion(messages, model, temperature=0.3):
                if is_done:
                    break
                if isinstance(chunk, OllamaErrorChunk):
                    logger.warning("[IMAGES] LLM error: %s", chunk.error)
                    return ""
                output += chunk.message.content
    except asyncio.TimeoutError:
        logger.info("[IMAGES] vision query timed out")
    except Exception as e:
        logger.warning("[IMAGES] vision query failed: %s", e)
    return output.strip()


async def describe_image(image_path: str, model: str | None = None) -> str:
    """Return a concise Russian description of the image contents."""
    prompt = (
        "Опиши, что изображено на фото, кратко и по существу на русском языке. "
        "Если на изображении есть текст, перечисли его отдельно."
    )
    return await _vision_query(image_path, prompt, model=model)


async def ocr_image(image_path: str, model: str | None = None) -> str:
    """Return any visible text on the image, or empty string if none."""
    prompt = (
        "Прочитай и перепиши весь текст, который видишь на изображении, "
        "сохраняя строки. Если текста нет — ответь 'нет текста'."
    )
    result = await _vision_query(image_path, prompt, model=model)
    if "нет текста" in result.lower():
        return ""
    return result


def _unique_local_path(directory: Path, filename: str) -> Path:
    path = directory / filename
    counter = 1
    original = path
    while path.exists():
        stem = original.stem
        suffix = original.suffix
        path = directory / f"{stem}_{counter}{suffix}"
        counter += 1
    return path


async def process_image(
    user_id: int,
    telegram_file_id: str | None,
    source_path: str,
    caption: str | None,
    filename: str | None,
    base_dir: str | Path,
    model: str | None = None,
) -> dict:
    """Persist an image, run vision description + OCR, and store the result."""
    if db is None:
        raise RuntimeError("Database not available")

    safe_name = Path(filename or "image.jpg").name
    images_dir = _user_images_dir(base_dir, user_id)
    local_path = str(_unique_local_path(images_dir, safe_name))
    shutil.copy2(source_path, local_path)

    description = await describe_image(local_path, model=model)
    ocr_text = await ocr_image(local_path, model=model)

    image_id = db.add_image(
        user_id=user_id,
        telegram_file_id=telegram_file_id,
        local_path=local_path,
        caption=caption,
        description=description,
        ocr_text=ocr_text or None,
    )
    return {
        "id": image_id,
        "user_id": user_id,
        "local_path": local_path,
        "filename": safe_name,
        "caption": caption,
        "description": description,
        "ocr_text": ocr_text,
    }


def get_user_images(user_id: int) -> list[dict]:
    if db is None:
        return []
    return db.get_images(user_id)


def get_image(image_id: int) -> dict | None:
    if db is None:
        return None
    return db.get_image(image_id)


def delete_image(image_id: int) -> bool:
    if db is None:
        return False
    image = db.get_image(image_id)
    if not image:
        return False
    if image.get("local_path") and Path(image["local_path"]).exists():
        try:
            os.unlink(image["local_path"])
        except Exception as e:
            logger.warning("[IMAGES] failed to remove file %s: %s", image["local_path"], e)
    return db.delete_image(image_id)


async def save_description_to_memory(user_id: int, image_id: int) -> str:
    """Save an image's description as a memory fact for the user."""
    if db is None:
        return "⚠️ База данных недоступна."
    image = db.get_image(image_id)
    if not image or image.get("user_id") != user_id:
        return "⚠️ Изображение не найдено или нет доступа."
    description = image.get("description") or ""
    if not description:
        return "⚠️ Описание отсутствует."
    db.add_memory(user_id, "fact", description, source="image")
    try:
        from bot.routers import completion
        completion.refresh_system_prompt(user_id)
    except Exception:
        pass
    return "✅ Сохранил описание фото в память."
