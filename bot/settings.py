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
# available and billing is per-token. Keep this list in sync with the provider.
CLOUD_MODELS = [
    "kimi-k2.7-code:cloud",
    "kimi-k2.5:cloud",
    "kimi-k2.6:cloud",
    "qwen3-coder:480b:cloud",
    "qwen3-coder-next:cloud",
    "qwen3.5:397b:cloud",
    "deepseek-v3.1:671b:cloud",
    "deepseek-v3.2:cloud",
    "deepseek-v4-pro:cloud",
    "deepseek-v4-flash:cloud",
    "nemotron-3-super:cloud",
    "nemotron-3-ultra:cloud",
    "nemotron-3-nano:30b:cloud",
    "mistral-large-3:675b:cloud",
    "ministral-3:3b:cloud",
    "ministral-3:8b:cloud",
    "ministral-3:14b:cloud",
    "gpt-oss:20b:cloud",
    "gpt-oss:120b:cloud",
    "gemma3:4b:cloud",
    "gemma3:12b:cloud",
    "gemma3:27b:cloud",
    "gemma4:31b:cloud",
    "glm-4.7:cloud",
    "glm-5:cloud",
    "glm-5.1:cloud",
    "glm-5.2:cloud",
    "minimax-m2.1:cloud",
    "minimax-m2.5:cloud",
    "minimax-m2.7:cloud",
    "minimax-m3:cloud",
    "devstral-small-2:24b:cloud",
    "devstral-2:123b:cloud",
    "gemini-3-flash-preview:cloud",
    "rnj-1:8b:cloud",
]

OLLAMA_MODEL = os.getenv("OLLAMA_BOT_MODEL", default="kimi-k2.7-code:cloud")
OLLAMA_MODEL_TEMPERATURE = 1
OLLAMA_KEEP_ALIVE = "5m"
OLLAMA_API_KEY = os.getenv("OLLAMA_API_KEY", default="")
OLLAMA_MAX_CONCURRENT = int(os.getenv("OLLAMA_MAX_CONCURRENT", default="2"))

# Ollama Web Search API (https://ollama.com/api/web_search)
# Get your key at https://ollama.com and set OLLAMA_WEB_API_KEY
OLLAMA_WEB_API_KEY = os.getenv("OLLAMA_WEB_API_KEY", default="") or OLLAMA_API_KEY

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
