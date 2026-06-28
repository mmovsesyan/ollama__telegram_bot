import asyncio
import html
import ipaddress
import json
import logging
import re
import socket
from datetime import datetime
from typing import AsyncIterator, Awaitable, TypeVar
from urllib.parse import urlparse

import aiohttp
from aiogram.fsm.context import FSMContext
from aiogram.types import Message

from bot.bot import bot as aiogram_bot
from bot.keyboards.reply import command_keyboard
from bot.ollama import OllamaChatMessage, generate_chat_completion
from bot.ollama.dto import OllamaErrorChunk
from bot.services.profile import format_local
from bot.settings import OLLAMA_MODEL, SYSTEM_MESSAGE

# Injected from bot/__init__.py at startup.
db = None

logger = logging.getLogger(__name__)

T = TypeVar("T")

# Known command buttons that should cancel pending FSM input
_COMMAND_BUTTONS = {
    "✨ Умный запрос",
    "⏰ Напомнить",
    "📒 Список",
    "🧠 Память",
    "📚 База",
    "📊 Отчёт",
    "❓ Помощь",
    "⚙️ Настройки",
}

# Button text → handler mapping for instant routing when pressed during FSM
_BUTTON_HANDLERS: dict[str, callable] = {}


def _user_tz(user_id: int) -> str | None:
    """Look up the user's saved timezone for display + parsing."""
    if db is None:
        return None
    try:
        prefs = db.get_user_prefs(user_id)
    except Exception:
        return None
    return (prefs or {}).get("timezone") or None


def _format_trigger(trigger_at, user_id: int) -> str:
    """Render a stored UTC trigger_at as a human-readable string in the
    user's local timezone. Accepts either a datetime object or an ISO string.
    Returns 'ASAP' if the value is missing or unparseable."""
    if trigger_at is None or trigger_at == "":
        return "ASAP"
    if isinstance(trigger_at, str):
        try:
            trigger_at = datetime.fromisoformat(trigger_at)
        except Exception:
            return trigger_at  # pragma: no cover — show raw if mangled
    return format_local(trigger_at, _user_tz(user_id))


async def _fsm_guard(message: Message, state: FSMContext) -> bool:
    """If user sends a cancel/command while in FSM state, cancel state and return True."""
    text = message.text or ""

    if text == "❌ Отмена":
        await state.clear()
        await message.answer("Действие отменено.", reply_markup=command_keyboard)
        return True

    if text in _COMMAND_BUTTONS:
        await state.clear()
        handler = _BUTTON_HANDLERS.get(text)
        if handler:
            await handler(message, state)
        else:
            await message.answer(
                "Текущее действие отменено. Нажми кнопку ещё раз.",
                reply_markup=command_keyboard,
            )
        return True

    if text.startswith("/"):
        await state.clear()
        await message.answer(
            "Текущее действие отменено. Введи команду повторно.",
            reply_markup=command_keyboard,
        )
        return True

    return False


def _parse_interval(text: str) -> int:
    """Parse interval: 5m, 10m, 1h, 2h, or raw seconds. Default 300 (5 min)."""
    text = text.strip().lower()
    if not text:
        return 300
    if text.endswith("m"):
        try:
            return int(text[:-1]) * 60
        except ValueError:
            return 300
    if text.endswith("h"):
        try:
            return int(text[:-1]) * 3600
        except ValueError:
            return 300
    try:
        return int(text)
    except ValueError:
        return 300


def _format_interval(seconds: int) -> str:
    """Format seconds to human readable."""
    if seconds < 60:
        return f"{seconds} сек"
    if seconds < 3600:
        return f"{seconds // 60} мин"
    h = seconds // 3600
    m = (seconds % 3600) // 60
    if m == 0:
        return f"{h} ч"
    return f"{h} ч {m} мин"


def _normalize_url(url: str) -> str:
    """Add http:// if no scheme present."""
    url = url.strip()
    if "://" not in url:
        url = f"http://{url}"
    return url


