"""
ws_server.py — Local WebSocket server for the Tauri/React frontend.

Runs on ws://localhost:8765. Provides the WsUI interface used by main.py.
Message protocol: JSON {type, payload}. No encryption (localhost only).
"""

# ruff: noqa: F823

from __future__ import annotations

import asyncio
import json
import threading
import time
import traceback
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

import websockets
from websockets.asyncio.server import serve as ws_serve

from actions.agents import agent_manager
from persistence.repository import Repository

_PORT = 8765
_HERE = Path(__file__).resolve().parent
_server_ready = threading.Event()


# ── Obsidian vault connection (retry-aware for slow Google Drive mounts) ──────

_OBSIDIAN_ATTEMPTS = 3
_OBSIDIAN_RETRY_DELAY = 180  # seconds between attempts (G: may take minutes to mount)

_last_obsidian_status: dict[str, Any] = {"status": "idle"}


def _set_obsidian_status(status: str, attempt: int | None = None, message: str = "") -> None:
    """Cache and broadcast the current Obsidian connection status."""
    entry: dict[str, Any] = {"status": status}
    if attempt is not None:
        entry["attempt"] = attempt
    if message:
        entry["message"] = message
    _last_obsidian_status.clear()
    _last_obsidian_status.update(entry)
    manager.broadcast_sync(WsMessage("obsidian_status", entry))


class ObsidianConnector:
    """Owns the vault watcher and retries the connection when the drive is slow.

    Google Drive virtual drives (e.g. G:) can take minutes to mount after login,
    so connecting runs up to N attempts spaced apart instead of failing once and
    giving up. The configured vault path is never cleared on failure — the UI
    shows 'erro ao conectar ao obsidian' plus a retry button instead.
    """

    def __init__(self) -> None:
        self._watcher: Any = None
        self._lock = threading.Lock()
        self._generation = 0

    def stop_watcher(self) -> None:
        if self._watcher is not None:
            try:
                self._watcher.stop()
            except Exception:
                pass
            self._watcher = None

    def _try_connect(self) -> Path | None:
        """Single attempt: check reachability and run the initial indexing."""
        from core.config_loader import get_config
        vault = get_config("obsidian_vault_path", "")
        if not vault:
            print("[Obsidian] No vault path configured; skipping connect.")
            return None
        vp = Path(vault)
        if not vp.is_dir():
            print(f"[Obsidian] Vault not reachable yet (drive may still be mounting): {vp}")
            return None
        from actions.obsidian_notes import load_notes_from_vault
        from actions.obsidian_tasks import load_tasks_from_vault
        load_tasks_from_vault(vp, tasks_subpath=get_config("obsidian_tasks_subpath", "Tarefas"))
        load_notes_from_vault(vp, notes_subpath=get_config("obsidian_notes_subpath", "Anotações"))
        return vp

    def _start_watcher(self, vp: Path) -> None:
        from actions.obsidian_notes import load_notes_from_vault
        from actions.obsidian_tasks import load_tasks_from_vault
        from actions.obsidian_watcher import ObsidianWatcher
        from core.config_loader import get_config
        tasks_subpath = get_config("obsidian_tasks_subpath", "Tarefas") or "Tarefas"
        notes_subpath = get_config("obsidian_notes_subpath", "Anotações") or "Anotações"
        self.stop_watcher()
        watcher = ObsidianWatcher(vp, tasks_subpath=tasks_subpath, notes_subpath=notes_subpath)
        watcher.start(
            on_task_change=lambda fp: load_tasks_from_vault(vp, tasks_subpath=tasks_subpath),
            on_note_change=lambda fp: load_notes_from_vault(vp, notes_subpath=notes_subpath),
        )
        self._watcher = watcher

    def connect_with_retry(self, attempts: int = _OBSIDIAN_ATTEMPTS,
                           delay_seconds: float = _OBSIDIAN_RETRY_DELAY) -> None:
        """Run the connect/retry cycle in a daemon thread (safe to call from WS loop).

        A new call cancels any previous running cycle (generation counter).
        """
        def _run() -> None:
            from core.config_loader import get_config
            if not get_config("obsidian_vault_path", ""):
                print("[Obsidian] No vault path configured; skipping retry loop.")
                return
            with self._lock:
                self._generation += 1
                gen = self._generation
                self.stop_watcher()

            def _stale() -> bool:
                with self._lock:
                    return gen != self._generation

            print(f"[Obsidian] Connecting to vault (up to {attempts} attempts, {delay_seconds:.0f}s apart)...")
            for attempt in range(1, attempts + 1):
                if _stale():
                    return
                _set_obsidian_status("connecting", attempt=attempt)
                try:
                    vp = self._try_connect()
                except Exception as e:
                    print(f"[Obsidian] Connect attempt {attempt}/{attempts} failed: {e}")
                    vp = None
                if vp is not None:
                    try:
                        self._start_watcher(vp)
                    except Exception as e:
                        print(f"[Obsidian] Watcher failed to start on {vp}: {e}")
                        vp = None
                if vp is not None:
                    _set_obsidian_status("connected")
                    print(f"[Obsidian] Vault connected on attempt {attempt}: {vp}")
                    return
                if attempt < attempts and not _stale():
                    deadline = time.monotonic() + delay_seconds
                    while time.monotonic() < deadline:
                        if _stale():
                            return
                        time.sleep(1.0)
            if _stale():
                return
            # All attempts failed — vault path stays untouched in config; UI shows
            # the error plus a retry button.
            _set_obsidian_status("error", message="erro ao conectar ao obsidian")
            print("[Obsidian] Could not connect after all attempts; vault path kept in config.")

        threading.Thread(target=_run, daemon=True, name="obsidian-connect").start()


obsidian_connector = ObsidianConnector()


def connect_obsidian_with_retry(attempts: int = _OBSIDIAN_ATTEMPTS,
                                delay_seconds: float = _OBSIDIAN_RETRY_DELAY) -> None:
    """Start (or restart) the background vault connect/retry cycle."""
    obsidian_connector.connect_with_retry(attempts=attempts, delay_seconds=delay_seconds)


def show_windows_notification(title: str, message: str) -> None:
    """Show a native Windows toast notification (silent fallback if unavailable)."""
    try:
        from win10toast import ToastNotifier
        ToastNotifier().show_toast(title, message, duration=10, threaded=True)
    except Exception:
        pass


def show_sticky_task_notification(
    title: str,
    message: str,
    on_done: Callable[[], None] | None = None,
    on_snooze: Callable[[], None] | None = None,
) -> bool:
    """Persistent Windows toast (scenario=reminder): stays on screen until the
    user dismisses it. Returns True if the persistent toast was shown."""
    try:
        from windows_toasts import (
            InteractableWindowsToaster,
            Toast,
            ToastButton,
            ToastScenario,
        )

        def _handle_activated(args):
            action = ""
            try:
                action = (getattr(args, "arguments", "") or "").lower()
            except Exception:
                pass
            try:
                if action == "sirius_snooze" and on_snooze:
                    on_snooze()
                elif on_done:
                    on_done()
            except Exception as e:
                print(f"[TaskToast] Action callback failed: {e}")

        toast = Toast(
            text_fields=[title, message],
            scenario=ToastScenario.Reminder,
            on_activated=_handle_activated,
        )

        if on_done:
            toast.AddAction(ToastButton(content="Concluído", arguments="sirius_done"))
        if on_snooze:
            toast.AddAction(ToastButton(content="Adiar 5 min", arguments="sirius_snooze"))
        # scenario=reminder requires at least one action to persist on screen;
        # without callbacks add a plain dismiss button.
        if not on_done and not on_snooze:
            toast.AddAction(ToastButton(content="Dispensar", arguments="sirius_dismiss"))

        toaster = InteractableWindowsToaster("SIRIUS")
        toaster.show_toast(toast)
        return True
    except Exception as e:
        print(f"[TaskToast] Persistent toast unavailable ({e}); falling back.")
    show_windows_notification(title, message)
    return False


