#!/usr/bin/env bash
# Jarvis Kino entfernen. Einstellungen/Anmeldung bleiben, außer mit --alles.
set -euo pipefail
DATEN="${XDG_DATA_HOME:-$HOME/.local/share}/jarvis-kino"
rm -rf "$DATEN/app" "$DATEN/app.neu" "$DATEN/app.alt" "$DATEN/venv"
rm -f "$HOME/.local/bin/jarvis-kino" \
      "${XDG_DATA_HOME:-$HOME/.local/share}/applications/jarvis-kino.desktop" \
      "${XDG_DATA_HOME:-$HOME/.local/share}/icons/hicolor/scalable/apps/jarvis-kino.svg"
if [ "${1:-}" = "--alles" ]; then
    rm -rf "$DATEN" "${XDG_CONFIG_HOME:-$HOME/.config}/jarvis-kino"
    echo "Jarvis Kino samt Einstellungen und Anmeldung entfernt."
else
    echo "Jarvis Kino entfernt (Einstellungen und Anmeldung bleiben für eine Neuinstallation erhalten)."
fi
