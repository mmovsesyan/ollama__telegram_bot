#!/usr/bin/env bash
set -euo pipefail

REPO_URL="https://github.com/mmovsesyan/ollama__telegram_bot.git"
INSTALL_DIR="${1:-ollama__telegram_bot}"

echo "📦 Cloning $REPO_URL into $INSTALL_DIR..."
git clone "$REPO_URL" "$INSTALL_DIR"
cd "$INSTALL_DIR"

echo "🐍 Checking Python version..."
python3 --version

echo "📚 Installing Poetry (if missing)..."
if ! command -v poetry &> /dev/null; then
    curl -sSL https://install.python-poetry.org | python3 -
    export PATH="$HOME/.local/bin:$PATH"
fi

if ! command -v ffmpeg &> /dev/null; then
    echo "⚠️  ffmpeg не найден. Он нужен для распознавания голосовых сообщений."
    echo "   macOS: brew install ffmpeg"
    echo "   Linux: sudo apt install ffmpeg"
fi

echo "⬇️  Installing dependencies..."
poetry install --without dev

echo "⚙️  Running interactive setup..."
poetry run python setup_env.py

echo ""
echo "✅ Installation complete."
echo "   Directory: $(pwd)"
echo "   Start bot: poetry run python main.py"
