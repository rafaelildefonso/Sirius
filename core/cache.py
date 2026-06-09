import json
import time
import threading
from pathlib import Path
from functools import wraps
from typing import Any, Callable, Optional

_CACHE: dict[str, dict] = {}
_LOCKS: dict[str, threading.Lock] = {}
_GLOBAL_LOCK = threading.Lock()

DEFAULT_TTL = 300

def _get_lock(key: str) -> threading.Lock:
    if key not in _LOCKS:
        with _GLOBAL_LOCK:
            if key not in _LOCKS:
                _LOCKS[key] = threading.Lock()
    return _LOCKS[key]


class Cache:
    def __init__(self, namespace: str = "default", max_size: int = 500):
        self.namespace = namespace
        self.max_size = max_size
        self._lock = threading.Lock()

    def _key(self, k: str) -> str:
        return f"{self.namespace}:{k}"

    def get(self, key: str) -> Optional[Any]:
        full = self._key(key)
        with self._lock:
            entry = _CACHE.get(full)
            if entry is None:
                return None
            if entry["ttl"] is not None and time.time() > entry["expires"]:
                del _CACHE[full]
                return None
            entry["hits"] = entry.get("hits", 0) + 1
            return entry["value"]

    def set(self, key: str, value: Any, ttl: Optional[int] = DEFAULT_TTL) -> None:
        full = self._key(key)
        with self._lock:
            if len(_CACHE) >= self.max_size:
                self._evict_one()
            _CACHE[full] = {
                "value": value,
                "ttl": ttl,
                "expires": time.time() + ttl if ttl is not None else None,
                "created": time.time(),
                "hits": 0,
            }

    def _evict_one(self) -> None:
        oldest = None
        oldest_key = None
        for k, v in _CACHE.items():
            if oldest is None or v["created"] < oldest:
                oldest = v["created"]
                oldest_key = k
        if oldest_key:
            del _CACHE[oldest_key]

    def invalidate(self, pattern: Optional[str] = None) -> None:
        prefix = f"{self.namespace}:"
        if pattern:
            prefix = f"{self.namespace}:{pattern}"
        with self._lock:
            to_delete = [k for k in _CACHE if k.startswith(prefix)]
            for k in to_delete:
                del _CACHE[k]

    def invalidate_all(self) -> None:
        prefix = f"{self.namespace}:"
        with self._lock:
            to_delete = [k for k in _CACHE if k.startswith(prefix)]
            for k in to_delete:
                del _CACHE[k]

    def clear(self) -> None:
        self.invalidate_all()

    def has(self, key: str) -> bool:
        return self.get(key) is not None


class PersistentCache(Cache):
    def __init__(self, namespace: str = "persistent", max_size: int = 200, db_path: Optional[Path] = None):
        super().__init__(namespace, max_size)
        if db_path is None:
            base = Path(__file__).resolve().parent.parent
            self.db_path = base / "memory" / f"cache_{namespace}.json"
        else:
            self.db_path = db_path
        self._load_from_disk()

    def _load_from_disk(self) -> None:
        try:
            if self.db_path.exists():
                data = json.loads(self.db_path.read_text(encoding="utf-8"))
                with self._lock:
                    for k, v in data.items():
                        full = self._key(k)
                        _CACHE[full] = v
        except Exception:
            pass

    def _save_to_disk(self) -> None:
        try:
            prefix = f"{self.namespace}:"
            with self._lock:
                data = {}
                for k, v in _CACHE.items():
                    if k.startswith(prefix):
                        data[k[len(prefix):]] = v
            self.db_path.parent.mkdir(parents=True, exist_ok=True)
            self.db_path.write_text(json.dumps(data, indent=2), encoding="utf-8")
        except Exception:
            pass

    def set(self, key: str, value: Any, ttl: Optional[int] = DEFAULT_TTL) -> None:
        super().set(key, value, ttl)
        self._save_to_disk()

    def invalidate(self, pattern: Optional[str] = None) -> None:
        super().invalidate(pattern)
        self._save_to_disk()


config_cache = Cache(namespace="config", max_size=50)
memory_cache = Cache(namespace="memory", max_size=20)
search_cache = Cache(namespace="search", max_size=100)
api_cache = Cache(namespace="api", max_size=100)
llm_cache = Cache(namespace="llm", max_size=200)
vision_cache = Cache(namespace="vision", max_size=50)
service_cache = Cache(namespace="service", max_size=20)

persistent_cache = PersistentCache(namespace="persistent", max_size=200)


def cached(cache: Cache, ttl: Optional[int] = DEFAULT_TTL, key_func: Optional[Callable] = None):
    def decorator(func: Callable):
        @wraps(func)
        def wrapper(*args, **kwargs):
            if key_func:
                cache_key = key_func(*args, **kwargs)
            else:
                cache_key = f"{func.__name__}:{str(args)}:{str(sorted(kwargs.items()))}"
            result = cache.get(cache_key)
            if result is not None:
                return result
            result = func(*args, **kwargs)
            cache.set(cache_key, result, ttl=ttl)
            return result
        return wrapper
    return decorator
