from __future__ import annotations

import datetime
from pathlib import Path

import numpy as np

from persistence.embedding import EmbeddingProvider
from persistence.repository import Repository


def _get_embedding_provider() -> EmbeddingProvider:
    """Singleton provider; loaded once per process."""
    return EmbeddingProvider.get_instance()


def _text_to_embedding_bytes(text: str) -> bytes:
    """Convert text to a 384‑dim float32 vector and return as bytes (BLOB)."""
    provider = _get_embedding_provider()
    vec: np.ndarray = provider.encode(text)
    # Ensure float32 and convert to bytes
    vec = vec.astype(np.float32)
    return vec.tobytes()


def load_notes_from_vault(vault_path: Path, notes_subpath: str = "Anotações") -> None:
    """Scan the notes subfolder inside the vault and store note metadata + embedding in DB."""
    repo = Repository()
    notes_root = vault_path / notes_subpath
    if not notes_root.is_dir():
        print(f"[Obsidian] Notes folder not found: {notes_root}")
        return

    md_files = sorted(notes_root.rglob("*.md"))
    for md in md_files:
        file_path_str = str(md.relative_to(vault_path))
        try:
            content = md.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            continue
        if not content.strip():
            # Store a dummy embedding so the row exists but has no meaningful vector
            embedding_blob = b"\x00" * 384 * 4  # 384 floats * 4 bytes
        else:
            embedding_blob = _text_to_embedding_bytes(content)
        existing = repo.db.fetchone(
            "SELECT id FROM obsidian_notes WHERE file_path = ?", (file_path_str,)
        )
        if existing:
            # Update content and embedding
            now = datetime.datetime.now().isoformat()
            repo.db.execute(
                """UPDATE obsidian_notes SET content = ?, embedding = ?, updated_at = ? WHERE id = ?""",
                (content, embedding_blob, now, existing["id"]),
            )
            repo.db.commit()
            print(f"[Obsidian] Updated note: {md.name}")
        else:
            now = datetime.datetime.now().isoformat()
            repo.db.execute(
                """INSERT INTO obsidian_notes (file_path, content, embedding, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?)""",
                (file_path_str, content, embedding_blob, now, now),
            )
            repo.db.commit()
            print(f"[Obsidian] Added note: {md.name}")
