"""
BackupManager — automatic backup of the database file.
"""

from __future__ import annotations

import logging
import shutil
from datetime import datetime
from pathlib import Path
from typing import Optional

from persistence.database import Database

logger = logging.getLogger("persistence.backup")

_MAX_BACKUPS = 7


class BackupManager:
    """Copies the SQLite DB to timestamped backup files and manages retention."""

    def __init__(
        self,
        db_path: Optional[Path] = None,
        backup_dir: Optional[Path] = None,
        max_backups: int = _MAX_BACKUPS,
    ):
        if db_path is None:
            db = Database.get_instance()
            db_path = db.db_path
        self.db_path = db_path
        self.backup_dir = backup_dir or db_path.parent / "backups"
        self.max_backups = max_backups

    def backup(self) -> Path:
        self.backup_dir.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_path = self.backup_dir / f"sirius_backup_{timestamp}.db"

        if self.db_path.exists():
            shutil.copy2(str(self.db_path), str(backup_path))
            logger.info(f"Backup saved: {backup_path}")

        self._enforce_retention()
        return backup_path

    def _enforce_retention(self) -> None:
        backups = sorted(self.backup_dir.glob("sirius_backup_*.db"))
        while len(backups) > self.max_backups:
            oldest = backups.pop(0)
            try:
                oldest.unlink()
                logger.info(f"Removed old backup: {oldest}")
            except OSError:
                pass

    def list_backups(self) -> list[Path]:
        return sorted(self.backup_dir.glob("sirius_backup_*.db"), reverse=True)

    def restore(self, backup_path: Path) -> bool:
        if not backup_path.exists():
            logger.error(f"Backup not found: {backup_path}")
            return False
        try:
            shutil.copy2(str(backup_path), str(self.db_path))
            logger.info(f"Restored from backup: {backup_path}")
            return True
        except OSError as e:
            logger.error(f"Restore failed: {e}")
            return False
