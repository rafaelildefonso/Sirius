from __future__ import annotations

import asyncio
import json
import platform as _platform
import re
import subprocess as _subprocess
import sys
import threading
import time as _time
import traceback
from datetime import datetime
from pathlib import Path

# -- Set AppUserModelID early so Windows taskbar can associate the pinned shortcut --
if getattr(sys, "frozen", False) and sys.platform == "win32":
    try:
        import ctypes
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
            "rafaelildefonso.sirius.assistant.1.0"
        )
    except Exception:
        pass

# -- Nuclear: force CREATE_NO_WINDOW on EVERY subprocess call on Windows --
if _platform.system() == "Windows":
    _OrigPopen = _subprocess.Popen
    class _Popen(_OrigPopen):
        def __init__(self, args, **kw):
            kw["creationflags"] = kw.get("creationflags", 0) | _subprocess.CREATE_NO_WINDOW
            kw.pop("startupinfo", None)
            super().__init__(args, **kw)
    _subprocess.Popen = _Popen

import numpy as np
import sounddevice as sd
from google import genai
from google.genai import types

# -- UI backend: WebSocket server for the Tauri/React frontend ----------------
import ws_server as _ws
from ws_server import WsUI as SiriusUI

_DASHBOARD: 'DashboardServer | None' = None  # noqa: F821 — imported lazily below
_DASHBOARD_READY = threading.Event()  # set when dashboard port is confirmed open
_ws.start()
from core.activity_monitor import is_monitor_enabled, start_monitor

start_monitor()
from core.config_loader import get_all_config

cfg = get_all_config()
vault_path = cfg.get("obsidian_vault_path")
if vault_path:
    # Google Drive (G:) pode demorar minutos para montar; conecta em background
    # com retry (3 tentativas, 3 min de intervalo) em vez de bloquear a inicialização.
    _ws.connect_obsidian_with_retry()
else:
    print("[Main] No obsidian vault path configured; skipping initialization.")

from actions.apply_assist import apply_assist
from actions.browser_control import browser_control
from actions.business_radar import business_radar
from actions.code_helper import code_helper
from actions.computer_control import computer_control
from actions.computer_settings import computer_settings
from actions.deep_research import deep_research
from actions.desktop import desktop_control
from actions.dev_agent import dev_agent
from actions.file_controller import file_controller
from actions.file_processor import file_processor
from actions.flight_finder import flight_finder
from actions.freela_arsenal import freela_arsenal
from actions.game_updater import game_updater
from actions.gmail import gmail_action
from actions.google_calendar import google_calendar as calendar_action
from actions.linkedin_jobs_radar import linkedin_jobs_radar
from actions.notion_calendar import notion_calendar as notion_calendar_action
from actions.open_app import open_app
from actions.reminder import reminder
from actions.screen_processor import screen_process
from actions.send_message import send_message
from actions.send_to_phone import send_to_phone
from actions.weather_report import weather_action
from actions.web_search import _news as _fetch_news_sync
from actions.web_search import web_search as web_search_action
from actions.youtube_video import youtube_video
from config.permissions import (
    PERMISSION_META,
    get_category,
    grant_permission,
    is_granted,
)
from core.config_loader import get_base_dir
from memory.config_manager import get_assistant_name
from memory.memory_manager import (
    extract_memory,
    format_memory_for_prompt,
    get_repo,
    load_memory,
    process_user_input,
    should_extract_memory,
    update_memory,
)

BASE_DIR        = get_base_dir()
PROMPT_RELPATH  = Path("assets") / "prompts" / "system_prompt.txt"
PROMPT_PATH     = BASE_DIR / PROMPT_RELPATH
LIVE_MODEL          = "models/gemini-2.5-flash-native-audio-preview-12-2025"
CHANNELS            = 1
SEND_SAMPLE_RATE    = 16000
RECEIVE_SAMPLE_RATE = 24000
CHUNK_SIZE          = 1024
FFT_NUM_BINS        = 32
_SEND_FFT_INTERVAL  = 4  # Send FFT bins every N chunks (~60ms at 16kHz/1024)

def compute_fft_bins(audio_data: np.ndarray, num_bins: int = FFT_NUM_BINS) -> list[float]:
    samples = audio_data.astype(np.float32).flatten()
    if len(samples) == 0:
        return [0.0] * num_bins
    rms = float(np.sqrt(np.mean(samples ** 2)))
    energy = min(1.0, rms / 0.05)
    if energy < 0.005:
        return [0.0] * num_bins
    window = np.hanning(len(samples))
    fft = np.abs(np.fft.rfft(samples * window))
    n = len(fft)
    result = []
    for i in range(num_bins):
        lo = int((i / num_bins) ** 2 * n) if i > 0 else 0
        hi = int(((i + 1) / num_bins) ** 2 * n) if i < num_bins - 1 else n
        lo = min(lo, n - 1)
        hi = max(hi, lo + 1)
        hi = min(hi, n)
        avg = float(np.mean(fft[lo:hi]))
        result.append(avg)
    max_val = max(result)
    if max_val < 1e-6:
        return [0.0] * num_bins
    return [min(1.0, (v / max_val) * energy) for v in result]

def _get_api_key() -> str:
    from core.config_loader import get_secret
    key = get_secret("gemini_api_key", "")
    if not key:
        raise ValueError("gemini_api_key is empty. Configure it in Settings.")
    return key


_last_memory_input = ""
_sirius_instance: "SiriusLive | None" = None

def request_restart() -> None:
    """Signal the running SiriusLive to disconnect and reconnect with fresh config."""
    global _sirius_instance
    if _sirius_instance is not None:
        _sirius_instance.request_restart()
        print("[SYS] Restart requested (config changed)")

def _update_memory_async(user_text: str, sirius_text: str) -> None:
    global _last_memory_input

    user_text   = (user_text   or "").strip()
    sirius_text = (sirius_text or "").strip()

    if len(user_text) < 5 or user_text == _last_memory_input:
        return
    _last_memory_input = user_text

    # New pipeline: classify + extract + persist via process_user_input
    try:
        event_id = process_user_input(user_text, source="user", context={"reply": sirius_text[:500]})
        if event_id:
            print(f"[Memory] Persisted as event {event_id[:12]}...")
            return
    except Exception as e:
        if "429" not in str(e):
            print(f"[Memory] process_user_input warning: {e}")

    # Legacy fallback: LLM-based extraction for non-classified items
    try:
        api_key = _get_api_key()
        if not should_extract_memory(user_text, sirius_text, api_key):
            return
        data = extract_memory(user_text, sirius_text, api_key)
        if data:
            update_memory(data)
            print(f"[Memory] Legacy OK {list(data.keys())}")
    except Exception as e:
        if "429" not in str(e):
            print(f"[Memory] Legacy warning: {e}")


def _persist_message_to_db(instance: "SiriusLive", role: str, content: str) -> None:
    """Persist a conversation message to the DB, creating a conversation lazily."""
    try:
        repo = get_repo()
        if repo is None:
            print("[Memory] DB persist skipped — repo not available")
            return
        if instance._conv_id is None:
            instance._conv_id = repo.create_conversation(title=f"SIRIUS Live {datetime.now().strftime('%Y-%m-%d %H:%M')}")
            print(f"[Memory] Created conversation #{instance._conv_id}")
        repo.add_message(int(instance._conv_id), role, content[:500])
        print(f"[Memory] Persisted {role} message to conv #{instance._conv_id}")
    except Exception as e:
        print(f"[Memory] DB persist warning: {e}")


_system_prompt_cache: str | None = None

def _detect_lan_ip() -> str:
    """Return the first non-loopback IPv4 address (works offline)."""
    import socket
    for probe in ("8.8.8.8", "1.1.1.1", "192.168.1.1"):
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.settimeout(0.5)
            s.connect((probe, 80))
            addr = s.getsockname()[0]
            s.close()
            if not addr.startswith("127."):
                return addr
        except Exception:
            pass
    try:
        addr = socket.gethostbyname(socket.gethostname())
        if not addr.startswith("127."):
            return addr
    except Exception:
        pass
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            addr = info[4][0]
            if not addr.startswith("127.") and not addr.startswith("169.254."):
                return addr
    except Exception:
        pass
    return "127.0.0.1"


def _is_port_open(host: str = '127.0.0.1', port: int = 8000, timeout: float = 0.5) -> bool:
    """Check if a TCP port is accepting connections."""
    import socket
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(timeout)
        s.connect((host, port))
        s.close()
        return True
    except Exception:
        return False


def _now_context_str() -> str:
    """Fresh [CURRENT DATE & TIME] block — always call at usage time so the
    model's clock matches the moment the text is actually sent/spoken."""
    now      = datetime.now()
    time_str = now.strftime("%A, %B %d, %Y — %I:%M %p")
    return (
        f"[CURRENT DATE & TIME]\n"
        f"Right now it is: {time_str}\n"
        f"Use this to calculate exact times for reminders."
    )

def _load_system_prompt() -> str:
    global _system_prompt_cache
    if _system_prompt_cache is not None:
        return _system_prompt_cache
    try:
        _system_prompt_cache = PROMPT_PATH.read_text(encoding="utf-8")
        return _system_prompt_cache
    except Exception:
        # Frozen (PyInstaller onefile) fallback: bundled under sys._MEIPASS.
        pass
    try:
        import sys as _sys

        meipass = getattr(_sys, "_MEIPASS", None)
        if meipass:
            _system_prompt_cache = (Path(meipass) / PROMPT_RELPATH).read_text(encoding="utf-8")
            return _system_prompt_cache
    except Exception:
        pass
    _system_prompt_cache = (
        "You are SIRIUS, a powerful and minimalist AI assistant. "
        "Be concise, direct, and always use the provided tools to complete tasks. "
        "Never simulate or guess results — always call the appropriate tool."
    )
    return _system_prompt_cache

_CTRL_RE = re.compile(r"<ctrl\d+>", re.IGNORECASE)

def _clean_transcript(text: str) -> str:
    text = _CTRL_RE.sub("", text)
    text = re.sub(r"[\x00-\x08\x0b-\x1f]", "", text)
    return text.strip()

# Bundled plugin modules (loaded via importlib in frozen mode when plugins/
# is not shipped as loose .py files to avoid AV blocking in _MEIxxxxx temp dir)
_BUNDLED_PLUGIN_MODULES = ["calorie_counter", "pushup_counter", "upload_video"]