def notify_pair_request(info: dict) -> None:
    """Broadcast a companion-app pairing request to the React UI.

    Payload: {device_id, name, model, platform}. The UI shows an
    Approve/Reject prompt and answers with {type: "pair_approve"}.
    """
    manager.broadcast_sync(WsMessage("pair_request", dict(info)))


def notify_task_alarm(task: dict) -> None:
    """Fire a due scheduled task: sticky toast on PC + broadcast to React UI.

    Button actions update the task directly in the database so both the PC
    and the phone converge on the new status at the next sync.
    """
    task_id = str(task.get("id", ""))
    title = str(task.get("title") or "Lembrete")
    due_raw = str(task.get("due_at") or "")
    try:
        from datetime import datetime as _dt

        due_txt = _dt.fromisoformat(due_raw).strftime("%H:%M")
    except ValueError:
        due_txt = due_raw

    message = f"Está na hora: {title} ({due_txt})"

    def _done():
        try:
            from persistence.repository import Repository
            Repository().complete_scheduled_task(task_id)
            print(f"[TaskAlarm] Task done via toast: {task_id}")
        except Exception as e:
            print(f"[TaskAlarm] Complete failed for {task_id}: {e}")

    def _snooze():
        try:
            from persistence.repository import Repository
            Repository().snooze_scheduled_task(task_id, minutes=5)
            print(f"[TaskAlarm] Task snoozed via toast: {task_id}")
        except Exception as e:
            print(f"[TaskAlarm] Snooze failed for {task_id}: {e}")

    show_sticky_task_notification(
        "SIRIUS — Tarefa agendada", message, on_done=_done, on_snooze=_snooze
    )

    try:
        manager.broadcast_sync(WsMessage("task_alarm", {
            "id": task_id,
            "text": title,
            "message": message,
            "due_at": due_raw,
        }))
    except Exception:
        pass
    print(f"[TaskAlarm] Fired: {title} ({due_txt}) [{task_id}]")


def _create_desktop_shortcut() -> None:
    """Create a desktop shortcut for SIRIUS (platform-aware)."""
    import os
    import sys
    shortcut_name = "SIRIUS"
    desktop = Path(os.path.expanduser("~/Desktop"))
    exe = Path(sys.executable).resolve()
    try:
        if sys.platform == "win32":
            import pythoncom
            pythoncom.CoInitialize()
            from win32com.client import Dispatch
            ws = Dispatch("WScript.Shell")
            scut = ws.CreateShortcut(str(desktop / f"{shortcut_name}.lnk"))
            scut.TargetPath = str(exe)
            scut.WorkingDirectory = str(exe.parent)
            scut.Description = "SIRIUS AI Assistant"
            scut.Save()
        elif sys.platform == "darwin":
            app_path = desktop / f"{shortcut_name}.app"
            app_path.mkdir(parents=True)
            (app_path / "Contents").mkdir()
            (app_path / "Contents/MacOS").mkdir()
            launcher = app_path / "Contents/MacOS" / shortcut_name
            launcher.write_text(f'#!/bin/bash\n"{exe}" &\n')
            os.chmod(launcher, 0o755)
        else:  # linux
            desktop_file = desktop / f"{shortcut_name}.desktop"
            desktop_file.write_text(
                f"[Desktop Entry]\nName={shortcut_name}\nExec={exe}\n"
                f"Terminal=false\nType=Application\n"
            )
            os.chmod(desktop_file, 0o755)
            os.system(f"gio set {desktop_file} metadata::trusted true 2>/dev/null")
        print(f"[Shortcut] Created on desktop: {desktop / shortcut_name}")
    except Exception as e:
        print(f"[Shortcut] Failed: {e}")


# ── Message types ──────────────────────────────────────────────────────────────

@dataclass
class WsMessage:
    type: str
    payload: dict = field(default_factory=dict)

    def to_json(self) -> str:
        return json.dumps({"type": self.type, **self.payload}, ensure_ascii=False)


# ── Connection Manager ─────────────────────────────────────────────────────────

class ConnectionManager:
    """Manages a single active frontend connection (or multiple, broadcasting to all)."""

    def __init__(self):
        self._lock = threading.Lock()
        self._connections: set[Any] = set()  # websocket objects
        self._loop: asyncio.AbstractEventLoop | None = None

        # Pending permission request
        self._perm_event: threading.Event | None = None
        self._perm_result: str = "deny"

        # Onboarding state
        self._onboarding_event: threading.Event | None = None
        self._onboarding_completed = False

        # First-client waiting
        self._client_event: threading.Event | None = None
        self._on_client_connect: Callable[[], None] | None = None

        # Callbacks from the frontend
        self.on_text_command: Callable[[str], None] | None = None
        self.on_mute_toggle: Callable[[bool], None] | None = None
        self.on_visibility: Callable[[bool], None] | None = None
        self.on_toggle_mute: Callable[[], None] | None = None
        self.on_remote_key_request: Callable | None = None
        self.on_interrupt: Callable[[], None] | None = None
        self.on_briefing_dismiss: Callable[[], None] | None = None
        # Companion app pairing decision from the React UI (device_id, approve)
        self.on_pair_response: Callable[[str, bool], None] | None = None

    def set_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        self._loop = loop

    def has_connections(self) -> bool:
        with self._lock:
            return len(self._connections) > 0

    def add(self, ws: Any) -> None:
        had_clients = False
        with self._lock:
            had_clients = len(self._connections) > 0
            self._connections.add(ws)
        # Notify anyone waiting for the first client to connect
        if self._client_event is not None:
            self._client_event.set()
        # If a client reconnects (not the first one), notify the callback
        if had_clients and self._on_client_connect:
            self._on_client_connect()

    def remove(self, ws: Any) -> None:
        with self._lock:
            self._connections.discard(ws)

    async def broadcast(self, msg: WsMessage) -> None:
        data = msg.to_json()
        dead: set[Any] = set()
        with self._lock:
            for ws in list(self._connections):
                try:
                    await ws.send(data)
                except Exception:
                    dead.add(ws)
            self._connections -= dead

    def broadcast_sync(self, msg: WsMessage) -> None:
        """Thread-safe synchronous broadcast. Call from any thread."""
        if self._loop is None or self._loop.is_closed():
            return
        try:
            asyncio.run_coroutine_threadsafe(self.broadcast(msg), self._loop)
        except Exception:
            pass

    # ── Permission handling ──────────────────────────────────────────────

    async def request_permission(self, perm_key: str, label: str, tool_name: str) -> str:
        """Ask the user for permission. Returns 'once' | 'always' | 'deny'."""
        self._perm_event = threading.Event()
        self._perm_result = "deny"
        await self.broadcast(WsMessage("permission_request", {
            "perm_key": perm_key,
            "label": label,
            "tool_name": tool_name,
        }))
        self._perm_event.wait(timeout=60)
        return self._perm_result

    def resolve_permission(self, result: str) -> None:
        self._perm_result = result
        if self._perm_event:
            self._perm_event.set()

    # ── Onboarding ───────────────────────────────────────────────────

    def mark_onboarding_completed(self) -> None:
        """Mark onboarding as completed in memory (survives reconnect within same session)."""
        self._onboarding_completed = True

    def resolve_onboarding(self) -> None:
        """Unblock the wait_for_onboarding() call."""
        self.mark_onboarding_completed()
        if self._onboarding_event:
            self._onboarding_event.set()
            self._onboarding_event = None


