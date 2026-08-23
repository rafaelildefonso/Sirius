from __future__ import annotations

from pathlib import Path
from typing import Callable, Optional

import watchdog.events
import watchdog.observers


class ObsidianEventHandler(watchdog.events.FileSystemEventHandler):
    """Handler that fires callbacks when markdown files change inside the Obsidian vault."""

    def __init__(self, vault_path: Path, on_change: Callable[[Path], None]):
        super().__init__()
        self.vault_path = vault_path.resolve()
        self.on_change = on_change

    def _should_process(self, src_path: Path) -> bool:
        try:
            rel = src_path.resolve().relative_to(self.vault_path)
        except ValueError:
            return False
        # Only process markdown files
        return str(rel).endswith(".md") and not any(
            part.startswith(".") for part in rel.parts
        )

    def on_created(self, event: watchdog.events.FileCreatedEvent) -> None:
        if self._should_process(Path(event.src_path)):
            self.on_change(Path(event.src_path))

    def on_modified(self, event: watchdog.events.FileModifiedEvent) -> None:
        if self._should_process(Path(event.src_path)):
            self.on_change(Path(event.src_path))

    def on_deleted(self, event: watchdog.events.FileDeletedEvent) -> None:
        # Optionally clean DB entries for deleted files
        pass


class ObsidianWatcher:
    """Runs a watchdog observer in a background thread monitoring the Obsidian vault."""

    def __init__(self, vault_path: Path, tasks_subpath: str = "Tarefas", notes_subpath: str = "Anotações"):
        self.vault_path = vault_path.resolve()
        self.tasks_subpath = tasks_subpath
        self.notes_subpath = notes_subpath
        self._observer: Optional[watchdog.observers.Observer] = None
        self._handler: Optional[ObsidianEventHandler] = None

    def start(self, on_task_change: Callable[[Path], None] | None = None,
              on_note_change: Callable[[Path], None] | None = None) -> None:
        """Start watching the vault root. on_task_change and on_note_change receive the file path."""
        self._observer = watchdog.observers.Observer()
        self._handler = ObsidianEventHandler(self.vault_path, self._on_file_change)
        self._on_task_change = on_task_change
        self._on_note_change = on_note_change
        self._observer.schedule(self._handler, str(self.vault_path), recursive=True)
        self._observer.start()
        print(f"[Obsidian] Watcher started on {self.vault_path}")

    def stop(self) -> None:
        if self._observer:
            self._observer.stop()
            self._observer.join()
            self._observer = None
            self._handler = None
        print("[Obsidian] Watcher stopped")

    def _on_file_change(self, file_path: Path) -> None:
        # Dispatch based on subpath
        rel = file_path.relative_to(self.vault_path)
        parts = rel.parts
        if len(parts) >= 1 and parts[0].lower() == self.tasks_subpath.lower():
            if self._on_task_change:
                try:
                    self._on_task_change(file_path)
                except Exception as e:
                    print(f"[Obsidian] Error in task change callback: {e}")
        elif len(parts) >= 1 and parts[0].lower() == self.notes_subpath.lower():
            if self._on_note_change:
                try:
                    self._on_note_change(file_path)
                except Exception as e:
                    print(f"[Obsidian] Error in note change callback: {e}")

    def restart_tasks_load(self) -> None:
        """Trigger a full reload of tasks from the vault (e.g., after a config change)."""
        from actions.obsidian_tasks import load_tasks_from_vault
        from core.config_loader import get_config
        cfg = get_config()
        vault = cfg.get("obsidian_vault_path")
        if not vault:
            print("[Obsidian] No vault path configured; skipping task reload.")
            return
        vault_path = Path(vault)
        if vault_path.is_dir():
            load_tasks_from_vault(vault_path, tasks_subpath=cfg.get("obsidian_tasks_subpath", "Tarefas"))
            print("[Obsidian] Tasks re‑loaded from vault.")
