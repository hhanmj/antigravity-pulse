#!/usr/bin/env bash
set -e

echo "========================================================"
echo "  Antigravity Pulse v3.0 — One-Click Installer"
echo "========================================================"

TARGET_DIR="$HOME/.gemini/config/plugins/context-monitor"
SRC_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

if [ "$SRC_DIR" != "$TARGET_DIR" ]; then
    echo "[*] Installing plugin to $TARGET_DIR ..."
    mkdir -p "$TARGET_DIR"
    cp -R "$SRC_DIR/"* "$TARGET_DIR/"
    echo "[OK] Files copied successfully."
else
    echo "[OK] Already located inside $TARGET_DIR"
fi

echo ""
echo "[SUCCESS] Antigravity Pulse v3.0 is installed!"
echo "- Restart Antigravity 2.0 and the bottom-bar HUD will appear automatically."
echo "- Right-click any HUD pill or click [极简 | 详细] in the popover to switch between Minimal and Pro modes."