TOOL_DECLARATIONS = [
    {
        "name": "open_app",
        "description": (
            "Opens any application on the computer. "
            "Use this for programs like Spotify, WhatsApp, Discord, etc. "
            "CRITICAL: For websites or searching the web, NEVER use this — use browser_control instead. "
            "If the user asks to 'open Brave and go to X', ONLY call browser_control with browser='brave' and url='X'."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "app_name": {
                    "type": "STRING",
                    "description": "Exact name of the application (e.g. 'WhatsApp', 'Chrome', 'Spotify')"
                }
            },
            "required": ["app_name"]
        }
    },
    {
        "name": "web_search",
        "description": (
            "Searches the web for information. "
            "Modes: search (default), news, research, price, compare, shopping. "
            "WHEN THE USER WANTS TO BUY SOMETHING: search for specific products "
            "with prices, brands, and buying options — NOT just a description of "
            "what the product is. After searching, use browser_control to navigate "
            "to a shopping site showing the products on screen."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "query":  {"type": "STRING", "description": "Search query"},
                "mode":   {"type": "STRING", "description": "search (default), news, research, price, compare, or shopping"},
                "items":  {"type": "ARRAY", "items": {"type": "STRING"}, "description": "Items to compare"},
                "aspect": {"type": "STRING", "description": "price | specs | reviews"}
            },
            "required": ["query"]
        }
    },
    {
        "name": "weather_report",
        "description": "Gives the weather report to user",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "city": {"type": "STRING", "description": "City name"}
            },
            "required": ["city"]
        }
    },
    {
        "name": "system_status",
        "description": (
            "Returns real-time system metrics: CPU usage, RAM, GPU load, CPU temperature, "
            "uptime, and process count. Use when the user asks about computer performance, "
            "temperature, memory, or resource usage."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {},
        }
    },
    {
        "name": "add_monitor",
        "description": (
            "Starts monitoring a topic. SIRIUS checks it once a day via news search "
            "and alerts the user when there is a new development. Use when the user "
            "says 'monitor X', 'track X', 'acompanha notícias de X'. "
            "Do NOT add crypto, financial, or trading topics."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "topic": {"type": "STRING", "description": "Topic to monitor (e.g. 'space exploration', 'AI news')"}
            },
            "required": ["topic"]
        }
    },
    {
        "name": "remove_monitor",
        "description": (
            "Stops monitoring a previously added topic. Use when the user says "
            "'stop monitoring X', 'para de monitorar X'."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "topic": {"type": "STRING", "description": "Topic to stop monitoring"}
            },
            "required": ["topic"]
        }
    },
    {
        "name": "list_monitors",
        "description": "Lists all topics currently being monitored.",
        "parameters": {
            "type": "OBJECT",
            "properties": {}
        }
    },
    {
        "name": "send_message",
        "description": "Sends a text message via WhatsApp, Telegram, or other messaging platform.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "receiver":     {"type": "STRING", "description": "Recipient contact name"},
                "message_text": {"type": "STRING", "description": "The message to send"},
                "platform":     {"type": "STRING", "description": "Platform: WhatsApp, Telegram, etc."}
            },
            "required": ["receiver", "message_text", "platform"]
        }
    },
    {
        "name": "reminder",
        "description": "Sets a timed reminder using Task Scheduler.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "date":    {"type": "STRING", "description": "Date in YYYY-MM-DD format"},
                "time":    {"type": "STRING", "description": "Time in HH:MM format (24h)"},
                "message": {"type": "STRING", "description": "Reminder message text"}
            },
            "required": ["date", "time", "message"]
        }
    },
    {
        "name": "send_to_phone",
        "description": (
            "Sends a message/notification to the user's phone (SIRIUS companion app). "
            "Use when the user asks to send something to their phone/celular, or to "
            "deliver a note they'll see away from the PC."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "message": {"type": "STRING", "description": "Message text to deliver"}
            },
            "required": ["message"]
        }
    },
    {
        "name": "youtube_video",
        "description": (
            "Controls YouTube. Use for: playing videos, summarizing a video's content, "
            "getting video info, or showing trending videos."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "action": {"type": "STRING", "description": "play | summarize | get_info | trending (default: play)"},
                "query":  {"type": "STRING", "description": "Search query for play action"},
                "save":   {"type": "BOOLEAN", "description": "Save summary to Notepad (summarize only)"},
                "region": {"type": "STRING", "description": "Country code for trending e.g. TR, US"},
                "url":    {"type": "STRING", "description": "Video URL for get_info action"},
            },
            "required": []
        }
    },
    {
        "name": "screen_process",
        "description": (
            "Captures and analyzes the screen or webcam image. "
            "MUST be called when user asks what is on screen, what you see, "
            "analyze my screen, look at camera, etc. "
            "You have NO visual ability without this tool. "
            "After calling this tool, stay SILENT — the vision module speaks directly."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "angle": {"type": "STRING", "description": "'screen' to capture display, 'camera' for webcam. Default: 'screen'"},
                "text":  {"type": "STRING", "description": "The question or instruction about the captured image"}
            },
            "required": ["text"]
        }
    },
    {
        "name": "close_camera",
        "description": "Closes the live camera feed / webcam view. Call when user says close camera, stop camera, turn off camera.",
        "parameters": {
            "type": "OBJECT",
            "properties": {}
        }
    },
    {
        "name": "computer_settings",
        "description": (
            "Controls the computer: volume, brightness, window management, keyboard shortcuts, "
            "typing text on screen, closing apps, fullscreen, dark mode, WiFi, restart, shutdown, "
            "scrolling, tab management, zoom, screenshots, lock screen, refresh/reload page. "
            "Use for ANY single computer control command. NEVER route to agent_task."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "action":      {"type": "STRING", "description": "The action to perform"},
                "description": {"type": "STRING", "description": "Natural language description of what to do"},
                "value":       {"type": "STRING", "description": "Optional value: volume level, text to type, application name for minimize/maximize/close, etc."}
            },
            "required": []
        }
    },
    {
        "name": "browser_control",
        "description": (
            "Controls any web browser. This tool handles EVERYTHING related to web browsing: "
            "opening sites, searching, interacting with pages, and managing browser sessions. "
            "If the browser is not open, this tool will launch it. "
            "Always pass the 'browser' parameter when the user specifies a browser (e.g. 'Brave', 'Edge'). "
            "If the browser is already open, it will use the active session. "
            "CRITICAL: When the user wants to buy something, use browser_control to navigate "
            "to a shopping site (e.g. Mercado Livre, Amazon, Buscapé) showing the products "
            "and prices directly on screen. "
            "NEW ACTIONS: 'upload' for file uploads (input[type=file]), 'wait' to wait for "
            "elements, 'download' to download files, 'script' to run multi-step workflows "
            "in one call. "
            "Use 'headless: true' for invisible scraping tasks, 'headless: false' (default) "
            "for visible UI automation."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "action":      {"type": "STRING", "description": (
                    "go_to | search | click | type | scroll | fill_form | "
                    "smart_click | smart_type | get_text | get_url | press | "
                    "new_tab | close_tab | screenshot | back | forward | reload | "
                    "switch | list_browsers | close | close_all | upload | wait | "
                    "download | script"
                )},
                "browser":     {"type": "STRING", "description": (
                    "Target browser: chrome | edge | firefox | opera | "
                    "operagx | brave | vivaldi | safari. "
                    "Omit to use the currently active browser."
                )},
                "url":         {"type": "STRING", "description": "URL for go_to / new_tab action"},
                "query":       {"type": "STRING", "description": "Search query for search action"},
                "engine":      {"type": "STRING", "description": (
                    "Search engine: google | bing | duckduckgo | yandex (default: google)"
                )},
                "selector":    {"type": "STRING", "description": "CSS selector for click/type/upload/download/wait"},
                "text":        {"type": "STRING", "description": "Text to click or type"},
                "description": {"type": "STRING", "description": "Element description for smart_click/smart_type"},
                "direction":   {"type": "STRING", "description": "up | down for scroll"},
                "amount":      {"type": "INTEGER", "description": "Scroll amount in pixels (default: 500)"},
                "key":         {"type": "STRING", "description": "Key name for press action (e.g. Enter, Escape, F5)"},
                "path":        {"type": "STRING", "description": (
                    "Save path for screenshot OR file path for upload action"
                )},
                "incognito":   {"type": "BOOLEAN", "description": "Open in private/incognito mode"},
                "clear_first": {"type": "BOOLEAN", "description": "Clear field before typing (default: true)"},
                "headless":    {"type": "BOOLEAN", "description": (
                    "Run browser invisible (default: false). Use true for scraping."
                )},
                "state":       {"type": "STRING", "description": (
                    "Element state for wait action: visible | hidden | attached | detached (default: visible)"
                )},
                "timeout":     {"type": "INTEGER", "description": "Timeout in ms for wait action (default: 30000)"},
                "steps":       {"type": "ARRAY", "description": (
                    "Array of step objects for script action. "
                    "Each step: {action, url, selector, text, path, ...}"
                ), "items": {"type": "OBJECT"}},
            },
            "required": ["action"]
        }
    },
    {
        "name": "file_controller",
        "description": "Manages files and folders: list, create, delete, move, copy, rename, read, write, find, disk usage.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "action":      {"type": "STRING", "description": "list | create_file | create_folder | delete | move | copy | rename | read | write | find | largest | disk_usage | organize_desktop | info"},
                "path":        {"type": "STRING", "description": "File/folder path or shortcut: desktop, downloads, documents, home"},
                "destination": {"type": "STRING", "description": "Destination path for move/copy"},
                "new_name":    {"type": "STRING", "description": "New name for rename"},
                "content":     {"type": "STRING", "description": "Content for create_file/write"},
                "name":        {"type": "STRING", "description": "File name to search for"},
                "extension":   {"type": "STRING", "description": "File extension to search (e.g. .pdf)"},
                "count":       {"type": "INTEGER", "description": "Number of results for largest"},
            },
            "required": ["action"]
        }
    },
    {
        "name": "desktop_control",
        "description": "Controls the desktop: wallpaper, organize, clean, list, stats.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "action": {"type": "STRING", "description": "wallpaper | wallpaper_url | organize | clean | list | stats | task"},
                "path":   {"type": "STRING", "description": "Image path for wallpaper"},
                "url":    {"type": "STRING", "description": "Image URL for wallpaper_url"},
                "mode":   {"type": "STRING", "description": "by_type or by_date for organize"},
                "task":   {"type": "STRING", "description": "Natural language desktop task"},
            },
            "required": ["action"]
        }
    },
    {
        "name": "code_helper",
        "description": "Writes, edits, explains, runs, or builds code files.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "action":      {"type": "STRING", "description": "write | edit | explain | run | build | auto (default: auto)"},
                "description": {"type": "STRING", "description": "What the code should do or what change to make"},
                "language":    {"type": "STRING", "description": "Programming language (default: python)"},
                "output_path": {"type": "STRING", "description": "Where to save the file"},
                "file_path":   {"type": "STRING", "description": "Path to existing file for edit/explain/run/build"},
                "code":        {"type": "STRING", "description": "Raw code string for explain"},
                "args":        {"type": "STRING", "description": "CLI arguments for run/build"},
                "timeout":     {"type": "INTEGER", "description": "Execution timeout in seconds (default: 30)"},
            },
            "required": ["action"]
        }
    },
    {
        "name": "dev_agent",
        "description": "Builds complete multi-file projects from scratch: plans, writes files, installs deps, opens VSCode, runs and fixes errors.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "description":  {"type": "STRING", "description": "What the project should do"},
                "language":     {"type": "STRING", "description": "Programming language (default: python)"},
                "project_name": {"type": "STRING", "description": "Optional project folder name"},
                "timeout":      {"type": "INTEGER", "description": "Run timeout in seconds (default: 30)"},
            },
            "required": ["description"]
        }
    },
    {
        "name": "agent_task",
        "description": (
            "Executes complex multi-step tasks requiring multiple different tools. "
            "Examples: 'research X and save to file', 'find and organize files'. "
            "DO NOT use for single commands. NEVER use for Steam/Epic — use game_updater."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "goal":     {"type": "STRING", "description": "Complete description of what to accomplish"},
                "priority": {"type": "STRING", "description": "low | normal | high (default: normal)"}
            },
            "required": ["goal"]
        }
    },
    {
        "name": "computer_control",
        "description": "Direct computer control: type, click, hotkeys, scroll, move mouse, screenshots, find elements on screen.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "action":      {"type": "STRING", "description": "type | smart_type | click | double_click | right_click | hotkey | press | scroll | move | copy | paste | screenshot | wait | clear_field | focus_window | screen_find | screen_click | random_data | user_data"},
                "text":        {"type": "STRING", "description": "Text to type or paste"},
                "x":           {"type": "INTEGER", "description": "X coordinate"},
                "y":           {"type": "INTEGER", "description": "Y coordinate"},
                "keys":        {"type": "STRING", "description": "Key combination e.g. 'ctrl+c'"},
                "key":         {"type": "STRING", "description": "Single key e.g. 'enter'"},
                "direction":   {"type": "STRING", "description": "up | down | left | right"},
                "amount":      {"type": "INTEGER", "description": "Scroll amount (default: 3)"},
                "seconds":     {"type": "NUMBER",  "description": "Seconds to wait"},
                "title":       {"type": "STRING",  "description": "Window title for focus_window"},
                "description": {"type": "STRING",  "description": "Element description for screen_find/screen_click"},
                "type":        {"type": "STRING",  "description": "Data type for random_data"},
                "field":       {"type": "STRING",  "description": "Field for user_data: name|email|city"},
                "clear_first": {"type": "BOOLEAN", "description": "Clear field before typing (default: true)"},
                "path":        {"type": "STRING",  "description": "Save path for screenshot"},
            },
            "required": ["action"]
        }
    },
    {
        "name": "game_updater",
        "description": (
            "THE ONLY tool for ANY Steam or Epic Games request. "
            "Use for: installing, downloading, updating games, listing installed games, "
            "checking download status, scheduling updates. "
            "ALWAYS call directly for any Steam/Epic/game request. "
            "NEVER use agent_task, browser_control, or web_search for Steam/Epic."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "action":    {"type": "STRING",  "description": "update | install | list | download_status | schedule | cancel_schedule | schedule_status (default: update)"},
                "platform":  {"type": "STRING",  "description": "steam | epic | both (default: both)"},
                "game_name": {"type": "STRING",  "description": "Game name (partial match supported)"},
                "app_id":    {"type": "STRING",  "description": "Steam AppID for install (optional)"},
                "hour":      {"type": "INTEGER", "description": "Hour for scheduled update 0-23 (default: 3)"},
                "minute":    {"type": "INTEGER", "description": "Minute for scheduled update 0-59 (default: 0)"},
                "shutdown_when_done": {"type": "BOOLEAN", "description": "Shut down PC when download finishes"},
            },
            "required": []
        }
    },
    {
        "name": "flight_finder",
        "description": "Searches Google Flights and speaks the best options.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "origin":      {"type": "STRING",  "description": "Departure city or airport code"},
                "destination": {"type": "STRING",  "description": "Arrival city or airport code"},
                "date":        {"type": "STRING",  "description": "Departure date (any format)"},
                "return_date": {"type": "STRING",  "description": "Return date for round trips"},
                "passengers":  {"type": "INTEGER", "description": "Number of passengers (default: 1)"},
                "cabin":       {"type": "STRING",  "description": "economy | premium | business | first"},
                "save":        {"type": "BOOLEAN", "description": "Save results to Notepad"},
            },
            "required": ["origin", "destination", "date"]
        }
    },
    {
        "name": "hide_interface",
        "description": (
            "Hides the interface window to the system tray. "
            "The assistant continues running silently in the background. "
            "User can restore the window from the system tray icon. "
            "Call this when the user says goodbye like tchau, até logo, "
            "pode fechar, or expresses intent to close the interface "
            "but NOT to terminate the system. "
            "The user can say this in ANY language. "
            "If the user explicitly says 'fechar tudo' or wants to "
            "shut down everything, use shutdown_sirius instead."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {},
        }
    },
    {
        "name": "shutdown_sirius",
        "description": (
            "Shuts down the assistant completely — closes the interface "
            "AND terminates the backend process. "
            "Call this ONLY when the user explicitly says 'fechar tudo', "
            "'desligar tudo', 'shut down completely', or makes it clear "
            "they want to stop the entire system. "
            "DO NOT call this for simple goodbyes like 'tchau' or 'até logo' "
            "— use hide_interface instead."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {},
        }
    },
    {
    "name": "file_processor",
    "description": (
        "Processes any file that the user has uploaded or dropped onto the interface. "
        "Use this when the user refers to an uploaded file and wants an action on it. "
        "Supports: images (describe/ocr/resize/compress/convert), "
        "PDFs (summarize/extract_text/to_word), "
        "Word docs & text files (summarize/fix/reformat/translate), "
        "CSV/Excel (analyze/stats/filter/sort/convert), "
        "JSON/XML (validate/format/analyze), "
        "code files (explain/review/fix/optimize/run/document/test), "
        "audio (transcribe/trim/convert/info), "
        "video (trim/extract_audio/extract_frame/compress/transcribe/info), "
        "archives (list/extract), "
        "presentations (summarize/extract_text). "
        "ALWAYS call this tool when a file has been uploaded and the user gives a command about it. "
        "If the user's command is ambiguous, pick the most logical action for that file type."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "file_path": {
                "type": "STRING",
                "description": "Full path to the uploaded file. Leave empty to use the currently uploaded file."
            },
            "action": {
                "type": "STRING",
                "description": (
                    "What to do with the file. Examples by type:\n"
                    "image: describe | ocr | resize | compress | convert | info\n"
                    "pdf: summarize | extract_text | to_word | info\n"
                    "docx/txt: summarize | fix | reformat | translate_hint | word_count | to_bullet\n"
                    "csv/excel: analyze | stats | filter | sort | convert | info\n"
                    "json: validate | format | analyze | to_csv\n"
                    "code: explain | review | fix | optimize | run | document | test\n"
                    "audio: transcribe | trim | convert | info\n"
                    "video: trim | extract_audio | extract_frame | compress | transcribe | info | convert\n"
                    "archive: list | extract\n"
                    "pptx: summarize | extract_text | analyze"
                )
            },
            "instruction": {
                "type": "STRING",
                "description": "Free-form instruction if action doesn't cover it. E.g. 'translate this to Turkish', 'find all email addresses'"
            },
            "format": {
                "type": "STRING",
                "description": "Target format for conversion. E.g. 'mp3', 'pdf', 'csv', 'png'"
            },
            "width":     {"type": "INTEGER", "description": "Target width for image resize"},
            "height":    {"type": "INTEGER", "description": "Target height for image resize"},
            "scale":     {"type": "NUMBER",  "description": "Scale factor for image resize (e.g. 0.5)"},
            "quality":   {"type": "INTEGER", "description": "Quality 1-100 for image/video compress"},
            "start":     {"type": "STRING",  "description": "Start time for trim: seconds or HH:MM:SS"},
            "end":       {"type": "STRING",  "description": "End time for trim: seconds or HH:MM:SS"},
            "timestamp": {"type": "STRING",  "description": "Timestamp for video frame extraction HH:MM:SS"},
            "column":    {"type": "STRING",  "description": "Column name for CSV filter/sort"},
            "value":     {"type": "STRING",  "description": "Filter value for CSV filter"},
            "condition": {"type": "STRING",  "description": "Filter condition: equals|contains|gt|lt"},
            "ascending": {"type": "BOOLEAN", "description": "Sort order for CSV sort (default: true)"},
            "save":      {"type": "BOOLEAN", "description": "Save result to file (default: true)"},
            "destination": {"type": "STRING", "description": "Output folder for archive extract"},
        },
        "required": []
    }
},
    {
        "name": "save_memory",
        "description": (
            "Save an important personal fact about the user to long-term memory. "
            "Call this silently whenever the user reveals something worth remembering: "
            "name, age, city, job, preferences, hobbies, relationships, projects, or future plans. "
            "Do NOT call for: weather, reminders, searches, or one-time commands. "
            "Do NOT announce that you are saving — just call it silently. "
            "Values must be in English regardless of the conversation language."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "category": {
                    "type": "STRING",
                    "description": (
                        "identity — name, age, birthday, city, job, language, nationality | "
                        "preferences — favorite food/color/music/film/game/sport, hobbies | "
                        "projects — active projects, goals, things being built | "
                        "relationships — friends, family, partner, colleagues | "
                        "wishes — future plans, things to buy, travel dreams | "
                        "notes — habits, schedule, anything else worth remembering"
                    )
                },
                "key":   {"type": "STRING", "description": "Short snake_case key (e.g. name, favorite_food, sister_name)"},
                "value": {"type": "STRING", "description": "Concise value in English (e.g. Fatih, pizza, older sister)"},
            },
            "required": ["category", "key", "value"]
        }
    },
    {
        "name": "google_calendar",
        "description": "Manages the user's Google Calendar: list events, create events. Use when the user mentions Google Calendar.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "action":   {"type": "STRING", "description": "list | create"},
                "days":     {"type": "INTEGER", "description": "Number of days to list (for list)"},
                "summary":  {"type": "STRING", "description": "Title of the event (for create)"},
                "start":    {"type": "STRING", "description": "Start time in ISO format (for create)"},
                "end":      {"type": "STRING", "description": "End time in ISO format (for create)"},
                "location": {"type": "STRING", "description": "Location (for create)"},
            },
            "required": ["action"]
        }
    },
    {
        "name": "notion_calendar",
        "description": "Manages the user's Notion database calendar: list, create, complete events, list available databases. Use when the user mentions Notion calendar or agenda.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "action":   {"type": "STRING", "description": "list | create | list_databases | complete"},
                "database_id": {"type": "STRING", "description": "ID do banco de dados Notion (opcional, configurado nas settings se omitido)"},
                "data_source_id": {"type": "STRING", "description": "ID of the Notion data source (optional, resolved from database_id if omitted)"},
                "days":     {"type": "INTEGER", "description": "Number of days to list (for list)"},
                "date":     {"type": "STRING", "description": "Date in YYYY-MM-DD format or 'hoje'/'amanhã' (for list)"},
                "summary":  {"type": "STRING", "description": "Title of the event (for create)"},
                "start_time": {"type": "STRING", "description": "Start time in YYYY-MM-DD HH:MM format (for create)"},
                "end_time":   {"type": "STRING", "description": "End time in YYYY-MM-DD HH:MM format (for create)"},
                "page_id":  {"type": "STRING", "description": "ID of the page to complete (for complete)"},
                "search_title": {"type": "STRING", "description": "Title text to search for (for complete, falls back to page_id)"},
            },
            "required": ["action"]
        }
    },
    {
        "name": "gmail",
        "description": "Accesses and manages the user's Gmail: list emails, search, read email.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "action": {"type": "STRING", "description": "list | search | read"},
                "count":  {"type": "INTEGER", "description": "Number of emails to list/search"},
                "query":  {"type": "STRING", "description": "Search query"},
                "id":     {"type": "STRING", "description": "Email ID to read"},
            },
            "required": ["action"]
        }
    },
    {
        "name": "workspaces",
        "description": "Salva ou abre conjuntos de aplicativos (espaços de trabalho).",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "action": {"type": "STRING", "description": "save | open | list | delete"},
                "name":   {"type": "STRING", "description": "Nome do espaço (ex: trabalho, estudo, filmes)"}
            },
            "required": ["action", "name"]
        }
    },
    {
        "name": "deep_research",
        "description": (
            "Performs deep web research to find potential freelance clients or businesses "
            "based on the user's competencies, target audience, and region. Returns a structured list. "
            "IMPORTANT: Use what you know about the user from memory/context. Only ask for clarification "
            "on a specific parameter if you are truly uncertain about it. Prefer to make reasonable assumptions "
            "based on previous conversations rather than asking upfront."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "competencies":    {"type": "STRING", "description": "User's skills or competencies (e.g. 'Web Developer', 'React')"},
                "target_audience": {"type": "STRING", "description": "Target business or niche (e.g. 'clínicas médicas', 'e-commerce')"},
                "region":          {"type": "STRING", "description": "Target location (e.g. 'São Paulo', 'Brasil', 'remoto')"}
            },
            "required": ["competencies", "target_audience", "region"]
        }
    },
    {
        "name": "linkedin_jobs_radar",
        "description": (
            "Busca, filtra e analisa vagas no LinkedIn de forma inteligente e humanizada. "
            "Use para buscar vagas (keywords), analisar compatibilidade de vagas salvas, ou listar/abrir o painel."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "action": {"type": "STRING", "description": "search (default) | analyze | list"},
                "keywords": {"type": "STRING", "description": "Termos de busca de vaga (ex: 'Desenvolvedor React', 'Python Junior')"}
            },
            "required": []
        }
    },
    {
        "name": "apply_assist",
        "description": (
            "Auxilia no processo de candidatura para uma vaga de emprego específica. "
            "Pode gerar cover letters sob medida, dar conselhos para adaptar o currículo para passar no ATS, ou preparar perguntas de entrevista."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "job_title": {"type": "STRING", "description": "Título da vaga de emprego"},
                "company": {"type": "STRING", "description": "Nome da empresa contratante"},
                "job_description": {"type": "STRING", "description": "Descrição completa dos requisitos e responsabilidades da vaga"},
                "mode": {"type": "STRING", "description": "cover_letter (default) | resume_tailor | interview_prep"}
            },
            "required": []
        }
    },
    {
        "name": "business_radar",
        "description": (
            "Busca empresas no Google Maps e analisa potencial de compra de sites. "
            "Use para prospectar (search), analisar compatibilidade (analyze), listar/abrir painel (list), ou exportar dados (export)."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "action": {"type": "STRING", "description": "search (default) | analyze | list | export"},
                "estado": {"type": "STRING", "description": "Estado alvo (ex: SP, RJ, MG)"}
            },
            "required": []
        }
    },
    {
        "name": "freela_arsenal",
        "description": (
            "Orquestrador completo de prospecção de freelas. "
            "Combina Google Maps (navegador visível — encontra empresas sem site para prospecção ativa via WhatsApp), "
            "Deep Research (leads de freelance na web), e análise unificada. "
            "Use para achar freelas, prospectar clientes, ou ambos. "
            "IMPORTANTE: Mostra progresso no log. Use o que sabe do usuário por contexto/memória. "
            "Só pergunte se realmente não souber. Prefira assumir com base no histórico."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "objetivo": {
                    "type": "STRING",
                    "description": "'tudo' (default) | 'prospectar_clientes' | 'achar_vagas' | 'so_maps'"
                },
                "competencias": {
                    "type": "STRING",
                    "description": "Suas habilidades (ex: 'React, Python, Django')"
                },
                "target_audience": {
                    "type": "STRING",
                    "description": "Nicho de clientes (ex: 'restaurantes, pet shops')"
                },
                "segmentos": {
                    "type": "STRING",
                    "description": "Segmentos para buscar no Maps (ex: 'restaurante, pet shop')"
                },
                "cidade": {
                    "type": "STRING",
                    "description": "Cidade para prospecção (ex: 'Belo Horizonte')"
                },
                "regiao": {
                    "type": "STRING",
                    "description": "Região para deep research (ex: 'São Paulo', 'Brasil')"
                },
                "max_resultados": {
                    "type": "STRING",
                    "description": "Limite por segmento no Maps (default: 10, máx: 30)"
                },
                "mostrar_navegador": {
                    "type": "STRING",
                    "description": "'true' (default) para ver o Chrome abrindo, 'false' para headless"
                },
                "detalhado": {
                    "type": "STRING",
                    "description": "'true' para listar empresas no relatório"
                },
                "gerar_arquivos": {
                    "type": "STRING",
                    "description": "'true' (default) para salvar CSV/TXT, 'false' para não salvar"
                }
            },
            "required": []
        }
    },
    {
        "name": "obsidian_notes_search",
        "description": (
            "Busca nas notas do Obsidian do usuário (vault configurado nas integrações). "
            "Use quando o usuário perguntar sobre o conteúdo das anotações dele no Obsidian, "
            "ex: 'o que tenho anotado sobre X?', 'procure nas minhas notas por Y'. "
            "Retorna os trechos mais relevantes com o caminho da nota."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "query": {
                    "type": "STRING",
                    "description": "Termo/tema para buscar nas notas. Deixe vazio para listar as notas mais recentes."
                },
                "limit": {
                    "type": "INTEGER",
                    "description": "Máximo de resultados (default: 5)"
                }
            },
            "required": ["query"]
        }
    },
    {
        "name": "obsidian_tasks_list",
        "description": (
            "Lista as tarefas pendentes do Obsidian do usuário. "
            "Use quando o usuário perguntar sobre tarefas/afazeres anotados no vault dele."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {}
        }
    },
    {
        "name": "agents_control",
        "description": (
            "Controla terminais interativos de agentes de IA (Claude, Codex, Cursor, OpenCode, Sirius). "
            "Use para criar terminais, enviar prompts, ou listar terminais ativos. "
            "Cada terminal roda o CLI do agente em modo interativo."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "action":     {"type": "STRING", "description": "create | send_prompt | close | list"},
                "agent":      {"type": "STRING", "description": "claude | codex | cursor | opencode | sirius (default: claude)"},
                "prompt":     {"type": "STRING", "description": "Prompt para enviar ao agente (para send_prompt ou create+prompt)"},
                "session_id": {"type": "STRING", "description": "ID da sessao (para close)"},
            },
            "required": ["action"]
        }
    },
]

