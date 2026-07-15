"""
Database engine — SQLite connection, migration management, encryption layer.
Uses standard sqlite3 with FTS5 + cryptography (Fernet) for at-rest field encryption.
"""

from __future__ import annotations

import json
import os
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any, Optional

from cryptography.fernet import Fernet

from core.cache import memory_cache

DEFAULT_DB_FILENAME = "sirius.db"

_SQL_SCHEMA = """\
-- Schema version tracking
CREATE TABLE IF NOT EXISTS schema_version (
    version INTEGER PRIMARY KEY,
    applied_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

-- Conversations
CREATE TABLE IF NOT EXISTS conversation (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    title        TEXT,
    started_at   DATETIME NOT NULL,
    ended_at     DATETIME
);

-- Messages
CREATE TABLE IF NOT EXISTS message (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    conversation_id   INTEGER NOT NULL REFERENCES conversation(id) ON DELETE CASCADE,
    role              TEXT NOT NULL CHECK(role IN ('user','assistant','system','tool')),
    content           TEXT NOT NULL,
    timestamp         DATETIME NOT NULL,
    metadata          TEXT,
    importance        REAL DEFAULT 0.5,
    confidence        REAL DEFAULT 1.0,
    source            TEXT DEFAULT 'user'
);

-- Episodic / Semantic events (generic memory entries)
CREATE TABLE IF NOT EXISTS event (
    id            TEXT PRIMARY KEY,
    type          TEXT NOT NULL,
    payload       TEXT NOT NULL,
    timestamp     DATETIME NOT NULL,
    source        TEXT NOT NULL DEFAULT 'user',
    importance    REAL DEFAULT 0.5,
    confidence    REAL DEFAULT 1.0,
    frequency     INTEGER DEFAULT 0,
    last_accessed DATETIME,
    ttl           INTEGER,
    valid_until   DATETIME,
    metadata      TEXT
);

-- Semantic facts (triples)
CREATE TABLE IF NOT EXISTS fact (
    id          TEXT PRIMARY KEY,
    subject     TEXT NOT NULL,
    predicate   TEXT NOT NULL,
    object      TEXT NOT NULL,
    confidence  REAL DEFAULT 0.5,
    source      TEXT,
    created_at  DATETIME NOT NULL,
    updated_at  DATETIME,
    importance  REAL DEFAULT 0.5
);

-- Procedural preferences
CREATE TABLE IF NOT EXISTS preference (
    key         TEXT PRIMARY KEY,
    value       TEXT NOT NULL,
    type        TEXT DEFAULT 'general',
    importance  REAL DEFAULT 0.5,
    last_used   DATETIME,
    usage_count INTEGER DEFAULT 0,
    ttl         INTEGER,
    created_at  DATETIME NOT NULL,
    updated_at  DATETIME
);

-- File references
CREATE TABLE IF NOT EXISTS file_reference (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    path        TEXT NOT NULL UNIQUE,
    type        TEXT NOT NULL CHECK(type IN ('file','directory','link')),
    size        INTEGER,
    created_at  DATETIME,
    modified_at DATETIME,
    hash        TEXT,
    importance  REAL DEFAULT 0.3,
    metadata    TEXT
);

-- Tags
CREATE TABLE IF NOT EXISTS tag (
    id    INTEGER PRIMARY KEY AUTOINCREMENT,
    name  TEXT NOT NULL UNIQUE,
    color TEXT
);

-- Many-to-many: event <-> tag
CREATE TABLE IF NOT EXISTS event_tag (
    event_id TEXT    NOT NULL REFERENCES event(id) ON DELETE CASCADE,
    tag_id   INTEGER NOT NULL REFERENCES tag(id) ON DELETE CASCADE,
    PRIMARY KEY (event_id, tag_id)
);

-- Many-to-many: fact <-> tag
CREATE TABLE IF NOT EXISTS fact_tag (
    fact_id TEXT    NOT NULL REFERENCES fact(id) ON DELETE CASCADE,
    tag_id  INTEGER NOT NULL REFERENCES tag(id) ON DELETE CASCADE,
    PRIMARY KEY (fact_id, tag_id)
);

-- Many-to-many: file <-> tag
CREATE TABLE IF NOT EXISTS file_tag (
    file_id INTEGER NOT NULL REFERENCES file_reference(id) ON DELETE CASCADE,
    tag_id  INTEGER NOT NULL REFERENCES tag(id) ON DELETE CASCADE,
    PRIMARY KEY (file_id, tag_id)
);

-- Encrypted credentials
CREATE TABLE IF NOT EXISTS credential (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    service    TEXT NOT NULL UNIQUE,
    data       BLOB NOT NULL,
    expires_at DATETIME
);

-- Embeddings (vectors for semantic search)
CREATE TABLE IF NOT EXISTS embedding (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    source_id   TEXT NOT NULL,
    source_type TEXT NOT NULL CHECK(source_type IN ('event','fact','file','message')),
    vector      BLOB NOT NULL,
    model       TEXT NOT NULL,
    created_at  DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- FTS5 virtual tables
CREATE VIRTUAL TABLE IF NOT EXISTS event_fts USING fts5(
    payload,
    content='event',
    content_rowid='rowid'
);

CREATE VIRTUAL TABLE IF NOT EXISTS message_fts USING fts5(
    content,
    content='message',
    content_rowid='rowid'
);

CREATE VIRTUAL TABLE IF NOT EXISTS fact_fts USING fts5(
    subject, predicate, object,
    content='fact',
    content_rowid='rowid'
);

-- Indexes for performance
CREATE INDEX IF NOT EXISTS idx_conversation_started ON conversation(started_at);
CREATE INDEX IF NOT EXISTS idx_message_timestamp   ON message(timestamp);
CREATE INDEX IF NOT EXISTS idx_message_conv        ON message(conversation_id);
CREATE INDEX IF NOT EXISTS idx_event_type          ON event(type);
CREATE INDEX IF NOT EXISTS idx_event_timestamp     ON event(timestamp);
CREATE INDEX IF NOT EXISTS idx_event_importance    ON event(importance);
CREATE INDEX IF NOT EXISTS idx_fact_subject        ON fact(subject);
CREATE INDEX IF NOT EXISTS idx_fact_predicate      ON fact(predicate);
CREATE INDEX IF NOT EXISTS idx_preference_key      ON preference(key);
CREATE INDEX IF NOT EXISTS idx_file_path           ON file_reference(path);
CREATE INDEX IF NOT EXISTS idx_file_importance     ON file_reference(importance);
CREATE INDEX IF NOT EXISTS idx_embedding_source    ON embedding(source_id, source_type);
CREATE INDEX IF NOT EXISTS idx_credential_service  ON credential(service);
"""

