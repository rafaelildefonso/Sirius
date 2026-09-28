from __future__ import annotations

import re
from pathlib import Path
from typing import Dict, List, Optional

from persistence.repository import Repository

PRIORITY_EMOJIS = ("🔴", "🟠", "🟢")

_TASK_LINE_RE = re.compile(
    r"^\s*-\s*\[ \]\s*(.+?)(?:\s+🛫\s+(\d{4}-\d{2}-\d{2}))?"
    r"(?:\s+([🔴🟠🟢]))?"
    r"(?:\s+✅\s+(\d{4}-\d{2}-\d{2}))?\s*$",
    re.IGNORECASE,
)


def parse_task_line(line: str) -> Optional[Dict[str, Optional[str]]]:
    """Parse a single task line like:
       - [ ] description 🛫 2026-08-16 ⏫ 🔴 ✅ 2026-08-18
    Returns dict with keys: description, start_date, priority_emoji, end_date
    or None if the line does not match.
    """
    m = _TASK_LINE_RE.match(line)
    if not m:
        return None
    description = m.group(1).strip()
    start_date = m.group(2)  # may be None
    priority_emoji = m.group(3)  # may be None
    end_date = m.group(4)  # may be None
    return {
        "description": description,
        "start_date": start_date,
        "priority_emoji": priority_emoji,
        "end_date": end_date,
    }


def extract_tasks_from_file(filepath: Path) -> List[Dict[str, Optional[str]]]:
    """Read a markdown file and return a list of parsed tasks."""
    tasks: List[Dict[str, Optional[str]]] = []
    try:
        text = filepath.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        return tasks
    for line in text.splitlines():
        parsed = parse_task_line(line)
        if parsed:
            tasks.append(parsed)
    return tasks


def load_tasks_from_vault(vault_path: Path, tasks_subpath: str = "Tarefas") -> None:
    """Scan the tasks subfolder inside the vault and store/update tasks in the DB.

    The expected structure: <vault_path>/<tasks_subpath>/*.md
    Each .md file may contain task lines as described in parse_task_line.
    """
    repo = Repository()
    tasks_root = vault_path / tasks_subpath
    if not tasks_root.is_dir():
        print(f"[Obsidian] Tasks folder not found: {tasks_root}")
        return

    md_files = sorted(tasks_root.rglob("*.md"))
    for md in md_files:
        file_path_str = str(md.relative_to(vault_path))  # relative path for reference
        tasks = extract_tasks_from_file(md)
        for task in tasks:
            description = task["description"]
            start_date = task["start_date"]
            priority_emoji = task["priority_emoji"]
            end_date = task["end_date"]
            # Upsert: we use file_path + description as unique key
            existing = repo.db.fetchone(
                "SELECT id FROM obsidian_tasks WHERE file_path = ? AND description = ?",
                (file_path_str, description),
            )
            if existing:
                # Update existing row (keep fields in sync with the vault file)
                completed = bool(end_date)
                repo.update_task(existing["id"], start_date, priority_emoji, end_date, completed)
            else:
                repo.add_task(file_path_str, description, start_date, priority_emoji, end_date)
                print(f"[Obsidian] Added task from {md}: {description}")


def organize_task_in_obsidian(
    title: str,
    due_at: str | None = None,
    notes: str | None = None,
    vault_path: str | None = None,
) -> Path | None:
    """Save a task to the Obsidian vault in Tasks plugin syntax.

    Args:
        title: Task description.
        due_at: ISO datetime string for the due date (optional).
        notes: Additional notes for the task (optional).
        vault_path: Explicit vault path. Falls back to config, then auto-discover.

    Returns:
        Path of the markdown file written, or None on failure.
    """
    try:
        # Determine vault
        if vault_path:
            vault = Path(vault_path)
        else:
            vault = _find_vault()
        if not vault or not vault.exists():
            print("[ObsidianTasks] No vault found")
            return None

        tasks_dir = vault / "Tarefas"
        tasks_dir.mkdir(parents=True, exist_ok=True)

        # Build task line in Tasks plugin syntax
        task_line = f"- [ ] {title}"
        if due_at:
            # Extract date portion (YYYY-MM-DD)
            date_part = due_at[:10] if len(due_at) >= 10 else due_at
            task_line += f" 🛫 {date_part}"
        task_line += "\n"

        # Append to a dated file or general tasks file
        from datetime import datetime
        today = datetime.now().strftime("%Y-%m-%d")
        task_file = tasks_dir / f"{today}.md"

        # Add header if file is new
        if not task_file.exists():
            header = f"# Tarefas — {today}\n\n"
            task_file.write_text(header, encoding="utf-8")

        with open(task_file, "a", encoding="utf-8") as f:
            f.write(task_line)

        # Also add notes as a child block if provided
        if notes:
            note_line = f"  > {notes}\n"
            with open(task_file, "a", encoding="utf-8") as f:
                f.write(note_line)

        print(f"[ObsidianTasks] Task saved: {title} → {task_file}")
        return task_file

    except Exception as e:
        print(f"[ObsidianTasks] Failed to organize task: {e}")
        return None


def _find_vault() -> Path | None:
    """Try common Obsidian vault locations."""
    home = Path.home()
    candidates = [
        home / "Documents" / "Obsidian",
        home / "Obsidian",
        home / "Documents" / "Vault",
        home / "Documents" / "notes",
    ]
    for p in candidates:
        if p.exists() and any(p.glob("*.md")):
            return p
    return None