def _is_safe_monitor_url(url: str) -> tuple[bool, str]:
    """Block obviously internal / unsafe URLs for the site monitor.

    Monitors run on the bot's scheduler and issue outbound HTTP requests.
    We reject non-public schemes, missing hosts, localhost, and private/reserved
    IP literals to prevent SSRF against internal services (Ollama, cloud metadata,
    etc.). Domain names are accepted on trust; a determined attacker can still
    point a public DNS name at an internal IP, so this is a best-effort guard.

    For synchronous call-sites (tests, quick checks) no DNS resolution is
    performed. Use `_is_safe_monitor_url_async()` before issuing a request.
    """
    parsed = urlparse(url)
    scheme = parsed.scheme.lower()
    if scheme not in ("http", "https"):
        return False, f"схема `{scheme}` не разрешена (только http/https)"
    host = parsed.hostname
    if not host:
        return False, "не удалось определить хост"
    host = host.lower()
    if host in ("localhost", "127.0.0.1", "::1"):
        return False, "localhost запрещён"
    try:
        addr = ipaddress.ip_address(host)
        if (
            addr.is_private
            or addr.is_loopback
            or addr.is_link_local
            or addr.is_reserved
            or addr.is_multicast
        ):
            return False, "внутренние IP-адреса запрещены"
    except ValueError:
        pass
    return True, ""


async def _is_safe_monitor_url_async(url: str) -> tuple[bool, str]:
    """Async variant of `_is_safe_monitor_url` that also resolves the hostname.

    DNS rebinding / bypass protection: the hostname is resolved in an executor
    and any returned address that is loopback/private/link-local/reserved/
    multicast causes the URL to be rejected. All addresses must be public.
    """
    safe, reason = _is_safe_monitor_url(url)
    if not safe:
        return False, reason

    parsed = urlparse(url)
    host = parsed.hostname
    if not host:
        return False, "не удалось определить хост"

    try:
        ipaddress.ip_address(host)
        return True, ""  # already validated by _is_safe_monitor_url
    except ValueError:
        pass  # hostname, need to resolve

    loop = asyncio.get_running_loop()
    try:
        infos = await asyncio.wait_for(
            loop.run_in_executor(None, socket.getaddrinfo, host, None),
            timeout=5,
        )
    except asyncio.TimeoutError:
        return False, "DNS таймаут"
    except socket.gaierror as exc:
        return False, f"не удалось разрешить имя: {exc.strerror or exc}"
    except OSError as exc:
        return False, f"ошибка разрешения имени: {exc}"

    if not infos:
        return False, "имя не разрешается"

    for _family, _socktype, _proto, _canonname, sockaddr in infos:
        ip = sockaddr[0]
        try:
            addr = ipaddress.ip_address(ip)
        except ValueError:
            continue
        if (
            addr.is_private
            or addr.is_loopback
            or addr.is_link_local
            or addr.is_reserved
            or addr.is_multicast
        ):
            return False, f"хост разрешается в запрещённый IP: {ip}"
    return True, ""


def _clean_snippet(text: str, max_len: int = 200) -> str:
    """Aggressively clean a web-search content snippet for Telegram display."""
    if not text:
        return ""
    text = re.sub(r"<[^>]+>", "", text)
    text = html.unescape(text)
    text = re.sub(r"\s+", " ", text).strip()

    garbage = [
        r"В приложении удобнее",
        r"RuStore",
        r"Samsung Galaxy Store",
        r"Huawei AppGallery",
        r"Xiaomi GetApps",
        r"AppGallery",
        r"GetApps",
        r"КУПИТЬ",
        r"ДОСТАВКА",
        r"СПОСОБЫ",
        r"отслеживать",
        r"Сравнить",
        r"В список желаний",
        r"Сделать любимым",
        r"Оставить отзыв",
        r"Подробнее",
        r"ПОДРОБНЕЕ",
        r"рейтинг:",
        r"\(1\)",
        r"ISBN",
        r"Артикул",
        r"Артикул:",
        r"товара:",
        r"Попробуйте обновленную версию",
        r"LiveLib",
        r"Часть функций",
        r"бета-версии",
        r"Моя оценка",
        r"Все уведомления",
        r"Рецензии",
        r"Цитаты",
        r"Издания и произведения",
        r"Пожаловаться",
        r"прочитали",
        r"планируют",
        r"рецензий",
        r"цитаты",
        r"№\d+ в ",
        r"Goodreads",
        r"Вподобайки",
        r"Характеристики",
        r"Переглянути фото",
        r"Паперова",
        r"Електронна",
        r"В наявності",
        r"Відправка:",
        r"Не получается оформить заказ?",
        r"укажите код",
        r"СПОСОБЫ ОПЛАТЫ",
        r"код \d+",
        r"КУПИТЬ С ДОСТАВКОЙ",
        r"книгу в наявності",
    ]
    for g in garbage:
        text = re.sub(g, "", text, flags=re.IGNORECASE)
    text = re.sub(r"\s+", " ", text).strip()
    sentences = re.split(r"(?<=[.!?])\s+", text)
    if sentences:
        snippet = sentences[0]
        if len(snippet) < 60 and len(sentences) > 1:
            snippet += " " + sentences[1]
    else:
        snippet = text
    if len(snippet) > max_len:
        snippet = snippet[:max_len].rsplit(" ", 1)[0] + "..."
    return snippet.strip()


