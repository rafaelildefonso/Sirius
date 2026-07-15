"""
Repository — high-level CRUD API for all memory entities.
"""

from __future__ import annotations

import json
import time
from datetime import datetime, timedelta
from typing import Any, Optional
from uuid import UUID

from persistence.database import Database
from persistence.models import (
    Conversation,
    Event,
    Fact,
    FileReference,
    MemoryType,
    Message,
    Preference,
    RelevanceMetadata,
    RetrievedMemory,
    SearchResult,
    Tag,
)


class Repository:
    """Unified data access layer. All read/write operations go through here."""

    def __init__(self, db: Optional[Database] = None):
        self.db = db or Database.get_instance()

    # ------------------------------------------------------------------
    # Conversation
    # ------------------------------------------------------------------

    def create_conversation(self, title: Optional[str] = None) -> int:
        now = datetime.now().isoformat()
        cur = self.db.execute(
            "INSERT INTO conversation (title, started_at) VALUES (?, ?)",
            (title, now),
        )
        self.db.commit()
        return cur.lastrowid

    def close_conversation(self, conv_id: int) -> None:
        self.db.execute(
            "UPDATE conversation SET ended_at = ? WHERE id = ?",
            (datetime.now().isoformat(), conv_id),
        )
        self.db.commit()

    def get_conversation(self, conv_id: int) -> Optional[dict]:
        row = self.db.fetchone("SELECT * FROM conversation WHERE id = ?", (conv_id,))
        return dict(row) if row else None

    def list_conversations(self, limit: int = 50, offset: int = 0) -> list[dict]:
        rows = self.db.fetchall(
            "SELECT * FROM conversation ORDER BY started_at DESC LIMIT ? OFFSET ?",
            (limit, offset),
        )
        return [dict(r) for r in rows]

    def delete_conversation(self, conv_id: int) -> None:
        self.db.execute("DELETE FROM conversation WHERE id = ?", (conv_id,))
        self.db.commit()

    # ------------------------------------------------------------------
    # Message
    # ------------------------------------------------------------------

    def add_message(
        self,
        conversation_id: int,
        role: str,
        content: str,
        metadata: Optional[dict] = None,
        importance: float = 0.5,
    ) -> int:
        now = datetime.now().isoformat()
        cur = self.db.execute(
            "INSERT INTO message (conversation_id, role, content, timestamp, metadata, importance) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (conversation_id, role, content, now, json.dumps(metadata or {}), importance),
        )
        self.db.commit()
        rowid = cur.lastrowid
        self.db.execute(
            "INSERT OR REPLACE INTO message_fts (rowid, content) VALUES (?, ?)",
            (rowid, content),
        )
        self.db.commit()
        return rowid

    def get_messages(self, conversation_id: int, limit: int = 200) -> list[dict]:
        rows = self.db.fetchall(
            "SELECT * FROM message WHERE conversation_id = ? ORDER BY timestamp ASC LIMIT ?",
            (conversation_id, limit),
        )
        return [dict(r) for r in rows]

    def search_messages(self, query: str, limit: int = 50) -> list[dict]:
        rows = self.db.fetchall(
            "SELECT m.* FROM message_fts f JOIN message m ON m.id = f.rowid "
            "WHERE message_fts MATCH ? ORDER BY rank LIMIT ?",
            (query, limit),
        )
        return [dict(r) for r in rows]

    def delete_old_messages(self, days: int = 90) -> int:
        cutoff = (datetime.now() - timedelta(days=days)).isoformat()
        cur = self.db.execute("DELETE FROM message WHERE timestamp < ?", (cutoff,))
        self.db.commit()
        return cur.rowcount

    # ------------------------------------------------------------------
    # Event (generic memory entry)
    # ------------------------------------------------------------------

    def save_event(self, event: Event) -> str:
        now = event.timestamp.isoformat() if isinstance(event.timestamp, datetime) else event.timestamp
        valid_until = event.valid_until.isoformat() if isinstance(event.valid_until, datetime) else event.valid_until
        self.db.execute(
            "INSERT OR REPLACE INTO event "
            "(id, type, payload, timestamp, source, importance, confidence, "
            " frequency, last_accessed, ttl, valid_until, metadata) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                event.id,
                event.type.value if isinstance(event.type, MemoryType) else event.type,
                json.dumps(event.payload, ensure_ascii=False),
                now,
                event.source,
                event.importance,
                event.confidence,
                event.frequency,
                event.last_accessed.isoformat() if isinstance(event.last_accessed, datetime) else None,
                event.ttl,
                valid_until,
                json.dumps(event.metadata, ensure_ascii=False),
            ),
        )
        self.db.commit()
        self._update_event_fts(event.id)
        return event.id

    def get_event(self, event_id: str) -> Optional[Event]:
        row = self.db.fetchone("SELECT * FROM event WHERE id = ?", (event_id,))
        if not row:
            return None
        return self._row_to_event(row)

    def search_events(self, query: str, limit: int = 50) -> list[Event]:
        rows = self.db.fetchall(
            "SELECT e.* FROM event_fts f JOIN event e ON e.rowid = f.rowid "
            "WHERE event_fts MATCH ? ORDER BY rank LIMIT ?",
            (query, limit),
        )
        return [self._row_to_event(r) for r in rows]

    def query_events(
        self,
        type_filter: Optional[str] = None,
        min_importance: float = 0.0,
        tags: Optional[list[str]] = None,
        limit: int = 50,
    ) -> list[Event]:
        sql = "SELECT DISTINCT e.* FROM event e"
        params: list[Any] = []
        conditions = []

        if tags:
            placeholders = ",".join("?" for _ in tags)
            sql += " JOIN event_tag et ON et.event_id = e.id JOIN tag t ON t.id = et.tag_id"
            conditions.append(f"t.name IN ({placeholders})")
            params.extend(tags)

        if type_filter:
            conditions.append("e.type = ?")
            params.append(type_filter)

        conditions.append("e.importance >= ?")
        params.append(min_importance)

        if conditions:
            sql += " WHERE " + " AND ".join(conditions)

        sql += " ORDER BY e.importance DESC, e.timestamp DESC LIMIT ?"
        params.append(limit)

        rows = self.db.fetchall(sql, tuple(params))
        return [self._row_to_event(r) for r in rows]

    def update_event_access(self, event_id: str) -> None:
        self.db.execute(
            "UPDATE event SET frequency = frequency + 1, last_accessed = ? WHERE id = ?",
            (datetime.now().isoformat(), event_id),
        )
        self.db.commit()

    def delete_event(self, event_id: str) -> None:
        self.db.execute("DELETE FROM event WHERE id = ?", (event_id,))
        self.db.commit()

    def _update_event_fts(self, event_id: str) -> None:
        row = self.db.fetchone("SELECT payload, rowid FROM event WHERE id = ?", (event_id,))
        if row:
            self.db.execute(
                "INSERT OR REPLACE INTO event_fts (rowid, payload) VALUES (?, ?)",
                (row["rowid"], row["payload"]),
            )
            self.db.commit()

    @staticmethod
    def _row_to_event(row: sqlite3.Row | dict) -> Event:
        if isinstance(row, dict):
            d = row
        else:
            d = dict(row)
        return Event(
            id=d["id"],
            type=MemoryType(d["type"]) if d.get("type") else MemoryType.CASUAL,
            payload=json.loads(d["payload"]) if isinstance(d.get("payload"), str) else d.get("payload") or {},
            timestamp=d["timestamp"] if isinstance(d.get("timestamp"), datetime) else (datetime.fromisoformat(d["timestamp"]) if d.get("timestamp") else datetime.now()),
            source=d.get("source", "user"),
            importance=d.get("importance", 0.5),
            confidence=d.get("confidence", 1.0),
            frequency=d.get("frequency", 0),
            last_accessed=d.get("last_accessed") if isinstance(d.get("last_accessed"), datetime) else (datetime.fromisoformat(d["last_accessed"]) if d.get("last_accessed") else None),
            ttl=d.get("ttl"),
            valid_until=d.get("valid_until") if isinstance(d.get("valid_until"), datetime) else (datetime.fromisoformat(d["valid_until"]) if d.get("valid_until") else None),
            metadata=json.loads(d["metadata"]) if isinstance(d.get("metadata"), str) else d.get("metadata") or {},
        )

    # ------------------------------------------------------------------
    # Fact (semantic memory)
    # ------------------------------------------------------------------

    def save_fact(self, fact: Fact) -> str:
        now = datetime.now().isoformat()
        self.db.execute(
            "INSERT OR REPLACE INTO fact (id, subject, predicate, object, confidence, source, created_at, updated_at, importance) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (fact.id, fact.subject, fact.predicate, fact.object, fact.confidence, fact.source,
             fact.created_at.isoformat() if isinstance(fact.created_at, datetime) else now,
             now, fact.importance),
        )
        self.db.commit()
        row = self.db.fetchone("SELECT rowid FROM fact WHERE id = ?", (fact.id,))
        if row:
            self.db.execute(
                "INSERT OR REPLACE INTO fact_fts (rowid, subject, predicate, object) VALUES (?, ?, ?, ?)",
                (row["rowid"], fact.subject, fact.predicate, fact.object),
            )
            self.db.commit()
        return fact.id

    def search_facts(self, query: str, limit: int = 50) -> list[Fact]:
        rows = self.db.fetchall(
            "SELECT f.* FROM fact_fts ff JOIN fact f ON f.rowid = ff.rowid "
            "WHERE fact_fts MATCH ? ORDER BY rank LIMIT ?",
            (query, limit),
        )
        facts = []
        for r in rows:
            d = dict(r)
            facts.append(Fact(
                id=d["id"],
                subject=d["subject"],
                predicate=d["predicate"],
                object=d["object"],
                confidence=d["confidence"],
                source=d.get("source", ""),
                created_at=d["created_at"] if isinstance(d.get("created_at"), datetime) else datetime.fromisoformat(d["created_at"]),
                updated_at=d.get("updated_at") if isinstance(d.get("updated_at"), datetime) else (datetime.fromisoformat(d["updated_at"]) if d.get("updated_at") else None),
                importance=d["importance"],
            ))
        return facts

    def delete_old_facts(self, days: int = 365) -> int:
        cutoff = (datetime.now() - timedelta(days=days)).isoformat()
        cur = self.db.execute("DELETE FROM fact WHERE updated_at < ?", (cutoff,))
        self.db.commit()
        return cur.rowcount

    # ------------------------------------------------------------------
    # Preference (procedural memory)
    # ------------------------------------------------------------------

    def set_preference(self, key: str, value: str, pref_type: str = "general", importance: float = 0.5, ttl: Optional[int] = None) -> None:
        now = datetime.now().isoformat()
        existing = self.db.fetchone("SELECT usage_count FROM preference WHERE key = ?", (key,))
        usage_count = (existing["usage_count"] if existing else 0) + 1
        self.db.execute(
            "INSERT OR REPLACE INTO preference (key, value, type, importance, last_used, usage_count, ttl, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, COALESCE((SELECT created_at FROM preference WHERE key = ?), ?), ?)",
            (key, value, pref_type, importance, now, usage_count, ttl, key, now, now),
        )
        self.db.commit()

    def get_preference(self, key: str) -> Optional[Preference]:
        row = self.db.fetchone("SELECT * FROM preference WHERE key = ?", (key,))
        if not row:
            return None
        d = dict(row)
        return Preference(
            key=d["key"],
            value=d["value"],
            type=d["type"],
            importance=d["importance"],
            last_used=d.get("last_used"),
            usage_count=d["usage_count"],
            ttl=d["ttl"],
            created_at=d["created_at"],
            updated_at=d["updated_at"],
        )

    def get_all_preferences(self) -> dict[str, str]:
        rows = self.db.fetchall("SELECT key, value FROM preference ORDER BY importance DESC, last_used DESC")
        return {r["key"]: r["value"] for r in rows}

    def delete_preference(self, key: str) -> None:
        self.db.execute("DELETE FROM preference WHERE key = ?", (key,))
        self.db.commit()

    # ------------------------------------------------------------------
    # File reference
    # ------------------------------------------------------------------

    def save_file_reference(self, ref: FileReference) -> int:
        created = ref.created_at.isoformat() if isinstance(ref.created_at, datetime) else ref.created_at
        modified = ref.modified_at.isoformat() if isinstance(ref.modified_at, datetime) else ref.modified_at
        cur = self.db.execute(
            "INSERT OR REPLACE INTO file_reference (path, type, size, created_at, modified_at, hash, importance, metadata) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (ref.path, ref.type, ref.size, created, modified, ref.hash, ref.importance,
             json.dumps(ref.metadata, ensure_ascii=False)),
        )
        self.db.commit()
        return cur.lastrowid

    def search_files(self, query: str, limit: int = 50) -> list[dict]:
        rows = self.db.fetchall(
            "SELECT * FROM file_reference WHERE path LIKE ? OR (metadata IS NOT NULL AND json_extract(metadata, '$.description') LIKE ?) "
            "ORDER BY importance DESC LIMIT ?",
            (f"%{query}%", f"%{query}%", limit),
        )
        return [dict(r) for r in rows]

    def get_file_by_path(self, path: str) -> Optional[dict]:
        row = self.db.fetchone("SELECT * FROM file_reference WHERE path = ?", (path,))
        return dict(row) if row else None

    # ------------------------------------------------------------------
    # Tags
    # ------------------------------------------------------------------

    def ensure_tag(self, name: str) -> int:
        existing = self.db.fetchone("SELECT id FROM tag WHERE name = ?", (name,))
        if existing:
            return existing["id"]
        self.db.execute("INSERT INTO tag (name) VALUES (?)", (name,))
        self.db.commit()
        return self.db.execute("SELECT last_insert_rowid()").fetchone()[0]

    def add_event_tags(self, event_id: str, tags: list[str]) -> None:
        for tag_name in tags:
            tag_id = self.ensure_tag(tag_name)
            self.db.execute(
                "INSERT OR IGNORE INTO event_tag (event_id, tag_id) VALUES (?, ?)",
                (event_id, tag_id),
            )
        self.db.commit()

    def add_file_tags(self, file_id: int, tags: list[str]) -> None:
        for tag_name in tags:
            tag_id = self.ensure_tag(tag_name)
            self.db.execute(
                "INSERT OR IGNORE INTO file_tag (file_id, tag_id) VALUES (?, ?)",
                (file_id, tag_id),
            )
        self.db.commit()

    # ------------------------------------------------------------------
    # Credentials (encrypted)
    # ------------------------------------------------------------------

    def store_credential(self, service: str, data: dict, expires_at: Optional[datetime] = None) -> None:
        encrypted = self.db.encrypt(json.dumps(data, ensure_ascii=False))
        expires = expires_at.isoformat() if isinstance(expires_at, datetime) else expires_at
        self.db.execute(
            "INSERT OR REPLACE INTO credential (service, data, expires_at) VALUES (?, ?, ?)",
            (service, encrypted, expires),
        )
        self.db.commit()

    def load_credential(self, service: str) -> Optional[dict]:
        row = self.db.fetchone("SELECT data, expires_at FROM credential WHERE service = ?", (service,))
        if not row:
            return None
        if row["expires_at"]:
            expires = datetime.fromisoformat(row["expires_at"])
            if expires < datetime.now():
                self.db.execute("DELETE FROM credential WHERE service = ?", (service,))
                self.db.commit()
                return None
        try:
            return json.loads(self.db.decrypt(row["data"]))
        except Exception:
            return None

    def delete_credential(self, service: str) -> None:
        self.db.execute("DELETE FROM credential WHERE service = ?", (service,))
        self.db.commit()

    # ------------------------------------------------------------------
    # Embeddings
    # ------------------------------------------------------------------

    def save_embedding(self, source_id: str, source_type: str, vector: bytes, model: str = "all-MiniLM-L6-v2") -> None:
        self.db.execute(
            "INSERT OR REPLACE INTO embedding (source_id, source_type, vector, model) VALUES (?, ?, ?, ?)",
            (source_id, source_type, vector, model),
        )
        self.db.commit()

    def get_embedding(self, source_id: str) -> Optional[bytes]:
        row = self.db.fetchone("SELECT vector FROM embedding WHERE source_id = ?", (source_id,))
        return row["vector"] if row else None

    def delete_embedding(self, source_id: str) -> None:
        self.db.execute("DELETE FROM embedding WHERE source_id = ?", (source_id,))
        self.db.commit()

    # ------------------------------------------------------------------
    # Utility / Maintenance
    # ------------------------------------------------------------------

    def get_stats(self) -> dict:
        tables = ["event", "fact", "preference", "file_reference", "message", "conversation", "credential", "tag"]
        stats = {}
        for t in tables:
            row = self.db.fetchone(f"SELECT COUNT(*) as cnt FROM {t}")
            stats[t] = row["cnt"] if row else 0
        return stats

    def purge_expired(self) -> int:
        total = 0
        now = datetime.now().isoformat()
        cur = self.db.execute("DELETE FROM event WHERE valid_until IS NOT NULL AND valid_until < ?", (now,))
        total += cur.rowcount
        cur = self.db.execute("DELETE FROM preference WHERE ttl IS NOT NULL AND last_used IS NOT NULL AND "
                              "datetime(last_used, '+' || ttl || ' seconds') < ?", (now,))
        total += cur.rowcount
        self.db.commit()
        return total

    def run_maintenance(self) -> dict:
        result = {}
        result["purged_expired"] = self.purge_expired()
        result["purged_messages"] = self.delete_old_messages(days=90)
        result["purged_facts"] = self.delete_old_facts(days=365)
        self.db.vacuum()
        result["stats"] = self.get_stats()
        return result
