@echo off
echo Starting Jarvis Voice Assistant...
cd /d "%~dp0"
uv run python voice-assistant.py
if %ERRORLEVEL% NEQ 0 (
    echo.
    echo Error occurred. Press any key to exit...
    pause >nul
)