# ── Singleton ──────────────────────────────────────────────────────────────────

manager = ConnectionManager()
_current_ui: WsUI | None = None  # Set by WsUI.__init__

# Wire agent_manager to broadcast via WebSocket
agent_manager.set_broadcast(
    lambda msg_type, data: manager.broadcast_sync(WsMessage(msg_type, data))
)


# ── WebSocket handler ──────────────────────────────────────────────────────────

async def _send_onboarding_if_needed(ws) -> None:
    """If onboarding is pending, send the status to this client."""
    needed, step, partial = _check_onboarding()
    if needed:
        await ws.send(json.dumps({
            "type": "onboarding_needed",
            "step": step,
            "config": partial,
        }))


async def _handler(ws: websockets.asyncio.server.ServerConnection) -> None:
    """Handle a single WebSocket connection from the frontend."""
    manager.add(ws)
    try:
        # Send current startup progress to this newly connected client
        if _current_ui is not None:
            _current_ui._send_last_startup(ws)
        await _send_onboarding_if_needed(ws)

        async for raw in ws:
            try:
                data = json.loads(raw)
            except json.JSONDecodeError:
                continue

            msg_type = data.get("type", "")

            if msg_type == "command":
                text = data.get("text", "").strip()
                if text and manager.on_text_command:
                    manager.on_text_command(text)

            elif msg_type == "permission_response":
                result = data.get("result", "deny")
                manager.resolve_permission(result)

            elif msg_type == "mute_toggle":
                muted = data.get("muted", False)
                if manager.on_mute_toggle:
                    manager.on_mute_toggle(muted)
                else:
                    manager.broadcast_sync(WsMessage("muted", {"muted": muted}))

            elif msg_type == "toggle_mute":
                if manager.on_toggle_mute:
                    manager.on_toggle_mute()

            elif msg_type == "interrupt":
                if manager.on_interrupt:
                    manager.on_interrupt()

            elif msg_type == "briefing_dismissed":
                if manager.on_briefing_dismiss:
                    manager.on_briefing_dismiss()

            elif msg_type == "task_action":
                task_id = str(data.get("task_id", ""))
                action = str(data.get("action", "done"))
                try:
                    repo = Repository()
                    if action == "done":
                        repo.complete_scheduled_task(task_id)
                    elif action == "dismiss":
                        repo.dismiss_scheduled_task(task_id)
                    elif action == "snooze":
                        repo.snooze_scheduled_task(
                            task_id, minutes=int(data.get("minutes", 5) or 5)
                        )
                except Exception as e:
                    print(f"[TaskAlarm] UI action '{action}' failed for {task_id}: {e}")

            elif msg_type == "create_desktop_shortcut":
                threading.Thread(target=_create_desktop_shortcut, daemon=True).start()

            elif msg_type == "set_visibility":
                visible = data.get("visible", True)
                if manager.on_visibility:
                    manager.on_visibility(visible)

            elif msg_type == "get_config":
                from core.config_loader import get_all_config
                cfg = get_all_config()
                await ws.send(json.dumps({"type": "config", **cfg}))
            elif msg_type == "request_activity_data":  # noqa: F823
                try:
                    stats = Repository().get_weekly_stats()
                    top_apps = stats.get("top_apps") or []
                    if top_apps:
                        from core.app_icons import get_app_icons
                        icons = get_app_icons([a.get("name", "") for a in top_apps])
                        for a in top_apps:
                            a["icon"] = icons.get((a.get("name") or "").strip().lower())
                    await ws.send(json.dumps({"type": "activity_data", "stats": stats}))
                except Exception as e:
                    traceback.print_exc()
                    await ws.send(json.dumps({"type": "activity_error", "message": str(e)}))
            elif msg_type == "request_activity_summary":
                await ws.send(json.dumps({"type": "activity_summary", "text": "Resumo de atividade gerado pela IA."}))
            elif msg_type == "set_activity_monitor":  # noqa: F823
                try:
                    enabled = bool(data.get("enabled", False))
                    from core.config_loader import get_all_config, set_config
                    # Fonte única de verdade: configs.json como string "true"/"false"
                    set_config("activity_monitor", "true" if enabled else "false")
                    if enabled:
                        from core.activity_monitor import start_monitor
                        start_monitor()
                    else:
                        from core.activity_monitor import stop_monitor
                        stop_monitor()
                    # Devolve o config atualizado para a UI re-renderizar o toggle
                    await ws.send(json.dumps({"type": "config", **get_all_config()}))
                    await ws.send(json.dumps({"type": "activity_monitor_ack", "enabled": enabled}))
                except Exception as e:
                    traceback.print_exc()
                    await ws.send(json.dumps({"type": "activity_error", "message": str(e)}))
            elif msg_type == "clear_activity_data":
                try:
                    Repository().clear_activity_data()
                    await ws.send(json.dumps({"type": "activity_cleared", "ok": True}))
                except Exception as e:
                    traceback.print_exc()
                    await ws.send(json.dumps({"type": "activity_error", "message": str(e)}))
            elif msg_type == "save_config":
                from config.permissions import save_permissions
                from core.config_loader import get_all_config, save_configs, set_secret
                payload = data.get("payload", {})
                secrets = data.get("secrets", {})
                user_perms = data.get("permissions")
                mode = payload.get("assistant_mode", "")
                if mode == "gemini":
                    payload["llm_provider"] = "gemini"
                elif mode == "local":
                    payload["llm_provider"] = "ollama"
                if payload:
                    save_configs(payload)
                for key, value in secrets.items():
                    if value:
                        set_secret(key, value)
                if user_perms is not None:
                    save_permissions(user_perms)
                # Send updated config to frontend before restart
                cfg = get_all_config()
                await ws.send(json.dumps({"type": "config", **cfg}))
                await ws.send(json.dumps({"type": "config_saved", "ok": True}))
                # Re-index Obsidian vault if a path is configured now
                if payload.get("obsidian_vault_path"):
                    connect_obsidian_with_retry()
                # Reload assistant with new config
                try:
                    from main import request_restart
                    request_restart()
                except Exception:
                    pass

            elif msg_type == "google_auth":
                from core.google_auth import run_auth_flow
                def _do_auth():
                    try:
                        result_ok, result_msg = run_auth_flow()
                        manager.broadcast_sync(WsMessage("google_auth_result", {
                            "ok": result_ok, "msg": result_msg,
                        }))
                    except Exception as e:
                        print(f"[WS] google_auth error: {e}")
                threading.Thread(target=_do_auth, daemon=True).start()
                await ws.send(json.dumps({"type": "google_auth_result", "ok": True, "msg": "Abra o navegador para autenticar."}))

            elif msg_type == "get_google_status":
                from core.google_auth import is_token_valid
                valid = is_token_valid(time_buffer_s=300)
                await ws.send(json.dumps({"type": "google_status", "connected": valid}))

            elif msg_type == "get_onboarding_status":
                needed, step, partial = _check_onboarding()
                await ws.send(json.dumps({
                    "type": "onboarding_status",
                    "needed": needed,
                    "step": step,
                    "config": partial,
                }))

            elif msg_type == "get_permissions_list":
                from config.permissions import PERMISSION_META, get_permissions
                perms = get_permissions()
                items = []
                for key, meta in PERMISSION_META.items():
                    items.append({
                        "key": key,
                        "label": meta.get("label", key),
                        "description": meta.get("description", ""),
                        "granted": perms.get(key, True),
                    })
                await ws.send(json.dumps({
                    "type": "permissions_list",
                    "permissions": items,
                }))

            elif msg_type == "save_onboarding":
                try:
                    from config.permissions import save_permissions
                    from core.config_loader import (
                        _CONFIGS_FILE,
                        _read_json,
                        get_all_config,
                        get_base_dir,
                        save_configs,
                        set_secret,
                    )
                    cfg_data = data.get("config", {})
                    secrets = data.get("secrets", {})
                    user_perms = data.get("permissions")
                    mode = cfg_data.get("assistant_mode", "")
                    print(f"[WS] save_onboarding: received mode={mode!r}, config keys={list(cfg_data.keys())}")
                    if mode == "gemini":
                        cfg_data["llm_provider"] = "gemini"
                    elif mode == "local":
                        cfg_data["llm_provider"] = "ollama"
                    existing = _read_json(_CONFIGS_FILE)
                    existing.update(cfg_data)
                    if existing:
                        save_configs(existing)
                    for key, value in secrets.items():
                        if value:
                            set_secret(key, value)
                    if user_perms is not None:
                        save_permissions(user_perms)
                    await ws.send(json.dumps({"type": "onboarding_saved", "ok": True}))
                    manager.resolve_onboarding()
                    try:
                        from main import request_restart
                        request_restart()
                    except Exception:
                        pass
                except Exception as e:
                    traceback.print_exc()
                    await ws.send(json.dumps({
                        "type": "onboarding_saved",
                        "ok": False,
                        "error": str(e),
                    }))

            elif msg_type == "request_remote_key":
                print("[DEBUG WS] request_remote_key received from frontend")
                print(f"[DEBUG WS] manager.on_remote_key_request is {'SET' if manager.on_remote_key_request else 'NOT SET'}")
                if manager.on_remote_key_request:
                    try:
                        print("[DEBUG WS] Calling manager.on_remote_key_request()...")
                        result = manager.on_remote_key_request()
                        print(f"[DEBUG WS] Result: {result}")
                    except Exception as e:
                        print(f"[DEBUG WS] Exception in on_remote_key_request: {e}")
                        traceback.print_exc()
                        result = None
                    if result:
                        url, key, login_url, manual = result
                        print(f"[RemoteKey] Generated URL: {login_url}")
                        qr_data_url = ""
                        try:
                            import base64
                            from io import BytesIO

                            import qrcode
                            import qrcode.image.pil
                            print(f"[DEBUG WS] Generating QR code for {login_url}...")
                            qr = qrcode.make(login_url, image_factory=qrcode.image.pil.PilImage)
                            buf = BytesIO()
                            qr.save(buf, format="PNG")
                            b64 = base64.b64encode(buf.getvalue()).decode()
                            qr_data_url = f"data:image/png;base64,{b64}"
                            print(f"[DEBUG WS] QR code generated successfully ({len(b64)} bytes base64)")
                        except Exception as e:
                            print(f"[DEBUG WS] QR code generation failed: {e}")
                        await ws.send(json.dumps({
                            "type": "remote_key",
                            "url": url,
                            "key": key,
                            "login_url": login_url,
                            "manual": manual,
                            "qr_data_url": qr_data_url,
                        }))
                        print("[DEBUG WS] remote_key message sent to frontend")
                    else:
                        print("[DEBUG WS] on_remote_key_request returned None/empty")
                        await ws.send(json.dumps({
                            "type": "remote_key_error",
                            "message": "Dashboard unavailable.",
                        }))
                else:
                    print("[DEBUG WS] on_remote_key_request NOT SET")
                    await ws.send(json.dumps({
                        "type": "remote_key_error",
                        "message": "Remote control not initialized.",
                    }))

            elif msg_type == "pair_approve":
                device_id = str(data.get("device_id", "")).strip()
                approve = bool(data.get("approve", True))
                if manager.on_pair_response and device_id:
                    try:
                        manager.on_pair_response(device_id, approve)
                    except Exception as e:
                        print(f"[WS] pair_approve callback failed: {e}")
                        traceback.print_exc()

            elif msg_type == "radar_scan":
                from threading import Thread
                payload = data.get("payload", {})
                keywords = payload.get("keywords", "")
                max_jobs = payload.get("max_jobs", 5)
                sources = data.get("sources", ["linkedin"])
                Thread(target=_run_radar_scan, args=(keywords, max_jobs, sources), daemon=True).start()

            elif msg_type == "obsidian_set_path":
                vault_path = data.get("vault_path", "")
                tasks_subpath = data.get("tasks_subpath", "")
                notes_subpath = data.get("notes_subpath", "")
                sirius_subpath = data.get("sirius_subpath", "")
                from core.config_loader import set_config
                if vault_path:
                    set_config("obsidian_vault_path", vault_path)
                    if tasks_subpath:
                        set_config("obsidian_tasks_subpath", tasks_subpath)
                    if notes_subpath:
                        set_config("obsidian_notes_subpath", notes_subpath)
                    if sirius_subpath:
                        set_config("obsidian_sirius_subpath", sirius_subpath)
                    print(f"[WS] Obsidian vault path set to {vault_path}")
                    connect_obsidian_with_retry()
                    await ws.send(json.dumps({"type": "obsidian_set_path_ok", "ok": True}))
                else:
                    await ws.send(json.dumps({"type": "obsidian_set_path_ok", "ok": False, "error": "empty path"}))

            elif msg_type == "obsidian_retry_connect":
                # User pressed the retry button — restart the full attempt cycle.
                connect_obsidian_with_retry()
                await ws.send(json.dumps({**_last_obsidian_status, "type": "obsidian_status"}))

            elif msg_type == "get_obsidian_status":
                await ws.send(json.dumps({**_last_obsidian_status, "type": "obsidian_status"}))

            elif msg_type == "obsidian_set_retention":
                days = data.get("days", "")
                from core.config_loader import set_config
                if days and days.isdigit():
                    set_config("obsidian_task_retention_days", int(days))
                    await ws.send(json.dumps({"type": "obsidian_set_retention_ok", "ok": True}))
                else:
                    await ws.send(json.dumps({"type": "obsidian_set_retention_ok", "ok": False, "error": "invalid days"}))

            elif msg_type == "obsidian_get_tasks":
                repo = Repository()
                tasks = repo.get_pending_tasks()
                await ws.send(json.dumps({"type": "obsidian_tasks", "tasks": tasks}))

            elif msg_type == "obsidian_mark_done":
                task_id = data.get("task_id")
                end_date = data.get("end_date", "")
                if task_id is not None:
                    repo = Repository()
                    repo.mark_task_done(task_id, end_date)
                    await ws.send(json.dumps({"type": "obsidian_mark_done_ok", "ok": True}))
                else:
                    await ws.send(json.dumps({"type": "obsidian_mark_done_ok", "ok": False, "error": "invalid task_id"}))

            elif msg_type == "obsidian_cleanup_tasks":
                repo = Repository()
                deleted = repo.cleanup_completed_tasks()
                await ws.send(json.dumps({"type": "obsidian_cleanup_tasks_ok", "ok": True, "deleted": deleted}))

            elif msg_type == "obsidian_search_notes":
                # Simple return list of note file paths (no vector similarity)
                repo = Repository()
                rows = repo.db.fetchall("SELECT id, file_path FROM obsidian_notes LIMIT 20")
                notes = [{"id": r["id"], "file_path": r["file_path"]} for r in rows]
                await ws.send(json.dumps({"type": "obsidian_notes", "notes": notes}))

            elif msg_type == "obsidian_list_dirs":
                # List directories under the vault root path supplied in payload.vault_path
                vault_path = data.get("vault_path", "")
                if not vault_path:
                    await ws.send(json.dumps({"type": "obsidian_list_dirs_ok", "ok": False, "error": "missing vault_path"}))
                    return

                def _walk_dirs(base: str) -> list[str]:
                    import os
                    dirs = []
                    for root, subdirs, files in os.walk(base):
                        for d in subdirs:
                            full = os.path.join(root, d)
                            rel = os.path.relpath(full, base)
                            dirs.append(rel.replace(os.sep, "/"))
                    return dirs

                try:
                    base = Path(vault_path).resolve()
                    if not base.is_dir():
                        await ws.send(json.dumps({"type": "obsidian_list_dirs_ok", "ok": False, "error": "path not found"}))
                        return
                    dirs = await asyncio.to_thread(_walk_dirs, str(base))
                    await ws.send(json.dumps({"type": "obsidian_list_dirs_ok", "ok": True, "dirs": dirs}))
                except Exception as e:
                    await ws.send(json.dumps({"type": "obsidian_list_dirs_ok", "ok": False, "error": str(e)}))

            elif msg_type == "obsidian_list_drives":
                # Windows drive letters (or filesystem root on other platforms)
                def _list_drives() -> list[str]:
                    import os
                    if os.name == "nt":
                        import string
                        drives = []
                        for letter in string.ascii_uppercase:
                            root = f"{letter}:\\"
                            if os.path.exists(root):
                                drives.append(root)
                        return drives
                    return [os.path.abspath(os.sep)]

                try:
                    drives = await asyncio.to_thread(_list_drives)
                    await ws.send(json.dumps({"type": "obsidian_list_drives_ok", "ok": True, "drives": drives}))
                except Exception as e:
                    await ws.send(json.dumps({"type": "obsidian_list_drives_ok", "ok": False, "error": str(e)}))

            elif msg_type == "obsidian_list_children":
                # List immediate subdirectories (one level) of a given path
                def _list_children(base: str) -> list[dict]:
                    import os
                    children = []
                    try:
                        for entry in sorted(os.scandir(base), key=lambda e: e.name.lower()):
                            if entry.is_dir():
                                children.append({
                                    "name": entry.name,
                                    "path": os.path.abspath(entry.path),
                                })
                    except PermissionError:
                        pass
                    except OSError:
                        pass
                    return children

                try:
                    base = data.get("path", "")
                    if not base:
                        base = Path.home().resolve()
                    if not Path(base).is_dir():
                        await ws.send(json.dumps({"type": "obsidian_list_children_ok", "ok": False, "error": "path not found"}))
                        return
                    children = await asyncio.to_thread(_list_children, base)
                    await ws.send(json.dumps({
                        "type": "obsidian_list_children_ok",
                        "ok": True,
                        "path": str(Path(base).resolve()),
                        "children": children,
                    }))
                except Exception as e:
                    await ws.send(json.dumps({"type": "obsidian_list_children_ok", "ok": False, "error": str(e)}))

            elif msg_type == "list_radar_files":
                from core.config_loader import get_base_dir
                jobs_dir = get_base_dir() / "jobs"
                try:
                    files = sorted(
                        (f.name for f in jobs_dir.iterdir() if f.is_file() and f.suffix == ".json"),
                        key=lambda f: jobs_dir / f,
                        reverse=True,
                    )
                    await ws.send(json.dumps({"type": "radar_files", "files": list(files)[:50]}))
                except Exception:
                    pass

            elif msg_type == "read_radar_file":
                from core.config_loader import get_base_dir
                jobs_dir = get_base_dir() / "jobs"
                filename = data.get("filename", "")
                if filename and not any(c in filename for c in "/\\"):
                    path = jobs_dir / filename
                    try:
                        with open(path, "r", encoding="utf-8") as f:
                            content = json.load(f)
                        await ws.send(json.dumps({"type": "radar_file_content", "filename": filename, "content": content}))
                    except Exception:
                        pass

            elif msg_type == "onboarding_done":
                print("[WS] Onboarding completed by frontend — resolving barrier.")
                manager.resolve_onboarding()

            elif msg_type == "shutdown":
                print("[WS] Shutdown requested via WebSocket — exiting...")
                import os
                os._exit(0)

            elif msg_type == "get_plugins_list":
                from core.plugin_loader import discover_plugins
                from main import TOOL_DECLARATIONS
                _core_names = {d["name"] for d in TOOL_DECLARATIONS}
                _plugins_dir = Path(__file__).resolve().parent / "plugins"
                registry = discover_plugins(_plugins_dir, _core_names, logger=print)
                await ws.send(json.dumps({
                    "type": "plugins_list",
                    "plugins": registry.list_for_ui(),
                }))

            elif msg_type == "toggle_plugin":
                plugin_name = data.get("plugin_name", "")
                enabled = data.get("enabled", False)
                from memory.config_manager import save_plugin_enabled
                save_plugin_enabled(plugin_name, enabled)
                from core.config_loader import get_all_config
                cfg = get_all_config()
                await ws.send(json.dumps({"type": "config", **cfg}))
                await ws.send(json.dumps({"type": "plugin_toggled", "plugin_name": plugin_name, "enabled": enabled}))

            elif msg_type == "get_monitors_list":
                from actions.background_monitor import list_monitors
                topics = list_monitors()
                await ws.send(json.dumps({"type": "monitors_list", "topics": topics}))

            elif msg_type == "add_monitor":
                topic = data.get("topic", "").strip()
                from actions.background_monitor import add_monitor
                result = add_monitor(topic)
                await ws.send(json.dumps({"type": "monitor_added", "topic": topic, "result": result}))
                # Send updated list
                from actions.background_monitor import list_monitors
                topics = list_monitors()
                await ws.send(json.dumps({"type": "monitors_list", "topics": topics}))

            elif msg_type == "remove_monitor":
                topic = data.get("topic", "").strip()
                from actions.background_monitor import remove_monitor
                result = remove_monitor(topic)
                await ws.send(json.dumps({"type": "monitor_removed", "topic": topic, "result": result}))
                # Send updated list
                from actions.background_monitor import list_monitors
                topics = list_monitors()
                await ws.send(json.dumps({"type": "monitors_list", "topics": topics}))

            # ── Agent orchestration messages ──────────────────────────────
            elif msg_type in ("agent_create_session", "agent_send_prompt",
                              "agent_switch", "agent_cli_run", "agent_close_session",
                              "agent_create_pty", "agent_pty_input",
                              "agent_pty_resize", "agent_close_pty"):
                from actions.agents import handle_agent_message
                await handle_agent_message(data, ws.send)

    except websockets.exceptions.ConnectionClosed:
        pass
    except Exception:
        traceback.print_exc()
    finally:
        manager.remove(ws)


