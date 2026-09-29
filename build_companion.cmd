@echo off
setlocal
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0build_companion.ps1" %*
exit /b %errorlevel%
