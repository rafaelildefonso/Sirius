"""
agents.py — AI agent orchestration with real PTY terminals.

Manages multiple AI agent sessions (Claude, Codex, Cursor, OpenCode, Sirius)
using interactive pseudo-terminals (ConPTY on Windows via pywinpty).
Output is streamed in real-time via WebSocket to xterm.js in the frontend.
"""

from __future__ import annotations

import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable

from core.config_loader import get_base_dir

BASE_DIR = get_base_dir()

# ── Agent definitions ────────────────────────────────────────────────────────

AGENT_COMMANDS: dict[str, list[str] | None] = {
    "claude": ["claude"],          # interactive TUI mode
    "codex": ["codex"],            # interactive TUI mode
    "cursor": ["cursor", "ask"],   # interactive mode
    "opencode": ["opencode"],      # interactive TUI mode
    "sirius": None,                # uses LLM fallback (no CLI)
}

AGENT_LABELS: dict[str, str] = {
    "claude": "Claude",
    "codex": "Codex",
    "cursor": "Cursor",
    "opencode": "OpenCode",
    "sirius": "Sirius",
}

AGENT_COLORS: dict[str, str] = {
    "claude": "#d97706",
    "codex": "#10b981",
    "cursor": "#6366f1",
    "opencode": "#ec4899",
    "sirius": "#8b5cf6",
}

READ_CHUNK_SIZE = 4096
READ_INTERVAL = 0.03  # 30ms between reads


# ── PTY Session model ────────────────────────────────────────────────────────

@dataclass
class PtySession:
    id: str
    agent: str
    status: str = "starting"  # starting | running | closed | error
    created_at: float = field(default_factory=time.time)
    _pty: Any = None
    _process: Any = None
    _read_thread: threading.Thread | None = None
    _lock: threading.Lock = field(default_factory=threading.Lock)


# ── Global session manager ───────────────────────────────────────────────────

