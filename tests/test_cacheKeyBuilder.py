"""Tests for building backend-safe cache keys from raw key material."""

from lti1p3.cache import buildCacheKey

FORBIDDEN_CHARACTERS = "{}()/\\@:"


class TestBuildCacheKey:
    def test_buildsAConsistentKeyForTheSameInputs(self):
        first = buildCacheKey("jwks", "https://example.brightspace.com/d2l/.well-known/jwks")
        second = buildCacheKey("jwks", "https://example.brightspace.com/d2l/.well-known/jwks")
        assert first == second

    def test_differentPartsProduceDifferentKeys(self):
        assert buildCacheKey("jwks", "https://one.brightspace.com/jwks") != buildCacheKey(
            "jwks", "https://two.brightspace.com/jwks"
        )

    def test_orderOfPartsMatters(self):
        assert buildCacheKey("token", "issuer-a", "client-b") != buildCacheKey("token", "client-b", "issuer-a")

    def test_differentNamespacesProduceDifferentKeysForTheSameParts(self):
        assert buildCacheKey("jwks", "shared-part") != buildCacheKey("nonce", "shared-part")

    def test_keyContainsNoCharactersForbiddenByCommonCacheBackends(self):
        key = buildCacheKey("jwks", "https://example.brightspace.com:443/d2l/.well-known/jwks", "client@example.com")
        for character in FORBIDDEN_CHARACTERS:
            assert character not in key

    def test_keyIncludesASanitizedNamespaceForReadability(self):
        assert buildCacheKey("jwks", "anything").startswith("lti1p3_jwks_")

    def test_namespaceIsSanitizedWhenItContainsForbiddenCharacters(self):
        key = buildCacheKey("jwks:platform", "anything")
        for character in FORBIDDEN_CHARACTERS:
            assert character not in key
