"""
Sirius persistence layer — local memory database, classification, extraction, retrieval.
"""

from persistence.backup import BackupManager
from persistence.classifier import Classifier
from persistence.context_builder import ContextBuilder
from persistence.database import Database
from persistence.embedding import EmbeddingProvider
from persistence.extractor import Extractor
from persistence.repository import Repository
from persistence.retriever import Retriever
from persistence.scheduler import Scheduler

__all__ = [
    "Database",
    "Repository",
    "Classifier",
    "Extractor",
    "Retriever",
    "ContextBuilder",
    "Scheduler",
    "BackupManager",
    "EmbeddingProvider",
]
