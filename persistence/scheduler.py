"""
Scheduler — background tasks for TTL expiry, reminders, cleanup, and periodic maintenance.
"""

from __future__ import annotations

import asyncio
import logging
import threading
import time
from datetime import datetime, timedelta
from typing import Any, Optional

from persistence.repository import Repository
from persistence.backup import BackupManager

logger = logging.getLogger("persistence.scheduler")


class Scheduler:
    """Manages periodic maintenance tasks:
    - Purge expired events / preferences
    - Trim old messages
    - Run VACUUM
    - Trigger backup
    """

    def __init__(
        self,
        repo: Optional[Repository] = None,
        backup_manager: Optional[BackupManager] = None,
        maintenance_interval_hours: int = 6,
        backup_interval_hours: int = 24,
    ):
        self.repo = repo or Repository()
        self.backup_manager = backup_manager or BackupManager()
        self.maintenance_interval = maintenance_interval_hours * 3600
        self.backup_interval = backup_interval_hours * 3600
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run_loop, daemon=True, name="mem-scheduler")
        self._thread.start()
        logger.info("Scheduler started")

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=5)
        logger.info("Scheduler stopped")

    def _run_loop(self) -> None:
        last_maintenance = time.time()
        last_backup = time.time()

        while not self._stop_event.is_set():
            now = time.time()
            try:
                if now - last_maintenance >= self.maintenance_interval:
                    self._run_maintenance()
                    last_maintenance = now

                if now - last_backup >= self.backup_interval:
                    self._run_backup()
                    last_backup = now
            except Exception as e:
                logger.error(f"Scheduler error: {e}")

            self._stop_event.wait(300)

    def _run_maintenance(self) -> None:
        try:
            result = self.repo.run_maintenance()
            logger.info(f"Maintenance done: {result}")
        except Exception as e:
            logger.error(f"Maintenance failed: {e}")

    def _run_backup(self) -> None:
        try:
            path = self.backup_manager.backup()
            logger.info(f"Backup created: {path}")
        except Exception as e:
            logger.error(f"Backup failed: {e}")
