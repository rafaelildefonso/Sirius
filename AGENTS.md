# AGENTS.md — SIRIUS Project Guide

## 1. Project Overview

SIRIUS (by Rafael Ildefonso) is a cross-platform, real-time voice AI assistant that can hear, see, understand, and control the computer. It runs locally on Windows/macOS/Linux. Key abilities: screen analysis, document processing, workflow execution, computer automation, and a remote dashboard for phone control.

The project uses a **dual-process architecture**: a Tauri v2 + React frontend (`sirius-ui/`) and a Python backend (WebSocket server on port 8765). The Python backend is the only runtime; there is **no PyQt6 desktop UI**.

## 2. Architecture

| File | Role |
|------|------|
| `main.py` | Entry point (~2900 lines). Wires everything together. |
| `ws_server.py` | WebSocket server on `ws://127.0.0.1:8765` for the React frontend. Provides `WsUI` class. |
| `sirius_backend_launcher.py` | Sidecar entry point (PyInstaller). Sets `SIRIUS_WS_UI=1` and runs `main()`. |
| `build_backend.py` | Builds the headless Python sidecar for Tauri (`sirius-backend.exe`). |
| `sirius-backend.spec` | PyInstaller spec for the headless sidecar (excludes PyQt6). |
| `dashboard/server.py` | HTTP dashboard on **port 8000** for phone remote control (FastAPI + uvicorn). |
| `sirius-ui/` | React 19 + TypeScript + Vite + Tailwind frontend + Tauri v2 shell. |

**Flow:** Tauri shell (`sirius-ui.exe`) spawns `sirius-backend.exe` as a sidecar → `sirius_backend_launcher.py` sets `SIRIUS_WS_UI=1` → `main.py` starts `WsUI` (WebSocket server) → runs `SiriusLive` or `SiriusLocal` assistant loop → optionally starts dashboard server.

## 3. Running Modes

| Mode | Env Var | Notes |
|------|---------|-------|
| **Tauri (default)** | `SIRIUS_WS_UI=1` (set automatically by `sirius_backend_launcher.py`) | `main.py` always uses the WebSocket UI. The env var is kept for clarity/dev but is no longer a UI selector. |

## 4. Key Directories

| Directory | Contents |
|-----------|----------|
| `core/` | Config loader, LLM clients (`llm_client.py`, `or_client.py`), STT, TTS, Google auth, plugin loader |
| `core/intel/` | Scrapers & business intelligence (LinkedIn/Google Jobs/Maps scrapers, business/job analyzers, scoring engine) |
| `assets/` | Non-code assets: `sounds/init_sound.wav`, `prompts/system_prompt.txt` (bundled by the PyInstaller spec) |
| `actions/` | All tool/action modules (computer control, browser, files, web search, Gmail, Calendar, etc.) |
| `agent/` | Executor, planner, task queue, error handler |
| `dashboard/` | `server.py` + `static/` (login.html, app.html, crypto-js) |
| `persistence/` | SQLite + Fernet encryption: database, repository, models, embedding, retriever |
| `config/` | JSON configs: `configs.json`, `api_keys.json`, `permissions.json`, etc. |
| `memory/` | `memory_manager.py`, `config_manager.py`, `sirius.db` |
| `tests/` | Pytest suite (`test_persistence.py`) + integration tests (`test_server_security.py`) |
| `sirius-ui/` | React 19 + TypeScript + Vite + Tailwind CSS frontend + Tauri v2 |
| `sirius_companion/` | Flutter app companion para celular (controla o SIRIUS via dashboard) |

## 5. Dashboard Server (Port 8000)

- **File:** `dashboard/server.py` — `DashboardServer` class
- **Tech:** FastAPI + uvicorn (falls back to `http.server`)
- **Auth:** 6-char one-time keys (no O/I/L/0/1), AES-256-CBC encryption
- **Started in:** daemon thread in `main()` (early dashboard thread)
- **Key endpoints:** `/` (app.html), `/login` (PIN entry), `/auto-login?key=XXX` (QR code target), `/api/command`, `/ws` (WebSocket), `/ws/phone-audio`
- **Known issue:** PyInstaller onefile mode can give `PermissionError` reading `login.html`/`app.html` from temp. The `_read()` function has retry logic + `sys._MEIPASS` fallback.
- **Celular ↔ PC:** veja **[docs/SYNC.md](docs/SYNC.md)** — arquitetura completa da sincronização (pareamento seguro, AES do sync, timings do app Flutter, push PC→celular).