class SiriusLive:

    def __init__(self, ui: SiriusUI):
        import queue as _queue
        self.ui             = ui
        self.session        = None
        self._resumption_handle = None     # last Live API resumption handle (survives rotations)
        self._reconnect_attempts = 0       # consecutive failed connects (drives backoff)
        self.audio_in_queue = None
        self.out_queue      = None
        self._loop          = None
        self._is_speaking   = False
        self._speaking_lock = threading.Lock()
        self._first_run     = True
        self._phone_active     = False   # True while phone mic is streaming; pauses PC mic
        self._dashboard        = None
        self._dashboard_ready  = threading.Event()
        # If the early dashboard thread already started, link its ready event
        if _DASHBOARD_READY.is_set() or _DASHBOARD is not None:
            self._dashboard_ready.set()
        self.ui.on_text_command   = self._on_text_command
        self.ui.on_remote_clicked = self._make_remote_key
        self.ui.on_interrupt      = self.interrupt
        self.ui.on_briefing_dismiss = self._on_briefing_dismiss
        self._briefing_dismissed_event: asyncio.Event | None = None
        self._turn_done_event: asyncio.Event | None = None
        self._allow_mic: asyncio.Event | None = None
        self._tts           = None                  # LOCAL TTS DISABLED in Live mode — Gemini handles all voice
        self._tts_queue     = _queue.Queue()
        self._tts_ready     = threading.Event()
        self._tts_busy       = threading.Event()   # UNUSED in Live mode — kept for API compat
        self._gemini_turn    = threading.Event()   # set while Gemini is producing audio for a turn
        self._conv_id        = None                # DB conversation id for current session
        self._restart_event  = threading.Event()   # set to force session restart
        self._briefing_sent     = False              # morning briefing fires once per process
        self._interrupted       = False              # True while draining audio after user interrupt
        self._pending_vision    = None               # (img_bytes, mime_type, question, angle) to inject after tool response
        self._vision_cam_active = False              # True if camera was opened for vision → auto-close after response
        self._vision_close_pending = False           # True after vision injected; next turn_complete closes camera
        self._vision_last_time  = 0.0                # monotonic time of last screen_process call (cooldown guard)
        self._vision_busy       = False              # True while a vision capture/inject cycle is in flight
        self._ui_visible = False                    # track if UI window is visible
        self._greeting_sent = False                 # ensure greeting runs only once per UI session
        # Register callback for UI visibility changes
        self.ui.on_visibility = self._on_visibility_from_ws
        self._fft_mic_counter = 0
        self._fft_tts_counter = 0
        self._last_user_speech = 0.0

        # Proactive engine 2.0 (context rotation, time-of-day, monitors)
        from actions.proactive import ProactiveEngine
        self._proactive = ProactiveEngine()

        # Plugin registry (discover once at startup; enable/disable re-read per call)
        from core.plugin_loader import discover_plugins
        _core_names    = {d["name"] for d in TOOL_DECLARATIONS}
        _plugins_dir   = Path(__file__).resolve().parent / "plugins"
        self._plugin_registry = discover_plugins(
            _plugins_dir,
            _core_names,
            logger=lambda m: (print(f"[Plugins] {m}"), self.ui.write_log(f"SYS: {m}")),
            bundled_module_names=_BUNDLED_PLUGIN_MODULES,
        )

        # LOCAL TTS DISABLED — Gemini Live provides all voice output natively.
        # Do NOT start _lazy_init_tts or _tts_worker threads here.

    def _make_remote_key(self):
        """Generate remote key + QR data. Uses shared dashboard if available, else fallback."""
        global _DASHBOARD, _DASHBOARD_READY
        print(f"[DEBUG _make_remote_key] Called. _DASHBOARD={_DASHBOARD is not None}, self._dashboard={self._dashboard is not None}")

        # Wait up to 5s for the dashboard server to start listening
        # Check both the local event (session dashboard) and global (early dashboard)
        if _DASHBOARD is not None:
            _DASHBOARD_READY.wait(timeout=5.0)
        else:
            self._dashboard_ready.wait(timeout=5.0)

        # Verify the port is actually open
        port_open = _is_port_open()
        print(f"[DEBUG _make_remote_key] Port 8000 open={port_open}")

        if _DASHBOARD is not None:
            if not port_open:
                print("[DEBUG _make_remote_key] WARNING: _DASHBOARD exists but port 8000 not listening!")
            key    = _DASHBOARD.new_key()
            url    = _DASHBOARD.get_url()
            manual = _DASHBOARD.get_manual_url()
            login_url = f"{url}/auto-login?key={key}"
            print(f"[DEBUG _make_remote_key] Using _DASHBOARD. url={url}, key={key}, login_url={login_url}")
            return url, key, login_url, manual

        if self._dashboard is not None:
            if not port_open:
                print("[DEBUG _make_remote_key] WARNING: self._dashboard exists but port 8000 not listening!")
            key    = self._dashboard.new_key()
            url    = self._dashboard.get_url()
            manual = self._dashboard.get_manual_url()
            login_url = f"{url}/auto-login?key={key}"
            print(f"[DEBUG _make_remote_key] Using self._dashboard. url={url}, key={key}, login_url={login_url}")
            return url, key, login_url, manual

        # Fallback: generate key locally without DashboardServer
        print("[DEBUG _make_remote_key] FALLBACK path — no dashboard object at all")
        import secrets
        import string

        _key_chars = [c for c in (string.ascii_uppercase + string.digits)
                      if c not in ('O', 'I', 'L', '0', '1')]
        key = ''.join(secrets.choice(_key_chars) for _ in range(6))

        ip = _detect_lan_ip()
        port = 8000
        url = f"http://{ip}:{port}"
        manual = f"{ip}:{port}"
        login_url = f"{url}/auto-login?key={key}"
        print(f"[DEBUG _make_remote_key] FALLBACK url={url}, key={key}, login_url={login_url}")

        return url, key, login_url, manual

    def _on_phone_connected(self) -> None:
        self.ui.write_log("SYS: Phone connected via Remote Dashboard.")
        self.ui.notify_phone_connected()

    def _on_pair_request(self, info: dict) -> None:
        """Companion app requested manual pairing — show prompt in the React UI."""
        try:
            _ws.notify_pair_request(info)
            self.ui.write_log(
                f"SYS: Pareamento solicitado por {info.get('name', 'dispositivo')} — aprove no popup."
            )
        except Exception as e:
            print(f"[Dashboard] notify pair_request failed: {e}")

    def _on_pair_decision(self, device_id: str, approve: bool) -> None:
        """React UI answered a pair_request (approve/reject)."""
        dash = getattr(self, "_dashboard", None) or _DASHBOARD
        if dash is not None:
            dash.schedule_pair_approval(device_id, approve)

    def _on_text_command(self, text: str):
        self.ui.write_log(f"You: {text}")
        if not self._loop or not self.session:
            return
        asyncio.run_coroutine_threadsafe(
            self.session.send_client_content(
                turns={"parts": [{"text": text}]},
                turn_complete=True
            ),
            self._loop
        )

    def _on_visibility_from_ws(self, visible: bool) -> None:
        self._ui_visible = visible

    def _lazy_init_tts(self):
        from core.config_loader import get_all_config
        from core.tts import create_tts_player, set_audio_chunk_callback
        try:
            config = get_all_config()
            self._tts = create_tts_player(config)
            set_audio_chunk_callback(self._on_tts_audio_chunk)
        except Exception as e:
            print(f"[SiriusLive] TTS init error: {e}")
        finally:
            self._tts_ready.set()

    def _on_tts_audio_chunk(self, audio: np.ndarray) -> None:
        self._fft_tts_counter += 1
        if self._fft_tts_counter >= _SEND_FFT_INTERVAL:
            self._fft_tts_counter = 0
            bins = compute_fft_bins(audio)
            self.ui.send_audio_bins(bins, "tts")

    def _tts_worker(self):
        self._tts_ready.wait(timeout=120)
        while True:
            text = self._tts_queue.get()
            try:
                if text and self._tts:
                    # Wait for any active Gemini turn to finish before speaking locally
                    # Timeout of 10s to avoid deadlock if _gemini_turn never clears
                    waited = 0
                    while self._gemini_turn.is_set() and waited < 100:
                        self._gemini_turn.wait(timeout=0.5)
                        waited += 1
                    if self._gemini_turn.is_set():
                        print("[TTS] _gemini_turn still set after 50s — forcing clear")
                        self._gemini_turn.clear()
                    self._tts_busy.set()
                    self._tts.speak(text, on_start=lambda: self.set_speaking(True), on_done=lambda: self.set_speaking(False))
            except Exception as e:
                print(f"[TTS] speak error: {e}")
            finally:
                self._tts_busy.clear()

    def set_speaking(self, value: bool):
        with self._speaking_lock:
            self._is_speaking = value
        if value:
            self.ui.set_state("SPEAKING")
        elif not self.ui.muted:
            self.ui.set_state("LISTENING")

    def speak(self, text: str):
        # LOCAL TTS DISABLED in Live mode — Gemini handles all voice output.
        # Tools call speak() for progress updates; we silently ignore them
        # to avoid a second (local TTS) voice overlapping with Gemini's.
        if text:
            self.ui.write_log(f"[SIRIUS] {text}")

    def interrupt(self) -> None:
        """Stop the assistant mid-speech. Drains audio queue and resets state."""
        self._interrupted = True
        # Drain the audio output queue
        while not self.audio_in_queue.empty():
            try:
                self.audio_in_queue.get_nowait()
            except (asyncio.QueueEmpty, AttributeError):
                break
        self.set_speaking(False)
        if self._turn_done_event and not self._turn_done_event.is_set():
            self._turn_done_event.set()
        self.ui.write_log("SYS: Interrompido — ouvindo.")

    def request_restart(self) -> None:
        """Signal the run loop to disconnect and reconnect (picks up new config)."""
        self._restart_event.set()

    def speak_error(self, tool_name: str, error: str):
        short = str(error)[:120]
        self.ui.write_log(f"ERR: {tool_name} — {short}")
        self.speak(f"Sir, {tool_name} encountered an error. {short}")

    @staticmethod
    def _merge_segments(segments: list[str]) -> str:
        """Merge incremental transcript segments, removing overlapping text."""
        if not segments:
            return ""
        result = segments[0]
        for seg in segments[1:]:
            overlap = 0
            for i in range(min(len(result), len(seg)), 0, -1):
                if result[-i:] == seg[:i]:
                    overlap = i
                    break
            if overlap:
                result += seg[overlap:]
            else:
                # No overlap — likely incremental words; join with space
                if result and seg:
                    result += " " + seg
                else:
                    result += seg
        return result.strip()

    def _build_config(self) -> types.LiveConnectConfig:
        from memory.config_manager import get_user_name

        memory     = load_memory()
        mem_str    = format_memory_for_prompt(memory)
        sys_prompt = _load_system_prompt()

        time_ctx = _now_context_str() + "\n\n"

        # Identity injection
        _asst_name = get_assistant_name()
        _user_name = get_user_name()
        _addr = (f"ADDRESS: Always call the user '{_user_name}'."
                 if _user_name
                 else "ADDRESS: Say 'sir' or 'ma'am' when addressing the user. Never mix languages.")
        identity_ctx = (
            f"[IDENTITY]\n"
            f"Your name is {_asst_name}. "
            f"Always refer to yourself as {_asst_name}.\n"
            f"{_addr}\n\n"
        )

        parts = [time_ctx, identity_ctx]
        if mem_str:
            parts.append(mem_str)
        parts.append(sys_prompt)

        return types.LiveConnectConfig(
            response_modalities=["AUDIO"],
            output_audio_transcription={},
            input_audio_transcription={},
            system_instruction="\n".join(parts),
            tools=[{"function_declarations": TOOL_DECLARATIONS + self._plugin_registry.get_tool_declarations()}],
            speech_config=types.SpeechConfig(
                voice_config=types.VoiceConfig(
                    prebuilt_voice_config=types.PrebuiltVoiceConfig(
                        voice_name="Charon"
                    )
                )
            ),
            session_resumption=types.SessionResumptionConfig(
                handle=self._resumption_handle
            ),
            context_window_compression=types.ContextWindowCompressionConfig(
                sliding_window=types.SlidingWindow()
            ),
        )

    def _on_briefing_dismiss(self) -> None:
        """Called when the frontend user dismisses the briefing news modal."""
        if self._briefing_dismissed_event:
            self._briefing_dismissed_event.set()

    async def _send_startup_briefing(self) -> None:
        """
        News-first briefing:
          1. Fetch news in background thread
          2. Show news as modal on frontend
          3. Wait for user to dismiss the modal
          4. Send greeting via Gemini Live
        """
        if not self.session:
            return
        if not (self.ui.has_client and getattr(self.ui, '_window_visible', False)):
            print("[SIRIUS] Briefing skipped — no visible UI")
            return
        memory = load_memory()
        identity = memory.get("identity", {})
        def _val(k: str) -> str:
            e = identity.get(k, {})
            return (e.get("value", "") if isinstance(e, dict) else str(e)).strip()
        lang = _val("language")
        name = _val("name")

        # Fetch news in background
        loop = asyncio.get_event_loop()
        news_future = loop.run_in_executor(None, _fetch_news_sync, "top world news today")

        # Wait for news
        news_text = ""
        headlines: list[str] = []
        try:
            news_text = await asyncio.wait_for(asyncio.wrap_future(news_future), timeout=10.0)
        except Exception:
            pass

        # Show news modal on frontend
        if news_text and len(news_text) > 60:
            headlines = [line.strip() for line in news_text.split('\n') if line.strip()][:5]
        if hasattr(self.ui, 'show_briefing'):
            self.ui.show_briefing("", headlines)

        # Wait for user to dismiss
        self._briefing_dismissed_event = asyncio.Event()
        try:
            await asyncio.wait_for(self._briefing_dismissed_event.wait(), timeout=120.0)
        except asyncio.TimeoutError:
            pass
        self._briefing_dismissed_event = None

        if not self.session:
            return

        # Send greeting via Gemini Live
        # Capture the time at speak-moment: news fetch + modal dismiss wait
        # can take minutes, so a time captured earlier would be stale.
        lang_clause = f" Responda em {lang}." if lang else ""
        name_clause = f" Chame o usuário de {name}." if name else ""
        time_str = datetime.now().strftime("%H:%M")
        greeting_text = (
            f"Cumprimente o usuário, são {time_str}. "
            f"Se houver notícias, resuma UMA manchete em uma frase e diga que a lista completa está na tela. "
            f"Não chame nenhuma ferramenta.{lang_clause}{name_clause}"
        )
        if self._turn_done_event:
            self._turn_done_event.clear()
        await self.session.send_client_content(
            turns={"parts": [{"text": greeting_text}]},
            turn_complete=True,
        )
        self.ui.write_log("SYS: Briefing greeting enviado após dismiss.")

        # Espera o Gemini TERMINAR de falar o greeting antes do resumo de uso.
        # send_client_content só envia o prompt; sem essa espera o TTS local
        # disparava antes/por cima da voz do Gemini.
        if self._turn_done_event:
            try:
                await asyncio.wait_for(self._turn_done_event.wait(), timeout=90)
            except asyncio.TimeoutError:
                self.ui.write_log("SYS: Timeout aguardando fim do greeting.")

        # Atividade: resumo semanal falado pela própria voz do Gemini
        if is_monitor_enabled() and self.session:
            from persistence.repository import Repository
            repo = Repository()
            stats = repo.get_weekly_stats()
            top_apps = [a.get("name", "") for a in (stats.get("top_apps") or []) if a.get("name")]
            avg = float(stats.get("avg_daily_minutes") or 0)
            if avg > 0 and top_apps and is_monitor_enabled():
                usage_text = (
                    "Sem usar nenhuma ferramenta, comente brevemente e de forma natural "
                    f"o uso de apps do usuário na semana: média de {avg:.0f} minutos por dia; "
                    f"apps mais usados: {', '.join(top_apps)}."
                )
                if self._turn_done_event:
                    self._turn_done_event.clear()
                try:
                    await self.session.send_client_content(
                        turns={"parts": [{"text": usage_text}]},
                        turn_complete=True,
                    )
                except Exception as e:
                    self.ui.write_log(f"ERR: resumo de uso via Gemini — {e}")

    async def _run_proactive_mode(self) -> None:
        while True:
            await asyncio.sleep(15)
            try:
                from memory.config_manager import load_api_keys
                cfg = load_api_keys()
                if cfg.get("proactive_mode_enabled", "true") == "false":
                    continue
                memory = load_memory()
                if not self._proactive.should_trigger(self._last_user_speech):
                    continue
                self._proactive.mark_triggered()

                from actions.background_monitor import list_monitors
                monitors = list_monitors()

                recent_turns: list[str] = []
                try:
                    if self._conv_id:
                        from persistence.repository import Repository
                        msgs = Repository().get_messages(int(self._conv_id), limit=8)
                        recent_turns = [
                            f"{m.get('role', '')}: {str(m.get('content', ''))[:200]}"
                            for m in msgs
                        ]
                except Exception:
                    recent_turns = []

                prompt = self._proactive.build_prompt(
                    memory,
                    monitors=monitors or None,
                    recent_turns=recent_turns or None,
                )
                import google.generativeai as genai
                genai.configure(api_key=_get_api_key())
                m = genai.GenerativeModel("gemini-2.5-flash")
                result = (await asyncio.to_thread(m.generate_content, prompt)).text.strip()
                if result:
                    print(f"[Proactive] Gemini: {result[:80]}...")
                    self.ui.write_log(f"SYS: {result[:80]}...")
                    if hasattr(self.ui, 'show_suggestion'):
                        self.ui.show_suggestion(result[:200])
            except Exception as e:
                print(f"[Proactive] Check failed: {e}")

    async def _run_background_monitor(self) -> None:
        """Check user-configured topics once per day; speak alerts when new headlines appear."""
        from actions.background_monitor import check_all as monitor_check_all

        await asyncio.sleep(300)          # wait 5 min after startup before first check
        while True:
            if self.session:
                # Don't interrupt if user spoke recently or SIRIUS is mid-sentence
                with self._speaking_lock:
                    speaking = self._is_speaking
                recent_speech = (_time.monotonic() - self._last_user_speech) < 30
                if not speaking and not recent_speech:
                    try:
                        alerts = await asyncio.to_thread(monitor_check_all)
                        memory = load_memory()
                        lang_e = memory.get("identity", {}).get("language", {})
                        lang   = (lang_e.get("value", "") if isinstance(lang_e, dict) else str(lang_e)).strip() or "Portuguese"
                        for alert in alerts:
                            msg = (
                                f"{alert}\n\n"
                                f"Inform the user about this development naturally in {lang}. "
                                "One brief sentence only."
                            )
                            await self.session.send_client_content(
                                turns={"parts": [{"text": msg}]},
                                turn_complete=True,
                            )
                            self.ui.write_log("SYS: Monitor alert sent.")
                            await asyncio.sleep(6)   # gap between consecutive alerts
                    except Exception as e:
                        print(f"[Monitor] ⚠️ Background check error: {e}")
            await asyncio.sleep(1800)     # check every 30 minutes

    async def _execute_tool(self, fc) -> types.FunctionResponse:
        name = fc.name
        args = dict(fc.args or {})

        print(f"[SIRIUS] Tool: {name}  {args}")
        self.ui.set_state("THINKING")

        if name == "save_memory":
            category = args.get("category", "notes")
            key      = args.get("key", "")
            value    = args.get("value", "")
            if key and value:
                update_memory({category: {key: {"value": value}}})
                print(f"[Memory] save_memory: {category}/{key} = {value}")
            if not self.ui.muted:
                self.ui.set_state("LISTENING")
            return types.FunctionResponse(
                id=fc.id, name=name,
                response={"result": "ok", "silent": True}
            )
        if name == "hide_interface":
            self.ui.write_log("SYS: Hiding interface.")
            if hasattr(self.ui, "request_hide_interface"):
                self.ui.request_hide_interface()
            return types.FunctionResponse(
                id=fc.id, name=name,
                response={"result": "ok", "silent": True}
            )
        if name == "shutdown_sirius":
            self.ui.write_log("SYS: Shutdown requested.")
            if hasattr(self.ui, 'request_close_app'):
                self.ui.request_close_app()
            def _shutdown():
                import os
                import time
                time.sleep(2.5)
                os._exit(0)
            threading.Thread(target=_shutdown, daemon=True).start()
            return types.FunctionResponse(
                id=fc.id, name=name,
                response={"result": "ok", "silent": True}
            )
        loop   = asyncio.get_event_loop()
        result = "Done."

        # -- Permission gate ----------------------------------------------
        _NO_PERM_CHECK = {"save_memory", "shutdown_sirius", "hide_interface"}
        if name not in _NO_PERM_CHECK:
            _perm_key = get_category(name)
            if _perm_key and not is_granted(name):
                _meta     = PERMISSION_META.get(_perm_key, {})
                _label    = _meta.get("label", _perm_key)
                _decision = await loop.run_in_executor(
                    None,
                    lambda pk=_perm_key, lb=_label, n=name: self.ui.ask_permission_sync(pk, lb, n)
                )
                if _decision == "always":
                    grant_permission(_perm_key)
                    self.ui.write_log(f"SYS: Permissão '{_label}' ativada permanentemente.")
                elif _decision == "deny":
                    if not self.ui.muted:
                        self.ui.set_state("LISTENING")
                    return types.FunctionResponse(
                        id=fc.id, name=name,
                        response={"error": f"Permissão negada pelo usuário: '{_label}'."}
                    )
                # 'once' -> proceed without saving

        try:
            if name == "open_app":
                r = await loop.run_in_executor(None, lambda: open_app(parameters=args, response=None, player=self.ui))
                result = r or f"Opened {args.get('app_name')}."

            elif name == "weather_report":
                r = await loop.run_in_executor(None, lambda: weather_action(parameters=args, player=self.ui))
                result = r or "Weather delivered."

            elif name == "system_status":
                from actions.system_monitor import get_system_status
                r = await loop.run_in_executor(None, get_system_status)
                result = str(r)

            elif name == "add_monitor":
                from actions.background_monitor import add_monitor
                result = await loop.run_in_executor(None, lambda: add_monitor(args.get("topic", "")))

            elif name == "remove_monitor":
                from actions.background_monitor import remove_monitor
                result = await loop.run_in_executor(None, lambda: remove_monitor(args.get("topic", "")))

            elif name == "list_monitors":
                from actions.background_monitor import list_monitors
                topics = await loop.run_in_executor(None, list_monitors)
                result = str(topics)

            elif name == "browser_control":
                r = await loop.run_in_executor(None, lambda: browser_control(parameters=args, player=self.ui))
                result = r or "Done."

            elif name == "file_controller":
                r = await loop.run_in_executor(None, lambda: file_controller(parameters=args, player=self.ui))
                result = r or "Done."

            elif name == "send_message":
                r = await loop.run_in_executor(None, lambda: send_message(parameters=args, response=None, player=self.ui, session_memory=None))
                result = r or f"Message sent to {args.get('receiver')}."

            elif name == "reminder":
                r = await loop.run_in_executor(None, lambda: reminder(parameters=args, response=None, player=self.ui))
                result = r or "Reminder set."

            elif name == "send_to_phone":
                r = await loop.run_in_executor(None, lambda: send_to_phone(parameters=args, player=self.ui))
                result = r or "Message sent to your phone."

            elif name == "youtube_video":
                r = await loop.run_in_executor(None, lambda: youtube_video(parameters=args, response=None, player=self.ui))
                result = r or "Done."

            elif name == "screen_process":
                import time as _t_mod

                from actions.screen_processor import _capture_camera, _capture_screen
                _now = _t_mod.monotonic()
                _cooldown = 4.0
                if self._vision_busy or (_now - self._vision_last_time) < _cooldown:
                    _wait = max(0, _cooldown - (_now - self._vision_last_time))
                    print(f"[Vision] Cooldown active ({_wait:.1f}s remaining) — ignoring duplicate call")
                    result = "Vision is still processing the previous request. I will not call this again."
                else:
                    self._vision_busy      = True
                    self._vision_last_time = _now
                    angle     = args.get("angle", "screen").lower()
                    user_text = args.get("text", "What do you see?")
                    if angle == "camera":
                        img_b, mime_t = await loop.run_in_executor(None, _capture_camera)
                        if hasattr(self.ui, 'start_camera_stream'):
                            self.ui.start_camera_stream()
                        self._vision_cam_active = True
                        print(f"[Vision] Camera: {len(img_b):,} bytes")
                        _stall = "camera"
                    else:
                        img_b, mime_t = await loop.run_in_executor(None, _capture_screen)
                        print(f"[Vision] Screen: {len(img_b):,} bytes")
                        _stall = "screen"
                    self._pending_vision = (img_b, mime_t, user_text, angle)
                    result = (
                        f"[VISION_ACTIVE] {_stall.capitalize()} captured. "
                        f"Immediately say ONE short natural sentence in the user's own language, "
                        f"telling them you are looking at their {_stall} right now. "
                        f"Do NOT describe or guess content — the actual image arrives in the NEXT message."
                    )

            elif name == "close_camera":
                if hasattr(self.ui, 'stop_camera_stream'):
                    self.ui.stop_camera_stream()
                self._vision_busy = False
                self._vision_cam_active = False
                self._vision_close_pending = False
                result = "Camera closed."

            elif name == "computer_settings":
                r = await loop.run_in_executor(None, lambda: computer_settings(parameters=args, response=None, player=self.ui))
                result = r or "Done."

            elif name == "desktop_control":
                r = await loop.run_in_executor(None, lambda: desktop_control(parameters=args, player=self.ui))
                result = r or "Done."

            elif name == "code_helper":
                r = await loop.run_in_executor(None, lambda: code_helper(parameters=args, player=self.ui, speak=self.speak))
                result = r or "Done."

            elif name == "dev_agent":
                r = await loop.run_in_executor(None, lambda: dev_agent(parameters=args, player=self.ui, speak=self.speak))
                result = r or "Done."

            elif name == "agent_task":
                from agent.task_queue import TaskPriority, get_queue
                priority_map = {"low": TaskPriority.LOW, "normal": TaskPriority.NORMAL, "high": TaskPriority.HIGH}
                priority = priority_map.get(args.get("priority", "normal").lower(), TaskPriority.NORMAL)
                task_id  = get_queue().submit(goal=args.get("goal", ""), priority=priority, speak=self.speak)
                result   = f"Task started (ID: {task_id})."

            elif name == "web_search":
                r = await loop.run_in_executor(None, lambda: web_search_action(parameters=args, player=self.ui))
                result = r or "Done."
            elif name == "file_processor":
                if not args.get("file_path") and self.ui.current_file:
                    args["file_path"] = self.ui.current_file
                r = await loop.run_in_executor(
                    None,
                    lambda: file_processor(parameters=args, player=self.ui, speak=self.speak)
                )
                result = r or "Done."

            elif name == "computer_control":
                r = await loop.run_in_executor(None, lambda: computer_control(parameters=args, player=self.ui))
                result = r or "Done."

            elif name == "game_updater":
                r = await loop.run_in_executor(None, lambda: game_updater(parameters=args, player=self.ui, speak=self.speak))
                result = r or "Done."

            elif name == "flight_finder":
                r = await loop.run_in_executor(None, lambda: flight_finder(parameters=args, player=self.ui))
                result = r or "Done."

            elif name == "google_calendar":
                r = await loop.run_in_executor(None, lambda: calendar_action(parameters=args, player=self.ui))
                result = r or "Done."

            elif name == "notion_calendar":
                r = await loop.run_in_executor(None, lambda: notion_calendar_action(parameters=args, player=self.ui))
                result = r or "Done."

            elif name == "gmail":
                r = await loop.run_in_executor(None, lambda: gmail_action(parameters=args, player=self.ui))
                result = r or "Done."

            elif name == "workspaces":
                from actions.workspaces import workspaces
                r = await loop.run_in_executor(None, lambda: workspaces(parameters=args, player=self.ui))
                result = r or "Done."

            elif name == "obsidian_notes_search":
                from actions.obsidian_search import search_notes
                result = await loop.run_in_executor(
                    None,
                    lambda: search_notes(args.get("query", ""), args.get("limit", 5)),
                )

            elif name == "obsidian_tasks_list":
                from actions.obsidian_search import list_tasks
                result = await loop.run_in_executor(None, list_tasks)

            elif name == "agents_control":
                from actions.agents import agents_control
                r = await loop.run_in_executor(
                    None,
                    lambda: agents_control(parameters=args, player=self.ui, speak=self.speak),
                )
                result = r or "Done."

            elif name == "deep_research":
                r = await loop.run_in_executor(None, lambda: deep_research(parameters=args, player=self.ui))
                result = r or "Done."

            elif name == "linkedin_jobs_radar":
                r = await loop.run_in_executor(None, lambda: linkedin_jobs_radar(parameters=args, player=self.ui, speak=self.speak))
                result = r or "Done."

            elif name == "apply_assist":
                r = await loop.run_in_executor(None, lambda: apply_assist(parameters=args, player=self.ui, speak=self.speak))
                result = r or "Done."

            elif name == "business_radar":
                r = await loop.run_in_executor(None, lambda: business_radar(parameters=args, player=self.ui, speak=self.speak))
                result = r or "Done."

            elif name == "freela_arsenal":
                r = await loop.run_in_executor(None, lambda: freela_arsenal(parameters=args, player=self.ui, speak=self.speak))
                result = r or "Done."


            elif self._plugin_registry.has(name):
                r = await loop.run_in_executor(
                    None,
                    lambda: self._plugin_registry.run(name, args, player=self.ui, session_memory=None)
                )
                result = r or "Done."

            else:
                result = f"Unknown tool: {name}"

        except Exception as e:
            result = f"Tool '{name}' failed: {e}"
            traceback.print_exc()
            self.speak_error(name, e)

        if not self.ui.muted:
            self.ui.set_state("LISTENING")

        print(f"[SIRIUS] -> {name} -> {str(result)[:500]}")
        return types.FunctionResponse(
            id=fc.id, name=name,
            response={"result": result}
        )

    async def _send_realtime(self):
        while True:
            msg = await self.out_queue.get()
            await self.session.send_realtime_input(media=msg)

    async def _listen_audio(self):
        print("[SIRIUS] Mic started")
        loop = asyncio.get_event_loop()
        self._audio_stream = None

        def callback(indata, frames, time_info, status):
            with self._speaking_lock:
                sirius_speaking = self._is_speaking
            if not sirius_speaking:
                data = indata.tobytes()
                rms = np.sqrt(np.mean(indata**2))
                level = min(1.0, rms * 15)
                self.ui.set_voice_level(level)
                self._fft_mic_counter += 1
                if self._fft_mic_counter >= _SEND_FFT_INTERVAL:
                    self._fft_mic_counter = 0
                    bins = compute_fft_bins(indata)
                    self.ui.send_audio_bins(bins, "mic")
                loop.call_soon_threadsafe(
                    self.out_queue.put_nowait,
                    {"data": data, "mime_type": "audio/pcm"}
                )
            else:
                self.ui.set_voice_level(0.0)

        try:
            # Wait for frontend before opening mic
            while not self.ui.has_client:
                await asyncio.sleep(0.5)
            # Wait for greeting to finish before opening mic
            if self._allow_mic is not None:
                await self._allow_mic.wait()
            # Wait briefly for visibility state to arrive from frontend
            for _ in range(50):  # up to 5s
                if self.ui._visibility_set:
                    break
                await asyncio.sleep(0.1)

            # Don't open mic if UI is muted/hidden
            if self.ui.muted:
                print("[SIRIUS] Mic not opened — UI muted/hidden, waiting for visibility...")
                while self.ui.muted:
                    await asyncio.sleep(0.5)
                print("[SIRIUS] UI visible, opening mic")

            stream = sd.InputStream(
                samplerate=SEND_SAMPLE_RATE,
                channels=CHANNELS,
                dtype="int16",
                blocksize=CHUNK_SIZE,
                callback=callback,
            )
            stream.start()
            self._audio_stream = stream
            print("[SIRIUS] Mic stream open")

            # Start inactive; wait for explicit visibility confirmation
            was_active = False
            if not was_active:
                stream.stop()
                self.ui.set_voice_level(0.0)
                print("[SIRIUS] Mic stream paused initially (waiting for visibility)")

            while True:
                if self._restart_event.is_set():
                    self._restart_event.clear()
                    print("[SIRIUS] Restart requested — disconnecting")
                    msg = "[SIRIUS] Restart requested by config change"
                    raise RuntimeError(msg)
                await asyncio.sleep(0.3)
                is_active = self.ui.has_client and not self.ui.muted
                if is_active != was_active:
                    if not is_active:
                        stream.stop()
                        self.ui.set_voice_level(0.0)
                        print(f"[SIRIUS] Mic stream paused (has_client={self.ui.has_client}, muted={self.ui.muted})")
                    else:
                        stream.start()
                        print(f"[SIRIUS] Mic stream resumed (has_client={self.ui.has_client}, muted={self.ui.muted})")
                    was_active = is_active
        except Exception as e:
            print(f"[SIRIUS] Mic error: {e}")
            raise
        finally:
            if self._audio_stream:
                try:
                    self._audio_stream.close()
                except Exception:
                    pass

    async def _receive_audio(self):
        print("[SIRIUS] Recv started")
        out_buf, in_buf = [], []

        try:
            while True:
                async for response in self.session.receive():

                    if response.session_resumption_update:
                        upd = response.session_resumption_update
                        if upd.resumable and upd.new_handle:
                            if upd.new_handle != self._resumption_handle:
                                self._resumption_handle = upd.new_handle
                                print("[SIRIUS] Resumption handle updated")

                    if response.go_away:
                        print("[SIRIUS] go_away received — server will rotate session soon")

                    if response.data:
                        if self._interrupted:
                            continue  # discard: interrupted
                        if not self._gemini_turn.is_set():
                            self._gemini_turn.set()
                        if self._turn_done_event and self._turn_done_event.is_set():
                            self._turn_done_event.clear()
                        self.audio_in_queue.put_nowait(response.data)

                    if response.server_content:
                        sc = response.server_content

                        if not self._gemini_turn.is_set():
                            self._gemini_turn.set()

                        if sc.output_transcription and sc.output_transcription.text:
                            txt = _clean_transcript(sc.output_transcription.text)
                            if txt:
                                if not out_buf:
                                    out_buf.append(txt)
                                elif out_buf[-1] in txt:
                                    # Cumulative: new text contains the last segment
                                    out_buf[-1] = txt
                                elif txt in out_buf[-1]:
                                    pass  # Subset — skip
                                else:
                                    out_buf.append(txt)

                        if sc.input_transcription and sc.input_transcription.text:
                            txt = _clean_transcript(sc.input_transcription.text)
                            if txt:
                                if not in_buf:
                                    in_buf.append(txt)
                                elif in_buf[-1] in txt:
                                    in_buf[-1] = txt
                                elif txt in in_buf[-1]:
                                    pass
                                else:
                                    in_buf.append(txt)

                        if sc.turn_complete:
                            if self._turn_done_event:
                                self._turn_done_event.set()
                            self._gemini_turn.clear()
                            if self._interrupted:
                                self._interrupted = False
                                self.set_speaking(False)

                            full_in = self._merge_segments(in_buf)
                            if full_in:
                                self._last_user_speech = _time.monotonic()
                                self.ui.write_log(f"You: {full_in}")
                                if self._dashboard:
                                    asyncio.create_task(self._dashboard.broadcast({
                                        "type": "log", "speaker": "user",
                                        "text": full_in,
                                        "ts": datetime.now().isoformat(),
                                    }))
                                # Persist user message to DB
                                _persist_message_to_db(self, "user", full_in)
                            in_buf = []

                            full_out = self._merge_segments(out_buf)
                            if full_out:
                                self.ui.write_log(f"Sirius: {full_out}")
                                if self._dashboard:
                                    asyncio.create_task(self._dashboard.broadcast({
                                        "type": "log", "speaker": "sirius",
                                        "text": full_out,
                                        "ts": datetime.now().isoformat(),
                                    }))
                                # Persist assistant message to DB
                                _persist_message_to_db(self, "assistant", full_out)
                                # Trigger background memory extraction
                                threading.Thread(
                                    target=_update_memory_async,
                                    args=(full_in, full_out),
                                    daemon=True
                                ).start()
                            out_buf = []

                            # Vision injection: model finished tool-response turn -> now send the image
                            if self._pending_vision and self.session:
                                import base64 as _b64
                                img_b, mime_t, question, angle = self._pending_vision
                                self._pending_vision = None
                                b64 = _b64.b64encode(img_b).decode("ascii")
                                print(f"[Vision] {len(img_b):,} bytes (angle={angle}) -> main session")
                                await self.session.send_client_content(
                                    turns={"parts": [
                                        {"inline_data": {"mime_type": mime_t, "data": b64}},
                                        {"text": question},
                                    ]},
                                    turn_complete=True,
                                )
                                if self._vision_cam_active:
                                    self._vision_cam_active = False
                                    self._vision_close_pending = True
                                else:
                                    self._vision_busy = False
                            elif self._vision_close_pending:
                                self._vision_close_pending = False
                                self._vision_busy = False
                                async def _cam_close():
                                    await asyncio.sleep(2.0)
                                    if hasattr(self.ui, 'stop_camera_stream'):
                                        self.ui.stop_camera_stream()
                                asyncio.create_task(_cam_close())

                    if response.tool_call:
                        fn_responses = []
                        for fc in response.tool_call.function_calls:
                            print(f"[SIRIUS] Call: {fc.name}")
                            fr = await self._execute_tool(fc)
                            fn_responses.append(fr)
                        await self.session.send_tool_response(
                            function_responses=fn_responses
                        )
        except Exception as e:
            print(f"[SIRIUS] Recv error: {e}")
            traceback.print_exc()
            raise

    async def _play_audio(self):
        print("[SIRIUS] Play started")

        stream = sd.RawOutputStream(
            samplerate=RECEIVE_SAMPLE_RATE,
            channels=CHANNELS,
            dtype="int16",
            blocksize=CHUNK_SIZE,
        )
        stream.start()

        try:
            while True:
                try:
                    chunk = await asyncio.wait_for(
                        self.audio_in_queue.get(),
                        timeout=0.1
                    )
                except asyncio.TimeoutError:
                    if self._interrupted:
                        self._interrupted = False
                        self.set_speaking(False)
                        # Drain any remaining chunks
                        while not self.audio_in_queue.empty():
                            try:
                                self.audio_in_queue.get_nowait()
                            except asyncio.QueueEmpty:
                                break
                    if (
                        self._turn_done_event
                        and self._turn_done_event.is_set()
                        and self.audio_in_queue.empty()
                    ):
                        self.set_speaking(False)
                        self._turn_done_event.clear()
                    continue

                # Pause Gemini playback while local TTS is speaking
                while self._tts_busy.is_set():
                    await asyncio.sleep(0.1)

                self.set_speaking(True)
                self._fft_tts_counter += 1
                if self._fft_tts_counter >= _SEND_FFT_INTERVAL:
                    self._fft_tts_counter = 0
                    arr = np.frombuffer(chunk, dtype=np.int16).reshape(-1, 1)
                    bins = compute_fft_bins(arr)
                    self.ui.send_audio_bins(bins, "tts")
                await asyncio.to_thread(stream.write, chunk)
        except Exception as e:
            print(f"[SIRIUS] Play error: {e}")
            raise
        finally:
            self.set_speaking(False)
            stream.stop()
            stream.close()

    async def _relay_phone_audio(self) -> None:
        """Forward phone mic PCM chunks from dashboard queue into the Gemini Live session."""
        q = self._dashboard._phone_audio_queue
        while True:
            try:
                chunk = await asyncio.wait_for(q.get(), timeout=1.0)
            except asyncio.TimeoutError:
                # No audio for 1 s -> phone mic inactive, give PC mic back
                self._phone_active = False
                continue
            self._phone_active = True   # phone is streaming — silence PC mic
            with self._speaking_lock:
                speaking = self._is_speaking
            if not speaking and not self.ui.muted:
                try:
                    self.out_queue.put_nowait(chunk)
                except asyncio.QueueFull:
                    pass

    # -- dashboard command relay ---------------------------------------------

    async def _process_dashboard_commands(self) -> None:
        while True:
            try:
                text = await asyncio.wait_for(
                    self._dashboard._command_queue.get(), timeout=0.5
                )
                if not text:
                    continue
                # Wait up to 8s for session to become ready after a wake
                for _ in range(80):
                    if self.session:
                        break
                    await asyncio.sleep(0.1)
                if self.session:
                    await self.session.send_client_content(
                        turns={"parts": [{"text": text}]},
                        turn_complete=True,
                    )
                    self.ui.write_log(f"[Web]: {text}")
                    _persist_message_to_db(self, "user", text)
                else:
                    print(f"[Dashboard] Dropped command (no session): {text}")
            except asyncio.TimeoutError:
                pass
            except Exception as e:
                print(f"[Dashboard] Command error: {e}")
                await asyncio.sleep(0.5)

    async def run(self):
        # Wait for a frontend client before connecting to Gemini
        if hasattr(self.ui, 'set_startup_status'):
            self.ui.set_startup_status("Pronto — aguardando interface...")
        if hasattr(self.ui, 'wait_for_client_async'):
            await self.ui.wait_for_client_async()
        if hasattr(self.ui, 'set_startup_progress'):
            self.ui.set_startup_progress(3, 5, "Conectando ao Gemini...")
        if hasattr(self.ui, 'set_startup_status'):
            self.ui.set_startup_status("Interface conectada. Iniciando...")
        if hasattr(self.ui, 'set_startup_progress'):
            self.ui.set_startup_progress(4, 5, "Estabelecendo conexão...")
        client = genai.Client(
            api_key=_get_api_key(),
            http_options={"api_version": "v1beta"}
        )

        # Start dashboard (optional — needs: pip install fastapi "uvicorn[standard]" cryptography)
        try:
            from dashboard.server import DashboardServer
            global _DASHBOARD
            # Use the early dashboard if already started by the background thread
            if _DASHBOARD is not None:
                self._dashboard = _DASHBOARD
                print(f"[DEBUG main] Reusing early dashboard instance (IP={self._dashboard._ip})")
            else:
                self._dashboard = DashboardServer()
                self._dashboard._ready_event = self._dashboard_ready
                print("[DEBUG main] Starting DashboardServer in background...")
                print(f"[DEBUG main] Dashboard IP: {self._dashboard._ip}")
                task = asyncio.ensure_future(self._dashboard.serve())
                def _on_dashboard_done(fut):
                    try:
                        fut.result()
                    except Exception as e:
                        print(f"[Dashboard] SERVER TASK CRASHED: {e}")
                        traceback.print_exc()
                        self._dashboard = None
                        self._dashboard_ready.set()
                task.add_done_callback(_on_dashboard_done)
            self._dashboard.set_connect_callback(self._on_phone_connected)
            self._dashboard.set_pair_request_callback(self._on_pair_request)
            _ws.manager.on_pair_response = self._on_pair_decision
            asyncio.ensure_future(self._process_dashboard_commands())
            self.ui.write_log("SYS: Remote dashboard started.")
        except Exception as e:
            print(f"[Dashboard] Disabled: {e}")
            traceback.print_exc()
            self._dashboard = None
            self._dashboard_ready.set()

        while True:
            session_started = _time.monotonic()
            try:
                print("[SIRIUS] Connecting...")
                self._gemini_turn.clear()
                self._tts_busy.clear()
                config = self._build_config()

                async with (
                    client.aio.live.connect(model=LIVE_MODEL, config=config) as session,
                    asyncio.TaskGroup() as tg,
                ):
                    self.session        = session
                    self._loop          = asyncio.get_event_loop()
                    self.audio_in_queue = asyncio.Queue()
                    self.out_queue      = asyncio.Queue(maxsize=10)
                    self._turn_done_event = asyncio.Event()
                    self._reconnect_attempts = 0

                    print("[SIRIUS] Connected.")
                    if self._first_run:
                        self.ui.write_log("SYS: SIRIUS online.")

                    self._allow_mic = asyncio.Event()

                    if self._dashboard:
                        self._dashboard._assistant_running = True
                        await self._dashboard.broadcast({"type": "status", "state": "active"})

                    tg.create_task(self._send_realtime())
                    tg.create_task(self._listen_audio())
                    tg.create_task(self._receive_audio())
                    tg.create_task(self._play_audio())
                    tg.create_task(self._run_proactive_mode())
                    tg.create_task(self._run_background_monitor())
                    if self._dashboard:
                        tg.create_task(self._relay_phone_audio())

                    if self._first_run:
                        self._first_run = False

                        # Greeting/chime/briefing only when a VISIBLE UI is attached.
                        # Headless/hidden starts (autostart, background) stay silent and
                        # never fire the greeting later in this process.
                        # Wait for visibility confirmation from frontend (up to 5s)
                        for _ in range(50):
                            if getattr(self.ui, '_visibility_set', False) and not self.ui.muted:
                                break
                            await asyncio.sleep(0.1)

                        if self.ui.has_client and getattr(self.ui, '_window_visible', False) and not self.ui.muted:
                            if hasattr(self.ui, 'set_startup_progress'):
                                self.ui.set_startup_progress(5, 5, "SIRIUS pronto!")
                            if hasattr(self.ui, 'set_startup_status'):
                                self.ui.set_startup_status("* SIRIUS online")

                            from core.sounds import play_init_sound
                            tg.create_task(asyncio.to_thread(play_init_sound))

                            if not self._briefing_sent:
                                from memory.config_manager import get_speak_briefing_enabled
                                if get_speak_briefing_enabled():
                                    self._briefing_sent = True
                                    tg.create_task(self._send_startup_briefing())

                            self.ui.write_log("SYS: SIRIUS online. Pronto para ouvir.")
                        else:
                            self._briefing_sent = True
                            print("[SIRIUS] No visible UI — greeting/chime/briefing suppressed")

                        # Hide startup panel LAST so it stays hidden on reconnect
                        if hasattr(self.ui, 'hide_startup_panel'):
                            self.ui.hide_startup_panel()

                        self._allow_mic.set()
                        self.ui.set_state("LISTENING")
                    else:
                        self._allow_mic.set()
                        self.ui.set_state("LISTENING")

                    self.ui.send_current_state()

            except Exception as e:
                print(f"[SIRIUS] Error: {e}")
                traceback.print_exc()
            except BaseException as e:
                if isinstance(e, (KeyboardInterrupt, SystemExit)):
                    raise
                print(f"[SIRIUS] Session interrupted (ExceptionGroup): {e}")
                traceback.print_exc()
            self.set_speaking(False)
            self.session = None

            if self._dashboard:
                self._dashboard._assistant_running = False
                await self._dashboard.broadcast({"type": "status", "state": "sleeping"})

            lasted = _time.monotonic() - session_started
            if lasted >= 60:
                # Routine server-side rotation (~10 min connection limit).
                # Resumption handle keeps context; invisible to the user.
                self._reconnect_attempts = 0
                print("[SIRIUS] Session rotated — reconnecting silently")
                await asyncio.sleep(1)
            else:
                self._reconnect_attempts += 1
                delay = min(60, 3 * (2 ** (self._reconnect_attempts - 1)))
                self.ui.set_state("THINKING")
                self.ui.write_log("SYS: Reconectando...")
                print(f"[SIRIUS] Reconnecting in {delay}s...")
                await asyncio.sleep(delay)

