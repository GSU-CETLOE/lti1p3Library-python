"""Tests for the in-memory cache used by the test suite."""

from datetime import timedelta

from arrayCache import ArrayCache


class TestArrayCache:
    def test_getReturnsDefaultWhenKeyIsMissing(self):
        cache = ArrayCache()
        assert cache.get("missing", "default") == "default"
        assert cache.get("missing") is None

    def test_setThenGetReturnsTheStoredValue(self):
        cache = ArrayCache()
        assert cache.set("key", {"keys": []}) is True
        assert cache.get("key") == {"keys": []}

    def test_hasReflectsWhetherAKeyIsPresent(self):
        cache = ArrayCache()
        assert not cache.has("key")
        cache.set("key", "value")
        assert cache.has("key")

    def test_deleteRemovesAKey(self):
        cache = ArrayCache()
        cache.set("key", "value")
        assert cache.delete("key") is True
        assert not cache.has("key")

    def test_clearRemovesAllKeys(self):
        cache = ArrayCache()
        cache.set("a", 1)
        cache.set("b", 2)
        assert cache.clear() is True
        assert not cache.has("a")
        assert not cache.has("b")

    def test_itemWithAnElapsedIntegerTtlIsExpired(self):
        cache = ArrayCache()
        cache.set("key", "value", -1)
        assert not cache.has("key")
        assert cache.get("key") is None

    def test_itemWithNoTtlNeverExpires(self):
        cache = ArrayCache()
        cache.set("key", "value")
        assert cache.has("key")

    def test_itemWithAnElapsedTimedeltaTtlIsExpired(self):
        cache = ArrayCache()
        cache.set("key", "value", timedelta(seconds=-1))
        assert not cache.has("key")
