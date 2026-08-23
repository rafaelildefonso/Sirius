"""
task_alarm.py — Background scheduler that fires due scheduled tasks.

Checks the `scheduled_tasks` table every few seconds and triggers a
notification pipeline (persistent Windows toast + WebSocket broadcast to
the React UI) for each task whose due time has arrived. Tasks that came
due while SIRIUS was offline fire on the first tick after startup.

Status flow: pending -> notified -> done/dismissed (snooze returns to pending).
"""

from __future__ import annotations

import logging
import threading
from datetime import datetime
from typing import Callable, Optional

logger = logging.getLogger("core.task_alarm")

CHECK_INTERVAL_SECS = 10


def _default_on_fire(task: dict) -> None:
    """Default notification pipeline — routes through ws_server helpers."""
    try:
        import ws_server

        ws_server.notify_task_alarm(task)
    except Exception as e:
        logger.error("Failed to notify task %s: %s", task.get("id"), e)


class TaskAlarmScheduler:
    """Daemon thread that polls for due scheduled tasks and fires them."""

    def __init__(
        self,
        repo=None,
        on_fire: Optional[Callable[[dict], None]] = None,
        check_interval: int = CHECK_INTERVAL_SECS,
    ):
        self._repo = repo
        self._on_fire = on_fire or _default_on_fire
        self._interval = check_interval
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None

    @property
    def repo(self):
        if self._repo is None:
            from persistence.repository import Repository

            self._repo = Repository()
        return self._repo

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._run_loop, daemon=True, name="task-alarm"
        )
        self._thread.start()
        logger.info("TaskAlarmScheduler started (every %ss)", self._interval)

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=5)

    def fire_now(self, task_id: str) -> bool:
        """Fire a specific task immediately if it is already due."""
        task = self.repo.get_scheduled_task(task_id)
        if not task or task["status"] != "pending":
            return False
        try:
            if datetime.fromisoformat(str(task["due_at"])) > datetime.now():
                return False  # not due yet — the polling loop will handle it
        except ValueError:
            return False
        self._dispatch(task)
        return True

    def _run_loop(self) -> None:
        # First tick doubles as catch-up for tasks missed while offline.
        while not self._stop_event.is_set():
            try:
                self._tick()
            except Exception as e:
                logger.error("Task alarm tick failed: %s", e)
            self._stop_event.wait(self._interval)

    def _tick(self) -> None:
        now_iso = datetime.now().isoformat()
        try:
            due = self.repo.get_due_scheduled_tasks(now_iso)
        except Exception as e:
            logger.error("Could not query due tasks: %s", e)
            return

        for task in due:
            self._dispatch(task)

    def _dispatch(self, task: dict) -> None:
        task_id = task.get("id", "?")
        try:
            self._on_fire(task)
        except Exception as e:
            logger.error("on_fire failed for task %s: %s", task_id, e)
        try:
            self.repo.mark_scheduled_task_notified(task_id)
        except Exception as e:
            logger.error("Could not mark task %s notified: %s", task_id, e)


# Module-level singleton so dashboard endpoints can trigger immediate fires.
_scheduler: Optional[TaskAlarmScheduler] = None
_singleton_lock = threading.Lock()


def get_scheduler() -> TaskAlarmScheduler:
    global _scheduler
    if _scheduler is None:
        with _singleton_lock:
            if _scheduler is None:
                _scheduler = TaskAlarmScheduler()
    return _scheduler


def start_scheduler() -> TaskAlarmScheduler:
    sched = get_scheduler()
    sched.start()
    return sched
