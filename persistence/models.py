from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Optional


class MemoryType(str, Enum):
    CASUAL = "C0"
    PREFERENCE = "C1"
    USER_FACT = "C2"
    PROJECT = "C3"
    FILE_REF = "C4"
    COMMITMENT = "C5"
    REMINDER = "C6"
    TASK = "C7"
    CONTACT = "C8"
    KNOWLEDGE = "C9"
    TEMPORARY = "C10"
    PERMANENT = "C11"


MEMORY_TYPE_LABELS = {
    MemoryType.CASUAL: "conversa casual",
    MemoryType.PREFERENCE: "preferência",
    MemoryType.USER_FACT: "fato sobre o usuário",
    MemoryType.PROJECT: "projeto/domínio",
    MemoryType.FILE_REF: "referência a arquivo",
    MemoryType.COMMITMENT: "compromisso/evento",
    MemoryType.REMINDER: "lembrete",
    MemoryType.TASK: "tarefa",
    MemoryType.CONTACT: "contato",
    MemoryType.KNOWLEDGE: "conhecimento útil",
    MemoryType.TEMPORARY: "informação temporária",
    MemoryType.PERMANENT: "informação permanente",
}


@dataclass
class RelevanceMetadata:
    importance: float = 0.5
    confidence: float = 1.0
    frequency: int = 0
    last_accessed: Optional[datetime] = None
    ttl: Optional[int] = None
    valid_until: Optional[datetime] = None
    tags: list[str] = field(default_factory=list)


@dataclass
class Event:
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    type: MemoryType = MemoryType.CASUAL
    payload: dict = field(default_factory=dict)
    timestamp: datetime = field(default_factory=datetime.now)
    source: str = "user"
    importance: float = 0.5
    confidence: float = 1.0
    frequency: int = 0
    last_accessed: Optional[datetime] = None
    ttl: Optional[int] = None
    valid_until: Optional[datetime] = None
    metadata: dict = field(default_factory=dict)
    tags: list[str] = field(default_factory=list)


@dataclass
class Conversation:
    id: int = 0
    title: Optional[str] = None
    started_at: datetime = field(default_factory=datetime.now)
    ended_at: Optional[datetime] = None


@dataclass
class Message:
    id: int = 0
    conversation_id: int = 0
    role: str = "user"
    content: str = ""
    timestamp: datetime = field(default_factory=datetime.now)
    metadata: dict = field(default_factory=dict)
    importance: float = 0.5
    confidence: float = 1.0
    source: str = "user"


@dataclass
class Fact:
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    subject: str = ""
    predicate: str = ""
    object: str = ""
    confidence: float = 0.5
    source: str = ""
    created_at: datetime = field(default_factory=datetime.now)
    updated_at: Optional[datetime] = None
    importance: float = 0.5


@dataclass
class Preference:
    key: str = ""
    value: str = ""
    type: str = "general"
    importance: float = 0.5
    last_used: Optional[datetime] = None
    usage_count: int = 0
    ttl: Optional[int] = None
    created_at: datetime = field(default_factory=datetime.now)
    updated_at: Optional[datetime] = None


@dataclass
class FileReference:
    id: int = 0
    path: str = ""
    type: str = "file"
    size: Optional[int] = None
    created_at: Optional[datetime] = None
    modified_at: Optional[datetime] = None
    hash: Optional[str] = None
    importance: float = 0.3
    metadata: dict = field(default_factory=dict)
    tags: list[str] = field(default_factory=list)


@dataclass
class Tag:
    id: int = 0
    name: str = ""
    color: Optional[str] = None


@dataclass
class RetrievedMemory:
    event: Event
    score: float = 0.0
    source_type: str = "event"
    snippet: str = ""


@dataclass
class SearchResult:
    items: list[RetrievedMemory] = field(default_factory=list)
    total: int = 0
    query_time_ms: float = 0.0
