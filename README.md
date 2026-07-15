# 🤖 SIRIUS
### The Ultimate Cross-Platform Personal AI Assistant — By Rafael Ildefonso

> 📺 **[Watch the full setup video on YouTube](https://youtu.be/ej1f5OE3SNQ?si=lCxDhJix9ungq1Ry)**

A real-time voice AI that can hear, see, understand, and control your computer — on any OS. Supporting Windows, macOS, and Linux. Local execution. Zero subscriptions. Engineered for total autonomy.

---

## ✨ Overview

SIRIUS represents the pinnacle of the Sirius series, evolving into a more flexible and robust system. It bridges the gap between the operating system and human intent. Through natural dialogue, Sirius 39 analyzes your screen, processes uploaded documents, and executes complex workflows with a brand-new, adaptive interface.

It's not just an assistant — it's an extension of your digital life.

---

## 🚀 Capabilities

### Core Features
| Feature | Description |
|---|---|
| 🎙️ Real-time Voice | Ultra-low latency conversation in any language |
| 🖥️ System Control | Launch apps, manage files, execute terminal commands |
| 🧩 Autonomous Tasks | High-level planning for complex, multi-step goals |
| 👁️ Visual Awareness | Real-time screen processing and webcam vision |
| 🧠 Persistent Memory | SQLite + FTS5 with classification, extraction, and RAG embeddings |
| 🗄️ Dashboard API | REST + WebSocket remote control with persistent history |
| ⌨️ Hybrid Input | Seamlessly switch between keyboard typing and voice commands |

---

## 🆕 What's New

- 🎨 **Modern UI (Tauri + React)** — GPU-accelerated interface with Tailwind CSS, perfect Unicode/Portuguese text rendering, animated HUD via Canvas API. Drop-in replacement for the legacy PyQt6 UI.
- 🔌 **WebSocket Server** — UI backend decoupled from PyQt6. Enables any frontend technology (React, Svelte, mobile) to connect to the Python core.
- 📦 **PyInstaller Bundle** — Backend Python empacotado em `sirius-backend.exe` standalone (~300 MB). Zero dependência de Python instalado para usuários finais.
- 🔗 **Tauri Sidecar** — Tauri gerencia o backend como sidecar: spawn automático na inicialização e kill ao fechar a janela.
- 🧭 **Onboarding Wizard** — Assistente de primeira execução com 5 passos: modo (gemini/ollama), nome do usuário, API keys, permissões e resumo.
- 📂 **Advanced File Handling** — Drop PDFs, source code, or images for instant analysis.
- ⚡ **Optimized Core Engine** — 40% faster interaction speed.

---

## 🏗️ Architecture

```
┌─────────────────────────────────────────────────────┐
│  UI Layer                                            │
│  ├── Modern: Tauri v2 + React + Tailwind (GPU)       │
│  └── Legacy:  PyQt6 + QPainter                       │
├─────────────────────┬───────────────────────────────┤
│  Dashboard (port 8000) │  WebSocket (port 8765)      │
│  REST API + WS        │  (Tauri sidecar comm)       │
├─────────────────────┴───────────────────────────────┤
│  PyInstaller Bundle (sirius-backend.exe)             │
│  ┌──────────────────────────────────────────────────┐│
│  │  Python Core                                     ││
│  │  ├── STT (Whisper / Vosk)                        ││
│  │  ├── TTS (Edge TTS / Kokoro / ElevenLabs)        ││
│  │  ├── LLM (Gemini / Ollama / OpenRouter)          ││
│  │  ├── Actions (25+ tools — system, browser)       ││
│  │  ├── Agent (autonomous task planner)             ││
│  │  └── Persistence Layer (SQLite + FTS5 + RAG)    ││
│  │       ├── database.py    — Engine + migrations   ││
│  │       ├── repository.py  — CRUD for all entities ││
│  │       ├── classifier.py  — C0–C11 classification  ││
│  │       ├── extractor.py   — Structured extraction ││
│  │       ├── retriever.py   — Hybrid search (FTS+vec)││
│  │       ├── context_builder.py — LLM prompt builder││
│  │       ├── embedding.py   — Vector embeddings     ││
│  │       ├── scheduler.py   — Maintenance + backup  ││
│  │       └── backup.py      — Automated DB backups  ││
│  └──────────────────────────────────────────────────┘│
└─────────────────────────────────────────────────────┘
```

---

## 🧠 Persistence Layer

SIRIUS stores all long-term knowledge in a structured SQLite database with FTS5 full-text search and optional vector embeddings for semantic retrieval.

### Architecture

| Module | Purpose |
|--------|---------|
| `database.py` | SQLite engine, WAL mode, automatic schema migrations, Fernet-encrypted credential storage |
| `repository.py` | Unified CRUD for conversations, messages, events, facts, preferences, files, tags |
| `classifier.py` | Two-stage classification (C0–C11): fast regex rules → LLM fallback for ambiguous input |
| `extractor.py` | Transforms classified text into structured `Event` objects with importance, confidence, tags, TTL |
| `retriever.py` | Hybrid search combining SQL filters, FTS5 full-text, and cosine similarity over embedding vectors |
| `context_builder.py` | Assembles the memory context block injected into every LLM prompt |
| `embedding.py` | Wraps `sentence-transformers` (optional) for real vector embeddings; hash-based fallback when unavailable |
| `scheduler.py` | Background thread: purges expired entries every 6h, runs VACUUM, triggers DB backup every 24h |
| `backup.py` | Timestamped copies with auto-rotation (max 7), manual restore support |

### Memory Types (C0–C11)

| Code | Type | Examples |
|------|------|----------|
| C0 | Casual chat | Greetings, jokes, small talk — not stored |
| C1 | Preference | "I like blue", "Favorite food is pizza" |
| C2 | User fact | Name, age, job, city, family |
| C3 | Project | Current project, codebase info |
| C4 | File reference | Paths, documents, code snippets |
| C5 | Commitment | Appointments, meetings, events |
| C6 | Reminder | "Remind me at 5pm" |
| C7 | Task | To-do items, actionable tasks |
| C8 | Contact | People's names, emails, phones |
| C9 | Knowledge | Tips, tutorials, useful facts |
| C10 | Temporary | Weather, status, transient data |
| C11 | Permanent | Serial numbers, credentials, API keys |

### Embeddings & Semantic Search

With `sentence-transformers` installed, SIRIUS generates 384-dimension vectors for every stored event and performs cosine similarity search. Without the package, a deterministic hash-based fallback ensures the pipeline never breaks.

```bash
# Enable real semantic search:
pip install sentence-transformers
```

### Database Location

```
📁 <SIRIUS_DATA_DIR>/
└── memory/
    ├── sirius.db           # Main SQLite database
    ├── long_term.json      # Legacy JSON memory (auto-synced on startup)
    └── backups/            # Automatic backups (max 7, rotated daily)
```

---

## 🗄️ Dashboard API (Remote Control)

The dashboard runs on **port 8000** (FastAPI + uvicorn) and provides REST + WebSocket endpoints for phone/tablet remote control.

### Endpoints

| Endpoint | Method | Auth | Purpose |
|----------|--------|------|---------|
| `/` | GET | Client-side | Main UI (`app.html`) |
| `/login` | GET/POST | PIN | Authentication with 6-char one-time PIN |
| `/auto-login` | GET | Key in URL | QR code target for instant pairing |
| `/api/command` | POST | Bearer token | Send text command to assistant |
| `/api/messages` | GET | Bearer token | Persistent message history from DB |
| `/api/conversations` | GET | Bearer token | List all conversations |
| `/api/preferences` | GET | Bearer token | View stored preferences |
| `/api/memory/stats` | GET | Bearer token | DB table statistics |
| `/api/files` | GET | Bearer token | List uploaded files |
| `/api/upload` | POST | Bearer token | Upload files (max 500 MB) |
| `/api/wake` | POST | Bearer token | Wake sleeping assistant |
| `/api/device-login` | POST | Device token | Auto-reconnect for known devices |
| `/api/revoke-devices` | POST | Bearer token | Revoke all paired devices |
| `/ws` | WebSocket | Token in URL | Real-time message stream |
| `/ws/phone-audio` | WebSocket | Token in URL | Phone microphone → Gemini Live |

---

## 🎤 Voice Commands

Simply speak naturally – the AI identifies intent and calls the correct tool.

### How to use the shutdown commands

| Action | How to say it | What happens |
|---|---|---|
| **Hide only the interface** (keeps backend running) | Say “tchau”, “até logo”, “pode fechar” or similar | The Tauri window is hidden to the system tray. The backend keeps running in the background; you can restore the window from the tray icon. |
| **Shut down completely** (closes interface and backend) | Say “fechar tudo”, “desligar tudo”, “encerrar completamente” | The interface closes and the backend process is terminated. Everything stops. |

> 💡 **Tip**: Clicking the window’s **X** button or pressing Alt+F4 also hides the interface (same as “tchau”) – it does **not** quit the backend.

### All Tools

| What to say | Tool |
|---|---|
| “Open Chrome / Spotify / Calculator” | open_app |
| “Search the internet for …” | web_search |
| “What’s the weather like today?” | weather_report |
| “Send a WhatsApp to …” | send_message |
| “Remind me to … at 14h” | eminder |
| “Play … on YouTube” | youtube_video |
| “What’s on my screen?” | screen_process |
| “Change volume / Wi‑Fi / brightness” | computer_settings |
| “Open site … / go back / reload” | rowser_control |
| “Create / move / delete file …” | ile_controller |
| “Minimize all / arrange windows” | desktop_control |
| “Write a code that …” | code_helper |
| “Create a React project with …” | dev_agent |
| “Run this background task” | gent_task |
| “Shut down / hibernate / sleep” | computer_control |
| “Update Steam games” | game_updater |
| “Search for flights to SP on 15th” | light_finder |
| “Hide interface” | hide_interface |
| “Shut down completely” | shutdown_sirius |
| Process uploaded file (drag‑and‑drop) | ile_processor |
| “Remember this info” | save_memory |
| “Schedule a meeting…” | google_calendar |
| “Add to Notion calendar” | 
otion_calendar |
| “Read / send email” | gmail |
| “Activate work workspace” | workspaces |
| “Do deep research on …” | deep_research |
| “Look for … jobs” | linkedin_jobs_radar |
| “Help me apply for job …” | pply_assist |
| “Find freelance work …” | reela_arsenal 
## ⚡ Quick Start

### Legacy UI (PyQt6 — padrão)

```bash
pip install -r requirements.txt
playwright install
python main.py
```

### Modern UI (Tauri + React)

```bash
# Terminal 1: Python backend
set SIRIUS_WS_UI=1    # Linux/macOS: export SIRIUS_WS_UI=1
python main.py

# Terminal 2: Tauri frontend
cd sirius-ui
npx tauri dev          # Dev mode (hot-reload)
```

> 💡 The Tauri window spawns `python main.py` automatically.
> For development, run Python manually in one terminal and Tauri in another.

### Single-Click Bundle (Produção)

```bash
# 1. Build backend standalone
pip install pyinstaller
python build_backend.py

# 2. Build Tauri + backend sidecar
cd sirius-ui
npx tauri build
```

> Gera instalador único (MSI/NSIS) com `sirius-backend.exe` embutido como sidecar.
> Usuário final não precisa de Python — apenas instalar e executar.

---

## 📁 Project Structure

```
📁 sirius/
├── main.py                       # Entry point (runtime principal)
├── ws_server.py                  # WebSocket server (localhost:8765) + onboarding
├── sirius_ui.py                  # UI PyQt6 legada
├── sirius_backend_launcher.py    # Wrapper PyInstaller (seta SIRIUS_WS_UI=1)
├── sirius-backend.spec           # PyInstaller spec (exclui PyQt6, torch...)
├── build_backend.py              # Script que builda e copia o sidecar
├── sirius-ui/                    # Frontend Tauri + React
│   ├── src/
│   │   ├── App.tsx, main.tsx
│   │   ├── components/
│   │   │   ├── HudCanvas, LogPanel, SettingsModal...
│   │   │   └── OnboardingWizard.tsx  # Wizard 5 passos
│   │   └── hooks/
│   │       └── useWebSocket.ts      # Auto-reconnect + onboarding flow
│   └── src-tauri/               # Rust + Tauri v2 + sidecar config
├── core/                      # STT, TTS, LLM, config loader
├── actions/                   # 25+ ferramentas do sistema
├── agent/                     # Planejador e executor autonomo
├── memory/                    # Memoria persistente (JSON legado + integracao DB)
│   └── memory_manager.py      # process_user_input(), load/save/format
├── persistence/               # Nova camada de persistencia (SQLite + RAG)
│   ├── database.py            # Engine SQLite, FTS5, migracoes, criptografia
│   ├── models.py              # Dataclasses: Event, Message, Fact, etc.
│   ├── repository.py          # CRUD unificado para todas as entidades
│   ├── classifier.py          # Classificador C0-C11 (regras + LLM fallback)
│   ├── extractor.py           # Extracao estruturada de eventos
│   ├── retriever.py           # Busca hibrida (FTS5 + similaridade de vetores)
│   ├── context_builder.py     # Montagem de contexto para o prompt LLM
│   ├── embedding.py           # Provider de embeddings (sentence-transformers)
│   ├── scheduler.py           # Tarefas de manutencao: purge, vacuum
│   └── backup.py              # Backups automaticos com retencao (max 7)
├── dashboard/                 # Remote control via FastAPI (port 8000)
│   ├── server.py              # REST + WebSocket, mensagens persistentes
│   └── static/                # app.html, login.html, CryptoJS
├── tests/                     # Testes unitarios (pytest)
│   └── test_persistence.py    # 40 testes: DB, CRUD, classificacao, embedding
└── config/                    # Configuracoes, API keys, permissoes
```

---

## 📋 Requirements

| Requirement | Details |
|---|---|
| **OS** | Windows 10/11, macOS, or Linux |
| **Python** | 3.11+ |
| **Microphone** | Required for voice interaction |
| **API Key** | Free Gemini API key |
| **Node.js 20+** | Only for Tauri UI (optional) |
| **Rust** | Only for Tauri build (optional) |
| **PyInstaller** | Only for production bundle (`pip install pyinstaller`) |
| **sentence-transformers** | Optional — enables real RAG/vector embeddings (`pip install sentence-transformers`) |

### Installing Dependencies

```bash
# Core runtime
pip install -r requirements.txt

# Optional: semantic search with vector embeddings
pip install sentence-transformers

# Optional: Tauri frontend build
npm install -g @tauri-apps/cli
```

## 📧 Integração Google (Calendar & Gmail)

O Sirius agora suporta integração com Google Calendar e Gmail. Para ativar:

1. Acesse o [Google Cloud Console](https://console.cloud.google.com/).
2. Crie um novo projeto.
3. Ative as APIs **Google Calendar API** e **Gmail API**.
4. Vá em **Credentials** > **Create Credentials** > **OAuth client ID**.
5. Selecione **Desktop App**.
6. Baixe o arquivo JSON e renomeie-o para `client_secrets.json`.
7. Mova o arquivo para a pasta `config/` do Sirius.

Na primeira vez que você usar um comando do Google (ex: "O que eu tenho para hoje?"), o Sirius abrirá o navegador para você autorizar o acesso

---

## ⚠️ License

Personal and non-commercial use only.
Licensed under **[Creative Commons BY-NC 4.0](https://creativecommons.org/licenses/by-nc/4.0/)**.

---

## 👤 Connect with the Creator

Engineered by a developer building a real-world JARVIS-style assistant.
⭐ **Star the repository to support the journey to Mark 100.**

| Platform | Link |
|---|---|
| YouTube | [@FatihMakes](https://www.youtube.com/@FatihMakes) |
| Instagram | [@fatihmakes](https://www.instagram.com/fatihmakes) |
