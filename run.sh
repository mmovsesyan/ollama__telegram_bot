#!/usr/bin/env bash
set -euo pipefail

APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENV_FILE="$APP_DIR/.env"
PID_FILE="$APP_DIR/bot.pid"
LOG_FILE="$APP_DIR/bot.log"

cd "$APP_DIR"

# shellcheck source=scripts/install_utils.sh
source "$APP_DIR/scripts/install_utils.sh"

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
    # Always try to kill ANY python instance running this project's main.py.
    # The pidfile alone is unreliable: nohup'd `poetry run` writes the
    # wrapper's PID, not the python child's, so killing the wrapper leaves
    # the bot alive. Match the absolute main.py path to avoid touching
    # other python processes.
    if [[ -f "$PID_FILE" ]]; then
        old_pid=$(cat "$PID_FILE" 2>/dev/null || true)
        if [[ -n "$old_pid" ]] && kill -0 "$old_pid" 2>/dev/null; then
            echo "🛑 Останавливаю предыдущий процесс бота (PID $old_pid)..."
            kill "$old_pid" 2>/dev/null || true
        fi
        rm -f "$PID_FILE"
    fi

    # Catch the actual python child the wrapper spawned.
    if [[ -f "$APP_DIR/main.py" ]]; then
        local stragglers
        stragglers=$(pgrep -f "python.*$APP_DIR/main.py" 2>/dev/null || true)
        if [[ -n "$stragglers" ]]; then
            echo "🛑 Найдены ещё живые Python-процессы бота: $stragglers"
            echo "$stragglers" | xargs -r kill 2>/dev/null || true
            sleep 2
            stragglers=$(pgrep -f "python.*$APP_DIR/main.py" 2>/dev/null || true)
            if [[ -n "$stragglers" ]]; then
                echo "🛑 Не сдаются, шлю SIGKILL: $stragglers"
                echo "$stragglers" | xargs -r kill -9 2>/dev/null || true
            fi
        fi
    fi
}

start_bot() {
    ensure_poetry

    if ! ensure_ffmpeg; then
        _warn "Голосовые сообщения будут недоступны без ffmpeg."
    fi

    echo "⬇️  Устанавливаю / обновляю зависимости..."
    poetry install --without dev

    ensure_env
    stop_existing

    echo "🚀 Запускаю бота..."
    # Use exec inside the subshell so the python process REPLACES the
    # shell wrapper. $! then points at python directly, and kill <pid>
    # actually stops the bot.
    nohup bash -c "exec poetry run python '$APP_DIR/main.py'" >> "$LOG_FILE" 2>&1 &
    BOT_PID=$!
    # Give the wrapper a moment to exec into python so the recorded PID
    # is the real one even if the user inspects it immediately.
    sleep 1
    # If exec did its job, $BOT_PID is python. If for some reason there's
    # still a poetry wrapper around, find the python child under it.
    if ! ps -p "$BOT_PID" -o cmd= 2>/dev/null | grep -q "main.py"; then
        child_pid=$(pgrep -P "$BOT_PID" -f "python.*main.py" 2>/dev/null | head -1 || true)
        if [[ -n "$child_pid" ]]; then
            BOT_PID="$child_pid"
        fi
    fi
    echo "$BOT_PID" > "$PID_FILE"
    echo "✅ Бот запущен. PID: $BOT_PID"
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
    deps)
        ensure_python
        ensure_ffmpeg
        ensure_poetry
        poetry_install_deps
        warmup_whisper
        ;;
    *)
        echo "Использование: $0 {start|stop|restart|status|logs|env|deps}"
        exit 1
        ;;
esac
