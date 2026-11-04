@echo off
setlocal
echo ========================================================
echo   Antigravity Pulse — Uninstaller (Windows)
echo ========================================================

set "TARGET_DIR=%USERPROFILE%\.gemini\config\plugins\context-monitor"

if exist "%TARGET_DIR%" (
    echo [*] Removing %TARGET_DIR% ...
    rmdir /S /Q "%TARGET_DIR%"
    echo [OK] Antigravity Pulse has been removed. Please restart Antigravity.
) else (
    echo [!] Not found at %TARGET_DIR%
)
pause
