import logging
import re
from urllib.parse import urlparse

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import InputMediaPhoto, Message

from bot.keyboards.reply import cancel_keyboard, command_keyboard
from bot.security import is_allowed as _is_allowed
from bot.services.weather import get_forecast, get_weather
from bot.states import BotStates
from bot.routers.common import (
    _BUTTON_HANDLERS,
    _fsm_guard,
    _typing_until,
    ollama_web_fetch,
    ollama_web_search,
)

router = Router()
logger = logging.getLogger(__name__)

# Injected from bot/__init__.py at startup.
db = None


# --- Weather ---


@router.message(lambda m: m.text and m.text.startswith("/weather"))
async def cmd_weather(message: Message, state: FSMContext):
    await state.clear()
    if message.from_user is None:
        return
    if not _is_allowed(message.from_user.id):
        return

    parts = message.text.split(maxsplit=1)
    if len(parts) < 2:
        await message.answer(
            "🌤 Введи название города:\n"
            "Пример: Москва\n"
            "Или прогноз: «Москва на неделю», «Сочи 5 дней», «Москва месяц»",
            reply_markup=cancel_keyboard,
        )
        await state.set_state(BotStates.waiting_weather)
        return

    await _process_weather(message, parts[1].strip())


async def _process_weather(message: Message, raw: str):
    """Handle both '/weather Moscow' and '/weather Moscow на неделю'.
    Strips trailing duration phrases from the city, then routes to
    get_forecast or get_weather depending on intent."""
    from bot.intent.tools.weather import _FORECAST_PHRASE_RE, _detect_days

    raw = (raw or "").strip()
    days = _detect_days(raw)
    is_forecast = bool(days) or bool(_FORECAST_PHRASE_RE.search(raw))

    # Strip trailing duration / forecast phrases so 'Москва на неделю'
    # leaves just 'Москва' as the city.
    city = re.sub(
        r"\s*(?:на\s+)?(?:неделю|неделя|месяц|выходные|завтра|послезавтра|"
        r"ближайш\w*|прогноз\w*|forecast|this\s+week|this\s+month|tomorrow|"
        r"\d+\s*(?:день|дня|дней|сутки|суток)|next\s+\d+\s+days?)\s*",
        " ",
        raw,
        flags=re.IGNORECASE,
    ).strip(" ,.;-—")

    if not city:
        await message.answer(
            "🌤 Не понял город. Пример: Москва", reply_markup=command_keyboard
        )
        return

    label = "прогноз" if is_forecast else "погоду"
    await message.answer(f"🌤 Ищу {label}: {city}...")
    user_id = message.from_user.id
    if is_forecast:
        text, error = await _typing_until(user_id, get_forecast(city, days or 7))
    else:
        text, error = await _typing_until(user_id, get_weather(city))
    if error:
        await message.answer(
            f"❌ Ошибка погоды: {error}", reply_markup=command_keyboard
        )
        return
    await message.answer(text, reply_markup=command_keyboard)


@router.message(BotStates.waiting_weather)
async def process_weather(message: Message, state: FSMContext):
    if message.from_user is None:
        await state.clear()
        return
    if message.text is None:
        await message.answer("Ожидался текст.", reply_markup=cancel_keyboard)
        await state.clear()
        return
    if await _fsm_guard(message, state):
        return
    await _process_weather(message, message.text.strip())
    await state.clear()


# --- News ---


def _format_search_results(query: str, items: list[dict]) -> str:
    """Render Ollama web-search results as compact clickable cards (HTML)."""
    from html import escape
    import re

    blocks = [f"<b>🔍 {escape(query)}</b>", ""]
    for i, item in enumerate(items[:5], 1):
        title = (item.get("title") or "Без названия").strip()
        url = (item.get("url") or "").strip()
        raw_content = item.get("content") or item.get("body") or ""
        # Web search snippets sometimes contain raw HTML/imgs; strip tags.
        snippet = re.sub(r"<[^>]+>", " ", str(raw_content))
        snippet = re.sub(r"\s+", " ", snippet).strip()
        if len(snippet) > 180:
            snippet = snippet[:180].rsplit(" ", 1)[0] + "..."

        domain = ""
        if url:
            try:
                domain = urlparse(url).netloc.replace("www.", "")
            except Exception:
                pass

        safe_title = escape(title)
        safe_url = escape(url)
        safe_domain = escape(domain)
        safe_snippet = escape(snippet)

        lines = [f"<b>{i}.</b> <a href=\"{safe_url}\">{safe_title}</a>"]
        if domain:
            lines.append(f"<i>{safe_domain}</i>")
        if snippet:
            lines.append(safe_snippet)
        blocks.append("\n".join(lines))
        blocks.append("")
    return "\n".join(blocks)[:4096]