_SCHEMA_VERSION = 1


class Database:
    """Manages the SQLite connection, schema migrations, and encryption key lifecycle."""

    _instance: Optional["Database"] = None
    _lock = threading.Lock()

    def __init__(
        self,
        db_path: Optional[Path] = None,
        encryption_key: Optional[bytes] = None,
    ):
        if db_path is None:
            base = self._resolve_base()
            db_path = base / "memory" / DEFAULT_DB_FILENAME
        self.db_path = db_path.resolve()
        self.encryption_key = encryption_key or self._load_or_create_key()
        self._fernet = Fernet(self.encryption_key)
        self._conn: Optional[sqlite3.Connection] = None
        self._local = threading.local()
        self.open()

    @staticmethod
    def _resolve_base() -> Path:
        from core.config_loader import get_base_dir
        return get_base_dir()

    @staticmethod
    def _load_or_create_key() -> bytes:
        base = Database._resolve_base()
        key_file = base / "config" / ".db_key"
        if key_file.exists():
            raw = key_file.read_bytes()
            if len(raw) == 44:
                return raw
        key = Fernet.generate_key()
        key_file.parent.mkdir(parents=True, exist_ok=True)
        key_file.write_bytes(key)
        return key

    @property
    def conn(self) -> sqlite3.Connection:
        if not hasattr(self._local, "conn") or self._local.conn is None:
            self._local.conn = self._create_connection()
        return self._local.conn

    def _create_connection(self) -> sqlite3.Connection:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("PRAGMA busy_timeout=5000")
        return conn

    def open(self) -> None:
        if self._conn is not None:
            return
        self._conn = self._create_connection()
        self._run_migrations()

    def close(self) -> None:
        if self._conn:
            self._conn.close()
            self._conn = None
        self._local.conn = None

    def _run_migrations(self) -> None:
        cursor = self._conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='schema_version'")
        exists = cursor.fetchone() is not None
        if not exists:
            self._conn.executescript(_SQL_SCHEMA)
            self._conn.execute("INSERT OR IGNORE INTO schema_version (version) VALUES (?)", (_SCHEMA_VERSION,))
            self._conn.commit()
            return
        current = self._conn.execute("SELECT MAX(version) FROM schema_version").fetchone()[0]
        if current is None or current < _SCHEMA_VERSION:
            self._migrate(current or 0)

    def _migrate(self, from_version: int) -> None:
        if from_version < 1:
            self._conn.executescript(_SQL_SCHEMA)
        self._conn.execute("INSERT OR IGNORE INTO schema_version (version) VALUES (?)", (_SCHEMA_VERSION,))
        self._conn.commit()

    def encrypt(self, plaintext: str) -> bytes:
        return self._fernet.encrypt(plaintext.encode("utf-8"))

    def decrypt(self, ciphertext: bytes) -> str:
        return self._fernet.decrypt(ciphertext).decode("utf-8")

    def execute(self, sql: str, params: tuple = ()) -> sqlite3.Cursor:
        return self.conn.execute(sql, params)

    def executemany(self, sql: str, params_list: list[tuple]) -> sqlite3.Cursor:
        return self.conn.executemany(sql, params_list)

    def fetchone(self, sql: str, params: tuple = ()) -> Optional[sqlite3.Row]:
        return self.conn.execute(sql, params).fetchone()

    def fetchall(self, sql: str, params: tuple = ()) -> list[sqlite3.Row]:
        return self.conn.execute(sql, params).fetchall()

    def commit(self) -> None:
        self.conn.commit()

    def vacuum(self) -> None:
        self.conn.execute("VACUUM")
        self.commit()

    @classmethod
    def get_instance(cls, **kwargs) -> "Database":
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = cls(**kwargs)
        return cls._instance

    @classmethod
    def reset_instance(cls) -> None:
        with cls._lock:
            if cls._instance:
                cls._instance.close()
            cls._instance = None
