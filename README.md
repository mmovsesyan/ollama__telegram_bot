# Ollama Telegram Bot

Telegram-бот на базе Ollama (Cloud или локальной) с долгосрочной памятью, напоминаниями, веб-поиском и мониторингом сайтов.

## Возможности

- 💬 **AI-чат** с контекстом, сменой моделей и кнопками лайк/дизлайк
- 🧠 **Память**: автоматическое извлечение фактов, предпочтений, задач и решений
- 📝 **Заметки** в пользовательском профиле
- ⏰ **Напоминания** разовые и периодические (ежедневно, по будням, в выходные, по дням недели)
- 🤖 **AI-задачи**: напоминания, которые выполняются через LLM или реальные API (погода и др.)
- 🔍 **Веб-поиск** и загрузка страниц через Ollama Web API
- 🌤 **Погода** (wttr.in + Open-Meteo fallback)
- 📰 **Новости** через веб-поиск
- 🔎 **Мониторинг сайтов** с алертами в Telegram
- 🗑 **Очистка истории** и управление сессиями

## Быстрая установка

### Интерактивно (рекомендуется)

```bash
curl -sSL https://raw.githubusercontent.com/mmovsesyan/ollama__telegram_bot/main/install.sh | bash
```

Скрипт клонирует репозиторий, установит зависимости и проведёт по шагам настройки `.env`.

### Автоматически

```bash
export TELEGRAM_TOKEN="123456:ABC..."
export OLLAMA_API_KEY="your_ollama_key"
export OLLAMA_BOT_MODEL="kimi-k2.7-code:cloud"
export OLLAMA_API_HOST="https://api.ollama.com"

curl -sSL https://raw.githubusercontent.com/mmovsesyan/ollama__telegram_bot/main/install_auto.sh | bash
```

### Вручную

```bash
git clone https://github.com/mmovsesyan/ollama__telegram_bot.git
cd ollama__telegram_bot
poetry install --no-dev
cp .env.example .env
# отредактируй .env
poetry run python main.py
```

## Управление ботом

После установки используйте `./run.sh`:

```bash
./run.sh start      # запуск (спросит ключи при первом старте)
./run.sh stop       # остановка
./run.sh restart    # перезапуск
./run.sh status     # статус
./run.sh logs       # смотреть лог в реальном времени
./run.sh env        # пересоздать .env
```

## Автоматическое обновление

```bash
./update.sh         # git pull + обновление зависимостей + restart
```

Для автообновления по расписанию:

```bash
./install_service.sh
```

Скрипт интерактивно предложит:
- установить systemd service (Linux) или launchd agent (macOS)
- настроить cron на автообновление раз в час

## Настройка `.env`

```env
TELEGRAM_TOKEN=123456:ABC...
ALLOWED_CHAT_IDS=          # опционально: разрешённые Telegram ID через запятую
OLLAMA_API_HOST=https://api.ollama.com
OLLAMA_BOT_MODEL=kimi-k2.7-code:cloud
OLLAMA_API_KEY=your_ollama_api_key
OLLAMA_WEB_API_KEY=your_ollama_web_key  # если пусто, используется OLLAMA_API_KEY
```

## Команды бота

| Команда | Описание |
|---------|----------|
| `/start` | Приветствие и меню |
| `/models` | Список доступных моделей |
| `/model <name>` | Сменить модель |
| `/clear` | Очистить историю чата |
| `/note <текст>` | Сохранить заметку |
| `/memory` | Показать сохранённые факты |
| `/memory_add [category] <текст>` | Добавить факт |
| `/remind <время> <текст>` | Добавить напоминание |
| `/reminders` | Список напоминаний |
| `/remind_cancel <id>` | Отменить напоминание |
| `/monitor_add <name> <url> [интервал]` | Мониторинг сайта |
| `/monitors` | Список мониторов |
| `/search <запрос>` | Поиск в интернете |
| `/fetch <url>` | Загрузить страницу |
| `/weather <город>` | Погода |
| `/news` | Актуальные новости |
| `/report` | Ежедневный отчёт |
| `/help` | Справка |

## Требования

- Python 3.10+
- [Poetry](https://python-poetry.org/)
- Аккаунт/ключ Ollama Cloud (или локальная Ollama)
- Telegram Bot Token от [@BotFather](https://t.me/BotFather)

## Архитектура

```
main.py
├── bot/__init__.py      # инициализация, роутеры, планировщик
├── bot/bot.py           # экземпляр aiogram Bot + Dispatcher
├── bot/settings.py      # конфигурация из env
├── bot/db.py            # SQLite: сообщения, сессии, напоминания, мониторы, память
├── bot/routers/
│   ├── start.py         # /start
│   ├── completion.py    # AI-чат, обработка сообщений, файлов
│   └── cron.py          # reminders, monitors, weather, search, news
├── bot/ollama/api.py    # клиент Ollama API
├── bot/tasks_exec.py    # "умное" выполнение задач (погода и др.)
└── bot/keyboards/       # reply и inline клавиатуры
```

## Безопасность

- `.env`, логи и база данных исключены из git (`.gitignore`).
- `ALLOWED_CHAT_IDS` ограничивает доступ к боту.
- Никогда не коммитьте реальные токены и ключи.

## Лицензия

MIT
