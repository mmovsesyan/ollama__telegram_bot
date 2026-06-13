#!/usr/bin/env bash
set -euo pipefail

APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
USER_NAME="$(whoami)"

echo "🔧 Установка системного сервиса для Ollama Telegram Bot"
echo "   Платформа: $(uname -s)"
echo "   Пользователь: $USER_NAME"
echo "   Директория: $APP_DIR"

if [[ "$(uname -s)" == "Linux" ]]; then
    echo ""
    read -rp "Установить systemd service? Требуются права root. [y/N]: " install_systemd
    if [[ "${install_systemd:-}" =~ ^[Yy]$ ]]; then
        SERVICE_SRC="$APP_DIR/ollama-telegram-bot.service"
        SERVICE_DST="/etc/systemd/system/ollama-telegram-bot.service"

        sed "s|/opt/ollama__telegram_bot|$APP_DIR|g; s|%I|$USER_NAME|g" "$SERVICE_SRC" | sudo tee "$SERVICE_DST" > /dev/null
        sudo systemctl daemon-reload
        sudo systemctl enable ollama-telegram-bot.service
        echo "✅ Service установлен."
        echo "   Запуск: sudo systemctl start ollama-telegram-bot"
        echo "   Статус: sudo systemctl status ollama-telegram-bot"
        echo "   Логи: sudo journalctl -u ollama-telegram-bot -f"
    fi
elif [[ "$(uname -s)" == "Darwin" ]]; then
    echo ""
    read -rp "Установить launchd agent? [y/N]: " install_launchd
    if [[ "${install_launchd:-}" =~ ^[Yy]$ ]]; then
        PLIST_SRC="$APP_DIR/com.mmovsesyan.ollama-telegram-bot.plist"
        PLIST_DST="$HOME/Library/LaunchAgents/com.mmovsesyan.ollama-telegram-bot.plist"

        sed "s|/Users/%USER%/ollama__telegram_bot|$APP_DIR|g; s|%USER%|$USER_NAME|g" "$PLIST_SRC" > "$PLIST_DST"
        launchctl load "$PLIST_DST" 2>/dev/null || launchctl bootstrap gui/$(id -u) "$PLIST_DST"
        echo "✅ LaunchAgent установлен."
        echo "   Старт: launchctl start com.mmovsesyan.ollama-telegram-bot"
        echo "   Стоп: launchctl stop com.mmovsesyan.ollama-telegram-bot"
    fi
else
    echo "❌ Неподдерживаемая платформа. Используйте ./run.sh start"
    exit 1
fi

echo ""
read -rp "Настроить автообновление через cron (раз в час)? [y/N]: " setup_cron
if [[ "${setup_cron:-}" =~ ^[Yy]$ ]]; then
    CRON_LINE="0 * * * * cd $APP_DIR && ./update.sh >> $APP_DIR/update.log 2>&1"
    (crontab -l 2>/dev/null || true) | grep -v "$APP_DIR/update.sh" | cat - <(echo "$CRON_LINE") | crontab -
    echo "✅ Cron настроен: $CRON_LINE"
fi

echo ""
echo "🎉 Готово."
