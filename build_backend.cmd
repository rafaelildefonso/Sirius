@echo off
setlocal EnableExtensions

set "SIRIUS_ROOT=%~dp0"

rem Prefer the project's virtual environment, then standard Windows Python launchers.
if exist "%SIRIUS_ROOT%venv\Scripts\python.exe" (
    "%SIRIUS_ROOT%venv\Scripts\python.exe" -c "import sys" >nul 2>nul
    if not errorlevel 1 (
        "%SIRIUS_ROOT%venv\Scripts\python.exe" -c "import PyInstaller" >nul 2>nul
        if errorlevel 1 (
            echo [ERRO] PyInstaller nao esta instalado no ambiente virtual do projeto.
            echo [ERRO] Execute ".\venv\Scripts\python.exe setup.py" e tente novamente.
            exit /b 1
        )
        "%SIRIUS_ROOT%venv\Scripts\python.exe" "%SIRIUS_ROOT%build_backend.py" --cached %*
        if errorlevel 1 exit /b 1
        exit /b 0
    )
    echo [SIRIUS] The project's Python environment could not be started. Trying another Python installation...
)

where py >nul 2>nul
if not errorlevel 1 (
    py -3 -c "import PyInstaller" >nul 2>nul
    if not errorlevel 1 (
        py -3 "%SIRIUS_ROOT%build_backend.py" --cached %*
        if errorlevel 1 exit /b 1
        exit /b 0
    )
)

where python >nul 2>nul
if not errorlevel 1 (
    python -c "import PyInstaller" >nul 2>nul
    if not errorlevel 1 (
        python "%SIRIUS_ROOT%build_backend.py" --cached %*
        if errorlevel 1 exit /b 1
        exit /b 0
    )
)

echo.
echo [ERRO] Python 3 com PyInstaller nao foi encontrado.
echo [ERRO] Execute ".\venv\Scripts\python.exe setup.py" e tente novamente.
exit /b 1