# ---------------------------------------------------------------------------
# Convert Gemini-style declarations to OpenAI/Ollama format
# ---------------------------------------------------------------------------

_TYPE_MAP = {
    "OBJECT": "object", "STRING": "string", "ARRAY": "array",
    "INTEGER": "integer", "BOOLEAN": "boolean", "NUMBER": "number",
}

def _convert_type(t: str) -> str:
    return _TYPE_MAP.get(t, t.lower()) if isinstance(t, str) else t

def _convert_props(props: dict) -> dict:
    out = {}
    for k, v in props.items():
        nv = dict(v)
        if "type" in nv:
            nv["type"] = _convert_type(nv["type"])
        if "items" in nv and isinstance(nv["items"], dict):
            nv["items"] = {"type": _convert_type(nv["items"].get("type", "string"))}
        out[k] = nv
    return out

def _to_ollama_tools(decls: list) -> list:
    tools = []
    for d in decls:
        params = d.get("parameters", {})
        new_params: dict = {
            "type":       "object",
            "properties": _convert_props(params.get("properties", {})),
        }
        req = params.get("required")
        if req:
            new_params["required"] = req
        tools.append({
            "type": "function",
            "function": {
                "name":        d["name"],
                "description": d["description"],
                "parameters":  new_params,
            },
        })
    return tools

