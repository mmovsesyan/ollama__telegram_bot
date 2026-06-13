#!/usr/bin/env bash
# Shared helpers for installing system and Python dependencies.
# This file is meant to be sourced, not executed directly.

set -euo pipefail

: "${AUTO_INSTALL:=0}"
: "${CI:=0}"

_SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
_APP_DIR="$(cd "$_SCRIPT_DIR/.." && pwd)"

# Colors for output
_RED='\033[0;31m'
_GREEN='\033[0;32m'
_YELLOW='\033[1;33m'
_BLUE='\033[0;34m'
_NC='\033[0m' # No Color

_print() {
    echo -e "${_GREEN}[install]${_NC} $*"
}

_warn() {
    echo -e "${_YELLOW}[warn]${_NC} $*"
}

_error() {
    echo -e "${_RED}[error]${_NC} $*"
}

_info() {
    echo -e "${_BLUE}[info]${_NC} $*"
}

# Ask the user for confirmation before running a command with sudo.
# Usage: _confirm_sudo "description" "command" [args...]
_confirm_sudo() {
    local desc="$1"
    shift
    if [[ "$AUTO_INSTALL" == "1" || "$CI" == "1" ]]; then
        _print "$desc"
        sudo "$@"
        return
    fi
    read -rp "🔐 $desc Требуется sudo. Разрешить? [y/N]: " answer
    if [[ "${answer:-}" =~ ^[Yy]$ ]]; then
        sudo "$@"
    else
        _warn "Установка отменена пользователем."
        return 1
    fi
}

detect_os() {
    local uname_s
    uname_s="$(uname -s)"
    if [[ "$uname_s" == "Darwin" ]]; then
        echo "macos"
        return
    fi
    if [[ "$uname_s" == "Linux" ]]; then
        if [[ -f /etc/os-release ]]; then
            # shellcheck source=/dev/null
            . /etc/os-release
            case "$ID" in
                ubuntu|debian|pop|mint|elementary|zorin)
                    echo "debian"
                    return
                    ;;
                fedora|rhel|centos|rocky|almalinux|nobara)
                    echo "fedora"
                    return
                    ;;
                arch|manjaro|endeavouros|garuda)
                    echo "arch"
                    return
                    ;;
            esac
            # Check ID_LIKE as fallback
            case "${ID_LIKE:-}" in
                *debian*|*ubuntu*)
                    echo "debian"
                    return
                    ;;
                *fedora*|*rhel*|*centos*)
                    echo "fedora"
                    return
                    ;;
                *arch*)
                    echo "arch"
                    return
                    ;;
            esac
        fi
    fi
    echo "unknown"
}

ensure_command() {
    local cmd="$1"
    local install_cmd="$2"
    local desc="${3:-$cmd}"

    if command -v "$cmd" &> /dev/null; then
        return 0
    fi

    _warn "$desc не найден. Пробую установить..."
    if [[ "$install_cmd" == sudo* ]]; then
        # install_cmd starts with 'sudo ...' — split and run through _confirm_sudo
        local args
        read -r -a args <<< "$install_cmd"
        _confirm_sudo "Установка $desc" "${args[@]:1}"
    else
        eval "$install_cmd"
    fi
}

ensure_homebrew() {
    if command -v brew &> /dev/null; then
        return 0
    fi
    _warn "Homebrew не найден. Установка Homebrew..."
    /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)" || {
        _error "Не удалось установить Homebrew. Установи вручную: https://brew.sh"
        return 1
    }
    # Try to add to PATH for this session
    if [[ -d /opt/homebrew/bin ]]; then
        export PATH="/opt/homebrew/bin:$PATH"
    elif [[ -d /usr/local/bin ]]; then
        export PATH="/usr/local/bin:$PATH"
    fi
}

_python_version_ok() {
    local py="$1"
    if ! command -v "$py" &> /dev/null; then
        return 1
    fi
    local version
    version="$($py --version 2>&1 | awk '{print $2}')"
    local major minor
    major="$(echo "$version" | cut -d. -f1)"
    minor="$(echo "$version" | cut -d. -f2)"
    if [[ "$major" -gt 3 ]] || { [[ "$major" == 3 ]] && [[ "$minor" -ge 10 ]]; }; then
        return 0
    fi
    return 1
}

