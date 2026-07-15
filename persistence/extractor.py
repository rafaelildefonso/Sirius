"""
Extractor — transforms classified text + context into structured Event objects.
"""

from __future__ import annotations

import json
import re
from datetime import datetime
from typing import Any, Optional

from persistence.models import Event, MemoryType, RelevanceMetadata

_SYSTEM_PROMPT = """You are a structured memory extractor. Given a conversation turn, extract a JSON object with:

{
  "entities": [{"name": "", "type": "person|project|file|place|other", "value": ""}],
  "attributes": {"key1": "value1", ...},
  "importance": 0.0-1.0,
  "confidence": 0.0-1.0,
  "tags": ["tag1", "tag2"],
  "ttl_seconds": null or number,
  "summary": "brief description of what was extracted"
}

Rules:
- importance: 0.3=trivial, 0.5=normal, 0.7=important, 0.9=crucial
- confidence: 0.5=guessed, 0.8=likely, 1.0=explicitly stated
- tags: free-form keywords for later retrieval
- ttl_seconds: set to null if permanent, or number of seconds if info expires
- Extract ALL entities mentioned
- Use concise English keys in attributes regardless of language"""


class Extractor:
    """Converts recognized text into a structured Event."""

    def extract(
        self,
        text: str,
        memory_type: MemoryType,
        source: str = "user",
        context: Optional[dict] = None,
        use_llm: bool = True,
    ) -> Event:
        if use_llm and memory_type not in (MemoryType.CASUAL, MemoryType.TEMPORARY):
            return self._llm_extract(text, memory_type, source, context)
        return self._rule_extract(text, memory_type, source)

    def _rule_extract(self, text: str, memory_type: MemoryType, source: str) -> Event:
        payload = {"text": text}
        importance = 0.5
        confidence = 0.8
        tags = []
        ttl = None

        if memory_type == MemoryType.PREFERENCE:
            payload["preference_key"] = self._extract_keyword(text)
            importance = 0.6
            tags.append("preference")
        elif memory_type == MemoryType.USER_FACT:
            payload["fact_text"] = text
            importance = 0.7
            tags.append("user_fact")
        elif memory_type == MemoryType.PROJECT:
            payload["project_name"] = self._extract_keyword(text)
            importance = 0.7
            tags.append("project")
        elif memory_type == MemoryType.FILE_REF:
            paths = re.findall(r"[\w:][\\/][\w\\/. -]+", text)
            if paths:
                payload["path"] = paths[0]
            tags.append("file")
        elif memory_type == MemoryType.COMMITMENT:
            importance = 0.8
            tags.append("commitment")
            ttl = 30 * 86400
        elif memory_type == MemoryType.REMINDER:
            importance = 0.6
            tags.append("reminder")
            ttl = 7 * 86400
        elif memory_type == MemoryType.TASK:
            importance = 0.6
            tags.append("task")
        elif memory_type == MemoryType.CONTACT:
            importance = 0.8
            tags.append("contact")
        elif memory_type == MemoryType.KNOWLEDGE:
            importance = 0.5
            tags.append("knowledge")
        elif memory_type == MemoryType.PERMANENT:
            importance = 0.9
            confidence = 0.9
            tags.append("permanent")

        return Event(
            type=memory_type,
            payload=payload,
            source=source,
            importance=importance,
            confidence=confidence,
            metadata={"tags": tags},
            tags=tags,
            ttl=ttl,
            valid_until=datetime.now().timestamp() + ttl if ttl else None,
        )

    def _llm_extract(self, text: str, memory_type: MemoryType, source: str, context: Optional[dict] = None) -> Event:
        try:
            from or_client import client
            context_str = json.dumps(context or {})
            prompt = (
                f"{_SYSTEM_PROMPT}\n\n"
                f"Category: {memory_type.value}\n"
                f"Context: {context_str[:300]}\n"
                f"User message: {text[:600]}\n\n"
                f"JSON:"
            )
            raw = client.chat(
                prompt,
                system=_SYSTEM_PROMPT,
                max_tokens=512,
                temperature=0.2,
            )
            clean = raw.strip()
            clean = re.sub(r"```(?:json)?", "", clean).strip().rstrip("`").strip()
            if clean and clean.startswith("{"):
                data = json.loads(clean)
            else:
                data = {}
        except Exception:
            data = {}

        return Event(
            type=memory_type,
            payload=data.get("attributes", {"text": text}),
            source=source,
            importance=min(max(float(data.get("importance", 0.5)), 0.0), 1.0),
            confidence=min(max(float(data.get("confidence", 0.8)), 0.0), 1.0),
            metadata={"entities": data.get("entities", []), "tags": data.get("tags", [])},
            tags=data.get("tags", []),
            ttl=data.get("ttl_seconds"),
        )

    @staticmethod
    def _extract_keyword(text: str) -> str:
        words = text.split()
        for w in words:
            clean = w.strip(".,:;!?\"'")
            if clean and clean[0].isupper() and len(clean) > 2:
                return clean
        return words[-1] if words else ""