def _extract_main_text(html_text: str, max_len: int = 250) -> str:
    """Use BeautifulSoup to strip nav/scripts and extract the longest coherent paragraph."""
    try:
        from bs4 import BeautifulSoup
    except Exception:
        return _clean_snippet(html_text, max_len)

    soup = BeautifulSoup(html_text, "lxml")
    for tag_name in (
        "script",
        "style",
        "nav",
        "header",
        "footer",
        "aside",
        "form",
        "button",
        "noscript",
    ):
        for t in soup.find_all(tag_name):
            t.decompose()

    meta = soup.find("meta", attrs={"name": "description"})
    if meta and meta.get("content"):
        desc = meta["content"].strip()
        if 30 < len(desc) < 300:
            return (
                desc[:max_len].rsplit(" ", 1)[0] + "..."
                if len(desc) > max_len
                else desc
            )

    candidates = []
    for tag in soup.find_all(("p", "div", "article", "section", "span")):
        txt = tag.get_text(separator=" ", strip=True)
        if len(txt) < 30:
            continue
        noise = (
            txt.count("|")
            + txt.count("→")
            + txt.count("↳")
            + txt.count("▸")
            + txt.count("·")
        )
        score = len(txt) - noise * 10
        candidates.append((score, txt))
    if not candidates:
        return _clean_snippet(html_text, max_len)
    candidates.sort(key=lambda x: x[0], reverse=True)
    best = candidates[0][1]
    best = best.replace("\n\n", "\n").split("\n")[0]
    if len(best) > max_len:
        best = best[:max_len].rsplit(" ", 1)[0] + "..."
    return best.strip()


async def ollama_web_search(query: str, max_results: int = 5):
    from bot.settings import OLLAMA_WEB_API_KEY

    if not OLLAMA_WEB_API_KEY:
        return (
            None,
            "OLLAMA_WEB_API_KEY не установлен. Получите ключ на https://ollama.com",
        )

    url = "https://ollama.com/api/web_search"
    headers = {
        "Authorization": f"Bearer {OLLAMA_WEB_API_KEY}",
        "Content-Type": "application/json",
    }
    payload = {"query": query, "max_results": max_results}

    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                url,
                headers=headers,
                json=payload,
                timeout=aiohttp.ClientTimeout(total=30),
            ) as resp:
                text = await resp.text()
                if resp.status == 200:
                    try:
                        data = json.loads(text)
                        return data, None
                    except json.JSONDecodeError as e:
                        return None, f"JSON decode error: {e}"
                else:
                    return None, f"HTTP {resp.status}: {text[:200]}"
    except Exception as e:
        return None, str(e)


