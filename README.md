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
| 💬 **AI-чат** | Контекстный диалог со сменой моделей, кнопками лайк/дизлайк |
| 🎤 **Голосовые сообщения** | Распознавание речи через Whisper и AI-ответ на транскрибированный текст |
| 🧠 **Память (OpenClaude-style)** | Автоизвлечение фактов, предпочтений, задач и решений из диалога |
| 📝 **Заметки** | Сохранение личных заметок в профиле пользователя |
| ⏰ **Напоминания** | Разовые и периодические: ежедневно, по будням, выходным, дням недели |
| 🤖 **AI-задачи** | Напоминания, которые выполняет LLM или реальные API (погода и др.) |
| 🔍 **Веб-поиск** | Поиск в интернете и загрузка страниц через Ollama Web API |
| 🌤 **Погода** | wttr.in + Open-Meteo fallback |
| 📰 **Новости** | Актуальные новости через веб-поиск |
| 🔎 **Мониторинг сайтов** | Проверка URL с алертами в Telegram |
| 📄 **Файлы** | Извлечение текста из PDF, DOCX, CSV, TXT, JSON и других |
| 🗑 **Управление сессиями** | Очистка истории, авто-сжатие контекста |

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

Просто напиши или скажи голосом:

- «погода в Москве»
- «напомни через 5 минут позвонить»
- «завтра в 9:00 проверить отчёт»
- «каждое утро в 9 покажи новости»
- «запомни, я люблю краткие ответы»
- «заметка: купить акции TSLA»
- «поищи последние новости Tesla»
- «новости»

> 💡 Отправь **голосовое сообщение** — бот распознает речь через Whisper и ответит так же, как на текст.

### Команды бота

| Команда | Описание |
|---------|----------|
| `/start` | Приветствие и меню |
| `/help` | Примеры и полная справка |
| `/remind` | Добавить напоминание (пошагово) |
| `/reminders` | Список и удаление напоминаний |
| `/memory` | Показать сохранённые факты |
| `/memory_add` | Добавить факт в память (пошагово) |
| `/note` | Сохранить заметку |
| `/search <запрос>` | Поиск в интернете |
| `/weather <город>` | Погода |
| `/news` | Актуальные новости |
| `/monitor_add` | Добавить монитор сайта (пошагово) |
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
├── bot/__init__.py      # инициализация, роутеры, планировщик
├── bot/bot.py           # экземпляр aiogram Bot + Dispatcher
├── bot/settings.py      # конфигурация из env
├── bot/db.py            # SQLite: сообщения, сессии, напоминания, мониторы, память
├── bot/routers/
│   ├── start.py         # /start
│   ├── completion.py    # AI-чат, файлы, голос, обработка сообщений
│   └── cron.py          # reminders, monitors, weather, search, news
├── bot/ollama/api.py    # клиент Ollama API + OpenAI fallback
├── bot/tasks_exec.py    # "умное" выполнение задач (погода и др.)
├── scripts/             # установщики и утилиты
└── bot/keyboards/       # reply и inline клавиатуры
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
