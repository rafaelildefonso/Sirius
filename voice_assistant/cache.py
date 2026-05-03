"""Simple cache system for voice assistant."""

from __future__ import annotations

import json
import hashlib
import os
import time
from typing import Optional, Any
from pathlib import Path


def get_default_cache_dir() -> Path:
    """Get default cache directory based on OS."""
    if os.name == 'nt':  # Windows
        base_dir = os.environ.get('LOCALAPPDATA', os.path.expanduser('~'))
    else:  # Linux/Mac
        base_dir = os.environ.get('XDG_CACHE_HOME', os.path.expanduser('~/.cache'))

    cache_dir = Path(base_dir) / 'sirius_cache'
    return cache_dir


class SimpleCache:
    """File-based cache with TTL support."""

    def __init__(self, cache_dir: str = None, default_ttl: int = 300):
        """Initialize cache.

        Args:
            cache_dir: Directory to store cache files (defaults to OS-appropriate location)
            default_ttl: Default time-to-live in seconds (5 minutes)
        """
        if cache_dir is None:
            self.cache_dir = get_default_cache_dir()
        else:
            self.cache_dir = Path(cache_dir)

        # Create cache directory and all parent directories
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.default_ttl = default_ttl
        self._memory_cache: dict[str, tuple[Any, float]] = {}  # (value, expiry)

    def _get_key(self, prefix: str, data: str) -> str:
        """Generate cache key from data."""
        hash_val = hashlib.md5(data.encode()).hexdigest()[:12]
        return f"{prefix}_{hash_val}"

    def get(self, key: str) -> Optional[Any]:
        """Get value from cache if not expired."""
        # Check memory cache first
        if key in self._memory_cache:
            value, expiry = self._memory_cache[key]
            if time.time() < expiry:
                return value
            else:
                del self._memory_cache[key]

        # Check file cache
        cache_file = self.cache_dir / f"{key}.json"
        if cache_file.exists():
            try:
                with open(cache_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                if time.time() < data.get('expiry', 0):
                    return data.get('value')
                else:
                    cache_file.unlink()  # Delete expired
            except Exception:
                pass
        return None

    def set(self, key: str, value: Any, ttl: Optional[int] = None) -> None:
        """Store value in cache."""
        ttl = ttl or self.default_ttl
        expiry = time.time() + ttl

        # Store in memory (fast access)
        self._memory_cache[key] = (value, expiry)

        # Store in file (persistent)
        cache_file = self.cache_dir / f"{key}.json"
        try:
            with open(cache_file, 'w', encoding='utf-8') as f:
                json.dump({'value': value, 'expiry': expiry}, f)
        except Exception:
            pass  # File cache is optional

    def get_or_compute(
        self,
        prefix: str,
        data: str,
        compute_fn: callable,
        ttl: Optional[int] = None,
    ) -> Any:
        """Get from cache or compute and store."""
        key = self._get_key(prefix, data)

        # Try cache first
        cached = self.get(key)
        if cached is not None:
            print(f"[Cache] Hit for {prefix}")
            return cached

        # Compute and cache
        print(f"[Cache] Miss for {prefix}, computing...")
        value = compute_fn()
        self.set(key, value, ttl)
        return value

    def clear(self) -> None:
        """Clear all cache."""
        self._memory_cache.clear()
        for f in self.cache_dir.glob("*.json"):
            try:
                f.unlink()
            except Exception:
                pass


class ModelCache:
    """Cache for loaded ML models to avoid reloading."""

    _instance: Optional[ModelCache] = None
    _models: dict[str, Any] = {}

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def get_model(self, name: str, loader_fn: callable) -> Any:
        """Get model from cache or load it."""
        if name not in self._models:
            print(f"[ModelCache] Loading {name}...")
            self._models[name] = loader_fn()
            print(f"[ModelCache] {name} loaded and cached")
        else:
            print(f"[ModelCache] Using cached {name}")
        return self._models[name]

    def has_model(self, name: str) -> bool:
        """Check if model is cached."""
        return name in self._models

    def clear(self) -> None:
        """Clear all cached models."""
        self._models.clear()


# Global cache instances (using OS-appropriate cache directories)
search_cache = SimpleCache(None, default_ttl=300)  # 5 min - uses ~/.cache/sirius_cache or %LOCALAPPDATA%/sirius_cache
llm_cache = SimpleCache(None, default_ttl=600)  # 10 min
model_cache = ModelCache()