class AgentManager:
    """Manages AI agent PTY sessions and streams output via WebSocket."""

    def __init__(self) -> None:
        self._sessions: dict[str, PtySession] = {}
        self._broadcast_fn: Callable | None = None

    def set_broadcast(self, broadcast_fn: Callable) -> None:
        self._broadcast_fn = broadcast_fn

    def _emit(self, msg_type: str, data: dict[str, Any]) -> None:
        if self._broadcast_fn:
            self._broadcast_fn(msg_type, data)

    # ── PTY session management ───────────────────────────────────────────

    def create_session(self, agent: str = "claude", cwd: str | None = None) -> str:
        """Create a new interactive PTY session for the given agent."""
        session_id = str(uuid.uuid4())[:8]
        session = PtySession(id=session_id, agent=agent)
        self._sessions[session_id] = session

        # Emit creation event immediately
        self._emit("agent_pty_created", {
            "session_id": session_id,
            "agent": agent,
        })

        # Start PTY in background thread
        cmd = AGENT_COMMANDS.get(agent)
        if cmd is None:
            # Sirius uses LLM fallback — no CLI process
            session.status = "running"
            self._emit("agent_pty_output", {
                "session_id": session_id,
                "data": "\x1b[38;5;141m[Sirius] Modo LLM — digite seu prompt abaixo.\x1b[0m\r\n> ",
            })
            return session_id

        def _start_pty() -> None:
            try:
                import winpty  # pywinpty

                pty = winpty.PTY(120, 40)

                with session._lock:
                    session._pty = pty

                # Spawn the agent command
                appname = cmd[0]
                cmdline = " ".join(cmd) if len(cmd) > 1 else None
                work_dir = cwd or str(BASE_DIR)
                pty.spawn(
                    appname,
                    cmdline=cmdline,
                    cwd=work_dir,
                )
                session.status = "running"

                self._emit("agent_pty_output", {
                    "session_id": session_id,
                    "data": f"\x1b[38;5;244m[{AGENT_LABELS.get(agent, agent)}] Terminal iniciado.\x1b[0m\r\n",
                })

                # Read loop — streams output to frontend
                while session.status == "running":
                    try:
                        raw = pty.read(READ_CHUNK_SIZE)
                        if raw:
                            text = raw.decode("utf-8", errors="replace")
                            self._emit("agent_pty_output", {
                                "session_id": session_id,
                                "data": text,
                            })
                        else:
                            time.sleep(READ_INTERVAL)
                    except Exception:
                        break

                session.status = "closed"
                self._emit("agent_pty_closed", {
                    "session_id": session_id,
                    "agent": agent,
                })

            except ImportError:
                session.status = "error"
                self._emit("agent_pty_output", {
                    "session_id": session_id,
                    "data": "\x1b[31m[Erro] pywinpty não instalado. Execute: pip install pywinpty\x1b[0m\r\n",
                })
            except FileNotFoundError:
                session.status = "error"
                self._emit("agent_pty_output", {
                    "session_id": session_id,
                    "data": f"\x1b[31m[Erro] CLI '{agent}' não encontrado. Verifique se está instalado.\x1b[0m\r\n",
                })
            except Exception as e:
                session.status = "error"
                self._emit("agent_pty_output", {
                    "session_id": session_id,
                    "data": f"\x1b[31m[Erro] {e}\x1b[0m\r\n",
                })

        t = threading.Thread(target=_start_pty, daemon=True, name=f"pty-{agent}-{session_id}")
        session._read_thread = t
        t.start()

        return session_id

    def write_input(self, session_id: str, data: str) -> bool:
        """Send user input to a PTY session. Returns True if sent."""
        session = self._sessions.get(session_id)
        if not session or not session._pty or session.status != "running":
            return False

        # Handle special: Sirius LLM mode (no real PTY)
        if session.agent == "sirius":
            return self._handle_sirius_input(session_id, session, data)

        try:
            with session._lock:
                if session._pty and session.status == "running":
                    session._pty.write(data)
                    return True
        except Exception:
            pass
        return False

    def resize(self, session_id: str, cols: int, rows: int) -> bool:
        """Resize the PTY terminal."""
        session = self._sessions.get(session_id)
        if not session or not session._pty:
            return False
        try:
            with session._lock:
                if session._pty:
                    session._pty.set_size(cols, rows)
                    return True
        except Exception:
            pass
        return False

    def close_session(self, session_id: str) -> bool:
        """Close a PTY session and kill the process."""
        session = self._sessions.get(session_id)
        if not session:
            return False

        session.status = "closed"
        try:
            with session._lock:
                if session._pty:
                    # winpty PTY has no close() — kill child process via pid
                    import os
                    try:
                        os.kill(session._pty.pid, 1)  # SIGTERM on Windows
                    except (OSError, ProcessLookupError):
                        pass
                    del session._pty
                    session._pty = None
        except Exception:
            pass

        self._emit("agent_pty_closed", {
            "session_id": session_id,
            "agent": session.agent,
        })

        del self._sessions[session_id]
        return True

    def get_sessions(self) -> list[dict[str, str]]:
        """Return info about all active sessions."""
        return [
            {
                "id": s.id,
                "agent": s.agent,
                "status": s.status,
                "label": AGENT_LABELS.get(s.agent, s.agent),
                "color": AGENT_COLORS.get(s.agent, "#888888"),
            }
            for s in self._sessions.values()
            if s.status in ("starting", "running")
        ]

    # ── Sirius LLM fallback ──────────────────────────────────────────────

    def _handle_sirius_input(self, session_id: str, session: PtySession, data: str) -> bool:
        """Handle input in Sirius LLM mode (no PTY, uses LLM)."""
        # Strip ANSI/terminal control sequences
        clean = data.strip("\r\n\x00\x01\x03")
        if not clean:
            return True

        # Echo the input
        self._emit("agent_pty_output", {
            "session_id": session_id,
            "data": "\r\n",
        })

        # Call LLM in a thread to not block
        def _call() -> None:
            try:
                from core.llm_client import call_llm

                self._emit("agent_pty_output", {
                    "session_id": session_id,
                    "data": "\x1b[38;5;244m思考ando...\x1b[0m",
                })

                result = call_llm(
                    messages=[{"role": "user", "content": clean}],
                    system="You are Sirius, an AI assistant. Answer concisely. Respond in Portuguese if the user writes in Portuguese."
                )
                content = result.get("content", "") or "[Sem resposta]"

                self._emit("agent_pty_output", {
                    "session_id": session_id,
                    "data": f"\r\x1b[2K\x1b[38;5;141m{content}\x1b[0m\r\n> ",
                })
            except Exception as e:
                self._emit("agent_pty_output", {
                    "session_id": session_id,
                    "data": f"\r\x1b[2K\x1b[31m[Erro LLM] {e}\x1b[0m\r\n> ",
                })

        threading.Thread(target=_call, daemon=True).start()
        return True

    # ── Voice control (LLM tool-use) ─────────────────────────────────────

    def voice_control(self, action: str, agent: str = "claude",
                      prompt: str = "", command: str = "",
                      session_id: str = "") -> str:
        """Control agents via voice commands (called by LLM tool-use)."""
        if action == "create":
            sid = self.create_session(agent)
            return f"Terminal {AGENT_LABELS.get(agent, agent)} criado (ID: {sid})."

        elif action == "close":
            if session_id:
                self.close_session(session_id)
                return f"Sessão {session_id} fechada."
            return "ID da sessão necessário."

        elif action == "list":
            sessions = self.get_sessions()
            if not sessions:
                return "Nenhum terminal ativo."
            lines = [f"{s['label']} ({s['id']}) - {s['status']}" for s in sessions]
            return "Terminais: " + ", ".join(lines)

        elif action == "send_prompt":
            if prompt:
                # Create session if needed, then send
                sessions = self.get_sessions()
                target = None
                for s in sessions:
                    if s["agent"] == agent:
                        target = s
                        break
                if not target:
                    sid = self.create_session(agent)
                    time.sleep(0.5)
                    self.write_input(sid, prompt)
                    return f"Prompt enviado para {AGENT_LABELS.get(agent, agent)}."
                else:
                    self.write_input(target["id"], prompt)
                    return f"Prompt enviado para {target['label']} (ID: {target['id']})."
            return "Nenhum prompt fornecido."

        return f"Ação '{action}' desconhecida."


