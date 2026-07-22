# AGENTS.md — SIRIUS Project Guide

## 1. Project Overview

SIRIUS (by Rafael Ildefonso) is a cross-platform, real-time voice AI assistant that can hear, see, understand, and control the computer. It runs locally on Windows/macOS/Linux. Key abilities: screen analysis, document processing, workflow execution, computer automation, and a remote dashboard for phone control.

## 2. Architecture

| File | Role |
|------|------|
| `main.py` | Entry point (~2700 lines). Selects UI via `SIRIUS_WS_UI`/`SIRIUS_WEBVIEW_UI` env vars. Wires everything together. |
| `sirius_webview_ui.py` | **Default UI** — single-process WebView2 window (pywebview) loading the React frontend. Manages tray, single-instance, autostart. |
| `ws_server.py` | WebSocket server on `ws://127.0.0.1:8765` for the React frontend. Provides `WsUI` class. |
| `sirius_ui.py` | PyQt6 desktop UI (legacy, 3100+ lines). Used when no `SIRIUS_WS_UI`/`SIRIUS_WEBVIEW_UI` env var is set. |
| `dashboard/server.py` | HTTP dashboard on **port 8000** for phone remote control (FastAPI + uvicorn). |

**Flow:** `main.py` → creates `SiriusUI` (WebViewUI / WsUI / PyQt6 SiriusUI) → runs `SiriusLive` or `SiriusLocal` assistant loop → optionally starts dashboard server.

## 3. UI Modes

| Mode | Env Var | UI Framework | How to Run |
|------|---------|-------------|------------|
| **WebView (React)** | `SIRIUS_WEBVIEW_UI=1` (default in build) | `sirius_webview_ui.py` + pywebview (WebView2) | `$env:SIRIUS_WEBVIEW_UI='1'; python main.py` or `python build.py` |
| **WS (Tauri/React)** | `SIRIUS_WS_UI=1` | `ws_server.py` + Tauri frontend (legacy, 2-process) | `$env:SIRIUS_WS_UI='1'; python main.py` |
| **Desktop (PyQt6)** | unset / `0` / `false` | `sirius_ui.py` (PyQt6) | `python main.py` |

**WebView mode** é o padrão no build compilado. Tudo roda em **um único processo** `SIRIUS.exe` — o React frontend é carregado via WebView2, o backend Python roda na mesma thread. Não precisa mais de sidecar separado, nem Rust, nem Tauri.

## 4. Key Directories

| Directory | Contents |
|-----------|----------|
| `core/` | Config loader, LLM client, STT, TTS, Google auth, scrapers |
| `actions/` | All tool/action modules (computer control, browser, files, web search, Gmail, Calendar, etc.) |
| `agent/` | Executor, planner, task queue, error handler |
| `dashboard/` | `server.py` + `static/` (login.html, app.html, crypto-js) |
| `persistence/` | SQLite + Fernet encryption: database, repository, models, embedding, retriever |
| `config/` | JSON configs: `configs.json`, `api_keys.json`, `permissions.json`, etc. |
| `memory/` | `memory_manager.py`, `config_manager.py`, `sirius.db` |
| `sirius-ui/` | React 19 + TypeScript + Vite + Tailwind CSS frontend |
| `sirius-ui/src-tauri-stubs/` | Polyfills de `@tauri-apps/api` para WebView mode |
| `_obsolete/` | Arquivos do Tauri removidos (src-tauri, build_backend, etc.) |

## 5. Dashboard Server (Port 8000)

- **File:** `dashboard/server.py` — `DashboardServer` class
- **Tech:** FastAPI + uvicorn (falls back to `http.server`)
- **Auth:** 6-char one-time keys (no O/I/L/0/1), AES-256-CBC encryption
- **Started in:** WS/WebView mode only (daemon thread in `main()`, lines ~2463-2480; or inside `SiriusLive.run()`)
- **Key endpoints:** `/` (app.html), `/login` (PIN entry), `/auto-login?key=XXX` (QR code target), `/api/command`, `/ws` (WebSocket), `/ws/phone-audio`
- **Known issue:** PyInstaller onefile mode can give `PermissionError` reading `login.html`/`app.html` from temp. The `_read()` function has retry logic + `sys._MEIPASS` fallback.

## 6. Build System

| Command | Output | When to Use |
|---------|--------|-------------|
| `python build.py` | `dist/SIRIUS/SIRIUS.exe` | **Build principal** — produz um único .exe com WebView2 + React + backend Python. |

**Spec file:** `sirius.spec`. O build:
1. Compila o frontend React (`sirius-ui/`) com `SIRIUS_WEBVIEW_BUILD=1` (ativa stubs Tauri)
2. Executa PyInstaller com `sirius.spec`
3. Copia o frontend compilado e dados de config/memory para dentro do bundle

Não precisa mais de `build_backend.py`, `sirius-backend.spec`, ou Tauri/Rust.

## 7. Configuration

Configs live in `config/` (or `%LOCALAPPDATA%\SIRIUS\config\` when frozen):

| File | Format | Use |
|------|--------|-----|
| `configs.json` | JSON | `assistant_mode`, `llm_provider`, `user_name`, `stt/tss settings`, etc. |
| `api_keys.json` | JSON | `gemini_api_key`, `openrouter_api_key`, `tavily_api_key`, `serpapi_key` |
| `permissions.json` | JSON | Tool permission grants (once/always/deny) |
| `.db_key` | binary | Fernet encryption key for SQLite DB |

Loaded via `core/config_loader.py`. `SIRIUS_DATA_DIR` overrides the base path.

## 8. Key Environment Variables

| Variable | Required | Purpose |
|----------|----------|---------|
| `GEMINI_API_KEY` | Yes | Gemini AI API key |
| `SIRIUS_WEBVIEW_UI` | No | `1` para WebView mode (single-process, default no build) |
| `SIRIUS_WS_UI` | No | `1` para Tauri/WS mode (2 processos, legado) |
| `SIRIUS_DATA_DIR` | No | Override data/config directory |
| `OPENROUTER_API_KEY` | For OpenRouter | Alternative LLM |
| `TAVILY_API_KEY` | For web search | Tavily search API |
| `GOOGLE_CLIENT_ID/SECRET` | For Gmail/Calendar | Google OAuth |

## 9. Quick Commands

```bash
# Dev — run with WebView UI (new default)
$env:SIRIUS_WEBVIEW_UI='1'; python main.py

# Dev — run with legacy Tauri UI
$env:SIRIUS_WS_UI='1'; python main.py

# Dev — run PyQt6 desktop (no env var)
python main.py

# Build single .exe (builds frontend + backend together)
python build.py

# Install dependencies
python setup.py
```

## 10. Debugging Tips

- Dashboard not starting? Check for `[DEBUG DashboardServer.serve]` or `[Dashboard] SERVE FAILED:` in the terminal logs.
- `PermissionError` reading static files in the compiled .exe? The `_read()` function in `dashboard/server.py` has retry + `sys._MEIPASS` fallback.
- WS server fails? Check port 8765 is free.
- WebView window shows white screen? Run frontend build manually: `cd sirius-ui && npm run build`
- Tauri API errors (`invoke` not found)? Ensure `SIRIUS_WEBVIEW_BUILD=1` is set when building the frontend (automatic via `build.py`).
- Configs not loading? Check `SIRIUS_DATA_DIR` env var or `%LOCALAPPDATA%\SIRIUS\config\`.
- Obsolete Tauri files moved to `_obsolete/`. If Tauri dev is still needed, restore from there.