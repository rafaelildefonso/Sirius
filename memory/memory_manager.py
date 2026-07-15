from __future__ import annotations

import json
import os
import re
import sys
import threading
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from core.cache import memory_cache

# ---------------------------------------------------------------------------
# New persistence layer integration
# ---------------------------------------------------------------------------
_DB_INITIALIZED = False
_DB_LOCK = threading.Lock()


def _init_db():
    global _DB_INITIALIZED
    if _DB_INITIALIZED:
        return
    with _DB_LOCK:
        if _DB_INITIALIZED:
            return
        try:
            from persistence.database import Database
            from persistence.repository import Repository

            Database.get_instance()
            _globals()["_repo"] = Repository()
        except Exception as e:
            print(f"[Memory] DB init (core) failed: {e}")
            return

        # Scheduler e Backup são opcionais — se falharem, DB ainda funciona
        try:
            from persistence.scheduler import Scheduler
            from persistence.backup import BackupManager
            schedule = Scheduler()
            schedule.start()
            _globals()["_scheduler"] = schedule
        except Exception as e:
            print(f"[Memory] Scheduler init deferred: {e}")

        _DB_INITIALIZED = True


def _globals() -> dict:
    import __main__
    mod = sys.modules[__name__]
    return vars(mod)


def get_repo():
    _init_db()
    return _globals().get("_repo")


# ---------------------------------------------------------------------------
# Legacy JSON-based memory (backward compatible)
# ---------------------------------------------------------------------------

from core.config_loader import get_base_dir

BASE_DIR         = get_base_dir()
MEMORY_PATH      = BASE_DIR / "memory" / "long_term.json"
_lock            = threading.Lock()
MAX_VALUE_LENGTH = 380
MEMORY_MAX_CHARS = 100000


def _empty_memory() -> dict:
    return {
        "identity":      {},
        "preferences":   {},
        "projects":      {},
        "relationships": {},
        "wishes":        {},
        "notes":         {},
    }


def load_memory() -> dict:
    cached = memory_cache.get("long_term")
    if cached is not None:
        return cached

    repo = get_repo()
    repo_data = None
    if repo:
        try:
            repo_data = _load_from_repo(repo)
        except Exception:
            pass

    json_data = None
    if MEMORY_PATH.exists():
        with _lock:
            try:
                d = json.loads(MEMORY_PATH.read_text(encoding="utf-8"))
                if isinstance(d, dict):
                    json_data = d
            except Exception as e:
                print(f"[Memory] Load error: {e}")

    if json_data:
        base = _empty_memory()
        for key in base:
            if key in json_data and isinstance(json_data[key], dict) and json_data[key]:
                base[key] = dict(json_data[key])
        if repo_data:
            for key in base:
                if key in repo_data and repo_data[key]:
                    base[key].update(repo_data[key])
        memory_cache.set("long_term", base, ttl=3600)
        return base

    if repo_data is not None:
        memory_cache.set("long_term", repo_data, ttl=3600)
        return repo_data

    return _empty_memory()


def _load_from_repo(repo) -> dict:
    memory = _empty_memory()
    try:
        prefs = repo.get_all_preferences()
        if prefs:
            for k, v in prefs.items():
                memory["preferences"][k] = {"value": v, "updated": datetime.now().strftime("%Y-%m-%d")}
        events = repo.query_events(min_importance=0.5, limit=50)
        for ev in events:
            payload = ev.payload
            if not isinstance(payload, dict):
                continue
            ts = ev.timestamp.strftime("%Y-%m-%d") if hasattr(ev.timestamp, "strftime") else str(ev.timestamp)
            if ev.type.value == "C2":
                ft = payload.get("fact_text", "")
                if isinstance(ft, str) and ft:
                    memory["identity"][ev.id[:16]] = {"value": ft, "updated": ts}
                elif payload.get("key") and payload.get("value"):
                    memory["identity"][payload["key"]] = {"value": payload["value"], "updated": ts}
            elif ev.type.value == "C9":
                if payload.get("key") and payload.get("value"):
                    memory["notes"][payload["key"]] = {"value": payload["value"], "updated": ts}
                else:
                    memory["notes"][ev.id[:16]] = {"value": json.dumps(payload, ensure_ascii=False)[:380], "updated": ts}
    except Exception:
        pass
    memory_cache.set("long_term", memory, ttl=3600)
    return memory


def _all_entries(memory: dict) -> list[tuple]:
    entries = []
    for cat, items in memory.items():
        if not isinstance(items, dict):
            continue
        for key, entry in items.items():
            if isinstance(entry, dict) and "value" in entry:
                entries.append((cat, key, entry))
    return entries


