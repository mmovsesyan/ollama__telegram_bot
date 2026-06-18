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
OLLAMA_MODEL = os.getenv("OLLAMA_BOT_MODEL", default="kimi-k2.7-code:cloud")
OLLAMA_MODEL_TEMPERATURE = 1
OLLAMA_KEEP_ALIVE = "5m"
OLLAMA_API_KEY = os.getenv("OLLAMA_API_KEY", default="")

# Ollama Web Search API (https://ollama.com/api/web_search)
# Get your key at https://ollama.com and set OLLAMA_WEB_API_KEY
OLLAMA_WEB_API_KEY = os.getenv("OLLAMA_WEB_API_KEY", default="") or OLLAMA_API_KEY

# Whisper model for voice/audio transcription.
# Available models: tiny, tiny.en, base, base.en, small, small.en, medium, medium.en, large-v1, large-v2, large-v3, turbo
WHISPER_MODEL = os.getenv("WHISPER_MODEL", default="tiny")
WHISPER_DEVICE = os.getenv("WHISPER_DEVICE", default="auto")  # cpu, cuda, auto
WHISPER_COMPUTE_TYPE = os.getenv("WHISPER_COMPUTE_TYPE", default="default")  # int8, float16, default

# Chat context limit (number of last messages to keep, excluding system)
MAX_CONTEXT_MESSAGES = int(os.getenv("MAX_CONTEXT_MESSAGES", default="20"))

# Soft token budget for the non-system part of the active chat context.
# Increase this for large-context models (e.g. kimi-k2.7-code:cloud).
MAX_CONTEXT_TOKENS = int(os.getenv("MAX_CONTEXT_TOKENS", default="16000"))

# Compaction: summarize every N user+assistant messages
COMPACTION_EVERY_N = int(os.getenv("COMPACTION_EVERY_N", default="8"))

# News aggregator settings
# Default RSS feeds for the /news command. Comma-separated list of feed URLs.
DEFAULT_RSS_FEEDS = os.getenv(
    "DEFAULT_RSS_FEEDS",
    default="https://habr.com/ru/rss/articles/top/,"
            "https://vc.ru/rss/all,"
            "https://www.cnews.ru/inc/rss/news.xml,"
            "https://tadviser.ru/rss/news,"
            "https://www.iguides.ru/main/rss/mainarticles.xml,"
            "https://lenta.ru/rss/news/it,"
            "https://www.rbc.ru/technology/?utm_source=topline_rbc",
)
RSS_FEEDS = [u.strip() for u in DEFAULT_RSS_FEEDS.split(",") if u.strip()]

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
