#!/usr/bin/env bash
set -euo pipefail

APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PID_FILE="$APP_DIR/bot.pid"
LOG_FILE="$APP_DIR/bot.log"

cd "$APP_DIR"

echo "🔄 Обновление Ollama Telegram Bot..."

# Pull latest code
echo "⬇️  git pull..."
if ! git pull origin main; then
    echo "❌ Ошибка git pull. Проверьте remote и конфликты."
    exit 1
fi

# Update dependencies
if command -v poetry &> /dev/null; then
    echo "📚 Обновление зависимостей..."
    poetry install --no-dev
fi

# Restart bot if running
echo "🔄 Перезапуск бота..."
./run.sh restart

echo "✅ Обновление завершено."
