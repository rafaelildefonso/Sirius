"""
ContextBuilder — builds structured context for LLM prompts from retrieved memories.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from typing import Any, Optional

from persistence.models import MemoryType, RetrievedMemory, SearchResult
from persistence.retriever import Retriever


class ContextBuilder:
    """Assembles the context block sent to the LLM, combining structured + semantic results."""

    MAX_TOKENS_DEFAULT = 4000

    def __init__(self, retriever: Optional[Retriever] = None):
        self.retriever = retriever or Retriever()

    def build(
        self,
        query: str,
        recent_messages: Optional[list[dict]] = None,
        max_tokens: int = MAX_TOKENS_DEFAULT,
        include_preferences: bool = True,
        include_facts: bool = True,
        include_top_memories: bool = True,
        recent_count: int = 10,
    ) -> str:
        sections = []

        sections.append(self._build_curt_term_section(recent_messages or [], recent_count))

        if include_top_memories:
            mems = self.retriever.get_top_memories(limit=8)
            if mems:
                sections.append(self._format_memories("Top memories", mems))

        result = self.retriever.search(query, limit=15, use_semantic=True)
        if result.items:
            sections.append(self._format_memories("Relevant memories", result.items))

        if include_facts:
            fact_result = self.retriever.search_facts(query, limit=10)
            if fact_result.items:
                sections.append(self._format_memories("Known facts", fact_result.items))

        if include_preferences:
            prefs = self.retriever.get_relevant_preferences()
            if prefs:
                prefs_lines = []
                for k, v in list(prefs.items())[:15]:
                    prefs_lines.append(f"  - {k}: {v}")
                sections.append("[USER PREFERENCES]\n" + "\n".join(prefs_lines))

        combined = "\n\n".join(sections)

        approx_tokens = len(combined) // 4
        if approx_tokens > max_tokens:
            lines = combined.split("\n")
            trimmed = []
            token_count = 0
            for line in lines:
                estimated = len(line) // 4
                if token_count + estimated > max_tokens - 200:
                    break
                trimmed.append(line)
                token_count += estimated
            combined = "\n".join(trimmed)

        return combined

    def build_for_conversation(self, conv_id: int, query: str, max_tokens: int = MAX_TOKENS_DEFAULT) -> str:
        from persistence.repository import Repository
        repo = Repository()
        messages = repo.get_messages(conv_id, limit=30)
        return self.build(query, recent_messages=messages, max_tokens=max_tokens)

    def _build_curt_term_section(self, messages: list[dict], count: int) -> str:
        recent = messages[-count:] if len(messages) > count else messages
        if not recent:
            return ""
        lines = ["[RECENT CONVERSATION]"]
        for m in recent:
            role = m.get("role", "user")
            content = m.get("content", "")
            if len(content) > 300:
                content = content[:297] + "..."
            lines.append(f"{role.title()}: {content}")
        return "\n".join(lines)

    @staticmethod
    def _format_memories(header: str, items: list[RetrievedMemory]) -> str:
        lines = [f"[{header.upper()}]"]
        for item in items[:10]:
            prefix = ""
            if item.event.type == MemoryType.PREFERENCE:
                prefix = "[PREF] "
            elif item.event.type == MemoryType.REMINDER:
                prefix = "[REMINDER] "
            elif item.event.type == MemoryType.TASK:
                prefix = "[TASK] "
            elif item.event.type == MemoryType.KNOWLEDGE:
                prefix = "[INFO] "

            payload = item.event.payload
            text = item.snippet[:200] if item.snippet else json.dumps(payload, ensure_ascii=False)[:200]
            score_str = f" [score:{item.score:.2f}]"
            lines.append(f"  {prefix}{text}{score_str}")

        return "\n".join(lines)
