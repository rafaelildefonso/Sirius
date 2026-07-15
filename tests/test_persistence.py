from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path
from datetime import datetime, timedelta
from typing import Iterator

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from persistence.database import Database
from persistence.repository import Repository
from persistence.models import (
    MemoryType, Event, Fact, Preference, FileReference,
    Conversation, Message, Tag, RetrievedMemory, SearchResult,
)
from persistence.classifier import Classifier
from persistence.extractor import Extractor
from persistence.backup import BackupManager


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def db_path() -> Iterator[Path]:
    tmp = tempfile.mktemp(suffix=".db")
    yield Path(tmp)
    try:
        os.unlink(tmp)
    except OSError:
        pass
    try:
        os.unlink(tmp + "-wal")
    except OSError:
        pass
    try:
        os.unlink(tmp + "-shm")
    except OSError:
        pass


@pytest.fixture
def db(db_path: Path) -> Database:
    Database.reset_instance()
    return Database.get_instance(db_path=db_path)


@pytest.fixture
def repo(db: Database) -> Repository:
    return Repository(db=db)


# ---------------------------------------------------------------------------
# Database tests
# ---------------------------------------------------------------------------

class TestDatabase:
    def test_init_creates_tables(self, db: Database):
        tables = db.fetchall("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
        names = [r["name"] for r in tables]
        assert "event" in names
        assert "message" in names
        assert "conversation" in names
        assert "fact" in names
        assert "preference" in names
        assert "file_reference" in names
        assert "tag" in names
        assert "credential" in names
        assert "embedding" in names
        assert "schema_version" in names

    def test_fts_tables_exist(self, db: Database):
        tables = db.fetchall("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
        names = [r["name"] for r in tables]
        assert "event_fts" in names
        assert "message_fts" in names
        assert "fact_fts" in names

    def test_encryption(self, db: Database):
        plain = "sensitive data"
        encrypted = db.encrypt(plain)
        assert encrypted != plain.encode()
        decrypted = db.decrypt(encrypted)
        assert decrypted == plain


# ---------------------------------------------------------------------------
# Repository tests
# ---------------------------------------------------------------------------

class TestConversation:
    def test_create_and_get(self, repo: Repository):
        cid = repo.create_conversation(title="Test")
        assert cid > 0
        conv = repo.get_conversation(cid)
        assert conv["title"] == "Test"
        assert conv["started_at"] is not None

    def test_close(self, repo: Repository):
        cid = repo.create_conversation()
        repo.close_conversation(cid)
        conv = repo.get_conversation(cid)
        assert conv["ended_at"] is not None

    def test_list(self, repo: Repository):
        repo.create_conversation(title="A")
        repo.create_conversation(title="B")
        convs = repo.list_conversations(limit=10)
        assert len(convs) >= 2

    def test_delete(self, repo: Repository):
        cid = repo.create_conversation()
        repo.delete_conversation(cid)
        assert repo.get_conversation(cid) is None


class TestMessage:
    def test_add_and_get(self, repo: Repository):
        cid = repo.create_conversation()
        mid = repo.add_message(cid, "user", "hello")
        assert mid > 0
        msgs = repo.get_messages(cid)
        assert len(msgs) == 1
        assert msgs[0]["content"] == "hello"

    def test_fts_search(self, repo: Repository):
        cid = repo.create_conversation()
        repo.add_message(cid, "user", "unique_keyword_test")
        results = repo.search_messages("unique_keyword_test")
        assert len(results) >= 1

    def test_delete_old(self, repo: Repository):
        cid = repo.create_conversation()
        repo.add_message(cid, "user", "old")
        repo.delete_old_messages(days=0)
        msgs = repo.get_messages(cid)
        assert len(msgs) == 0


class TestEvent:
    def test_save_and_get(self, repo: Repository):
        ev = Event(type=MemoryType.USER_FACT, payload={"key": "name", "value": "Joao"})
        eid = repo.save_event(ev)
        loaded = repo.get_event(eid)
        assert loaded is not None
        assert loaded.type == MemoryType.USER_FACT

    def test_fts_search(self, repo: Repository):
        ev = Event(type=MemoryType.KNOWLEDGE, payload={"text": "python programming tips"})
        eid = repo.save_event(ev)
        results = repo.search_events("python")
        assert len(results) >= 1

    def test_query_by_type_and_tag(self, repo: Repository):
        ev = Event(type=MemoryType.PREFERENCE, payload={"preference_key": "theme"}, tags=["ui"])
        eid = repo.save_event(ev)
        repo.add_event_tags(eid, ["ui"])
        results = repo.query_events(type_filter="C1", tags=["ui"])
        assert len(results) >= 1

    def test_update_access(self, repo: Repository):
        ev = Event(type=MemoryType.TEMPORARY, payload={"text": "test"})
        eid = repo.save_event(ev)
        repo.update_event_access(eid)
        ev2 = repo.get_event(eid)
        assert ev2.frequency == 1

    def test_delete(self, repo: Repository):
        ev = Event(type=MemoryType.CASUAL, payload={"text": "delete me"})
        eid = repo.save_event(ev)
        repo.delete_event(eid)
        assert repo.get_event(eid) is None


class TestFact:
    def test_save_and_search(self, repo: Repository):
        f = Fact(subject="Joao", predicate="gosta_de", object="Python", importance=0.8)
        fid = repo.save_fact(f)
        results = repo.search_facts("Python")
        assert len(results) >= 1
        assert results[0].subject == "Joao"


class TestPreference:
    def test_set_and_get(self, repo: Repository):
        repo.set_preference("language", "pt-BR", "ui", 0.5)
        p = repo.get_preference("language")
        assert p is not None
        assert p.value == "pt-BR"
        assert p.type == "ui"

    def test_get_all(self, repo: Repository):
        repo.set_preference("key_a", "val_a")
        repo.set_preference("key_b", "val_b")
        all_p = repo.get_all_preferences()
        assert "key_a" in all_p
        assert "key_b" in all_p

    def test_delete(self, repo: Repository):
        repo.set_preference("temp", "value")
        repo.delete_preference("temp")
        assert repo.get_preference("temp") is None


class TestFileReference:
    def test_save_and_search(self, repo: Repository):
        ref = FileReference(path="/tmp/test.txt", type="file", size=100)
        fid = repo.save_file_reference(ref)
        results = repo.search_files("test.txt")
        assert len(results) >= 1

    def test_get_by_path(self, repo: Repository):
        ref = FileReference(path="/unique/path/file.txt", type="file")
        repo.save_file_reference(ref)
        result = repo.get_file_by_path("/unique/path/file.txt")
        assert result is not None
        assert result["path"] == "/unique/path/file.txt"


class TestCredential:
    def test_store_and_load(self, repo: Repository):
        data = {"token": "abc123", "user": "test"}
        repo.store_credential("test_service", data)
        loaded = repo.load_credential("test_service")
        assert loaded is not None
        assert loaded["token"] == "abc123"

    def test_load_expired(self, repo: Repository):
        expired = datetime.now() - timedelta(days=1)
        repo.store_credential("expired_service", {"data": "x"}, expires_at=expired)
        assert repo.load_credential("expired_service") is None

    def test_delete(self, repo: Repository):
        repo.store_credential("delete_me", {"data": "x"})
        repo.delete_credential("delete_me")
        assert repo.load_credential("delete_me") is None


class TestTag:
    def test_ensure_tag(self, repo: Repository):
        tid = repo.ensure_tag("test-tag")
        assert tid > 0
        tid2 = repo.ensure_tag("test-tag")
        assert tid2 == tid


class TestMaintenance:
    def test_get_stats(self, repo: Repository):
        stats = repo.get_stats()
        assert "event" in stats
        assert "message" in stats
        assert "conversation" in stats

    def test_purge_expired(self, repo: Repository):
        past = datetime.now() - timedelta(days=10)
        ev = Event(
            type=MemoryType.TEMPORARY,
            payload={"text": "old"},
            valid_until=datetime.now() - timedelta(days=5),
        )
        repo.save_event(ev)
        purged = repo.purge_expired()
        assert purged >= 1


# ---------------------------------------------------------------------------
# Classifier tests
# ---------------------------------------------------------------------------

class TestClassifier:
    @pytest.fixture
    def clf(self) -> Classifier:
        return Classifier(use_llm_fallback=False)

    def test_classifier_categories(self, clf: Classifier):
        cases = [
            ("bom dia", MemoryType.CASUAL),
            ("gosto de pizza", MemoryType.PREFERENCE),
            ("meu nome é João", MemoryType.USER_FACT),
            ("projeto X está em andamento", MemoryType.PROJECT),
            ("c:\\arquivos\\test.txt", MemoryType.FILE_REF),
            ("reunião às 15h", MemoryType.COMMITMENT),
            ("não esquecer de comprar leite", MemoryType.REMINDER),
            ("preciso terminar o relatório", MemoryType.TASK),
            ("contato: maria@email.com", MemoryType.CONTACT),
            ("dica: use list comprehension", MemoryType.KNOWLEDGE),
            ("qual é a capital do Brasil", MemoryType.KNOWLEDGE),
            ("temperatura 25 graus", MemoryType.TEMPORARY),
            ("meu CPF é 123.456.789-00", MemoryType.PERMANENT),
        ]
        for text, expected in cases:
            result = clf.classify(text)
            assert result == expected, f"Failed: {text} => {result.value} != {expected.value}"


# ---------------------------------------------------------------------------
# Extractor tests
# ---------------------------------------------------------------------------

class TestExtractor:
    @pytest.fixture
    def ext(self) -> Extractor:
        return Extractor()

    def test_extract_user_fact(self, ext: Extractor):
        ev = ext.extract("meu nome é João", MemoryType.USER_FACT, use_llm=False)
        assert ev.type == MemoryType.USER_FACT
        assert ev.importance >= 0.5
        assert "user_fact" in ev.tags

    def test_extract_file_ref(self, ext: Extractor):
        ev = ext.extract("C:\\path\\to\\file.txt", MemoryType.FILE_REF, use_llm=False)
        assert ev.type == MemoryType.FILE_REF
        assert "file" in ev.tags

    def test_extract_commitment(self, ext: Extractor):
        ev = ext.extract("reunião amanhã às 10h", MemoryType.COMMITMENT, use_llm=False)
        assert ev.type == MemoryType.COMMITMENT
        assert ev.ttl == 30 * 86400

    def test_extract_permanent(self, ext: Extractor):
        ev = ext.extract("serial number ABC-123", MemoryType.PERMANENT, use_llm=False)
        assert ev.type == MemoryType.PERMANENT
        assert ev.importance >= 0.8

    def test_event_has_id(self, ext: Extractor):
        ev = ext.extract("test", MemoryType.KNOWLEDGE, use_llm=False)
        assert ev.id is not None
        assert len(ev.id) > 10


# ---------------------------------------------------------------------------
# Backup tests
# ---------------------------------------------------------------------------

class TestBackup:
    def test_backup_creates_file(self, db: Database):
        bm = BackupManager(db_path=db.db_path)
        backup_path = bm.backup()
        assert backup_path.exists()
        backup_path.unlink()

    def test_list_backups(self, db: Database):
        bm = BackupManager(db_path=db.db_path)
        bm.backup()
        backups = bm.list_backups()
        assert len(backups) >= 1
        for p in backups:
            p.unlink()


# ---------------------------------------------------------------------------
# Embedding tests
# ---------------------------------------------------------------------------

class TestEmbedding:
    def test_fallback_encoding(self):
        from persistence.embedding import EmbeddingProvider
        p = EmbeddingProvider()
        vec = p.encode("hello world")
        import numpy as np
        assert vec.dtype == np.float32
        assert vec.shape == (384,)
        norm = float(np.linalg.norm(vec))
        assert abs(norm - 1.0) < 0.01, f"norm={norm}"

    def test_different_texts_different_vectors(self):
        from persistence.embedding import EmbeddingProvider
        import numpy as np
        p = EmbeddingProvider()
        v1 = p.encode("cat")
        v2 = p.encode("dog")
        sim = float(np.dot(v1, v2))
        assert sim < 0.99

    def test_empty_text_zero_vector(self):
        from persistence.embedding import EmbeddingProvider
        import numpy as np
        p = EmbeddingProvider()
        vec = p.encode("")
        assert np.linalg.norm(vec) == 0.0

    def test_batch_encoding(self):
        from persistence.embedding import EmbeddingProvider
        import numpy as np
        p = EmbeddingProvider()
        vecs = p.encode_batch(["a", "b", "c"])
        assert vecs.shape == (3, 384)

    def test_repository_save_and_get_embedding(self, repo: Repository):
        from persistence.models import Event, MemoryType
        ev = Event(type=MemoryType.USER_FACT, payload={"text": "test embedding"})
        event_id = repo.save_event(ev)
        import numpy as np
        vec = np.ones(384, dtype=np.float32)
        repo.save_embedding(event_id, "event", vec.tobytes())
        stored = repo.get_embedding(event_id)
        assert stored is not None
        restored = np.frombuffer(stored, dtype=np.float32)
        assert np.allclose(restored, vec)
