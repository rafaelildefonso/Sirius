"""
date_range_notifier.py — Background scheduler that fires date-range task notifications at 00:00 daily.

Checks the `scheduled_tasks` table at midnight and triggers a notification pipeline
(persistent Windows toast + WebSocket broadcast to the React UI) for each date-range
task that is active on that day (start_date <= today <= end_date).
"""

from __future__ import annotations

import logging
import threading
from datetime import date, datetime, timedelta
from typing import Callable, Optional

logger = logging.getLogger("core.date_range_notifier")


def _default_on_fire(task: dict) -> None:
    """Default notification pipeline — routes through ws_server helpers."""
    try:
        import ws_server

        ws_server.notify_date_range_task_alarm(task)
    except Exception as e:
        logger.error("Failed to notify date-range task %s: %s", task.get("id"), e)


class DateRangeNotifier:
    """Daemon thread that fires notifications for active date-range tasks at 00:00 daily."""

    def __init__(
        self,
        repo=None,
        on_fire: Optional[Callable[[dict], None]] = None,
    ):
        self._repo = repo
        self._on_fire = on_fire or _default_on_fire
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
            target=self._run_loop, daemon=True, name="date-range-notifier"
        )
        self._thread.start()
        logger.info("DateRangeNotifier started")

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=5)

    def _run_loop(self) -> None:
        while not self._stop_event.is_set():
            try:
                self._wait_until_midnight()
                if not self._stop_event.is_set():
                    self._tick()
            except Exception as e:
                logger.error("Date range notifier tick failed: %s", e)

    def _wait_until_midnight(self) -> None:
        """Sleep until the next 00:00 local time."""
        now = datetime.now()
        tomorrow = (now + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
        seconds_until_midnight = (tomorrow - now).total_seconds()

        # Sleep in small chunks to respect stop event
        while seconds_until_midnight > 0 and not self._stop_event.is_set():
            sleep_time = min(seconds_until_midnight, 60)  # Check every minute
            self._stop_event.wait(sleep_time)
            seconds_until_midnight -= sleep_time

    def _tick(self) -> None:
        today_iso = date.today().isoformat()
        try:
            due = self.repo.get_date_range_tasks_for_today(today_iso)
        except Exception as e:
            logger.error("Could not query date-range tasks for %s: %s", today_iso, e)
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


# Module-level singleton
_notifier: Optional[DateRangeNotifier] = None
_singleton_lock = threading.Lock()


def get_notifier() -> DateRangeNotifier:
    global _notifier
    if _notifier is None:
        with _singleton_lock:
            if _notifier is None:
                _notifier = DateRangeNotifier()
    return _notifier


def start_notifier() -> DateRangeNotifier:
    notifier = get_notifier()
    notifier.start()
    return notifier
