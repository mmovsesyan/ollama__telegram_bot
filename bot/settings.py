import os

from dotenv import load_dotenv

# Load environment variables from .env file if present
load_dotenv()

# Telegram token
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN", default="")

# Security: comma-separated list of allowed Telegram user IDs (e.g. "123456,789012")
# Leave empty to allow anyone
ALLOWED_CHAT_IDS = os.getenv("ALLOWED_CHAT_IDS", default="")

# Database path
DB_PATH = os.getenv("DB_PATH", default="data/bot.db")

# First message that will be sent to model as it was user.
START_USER_MESSAGE = ""

# Model system message.
SYSTEM_MESSAGE = "You are a helpful assistant. Answer concisely and clearly."

# Ollama server configuration
OLLAMA_API_HOST = os.getenv("OLLAMA_API_HOST", default="https://api.ollama.com")

# Cloud-only model allow-list. Local models (e.g. llama3.2:latest) are rejected
# by /model because the bot runs against api.ollama.com where only cloud IDs are
# available and billing is per-token. Entries are stored as base names without
# the :cloud suffix; the bot normalizes inputs before checking this list.
# Built from the provider model list dated 2026-06-18.
CLOUD_MODELS = [
    "deepseek-v3.1:671b",
    "deepseek-v3.2",
    "deepseek-v4-flash",
    "deepseek-v4-pro",
    "devstral-2:123b",
    "devstral-small-2:24b",
    "gemini-3-flash-preview",
    "gemma3:12b",
    "gemma3:27b",
    "gemma3:4b",
    "gemma4:31b",
    "glm-4.7",
    "glm-5",
    "glm-5.1",
    "glm-5.2",
    "gpt-oss:120b",
    "gpt-oss:20b",
    "kimi-k2.5",
    "kimi-k2.6",
    "kimi-k2.7-code",
    "minimax-m2.1",
    "minimax-m2.5",
    "minimax-m2.7",
    "minimax-m3",
    "ministral-3:14b",
    "ministral-3:3b",
    "ministral-3:8b",
    "mistral-large-3:675b",
    "nemotron-3-nano:30b",
    "nemotron-3-super",
    "nemotron-3-ultra",
    "qwen3-coder-next",
    "qwen3-coder:480b",
    "qwen3.5:397b",
    "rnj-1:8b",
]

# Normalised lookup set for fast membership checks.
_CLOUD_MODEL_SET = {m.lower() for m in CLOUD_MODELS}


def normalize_model_id(model_id: str) -> str:
    """Return the canonical base model name used in CLOUD_MODELS.

    Strips the :cloud/:latest suffixes so the same model can be referred to as
    'kimi-k2.7-code', 'kimi-k2.7-code:cloud' or 'kimi-k2.7-code:latest'.
    """
    if not model_id:
        return ""
    normalized = model_id.lower().strip()
    for suffix in (":cloud", ":latest"):
        if normalized.endswith(suffix):
            normalized = normalized[: -len(suffix)]
    return normalized


_default_model = "kimi-k2.7-code"
_configured_model = normalize_model_id(
    os.getenv("OLLAMA_BOT_MODEL", default=_default_model)
)
OLLAMA_MODEL = (
    _configured_model
    if _configured_model in _CLOUD_MODEL_SET
    else _default_model
)

OLLAMA_MODEL_TEMPERATURE = 1
OLLAMA_KEEP_ALIVE = "5m"
OLLAMA_API_KEY = os.getenv("OLLAMA_API_KEY", default="")
OLLAMA_MAX_CONCURRENT = int(os.getenv("OLLAMA_MAX_CONCURRENT", default="2"))

# Ollama Web Search API (https://ollama.com/api/web_search)
# Get your key at https://ollama.com and set OLLAMA_WEB_API_KEY
OLLAMA_WEB_API_KEY = os.getenv("OLLAMA_WEB_API_KEY", default="") or OLLAMA_API_KEY

# Telegram IDs of admins allowed to control the bot process via Telegram.
ADMIN_TELEGRAM_IDS = os.getenv("ADMIN_TELEGRAM_IDS", default="")


def _parse_admin_ids(raw: str) -> set[int]:
    ids: set[int] = set()
    if not raw:
        return ids
    for part in raw.split(","):
        part = part.strip()
        if part.isdigit():
            ids.add(int(part))
    return ids


ADMIN_IDS = _parse_admin_ids(ADMIN_TELEGRAM_IDS)

