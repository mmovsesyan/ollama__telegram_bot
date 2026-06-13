#!/usr/bin/env bash
set -euo pipefail

REPO_URL="https://github.com/mmovsesyan/ollama__telegram_bot.git"
INSTALL_DIR="${1:-ollama__telegram_bot}"

TELEGRAM_TOKEN="${TELEGRAM_TOKEN:-}"
OLLAMA_API_KEY="${OLLAMA_API_KEY:-}"
OLLAMA_BOT_MODEL="${OLLAMA_BOT_MODEL:-kimi-k2.7-code:cloud}"
OLLAMA_API_HOST="${OLLAMA_API_HOST:-https://api.ollama.com}"
ALLOWED_CHAT_IDS="${ALLOWED_CHAT_IDS:-}"

if [[ -z "$TELEGRAM_TOKEN" ]]; then
    echo "❌ Set TELEGRAM_TOKEN env variable before running install_auto.sh"
    exit 1
fi
if [[ -z "$OLLAMA_API_KEY" ]]; then
    echo "❌ Set OLLAMA_API_KEY env variable before running install_auto.sh"
    exit 1
fi

echo "📦 Cloning $REPO_URL into $INSTALL_DIR..."
git clone "$REPO_URL" "$INSTALL_DIR"
cd "$INSTALL_DIR"

echo "📚 Installing Poetry (if missing)..."
if ! command -v poetry &> /dev/null; then
    curl -sSL https://install.python-poetry.org | python3 -
    export PATH="$HOME/.local/bin:$PATH"
fi

echo "⬇️  Installing dependencies..."
poetry install --no-dev

echo "⚙️  Writing .env automatically..."
cat > .env <<EOF
TELEGRAM_TOKEN=$TELEGRAM_TOKEN
ALLOWED_CHAT_IDS=$ALLOWED_CHAT_IDS
OLLAMA_API_HOST=$OLLAMA_API_HOST
OLLAMA_BOT_MODEL=$OLLAMA_BOT_MODEL
OLLAMA_API_KEY=$OLLAMA_API_KEY
OLLAMA_WEB_API_KEY=$OLLAMA_API_KEY
EOF

echo ""
echo "✅ Installation complete."
echo "   Directory: $(pwd)"
echo "   Start bot: poetry run python main.py"