# ---------------------------------------------------------------------------
# Voice Activity Detection (used for Whisper listen loop)
# ---------------------------------------------------------------------------

class _VADBuffer:
    """Energy-based VAD: buffers audio until end of utterance."""

    def __init__(
        self,
        sample_rate:    int   = 16_000,
        silence_sec:    float = 0.7,    # silence after last word -> send to STT
        speech_thresh:  float = 0.008,  # RMS above this = speech
        silence_thresh: float = 0.004,  # RMS below this = silence
        min_speech_sec: float = 0.3,
        max_speech_sec: float = 30.0,
    ):
        self._sr            = sample_rate
        self._sil_n         = int(silence_sec * sample_rate)
        self._speech_thresh = speech_thresh
        self._sil_thresh    = silence_thresh
        self._min_n         = int(min_speech_sec * sample_rate)
        self._max_n         = int(max_speech_sec * sample_rate)
        self._buf:          list[np.ndarray] = []
        self._in_spch       = False
        self._sil_cnt       = 0

    def process(self, chunk: np.ndarray) -> np.ndarray | None:
        rms     = float(np.sqrt(np.mean(chunk ** 2)))
        total_n = sum(len(c) for c in self._buf)

        if rms > self._speech_thresh:
            self._in_spch = True
            self._sil_cnt = 0
            self._buf.append(chunk.copy())
        elif self._in_spch:
            self._buf.append(chunk.copy())
            if rms < self._sil_thresh:
                self._sil_cnt += len(chunk)

            if self._sil_cnt >= self._sil_n or total_n >= self._max_n:
                audio         = np.concatenate(self._buf)
                self._buf     = []
                self._in_spch = False
                self._sil_cnt = 0
                if len(audio) >= self._min_n:
                    return audio
        return None