# ── Global instance ──────────────────────────────────────────────────────────

agent_manager = AgentManager()


# ── WS message handler ──────────────────────────────────────────────────────

async def handle_agent_message(data: dict, ws_send: Callable) -> bool:
    """Handle agent PTY WebSocket messages. Returns True if handled."""
    msg_type = data.get("type", "")

    if msg_type == "agent_create_pty":
        agent = data.get("agent", "claude")
        session_id = agent_manager.create_session(agent)
        # Response is already emitted inside create_session
        return True

    elif msg_type == "agent_pty_input":
        session_id = data.get("session_id", "")
        input_data = data.get("data", "")
        agent_manager.write_input(session_id, input_data)
        return True

    elif msg_type == "agent_pty_resize":
        session_id = data.get("session_id", "")
        cols = data.get("cols", 120)
        rows = data.get("rows", 40)
        agent_manager.resize(session_id, cols, rows)
        return True

    elif msg_type == "agent_close_pty":
        session_id = data.get("session_id", "")
        agent_manager.close_session(session_id)
        return True

    return False


# ── Voice control function (for LLM tool-use) ───────────────────────────────

def agents_control(parameters: dict, player: Any = None, speak: Any = None) -> str:
    """Control AI agents: create terminals, send prompts, run commands.

    Parameters:
        action: "create" | "send_prompt" | "close" | "list"
        agent: "claude" | "codex" | "cursor" | "opencode" | "sirius"
        prompt: Text to send (for send_prompt)
        session_id: Session ID (for close)
    """
    action = parameters.get("action", "list")
    agent = parameters.get("agent", "claude")
    prompt = parameters.get("prompt", "")
    command = parameters.get("command", "")
    session_id = parameters.get("session_id", "")

    result = agent_manager.voice_control(
        action=action,
        agent=agent,
        prompt=prompt or command,
        session_id=session_id,
    )

    if speak and result:
        speak(result)

    return result
