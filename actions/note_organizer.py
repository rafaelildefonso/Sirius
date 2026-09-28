"""Append companion notes to existing Obsidian documents without reading them."""
from __future__ import annotations

import asyncio
import hashlib
import inspect
import json
import logging
import re
import time
import unicodedata
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

logger = logging.getLogger("note_organizer")
DEFAULT_NOTES_SUBPATH = "Anotações"
INBOX_FILENAME = "Caixa de entrada.md"
IMAGES_FILENAME = "Imagens.md"
_AI_CALL_TIMEOUT = 15
_AI_COOLDOWN_UNTIL = 0.0
_AI_FAILURE_COOLDOWN = 300.0
_AI_SYSTEM = "Você é o organizador de notas do SIRIUS. Responda somente JSON válido."
_STOPWORDS = {"de", "do", "da", "dos", "das", "no", "na", "nos", "nas", "um", "uma", "e", "ou", "que", "com", "sem", "por", "para", "pra", "sobre", "the", "and", "for", "with"}


@dataclass(frozen=True)
class NoteOrganizationResult:
    target: Path
    summary: str | None = None
    tags: list[str] | None = None
    duplicate: bool = False


def _get_config(key: str, default: str = "") -> str:
    try:
        from core.config_loader import get_config
        return get_config(key, default) or default
    except Exception:
        return default


def _resolve_vault(vault_path: str | None = None) -> Path | None:
    if vault_path:
        path = Path(vault_path)
        return path if path.exists() else None
    configured = _get_config("obsidian_vault_path")
    if configured and Path(configured).exists():
        return Path(configured)
    for path in (Path.home() / "Documents" / "Obsidian", Path.home() / "Obsidian", Path.home() / "Documents" / "Vault"):
        if path.exists():
            return path
    return None


def _notes_dir(vault: Path) -> Path:
    subpath = _get_config("obsidian_notes_subpath", DEFAULT_NOTES_SUBPATH).strip() or DEFAULT_NOTES_SUBPATH
    return vault / subpath


def _list_note_files(notes_dir: Path) -> list[Path]:
    """List paths only; target file contents are never opened."""
    try:
        ignored = {INBOX_FILENAME.lower(), IMAGES_FILENAME.lower()}
        files = [path for path in notes_dir.rglob("*.md") if path.is_file()
                 and "_attachments" not in path.relative_to(notes_dir).parts
                 and not any(part.startswith(".") for part in path.relative_to(notes_dir).parts)
                 and path.name.lower() not in ignored]
        return sorted(files, key=lambda path: (len(path.relative_to(notes_dir).parts), str(path).lower()))
    except Exception as exc:
        logger.warning("Could not list notes folder %s: %s", notes_dir, exc)
        return []


def _routing_prompt(candidates: list[Path], notes_dir: Path, title: str, content: str, category: str) -> str:
    names = "\n".join(f"- {path.relative_to(notes_dir)}" for path in candidates) or "(nenhum)"
    return ("Escolha o documento existente mais adequado. Você só conhece nomes e não pode ler conteúdo.\n\n"
            f"Documentos:\n{names}\n\nCategoria: {category or 'geral'}\nTítulo: {title or '(sem título)'}\n"
            f"Anotação:\n{content[:800]}\n\n"
            'Retorne somente JSON: {"file":"nome-exato.md ou vazio", "summary":"resumo", "tags":["tag"]}. '
            "Use file vazio quando nenhum servir.")


def _parse_json(raw: str) -> dict | None:
    try:
        return json.loads(raw)
    except (TypeError, json.JSONDecodeError):
        match = re.search(r"\{.*\}", raw or "", re.DOTALL)
        try:
            return json.loads(match.group()) if match else None
        except json.JSONDecodeError:
            return None


async def _ask_ai(candidates: list[Path], notes_dir: Path, title: str, content: str, category: str, llm_client=None) -> dict | None:
    global _AI_COOLDOWN_UNTIL
    if time.monotonic() < _AI_COOLDOWN_UNTIL:
        return None
    try:
        prompt = _routing_prompt(candidates, notes_dir, title, content, category)
        if llm_client is not None and hasattr(llm_client, "generate"):
            response = llm_client.generate(prompt)
            raw = await response if inspect.isawaitable(response) else response
        else:
            from core.llm_utils import call_llm_for_action
            raw = await asyncio.wait_for(asyncio.to_thread(call_llm_for_action, prompt, _AI_SYSTEM), timeout=_AI_CALL_TIMEOUT)
        return _parse_json((raw or "").strip())
    except Exception as exc:
        _AI_COOLDOWN_UNTIL = time.monotonic() + _AI_FAILURE_COOLDOWN
        logger.warning("AI note routing unavailable: %s", exc)
        return None


def _match_choice(choice: object, candidates: list[Path], notes_dir: Path) -> Path | None:
    if not isinstance(choice, str) or not choice.strip():
        return None
    clean = choice.strip().splitlines()[0].strip("`'\" ").replace("\\", "/")
    by_relative = {str(path.relative_to(notes_dir)).replace("\\", "/").lower(): path for path in candidates}
    if clean.lower() in by_relative:
        return by_relative[clean.lower()]
    filename = Path(clean).name
    if not filename.lower().endswith(".md"):
        filename += ".md"
    matches = [path for path in candidates if path.name.lower() == filename.lower()]
    return matches[0] if len(matches) == 1 else None


def _tokens(value: str) -> set[str]:
    words = set()
    for raw in re.findall(r"[A-Za-zÀ-ÿ0-9]{3,}", value or ""):
        word = "".join(char for char in unicodedata.normalize("NFKD", raw.lower()) if not unicodedata.combining(char))
        if word not in _STOPWORDS:
            words.add(word[:-1] if word.endswith("s") and len(word) > 4 else word)
    return words