# Whisper model for voice/audio transcription.
# Available models: tiny, tiny.en, base, base.en, small, small.en, medium, medium.en, large-v1, large-v2, large-v3, turbo
WHISPER_MODEL = os.getenv("WHISPER_MODEL", default="tiny")
WHISPER_DEVICE = os.getenv("WHISPER_DEVICE", default="auto")  # cpu, cuda, auto
WHISPER_COMPUTE_TYPE = os.getenv(
    "WHISPER_COMPUTE_TYPE", default="default"
)  # int8, float16, default

# Document storage and chunking settings
DOCUMENTS_DIR = os.getenv("DOCUMENTS_DIR", default="data")
DOCUMENT_CHUNK_SIZE = int(os.getenv("DOCUMENT_CHUNK_SIZE", default="1500"))
DOCUMENT_CHUNK_OVERLAP = int(os.getenv("DOCUMENT_CHUNK_OVERLAP", default="200"))
DOCUMENT_MAX_SUMMARY_CHARS = int(
    os.getenv("DOCUMENT_MAX_SUMMARY_CHARS", default="8000")
)

# Smart reminder suggestion settings
SMART_REMINDERS_ENABLED = os.getenv("SMART_REMINDERS_ENABLED", default="1") == "1"
SMART_REMINDERS_COOLDOWN_MIN = int(
    os.getenv("SMART_REMINDERS_COOLDOWN_MIN", default="5")
)
SMART_REMINDERS_MESSAGE_THRESHOLD = int(
    os.getenv("SMART_REMINDERS_MESSAGE_THRESHOLD", default="10")
)
SMART_REMINDERS_CONFIDENCE = float(
    os.getenv("SMART_REMINDERS_CONFIDENCE", default="0.7")
)

# Image / vision settings
IMAGES_DIR = os.getenv("IMAGES_DIR", default="data")
VISION_MODEL = os.getenv("VISION_MODEL", default=OLLAMA_MODEL)

# Chat context limit (number of last messages to keep, excluding system)
MAX_CONTEXT_MESSAGES = int(os.getenv("MAX_CONTEXT_MESSAGES", default="20"))

# Soft token budget for the non-system part of the active chat context.
# Increase this for large-context models (e.g. kimi-k2.7-code:cloud).
MAX_CONTEXT_TOKENS = int(os.getenv("MAX_CONTEXT_TOKENS", default="16000"))

# Compaction: summarize every N user+assistant messages
COMPACTION_EVERY_N = int(os.getenv("COMPACTION_EVERY_N", default="8"))

# News aggregator settings
# Default RSS feeds for the /news command. Comma-separated list of feed URLs.
# Curated mix of Russian tech/business/games and English top-tier sources.
DEFAULT_RSS_FEEDS = os.getenv(
    "DEFAULT_RSS_FEEDS",
    default="https://habr.com/ru/rss/articles/top/,"
    "https://vc.ru/rss/all,"
    "https://www.cnews.ru/inc/rss/news.xml,"
    "https://tadviser.ru/rss/news,"
    "https://www.iguides.ru/main/rss/mainarticles.xml,"
    "https://lenta.ru/rss/news/it,"
    "https://www.rbc.ru/technology/?utm_source=topline_rbc,"
    "https://www.kommersant.ru/rss/regions/77.xml,"
    "https://www.vedomosti.ru/rss/news,"
    "https://www.bloomberg.com/feeds/markets/news.rss,"
    "https://www.reuters.com/business/finance/rss/,"
    "https://feeds.a.dj.com/rss/RSSMarketsMain.xml,"
    "https://www.ft.com/rss/home/uk,"
    "https://techcrunch.com/feed/,"
    "https://www.theverge.com/rss/index.xml,"
    "https://www.igromania.ru/rss/articles.xml,"
    "https://stopgame.ru/rss/rss_news.xml,"
    "https://dtf.ru/rss/all,"
    "https://kanobu.ru/rss/news.rss,"
    "https://www.bbc.co.uk/russian/rss.xml,"
    "https://meduza.io/rss/all",
)
RSS_FEEDS = [u.strip() for u in DEFAULT_RSS_FEEDS.split(",") if u.strip()]

