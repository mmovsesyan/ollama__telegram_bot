<div align="center">

# 🤖 Ollama Telegram Bot

**Кроссплатформенный Telegram AI-бот на базе Ollama**

С долгосрочной памятью, напоминаниями, веб-поиском, мониторингом сайтов и распознаванием голоса.

[![Python](https://img.shields.io/badge/python-3.10%2B-blue.svg)](https://www.python.org/)
[![Poetry](https://img.shields.io/badge/poetry-2.x-blueviolet.svg)](https://python-poetry.org/)
[![Ollama](https://img.shields.io/badge/ollama-cloud%20%7C%20local-white.svg)](https://ollama.com/)
[![License](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)

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
| 📄 **Файлы** | Извлечение текста из PDF, DOCX, CSV, TXT, JSON и других |
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
