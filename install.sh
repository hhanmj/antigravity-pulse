#!/usr/bin/env bash
set -e

echo "========================================================"
echo "  Antigravity Pulse — One-Click Installer (macOS/Linux)"
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

# Ensure 'python' is available inside Antigravity's runtime PATH on macOS
PY_BIN=""
if [ -x "/opt/homebrew/bin/python3" ]; then
    PY_BIN="/opt/homebrew/bin/python3"
elif [ -x "/usr/local/bin/python3" ]; then
    PY_BIN="/usr/local/bin/python3"
elif command -v python3 >/dev/null 2>&1; then
    PY_BIN="$(command -v python3)"
fi

if [ -n "$PY_BIN" ]; then
    for AGY_BIN_DIR in "$HOME/Library/Application Support/Antigravity/bin" "$HOME/.gemini/antigravity/bin"; do
        if [ -d "$(dirname "$AGY_BIN_DIR")" ]; then
            mkdir -p "$AGY_BIN_DIR"
            if [ ! -e "$AGY_BIN_DIR/python" ]; then
                ln -sf "$PY_BIN" "$AGY_BIN_DIR/python"
                echo "[OK] Linked $AGY_BIN_DIR/python -> $PY_BIN"
            fi
        fi
    done

    # Hot-start or reload daemon immediately
    pkill -f "context-monitor/skills/context-monitor/scripts/daemon_sync.py" >/dev/null 2>&1 || true
    nohup "$PY_BIN" "$TARGET_DIR/skills/context-monitor/scripts/daemon_sync.py" >/dev/null 2>&1 &
    echo "[OK] Background HUD daemon started ($PY_BIN)."
fi

echo ""
echo "[SUCCESS] Antigravity Pulse is installed and active!"
echo "- The bottom-bar HUD will appear automatically (no restart required)."
echo "- Right-click any HUD pill or click [极简 | 详细] in the popover to switch between Minimal and Pro modes."
