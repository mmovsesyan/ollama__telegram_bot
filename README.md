<div align="center">

# 🤖 Ollama Telegram Bot

**Cross-platform Telegram AI bot powered by Ollama**

With long-term memory, reminders, web search, site monitoring, and voice recognition.

🌐 [Русская версия ниже](#-ollama-telegram-bot-русская-версия)

[![Python](https://img.shields.io/badge/python-3.10%2B-blue.svg)](https://www.python.org/)
[![Poetry](https://img.shields.io/badge/poetry-2.x-blueviolet.svg)](https://python-poetry.org/)
[![Ollama](https://img.shields.io/badge/ollama-cloud%20%7C%20local-white.svg)](https://ollama.com/)
[![License](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)

</div>

---

## ✨ Features

| Feature | Description |
|---------|-------------|
| ✨ **Smart input** | One button/field for chat, weather, news, tasks, notes and web search — the bot figures out the intent |
| ⏰ **Reminders** | One-shot and recurring: daily, weekdays, weekends, weekly, monthly |
| 🤖 **AI tasks** | Create tasks via smart input: «задача через час проверить почту» — the AI executes them at the scheduled time |
| 🎤 **Voice messages** | Speech-to-text via Whisper, processed the same way as text |
| 🧠 **Memory** | Facts, preferences, notes. Auto-extract after each reply, LLM-compaction for long entries |
| 📚 **Knowledge base (FTS5)** | Full-text search over your memory. "What did I say about X" — instant, no LLM. Empty result falls back to the web |
| 📄 **Files** | Text extraction from PDF, DOCX, XLSX, CSV, TXT, JSON, MD and more. Reply to the summary to ask questions about the document |
| 📷 **Photo Q&A** | Send a photo, get a description + OCR, then reply to ask questions about that specific image |
| 🧹 **Retention** | Old documents and photos are auto-deleted after 90 days (configurable). Manual `/cleanup` available |
| 🔎 **Site monitoring** | URL checks with Telegram alerts, alert state survives restarts |
| 🌍 **Localization** | Bot asks for name and country on first launch, all times shown in your timezone |
| ✏️ **Editing** | Edit reminder/task text or time directly in Telegram |
| ✅ **Smart completion** | Say «готово», «сделал» or «done» about an active reminder/task — the bot will offer to close it |
| 🛡 **Multi-user access control** | New users request access; admin approves/rejects/removes them from a single DB-backed admin panel |

---

## 🚀 Quick install

### 1. One-liner (recommended)

```bash
curl -sSL https://raw.githubusercontent.com/mmovsesyan/ollama__telegram_bot/main/install.sh | bash
```

The script will:
- check and install **Python 3.10+**, **git**, **ffmpeg**, **Poetry**;
- install Python dependencies;
- pre-download the Whisper model;
- interactively create `.env` with the required keys.

On Linux **sudo** is required for system packages — the script will ask.
On macOS Homebrew is used (usually no sudo needed).

### 2. Fully unattended (servers / CI)

```bash
export TELEGRAM_TOKEN="123456:ABC..."
export OLLAMA_API_KEY="your_ollama_key"
export OLLAMA_BOT_MODEL="kimi-k2.7-code:cloud"
export OLLAMA_API_HOST="https://api.ollama.com"

curl -sSL https://raw.githubusercontent.com/mmovsesyan/ollama__telegram_bot/main/install_auto.sh | bash
```

Silent mode without prompts:

```bash
AUTO_INSTALL=1 curl -sSL https://raw.githubusercontent.com/mmovsesyan/ollama__telegram_bot/main/install_auto.sh | bash
```

### 3. Manual (if git is already available)

```bash
git clone https://github.com/mmovsesyan/ollama__telegram_bot.git
cd ollama__telegram_bot
./scripts/install_deps.sh
./run.sh env
./run.sh start
```

---

## 🖥 Supported platforms

- **macOS** 11+ (Intel and Apple Silicon)
- **Linux**:
  - Ubuntu / Debian / Pop!_OS / Linux Mint / Zorin OS / elementary OS
  - Fedora / RHEL / CentOS / Rocky Linux / AlmaLinux / Nobara
  - Arch Linux / Manjaro / EndeavourOS / Garuda
- **Windows** via **WSL2** or Git Bash

---

## 🎛 Bot management

```bash
./run.sh start      # start (creates .env on first run)
./run.sh stop       # stop
./run.sh restart    # restart
./run.sh status     # status
./run.sh logs       # tail logs in real time
./run.sh env        # recreate .env
./run.sh deps       # install/upgrade dependencies
```

Auto-update:

```bash
./update.sh         # git pull + dependency upgrade + restart
```

System service and cron-based auto-update:

```bash
./install_service.sh
```

---

## 📋 How to talk to the bot

On the first `/start` the bot asks for your name and country — needed so reminders fire in your local timezone.

Then just write or speak:

- "weather in Moscow"
- "weather in San Francisco"
- "remind me in 5 minutes to call"
- "tomorrow at 9:00 check the report"
- "every morning at 9 show the news" (this is a task — the AI will execute it)
- "remember I prefer short answers"
- "note: buy TSLA shares"
- "find latest Tesla news"
- "news about AI"
- "what did I say about Tesla?" — searches your KB, falls back to the web if empty
- "watch google.com"

> 💡 Voice messages are transcribed via Whisper and routed through the same pipeline as text.

> ⚡ Obvious commands (remind, weather, search) are matched instantly via regex, no LLM. Complex queries go through the LLM router with a 15-second timeout.

### Bot commands

| Command | Description |
|---------|-------------|
| `/start` | Onboarding (name + timezone) or back to main menu |
| `/help` | Full help with examples |
| `/remind` | Add a reminder (step-by-step) |
| `/reminders` | List reminders and tasks with edit/delete buttons |
| `/task` | Add an AI task (step-by-step) |
| `/memory` | Memory menu (facts, preferences, notes) |
| `/memory_add` | Add a memory entry |
| `/note` | Save a note |
| `/kb <query>` | Search your knowledge base (with web fallback) |
| `/search <query>` | Web-only search |
| `/weather <city>` | Weather |
| `/news <topic>` | News by topic (no topic = general top) |
| `/monitor_add` | Add a site monitor |
| `/monitors` | List monitors |
| `/models` | List available models |
| `/model <name>` | Switch model |
| `/clear` | Clear chat history |
| `/report` | Daily report |

### Admin commands

| Command | Description |
|---------|-------------|
| `/admin_requests` | List pending access requests |
| `/admin_approve <id>` | Approve a user |
| `/admin_reject <id>` | Reject a user |
| `/admin_remove <id>` | Remove a user from the access list |
| `/admin_list` | List all users |
| `/admin_promote <id>` | Make a user an admin |
| `/admin_demote <id>` | Remove admin rights |

The first user listed in `ALLOWED_CHAT_IDS` is bootstrapped as an admin on first DB creation. If `ALLOWED_CHAT_IDS` is empty, the first user who writes `/start` can be promoted to admin manually via `/admin_promote`.

---

## ⚙️ `.env` configuration

```env
# Telegram Bot Token from @BotFather
TELEGRAM_TOKEN=123456:ABC...

# Optional: comma-separated allowed Telegram IDs
ALLOWED_CHAT_IDS=

# Ollama Cloud (default) or local Ollama
OLLAMA_API_HOST=https://api.ollama.com
OLLAMA_BOT_MODEL=kimi-k2.7-code:cloud
OLLAMA_API_KEY=your_ollama_api_key

# Web search API key (falls back to OLLAMA_API_KEY if empty)
OLLAMA_WEB_API_KEY=your_ollama_web_key

# Whisper: model and parameters
WHISPER_MODEL=tiny         # tiny, base, small, medium, large-v3, turbo
WHISPER_DEVICE=auto        # cpu, cuda, auto
WHISPER_COMPUTE_TYPE=default # int8, float16, default
```

---

## 🛡 Security

- `.env`, logs and the database are excluded from git (`.gitignore`).
- Git history was scrubbed of secrets.
- `ALLOWED_CHAT_IDS` bootstraps the initial admin(s) and approved users on first DB creation. After that the SQLite `users` table is the source of truth; use admin commands to manage access.
- New users start with `pending` status and require admin approval before any bot features work.
- Admin commands are checked against the `is_admin` flag in the DB.
- Never commit real tokens or keys.

---

## 📄 License

MIT

---

<div align="center">

# 🤖 Ollama Telegram Bot (Русская версия)

**Кроссплатформенный Telegram AI-бот на базе Ollama**

С долгосрочной памятью, напоминаниями, веб-поиском, мониторингом сайтов и распознаванием голоса.

</div>

---

## ✨ Возможности

| Функция | Описание |
|---------|----------|
| 💬 **AI-чат** | Контекстный диалог со сменой моделей, кнопками лайк/дизлайк, сохранение истории и компакция |
| 🎤 **Голосовые сообщения** | Распознавание речи через Whisper, дальше как текст |
| 🧠 **Память** | Факты/предпочтения/заметки. Auto-extract после каждого ответа, сжатие длинных записей через LLM |
| 📚 **База знаний (FTS5)** | Полнотекстовый поиск по твоей памяти. «Что я говорил про X» — мгновенно, без LLM. Если пусто — fallback в интернет |
| 📝 **Заметки** | Сохранение личных заметок в профиле пользователя |
| ⏰ **Напоминания** | Разовые и периодические: ежедневно, по будням, выходным, дням недели, ежемесячно |
| 🤖 **AI-задачи** | Напоминания, которые AI выполняет в указанное время (погода в городе, поиск в интернете) |
| 🔍 **Веб-поиск** | Поиск + загрузка страниц через Ollama Web API |
| 🌤 **Погода** | wttr.in + Open-Meteo fallback, в твоей таймзоне |
| 📰 **Новости** | По теме («ИИ», «Tesla») или общий топ |
| 🔎 **Мониторинг сайтов** | Проверка URL с алертами в Telegram, состояние alert переживает рестарт |
| 📄 **Файлы** | Извлечение текста из PDF, DOCX, XLSX, CSV, TXT, JSON, MD и других |
| 🌍 **Локализация** | Бот спрашивает имя и страну при первом запуске, всё время — в твоей таймзоне |
| ✏️ **Редактирование** | Редактируй текст или время напоминаний/задач прямо в Telegram |

---

## 🚀 Быстрая установка

### 1. Один командой (рекомендуется)

```bash
curl -sSL https://raw.githubusercontent.com/mmovsesyan/ollama__telegram_bot/main/install.sh | bash
```

Скрипт автоматически:
- проверит/установит **Python 3.10+**, **git**, **ffmpeg**, **Poetry**;
- установит Python-зависимости;
- предзагрузит Whisper-модель;
- интерактивно создаст `.env` с нужными ключами.

На Linux для системных пакетов потребуется **sudo** — скрипт спросит разрешение.  
На macOS используется Homebrew (обычно без sudo).

### 2. Полностью автоматически (для серверов / CI)

```bash
export TELEGRAM_TOKEN="123456:ABC..."
export OLLAMA_API_KEY="your_ollama_key"
export OLLAMA_BOT_MODEL="kimi-k2.7-code:cloud"
export OLLAMA_API_HOST="https://api.ollama.com"

curl -sSL https://raw.githubusercontent.com/mmovsesyan/ollama__telegram_bot/main/install_auto.sh | bash
```

Для бесшумного режима без вопросов:

```bash
AUTO_INSTALL=1 curl -sSL https://raw.githubusercontent.com/mmovsesyan/ollama__telegram_bot/main/install_auto.sh | bash
```

### 3. Вручную (если уже есть git)

```bash
git clone https://github.com/mmovsesyan/ollama__telegram_bot.git
cd ollama__telegram_bot
./scripts/install_deps.sh
./run.sh env
./run.sh start
```

---

## 🖥 Поддерживаемые платформы

- **macOS** 11+ (Intel и Apple Silicon)
- **Linux**:
  - Ubuntu / Debian / Pop!_OS / Linux Mint / Zorin OS / elementary OS
  - Fedora / RHEL / CentOS / Rocky Linux / AlmaLinux / Nobara
  - Arch Linux / Manjaro / EndeavourOS / Garuda
- **Windows** — через **WSL2** или Git Bash

---

## 🎛 Управление ботом

```bash
./run.sh start      # запуск (создаст .env при первом запуске)
./run.sh stop       # остановка
./run.sh restart    # перезапуск
./run.sh status     # статус
./run.sh logs       # смотреть лог в реальном времени
./run.sh env        # пересоздать .env
./run.sh deps       # установить/обновить зависимости
```

Автоматическое обновление:

```bash
./update.sh         # git pull + обновление зависимостей + restart
```

Системный сервис и автообновление по cron:

```bash
./install_service.sh
```

---

## 📋 Как общаться с ботом

При первом `/start` бот спросит имя и страну — это нужно чтобы напоминания срабатывали в твоей таймзоне.

Дальше просто пиши или говори голосом:

- «погода в Москве»
- «погода в Санкт-Петербурге»
- «напомни через 5 минут позвонить»
- «завтра в 9:00 проверить отчёт»
- «каждое утро в 9 покажи новости» (это задача — AI выполнит)
- «запомни, я люблю краткие ответы»
- «заметка: купить акции TSLA»
- «поищи последние новости Tesla»
- «новости про ИИ»
- «что я говорил про Tesla?» — поищет в твоей базе, если пусто — в интернете
- «следи за google.com»

> 💡 Голосовое сообщение распознаётся через Whisper и идёт по тому же маршруту что и текст.

> ⚡ Очевидные команды (напомни, погода, поищи) обрабатываются мгновенно через regex, без LLM. Сложные — идут в LLM-роутер с таймаутом 15 сек.

### Команды бота

| Команда | Описание |
|---------|----------|
| `/start` | Онбординг (имя + таймзона) или возврат в меню |
| `/help` | Полная справка с примерами |
| `/remind` | Добавить напоминание (пошагово) |
| `/reminders` | Список напоминаний и задач с кнопками редактирования и удаления |
| `/task` | Добавить AI-задачу (пошагово) |
| `/memory` | Меню памяти (факты, предпочтения, заметки) |
| `/memory_add` | Добавить запись в память |
| `/note` | Сохранить заметку |
| `/kb <запрос>` | Поиск в твоей базе знаний (с fallback на интернет) |
| `/search <запрос>` | Поиск только в интернете |
| `/weather <город>` | Погода |
| `/news <тема>` | Новости по теме (без темы — общий топ) |
| `/monitor_add` | Добавить монитор сайта |
| `/monitors` | Список мониторов |
| `/models` | Список моделей |
| `/model <name>` | Сменить модель |
| `/clear` | Очистить историю чата |
| `/report` | Ежедневный отчёт |

---

## ⚙️ Настройка `.env`

```env
# Telegram Bot Token от @BotFather
TELEGRAM_TOKEN=123456:ABC...

# Опционально: разрешённые Telegram ID через запятую
ALLOWED_CHAT_IDS=

# Ollama Cloud (по умолчанию) или локальная Ollama
OLLAMA_API_HOST=https://api.ollama.com
OLLAMA_BOT_MODEL=kimi-k2.7-code:cloud
OLLAMA_API_KEY=your_ollama_api_key

# Web search API key (если пусто, используется OLLAMA_API_KEY)
OLLAMA_WEB_API_KEY=your_ollama_web_key

# Whisper: модель и параметры
WHISPER_MODEL=tiny         # tiny, base, small, medium, large-v3, turbo
WHISPER_DEVICE=auto        # cpu, cuda, auto
WHISPER_COMPUTE_TYPE=default # int8, float16, default
```

---

## 🏗 Архитектура

```
main.py
├── bot/__init__.py             # Инициализация, роутеры, APScheduler
├── bot/bot.py                  # aiogram Bot + Dispatcher
├── bot/security.py             # ALLOWED_CHAT_IDS allow-list
├── bot/settings.py             # Конфигурация из env
├── bot/db.py                   # SQLite: сессии, сообщения, напоминания, мониторы,
│                                 память + FTS5 индекс, миграции
├── bot/states.py               # FSM-состояния
├── bot/routers/
│   ├── start.py                # /start + онбординг (имя, таймзона)
│   ├── completion.py           # AI-чат, файлы, голос, generate()
│   └── cron.py                 # Напоминания, задачи, мониторы, погода, поиск,
│                                 новости, база знаний, FSM-обработчики кнопок
├── bot/handlers/smart.py       # Free-form roтер: regex fast-path → LLM → tool
├── bot/intent/                 # LLM-driven intent dispatch
│   ├── router.py               # LLMIntentRouter с regex fallback
│   ├── executor.py             # Validation + dispatch + clarification
│   ├── schemas.py              # IntentArgs, IntentResult, ToolContext
│   ├── validator.py            # Confidence threshold + required args
│   └── tools/                  # 11 тулов: chat, remind, task, weather,
│                                 search, news, note, memory, monitor, plan,
│                                 kb_search
├── bot/services/
│   ├── reminders.py            # Парсинг времени с поддержкой таймзон
│   ├── weather.py              # wttr.in + Open-Meteo
│   ├── kb.py                   # KB-first поиск с web fallback
│   ├── kb_extract.py           # Auto-extract фактов + LLM-сжатие
│   └── profile.py              # Таймзоны, локализация, IANA mapping
├── bot/ollama/api.py           # Ollama API client + OpenAI fallback
├── bot/tasks_exec.py           # «Умное» выполнение задач (погода и др.)
├── bot/keyboards/              # Reply + inline клавиатуры
└── tests/                      # 140 тестов: roтер, тулы, KB, миграции
```

---

## 🛡 Безопасность

- `.env`, логи и база данных исключены из git (`.gitignore`).
- История git была очищена от секретов.
- `ALLOWED_CHAT_IDS` ограничивает доступ к боту.
- Никогда не коммитьте реальные токены и ключи.

---

## 📄 Лицензия

MIT
