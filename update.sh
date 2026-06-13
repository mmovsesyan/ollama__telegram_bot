#!/usr/bin/env bash
set -euo pipefail

APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PID_FILE="$APP_DIR/bot.pid"
LOG_FILE="$APP_DIR/bot.log"

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

# Restart bot if running
_print "🔄 Перезапуск бота..."
./run.sh restart

_print "✅ Обновление завершено."
