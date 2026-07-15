"""
Sirius persistence layer — local memory database, classification, extraction, retrieval.
"""

from persistence.database import Database
from persistence.repository import Repository
from persistence.classifier import Classifier
from persistence.extractor import Extractor
from persistence.retriever import Retriever
from persistence.context_builder import ContextBuilder
from persistence.scheduler import Scheduler
from persistence.backup import BackupManager
from persistence.embedding import EmbeddingProvider

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