# Topic-keywords → preferred feed URLs. Helps route a query to feeds that are
# most likely to contain relevant news before falling back to generic web search.
_RSS_TOPIC_FEEDS_RAW = os.getenv(
    "RSS_TOPIC_FEEDS",
    default="games:https://www.igromania.ru/rss/articles.xml,https://stopgame.ru/rss/rss_news.xml,https://dtf.ru/rss/all,https://kanobu.ru/rss/news.rss;"
    "игры:https://www.igromania.ru/rss/articles.xml,https://stopgame.ru/rss/rss_news.xml,https://dtf.ru/rss/all,https://kanobu.ru/rss/news.rss;"
    "tech:https://habr.com/ru/rss/articles/top/,https://vc.ru/rss/all,https://techcrunch.com/feed/,https://www.theverge.com/rss/index.xml;"
    "технологии:https://habr.com/ru/rss/articles/top/,https://vc.ru/rss/all,https://techcrunch.com/feed/,https://www.theverge.com/rss/index.xml;"
    "markets:https://www.kommersant.ru/rss/regions/77.xml,https://www.vedomosti.ru/rss/news,https://www.bloomberg.com/feeds/markets/news.rss,https://feeds.a.dj.com/rss/RSSMarketsMain.xml;"
    "акции:https://www.kommersant.ru/rss/regions/77.xml,https://www.vedomosti.ru/rss/news,https://www.bloomberg.com/feeds/markets/news.rss,https://feeds.a.dj.com/rss/RSSMarketsMain.xml;"
    "финансы:https://www.kommersant.ru/rss/regions/77.xml,https://www.vedomosti.ru/rss/news,https://www.bloomberg.com/feeds/markets/news.rss,https://feeds.a.dj.com/rss/RSSMarketsMain.xml;"
    "рынки:https://www.kommersant.ru/rss/regions/77.xml,https://www.vedomosti.ru/rss/news,https://www.bloomberg.com/feeds/markets/news.rss,https://feeds.a.dj.com/rss/RSSMarketsMain.xml;"
    "ai:https://habr.com/ru/rss/articles/top/,https://vc.ru/rss/all,https://techcrunch.com/feed/;"
    "ии:https://habr.com/ru/rss/articles/top/,https://vc.ru/rss/all,https://techcrunch.com/feed/;"
    "искусственный интеллект:https://habr.com/ru/rss/articles/top/,https://vc.ru/rss/all,https://techcrunch.com/feed/;"
    "world:https://www.bbc.co.uk/russian/rss.xml,https://meduza.io/rss/all,https://www.kommersant.ru/rss/regions/77.xml;"
    "мир:https://www.bbc.co.uk/russian/rss.xml,https://meduza.io/rss/all,https://www.kommersant.ru/rss/regions/77.xml",
)


def _parse_topic_feeds(raw: str) -> dict[str, list[str]]:
    mapping: dict[str, list[str]] = {}
    for chunk in raw.split(";"):
        chunk = chunk.strip()
        if not chunk or ":" not in chunk:
            continue
        topic, urls = chunk.split(":", 1)
        topic = topic.strip().lower()
        mapping[topic] = [u.strip() for u in urls.split(",") if u.strip()]
    return mapping


RSS_TOPIC_FEEDS: dict[str, list[str]] = _parse_topic_feeds(_RSS_TOPIC_FEEDS_RAW)

# How far back to look for RSS news (hours)
RSS_NEWS_HOURS = int(os.getenv("RSS_NEWS_HOURS", default="48"))

# Web-search provider for fallback when RSS has no fresh news.
# Supported: "ollama", "duckduckgo", "searxng"
WEB_SEARCH_PROVIDER = os.getenv("WEB_SEARCH_PROVIDER", default="duckduckgo").lower()
SEARXNG_URL = os.getenv("SEARXNG_URL", default="").rstrip("/")

# Region / language for DuckDuckGo (e.g. "ru-ru", "us-en")
DUCKDUCKGO_REGION = os.getenv("DUCKDUCKGO_REGION", default="ru-ru")

# Preferred news language for filtering and display
NEWS_LANGUAGE = os.getenv("NEWS_LANGUAGE", default="ru")

# Prompt used for summarization
SUMMARY_PROMPT = os.getenv(
    "SUMMARY_PROMPT",
    default=(
        "Проанализируй следующий диалог и создай краткую выжимку, сохраняя:\n"
        "- ключевые факты и решения\n"
        "- предпочтения пользователя\n"
        "- важный контекст для будущих сообщений\n"
        "- нерешённые вопросы или задачи\n\n"
        "Ответь ТОЛЬКО текстом выжимки, без вступлений."
    ),
)
