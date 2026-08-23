from __future__ import annotations

import fnmatch
import threading
from datetime import datetime
from typing import Dict, Optional, Tuple

import psutil
import win32gui
import win32process

from config.permissions import get_permissions
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
        # optionally record shutdown event
        try:
            boot = psutil.boot_time() * 1000
            self._repo.add_activity("shutdown", timestamp=boot / 1000)
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Main loop
    # ------------------------------------------------------------------
    def _get_blocked_processes(self) -> list[str]:
        cfg = get_all_config()
        return cfg.get("activity_monitor", {}).get("blocked_processes", [])

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
                title = pid_titles.get(pid, "").strip()
                app_name = psutil.Process(pid).name() if pid else "unknown"

                # skip blocked processes
                if self._is_blocked(app_name):
                    # still track but do not record start/end events? We'll just ignore.
                    # Remove from active if it was there to avoid stale entries.
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
                        # record end of old title and start of new? For simplicity just update title.
                        self._active[pid] = (app_name, title, start_ts)

            # --- processes that disappeared ---
            vanished = set(self._active.keys()) - set(pid_titles.keys())
            for pid in vanished:
                app_name, title, start_ts = self._active.pop(pid)
                duration = now - start_ts
                self._repo.add_activity(
                    "app_end",
                    app_name,
                    title,
                    now,
                    duration,
                )

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


def start_monitor() -> ActivityMonitor:
    """Initialise and start the global monitor. Should be called once at app launch."""
    global _monitor
    perms = get_permissions()
    if not perms.get("activity_monitor", False):
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