## 6. Build System

| Command | Output | When to Use |
|---------|--------|-------------|
| `python build_backend.py` | `dist/sirius-backend/sirius-backend.exe` | Build do sidecar Python (headless, sem PyQt6). Copia o binário para `sirius-ui/src-tauri/binaries/` como sidecar do Tauri. |
| `cd sirius-ui && npx tauri build` | Installer Tauri (MSI/NSIS) | Build final do app (frontend React + shell Rust + sidecar Python). |

`tauri.conf.json` roda `python ../build_backend.py --cached && npm run build` antes de buildar.

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
| `SIRIUS_WS_UI` | No | `1` força o modo WebSocket/Tauri (default; setado pelo launcher) |
| `SIRIUS_DATA_DIR` | No | Override data/config directory |
| `OPENROUTER_API_KEY` | For OpenRouter | Alternative LLM |
| `TAVILY_API_KEY` | For web search | Tavily search API |
| `GOOGLE_CLIENT_ID/SECRET` | For Gmail/Calendar | Google OAuth |

## 9. Quick Commands

```bash
# Dev — Python backend (terminal 1)
$env:SIRIUS_WS_UI='1'; python main.py

# Dev — Tauri frontend (terminal 2)
cd sirius-ui; npm install; npx tauri dev

# Build Python sidecar
python build_backend.py

# Build final app
cd sirius-ui; npx tauri build

# Install Python dependencies
python setup.py
```

## 10. Debugging Tips

- Dashboard not starting? Check for `[DEBUG DashboardServer.serve]` or `[Dashboard] SERVE FAILED:` in the terminal logs.
- `PermissionError` reading static files in the compiled .exe? The `_read()` function in `dashboard/server.py` has retry + `sys._MEIPASS` fallback.
- WS server fails? Check port 8765 is free.
- Tauri window shows white screen? Run frontend build manually: `cd sirius-ui && npm run build`
- Configs not loading? Check `SIRIUS_DATA_DIR` env var or `%LOCALAPPDATA%\SIRIUS\config\`.

## 11. Browser Control Actions

`actions/browser_control.py` is the main module for web automation via Playwright. The AI uses `browser_control` tool for all web interactions.

### Basic Actions

| Action | Description | Key Params |
|--------|-------------|------------|
| `go_to` | Navigate to URL | `url`, `browser` |
| `search` | Search on engine | `query`, `engine` (google/bing/duckduckgo) |
| `click` | Click element | `selector` or `text` |
| `type` | Type text | `selector`, `text`, `clear_first` |
| `smart_click` | Click by description | `description` (role/text/placeholder match) |
| `smart_type` | Type by description | `description`, `text` |
| `scroll` | Scroll page | `direction` (up/down), `amount` |
| `fill_form` | Fill multiple fields | `fields` (dict: selector→value) |
| `press` | Press key | `key` (Enter, Escape, F5...) |
| `get_text` | Get page text | - |
| `get_url` | Get current URL | - |
| `screenshot` | Save screenshot | `path` |

### Advanced Actions (New)

| Action | Description | Key Params |
|--------|-------------|------------|
| `upload` | Upload file to `<input type="file">` | `selector`, `path` (file path) |
| `wait` | Wait for element/text | `selector` or `text`, `state`, `timeout` |
| `download` | Download file via click | `selector` |
| `script` | Run multi-step workflow | `steps` (array of action objects) |

### Session & Browser Management

| Action | Description |
|--------|-------------|
| `new_tab` / `close_tab` | Tab management |
| `back` / `forward` / `reload` | Navigation |
| `switch` / `list_browsers` | Switch between browsers |
| `close` / `close_all` | Close sessions |

### Headless Mode

Pass `"headless": true` to run the browser invisibly (for scraping). Default is `false` (visible UI).

### Script Action Example

```json
{
  "action": "script",
  "steps": [
    {"action": "go_to", "url": "https://tiktok.com/upload"},
    {"action": "wait", "selector": "input[type=file]", "timeout": 10000},
    {"action": "upload", "selector": "input[type=file]", "path": "C:/Videos/video.mp4"},
    {"action": "wait", "selector": "textarea", "timeout": 10000},
    {"action": "type", "selector": "textarea", "text": "My video description"},
    {"action": "click", "text": "Post"}
  ]
}
```