def _check_onboarding() -> tuple[bool, str, dict]:
    """Check if onboarding is needed. Returns (needed, step, partial_config)."""
    # If already completed in this session, skip file checks entirely
    if manager._onboarding_completed:
        return False, "", {}
    from core.config_loader import get_all_config, get_secret
    merged = get_all_config()
    mode = merged.get("assistant_mode", "")
    name = merged.get("user_name", "")
    partial = {}
    if not mode:
        return True, "mode", partial
    partial["assistant_mode"] = mode
    if mode == "gemini":
        provider = merged.get("llm_provider", "").strip().lower()
        if provider in ("ollama", "openai", ""):
            return True, "mode", partial
    if not name:
        return True, "name", partial
    partial["user_name"] = name
    if mode == "gemini":
        key = merged.get("gemini_api_key") or get_secret("gemini_api_key")
        if not key:
            return True, "keys", {**partial, "gemini_api_key": ""}
    return False, "", partial


def _run_radar_scan(keywords: str, max_jobs: int, sources: list[str]) -> None:
    """Run a radar job scan in a background thread and broadcast results."""
    def _scan():
        try:
            import asyncio as _aio
            loop = _aio.new_event_loop()
            _aio.set_event_loop(loop)
            total_new = 0

            if "linkedin" in sources:
                manager.broadcast_sync(WsMessage("radar_log", {"text": "Iniciando scraper do LinkedIn..."}))
                try:
                    from core.intel.linkedin_scraper import scrape_linkedin_jobs
                    new_jobs = loop.run_until_complete(scrape_linkedin_jobs(keywords, max_jobs=max_jobs))
                    total_new += new_jobs
                    manager.broadcast_sync(WsMessage("radar_log", {"text": f"LinkedIn finalizado. {new_jobs} novas vagas."}))
                except Exception as e:
                    manager.broadcast_sync(WsMessage("radar_log", {"text": f"LinkedIn: {e}"}))

            if "google_jobs" in sources:
                manager.broadcast_sync(WsMessage("radar_log", {"text": "Procurando vagas no Google Jobs..."}))
                try:
                    from core.intel.google_jobs_scraper import scrape_google_jobs
                    new_jobs = loop.run_until_complete(scrape_google_jobs(keywords, max_jobs=max_jobs))
                    total_new += new_jobs
                    manager.broadcast_sync(WsMessage("radar_log", {"text": f"Google Jobs finalizado. {new_jobs} novas vagas."}))
                except Exception as e:
                    manager.broadcast_sync(WsMessage("radar_log", {"text": f"Google Jobs: {e}"}))

            if total_new >= 0:
                manager.broadcast_sync(WsMessage("radar_log", {"text": "Analisando compatibilidade..."}))
                try:
                    from core.intel.job_analyzer import analyze_all_jobs
                    analyzed = analyze_all_jobs()
                    manager.broadcast_sync(WsMessage("radar_log", {"text": f"Análise finalizada. {analyzed} vagas analisadas."}))
                except Exception as e:
                    manager.broadcast_sync(WsMessage("radar_log", {"text": f"Análise: {e}"}))

            # Load results from saved file
            from pathlib import Path
            jobs_path = Path(__file__).resolve().parent / "memory" / "linkedin_jobs.json"
            jobs = []
            if jobs_path.exists():
                try:
                    import json
                    jobs = json.loads(jobs_path.read_text(encoding="utf-8"))
                except Exception:
                    pass
            manager.broadcast_sync(WsMessage("radar_results", {"jobs": jobs}))
        except Exception as e:
            manager.broadcast_sync(WsMessage("radar_log", {"text": f"Erro: {e}"}))

    threading.Thread(target=_scan, daemon=True, name="radar-scan").start()