def _trim_to_limit(memory: dict) -> dict:
    if len(json.dumps(memory, ensure_ascii=False)) <= MEMORY_MAX_CHARS:
        return memory
    entries = _all_entries(memory)
    entries.sort(key=lambda t: t[2].get("updated", "0000-00-00"))
    for cat, key, _ in entries:
        if len(json.dumps(memory, ensure_ascii=False)) <= MEMORY_MAX_CHARS:
            break
        del memory[cat][key]
        print(f"[Memory] Trimmed {cat}/{key}")
    return memory


def save_memory(memory: dict, sync_to_repo: bool = True) -> None:
    if not isinstance(memory, dict):
        return
    memory = _trim_to_limit(memory)
    MEMORY_PATH.parent.mkdir(parents=True, exist_ok=True)
    with _lock:
        try:
            MEMORY_PATH.write_text(
                json.dumps(memory, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
        except (OSError, PermissionError) as e:
            print(f"[Memory] Write error (read-only?): {e}")
    memory_cache.set("long_term", memory, ttl=3600)

    if sync_to_repo:
        repo = get_repo()
        if repo:
            try:
                _save_to_repo(repo, memory)
            except Exception:
                pass
    else:
        print("[Memory] JSON synced (DB skipped — already saved by event pipeline)")


def _save_to_repo(repo, memory: dict) -> None:
    from persistence.models import Event, MemoryType
    for cat, items in memory.items():
        if not isinstance(items, dict):
            continue
        for key, entry in items.items():
            value = entry.get("value", "") if isinstance(entry, dict) else entry
            ev = Event(
                type=MemoryType.PREFERENCE if cat == "preferences" else
                     MemoryType.USER_FACT if cat == "identity" else
                     MemoryType.KNOWLEDGE if cat == "notes" else
                     MemoryType.PROJECT if cat == "projects" else
                     MemoryType.CONTACT if cat == "relationships" else
                     MemoryType.TEMPORARY,
                payload={"key": key, "value": value, "category": cat},
                source="memory_manager",
                importance=0.7 if cat in ("identity", "preferences") else 0.5,
            )
            repo.save_event(ev)


def _truncate_value(val: str) -> str:
    if isinstance(val, str) and len(val) > MAX_VALUE_LENGTH:
        return val[:MAX_VALUE_LENGTH].rstrip() + "..."
    return val


def _recursive_update(target: dict, updates: dict) -> bool:
    changed = False
    for key, value in updates.items():
        if value is None:
            continue
        if isinstance(value, str) and not value.strip():
            continue
        if isinstance(value, dict) and "value" not in value:
            if key not in target or not isinstance(target[key], dict):
                target[key] = {}
                changed = True
            if _recursive_update(target[key], value):
                changed = True
        else:
            new_val  = _truncate_value(str(value["value"] if isinstance(value, dict) else value))
            entry    = {"value": new_val, "updated": datetime.now().strftime("%Y-%m-%d")}
            existing = target.get(key, {})
            if not isinstance(existing, dict) or existing.get("value") != new_val:
                target[key] = entry
                changed = True
    return changed


def update_memory(memory_update: dict, sync_to_repo: bool = True) -> dict:
    if not isinstance(memory_update, dict) or not memory_update:
        return load_memory()
    memory = load_memory()
    if _recursive_update(memory, memory_update):
        save_memory(memory, sync_to_repo=sync_to_repo)
        print(f"[Memory] Saved: {list(memory_update.keys())}")
    return memory


def should_extract_memory(user_text: str, sirius_text: str, api_key: str = "") -> bool:
    from core.config_loader import get_secret
    if not get_secret("openrouter_api_key"):
        return False
    try:
        from or_client import client
        combined = f"User: {user_text[:300]}\nSirius: {sirius_text[:1000]}"
        result = client.chat(
            f"Does this conversation contain ANY of the following?\n"
            f"- Personal facts (name, age, city, job, birthday, nationality)\n"
            f"- Preferences or favorites (food, color, music, sport, game, film, book, etc.)\n"
            f"- Active projects or goals the user is working on\n"
            f"- People in the user's life (friends, family, partner, colleagues)\n"
            f"- Things the user wants to do or buy in the future\n"
            f"- Any other fact worth remembering long-term\n\n"
            f"Reply only YES or NO.\n\nConversation:\n{combined}",
            system="You are a memory relevance checker. Reply only YES or NO.",
            max_tokens=5,
            temperature=0.0,
        )
        return "YES" in result.upper()
    except Exception as e:
        print(f"[Memory] Stage1 check failed: {e}")
        return False


def extract_memory(user_text: str, sirius_text: str, api_key: str = "") -> dict:
    from core.config_loader import get_secret
    if not get_secret("openrouter_api_key"):
        return {}
    try:
        from or_client import client
        combined = f"User: {user_text[:600]}\nSirius: {sirius_text[:300]}"
        raw = client.chat(
            f"Extract ALL memorable personal facts from this conversation. Any language.\n"
            f"Return ONLY valid JSON. Use {{}} if truly nothing is worth saving.\n\n"
            f"Category guide:\n"
            f"  identity      -> name, age, birthday, city, country, job, school, nationality, language\n"
            f"  preferences   -> ANY favorite or preferred thing:\n"
            f"                  favorite_food, favorite_color, favorite_music, favorite_film,\n"
            f"                  favorite_game, favorite_sport, favorite_book, favorite_artist,\n"
            f"                  favorite_country, hobbies, interests, dislikes, etc.\n"
            f"  projects      -> projects being built, ongoing work, goals, ideas in progress\n"
            f"                  (e.g. mark_xxv: 'Building a JARVIS-like AI assistant')\n"
            f"  relationships -> people mentioned: friends, family, partner, colleagues\n"
            f"                  (e.g. best_friend_ali: 'Best friend, met in university')\n"
            f"  wishes        -> future plans, things to buy, travel plans, dreams\n"
            f"  notes         -> anything else worth remembering (habits, schedule, etc.)\n\n"
            f"IMPORTANT:\n"
            f"- Be LIBERAL: if something MIGHT be worth remembering, include it.\n"
            f"- Extract from BOTH user and Sirius turns.\n"
            f"- Skip: weather, reminders, search results, one-time commands.\n"
            f"- Use concise English values regardless of conversation language.\n\n"
            f"Format:\n"
            f'{{"identity":{{"name":{{"value":"Ali"}}}},\n'
            f' "preferences":{{"favorite_color":{{"value":"blue"}}}},\n'
            f' "projects":{{"mark_xxv":{{"value":"JARVIS-like AI assistant"}}}},\n'
            f' "relationships":{{"friend_yusuf":{{"value":"close friend"}}}},\n'
            f' "wishes":{{"buy_guitar":{{"value":"wants an acoustic guitar"}}}},\n'
            f' "notes":{{"works_at_night":{{"value":"usually active late at night"}}}}}}\n\n'
            f"Conversation:\n{combined}\n\nJSON:",
            system="Return ONLY valid JSON. No markdown, no explanation, no extra text.",
            max_tokens=1024,
            temperature=0.2,
        )
        clean = raw.strip()
        clean = re.sub(r"```(?:json)?", "", clean).strip().rstrip("`").strip()
        if not clean or clean == "{}":
            return {}
        return json.loads(clean)
    except json.JSONDecodeError:
        return {}
    except Exception as e:
        if "429" not in str(e):
            print(f"[Memory] Extract failed: {e}")
        return {}


def format_memory_for_prompt(memory: dict | None) -> str:
    if not memory:
        return ""

    lines = []

    identity  = memory.get("identity", {})
    id_fields = ["name", "age", "birthday", "city", "job", "language", "school", "nationality"]
    for field in id_fields:
        entry = identity.get(field)
        if entry:
            val = entry.get("value") if isinstance(entry, dict) else entry
            if val:
                lines.append(f"{field.title()}: {val}")
    for key, entry in identity.items():
        if key in id_fields:
            continue
        val = entry.get("value") if isinstance(entry, dict) else entry
        if val:
            lines.append(f"{key.replace('_', ' ').title()}: {val}")

    prefs = memory.get("preferences", {})
    if prefs:
        lines.append("")
        lines.append("Preferences:")
        for key, entry in list(prefs.items())[:15]:
            val = entry.get("value") if isinstance(entry, dict) else entry
            if val:
                lines.append(f"  - {key.replace('_', ' ').title()}: {val}")

    projects = memory.get("projects", {})
    if projects:
        lines.append("")
        lines.append("Active Projects / Goals:")
        for key, entry in list(projects.items())[:8]:
            val = entry.get("value") if isinstance(entry, dict) else entry
            if val:
                lines.append(f"  - {key.replace('_', ' ').title()}: {val}")

    rels = memory.get("relationships", {})
    if rels:
        lines.append("")
        lines.append("People in their life:")
        for key, entry in list(rels.items())[:10]:
            val = entry.get("value") if isinstance(entry, dict) else entry
            if val:
                lines.append(f"  - {key.replace('_', ' ').title()}: {val}")

    wishes = memory.get("wishes", {})
    if wishes:
        lines.append("")
        lines.append("Wishes / Plans / Wants:")
        for key, entry in list(wishes.items())[:8]:
            val = entry.get("value") if isinstance(entry, dict) else entry
            if val:
                lines.append(f"  - {key.replace('_', ' ').title()}: {val}")

    notes = memory.get("notes", {})
    if notes:
        lines.append("")
        lines.append("Other notes:")
        for key, entry in list(notes.items())[:8]:
            val = entry.get("value") if isinstance(entry, dict) else entry
            if val:
                lines.append(f"  - {key}: {val}")

    repo = get_repo()
    if repo:
        try:
            from persistence.context_builder import ContextBuilder
            builder = ContextBuilder()
            extra = builder.build(
                query="",
                recent_messages=None,
                max_tokens=2000,
                include_preferences=False,
            )
            if extra and len(extra) > 30:
                lines.append("")
                lines.append("Recent memories:")
                for line in extra.split("\n")[:20]:
                    if line.strip():
                        lines.append(f"  {line.strip()}")
        except Exception:
            pass

    if not lines:
        return ""

    header = "[WHAT YOU KNOW ABOUT THIS PERSON - use naturally, never recite like a list]\n"
    result = header + "\n".join(lines)
    if len(result) > 10000:
        result = result[:9997] + "..."

    return result + "\n"


def remember(key: str, value: str, category: str = "notes") -> str:
    valid = {"identity", "preferences", "projects", "relationships", "wishes", "notes"}
    if category not in valid:
        category = "notes"
    update_memory({category: {key: {"value": value}}})
    return f"Remembered: {category}/{key} = {value}"


def forget(key: str, category: str = "notes") -> str:
    memory = load_memory()
    cat = memory.get(category, {})
    if key in cat:
        del cat[key]
        memory[category] = cat
        save_memory(memory)
        return f"Forgotten: {category}/{key}"
    return f"Not found: {category}/{key}"


forget_memory = forget


def sync_json_to_db() -> int:
    """Import all JSON memory entries into the DB. Returns count of events created."""
    repo = get_repo()
    if not repo:
        return 0
    try:
        memory = _empty_memory()
        if MEMORY_PATH.exists():
            data = json.loads(MEMORY_PATH.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                for key in memory:
                    if key in data:
                        memory[key] = data[key]
        _save_to_repo(repo, memory)
        count = sum(len(v) for v in memory.values() if isinstance(v, dict))
        print(f"[Memory] Synced {count} entries from JSON to DB")
        return count
    except Exception as e:
        print(f"[Memory] Sync error: {e}")
        return 0

# ---------------------------------------------------------------------------
# New pipeline: classify + extract + persist (for processed messages)
# ---------------------------------------------------------------------------


def _save_event_embedding(event_id: str, text: str, repo) -> None:
    try:
        from persistence.embedding import EmbeddingProvider
        embedder = EmbeddingProvider.get_instance()
        if embedder.available:
            import numpy as np
            vec = embedder.encode(text)
            repo.save_embedding(event_id, "event", vec.astype(np.float32).tobytes())
    except Exception:
        pass


def process_user_input(
    text: str,
    source: str = "user",
    context: Optional[dict] = None,
) -> Optional[str]:
    """Classify, extract, persist a user message. Returns event_id or None."""
    _init_db()
    try:
        from persistence.classifier import Classifier
        from persistence.extractor import Extractor
        from persistence.repository import Repository

        classifier = Classifier()
        extractor = Extractor()
        repo = get_repo()

        mtype = classifier.classify(text)
        if mtype.value == "C0":
            return None

        event = extractor.extract(text, mtype, source=source, context=context)
        event_id = repo.save_event(event)
        if event.tags:
            repo.add_event_tags(event_id, event.tags)
        _save_event_embedding(event_id, text, repo)

        if mtype.value in ("C2", "C9"):
            update_memory({
                "identity" if mtype.value == "C2" else "notes": {
                    event_id[:16]: {"value": text[:MAX_VALUE_LENGTH]}
                }
            }, sync_to_repo=False)

        print(f"[Memory] Processed {mtype.value}: {event_id[:12]}...")
        return event_id
    except Exception as e:
        print(f"[Memory] processUserInput error: {e}")
        return None


# ---------------------------------------------------------------------------
# Init on import (lazy, inside the process)
# ---------------------------------------------------------------------------
try:
    _init_db()
except Exception:
    pass
