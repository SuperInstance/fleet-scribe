"""scribe/cache.py — Persistent cache layer for baselines and state fingerprints.

Stores baselines on disk as JSON. Auto-prunes stale entries. Tracks hit/miss stats.
"""

import json
import os
import time
from pathlib import Path
from typing import Any, Dict, Optional, Tuple


class FileCache:
    """File-backed cache for state baselines and arbitrary key/value pairs.

    Keys are hashed to filenames, values are JSON-serialized. Each entry stores
    a timestamp for TTL-based pruning.

    Usage:
        cache = FileCache("/tmp/scribe_cache")
        cache.set("baseline:v1", {"files": {...}, "metrics": {...}})
        has_it = cache.has("baseline:v1")
        value, age = cache.get("baseline:v1")  # age in seconds
        cache.auto_prune(ttl_seconds=3600)
    """

    _META_KEY = "__meta__"

    def __init__(self, cache_dir: Optional[str] = None):
        """Initialize cache with a directory.

        Args:
            cache_dir: Directory to store cache files. Created if missing.
                       Defaults to ~/.cache/fleet-scribe/
        """
        if cache_dir is None:
            cache_dir = os.path.expanduser("~/.cache/fleet-scribe/")
        self._cache_dir = Path(cache_dir)
        self._cache_dir.mkdir(parents=True, exist_ok=True)

        # In-memory index to avoid hitting disk for every has() call
        self._index: Dict[str, Dict[str, Any]] = {}
        self._hits = 0
        self._misses = 0

        self._load_index()

    # ── Public API ─────────────────────────────────────────────────────────

    def get(self, key: str) -> Tuple[Optional[Any], Optional[float]]:
        """Get a value from the cache.

        Returns:
            Tuple of (value, age_seconds). age is None if key doesn't exist.
            Returns (None, None) if key not found.
        """
        entry = self._read_entry(key)
        if entry is None:
            self._misses += 1
            return None, None

        self._hits += 1
        created_at = entry.get("_created_at", time.time())
        age = time.time() - created_at
        return entry.get("value"), age

    def set(self, key: str, value: Any, ttl_seconds: Optional[float] = None) -> None:
        """Store a value in the cache.

        Args:
            key: Cache key (string)
            value: JSON-serializable value to store
            ttl_seconds: Optional TTL; entry will be auto-pruned after this many seconds.
                         None means no expiry.
        """
        entry = {
            "key": key,
            "value": value,
            "_created_at": time.time(),
        }
        if ttl_seconds is not None:
            entry["_ttl"] = ttl_seconds

        self._write_entry(key, entry)

    def has(self, key: str) -> bool:
        """Check if a key exists in the cache."""
        return self._read_entry(key) is not None

    def delete(self, key: str) -> bool:
        """Delete a key from the cache. Returns True if it existed."""
        path = self._key_path(key)
        if path.exists():
            path.unlink()
            self._index.pop(key, None)
            self._save_index()
            return True
        return False

    def clear(self) -> int:
        """Clear all entries from the cache. Returns count of deleted entries."""
        count = 0
        for key in list(self._index.keys()):
            if self.delete(key):
                count += 1
        return count

    def auto_prune(self, ttl_seconds: float) -> Dict[str, int]:
        """Remove all entries older than ttl_seconds.

        Also removes entries whose _ttl has expired.

        Returns:
            Dict with 'removed' (count of removed entries), 'remaining' (still in cache)
        """
        now = time.time()
        to_remove = []

        for key, meta in list(self._index.items()):
            created = meta.get("created_at", 0)
            age = now - created
            entry = self._read_entry(key)

            if entry is None:
                to_remove.append(key)
                continue

            # Check explicit TTL
            entry_ttl = entry.get("_ttl")
            if entry_ttl is not None and age > entry_ttl:
                to_remove.append(key)
                continue

            # Check max age
            if age > ttl_seconds:
                to_remove.append(key)
                continue

        for key in to_remove:
            self.delete(key)

        return {"removed": len(to_remove), "remaining": len(self._index)}

    # ── Statistics ─────────────────────────────────────────────────────────

    @property
    def stats(self) -> Dict[str, Any]:
        """Return cache statistics."""
        total = self._hits + self._misses
        hit_rate = self._hits / total if total > 0 else 0.0
        oldest = self._oldest_entry_age()

        return {
            "hits": self._hits,
            "misses": self._misses,
            "hit_rate": hit_rate,
            "size": len(self._index),
            "oldest_entry_age": oldest,
        }

    def reset_stats(self) -> None:
        """Reset hit/miss counters."""
        self._hits = 0
        self._misses = 0

    # ── Storage helpers ────────────────────────────────────────────────────

    def _key_path(self, key: str) -> Path:
        """Map a key to a filename within the cache directory."""
        import hashlib

        digest = hashlib.sha256(key.encode()).digest()
        safe = digest[:8].hex()
        return self._cache_dir / f"{safe}.json"

    def _read_entry(self, key: str) -> Optional[Dict[str, Any]]:
        """Read an entry from disk without touching the index."""
        path = self._key_path(key)
        if not path.exists():
            return None
        try:
            with open(path, "r") as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            return None

    def _write_entry(self, key: str, entry: Dict[str, Any]) -> None:
        """Write an entry to disk and update the index."""
        path = self._key_path(key)
        with open(path, "w") as f:
            json.dump(entry, f)

        self._index[key] = {
            "created_at": entry.get("_created_at", time.time()),
            "size_bytes": path.stat().st_size,
        }
        self._save_index()

    def _load_index(self) -> None:
        """Load the in-memory index from disk."""
        idx_path = self._cache_dir / "__index__.json"
        if idx_path.exists():
            try:
                with open(idx_path, "r") as f:
                    self._index = json.load(f)
            except (json.JSONDecodeError, OSError):
                self._index = {}
        else:
            self._index = {}

        # Verify index entries still exist on disk
        stale = [k for k in self._index if not self._key_path(k).exists()]
        for k in stale:
            self._index.pop(k, None)

    def _save_index(self) -> None:
        """Persist the in-memory index to disk."""
        idx_path = self._cache_dir / "__index__.json"
        with open(idx_path, "w") as f:
            json.dump(self._index, f)

    def _oldest_entry_age(self) -> Optional[float]:
        """Return age of the oldest entry in seconds, or None if empty."""
        if not self._index:
            return None
        now = time.time()
        oldest = min(m.get("created_at", now) for m in self._index.values())
        return now - oldest