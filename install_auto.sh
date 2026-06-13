#!/usr/bin/env bash
set -euo pipefail

REPO_URL="https://github.com/mmovsesyan/ollama__telegram_bot.git"
INSTALL_DIR="${1:-ollama__telegram_bot}"

TELEGRAM_TOKEN="${TELEGRAM_TOKEN:-}"
OLLAMA_API_KEY="${OLLAMA_API_KEY:-}"
OLLAMA_BOT_MODEL="${OLLAMA_BOT_MODEL:-kimi-k2.7-code:cloud}"
OLLAMA_API_HOST="${OLLAMA_API_HOST:-https://api.ollama.com}"
ALLOWED_CHAT_IDS="${ALLOWED_CHAT_IDS:-}"

ensure_git_minimal() {
    if ! command -v git &> /dev/null; then
        echo "❌ git не найден. Установи git вручную или запусти install_auto.sh на системе с git."
        exit 1
    fi
}

ensure_git_minimal

echo "📦 Cloning $REPO_URL into $INSTALL_DIR..."
git clone "$REPO_URL" "$INSTALL_DIR"
cd "$INSTALL_DIR"

# shellcheck source=scripts/install_utils.sh
source "scripts/install_utils.sh"

_print "🚀 Универсальная автоматическая установка Ollama Telegram Bot"
_print "Платформа: $(uname -s) ($(detect_os))"

ensure_python
ensure_ffmpeg
ensure_poetry
poetry_install_deps
warmup_whisper

if [[ -z "$TELEGRAM_TOKEN" || -z "$OLLAMA_API_KEY" ]]; then
    echo "⚠️  Required env variables not set. Switching to interactive setup..."
    poetry run python setup_env.py
else
    echo "⚙️  Writing .env automatically..."
    cat > .env <<EOF
TELEGRAM_TOKEN=$TELEGRAM_TOKEN
ALLOWED_CHAT_IDS=$ALLOWED_CHAT_IDS
OLLAMA_API_HOST=$OLLAMA_API_HOST
OLLAMA_BOT_MODEL=$OLLAMA_BOT_MODEL
OLLAMA_API_KEY=$OLLAMA_API_KEY
OLLAMA_WEB_API_KEY=$OLLAMA_API_KEY
WHISPER_MODEL=tiny
WHISPER_DEVICE=auto
WHISPER_COMPUTE_TYPE=default
EOF
fi

echo ""
echo "✅ Installation complete."
echo "   Directory: $(pwd)"
echo "   Start bot: ./run.sh start"