# ---------------------------------------------------------------------------
# SiriusLocal
# ---------------------------------------------------------------------------

class SiriusLocal:
    """
    Main assistant class for local offline mode.
    Replaces SiriusLive with:
      STT (Whisper/Vosk) -> Ollama LLM (tool calling) -> TTS (Edge/Kokoro/ElevenLabs)
    """

    def __init__(self, ui: SiriusUI):
        import queue as _queue

        from core.config_loader import get_all_config
        self.ui               = ui
        self._config          = get_all_config()
        self._stt             = None
        self._tts             = None
        self._tts_ready       = threading.Event()
        self._speaking        = False
        self._speaking_lock   = threading.Lock()
        self._text_queue      = _queue.Queue()
        self._tts_queue       = _queue.Queue()
        self._conversation:   list[dict]  = []

        self.ui.on_text_command = self._on_text_command
        self._fft_mic_counter = 0
        self._fft_tts_counter = 0

        # Plugin registry (discover once at startup; enable/disable re-read per call)
        from core.plugin_loader import discover_plugins
        _core_names    = {d["name"] for d in TOOL_DECLARATIONS}
        _plugins_dir   = Path(__file__).resolve().parent / "plugins"
        self._plugin_registry = discover_plugins(
            _plugins_dir,
            _core_names,
            logger=lambda m: (print(f"[Plugins] {m}"), self.ui.write_log(f"SYS: {m}")),
            bundled_module_names=_BUNDLED_PLUGIN_MODULES,
        )

    def _build_system_prompt(self) -> str:
        sys_p   = _load_system_prompt()
        memory  = load_memory()
        mem_str = format_memory_for_prompt(memory)
        time_ctx = _now_context_str()
        parts = [sys_p]
        if mem_str:
            parts.append(mem_str)
        parts.append(time_ctx)
        return "\n\n".join(parts)

    def _tts_worker(self) -> None:
        self._tts_ready.wait(timeout=120)

        while True:
            text = self._tts_queue.get()
            try:
                if text and self._tts:
                    with self._speaking_lock:
                        self._speaking = True
                    self.ui.set_state("SPEAKING")
                    self._tts.speak(text)
            except Exception as e:
                print(f"[TTS] speak error: {e}")
            finally:
                self._tts_queue.task_done()
                if self._tts_queue.empty():
                    with self._speaking_lock:
                        self._speaking = False
                    if not self.ui.muted:
                        self.ui.set_state("LISTENING")

    def set_speaking(self, value: bool) -> None:
        with self._speaking_lock:
            self._speaking = value
        if value:
            self.ui.set_state("SPEAKING")
        elif not self.ui.muted:
            self.ui.set_state("LISTENING")

    def _on_tts_audio_chunk(self, audio: np.ndarray) -> None:
        self._fft_tts_counter += 1
        if self._fft_tts_counter >= _SEND_FFT_INTERVAL:
            self._fft_tts_counter = 0
            bins = compute_fft_bins(audio)
            self.ui.send_audio_bins(bins, "tts")

    def speak(self, text: str) -> None:
        if not text or not self._tts:
            return
        with self._speaking_lock:
            self._speaking = True
        self._tts_queue.put(text)

    def speak_error(self, tool_name: str, error) -> None:
        short = str(error)[:120]
        self.ui.write_log(f"ERR: {tool_name} — {short}")
        self.speak(f"{tool_name} encountered an error.")

    def _on_text_command(self, text: str) -> None:
        self._text_queue.put(text)

    def _execute_tool(self, name: str, args: dict) -> str:
        print(f"[SIRIUS LOCAL] Tool: {name}  {args}")
        self.ui.set_state("THINKING")

        if name == "save_memory":
            category = args.get("category", "notes")
            key      = args.get("key", "")
            value    = args.get("value", "")
            if key and value:
                update_memory({category: {key: {"value": value}}})
                print(f"[Memory] save_memory: {category}/{key} = {value}")
            if not self.ui.muted:
                self.ui.set_state("LISTENING")
            return "ok"
        if name == "hide_interface":
            self.ui.write_log("SYS: Hiding interface.")
            if hasattr(self.ui, "request_hide_interface"):
                self.ui.request_hide_interface()
            return "ok"
        elif name == "shutdown_sirius":
            self.ui.write_log("SYS: Shutdown requested.")
            if hasattr(self.ui, 'request_close_app'):
                self.ui.request_close_app()
            def _shutdown():
                import os
                import time
                time.sleep(2.5)
                os._exit(0)
            threading.Thread(target=_shutdown, daemon=True).start()
            return "Shutting down."
        result = "Done."
        try:
            if name == "open_app":
                r = open_app(parameters=args, response=None, player=self.ui)
                result = r or f"Opened {args.get('app_name')}."

            elif name == "weather_report":
                r = weather_action(parameters=args, player=self.ui)
                result = r or "Weather delivered."

            elif name == "browser_control":
                r = browser_control(parameters=args, player=self.ui)
                result = r or "Done."

            elif name == "file_controller":
                r = file_controller(parameters=args, player=self.ui)
                result = r or "Done."

            elif name == "send_message":
                r = send_message(parameters=args, response=None, player=self.ui, session_memory=None)
                result = r or f"Message sent to {args.get('receiver')}."

            elif name == "reminder":
                r = reminder(parameters=args, response=None, player=self.ui)
                result = r or "Reminder set."

            elif name == "send_to_phone":
                r = send_to_phone(parameters=args, player=self.ui)
                result = r or "Message sent to your phone."

            elif name == "youtube_video":
                r = youtube_video(parameters=args, response=None, player=self.ui)
                result = r or "Done."

            elif name == "screen_process":
                r = screen_process(parameters=args, response=None, player=self.ui, session_memory=None)
                result = r if isinstance(r, str) and r else "Screen analyzed."

            elif name == "computer_settings":
                r = computer_settings(parameters=args, response=None, player=self.ui)
                result = r or "Done."

            elif name == "desktop_control":
                r = desktop_control(parameters=args, player=self.ui)
                result = r or "Done."

            elif name == "code_helper":
                r = code_helper(parameters=args, player=self.ui, speak=self.speak)
                result = r or "Done."

            elif name == "dev_agent":
                r = dev_agent(parameters=args, player=self.ui, speak=self.speak)
                result = r or "Done."

            elif name == "agent_task":
                from agent.task_queue import TaskPriority, get_queue
                priority_map = {
                    "low": TaskPriority.LOW,
                    "normal": TaskPriority.NORMAL,
                    "high": TaskPriority.HIGH,
                }
                priority = priority_map.get(
                    args.get("priority", "normal").lower(), TaskPriority.NORMAL
                )
                task_id = get_queue().submit(
                    goal=args.get("goal", ""), priority=priority, speak=self.speak
                )
                result = f"Task started (ID: {task_id})."

            elif name == "web_search":
                r = web_search_action(parameters=args, player=self.ui)
                result = r or "Done."

            elif name == "file_processor":
                if not args.get("file_path") and self.ui.current_file:
                    args["file_path"] = self.ui.current_file
                r = file_processor(parameters=args, player=self.ui, speak=self.speak)
                result = r or "Done."

            elif name == "computer_control":
                r = computer_control(parameters=args, player=self.ui)
                result = r or "Done."

            elif name == "game_updater":
                r = game_updater(parameters=args, player=self.ui, speak=self.speak)
                result = r or "Done."

            elif name == "flight_finder":
                r = flight_finder(parameters=args, player=self.ui)
                result = r or "Done."

            elif name == "google_calendar":
                r = calendar_action(parameters=args, player=self.ui)
                result = r or "Done."

            elif name == "notion_calendar":
                r = notion_calendar_action(parameters=args, player=self.ui)
                result = r or "Done."

            elif name == "gmail":
                r = gmail_action(parameters=args, player=self.ui)
                result = r or "Done."

            elif name == "workspaces":
                from actions.workspaces import workspaces
                r = workspaces(parameters=args, player=self.ui)
                result = r or "Done."

            elif name == "obsidian_notes_search":
                from actions.obsidian_search import search_notes
                result = search_notes(args.get("query", ""), args.get("limit", 5))

            elif name == "obsidian_tasks_list":
                from actions.obsidian_search import list_tasks
                result = list_tasks()

            elif name == "deep_research":
                r = deep_research(parameters=args, player=self.ui)
                result = r or "Done."

            elif name == "linkedin_jobs_radar":
                r = linkedin_jobs_radar(parameters=args, player=self.ui, speak=self.speak)
                result = r or "Done."

            elif name == "apply_assist":
                r = apply_assist(parameters=args, player=self.ui, speak=self.speak)
                result = r or "Done."

            elif name == "business_radar":
                r = business_radar(parameters=args, player=self.ui, speak=self.speak)
                result = r or "Done."

            elif name == "freela_arsenal":
                r = freela_arsenal(parameters=args, player=self.ui, speak=self.speak)
                result = r or "Done."
                return "Shutting down."

            elif name == "system_status":
                from actions.system_monitor import get_system_status
                result = str(get_system_status())

            elif name == "add_monitor":
                from actions.background_monitor import add_monitor
                result = add_monitor(args.get("topic", ""))

            elif name == "remove_monitor":
                from actions.background_monitor import remove_monitor
                result = remove_monitor(args.get("topic", ""))

            elif name == "list_monitors":
                from actions.background_monitor import list_monitors
                topics = list_monitors()
                result = str(topics)

            elif name == "agents_control":
                from actions.agents import agents_control
                result = agents_control(parameters=args, player=self.ui, speak=self.speak)

            elif self._plugin_registry.has(name):
                result = self._plugin_registry.run(name, args, player=self.ui, session_memory=None) or "Done."

            else:
                result = f"Unknown tool: {name}"

        except Exception as e:
            result = f"Tool '{name}' failed: {e}"
            traceback.print_exc()
            self.speak_error(name, e)

        if not self.ui.muted:
            self.ui.set_state("LISTENING")

        print(f"[SIRIUS LOCAL] -> {name} -> {str(result)[:80]}")
        return result

    def _process_message(self, user_text: str) -> None:
        self.ui.set_state("THINKING")
        self.ui.write_log(f"You: {user_text}")

        self._conversation.append({"role": "user", "content": user_text})

        MAX_HISTORY = 10
        if len(self._conversation) > MAX_HISTORY:
            self._conversation = self._conversation[-MAX_HISTORY:]

        messages = [
            {"role": "system", "content": self._build_system_prompt()}
        ] + list(self._conversation)

        _NEEDS_LLM_ROUND = {"web_search", "screen_process", "agent_task", "browser_control"}
        plugin_decls  = self._plugin_registry.get_tool_declarations()
        ollama_tools  = _to_ollama_tools(TOOL_DECLARATIONS + plugin_decls)

        MAX_TOOL_ROUNDS = 6
        for _round in range(MAX_TOOL_ROUNDS):
            final_content    = ""
            final_tool_calls: list = []
            _streamed: list[str] = []

            try:
                from core.llm_client import call_llm_stream
                for event in call_llm_stream(messages, ollama_tools):
                    if event["type"] == "sentence":
                        _streamed.append(event["text"])
                        self.speak(event["text"])
                    elif event["type"] == "done":
                        final_content    = event["content"]
                        final_tool_calls = event["tool_calls"]
            except RuntimeError as e:
                self.speak_error("LLM", e)
                return

            if not final_tool_calls:
                if _streamed:
                    assistant_msg = {"role": "assistant", "content": final_content}
                    messages.append(assistant_msg)
                    self._conversation.append(assistant_msg)
                    self.ui.write_log(f"Sirius: {final_content}")
                elif final_content:
                    assistant_msg = {"role": "assistant", "content": final_content}
                    messages.append(assistant_msg)
                    self._conversation.append(assistant_msg)
                    self.ui.write_log(f"Sirius: {final_content}")
                    self.speak(final_content)
                break

            assistant_msg = {
                "role":       "assistant",
                "content":    final_content or "",
                "tool_calls": final_tool_calls,
            }
            messages.append(assistant_msg)
            self._conversation.append(assistant_msg)

            _only_memory = all(
                tc.get("function", {}).get("name") == "save_memory"
                for tc in final_tool_calls
            )
            if _only_memory and final_content:
                for tc in final_tool_calls:
                    fn    = tc.get("function", {})
                    targs = fn.get("arguments", {})
                    if isinstance(targs, str):
                        try:
                            targs = json.loads(targs)
                        except Exception:
                            targs = {}
                    self._execute_tool("save_memory", targs)
                assistant_msg2 = {"role": "assistant", "content": final_content}
                messages.append(assistant_msg2)
                self._conversation.append(assistant_msg2)
                self.ui.write_log(f"Sirius: {final_content}")
                if not _streamed:
                    self.speak(final_content)
                break

            all_silent    = True
            _tool_results: list[tuple[str, str]] = []

            for tc in final_tool_calls:
                fn    = tc.get("function", {})
                tname = fn.get("name", "")
                targs = fn.get("arguments", {})
                if isinstance(targs, str):
                    try:
                        targs = json.loads(targs)
                    except Exception:
                        targs = {}

                tc_id = tc.get("id", "")
                self.ui.write_log(f"SYS: > {tname}")
                result = self._execute_tool(tname, targs)

                if result != "__SILENT__":
                    all_silent = False
                    _tool_results.append((tname, result))

                tool_msg: dict = {
                    "role":    "tool",
                    "content": "Done." if result == "__SILENT__" else str(result),
                }
                if tc_id:
                    tool_msg["tool_call_id"] = tc_id

                messages.append(tool_msg)
                self._conversation.append(tool_msg)

            if all_silent:
                _saved_name: str | None = None
                for _tc in final_tool_calls:
                    _fn = _tc.get("function", {})
                    if _fn.get("name") == "save_memory":
                        _a = _fn.get("arguments", {})
                        if isinstance(_a, str):
                            try: _a = json.loads(_a)
                            except Exception: _a = {}
                        if isinstance(_a, dict) and _a.get("key") == "name" and _a.get("value"):
                            _saved_name = str(_a["value"])
                            break
                _ack = f"Compreendido, {_saved_name}." if _saved_name else "Anotado."
                _amsg = {"role": "assistant", "content": _ack}
                messages.append(_amsg)
                self._conversation.append(_amsg)
                self.ui.write_log(f"Sirius: {_ack}")
                self.speak(_ack)
                break

            if _tool_results and not any(n in _NEEDS_LLM_ROUND for n, _ in _tool_results):
                _, _reply = _tool_results[-1]
                _amsg = {"role": "assistant", "content": _reply}
                messages.append(_amsg)
                self._conversation.append(_amsg)
                self.ui.write_log(f"Sirius: {_reply}")
                self.speak(_reply)
                break

        if not self.ui.muted:
            self.ui.set_state("LISTENING")

    def _listen_whisper(self) -> None:
        vad = _VADBuffer()
        import queue as _queue
        q = _queue.Queue(maxsize=200)
        stream = None

        def callback(indata, frames, time_info, status):
            with self._speaking_lock:
                is_speaking = self._speaking
            if not is_speaking:
                try:
                    q.put_nowait(indata.copy())
                except _queue.Full:
                    pass
                rms = float(np.sqrt(np.mean(indata ** 2)))
                level = min(1.0, rms * 15)
                self.ui.set_voice_level(level)
                self._fft_mic_counter += 1
                if self._fft_mic_counter >= _SEND_FFT_INTERVAL:
                    self._fft_mic_counter = 0
                    bins = compute_fft_bins(indata)
                    self.ui.send_audio_bins(bins, "mic")
            else:
                self.ui.set_voice_level(0.0)

        try:
            # Wait for frontend before opening mic
            import time as _time
            while not self.ui.has_client:
                _time.sleep(0.5)

            stream = sd.InputStream(
                samplerate=16000,
                channels=CHANNELS,
                dtype="float32",
                blocksize=CHUNK_SIZE,
                callback=callback,
            )
            stream.start()
            self.ui.write_log("SYS: Mic active (Whisper STT).")

            was_active = self.ui.has_client and not self.ui.muted
            if not was_active:
                try:
                    stream.stop()
                except Exception:
                    pass
                self.ui.set_voice_level(0.0)

            while True:
                try:
                    was_active = self._poll_mute_stream(stream, was_active)
                    chunk = q.get(timeout=0.1)
                    audio = vad.process(chunk.flatten())
                    if audio is not None:
                        self.ui.set_state("THINKING")
                        text = self._stt.transcribe(audio)
                        if text.strip():
                            self._process_message(text)
                except _queue.Empty:
                    pass
        except Exception as e:
            print(f"[STT-Whisper] Mic error: {e}")
            traceback.print_exc()
        finally:
            try:
                stream.close()
            except Exception:
                pass

    def _listen_vosk(self) -> None:
        import queue as _queue
        q = _queue.Queue(maxsize=200)
        stream = None

        def callback(indata, frames, time_info, status):
            with self._speaking_lock:
                is_speaking = self._speaking
            if not is_speaking:
                try:
                    q.put_nowait(indata.copy())
                except _queue.Full:
                    pass
                rms = float(np.sqrt(np.mean(indata.astype(np.float32) ** 2)))
                level = min(1.0, rms * 15 / 32768.0)
                self.ui.set_voice_level(level)
                self._fft_mic_counter += 1
                if self._fft_mic_counter >= _SEND_FFT_INTERVAL:
                    self._fft_mic_counter = 0
                    bins = compute_fft_bins(indata)
                    self.ui.send_audio_bins(bins, "mic")
            else:
                self.ui.set_voice_level(0.0)

        try:
            # Wait for frontend before opening mic
            import time as _time
            while not self.ui.has_client:
                _time.sleep(0.5)

            stream = sd.InputStream(
                samplerate=16000,
                channels=CHANNELS,
                dtype="int16",
                blocksize=4096,
                callback=callback,
            )
            stream.start()
            self.ui.write_log("SYS: Mic active (Vosk STT).")

            was_active = self.ui.has_client and not self.ui.muted
            if not was_active:
                try:
                    stream.stop()
                except Exception:
                    pass
                self.ui.set_voice_level(0.0)

            while True:
                try:
                    was_active = self._poll_mute_stream(stream, was_active)
                    chunk = q.get(timeout=0.1)
                    text, is_final = self._stt.process_chunk(chunk.tobytes())
                    if is_final and text.strip():
                        self._process_message(text)
                except _queue.Empty:
                    pass
        except Exception as e:
            print(f"[STT-Vosk] Mic error: {e}")
            traceback.print_exc()
        finally:
            try:
                stream.close()
            except Exception:
                pass

    def _poll_mute_stream(self, stream, was_active: bool) -> bool:
        is_active = self.ui.has_client and not self.ui.muted
        if is_active != was_active:
            if not is_active:
                try:
                    stream.stop()
                except Exception:
                    pass
                self.ui.set_voice_level(0.0)
            else:
                try:
                    stream.start()
                except Exception:
                    pass
        return is_active

    def _text_command_loop(self) -> None:
        import queue as _queue
        while True:
            try:
                text = self._text_queue.get(timeout=0.5)
                if text.strip():
                    self._process_message(text)
            except _queue.Empty:
                pass

    def run(self) -> None:
        try:
            # Wait for a frontend client before starting
            self.ui.set_startup_status("Pronto — aguardando interface...")
            self.ui.wait_for_client_sync()
            self.ui.set_startup_status("Interface conectada. Inicializando...")

            from core.llm_client import ensure_llm_running, warmup_model
            self.ui.set_startup_progress(3, 5, "Verificando LLM...")
            self.ui.write_log("SYS: Checking LLM…")
            if ensure_llm_running():
                self.ui.write_log("SYS: LLM OK.")
            else:
                self.ui.write_log("ERR: LLM unavailable.")

            stt_engine   = self._config.get("stt_engine",   "whisper").lower()
            stt_language = self._config.get("stt_language", "auto")
            stt_model    = self._config.get("stt_model",    "base")
            tts_engine   = self._config.get("tts_engine",   "edgetts").lower()

            self.ui.show_startup_panel()

            _warmup_done = threading.Event()
            _stt_done    = threading.Event()

            def _do_warmup():
                try:
                    self.ui.set_startup_progress(3, 5, "Inicializando LLM...")
                    static_prompt = _load_system_prompt()
                    warmup_model(system_prompt=static_prompt)
                    self.ui.write_log("SYS: LLM ready.")
                    self.ui.mark_startup_ready("llm")
                    self.ui.set_startup_progress(3, 5, "LLM pronto")
                except Exception as e:
                    self.ui.write_log(f"ERR: LLM warmup — {e}")
                    self.ui.mark_startup_ready("llm", error=True)
                finally:
                    _warmup_done.set()

            def _do_stt():
                try:
                    self.ui.set_startup_progress(3, 5, f"Carregando STT ({stt_engine.upper()})...")
                    self.ui.write_log(f"SYS: Loading {stt_engine.upper()} STT…")
                    if stt_engine == "vosk":
                        from core.stt import VoskSTT
                        self._stt = VoskSTT(
                            self._config.get("vosk_model_path"),
                            language=stt_language,
                        )
                    else:
                        from core.stt import WhisperSTT
                        self._stt = WhisperSTT(stt_model, language=stt_language)
                    self.ui.write_log("SYS: STT ready.")
                    self.ui.mark_startup_ready("stt")
                    self.ui.set_startup_progress(3, 5, "STT pronto")
                except Exception as e:
                    self.ui.write_log(f"ERR: STT — {e}")
                    self.ui.mark_startup_ready("stt", error=True)
                finally:
                    _stt_done.set()

            def _do_tts():
                try:
                    self.ui.set_startup_progress(4, 5, "Carregando voz...")
                    self.ui.write_log(f"SYS: Loading {tts_engine.upper()} TTS…")
                    from core.tts import create_tts_player, set_audio_chunk_callback
                    self._tts = create_tts_player(self._config)
                    set_audio_chunk_callback(self._on_tts_audio_chunk)
                    self._tts_ready.set()
                    self.ui.write_log("SYS: TTS ready.")
                    self.ui.mark_startup_ready("tts")
                    self.ui.set_startup_progress(5, 5, "SIRIUS pronto!")
                    self.ui.set_startup_status("* All systems ready.")
                    self.ui.hide_startup_panel()
                    from core.sounds import play_init_sound_async
                    play_init_sound_async()
                except Exception as e:
                    traceback.print_exc()
                    self.ui.write_log(f"ERR: TTS — {e}")
                    self.ui.mark_startup_ready("tts", error=True)
                    self._tts_ready.set()

            self.ui.write_log("SYS: Loading systems in parallel…")
            threading.Thread(target=_do_warmup, daemon=True).start()
            threading.Thread(target=_do_stt,    daemon=True).start()
            threading.Thread(target=_do_tts,    daemon=True).start()

            _warmup_done.wait(timeout=60)
            _stt_done.wait(timeout=60)

            self.ui.write_log("SYS: SIRIUS online.")

            # Start TTS worker early so it can process the greeting
            threading.Thread(target=self._tts_worker, daemon=True).start()

            # Wait for TTS to be ready, then speak greeting
            self._tts_ready.wait(timeout=120)
            self._tts_queue.put("SIRIUS online.")
            import time as _time
            _time.sleep(0.5)  # Brief pause for TTS to start speaking

            # Now set LISTENING and start listen
            self.ui.set_state("LISTENING")
            threading.Thread(target=self._text_command_loop, daemon=True).start()

            if stt_engine == "vosk":
                self._listen_vosk()
            else:
                self._listen_whisper()

        except Exception as e:
            self.ui.write_log(f"ERR: Init failed — {e}")
            traceback.print_exc()


