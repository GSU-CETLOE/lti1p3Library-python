"""The cache contract the library needs, a key builder, and a file-backed implementation.

Login initiation and the launch arrive as two separate HTTP requests, often
handled by different processes, so the cache handed to this library has to
outlive a single request. Any object with the five methods of CacheInterface
works: a Redis or Memcached wrapper, Django's cache, or the FileCache below.
"""

import hashlib
import json
import os
import re
import secrets
import time
from datetime import timedelta
from pathlib import Path
from typing import Protocol

type CacheTtl = int | timedelta | None


class CacheInterface(Protocol):
    """What the library needs from a cache. Values are JSON-serializable: strings, numbers, bools, dicts, lists."""

    def get(self, key: str, default: object = None) -> object:
        """Return the stored value, or default when the key is missing or expired."""
        ...

    def set(self, key: str, value: object, ttl: CacheTtl = None) -> bool:
        """Store a value. None keeps it until deleted; zero or negative stores it already expired."""
        ...

    def delete(self, key: str) -> bool:
        """Remove a key. Deleting a key that isn't there counts as success."""
        ...

    def has(self, key: str) -> bool:
        """Report whether a key is present and not expired."""
        ...

    def clear(self) -> bool:
        """Remove every key."""
        ...


def buildCacheKey(namespace: str, *parts: str) -> str:
    """Build a backend-safe cache key from arbitrary parts.

    Common cache backends forbid characters such as {}()/\\@: in keys, and
    the natural key material here (issuer URLs, JWKS URLs, client IDs, OAuth2
    scopes) routinely contains them. Every cache consumer in the library
    builds its keys through here rather than concatenating raw values.
    """
    sanitizedNamespace = re.sub(r"[^A-Za-z0-9_.-]", "_", namespace)
    digest = hashlib.sha256("\0".join(parts).encode("utf-8")).hexdigest()
    return f"lti1p3_{sanitizedNamespace}_{digest}"


def ttlToExpiryTimestamp(ttl: CacheTtl, now: float | None = None) -> float | None:
    """Convert a TTL into the Unix timestamp at which an item expires, or None when it never does."""
    if ttl is None:
        return None

    start = time.time() if now is None else now
    if isinstance(ttl, timedelta):
        return start + ttl.total_seconds()

    return start + ttl


class FileCache:
    """A file-backed cache, one JSON file per key, for applications without a cache backend.

    Keep the directory private and outside the web root; it is created with
    mode 0700. Expired items are only removed when read again or when
    removeExpired() runs, so schedule that call to keep the directory small.
    """

    def __init__(self, directory: str | Path) -> None:
        """Use the given directory for cache files, creating it with mode 0700 if missing."""
        self.directory = Path(directory)
        self.directory.mkdir(mode=0o700, parents=True, exist_ok=True)

    def get(self, key: str, default: object = None) -> object:
        """Return the stored value, or default when the key is missing or expired."""
        record = self._readRecord(key)
        return record["value"] if record is not None else default

    def set(self, key: str, value: object, ttl: CacheTtl = None) -> bool:
        """Store a value. None keeps it until deleted; zero or negative stores it already expired."""
        record = {"value": value, "expiresAt": ttlToExpiryTimestamp(ttl)}
        return self._writeAtomically(self._pathFor(key), json.dumps(record))

    def delete(self, key: str) -> bool:
        """Remove a key. Deleting a key that isn't there counts as success."""
        self._removeFile(self._pathFor(key))
        return True

    def has(self, key: str) -> bool:
        """Report whether a key is present and not expired."""
        return self._readRecord(key) is not None

    def clear(self) -> bool:
        """Remove every key in this cache directory."""
        for path in self._cacheFiles():
            self._removeFile(path)
        return True

    def removeExpired(self) -> int:
        """Delete the files of expired items and return how many were removed.

        A nonce is never read again unless a launch is replayed, so every
        launch leaves one small file behind. Call this from a scheduled job.
        """
        removed = 0
        for path in self._cacheFiles():
            record = self._readRecordFile(path)
            if record is not None and self._hasExpired(record):
                self._removeFile(path)
                removed += 1
        return removed

    def _readRecord(self, key: str) -> dict[str, object] | None:
        """Return the live record for a key, deleting its file if it has expired."""
        path = self._pathFor(key)
        record = self._readRecordFile(path)
        if record is None:
            return None

        if self._hasExpired(record):
            self._removeFile(path)
            return None

        return record

    def _readRecordFile(self, path: Path) -> dict[str, object] | None:
        """Parse one cache file whether or not it has expired; None when missing or not a record."""
        try:
            contents = path.read_text(encoding="utf-8")
        except OSError:
            # Another process can delete the file between listing and reading; that is a miss.
            return None

        try:
            record = json.loads(contents)
        except ValueError:
            return None

        if not isinstance(record, dict) or "value" not in record or "expiresAt" not in record:
            return None

        return record

    def _hasExpired(self, record: dict[str, object]) -> bool:
        expiresAt = record["expiresAt"]
        return isinstance(expiresAt, (int, float)) and expiresAt <= time.time()

    def _writeAtomically(self, path: Path, contents: str) -> bool:
        """Write to a temporary file and rename it into place, so readers never see a partial file."""
        temporaryPath = path.with_name(f"{path.name}.{secrets.token_hex(8)}.tmp")
        try:
            temporaryPath.write_text(contents, encoding="utf-8")
            os.replace(temporaryPath, path)
        except OSError:
            self._removeFile(temporaryPath)
            return False
        return True

    def _removeFile(self, path: Path) -> None:
        """Delete a cache file if it is still there. Two requests may race; the file being gone is the goal."""
        try:
            path.unlink()
        except FileNotFoundError:
            pass

    def _cacheFiles(self) -> list[Path]:
        return list(self.directory.glob("*.cache"))

    def _pathFor(self, key: str) -> Path:
        return self.directory / (hashlib.sha256(key.encode("utf-8")).hexdigest() + ".cache")
