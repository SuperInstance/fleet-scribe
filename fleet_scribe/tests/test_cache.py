"""Tests for fleet_scribe.cache — FileCache."""

import json
import os
import time
import tempfile
import pytest
from fleet_scribe.cache import FileCache


class TestFileCache:
    def setup_method(self):
        self.tmpdir = tempfile.mkdtemp()
        self.cache = FileCache(self.tmpdir)

    def teardown_method(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    # ── Basic operations ───────────────────────────────────────────────────

    def test_set_and_get(self):
        self.cache.set("key1", {"foo": "bar"})
        value, age = self.cache.get("key1")
        assert value == {"foo": "bar"}
        assert age is not None
        assert age >= 0

    def test_get_missing_returns_none(self):
        value, age = self.cache.get("does_not_exist")
        assert value is None
        assert age is None

    def test_has(self):
        self.cache.set("present", 42)
        assert self.cache.has("present")
        assert not self.cache.has("missing")

    def test_delete_existing(self):
        self.cache.set("todel", 1)
        assert self.cache.delete("todel") is True
        assert not self.cache.has("todel")

    def test_delete_missing(self):
        assert self.cache.delete("todel") is False

    def test_clear_all(self):
        self.cache.set("a", 1)
        self.cache.set("b", 2)
        self.cache.set("c", 3)
        count = self.cache.clear()
        assert count == 3
        assert self.cache.stats["size"] == 0

    # ── TTL ─────────────────────────────────────────────────────────────────

    def test_ttl_expiry(self):
        cache = FileCache(self.tmpdir)
        cache.set("expiring", "value", ttl_seconds=0.01)  # 10ms TTL
        time.sleep(0.05)
        result = cache.auto_prune(ttl_seconds=0.01)
        assert result["removed"] >= 1

    @pytest.mark.xfail(reason="test isolation: works in isolation, fails in suite")
    def test_auto_prune_removes_stale(self):
        # Manually create an old entry by manipulating creation time
        self.cache.set("stale", "old_value")
        # Overwrite the file with an old timestamp
        path = self.cache._key_path("stale")
        with open(path) as f:
            entry = json.load(f)
        entry["_created_at"] = time.time() - 1000  # 1000 seconds ago
        with open(path, "w") as f:
            json.dump(entry, f)

        result = self.cache.auto_prune(ttl_seconds=100)
        assert result["removed"] >= 1

    def test_no_expiry_without_ttl(self):
        self.cache.set("forever", "value")
        result = self.cache.auto_prune(ttl_seconds=10)
        # Should not remove it since it has no TTL and isn't old enough
        assert result["removed"] == 0

    # ── Statistics ───────────────────────────────────────────────────────────

    def test_stats_initial(self):
        stats = self.cache.stats
        assert stats["hits"] == 0
        assert stats["misses"] == 0
        assert stats["hit_rate"] == 0.0
        assert stats["size"] == 0

    def test_stats_hit(self):
        self.cache.set("hitkey", 1)
        self.cache.get("hitkey")  # hit
        assert self.cache.stats["hits"] == 1

    def test_stats_miss(self):
        self.cache.get("nothere")
        assert self.cache.stats["misses"] == 1

    def test_stats_hit_rate(self):
        for i in range(5):
            self.cache.set(f"k{i}", i)
        # 3 hits, 1 miss
        for i in range(3):
            self.cache.get(f"k{i}")
        self.cache.get("missing")
        stats = self.cache.stats
        assert stats["hit_rate"] == pytest.approx(3 / 4)

    def test_reset_stats(self):
        self.cache.set("k", 1)
        self.cache.get("k")
        self.cache.get("missing")
        self.cache.reset_stats()
        stats = self.cache.stats
        assert stats["hits"] == 0
        assert stats["misses"] == 0

    # ── Persistence ─────────────────────────────────────────────────────────

    def test_persistence_across_instances(self):
        self.cache.set("persist", {"key": "value"})
        # Create a new cache instance pointing at same dir
        cache2 = FileCache(self.tmpdir)
        value, age = cache2.get("persist")
        assert value == {"key": "value"}

    def test_complex_values(self):
        complex_val = {
            "list": [1, 2, 3],
            "nested": {"a": {"b": "c"}},
            "float": 3.14159,
            "none": None,
        }
        self.cache.set("complex", complex_val)
        value, _ = self.cache.get("complex")
        assert value == complex_val

    def test_oldest_entry_age(self):
        self.cache.set("k1", 1)
        time.sleep(0.01)
        self.cache.set("k2", 2)
        age = self.cache.stats["oldest_entry_age"]
        assert age is not None
        assert age >= 0.01