# ── Start / Stop ───────────────────────────────────────────────────────────────

_loop: asyncio.AbstractEventLoop | None = None
_server_instance: asyncio.AbstractServer | None = None
_server_started = False


def _release_port(port: int) -> None:
    """Kill any process holding the given port (Windows)."""
    import subprocess
    import sys
    _cnw = 0x08000000 if sys.platform == "win32" else 0
    try:
        output = subprocess.check_output(
            ["netstat", "-ano"], shell=False, text=True, stderr=subprocess.DEVNULL,
            creationflags=_cnw,
        )
        for line in output.splitlines():
            if f":{port}" in line and "LISTENING" in line:
                parts = line.strip().split()
                if parts:
                    pid = parts[-1]
                    try:
                        subprocess.run(
                            ["taskkill", "/F", "/PID", pid],
                            capture_output=True, text=True, timeout=5,
                            creationflags=_cnw,
                        )
                        print(f"[WS] Killed previous process holding port {port} (PID: {pid})")
                    except Exception:
                        pass
    except Exception:
        pass


async def _run_server() -> None:
    global _server_instance, _server_started
    print(f"[WS] _run_server() starting on 127.0.0.1:{_PORT}")
    try:
        async with ws_serve(_handler, "127.0.0.1", _PORT) as server:
            _server_instance = server
            _server_started = True
            _server_ready.set()
            print(f"[WS] UI WebSocket server started on ws://127.0.0.1:{_PORT}")
            await asyncio.Event().wait()
    except OSError as e:
        print(f"[WS] Port {_PORT} already in use — another backend instance is already running. Giving up. Error: {e}")
        _server_started = False
        _server_ready.set()
    except Exception as e:
        print(f"[WS] _run_server() FAILED with exception: {e}")
        traceback.print_exc()
        _server_started = False
        _server_ready.set()


