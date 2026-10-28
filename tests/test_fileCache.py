"""Tests for the file-backed cache that ships with the library."""

from datetime import timedelta
from pathlib import Path

import pytest

from lti1p3.cache import FileCache


@pytest.fixture
def cacheDirectory(tmp_path: Path) -> Path:
    return tmp_path / "cache"


def filesIn(directory: Path) -> list[Path]:
    return sorted(directory.iterdir()) if directory.is_dir() else []


class TestFileCache:
    def test_createsTheCacheDirectoryWhenItIsMissing(self, cacheDirectory: Path):
        nested = cacheDirectory / "nested" / "cache"
        FileCache(nested)
        assert nested.is_dir()

    def test_getReturnsDefaultWhenKeyIsMissing(self, cacheDirectory: Path):
        cache = FileCache(cacheDirectory)
        assert cache.get("missing", "default") == "default"
        assert cache.get("missing") is None

    def test_setThenGetReturnsTheStoredValue(self, cacheDirectory: Path):
        cache = FileCache(cacheDirectory)
        assert cache.set("key", {"keys": []}) is True
        assert cache.get("key") == {"keys": []}

    def test_setReplacesAnExistingValue(self, cacheDirectory: Path):
        cache = FileCache(cacheDirectory)
        cache.set("key", "first")
        cache.set("key", "second")
        assert cache.get("key") == "second"

    def test_storedValueIsVisibleToASecondCacheOnTheSameDirectory(self, cacheDirectory: Path):
        FileCache(cacheDirectory).set("key", "value")
        assert FileCache(cacheDirectory).get("key") == "value"

    def test_setLeavesExactlyOneFilePerKey(self, cacheDirectory: Path):
        cache = FileCache(cacheDirectory)
        cache.set("key", "first")
        cache.set("key", "second")
        assert len(filesIn(cacheDirectory)) == 1

    def test_hasReflectsWhetherAKeyIsPresent(self, cacheDirectory: Path):
        cache = FileCache(cacheDirectory)
        assert not cache.has("key")
        cache.set("key", "value")
        assert cache.has("key")

    def test_deleteRemovesAKey(self, cacheDirectory: Path):
        cache = FileCache(cacheDirectory)
        cache.set("key", "value")
        assert cache.delete("key") is True
        assert not cache.has("key")

    def test_deleteOfAMissingKeySucceeds(self, cacheDirectory: Path):
        assert FileCache(cacheDirectory).delete("missing") is True

    def test_clearRemovesAllKeys(self, cacheDirectory: Path):
        cache = FileCache(cacheDirectory)
        cache.set("a", 1)
        cache.set("b", 2)
        assert cache.clear() is True
        assert not cache.has("a")
        assert not cache.has("b")

    def test_itemWithNoTtlNeverExpires(self, cacheDirectory: Path):
        cache = FileCache(cacheDirectory)
        cache.set("key", "value")
        assert cache.has("key")

    def test_itemWithAFutureIntegerTtlIsReadable(self, cacheDirectory: Path):
        cache = FileCache(cacheDirectory)
        cache.set("key", "value", 60)
        assert cache.get("key") == "value"

    def test_itemWithANegativeIntegerTtlIsAlreadyExpired(self, cacheDirectory: Path):
        cache = FileCache(cacheDirectory)
        cache.set("key", "value", -1)
        assert not cache.has("key")
        assert cache.get("key") is None

    def test_itemWithAZeroTtlIsAlreadyExpired(self, cacheDirectory: Path):
        cache = FileCache(cacheDirectory)
        cache.set("key", "value", 0)
        assert not cache.has("key")

    def test_itemWithAFutureTimedeltaTtlIsReadable(self, cacheDirectory: Path):
        cache = FileCache(cacheDirectory)
        cache.set("key", "value", timedelta(seconds=60))
        assert cache.get("key") == "value"

    def test_itemWithAnElapsedTimedeltaTtlIsExpired(self, cacheDirectory: Path):
        cache = FileCache(cacheDirectory)
        cache.set("key", "value", timedelta(seconds=-60))
        assert not cache.has("key")

    def test_readingAnExpiredItemRemovesItsFile(self, cacheDirectory: Path):
        cache = FileCache(cacheDirectory)
        cache.set("key", "value", -1)
        cache.get("key")
        assert filesIn(cacheDirectory) == []

    def test_unreadableCacheFileIsTreatedAsAMiss(self, cacheDirectory: Path):
        cache = FileCache(cacheDirectory)
        cache.set("key", "value")
        filesIn(cacheDirectory)[0].write_text("not a cache record")
        assert cache.get("key", "default") == "default"

    def test_recordWithoutTheExpectedFieldsIsTreatedAsAMiss(self, cacheDirectory: Path):
        cache = FileCache(cacheDirectory)
        cache.set("key", "value")
        filesIn(cacheDirectory)[0].write_text('{"unrelated": true}')
        assert cache.get("key", "default") == "default"

    def test_removeExpiredDeletesOnlyExpiredItemsAndReportsHowMany(self, cacheDirectory: Path):
        cache = FileCache(cacheDirectory)
        cache.set("expired-a", 1, -1)
        cache.set("expired-b", 2, -1)
        cache.set("fresh", 3, 60)
        cache.set("permanent", 4)
        assert cache.removeExpired() == 2
        assert len(filesIn(cacheDirectory)) == 2
        assert cache.get("fresh") == 3
        assert cache.get("permanent") == 4