def _migrate_legacy_configs():
    """Move config keys from api_keys.json to configs.json (legacy migration)."""
    from core.config_loader import _CONFIGS_FILE, _SECRETS_FILE, _read_json, _write_json
    api_keys = _read_json(_SECRETS_FILE)
    config_keys = {"assistant_mode", "user_name", "llm_provider", "stt_engine",
                   "stt_language", "stt_model", "tts_engine", "tts_voice",
                   "tts_speed", "elevenlabs_api_key", "llm_url", "llm_model",
                   "os_system", "llm_provider"}
    migrated = {k: v for k, v in api_keys.items() if k in config_keys}
    if not migrated:
        return
    configs = _read_json(_CONFIGS_FILE)
    configs.update(migrated)
    _write_json(_CONFIGS_FILE, configs)
    # Remove migrated keys from api_keys.json
    for k in migrated:
        api_keys.pop(k, None)
    _write_json(_SECRETS_FILE, api_keys)


def main():
    # Preload torch to optimize Kokoro load
    def _preload_torch():
        try:
            pass
        except Exception:
            pass
    threading.Thread(target=_preload_torch, daemon=True).start()

    _migrate_legacy_configs()

    ui = SiriusUI()
    ui.show_startup_panel()

    # Start remote dashboard early (available before Assistant connects)
    def _start_dashboard():
        try:
            from dashboard.server import DashboardServer
            ds = DashboardServer()
            global _DASHBOARD, _DASHBOARD_READY
            ds._ready_event = _DASHBOARD_READY
            _DASHBOARD = ds
            print(f"[DEBUG main] Early dashboard thread started. IP={ds._ip}")
            asyncio.run(ds.serve())
        except Exception as e:
            print(f"[MAIN] Dashboard disabled: {e}")
            traceback.print_exc()
            _DASHBOARD = None
            _DASHBOARD_READY.set()
    print("[DEBUG main] Starting early dashboard thread...")
    threading.Thread(target=_start_dashboard, daemon=True).start()

    # Start the scheduled-task alarm loop (fires due reminders on PC + phone;
    # first tick also catches up on tasks missed while SIRIUS was offline).
    try:
        from core.task_alarm import start_scheduler
        start_scheduler()
        print("[DEBUG main] TaskAlarmScheduler started.")
    except Exception as e:
        print(f"[MAIN] Task alarm scheduler disabled: {e}")

    def runner():
        # Check WS server status FIRST — before blocking on onboarding
        if not _ws.was_started():
            print("[RUNNER] WS server not started — another backend instance is already running. Skipping assistant to avoid duplicate voice output.")
            _ws.show_windows_notification("SIRIUS", "Outra instância já está rodando. Esta será encerrada.")
            return
        ui.set_startup_progress(1, 5, "Verificando configuração inicial...")
        ui.wait_for_onboarding()
        ui.wait_for_api_key()

        from core.config_loader import get_all_config, get_secret
        cfg = get_all_config()

        mode = cfg.get("assistant_mode", "gemini")
        print(f"[RUNNER] Config loaded — assistant_mode={mode!r}, llm_provider={cfg.get('llm_provider', '<none>')!r}")
        print(f"[RUNNER] Full config keys: {list(cfg.keys())}")

        # Safeguard: if config says "local" but Gemini key exists, log and treat as gemini
        if mode == "local":
            gemini_key = cfg.get("gemini_api_key") or get_secret("gemini_api_key")
            if gemini_key:
                print("[RUNNER] assistant_mode='local' but gemini_api_key IS SET — forcing gemini mode")
                mode = "gemini"
            else:
                print("[RUNNER] assistant_mode='local' and no gemini key — staying local")

        # Safeguard: sync llm_provider with assistant_mode and persist
        from core.config_loader import set_config
        llm_prov = cfg.get("llm_provider", "").strip().lower()
        if mode == "gemini" and llm_prov != "gemini":
            print(f"[RUNNER] assistant_mode='gemini' but llm_provider='{llm_prov}' — fixing to 'gemini'")
            ui.write_log(f"SYS: assistant_mode='gemini' but llm_provider='{llm_prov}' — fixed to 'gemini'")
            set_config("llm_provider", "gemini")
        elif mode == "local" and llm_prov not in ("ollama", "openai", ""):
            print(f"[RUNNER] assistant_mode='local' but llm_provider='{llm_prov}' — fixing to 'ollama'")
            ui.write_log(f"SYS: assistant_mode='local' but llm_provider='{llm_prov}' — fixed to 'ollama'")
            set_config("llm_provider", "ollama")

        ui.set_startup_progress(2, 5, "Iniciando motor de IA...")

        try:
            if mode == "local":
                ui.write_log("SYS: Booting Local Offline Mode...")

                # Install dependencies on first run
                ui.write_log("SYS: Checking local dependencies...")
                _install_done = threading.Event()
                def _do_install():
                    try:
                        from core.installer import install_for_config
                        install_for_config(cfg, log=ui.write_log)
                    except Exception as e:
                        ui.write_log(f"ERR: Dependency install — {e}")
                    finally:
                        _install_done.set()
                threading.Thread(target=_do_install, daemon=True).start()
                _install_done.wait()

                sirius = SiriusLocal(ui)
                sirius.run()
            else:
                print(f"[RUNNER] Starting SiriusLive (mode={mode!r})...")
                ui.set_startup_progress(3, 5, "Aguardando interface...")
                sirius = SiriusLive(ui)
                global _sirius_instance
                _sirius_instance = sirius
                asyncio.run(sirius.run())
        except ValueError as e:
            msg = f"Configuração incompleta — {e}"
            ui.write_log(f"ERR: {msg}")
            print(f"[RUNNER] Config error: {e}")
            ui.set_startup_status(msg)
            ui.hide_startup_panel()
            _ws.show_windows_notification("SIRIUS", msg)
        except Exception as e:
            msg = f"Erro ao iniciar assistente — {e}"
            ui.write_log(f"ERR: {msg}")
            traceback.print_exc()
            ui.set_startup_status(msg)
            ui.hide_startup_panel()
            _ws.show_windows_notification("SIRIUS", msg)
        except KeyboardInterrupt:
            print("\nShutting down...")

    threading.Thread(target=runner, daemon=True).start()
    try:
        while True:
            import time
            time.sleep(1)
    except KeyboardInterrupt:
        print("\nShutting down...")

if __name__ == "__main__":
    main()
