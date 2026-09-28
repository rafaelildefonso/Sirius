"""
main_headless.py — Lightweight entry point for the Pane-integrated sidecar.

Starts the WebSocket server (port 8765) + planner/executor pipeline.
No audio, no microphone, no TTS, no Gemini Live session.
Pane handles STT; Sirius handles NLU + actions.

The pane_command and pane_agent_status_request handlers are registered
directly in ws_server.py, so this file only needs to wire up the
on_text_command callback to the AgentExecutor.
"""
import os
import sys
import threading
import time
import traceback
from pathlib import Path

# ── Windows: force CREATE_NO_WINDOW on every subprocess ──────────────────────
if sys.platform == "win32":
    import subprocess as _subprocess
    _orig_popen = _subprocess.Popen
    class _Popen(_orig_popen):
        def __init__(self, *args, **kwargs):
            kwargs["creationflags"] = kwargs.get("creationflags", 0) | 0x08000000
            kwargs.pop("startupinfo", None)
            super().__init__(*args, **kwargs)
    _subprocess.Popen = _Popen

if sys.platform == "win32":
    try:
        import ctypes
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
            "com.rafaelildefonso.sirius.headless"
        )
    except Exception:
        pass

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

# ── Ensure project root is on sys.path ──────────────────────────────────────
_this_dir = Path(__file__).resolve().parent
if str(_this_dir) not in sys.path:
    sys.path.insert(0, str(_this_dir))

# ── Data directory init (mirrors sirius_backend_launcher.py) ─────────────────
from core.config_loader import get_all_config
from sirius_backend_launcher import _init_data_dir, _init_database, _sync_json_to_db
from ws_server import WsMessage, WsUI, manager

_init_data_dir()
_init_database()
_sync_json_to_db()

os.environ["SIRIUS_WS_UI"] = "1"

# ── WebSocket server ────────────────────────────────────────────────────────
import ws_server as _ws

_ws.start()

# ── Obsidian (optional, non-blocking) ───────────────────────────────────────
cfg = get_all_config()
vault_path = cfg.get("obsidian_vault_path")
if vault_path:
    _ws.connect_obsidian_with_retry()

# ── Agent executor ──────────────────────────────────────────────────────────
from agent.executor import AgentExecutor

_executor = AgentExecutor()
_executor_lock = threading.Lock()


def _process_text_command(text: str) -> None:
    """Handle a text command from the Pane frontend via WebSocket."""
    print(f"[Headless] Command received: {text[:100]}")
    manager.broadcast_sync(WsMessage("state", {"state": "THINKING"}))

    def _run():
        try:
            with _executor_lock:
                result = _executor.execute(goal=text)
            print(f"[Headless] Result: {result[:200]}")
            manager.broadcast_sync(WsMessage("response", {"text": result}))
        except Exception as e:
            traceback.print_exc()
            error_msg = f"Erro ao processar comando: {e}"
            manager.broadcast_sync(WsMessage("response", {"text": error_msg}))
        finally:
            manager.broadcast_sync(WsMessage("state", {"state": "IDLE"}))

    threading.Thread(target=_run, daemon=True).start()


# ── Wire up WsUI callbacks ──────────────────────────────────────────────────
ui = WsUI()
ui.on_text_command = _process_text_command


# ── Main loop ───────────────────────────────────────────────────────────────
def main():
    print("[Headless] Sirius backend started (Pane sidecar mode)")
    print("[Headless] WebSocket server on ws://127.0.0.1:8765")
    print("[Headless] Waiting for Pane connection...")

    ui.set_state("IDLE")

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\n[Headless] Shutting down...")
        ui.set_state("SHUTDOWN")
        time.sleep(0.5)


if __name__ == "__main__":
    main()
