"""
Retriever — intelligent memory retrieval combining structured queries with optional semantic (RAG) search.
"""

from __future__ import annotations

import json
import math
import time
from datetime import datetime, timedelta
from typing import Any, Optional

import numpy as np

from persistence.database import Database
from persistence.models import Event, MemoryType, RetrievedMemory, SearchResult
from persistence.repository import Repository


class Retriever:
    """Combines structured (SQL) and semantic (embedding) retrieval with relevance scoring."""

    def __init__(self, repo: Optional[Repository] = None, db: Optional[Database] = None):
        self.repo = repo or Repository(db=db)
        self.db = db or Database.get_instance()
        self._embedding_provider = None

    @property
    def _embedder(self):
        if self._embedding_provider is None:
            try:
                from persistence.embedding import EmbeddingProvider
                self._embedding_provider = EmbeddingProvider.get_instance()
            except Exception:
                self._embedding_provider = False
        return self._embedding_provider if self._embedding_provider else None

    def search(
        self,
        query: str,
        memory_types: Optional[list[MemoryType]] = None,
        min_importance: float = 0.0,
        tags: Optional[list[str]] = None,
        limit: int = 30,
        use_semantic: bool = False,
        prefer_recency: bool = True,
    ) -> SearchResult:
        start = time.time()

        structured_results: list[RetrievedMemory] = []
        semantic_results: list[RetrievedMemory] = []

        type_filter = None
        if memory_types and len(memory_types) == 1:
            type_filter = memory_types[0].value

        events = self.repo.query_events(
            type_filter=type_filter,
            min_importance=min_importance,
            tags=tags,
            limit=limit,
        )

        for ev in events:
            snippet = json.dumps(ev.payload, ensure_ascii=False)
            if len(snippet) > 200:
                snippet = snippet[:197] + "..."
            structured_results.append(RetrievedMemory(
                event=ev,
                score=self._compute_score(ev, query, prefer_recency),
                source_type="event",
                snippet=snippet,
            ))

        if use_semantic:
            semantic_results = self._semantic_search(query, limit)
            seen_ids = {r.event.id for r in structured_results}
            semantic_results = [r for r in semantic_results if r.event.id not in seen_ids]

        all_results = structured_results + semantic_results
        all_results.sort(key=lambda r: r.score, reverse=True)
        all_results = all_results[:limit]

        return SearchResult(
            items=all_results,
            total=len(all_results),
            query_time_ms=(time.time() - start) * 1000,
        )

    def search_facts(self, query: str, limit: int = 20) -> SearchResult:
        start = time.time()
        facts = self.repo.search_facts(query, limit)
        items = []
        for f in facts:
            items.append(RetrievedMemory(
                event=Event(
                    type=MemoryType.KNOWLEDGE,
                    payload={"subject": f.subject, "predicate": f.predicate, "object": f.object},
                ),
                score=f.importance,
                source_type="fact",
                snippet=f"{f.subject} -> {f.predicate}: {f.object}",
            ))
        return SearchResult(items=items, total=len(items), query_time_ms=(time.time() - start) * 1000)

    def search_messages(self, query: str, limit: int = 20) -> SearchResult:
        start = time.time()
        messages = self.repo.search_messages(query, limit)
        items = []
        for m in messages:
            items.append(RetrievedMemory(
                event=Event(
                    type=MemoryType.CASUAL,
                    payload={"content": m["content"]},
                    timestamp=m["timestamp"] if isinstance(m.get("timestamp"), datetime) else datetime.fromisoformat(m["timestamp"]),
                ),
                score=0.5,
                source_type="message",
                snippet=m["content"][:200] if m["content"] else "",
            ))
        return SearchResult(items=items, total=len(items), query_time_ms=(time.time() - start) * 1000)

    def get_relevant_preferences(self, limit: int = 20) -> dict:
        return self.repo.get_all_preferences()

    def get_top_memories(self, limit: int = 10) -> list[RetrievedMemory]:
        events = self.repo.query_events(
            min_importance=0.5,
            limit=limit,
        )
        return [RetrievedMemory(
            event=ev,
            score=ev.importance,
            source_type="event",
            snippet=json.dumps(ev.payload, ensure_ascii=False)[:200],
        ) for ev in events]

    def _semantic_search(self, query: str, limit: int) -> list[RetrievedMemory]:
        """Semantic search using embedding vectors, falling back to FTS5."""
        embedder = self._embedder
        if embedder is not None and embedder.available:
            try:
                query_vec = embedder.encode(query)
                events = self._vector_search(query_vec, limit)
                if events:
                    return events
            except Exception as e:
                logger = __import__("logging").getLogger("persistence.retriever")
                logger.debug(f"Vector search failed, falling back to FTS: {e}")

        try:
            events = self.repo.search_events(query, limit)
            return [RetrievedMemory(
                event=ev,
                score=ev.importance * 1.1,
                source_type="event",
                snippet=json.dumps(ev.payload, ensure_ascii=False)[:200],
            ) for ev in events]
        except Exception:
            return []

    def _vector_search(self, query_vec: np.ndarray, limit: int) -> list[RetrievedMemory]:
        """Cosine similarity search over stored embeddings."""
        rows = self.db.fetchall(
            "SELECT e.*, em.vector, em.source_type "
            "FROM embedding em JOIN event e ON e.id = em.source_id "
            "WHERE em.source_type = 'event' "
            "ORDER BY em.rowid DESC LIMIT 200"
        )
        if not rows:
            return []

        scored = []
        for r in rows:
            stored_vec = np.frombuffer(r["vector"], dtype=np.float32)
            if len(stored_vec) == 0:
                continue
            norm = np.linalg.norm(stored_vec)
            if norm > 0:
                stored_vec = stored_vec / norm
            sim = float(np.dot(query_vec, stored_vec))
            if sim > 0.3:
                ev = self.repo._row_to_event(r)
                scored.append(RetrievedMemory(
                    event=ev,
                    score=sim * 0.5 + ev.importance * 0.5,
                    source_type="event",
                    snippet=json.dumps(ev.payload, ensure_ascii=False)[:200],
                ))

        scored.sort(key=lambda x: x.score, reverse=True)
        return scored[:limit]

    def _compute_score(self, event: Event, query: str, prefer_recency: bool) -> float:
        alpha = 0.4
        beta = 0.3
        gamma = 0.2
        delta = 0.1

        imp = event.importance
        freq = min(math.log(event.frequency + 1) / 5.0, 1.0)

        recency = 0.5
        if prefer_recency and event.last_accessed:
            days_since = (datetime.now() - event.last_accessed).days
            recency = math.exp(-days_since / 30.0)

        text = json.dumps(event.payload).lower()
        query_words = set(query.lower().split())
        text_words = set(text.split())
        overlap = len(query_words & text_words) / max(len(query_words), 1)

        score = alpha * imp + beta * freq + gamma * recency + delta * overlap
        return min(score, 1.0)
