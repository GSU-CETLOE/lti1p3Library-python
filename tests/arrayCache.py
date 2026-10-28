"""A real in-memory cache with TTL expiry, for tests that need a cache without a backend.

Not a mock of anything under test. It is a genuine, if small, cache that
satisfies the library's CacheInterface.
"""

import time

from lti1p3.cache import CacheTtl, ttlToExpiryTimestamp


class ArrayCache:
    """Dictionary-backed cache that honors TTLs."""

    def __init__(self) -> None:
        self.items: dict[str, tuple[object, float | None]] = {}

    def get(self, key: str, default: object = None) -> object:
        """Return the stored value, or default when the key is missing or expired."""
        return self.items[key][0] if self.has(key) else default

    def set(self, key: str, value: object, ttl: CacheTtl = None) -> bool:
        """Store a value with an optional TTL."""
        self.items[key] = (value, ttlToExpiryTimestamp(ttl))
        return True

    def delete(self, key: str) -> bool:
        """Remove a key; a missing key still counts as success."""
        self.items.pop(key, None)
        return True

    def clear(self) -> bool:
        """Remove every key."""
        self.items.clear()
        return True

    def has(self, key: str) -> bool:
        """Report whether a key is present and not expired, dropping it if it has expired."""
        if key not in self.items:
            return False

        expiresAt = self.items[key][1]
        if expiresAt is not None and expiresAt <= time.time():
            del self.items[key]
            return False

        return True
