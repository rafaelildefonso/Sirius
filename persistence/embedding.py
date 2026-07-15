from __future__ import annotations

import logging
import threading
from typing import Optional

import numpy as np

logger = logging.getLogger("persistence.embedding")

_SENTENCE_TRANSFORMERS_AVAILABLE = False
try:
    from sentence_transformers import SentenceTransformer
    _SENTENCE_TRANSFORMERS_AVAILABLE = True
except ImportError:
    pass

_DEFAULT_MODEL = "all-MiniLM-L6-v2"


class EmbeddingProvider:
    """Generates vector embeddings for text using sentence-transformers.

    Falls back to a simple hash-based fixed vector if the package is not installed,
    so the rest of the pipeline never breaks.
    """

    _instance: Optional["EmbeddingProvider"] = None
    _lock = threading.Lock()
    _model = None

    def __init__(self, model_name: str = _DEFAULT_MODEL):
        self.model_name = model_name
        self._dimension = 384
        self._available = _SENTENCE_TRANSFORMERS_AVAILABLE
        if self._available:
            try:
                if EmbeddingProvider._model is None:
                    EmbeddingProvider._model = SentenceTransformer(model_name)
                self._model = EmbeddingProvider._model
                try:
                    self._dimension = self._model.get_embedding_dimension()
                except AttributeError:
                    self._dimension = self._model.get_sentence_embedding_dimension()
                logger.info(f"Embedding model '{model_name}' loaded (dim={self._dimension})")
            except Exception as e:
                logger.warning(f"Failed to load embedding model '{model_name}': {e}")
                self._available = False

    def encode(self, text: str) -> np.ndarray:
        if not text or not text.strip():
            return np.zeros(self._dimension, dtype=np.float32)
        if self._available and self._model is not None:
            return self._model.encode(text, normalize_embeddings=True)
        return self._fallback_encode(text)

    def encode_batch(self, texts: list[str]) -> np.ndarray:
        if not texts:
            return np.zeros((0, self._dimension), dtype=np.float32)
        if self._available and self._model is not None:
            return self._model.encode(texts, normalize_embeddings=True)
        return np.array([self._fallback_encode(t) for t in texts], dtype=np.float32)

    def _fallback_encode(self, text: str) -> np.ndarray:
        import hashlib
        h = hashlib.sha256(text.encode("utf-8")).digest()
        ints = [b for b in h]
        tiled = (ints * (self._dimension // len(ints) + 1))[:self._dimension]
        arr = np.array(tiled, dtype=np.float64)
        arr = arr - arr.mean()
        std = arr.std()
        if std > 0:
            arr = arr / std
        norm = np.linalg.norm(arr)
        if norm > 0:
            arr = arr / norm
        return arr.astype(np.float32)

    @property
    def dimension(self) -> int:
        return self._dimension

    @property
    def available(self) -> bool:
        return self._available

    @classmethod
    def get_instance(cls, model_name: str = _DEFAULT_MODEL) -> "EmbeddingProvider":
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = cls(model_name=model_name)
        return cls._instance

    @classmethod
    def reset_instance(cls) -> None:
        with cls._lock:
            cls._instance = None