def was_started() -> bool:
    """Return whether the WebSocket server bound successfully."""
    return _server_started


def start() -> tuple[asyncio.AbstractEventLoop, threading.Thread | None]:
    """Start the WebSocket server in a background thread. Returns (loop, thread)."""
    global _loop, _server_started
    print(f"[WS] start() called - releasing port {_PORT}")
    _release_port(_PORT)
    _loop = asyncio.new_event_loop()
    manager.set_loop(_loop)
    _server_started = False
    _server_ready.clear()

    def _start() -> None:
        print("[WS] Background thread starting, setting event loop")
        asyncio.set_event_loop(_loop)
        try:
            _loop.run_until_complete(_run_server())
        except (KeyboardInterrupt, RuntimeError, asyncio.CancelledError) as e:
            print(f"[WS] Thread exception: {type(e).__name__}: {e}")
            _server_ready.set()
        except Exception as e:
            print(f"[WS] Thread FAILED with unexpected exception: {e}")
            traceback.print_exc()
            _server_ready.set()

    t = threading.Thread(target=_start, daemon=True, name="ws-server")
    print("[WS] Starting ws-server thread")
    t.start()
    print("[WS] Waiting for server_ready event (timeout=5s)")
    _server_ready.wait(timeout=5)
    print(f"[WS] start() returning, server_started={_server_started}")
    return _loop, t


