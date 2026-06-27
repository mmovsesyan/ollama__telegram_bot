#!/usr/bin/env bash
set -euo pipefail

APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PID_FILE="$APP_DIR/bot.pid"
WATCHDOG_PID_FILE="$APP_DIR/watchdog.pid"
LOG_FILE="$APP_DIR/bot.log"

SERVICE_NAME="ollama-telegram-bot"
PLIST_LABEL="local.ollama-telegram-bot"

cd "$APP_DIR"

# shellcheck source=scripts/install_utils.sh
source "$APP_DIR/scripts/install_utils.sh"

# Ensure Poetry is available even when run from cron or a minimal shell
export PATH="$HOME/.local/bin:$PATH"

_print "🔄 Обновление Ollama Telegram Bot..."

# Ensure core dependencies are present before pulling/updating
ensure_poetry
if ! ensure_ffmpeg; then
    _warn "Голосовые сообщения будут недоступны без ffmpeg."
fi

# Pull latest code
_print "⬇️  git pull..."
if ! git pull origin main; then
    _error "Ошибка git pull. Проверь remote и конфликты."
    exit 1
fi

# Update dependencies
_print "📚 Обновление зависимостей..."
poetry install --without dev

# Detect how the bot is currently running and restart it the same way.
# This prevents duplicate watchdog/bot processes when the user mixes
# systemd/launchd with manual ./run.sh invocations.
_restart_bot() {
    local use_systemd=false
    local use_launchd=false
    local use_manual=false

    if command -v systemctl >/dev/null 2>&1; then
        if systemctl is-active --quiet "$SERVICE_NAME" 2>/dev/null; then
            use_systemd=true
        fi
    fi

    if [[ "$OSTYPE" == "darwin"* ]] && command -v launchctl >/dev/null 2>&1; then
        if launchctl list "$PLIST_LABEL" >/dev/null 2>&1; then
            use_launchd=true
        fi
    fi

    if [[ -f "$PID_FILE" ]] || [[ -f "$WATCHDOG_PID_FILE" ]]; then
        local pid
        for pid_file in "$WATCHDOG_PID_FILE" "$PID_FILE"; do
            if [[ -f "$pid_file" ]]; then
                pid=$(cat "$pid_file" 2>/dev/null || true)
                if [[ -n "$pid" ]] && kill -0 "$pid" 2>/dev/null; then
                    use_manual=true
                    break
                fi
            fi
        done
    fi

    # Also catch any stray processes that match this project's main.py or watchdog.
    if pgrep -f "python.*$APP_DIR/main.py" >/dev/null 2>&1 \
        || pgrep -f "python.*$APP_DIR/scripts/supervisor_watchdog.py" >/dev/null 2>&1; then
        use_manual=true
    fi

    if [[ "$use_systemd" == "true" ]]; then
        _print "🔄 Перезапуск через systemd..."
        if command -v sudo >/dev/null 2>&1; then
            sudo systemctl restart "$SERVICE_NAME"
        else
            systemctl restart "$SERVICE_NAME" || true
        fi
        return
    fi

    if [[ "$use_launchd" == "true" ]]; then
        _print "🔄 Перезапуск через launchd..."
        launchctl unload "$HOME/Library/LaunchAgents/${PLIST_LABEL}.plist" 2>/dev/null || true
        launchctl load "$HOME/Library/LaunchAgents/${PLIST_LABEL}.plist" 2>/dev/null || true
        return
    fi

    if [[ "$use_manual" == "true" ]]; then
        _print "🔄 Перезапуск бота (ручной запуск)..."
        ./run.sh restart
        return
    fi

    _print "ℹ️  Бот не был запущен. Запускаю..."
    ./run.sh start
}

_restart_bot

_print "✅ Обновление завершено."
