import os

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
OLLAMA_API_HOST = os.getenv("OLLAMA_API_HOST", default="http://localhost:11434")
OLLAMA_MODEL = os.getenv("OLLAMA_BOT_MODEL", default="llama2:13b-chat")
OLLAMA_MODEL_TEMPERATURE = 1
OLLAMA_KEEP_ALIVE = "5m"

# Ollama Web Search API (https://ollama.com/api/web_search)
# Get your key at https://ollama.com and set OLLAMA_WEB_API_KEY
OLLAMA_WEB_API_KEY = os.getenv("OLLAMA_WEB_API_KEY", default="")

# Chat context limit (number of last messages to keep, excluding system)
MAX_CONTEXT_MESSAGES = int(os.getenv("MAX_CONTEXT_MESSAGES", default="20"))

# Compaction: summarize every N user+assistant messages
COMPACTION_EVERY_N = int(os.getenv("COMPACTION_EVERY_N", default="8"))

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
