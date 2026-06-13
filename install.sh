#!/usr/bin/env bash
set -euo pipefail

REPO_URL="https://github.com/mmovsesyan/ollama__telegram_bot.git"
INSTALL_DIR="${1:-ollama__telegram_bot}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# For one-liner curl installs we are not yet inside the repo, so source helpers after cloning.
# We still need a minimal OS check up front for git/python availability.
ensure_git_minimal() {
    if ! command -v git &> /dev/null; then
        echo "❌ git не найден. Установи git вручную или запусти install.sh на системе с git."
        exit 1
    fi
}

ensure_git_minimal

echo "📦 Cloning $REPO_URL into $INSTALL_DIR..."
git clone "$REPO_URL" "$INSTALL_DIR"
cd "$INSTALL_DIR"

# shellcheck source=scripts/install_utils.sh
source "scripts/install_utils.sh"

_print "🚀 Универсальная установка Ollama Telegram Bot"
_print "Платформа: $(uname -s) ($(detect_os))"

ensure_python
ensure_ffmpeg
ensure_poetry
poetry_install_deps
warmup_whisper

echo "⚙️  Running interactive setup..."
poetry run python setup_env.py

echo ""
echo "✅ Installation complete."
echo "   Directory: $(pwd)"
echo "   Start bot: ./run.sh start"
