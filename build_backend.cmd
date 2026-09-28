@echo off
setlocal EnableExtensions

set "SIRIUS_ROOT=%~dp0"

rem Prefer the project's virtual environment, then standard Windows Python launchers.
if exist "%SIRIUS_ROOT%venv\Scripts\python.exe" (
    "%SIRIUS_ROOT%venv\Scripts\python.exe" "%SIRIUS_ROOT%build_backend.py" --cached
    if not errorlevel 1 exit /b 0
    echo [SIRIUS] The project's Python environment could not be started. Trying another Python installation...
)

where py >nul 2>nul
if not errorlevel 1 (
    py -3 "%SIRIUS_ROOT%build_backend.py" --cached
    if not errorlevel 1 exit /b 0
)

where python >nul 2>nul
if not errorlevel 1 (
    python "%SIRIUS_ROOT%build_backend.py" --cached
    if not errorlevel 1 exit /b 0
)

echo.
echo [ERRO] Python 3 nao foi encontrado ou a instalacao esta quebrada.
echo [ERRO] Instale Python 3.11+ e execute o build novamente.
exit /b 1