def _keyword_match(candidates: list[Path], title: str, content: str) -> Path | None:
    note_words = _tokens(f"{title} {content}")
    scores = [(sum(len(word) for word in note_words & _tokens(path.stem)), path) for path in candidates]
    scores = [(score, path) for score, path in scores if score >= 5]
    if not scores:
        return None
    scores.sort(key=lambda item: item[0], reverse=True)
    return scores[0][1] if len(scores) == 1 or scores[0][0] > scores[1][0] else None


def _normalize_tags(value: object) -> list[str] | None:
    if not isinstance(value, list):
        return None
    tags = [str(item).strip() for item in value if str(item).strip()]
    return tags or None


def _fingerprint(title: str, content: str, category: str) -> str:
    return hashlib.sha256(f"{title}\0{content}\0{category}".encode("utf-8")).hexdigest()


def _existing_delivery(source_uuid: str, fingerprint: str) -> NoteOrganizationResult | None:
    if not source_uuid:
        return None
    try:
        from persistence.database import Database
        row = Database.get_instance().fetchone("SELECT target_path, summary, tags_json FROM companion_note_deliveries WHERE source_uuid = ? AND fingerprint = ?", (source_uuid, fingerprint))
        if row:
            return NoteOrganizationResult(Path(row["target_path"]), row["summary"], _normalize_tags(json.loads(row["tags_json"] or "[]")), True)
    except Exception as exc:
        logger.warning("Could not read note delivery ledger: %s", exc)
    return None


def _record_delivery(source_uuid: str, fingerprint: str, result: NoteOrganizationResult) -> None:
    if not source_uuid:
        return
    try:
        from persistence.database import Database
        db = Database.get_instance()
        db.execute("""INSERT INTO companion_note_deliveries (source_uuid, fingerprint, target_path, summary, tags_json, delivered_at)
                      VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                      ON CONFLICT(source_uuid) DO UPDATE SET fingerprint=excluded.fingerprint, target_path=excluded.target_path,
                      summary=excluded.summary, tags_json=excluded.tags_json, delivered_at=CURRENT_TIMESTAMP""",
                   (source_uuid, fingerprint, str(result.target), result.summary, json.dumps(result.tags or [], ensure_ascii=False)))
        db.commit()
    except Exception as exc:
        logger.error("Could not write note delivery ledger: %s", exc)


def _append_note(target: Path, title: str, content: str) -> None:
    entry = f"## {title.strip()}\n\n{content.strip()}" if title.strip() else content.strip()
    with target.open("a", encoding="utf-8") as handle:
        handle.write(f"\n\n---\n\n{entry}\n")


async def organize_note(title: str, content: str, category: str, ai_summary: str | None = None,
                        ai_tags: list[str] | None = None, vault_path: str | None = None,
                        llm_client=None, source_uuid: str = "") -> NoteOrganizationResult | None:
    """Append to a matching document or a single inbox; never create title files."""
    vault = _resolve_vault(vault_path)
    if not vault:
        logger.error("No Obsidian vault found")
        return None
    notes_dir = _notes_dir(vault)
    notes_dir.mkdir(parents=True, exist_ok=True)
    fingerprint = _fingerprint(title, content, category)
    existing = _existing_delivery(source_uuid, fingerprint)
    if existing:
        return existing
    candidates = _list_note_files(notes_dir)
    ai = await _ask_ai(candidates, notes_dir, title, content, category, llm_client) if candidates or not ai_summary else None
    summary = ai_summary or (ai.get("summary").strip() if isinstance(ai, dict) and isinstance(ai.get("summary"), str) and ai.get("summary").strip() else None)
    tags = _normalize_tags(ai_tags) or (_normalize_tags(ai.get("tags")) if isinstance(ai, dict) else None)
    target = _match_choice(ai.get("file"), candidates, notes_dir) if isinstance(ai, dict) else None
    if target is None and ai is None:
        target = _keyword_match(candidates, title, content)
    target = target or (notes_dir / INBOX_FILENAME)
    if not target.exists():
        target.touch()
    await asyncio.to_thread(_append_note, target, title, content)
    result = NoteOrganizationResult(target, summary, tags)
    _record_delivery(source_uuid, fingerprint, result)
    logger.info("Companion note appended: %s", target)
    return result


def save_images(vault_path: str | None, attachments: list[tuple[str, bytes]]) -> list[Path]:
    """Save images and add dated links only to Imagens.md."""
    if not attachments:
        return []
    vault = _resolve_vault(vault_path)
    if not vault:
        raise RuntimeError("No Obsidian vault found")
    notes_dir = _notes_dir(vault)
    attachment_dir = notes_dir / "_attachments"
    attachment_dir.mkdir(parents=True, exist_ok=True)
    saved: list[Path] = []
    for original_name, data in attachments:
        safe = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", Path(original_name).name).strip(". ") or "image"
        target = attachment_dir / safe
        counter = 1
        while target.exists():
            target = attachment_dir / f"{Path(safe).stem}_{counter}{Path(safe).suffix}"
            counter += 1
        target.write_bytes(data)
        saved.append(target)
    images = notes_dir / IMAGES_FILENAME
    if not images.exists():
        images.touch()
    stamp = datetime.now().strftime("%Y-%m-%d %H:%M")
    with images.open("a", encoding="utf-8") as handle:
        for image in saved:
            handle.write(f"\n\n---\n\n{stamp}\n\n![](_attachments/{image.name})\n")
    return saved
