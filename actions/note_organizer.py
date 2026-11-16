"""Append companion notes to existing Obsidian documents without reading them."""
from __future__ import annotations

import asyncio
import hashlib
import inspect
import json
import logging
import re
import threading
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
_DELIVERY_LOCKS: dict[str, threading.Lock] = {}
_DELIVERY_LOCKS_GUARD = threading.Lock()


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


def _routing_prompt(candidates: list[Path], notes_dir: Path, title: str, content: str, category: str,
                   tags: list[str] | None = None, suggested_folder: str | None = None) -> str:
    names = "\n".join(f"- {path.relative_to(notes_dir)}" for path in candidates) or "(nenhum)"
    return ("Escolha o documento existente mais adequado. Você só conhece nomes e não pode ler conteúdo.\n\n"
            f"Documentos:\n{names}\n\nCategoria: {category or 'geral'}\nTítulo: {title or '(sem título)'}\n"
            f"Pasta sugerida pela classificação local: {suggested_folder or '(nenhuma)'}\n"
            f"Palavras-chave: {', '.join(tags or []) or '(nenhuma)'}\n"
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


async def _ask_ai(candidates: list[Path], notes_dir: Path, title: str, content: str, category: str,
                  tags: list[str] | None = None, suggested_folder: str | None = None,
                  llm_client=None) -> dict | None:
    global _AI_COOLDOWN_UNTIL
    if time.monotonic() < _AI_COOLDOWN_UNTIL:
        return None
    try:
        prompt = _routing_prompt(candidates, notes_dir, title, content, category, tags, suggested_folder)
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


def _keyword_match(candidates: list[Path], title: str, content: str, category: str = "",
                   tags: list[str] | None = None, suggested_folder: str | None = None) -> Path | None:
    note_words = _tokens(f"{title} {content} {category} {' '.join(tags or [])} {suggested_folder or ''}")
    scores = [(sum(len(word) for word in note_words & _tokens(path.stem)), path) for path in candidates]
    scores = [(score, path) for score, path in scores if score >= 5]
    if not scores:
        return None
    scores.sort(key=lambda item: item[0], reverse=True)
    return scores[0][1] if len(scores) == 1 or scores[0][0] > scores[1][0] else None


def _normalize_tags(value: object) -> list[str] | None:
    if not isinstance(value, list):
        return None
    tags: list[str] = []
    seen: set[str] = set()
    for item in value:
        if not isinstance(item, str):
            continue
        clean = _hashtag(item).removeprefix("#")
        key = unicodedata.normalize("NFKC", clean).casefold()
        if clean and key not in seen:
            seen.add(key)
            tags.append(clean)
    return tags or None


def _fingerprint(title: str, content: str, category: str) -> str:
    return hashlib.sha256(f"{title}\0{content}\0{category}".encode("utf-8")).hexdigest()


def _delivery_for_uuid(source_uuid: str) -> tuple[str, NoteOrganizationResult] | None:
    if not source_uuid:
        return None
    try:
        from persistence.database import Database
        row = Database.get_instance().fetchone(
            "SELECT fingerprint, target_path, summary, tags_json FROM companion_note_deliveries WHERE source_uuid = ?",
            (source_uuid,),
        )
        if row:
            return row["fingerprint"], NoteOrganizationResult(
                Path(row["target_path"]), row["summary"],
                _normalize_tags(json.loads(row["tags_json"] or "[]")), True,
            )
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


def _hashtag(tag: str) -> str:
    """Convert a raw Gemma tag into a valid Obsidian inline hashtag."""
    tag = unicodedata.normalize("NFKC", str(tag)).strip().lstrip("#").lower()
    tag = re.sub(r"[^\w/_-]+", "-", tag, flags=re.UNICODE)
    tag = re.sub(r"-{2,}", "-", tag)
    tag = re.sub(r"/{2,}", "/", tag).strip("/.-_")
    return f"#{tag}" if tag else ""


def _hashtag_line(tags: list[str] | None) -> str:
    """Join tags into one ' #tag1 #tag2' line, deduplicated and hidden-safe."""
    if not tags:
        return ""
    seen: set[str] = set()
    parts: list[str] = []
    for tag in tags:
        clean = _hashtag(tag)
        if clean and clean.lower() not in seen:
            seen.add(clean.lower())
            parts.append(clean)
    return "".join(f" {part}" for part in parts)


def _analysis_line(summary: str | None) -> str:
    """Format the Gemma analysis as a single-line blockquote above the hashtags."""
    if not summary:
        return ""
    text = " ".join(str(summary).split())
    return f"> 💡 {text}" if text else ""


def _append_note(target: Path, title: str, content: str, summary: str | None = None,
                 tags: list[str] | None = None, source_uuid: str = "") -> None:
    """Append the note with the AI analysis above a trailing #hashtag line."""
    header = f"## {title.strip()}\n\n" if title.strip() else ""
    analysis = _analysis_line(summary)
    hashtags = _hashtag_line(tags)
    marker = f"<!-- sirius-note:{source_uuid} -->\n" if source_uuid else ""
    entry = marker + header + content.strip()
    if analysis:
        entry += f"\n\n{analysis}"
    if hashtags:
        entry += f"\n\n{hashtags.strip()}"
    entry = entry.rstrip() + "\n"
    with target.open("a", encoding="utf-8") as handle:
        handle.write(f"\n\n---\n\n{entry}")


def _append_classification_update(target: Path, source_uuid: str, summary: str | None,
                                  tags: list[str] | None) -> None:
    """Append only classification metadata; never repeat the note body."""
    marker = f"<!-- sirius-classification:{source_uuid} -->"
    lines = [marker]
    analysis = _analysis_line(summary)
    if analysis:
        lines.append(analysis)
    hashtag_line = _hashtag_line(tags).strip()
    if hashtag_line:
        lines.append(hashtag_line)
    if len(lines) == 1:
        return
    with target.open("a", encoding="utf-8") as handle:
        handle.write("\n\n---\n\n" + "\n\n".join(lines) + "\n")


async def organize_note(title: str, content: str, category: str, ai_summary: str | None = None,
                        ai_tags: list[str] | None = None, vault_path: str | None = None,
                        llm_client=None, source_uuid: str = "",
                        ai_suggested_folder: str | None = None) -> NoteOrganizationResult | None:
    """Append to a matching document or a single inbox; never create title files."""
    if not source_uuid:
        return await _organize_note(title, content, category, ai_summary, ai_tags, vault_path,
                                    llm_client, source_uuid, ai_suggested_folder)
    with _DELIVERY_LOCKS_GUARD:
        lock = _DELIVERY_LOCKS.setdefault(source_uuid, threading.Lock())
    await asyncio.to_thread(lock.acquire)
    try:
        return await _organize_note(title, content, category, ai_summary, ai_tags, vault_path,
                                    llm_client, source_uuid, ai_suggested_folder)
    finally:
        lock.release()


async def _organize_note(title: str, content: str, category: str, ai_summary: str | None,
                         ai_tags: list[str] | None, vault_path: str | None, llm_client,
                         source_uuid: str, ai_suggested_folder: str | None) -> NoteOrganizationResult | None:
    vault = _resolve_vault(vault_path)
    if not vault:
        logger.error("No Obsidian vault found")
        return None
    notes_dir = _notes_dir(vault)
    notes_dir.mkdir(parents=True, exist_ok=True)
    fingerprint = _fingerprint(title, content, category)
    delivery = _delivery_for_uuid(source_uuid)
    if delivery:
        old_fingerprint, existing = delivery
        if old_fingerprint == fingerprint:
            # A note may have arrived before on-device Gemma finished. Add only
            # the classification metadata to the original destination.
            summary = ai_summary or existing.summary
            incoming_tags = _normalize_tags(ai_tags) or []
            old_tags = existing.tags or []
            old_tag_keys = {tag.casefold() for tag in old_tags}
            new_tags = [tag for tag in incoming_tags if tag.casefold() not in old_tag_keys]
            tags = old_tags + new_tags
            summary_changed = summary != existing.summary
            if (summary_changed or new_tags) and existing.target.exists():
                await asyncio.to_thread(
                    _append_classification_update,
                    existing.target,
                    source_uuid,
                    summary if summary_changed else None,
                    new_tags,
                )
                result = NoteOrganizationResult(existing.target, summary, tags, True)
                _record_delivery(source_uuid, fingerprint, result)
                logger.info("Companion note classification updated at %s (late metadata)", existing.target)
                return result
            return existing
        logger.info("Companion note content changed for existing source %s; saving a new revision", source_uuid)
    candidates = _list_note_files(notes_dir)
    mobile_tags = _normalize_tags(ai_tags)
    ai = await _ask_ai(candidates, notes_dir, title, content, category, mobile_tags,
                       ai_suggested_folder, llm_client) if candidates else None
    summary = ai_summary or (ai.get("summary").strip() if isinstance(ai, dict) and isinstance(ai.get("summary"), str) and ai.get("summary").strip() else None)
    tags = _normalize_tags(ai_tags) or (_normalize_tags(ai.get("tags")) if isinstance(ai, dict) else None)
    target = _match_choice(ai.get("file"), candidates, notes_dir) if isinstance(ai, dict) else None
    reason = "ai"
    if target is None:
        target = _keyword_match(candidates, title, content, category, tags, ai_suggested_folder)
        reason = "keyword" if target else ("no_candidates" if not candidates else "no_confident_match")
    target = target or (notes_dir / INBOX_FILENAME)
    if not target.exists():
        target.touch()
    await asyncio.to_thread(_append_note, target, title, content, summary, tags, source_uuid)
    result = NoteOrganizationResult(target, summary, tags)
    _record_delivery(source_uuid, fingerprint, result)
    logger.info("Companion note appended to %s (routing=%s, candidates=%d)", target, reason, len(candidates))
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