async def _process_news(message: Message, topic: str | None = None):
    """Fetch fresh news: RSS-first, then web-search fallback.

    RSS gives us curated, recent sources; if nothing matches the topic or
    the feeds are stale we fall back to DuckDuckGo/SearXNG/Ollama depending on
    the WEB_SEARCH_PROVIDER setting.
    """
    if message.from_user is None:
        return
    user_id = message.from_user.id
    label = topic.strip() if topic and topic.strip() else "топ-новости"

    # Expand known category aliases (e.g. "ии" → "искусственный интеллект нейросети")
    # so RSS topic feeds and keyword matching both hit the right content.
    from bot.services.news_categories import _normalize_category, _topic_for_category

    search_topic = topic
    if topic:
        normalized = _normalize_category(topic)
        expanded = _topic_for_category(normalized)
        if expanded != normalized:
            search_topic = expanded

    await message.answer(f"📰 Ищу новости: {label}...")

    from bot.services.rss_news import get_fresh_news, render_news

    text, items, source = await _typing_until(
        user_id, get_fresh_news(user_id, topic=search_topic, limit=5)
    )
    if not items:
        await message.answer(
            f"Новостей по запросу «{label}» не найдено.",
            reply_markup=command_keyboard,
        )
        return

    # Render with clickable headlines for Telegram HTML parse mode.
    full_text = render_news(
        items,
        header=f"📰 Новости: {label}",
        html=True,
    )
    if len(full_text) > 4096:
        full_text = full_text[:4090] + "..."

    # Send image previews as an album when available; Telegram albums are
    # limited to 10 media and captions must fit 1024 chars. Keep it simple:
    # first image with a compact summary, then the full text list.
    image_items = [it for it in items if it.image_url][:4]
    if image_items:
        media_group: list[InputMediaPhoto] = []
        for it in image_items:
            caption = f"<b>{it.title}</b>\n\n{it.summary[:140]}"
            if len(caption) > 1024:
                caption = caption[:1020] + "..."
            media_group.append(
                InputMediaPhoto(
                    media=it.image_url,
                    caption=caption,
                    parse_mode="HTML",
                )
            )
        try:
            await message.answer_media_group(media_group)
        except Exception as e:
            logger.warning("[NEWS] failed to send media group: %s", e)

    await message.answer(
        full_text, reply_markup=command_keyboard, parse_mode="HTML"
    )


async def _process_digest(message: Message):
    if message.from_user is None:
        return
    user_id = message.from_user.id
    await message.answer("📰 Собираю персональный дайджест...")

    from bot.services.news_categories import get_personalized_digest

    text = await _typing_until(user_id, get_personalized_digest(user_id))
    await message.answer(text, reply_markup=command_keyboard)


@router.message(lambda m: m.text and m.text.startswith("/news"))
async def cmd_news(message: Message, state: FSMContext):
    """`/news` alone → ask for topic. `/news <topic>` → search immediately."""
    await state.clear()
    if message.from_user is None:
        return
    if not _is_allowed(message.from_user.id):
        return
    parts = message.text.split(maxsplit=1)
    if len(parts) < 2:
        await message.answer(
            "📰 По какой теме новости?\n"
            "Например: «ИИ», «Tesla», «биткоин», «спорт»\n"
            "Или «дайджест» — персональная подборка по категориям.\n"
            "Или просто «топ» — покажу самое актуальное.",
            reply_markup=cancel_keyboard,
        )
        await state.set_state(BotStates.waiting_news)
        return
    await _process_news(message, parts[1])


@router.message(BotStates.waiting_news)
async def process_news(message: Message, state: FSMContext):
    if message.from_user is None:
        await state.clear()
        return
    if message.text is None:
        await message.answer("Ожидался текст.", reply_markup=cancel_keyboard)
        await state.clear()
        return
    if await _fsm_guard(message, state):
        return
    topic = message.text.strip()
    lowered = topic.lower()
    if lowered in ("топ", "top", ""):
        topic = None
        await _process_news(message, topic)
    elif lowered in ("дайджест", "digest", "мои", "подписки"):
        await _process_digest(message)
    else:
        await _process_news(message, topic)
    await state.clear()


@router.message(lambda m: m.text and m.text.startswith("/news_subscribe"))
async def cmd_news_subscribe(message: Message, state: FSMContext):
    await state.clear()
    if message.from_user is None:
        return
    if not _is_allowed(message.from_user.id):
        return
    if db is None:
        await message.answer("База данных недоступна.", reply_markup=command_keyboard)
        return

    parts = message.text.split(maxsplit=1)
    if len(parts) < 2:
        await message.answer(
            "📰 Какую категорию добавить?\n"
            "tech, markets, ai, science, crypto, world, games",
            reply_markup=cancel_keyboard,
        )
        return

    from bot.services.news_categories import add_user_category

    cats, added = add_user_category(message.from_user.id, parts[1])
    if added:
        await message.answer(
            f"✅ Добавлено. Твои категории: {', '.join(cats)}",
            reply_markup=command_keyboard,
        )
    else:
        await message.answer(
            f"⚠️ Уже есть или неизвестная категория. Текущие: {', '.join(cats)}",
            reply_markup=command_keyboard,
        )


