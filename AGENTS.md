# AGENTS.md — SIRIUS Project Guide

## 1. Project Overview

SIRIUS (by Rafael Ildefonso) is a cross-platform, real-time voice AI assistant that can hear, see, understand, and control the computer. It runs locally on Windows/macOS/Linux. Key abilities: screen analysis, document processing, workflow execution, computer automation, and a remote dashboard for phone control.

## 2. Architecture

| File | Role |
|------|------|
| `main.py` | Entry point (~2600 lines). Selects UI via `SIRIUS_WS_UI` env var. Wires everything together. |
| `ws_server.py` | WebSocket server on `ws://127.0.0.1:8765` for the Tauri/React frontend. Provides `WsUI` class. |
| `sirius_ui.py` | PyQt6 desktop UI (legacy, 3100+ lines). Used when `SIRIUS_WS_UI` is not set. |
| `dashboard/server.py` | HTTP dashboard on **port 8000** for phone remote control (FastAPI + uvicorn). |

**Flow:** `main.py` → creates `SiriusUI` (PyQt6 or WsUI) → runs `SiriusLive` or `SiriusLocal` assistant loop → optionally starts dashboard server.

## 3. UI Modes

| Mode | Env Var | UI Framework | How to Run |
|------|---------|-------------|------------|
| **Desktop (PyQt6)** | unset / `0` / `false` | `sirius_ui.py` (PyQt6) | `python main.py` |
| **WS (Tauri/React)** | `1` / `true` / `yes` | `ws_server.py` + Tauri frontend | `$env:SIRIUS_WS_UI='1'; python main.py` or `cd sirius-ui && npx tauri dev` |

In WS mode, the backend is a PyInstaller-compiled `.exe` launched as a **Tauri sidecar**. The Rust code (`sirius-ui/src-tauri/src/main.rs`) always sets `SIRIUS_WS_UI=1` on the sidecar process. The launcher (`sirius_backend_launcher.py`) also sets it.

**IMPORTANT:** When running through Tauri (`npx tauri dev`), the compiled `sirius-backend.exe` is used — editing `main.py` or `dashboard/server.py` requires **recompiling** with `python build_backend.py`.

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
| `sirius-ui/` | Tauri v2 + React 19 + TypeScript + Vite + Tailwind CSS frontend |
| `sirius-ui/src-tauri/` | Rust backend for Tauri: sidecar launcher, tray, single-instance |

## 5. Dashboard Server (Port 8000)

- **File:** `dashboard/server.py` — `DashboardServer` class
- **Tech:** FastAPI + uvicorn (falls back to `http.server`)
- **Auth:** 6-char one-time keys (no O/I/L/0/1), AES-256-CBC encryption
- **Started in:** WS mode only (daemon thread in `main()`, lines ~2463-2480; or inside `SiriusLive.run()`)
- **Key endpoints:** `/` (app.html), `/login` (PIN entry), `/auto-login?key=XXX` (QR code target), `/api/command`, `/ws` (WebSocket), `/ws/phone-audio`
- **Known issue:** PyInstaller onefile mode can give `PermissionError` reading `login.html`/`app.html` from temp. The `_read()` function has retry logic + `sys._MEIPASS` fallback.

## 6. Build System

| Command | Output | When to Use |
|---------|--------|-------------|
| `python build.py` | `dist/SIRIUS/SIRIUS.exe` | Full desktop build (PyQt6 + all features) |
| `python build_backend.py` | `dist/sirius-backend.exe` + copies to `sirius-ui/src-tauri/binaries/` | Headless backend for Tauri sidecar |
| `cd sirius-ui && npx tauri dev` | Vite + Tauri dev mode | Frontend development (auto-launches sidecar) |
| `cd sirius-ui && npx tauri build` | Tauri installer | Production Tauri bundle |
| `python build_backend.py --cached` | Skips rebuild if source hasn't changed | Faster Tauri builds |

**Spec files:** `sirius.spec` (full), `sirius-backend.spec` (headless). Both use PyInstaller.

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
| `SIRIUS_WS_UI` | No | `1` to enable Tauri/React UI instead of PyQt6 |
| `SIRIUS_DATA_DIR` | No | Override data/config directory |
| `OPENROUTER_API_KEY` | For OpenRouter | Alternative LLM |
| `TAVILY_API_KEY` | For web search | Tavily search API |
| `GOOGLE_CLIENT_ID/SECRET` | For Gmail/Calendar | Google OAuth |

## 9. Quick Commands

```bash
# Dev — run directly (PyQt6 mode)
python main.py

# Dev — run with Tauri UI
$env:SIRIUS_WS_UI='1'; python main.py

# Dev — full Tauri stack
cd sirius-ui && npm install && npx tauri dev

# Build backend (needed after editing main.py or dashboard/*.py)
python build_backend.py

# Install dependencies
python setup.py
```

## 10. Debugging Tips

- Dashboard not starting? Check for `[DEBUG DashboardServer.serve]` or `[Dashboard] SERVE FAILED:` in the terminal logs.
- `PermissionError` reading static files in the compiled .exe? The `_read()` function in `dashboard/server.py` has retry + `sys._MEIPASS` fallback.
- WS server fails? Check port 8765 is free (killed automatically by Tauri launcher).
- Backend crashes silently? The `asyncio.ensure_future` pattern may swallow exceptions — look for `[Dashboard] SERVER TASK CRASHED:` logs.
- Configs not loading? Check `SIRIUS_DATA_DIR` env var or `%LOCALAPPDATA%\SIRIUS\config\`.
