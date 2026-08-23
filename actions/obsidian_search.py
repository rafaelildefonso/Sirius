from __future__ import annotations

import numpy as np

from persistence.embedding import EmbeddingProvider
from persistence.repository import Repository


def _get_embedding_provider() -> EmbeddingProvider:
    return EmbeddingProvider.get_instance()


def search_notes(query: str, limit: int = 5) -> str:
    """Search Obsidian notes by semantic similarity (with keyword fallback).

    Returns a human-readable summary for the assistant to speak/print.
    """
    repo = Repository()
    query = (query or "").strip()

    rows = repo.db.fetchall(
        "SELECT id, file_path, content, embedding FROM obsidian_notes ORDER BY updated_at DESC LIMIT 500"
    )
    if not rows:
        return "Não há notas do Obsidian indexadas. Configure o caminho do vault nas integrações e aguarde o carregamento."

    try:
        limit = max(1, min(int(limit), 20))
    except (TypeError, ValueError):
        limit = 5

    results: list[tuple[str, str, float]] = []

    if query:
        try:
            query_vec = _get_embedding_provider().encode(query).astype(np.float32)
            norm = np.linalg.norm(query_vec)
            if norm > 0:
                query_vec = query_vec / norm
            for r in rows:
                blob = r["embedding"]
                if blob is None:
                    continue
                vec = np.frombuffer(blob, dtype=np.float32)
                if len(vec) == 0:
                    continue
                n = np.linalg.norm(vec)
                if n > 0:
                    vec = vec / n
                sim = float(np.dot(query_vec, vec))
                if sim > 0.25:
                    results.append((r["file_path"], r["content"] or "", sim))
            results.sort(key=lambda x: x[2], reverse=True)
        except Exception as e:
            print(f"[Obsidian] Semantic search failed ({e}); falling back to keyword search.")
            results = []

        if not results:
            # Keyword fallback: simple substring match
            q_lower = query.lower()
            for r in rows:
                content = (r["content"] or "").lower()
                if q_lower in content or q_lower in (r["file_path"] or "").lower():
                    results.append((r["file_path"], r["content"] or "", 0.0))
            results.sort(key=lambda x: x[2], reverse=True)

        top = results[:limit]
        if not top:
            return f"Não encontrei notas do Obsidian relacionadas a '{query}'."
        lines = [f"Notas do Obsidian relacionadas a '{query}':"]
        for path, content, _sim in top:
            snippet = _make_snippet(content, query, 180)
            lines.append(f"• {path}: {snippet}")
        return "\n".join(lines)

    # No query: return most recently updated notes
    lines = ["Notas mais recentes do Obsidian:"]
    for r in rows[:limit]:
        content = r["content"] or ""
        snippet = _make_snippet(content, "", 180)
        lines.append(f"• {r['file_path']}: {snippet}")
    return "\n".join(lines)


def _make_snippet(content: str, query: str, max_len: int = 180) -> str:
    """Return a snippet of content, centered on the query match if present."""
    if not content:
        return "(vazio)"
    content = content.replace("\r", "").replace("\n", " ").strip()
    idx = content.lower().find(query.lower()) if query else -1
    if idx > max_len // 2:
        start = idx - max_len // 4
        content = "…" + content[start:].strip()
    if len(content) > max_len:
        content = content[:max_len].rstrip() + "…"
    return content


def list_tasks() -> str:
    """List pending Obsidian tasks from the database."""
    repo = Repository()
    tasks = repo.get_pending_tasks()
    if not tasks:
        return "Não há tarefas pendentes no seu Obsidian."
    lines = [f"Você tem {len(tasks)} tarefa(s) pendente(s):"]
    for i, t in enumerate(tasks[:25], 1):
        desc = t.get("description", "").strip()
        prio = t.get("priority_emoji") or ""
        start = t.get("start_date") or ""
        when = f" (início: {start})" if start else ""
        file_path = t.get("file_path") or ""
        lines.append(f"{i}. {prio} {desc}{when} — {file_path}")
    return "\n".join(lines)