async def ollama_web_fetch(url: str):
    from bot.settings import OLLAMA_WEB_API_KEY

    if not OLLAMA_WEB_API_KEY:
        return (
            None,
            "OLLAMA_WEB_API_KEY не установлен. Получите ключ на https://ollama.com",
        )

    api_url = "https://ollama.com/api/web_fetch"
    headers = {
        "Authorization": f"Bearer {OLLAMA_WEB_API_KEY}",
        "Content-Type": "application/json",
    }
    payload = {"url": url}

    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                api_url,
                headers=headers,
                json=payload,
                timeout=aiohttp.ClientTimeout(total=30),
            ) as resp:
                text = await resp.text()
                if resp.status == 200:
                    try:
                        data = json.loads(text)
                        return data, None
                    except json.JSONDecodeError as e:
                        return None, f"JSON decode error: {e}"
                else:
                    return None, f"HTTP {resp.status}: {text[:200]}"
    except Exception as e:
        return None, str(e)


async def send_alert(user_id: int, text: str):
    from bot.bot import bot as aiogram_bot

    try:
        await aiogram_bot.send_message(chat_id=user_id, text=text)
    except Exception as e:
        print(f"[ALERT] Failed to send to {user_id}: {e}")


async def _classify_memory(content: str) -> str:
    """Use Ollama to pick the best memory category for content.

    Falls back to 'note' on timeout, error, or unparseable response so the
    user is never blocked for more than ~10 seconds on classification.
    """
    import asyncio

    prompt = (
        "Ты классифицируешь заметки пользователя. Выбери одну категорию:\n"
        "- fact: факт о пользователе, проекте или мире\n"
        "- preference: предпочтение, вкус, правило поведения\n"
        "- note: обычная заметка, напоминание, мысль\n\n"
        "Ответь ТОЛЬКО одним словом: fact, preference или note.\n\n"
        f"Текст: {content}\n\n"
        "Категория:"
    )
    messages = [
        OllamaChatMessage(role="system", content=SYSTEM_MESSAGE),
        OllamaChatMessage(role="user", content=prompt),
    ]
    result = ""
    try:
        async with asyncio.timeout(10):
            async for is_done, chunk in generate_chat_completion(
                messages, OLLAMA_MODEL, temperature=0.2
            ):
                if is_done:
                    break
                if isinstance(chunk, OllamaErrorChunk):
                    break
                result += chunk.message.content
    except asyncio.TimeoutError:
        print("[AUTO MEMORY] Classification timed out — defaulting to 'note'")
        return "note"
    except Exception as e:
        print(f"[AUTO MEMORY] Classification failed: {e}")
    result = result.strip().lower()
    if result in ("fact", "preference", "note"):
        return result
    return "note"


async def _typing_until(user_id: int, task: Awaitable[T], interval: float = 4.0) -> T:
    """Keep Telegram typing action alive while `task` runs.

    Wraps the awaitable in a background loop that calls
    send_chat_action("typing") every `interval` seconds.
    Stops automatically when the task finishes or raises.
    """

    async def _loop() -> None:
        while True:
            try:
                await aiogram_bot.send_chat_action(chat_id=user_id, action="typing")
            except Exception:
                pass
            await asyncio.sleep(interval)

    worker = asyncio.create_task(_loop())
    try:
        return await task
    finally:
        worker.cancel()
        try:
            await worker
        except asyncio.CancelledError:
            pass


async def _typing_while_iterating(
    user_id: int,
    stream: AsyncIterator[T],
    interval: float = 4.0,
) -> AsyncIterator[T]:
    """Keep Telegram typing action alive while iterating over `stream`."""

    async def _loop() -> None:
        while True:
            try:
                await aiogram_bot.send_chat_action(chat_id=user_id, action="typing")
            except Exception:
                pass
            await asyncio.sleep(interval)

    worker = asyncio.create_task(_loop())
    try:
        async for item in stream:
            yield item
    finally:
        worker.cancel()
        try:
            await worker
        except asyncio.CancelledError:
            pass


def _refresh_completion_system_prompt(user_id: int) -> None:
    """Best-effort refresh of the live chat's system prompt after the user
    saves a note or memory via cron handlers."""
    try:
        from bot.routers import completion

        completion.refresh_system_prompt(user_id)
    except Exception as exc:
        logger.warning("Failed to refresh system prompt for %s: %s", user_id, exc)
