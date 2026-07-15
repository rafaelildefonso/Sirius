"""
Classifier — automatically categorizes incoming user input into memory types (C0–C11).
Uses a two‑stage approach: fast keyword/rule‑based pre‑filter, then LLM for ambiguous cases.
"""

from __future__ import annotations

import re
from typing import Optional

from persistence.models import MemoryType, MEMORY_TYPE_LABELS

_SYSTEM_PROMPT = """You are a memory classifier for a personal AI assistant.
Your task is to classify the user's message into ONE of the following categories.
Respond ONLY with the category code (C0-C11), nothing else.

Categories:
C0 = CASUAL_CHAT — social conversation, greetings, small talk, jokes, no long-term info
C1 = PREFERENCE — user states a like, dislike, favorite, or personal preference
C2 = USER_FACT — personal fact about the user (name, age, job, city, family, etc.)
C3 = PROJECT — information about a project, codebase, domain, or ongoing work
C4 = FILE_REF — reference to a file, directory, path, document, or code snippet
C5 = COMMITMENT — appointment, meeting, event with date/time, schedule
C6 = REMINDER — something the user wants to be reminded of later
C7 = TASK — actionable item, to-do, task description
C8 = CONTACT — information about a person (name, email, phone, company)
C9 = KNOWLEDGE — useful knowledge, tip, trick, tutorial, conceptual information
C10 = TEMPORARY — transient info that will expire (weather, temp, status update)
C11 = PERMANENT — critical permanent info (serial numbers, IDs, credentials)"""

# Keyword patterns for fast pre-classification
_PATTERNS: list[tuple[re.Pattern, MemoryType]] = [
    (re.compile(r"\b(prefiro|gosto|odeio|amo|adoro|favorit[oa]|prefer(e|ência)|like|love|hate|favorite|dislike)\b", re.IGNORECASE), MemoryType.PREFERENCE),
    (re.compile(r"\b(meu nome|eu me chamo|i'?m\s+\w+|my name is|tenho \d+ anos|nasci|moro|trabalho com)\b", re.IGNORECASE), MemoryType.USER_FACT),
    (re.compile(r"\b(projeto|project|repositório|repo|github|branch|código|codebase|app|aplicativo)\b", re.IGNORECASE), MemoryType.PROJECT),
    (re.compile(r"(\w:[/\\][\w\\/. -]+|\b[C-Z]:\\|\b/home/|\b/Users/)", re.IGNORECASE), MemoryType.FILE_REF),
    (re.compile(r"\b(arquivo|file|pasta|folder|directory|caminho|path|documento)\b", re.IGNORECASE), MemoryType.FILE_REF),
    (re.compile(r"\b(agend(a|ar)|reunião|meeting|compromisso|appointment|evento|às?\s+\d+h|às?\s+\d+:\d+)\b", re.IGNORECASE), MemoryType.COMMITMENT),
    (re.compile(r"\b(lembra|lembrete|remind|não esquecer|não esqueça|não posso esquecer)\b", re.IGNORECASE), MemoryType.REMINDER),
    (re.compile(r"\b(tarefa|task|to.?do|afazer|preciso (fazer|terminar|completar|finalizar|entregar)|tenho que|pendente)\b", re.IGNORECASE), MemoryType.TASK),
    (re.compile(r"\b(contato|contact|email?|telefone|phone|whatsapp|linkedin)\b", re.IGNORECASE), MemoryType.CONTACT),
    (re.compile(r"\b(dica|truque|tutorial|how to|como fazer|aprendi|descobri|conhecimento|knowledge|útil)\b", re.IGNORECASE), MemoryType.KNOWLEDGE),
    (re.compile(r"^(qual [eé]|what (is|are)|o que [eé]|como (funciona|usar|fazer))", re.IGNORECASE), MemoryType.KNOWLEDGE),
    (re.compile(r"\b(temperatura|clima|weather|previsão|agora|current|status|online|offline)\b", re.IGNORECASE), MemoryType.TEMPORARY),
    (re.compile(r"\b(número de série|serial|cpf|cnpj|rg|identidade|credencial|password|senha|token|key|api.?key)\b", re.IGNORECASE), MemoryType.PERMANENT),
]


class Classifier:
    """Determines the memory type of a user message."""

    def __init__(self, use_llm_fallback: bool = True):
        self.use_llm_fallback = use_llm_fallback

    def classify(self, text: str) -> MemoryType:
        result = self._rule_based(text)
        if result is not None:
            return result
        if self.use_llm_fallback:
            return self._llm_classify(text)
        return MemoryType.CASUAL

    def _rule_based(self, text: str) -> Optional[MemoryType]:
        for pattern, mtype in _PATTERNS:
            if pattern.search(text):
                return mtype
        return None

    def _llm_classify(self, text: str) -> MemoryType:
        try:
            from or_client import client
            result = client.chat(
                f"{_SYSTEM_PROMPT}\n\nUser message: {text[:500]}\n\nCategory code (C0-C11):",
                system=_SYSTEM_PROMPT,
                max_tokens=5,
                temperature=0.0,
            )
            code = result.strip().upper()
            for mt in MemoryType:
                if mt.value == code:
                    return mt
        except Exception:
            pass
        return MemoryType.CASUAL
