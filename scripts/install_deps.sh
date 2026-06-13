#!/usr/bin/env bash
# Standalone dependency installer for already-cloned repo.
# Usage: ./scripts/install_deps.sh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=install_utils.sh
source "$SCRIPT_DIR/install_utils.sh"

_print "Установка системных зависимостей Ollama Telegram Bot"
_print "Платформа: $(uname -s) ($(detect_os))"

ensure_python
ensure_git
ensure_ffmpeg
ensure_poetry
poetry_install_deps
warmup_whisper

_print "✅ Все зависимости установлены."
_info "Дальше создай .env: ./run.sh env"
_info "И запусти бота: ./run.sh start"