@router.message(lambda m: m.text and m.text.startswith("/news_unsubscribe"))
async def cmd_news_unsubscribe(message: Message, state: FSMContext):
    await state.clear()
    if message.from_user is None:
        return
    if not _is_allowed(message.from_user.id):
        return
    if db is None:
        await message.answer("База данных недоступна.", reply_markup=command_keyboard)
        return

    parts = message.text.split(maxsplit=1)
    if len(parts) < 2:
        await message.answer(
            "📰 Какую категорию убрать?\n"
            "tech, markets, ai, science, crypto, world, games",
            reply_markup=cancel_keyboard,
        )
        return

    from bot.services.news_categories import remove_user_category

    cats, removed = remove_user_category(message.from_user.id, parts[1])
    if removed:
        await message.answer(
            f"✅ Убрано. Твои категории: {', '.join(cats)}",
            reply_markup=command_keyboard,
        )
    else:
        await message.answer(
            f"⚠️ Категории не было в подписках. Текущие: {', '.join(cats)}",
            reply_markup=command_keyboard,
        )


# --- Search ---


@router.message(F.text == "✨ Умный запрос")
async def btn_smart_block(message: Message, state: FSMContext):
    """Single smart-entry button replaces separate search/weather/news/task/note buttons."""
    await state.clear()
    if message.from_user is None:
        return
    if not _is_allowed(message.from_user.id):
        return
    await message.answer(
        "🧠 Умный режим. Просто напиши запрос:\n"
        "• «погода в Москве»\n"
        "• «новости Tesla»\n"
        "• «задача через час проверить почту»\n"
        "• «заметка: купить молоко»\n"
        "• «поищи рецепт пасты»",
        reply_markup=command_keyboard,
    )


@router.message(lambda m: m.text and m.text.startswith("/search"))
async def cmd_search(message: Message, state: FSMContext):
    await state.clear()
    if message.from_user is None:
        return
    if not _is_allowed(message.from_user.id):
        return
    parts = message.text.split(maxsplit=1)
    if len(parts) < 2:
        await message.answer(
            "🔍 Введи поисковый запрос:\n" "Пример: последние новости о Tesla",
            reply_markup=cancel_keyboard,
        )
        await state.set_state(BotStates.waiting_search)
        return
    await _process_search(message, parts[1].strip())


async def _process_search(message: Message, query: str):
    user_id = message.from_user.id
    await message.answer(f"🔍 Ищу в интернете: {query}...")

    result, error = await _typing_until(
        user_id, ollama_web_search(query, max_results=5)
    )
    if error:
        await message.answer(
            f"❌ Ошибка поиска: {error}", reply_markup=command_keyboard
        )
        return

    if not result or "results" not in result:
        await message.answer("Ничего не найдено.", reply_markup=command_keyboard)
        return

    items = result["results"]
    if not items:
        await message.answer("Ничего не найдено.", reply_markup=command_keyboard)
        return

    text = _format_search_results(query, items)
    await message.answer(
        text, reply_markup=command_keyboard, parse_mode="HTML"
    )


@router.message(BotStates.waiting_search)
async def process_search(message: Message, state: FSMContext):
    if message.from_user is None:
        await state.clear()
        return
    if message.text is None:
        await message.answer("Ожидался текст.", reply_markup=cancel_keyboard)
        await state.clear()
        return
    if await _fsm_guard(message, state):
        return
    await _process_search(message, message.text.strip())
    await state.clear()


# --- Fetch ---


@router.message(lambda m: m.text and m.text.startswith("/fetch"))
async def cmd_fetch(message: Message, state: FSMContext):
    await state.clear()
    if message.from_user is None:
        return
    if not _is_allowed(message.from_user.id):
        return

    parts = message.text.split(maxsplit=1)
    if len(parts) < 2:
        await message.answer(
            "📄 Введи URL для загрузки:\n" "Пример: https://example.com/article",
            reply_markup=cancel_keyboard,
        )
        await state.set_state(BotStates.waiting_fetch)
        return

    await _process_fetch(message, parts[1].strip())


async def _process_fetch(message: Message, url: str):
    if message.from_user is None:
        return
    user_id = message.from_user.id
    await message.answer(f"📄 Загружаю: {url}...")

    result, error = await _typing_until(user_id, ollama_web_fetch(url))
    if error:
        await message.answer(
            f"❌ Ошибка загрузки: {error}", reply_markup=command_keyboard
        )
        return

    title = result.get("title", "Без названия")
    content = result.get("content", "")[:3000]
    links = result.get("links", [])[:10]

    text = f"📄 {title}\n\n{content}\n"
    if links:
        text += "\n🔗 Ссылки на странице:\n"
        for link in links:
            text += f"- {link}\n"

    if len(text) > 4096:
        text = text[:4090] + "..."

    await message.answer(text, reply_markup=command_keyboard)


@router.message(BotStates.waiting_fetch)
async def process_fetch(message: Message, state: FSMContext):
    if message.from_user is None:
        await state.clear()
        return
    if message.text is None:
        await message.answer("Ожидался текст.", reply_markup=cancel_keyboard)
        await state.clear()
        return
    if await _fsm_guard(message, state):
        return
    await _process_fetch(message, message.text.strip())
    await state.clear()


_BUTTON_HANDLERS.update(
    {
        "✨ Умный запрос": lambda msg, st: btn_smart_block(msg, st),
    }
)
