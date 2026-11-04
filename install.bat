@echo off
setlocal
echo ========================================================
echo   Antigravity Pulse v3.0 — One-Click Installer (Windows)
echo ========================================================

set "TARGET_DIR=%USERPROFILE%\.gemini\config\plugins\context-monitor"
set "SRC_DIR=%~dp0"

if /I "%SRC_DIR:~0,-1%" == "%TARGET_DIR%" (
    echo [OK] Already located inside %TARGET_DIR%
) else (
    echo [*] Installing plugin files to %TARGET_DIR% ...
    if not exist "%TARGET_DIR%" mkdir "%TARGET_DIR%"
    xcopy /E /I /Y "%SRC_DIR%*" "%TARGET_DIR%\" >nul
    echo [OK] Files copied successfully.
)

echo.
echo [SUCCESS] Antigravity Pulse v3.0 is installed!
echo - Restart Antigravity 2.0 (or start a new session) and the bottom-bar HUD will appear automatically.
echo - Right-click any HUD pill or click [极简 ^| 详细] in the popover to switch between Minimal and Pro modes.
pause
