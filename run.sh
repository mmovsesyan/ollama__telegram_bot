#!/usr/bin/env bash
set -euo pipefail

APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENV_FILE="$APP_DIR/.env"
PID_FILE="$APP_DIR/bot.pid"
LOG_FILE="$APP_DIR/bot.log"

cd "$APP_DIR"

ensure_poetry() {
    if ! command -v poetry &> /dev/null; then
        echo "📚 Poetry не найден. Устанавливаю..."
        curl -sSL https://install.python-poetry.org | python3 -
        export PATH="$HOME/.local/bin:$PATH"
    fi
}

env_is_valid() {
    if [[ ! -f "$ENV_FILE" ]]; then
        return 1
    fi
    # Check that required keys are present, not placeholder and token is valid
    local token api_key
    token=$(grep "^TELEGRAM_TOKEN=" "$ENV_FILE" | cut -d'=' -f2- | tr -d '[:space:]')
    api_key=$(grep "^OLLAMA_API_KEY=" "$ENV_FILE" | cut -d'=' -f2- | tr -d '[:space:]')

    if [[ -z "$token" || -z "$api_key" ]]; then
        return 1
    fi
    if [[ "$token" == *"your_telegram_bot_token_here"* || "$api_key" == *"your_ollama_api_key_here"* ]]; then
        return 1
    fi
    if ! [[ "$token" =~ ^[0-9]+:[A-Za-z0-9_-]+$ ]]; then
        return 1
    fi
    return 0
}

ensure_env() {
    if env_is_valid; then
        return 0
    fi

    if [[ -f "$ENV_FILE" ]]; then
        echo "⚠️  .env найден, но отсутствуют или некорректны обязательные ключи."
        echo "   Пересоздаю .env интерактивно..."
    else
        echo "⚙️  .env не найден. Создаю интерактивно..."
    fi
    poetry run python setup_env.py
}

stop_existing() {
    if [[ -f "$PID_FILE" ]]; then
        old_pid=$(cat "$PID_FILE" 2>/dev/null || true)
        if [[ -n "$old_pid" ]] && kill -0 "$old_pid" 2>/dev/null; then
            echo "🛑 Останавливаю предыдущий процесс бота (PID $old_pid)..."
            kill "$old_pid" || true
            sleep 2
            if kill -0 "$old_pid" 2>/dev/null; then
                kill -9 "$old_pid" || true
            fi
        fi
        rm -f "$PID_FILE"
    fi

    # Fallback: kill any other bot instance matching our exact main.py path
    if [[ -f "$APP_DIR/main.py" ]]; then
        pkill -f "python.*$APP_DIR/main.py" 2>/dev/null || true
    fi
}

start_bot() {
    ensure_poetry

    if ! command -v ffmpeg &> /dev/null; then
        echo "⚠️  ffmpeg не найден. Голосовые сообщения не будут распознаваться."
        echo "   macOS: brew install ffmpeg"
        echo "   Linux: sudo apt install ffmpeg"
    fi

    echo "⬇️  Устанавливаю / обновляю зависимости..."
    poetry install --without dev

    ensure_env
    stop_existing

    echo "🚀 Запускаю бота..."
    nohup poetry run python "$APP_DIR/main.py" >> "$LOG_FILE" 2>&1 &
    echo $! > "$PID_FILE"
    echo "✅ Бот запущен. PID: $(cat "$PID_FILE")"
    echo "   Лог: tail -f $LOG_FILE"
}

status_bot() {
    if [[ -f "$PID_FILE" ]]; then
        pid=$(cat "$PID_FILE" 2>/dev/null || true)
        if [[ -n "$pid" ]] && kill -0 "$pid" 2>/dev/null; then
            echo "✅ Бот работает (PID $pid)"
        else
            echo "⚠️  PID-файл есть, но процесс не запущен"
        fi
    else
        echo "❌ Бот не запущен"
    fi
}

case "${1:-start}" in
    start)
        start_bot
        ;;
    stop)
        stop_existing
        echo "🛑 Бот остановлен"
        ;;
    restart)
        start_bot
        ;;
    status)
        status_bot
        ;;
    logs)
        exec tail -f "$LOG_FILE"
        ;;
    env)
        ensure_poetry
        ensure_env
        ;;
    *)
        echo "Использование: $0 {start|stop|restart|status|logs|env}"
        exit 1
        ;;
esac
