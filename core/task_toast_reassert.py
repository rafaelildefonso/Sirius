"""
task_toast_reassert.py — keeps today's sticky task toasts in Action Center.

Windows Action Center keeps only a bounded number of toasts and drops them on
reboot or when the user hits "limpar notificações". A reminder toast that
disappears would never come back, so this daemon checks every 15 minutes
(plus once right after startup) and re-posts the ones that are gone.

Restoring is safe: toasts are posted with a deterministic tag+group, so
Windows replaces anything that is still listed instead of stacking a duplicate.
"""

from __future__ import annotations

import logging
import threading
from typing import Callable, Optional

logger = logging.getLogger("core.task_toast_reassert")

DEFAULT_INTERVAL_SECONDS = 15 * 60


def _default_reassert() -> None:
    """Default pipeline — routes through ws_server helpers."""
    try:
        import ws_server

        ws_server.reassert_today_task_toasts()
    except Exception as e:
        logger.error("Toast re-assert failed: %s", e)


class TaskToastReassert:
    """Daemon thread that re-posts dropped date-range task toasts."""

    def __init__(
        self,
        interval_seconds: int = DEFAULT_INTERVAL_SECONDS,
        on_reassert: Optional[Callable[[], None]] = None,
    ):
        self._interval = max(60, int(interval_seconds))
        self._on_reassert = on_reassert or _default_reassert
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None

    @property
    def interval(self) -> int:
        return self._interval

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._run_loop, daemon=True, name="task-toast-reassert"
        )
        self._thread.start()
        logger.info("TaskToastReassert started (every %ss)", self._interval)

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=5)

    def run_once(self) -> None:
        try:
            self._on_reassert()
        except Exception as e:
            logger.error("Toast re-assert pass failed: %s", e)

    def _run_loop(self) -> None:
        # First pass immediately: the machine may have rebooted (or the user
        # cleared notifications) since the toast was originally posted.
        self.run_once()
        while not self._stop_event.wait(self._interval):
            self.run_once()


# Module-level singleton
_reassert: Optional[TaskToastReassert] = None
_singleton_lock = threading.Lock()


def get_reassert(interval_seconds: int = DEFAULT_INTERVAL_SECONDS) -> TaskToastReassert:
    global _reassert
    if _reassert is None:
        with _singleton_lock:
            if _reassert is None:
                _reassert = TaskToastReassert(interval_seconds=interval_seconds)
    return _reassert


def start_reassert(interval_seconds: int = DEFAULT_INTERVAL_SECONDS) -> TaskToastReassert:
    reassert = get_reassert(interval_seconds)
    reassert.start()
    return reassert
