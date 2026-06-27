#!/usr/bin/env bash
set -euo pipefail

APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENV_FILE="$APP_DIR/.env"
PID_FILE="$APP_DIR/bot.pid"
WATCHDOG_PID_FILE="$APP_DIR/watchdog.pid"
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
    # Stop both the watchdog (if started via run.sh) and the bot main process.
    # The supervisor writes the bot's main.py PID to $PID_FILE; run.sh writes
    # the watchdog PID to $WATCHDOG_PID_FILE. We clean up both so that restart
    # does not leave an old watchdog trying to resurrect a killed bot.
    for pid_file in "$WATCHDOG_PID_FILE" "$PID_FILE"; do
        if [[ -f "$pid_file" ]]; then
            old_pid=$(cat "$pid_file" 2>/dev/null || true)
            if [[ -n "$old_pid" ]] && kill -0 "$old_pid" 2>/dev/null; then
                echo "🛑 Останавливаю процесс $pid_file (PID $old_pid)..."
                kill "$old_pid" 2>/dev/null || true
            fi
            rm -f "$pid_file"
        fi
    done

    # Catch any remaining python processes running this project's main.py or
    # watchdog. Match absolute paths to avoid touching unrelated python work.
    for pattern in "python.*$APP_DIR/main.py" "python.*$APP_DIR/scripts/supervisor_watchdog.py"; do
        local stragglers
        stragglers=$(pgrep -f "$pattern" 2>/dev/null || true)
        if [[ -n "$stragglers" ]]; then
            echo "🛑 Найдены живые процессы по '$pattern': $stragglers"
            echo "$stragglers" | xargs -r kill 2>/dev/null || true
            sleep 2
            stragglers=$(pgrep -f "$pattern" 2>/dev/null || true)
            if [[ -n "$stragglers" ]]; then
                echo "🛑 Не сдаются, шлю SIGKILL: $stragglers"
                echo "$stragglers" | xargs -r kill -9 2>/dev/null || true
            fi
        fi
    done
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

    echo "🚀 Запускаю бота через watchdog..."
    # The watchdog is responsible for starting and restarting main.py. We
    # keep its PID separate from the bot PID (written by supervisor.py) so
    # that status checks actually reflect whether the bot is alive.
    nohup bash -c "exec poetry run python '$APP_DIR/scripts/supervisor_watchdog.py'" >> "$LOG_FILE" 2>&1 &
    WATCHDOG_PID=$!
    sleep 1
    # Verify the watchdog is still alive; if not, the log will show why.
    if ! kill -0 "$WATCHDOG_PID" 2>/dev/null; then
        echo "❌ Watchdog не удалось запустить. Смотри $LOG_FILE"
        return 1
    fi
    echo "$WATCHDOG_PID" > "$WATCHDOG_PID_FILE"
    echo "✅ Watchdog запущен. PID: $WATCHDOG_PID"
    echo "   Лог: tail -f $LOG_FILE"
    echo "   Бот будет поднят watchdog'ом в течение нескольких секунд."
}

status_bot() {
    # The bot's main.py PID is written by supervisor.py; the watchdog PID is
    # written by run.sh. We report both so the operator can see the whole
    # picture.
    local bot_pid watchdog_pid
    if [[ -f "$PID_FILE" ]]; then
        bot_pid=$(cat "$PID_FILE" 2>/dev/null || true)
    fi
    if [[ -f "$WATCHDOG_PID_FILE" ]]; then
        watchdog_pid=$(cat "$WATCHDOG_PID_FILE" 2>/dev/null || true)
    fi

    if [[ -n "$bot_pid" ]] && kill -0 "$bot_pid" 2>/dev/null; then
        echo "✅ Бот работает (PID $bot_pid)"
    elif [[ -n "$watchdog_pid" ]] && kill -0 "$watchdog_pid" 2>/dev/null; then
        echo "⏳ Watchdog работает (PID $watchdog_pid), бот поднимается..."
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
    menu)
        ensure_poetry
        exec poetry run python "$APP_DIR/scripts/menu.py"
        ;;
    *)
        echo "Использование: $0 {start|stop|restart|status|logs|env|deps|menu}"
        exit 1
        ;;
esac
