"""Tests for fetching a platform's JWKS over real HTTP from the fixture server."""

import json

import httpx
import jwt
import pytest

from arrayCache import ArrayCache
from fixturePlatformServer import FixturePlatformServer
from lti1p3.exceptions import ServiceException
from lti1p3.security import JwksFetcher, buildJwk, generateKeyPair

BOGUS_OCT_JWK = {"kty": "oct", "alg": "HS256", "kid": "oct-kid", "k": "c2VjcmV0"}


def fetcher(httpClient: httpx.Client, cache: ArrayCache | None = None, ttl: int = 3600) -> JwksFetcher:
    return JwksFetcher(httpClient, cache if cache is not None else ArrayCache(), ttl)


def publish(server: FixturePlatformServer, *jwks: dict[str, str], status: int = 200) -> None:
    server.queueResponse("GET", "/jwks", status, {"Content-Type": "application/json"}, json.dumps({"keys": list(jwks)}))


class TestJwksFetcher:
    def test_fetchesAndParsesARealJwksAndTheKeyVerifiesARealSignedToken(
        self, server: FixturePlatformServer, httpClient: httpx.Client
    ):
        keyPair = generateKeyPair("kid-1")
        publish(server, buildJwk(keyPair))

        keySet = fetcher(httpClient).fetch(server.baseUrl() + "/jwks")

        assert "kid-1" in keySet
        token = jwt.encode({"sub": "user-1"}, keyPair.privateKey, algorithm="RS256", headers={"kid": "kid-1"})
        assert jwt.decode(token, keySet["kid-1"], algorithms=["RS256"])["sub"] == "user-1"

    def test_sendsAnAcceptJsonHeader(self, server: FixturePlatformServer, httpClient: httpx.Client):
        publish(server, buildJwk(generateKeyPair("kid-1")))
        fetcher(httpClient).fetch(server.baseUrl() + "/jwks")
        requests = server.receivedRequests("GET", "/jwks")
        assert len(requests) == 1
        assert requests[0].header("Accept") == "application/json"

    def test_cachesTheDocumentAndDoesNotIssueASecondHttpRequestWithinTtl(
        self, server: FixturePlatformServer, httpClient: httpx.Client
    ):
        publish(server, buildJwk(generateKeyPair("kid-1")))
        jwksFetcher = fetcher(httpClient)
        jwksFetcher.fetch(server.baseUrl() + "/jwks")
        jwksFetcher.fetch(server.baseUrl() + "/jwks")
        assert len(server.receivedRequests("GET", "/jwks")) == 1

    def test_refetchesAfterTheCacheEntryExpires(self, server: FixturePlatformServer, httpClient: httpx.Client):
        publish(server, buildJwk(generateKeyPair("kid-1")))
        jwksFetcher = fetcher(httpClient, ttl=0)
        jwksFetcher.fetch(server.baseUrl() + "/jwks")
        jwksFetcher.fetch(server.baseUrl() + "/jwks")
        assert len(server.receivedRequests("GET", "/jwks")) == 2

    def test_throwsWhenHttpStatusIsNotSuccessful(self, server: FixturePlatformServer, httpClient: httpx.Client):
        server.queueResponse("GET", "/jwks", 500, {}, "internal error")
        with pytest.raises(ServiceException, match="HTTP status 500"):
            fetcher(httpClient).fetch(server.baseUrl() + "/jwks")

    def test_throwsWhenResponseBodyIsNotValidJson(self, server: FixturePlatformServer, httpClient: httpx.Client):
        server.queueResponse("GET", "/jwks", 200, {}, "not json")
        with pytest.raises(ServiceException, match="not valid JSON"):
            fetcher(httpClient).fetch(server.baseUrl() + "/jwks")

    def test_throwsWhenResponseHasNoKeysArray(self, server: FixturePlatformServer, httpClient: httpx.Client):
        server.queueResponse("GET", "/jwks", 200, {}, "{}")
        with pytest.raises(ServiceException, match='did not contain a "keys" array'):
            fetcher(httpClient).fetch(server.baseUrl() + "/jwks")

    def test_filtersOutNonRsaKeysAndKeepsAcceptableOnes(self, server: FixturePlatformServer, httpClient: httpx.Client):
        publish(server, buildJwk(generateKeyPair("rsa-kid")), BOGUS_OCT_JWK)
        keySet = fetcher(httpClient).fetch(server.baseUrl() + "/jwks")
        assert "rsa-kid" in keySet
        assert "oct-kid" not in keySet

    def test_filtersOutRsaKeysDeclaringAnotherAlgorithm(self, server: FixturePlatformServer, httpClient: httpx.Client):
        rs512 = {**buildJwk(generateKeyPair("rs512-kid")), "alg": "RS512"}
        publish(server, buildJwk(generateKeyPair("rsa-kid")), rs512)
        keySet = fetcher(httpClient).fetch(server.baseUrl() + "/jwks")
        assert set(keySet) == {"rsa-kid"}

    def test_throwsWhenNoAcceptableRsaKeysArePresent(self, server: FixturePlatformServer, httpClient: httpx.Client):
        publish(server, BOGUS_OCT_JWK)
        with pytest.raises(ServiceException, match="did not contain any supported RSA/RS256 keys"):
            fetcher(httpClient).fetch(server.baseUrl() + "/jwks")

    def test_throwsWhenAnRsaKeyCannotBeParsed(self, server: FixturePlatformServer, httpClient: httpx.Client):
        publish(server, {"kty": "RSA", "kid": "broken", "n": "!!!", "e": "AQAB"})
        with pytest.raises(ServiceException, match="could not be parsed"):
            fetcher(httpClient).fetch(server.baseUrl() + "/jwks")
