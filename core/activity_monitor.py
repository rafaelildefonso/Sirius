from __future__ import annotations

import fnmatch
import threading
from datetime import datetime
from typing import Dict, Optional, Tuple

import psutil
import win32gui
import win32process

from core.config_loader import get_all_config
from persistence.repository import Repository


class ActivityMonitor:
    """Daemon that watches active apps and PC uptime, persisting events to SQLite."""

    def __init__(self) -> None:
        self._repo = Repository()
        self._enabled: bool = False
        self._stop_event = threading.Event()
        # pid -> (app_name, window_title, start_ts_ms)
        self._active: Dict[int, Tuple[str, str, float]] = {}
        self._last_boot: Optional[float] = None

    # ------------------------------------------------------------------
    # Configuration
    # ------------------------------------------------------------------
    def enable(self) -> None:
        self._enabled = True
        self._stop_event.clear()
        # initialise boot time
        self._last_boot = psutil.boot_time() * 1000  # ms since epoch
        self._repo.add_activity("boot", timestamp=self._last_boot / 1000)

    def disable(self) -> None:
        self._enabled = False
        self._stop_event.set()
        # persist usage of apps still open so no time is lost on shutdown/toggle-off
        self._flush_active()
        # optionally record shutdown event
        try:
            boot = psutil.boot_time() * 1000
            self._repo.add_activity("shutdown", timestamp=boot / 1000)
        except Exception:
            pass

    def _flush_active(self) -> None:
        now = datetime.now().timestamp() * 1000  # ms
        for pid, (app_name, title, start_ts) in list(self._active.items()):
            try:
                duration = max(0, now - start_ts)
                self._repo.add_activity("app_end", app_name, title, now, duration)
            except Exception:
                pass
        self._active.clear()

    # ------------------------------------------------------------------
    # Main loop
    # ------------------------------------------------------------------
    def _get_blocked_processes(self) -> list[str]:
        # activity_monitor pode ser dict legado {"enabled":..., "blocked_processes":[...]}
        # ou a string "true"/"false" escrita pelo ws_server — nunca quebrar a thread aqui.
        cfg = get_all_config().get("activity_monitor")
        if isinstance(cfg, dict):
            blocked = cfg.get("blocked_processes", [])
            return blocked if isinstance(blocked, list) else []
        return []

    def _is_blocked(self, name: str) -> bool:
        for pattern in self._get_blocked_processes():
            if fnmatch.fnmatch(name.lower(), pattern.lower()):
                return True
        return False

    def _collect_windows_titles(self) -> Dict[int, str]:
        """Map PID -> window title for all top-level windows."""
        pid_to_title: Dict[int, str] = {}
        def enum_handler(hwnd, ctx):
            if not win32gui.IsWindowVisible(hwnd):
                return
            pid = win32process.GetWindowThreadProcessId(hwnd)[1]
            title = win32gui.GetWindowText(hwnd).strip()
            if pid and title:
                pid_to_title[pid] = title
        win32gui.EnumWindows(enum_handler, None)
        return pid_to_title

    def _loop(self) -> None:
        while not self._stop_event.is_set():
            self._stop_event.wait(60)  # 1 minute interval
            if not self._enabled:
                continue

            now = datetime.now().timestamp() * 1000  # ms

            # --- boot / uptime ---
            # We already recorded boot on enable; just ensure consistency.
            # Uptime can be derived if needed.

            # --- collect current processes ---
            try:
                pid_titles = self._collect_windows_titles()
            except Exception:
                pid_titles = {}

            # --- detect starts / ends ---
            current_pids = set(pid_titles.keys()) | set(self._active.keys())

            for pid in list(current_pids):
                try:
                    title = pid_titles.get(pid, "").strip()
                    # psutil.Process pode levantar NoSuchProcess para pid já morto
                    app_name = psutil.Process(pid).name() if pid else "unknown"

                    # skip blocked processes
                    if self._is_blocked(app_name):
                        self._active.pop(pid, None)
                        continue

                    if pid not in self._active:
                        # new process start
                        self._active[pid] = (app_name, title, now)
                        self._repo.add_activity(
                            "app_start",
                            app_name,
                            title,
                            now,
                        )
                    else:
                        # update window title if changed
                        old_name, old_title, start_ts = self._active[pid]
                        if title != old_title:
                            self._active[pid] = (app_name, title, start_ts)
                except Exception:
                    continue

            # --- processes that disappeared ---
            vanished = set(self._active.keys()) - set(pid_titles.keys())
            for pid in list(vanished):
                try:
                    app_name, title, start_ts = self._active.pop(pid)
                    duration = max(0, now - start_ts)
                    self._repo.add_activity(
                        "app_end",
                        app_name,
                        title,
                        now,
                        duration,
                    )
                except Exception:
                    self._active.pop(pid, None)
                    continue

    def start(self) -> threading.Thread:
        """Start the monitoring thread. Returns the thread object."""
        t = threading.Thread(target=self._loop, daemon=True)
        t.start()
        return t

    def stop(self) -> None:
        self._stop_event.set()


# ----------------------------------------------------------------------
# Module-level helpers called from WS server / main
# ----------------------------------------------------------------------
_monitor: Optional[ActivityMonitor] = None


def is_enabled_in_config() -> bool:
    """Return whether the user enabled activity monitoring in configs.json.

    Accepts the string "true"/"false" (UI convention) and the legacy dict
    shape {"enabled": bool, ...}.
    """
    cfg = get_all_config().get("activity_monitor")
    if isinstance(cfg, str):
        return cfg.strip().lower() == "true"
    if isinstance(cfg, dict):
        return bool(cfg.get("enabled", False))
    return False


def start_monitor() -> Optional[ActivityMonitor]:
    """Initialise and start the global monitor. Should be called once at app launch.

    Idempotent: returns the running monitor if already active.
    """
    global _monitor
    if _monitor is not None and is_monitor_enabled():
        return _monitor
    if not is_enabled_in_config():
        # monitor disabled by user
        return None
    _monitor = ActivityMonitor()
    _monitor.enable()
    _monitor.start()
    return _monitor


def stop_monitor() -> None:
    global _monitor
    if _monitor:
        _monitor.disable()
        _monitor = None


def is_monitor_enabled() -> bool:
    return _monitor is not None and _monitor._enabled