ensure_python() {
    if _python_version_ok python3; then
        _info "Python OK: $(python3 --version 2>&1 | awk '{print $2}')"
        return 0
    fi

    _warn "Требуется Python 3.10+. Пробую установить..."
    local os_type
    os_type="$(detect_os)"

    case "$os_type" in
        macos)
            ensure_homebrew
            _confirm_sudo "Установка Python 3.12" brew install python@3.12 || true
            # Prefer python3.12 if available
            if command -v python3.12 &> /dev/null; then
                export PYTHON_BIN=python3.12
            fi
            ;;
        debian)
            _confirm_sudo "Установка Python 3" apt-get update
            _confirm_sudo "Установка Python 3.11" apt-get install -y python3 python3-pip python3.11 || \
                _confirm_sudo "Установка Python 3" apt-get install -y python3 python3-pip
            ;;
        fedora)
            _confirm_sudo "Установка Python 3" dnf install -y python3 python3-pip || \
                _confirm_sudo "Установка Python 3" yum install -y python3 python3-pip
            ;;
        arch)
            _confirm_sudo "Установка Python 3" pacman -Syu --noconfirm python python-pip
            ;;
        *)
            _error "Не удалось определить дистрибутив Linux. Установи Python 3.10+ вручную."
            return 1
            ;;
    esac

    if _python_version_ok python3; then
        _info "Python OK: $(python3 --version 2>&1 | awk '{print $2}')"
        return 0
    fi
    if _python_version_ok python3.12; then
        _info "Python OK: $(python3.12 --version 2>&1 | awk '{print $2}')"
        export PYTHON_BIN=python3.12
        return 0
    fi
    if _python_version_ok python3.11; then
        _info "Python OK: $(python3.11 --version 2>&1 | awk '{print $2}')"
        export PYTHON_BIN=python3.11
        return 0
    fi

    _error "Python 3.10+ всё ещё не доступен. Установи вручную."
    return 1
}

ensure_git() {
    if command -v git &> /dev/null; then
        return 0
    fi
    local os_type
    os_type="$(detect_os)"
    _warn "git не найден. Пробую установить..."
    case "$os_type" in
        macos)
            ensure_homebrew
            _confirm_sudo "Установка git" brew install git
            ;;
        debian)
            _confirm_sudo "Установка git" apt-get update
            _confirm_sudo "Установка git" apt-get install -y git
            ;;
        fedora)
            _confirm_sudo "Установка git" dnf install -y git
            ;;
        arch)
            _confirm_sudo "Установка git" pacman -Syu --noconfirm git
            ;;
        *)
            _error "Не удалось установить git. Установи вручную."
            return 1
            ;;
    esac
}

ensure_ffmpeg() {
    if command -v ffmpeg &> /dev/null; then
        _info "ffmpeg OK: $(ffmpeg -version 2>&1 | head -1)"
        return 0
    fi

    local os_type
    os_type="$(detect_os)"
    _warn "ffmpeg не найден. Он нужен для распознавания голосовых сообщений. Пробую установить..."

    case "$os_type" in
        macos)
            ensure_homebrew
            _confirm_sudo "Установка ffmpeg" brew install ffmpeg
            ;;
        debian)
            _confirm_sudo "Установка ffmpeg" apt-get update
            _confirm_sudo "Установка ffmpeg" apt-get install -y ffmpeg
            ;;
        fedora)
            _confirm_sudo "Установка ffmpeg" dnf install -y ffmpeg
            ;;
        arch)
            _confirm_sudo "Установка ffmpeg" pacman -Syu --noconfirm ffmpeg
            ;;
        *)
            _error "Не удалось определить ОС для автоустановки ffmpeg."
            _error "macOS: brew install ffmpeg"
            _error "Ubuntu/Debian: sudo apt install ffmpeg"
            _error "Fedora: sudo dnf install ffmpeg"
            _error "Arch: sudo pacman -S ffmpeg"
            return 1
            ;;
    esac

    if command -v ffmpeg &> /dev/null; then
        _info "ffmpeg установлен: $(ffmpeg -version 2>&1 | head -1)"
        return 0
    fi
    _error "ffmpeg всё ещё не найден после попытки установки."
    return 1
}

ensure_poetry() {
    if command -v poetry &> /dev/null; then
        _info "Poetry OK: $(poetry --version 2>&1)"
        return 0
    fi
    _warn "Poetry не найден. Устанавливаю..."
    curl -sSL https://install.python-poetry.org | "${PYTHON_BIN:-python3}" -
    export PATH="$HOME/.local/bin:$PATH"
    if ! command -v poetry &> /dev/null; then
        _error "Poetry не удалось установить. Проверь ~/.local/bin."
        return 1
    fi
    _info "Poetry OK: $(poetry --version 2>&1)"
}

poetry_install_deps() {
    _print "Установка Python-зависимостей..."
    export PATH="$HOME/.local/bin:$PATH"
    poetry install --without dev
}

warmup_whisper() {
    _print "Предзагрузка Whisper модели (первая загрузка ~39 МБ)..."
    export PATH="$HOME/.local/bin:$PATH"
    poetry run python3 "$_SCRIPT_DIR/warmup_whisper.py" || {
        _warn "Не удалось предзагрузить Whisper модель. Пропускаю — загрузится при первом голосовом сообщении."
        return 0
    }
    _info "Whisper модель готова."
}