def stop() -> None:
    """Gracefully stop the WebSocket server."""
    if _server_instance is not None:
        _server_instance.close()
    if _loop is not None and not _loop.is_closed():
        # Cancel all pending tasks before stopping
        async def _cancel_all():
            for task in asyncio.all_tasks(_loop):
                task.cancel()
        try:
            fut = asyncio.run_coroutine_threadsafe(_cancel_all(), _loop)
            fut.result(timeout=3)
        except Exception:
            pass
        try:
            _loop.call_soon_threadsafe(_loop.stop)
        except Exception:
            pass



# ── WsUI — drop-in replacement for SiriusUI ────────────────────────────────────

class WsUI:
    """Interface-compatible with SiriusUI but talks WebSocket instead of PyQt6.

    Drop this in wherever main.py uses `self.ui` or `ui = SiriusUI()`.
    """

    def __init__(self):
        self._muted = False
        self._muted_by_user = False
        self._window_visible = True
        self._visibility_set = False
        self._current_state = "INITIALISING"
        self._current_file_path: str | None = None
        self._on_text_command: Callable | None = None
        self._on_remote_clicked: Callable | None = None
        self._on_interrupt: Callable | None = None
        self._on_briefing_dismiss: Callable | None = None
        self._ready = True  # No API key waiting needed
        self._last_startup_msg: dict | None = None

        # Server is started once at module level
        self.root = _WsRootShim()

        # Wire up frontend callbacks
        manager.on_text_command = self._on_command_from_ws
        manager.on_mute_toggle = self._on_mute_from_ws
        manager.on_visibility = self._on_visibility_from_ws
        manager.on_toggle_mute = self._on_toggle_mute_from_ws
        manager.on_interrupt = self._on_interrupt_from_ws
        manager.on_briefing_dismiss = self._on_briefing_dismiss_from_ws
        manager._on_client_connect = self._on_reconnect

        global _current_ui
        _current_ui = self

    # ── properties ───────────────────────────────────────────────────────

    @property
    def muted(self) -> bool:
        return self._muted or not self._window_visible

    @muted.setter
    def muted(self, v: bool):
        if v != self._muted:
            self._muted = v
            self._muted_by_user = v
            manager.broadcast_sync(WsMessage("muted", {"muted": self.muted}))

    @property
    def has_client(self) -> bool:
        return manager.has_connections()

    def request_close_app(self) -> None:
        """Send close_app message to frontend (thread-safe)."""
        manager.broadcast_sync(WsMessage("close_app"))

    def request_hide_interface(self) -> None:
        """Send hide_interface message to frontend (thread-safe)."""
        manager.broadcast_sync(WsMessage("hide_interface"))

    async def wait_for_client_async(self, timeout: float = 30.0) -> None:
        """Block until at least one frontend WebSocket client connects (async)."""
        if manager.has_connections():
            return
        manager._client_event = threading.Event()
        try:
            start = time.monotonic()
            while not manager.has_connections():
                remaining = timeout - (time.monotonic() - start)
                if remaining <= 0:
                    print("[WS] Timeout waiting for frontend client — proceeding anyway")
                    break
                manager._client_event.wait(timeout=min(0.5, remaining))
        finally:
            manager._client_event = None

    def wait_for_client_sync(self) -> None:
        """Block until at least one frontend WebSocket client connects (sync)."""
        if manager.has_connections():
            return
        manager._client_event = threading.Event()
        try:
            while not manager.has_connections():
                manager._client_event.wait(timeout=0.5)
        finally:
            manager._client_event = None

    @property
    def current_file(self) -> str | None:
        return self._current_file_path

    @property
    def on_text_command(self):
        return self._on_text_command

    @on_text_command.setter
    def on_text_command(self, cb):
        self._on_text_command = cb
        # If cb is set, forward incoming WS commands to it
        manager.on_text_command = self._on_command_from_ws

    @property
    def on_remote_clicked(self):
        return self._on_remote_clicked

    @on_remote_clicked.setter
    def on_remote_clicked(self, cb):
        self._on_remote_clicked = cb
        # Wire the WebSocket handler too
        manager.on_remote_key_request = cb

    @property
    def on_interrupt(self):
        return self._on_interrupt

    @on_interrupt.setter
    def on_interrupt(self, cb):
        self._on_interrupt = cb
        manager.on_interrupt = self._on_interrupt_from_ws

    @property
    def on_briefing_dismiss(self):
        return self._on_briefing_dismiss

    @on_briefing_dismiss.setter
    def on_briefing_dismiss(self, cb):
        self._on_briefing_dismiss = cb
        manager.on_briefing_dismiss = self._on_briefing_dismiss_from_ws

    # ── internal ─────────────────────────────────────────────────────────

    def _on_interrupt_from_ws(self) -> None:
        cb = getattr(self, "on_interrupt", None)
        if cb:
            cb()

    def _on_briefing_dismiss_from_ws(self) -> None:
        cb = getattr(self, "on_briefing_dismiss", None)
        if cb:
            cb()

    def _on_command_from_ws(self, text: str) -> None:
        if self._on_text_command:
            self._on_text_command(text)

    def _recalc_muted(self) -> None:
        """Single source of truth: muted = user_intent OR window_hidden."""
        self._muted = self._muted_by_user or not self._window_visible

    def _on_mute_from_ws(self, muted: bool) -> None:
        self._muted_by_user = muted
        self._recalc_muted()
        manager.broadcast_sync(WsMessage("muted", {"muted": self.muted}))

    def _on_visibility_from_ws(self, visible: bool) -> None:
        self._window_visible = visible
        self._visibility_set = True
        self._recalc_muted()
        manager.broadcast_sync(WsMessage("muted", {"muted": self.muted}))
        cb = getattr(self, "on_visibility", None)
        if cb:
            cb(visible)

    def _on_toggle_mute_from_ws(self) -> None:
        self._muted_by_user = not self._muted_by_user
        self._recalc_muted()
        manager.broadcast_sync(WsMessage("muted", {"muted": self.muted}))

    def _on_reconnect(self) -> None:
        """Called when a new frontend client connects while another already exists (reconnect)."""
        print("[WS] Frontend reconnected — re-sending current state.")
        self.send_current_state()
        manager.broadcast_sync(WsMessage("muted", {"muted": self.muted}))
        if hasattr(self, '_current_file_path') and self._current_file_path:
            manager.broadcast_sync(WsMessage("file_selected", {"path": self._current_file_path}))
        # Re-send last startup status if still relevant
        if self._last_startup_msg is not None and self._last_startup_msg.get("action") != "hide":
            manager.broadcast_sync(WsMessage("startup", self._last_startup_msg))

    # ── public API ───────────────────────────────────────────────────────

    def write_log(self, text: str) -> None:
        manager.broadcast_sync(WsMessage("log", {"text": text}))

    def set_state(self, state: str) -> None:
        self._current_state = state
        manager.broadcast_sync(WsMessage("state", {"state": state}))

    def send_current_state(self) -> None:
        """Broadcast the current assistant state to all connected clients.
        Used when a new frontend connects, so it doesn't stay on INITIALISING."""
        manager.broadcast_sync(WsMessage("state", {"state": self._current_state}))

    def set_voice_level(self, level: float) -> None:
        manager.broadcast_sync(WsMessage("voice_level", {"level": level}))

    def send_audio_bins(self, bins: list[float], source: str) -> None:
        manager.broadcast_sync(WsMessage("audio_bins", {"bins": bins, "source": source}))

    def show_content(self, title: str, text: str) -> None:
        manager.broadcast_sync(WsMessage("content_panel", {"title": title, "text": text}))

    def start_speaking(self) -> None:
        self.set_state("SPEAKING")

    def stop_speaking(self) -> None:
        if not self.muted:
            self.set_state("LISTENING")

    def wait_for_api_key(self) -> None:
        pass  # No Qt blocking needed

    def wait_for_onboarding(self) -> None:
        """Block until the frontend completes onboarding (first-run wizard)."""
        needed, step, partial = _check_onboarding()
        if not needed:
            return
        print(f"[WS] Onboarding needed (step={step}) — waiting for frontend...")
        manager._onboarding_event = threading.Event()
        # Re-send onboarding_needed to any already-connected clients
        # (they may have missed the first push if React wasn't mounted yet)
        manager.broadcast_sync(WsMessage("onboarding_needed", {
            "step": step,
            "config": partial,
        }))
        while True:
            signaled = manager._onboarding_event.wait(timeout=600)
            if signaled:
                print("[WS] Onboarding complete, starting assistant...")
                return
            # Timeout — re-check if onboarding is still needed.
            # The frontend may have been recreated (dev mode) or the config
            # may have been written manually (e.g. copied from a backup).
            still_needed, still_step, still_partial = _check_onboarding()
            if not still_needed:
                print("[WS] Onboarding no longer needed (config was set externally) — proceeding.")
                return
            print(f"[WS] [WAIT] Still waiting for onboarding (step={still_step}) — re-sending notification...")
            manager._onboarding_event.clear()
            manager.broadcast_sync(WsMessage("onboarding_needed", {
                "step": still_step,
                "config": still_partial,
            }))

    def ask_permission_sync(self, perm_key: str, label: str, tool_name: str) -> str:
        """Block the calling thread until the frontend user responds."""
        try:
            coro = manager.request_permission(perm_key, label, tool_name)
            fut = asyncio.run_coroutine_threadsafe(
                coro, manager._loop
            )
            return fut.result(timeout=60)
        except Exception:
            return "deny"

    def show_startup_panel(self) -> None:
        self._last_startup_msg = {"action": "show"}
        manager.broadcast_sync(WsMessage("startup", {"action": "show"}))

    def mark_startup_ready(self, key: str, error: bool = False) -> None:
        action = "error" if error else "ready"
        self._last_startup_msg = {"action": action, "key": key}
        manager.broadcast_sync(WsMessage("startup", {
            "action": action,
            "key": key,
        }))

    def set_startup_status(self, text: str) -> None:
        self._last_startup_msg = {"action": "status", "text": text}
        manager.broadcast_sync(WsMessage("startup", {
            "action": "status",
            "text": text,
        }))

    def set_startup_progress(self, current: int, total: int, text: str) -> None:
        self._last_startup_msg = {
            "action": "progress",
            "current": current,
            "total": total,
            "text": text,
        }
        manager.broadcast_sync(WsMessage("startup", self._last_startup_msg))

    def hide_startup_panel(self) -> None:
        self._last_startup_msg = {"action": "hide"}
        manager.broadcast_sync(WsMessage("startup", {"action": "hide"}))

    def _send_last_startup(self, ws) -> None:
        """Re-send the last startup status to a newly connected client."""
        if self._last_startup_msg is not None:
            coro = ws.send(json.dumps({"type": "startup", **self._last_startup_msg}))
            asyncio.run_coroutine_threadsafe(coro, manager._loop)

    def notify_phone_connected(self) -> None:
        manager.broadcast_sync(WsMessage("notification", {
            "text": "Phone connected via Remote Dashboard.",
        }))

    @property
    def remote_key_data(self):
        """Triggered when user clicks Remote Control button."""
        if self._on_remote_clicked:
            return self._on_remote_clicked()
        return None

    def request_remote_key(self) -> dict | None:
        """Returns {"url":..., "key":..., "login_url":..., "manual":...} or None."""
        if self._on_remote_clicked:
            result = self._on_remote_clicked()
            if result:
                url, key, login_url, manual = result
                return {"url": url, "key": key, "login_url": login_url, "manual": manual}
        return None

    # ── camera preview ───────────────────────────────────────────────

    def start_camera_stream(self):
        """Return a callable so the caller can send frames later.

        The returned function accepts a single argument (bytes or str —
        base64-encoded JPEG) and broadcasts it as 'camera_frame'.
        """
        def _send_frame(img_bytes_or_b64):
            if isinstance(img_bytes_or_b64, bytes):
                import base64
                b64 = base64.b64encode(img_bytes_or_b64).decode("ascii")
            else:
                b64 = img_bytes_or_b64
            manager.broadcast_sync(WsMessage("camera_frame", {"image": b64}))
        return _send_frame

    def stop_camera_stream(self) -> None:
        """Tell the frontend to hide the camera preview overlay."""
        manager.broadcast_sync(WsMessage("camera_stop"))

    def show_camera_frame(self, img_bytes_or_b64) -> None:
        """Send a single camera frame (bytes or base64 str)."""
        if isinstance(img_bytes_or_b64, bytes):
            import base64
            b64 = base64.b64encode(img_bytes_or_b64).decode("ascii")
        else:
            b64 = img_bytes_or_b64
        manager.broadcast_sync(WsMessage("camera_frame", {"image": b64}))

    # ── proactive suggestion ─────────────────────────────────────────

    def show_suggestion(self, text: str) -> None:
        """Send a proactive suggestion to the frontend."""
        manager.broadcast_sync(WsMessage("proactive_suggestion", {"text": text}))

    # ── morning briefing ──────────────────────────────────────────────

    def show_briefing(self, greeting: str, headlines: list[str] | None = None) -> None:
        """Send a morning/startup briefing to the frontend."""
        manager.broadcast_sync(WsMessage("briefing", {
            "greeting": greeting,
            "headlines": headlines or [],
        }))

    def shutdown(self) -> None:
        """Signal the mainloop to exit."""
        stop()
        self.root._running = False


class _WsRootShim:
    """Minimal shim so main.py can call ui.root.mainloop()."""

    _running = True

    def mainloop(self) -> None:
        """Blocks until KeyboardInterrupt or stop() is called."""
        try:
            while self._running:
                time.sleep(0.5)
        except KeyboardInterrupt:
            stop()
            self._running = False

    def protocol(self, *_):
        pass
