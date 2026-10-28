"""Obtains platform access tokens for calling AGS and NRPS, via the client_credentials JWT-bearer grant."""

import json
import secrets
import time
from collections.abc import Sequence

import httpx
import jwt

from lti1p3.cache import CacheInterface, buildCacheKey
from lti1p3.claims import jsonObject
from lti1p3.exceptions import ServiceException
from lti1p3.registration import Registration


class AccessTokenService:
    """Requests OAuth2 access tokens per the 1EdTech Security Framework 1.0, caching them until shortly before expiry.

    Tokens are cached per issuer, client_id, and scope set.
    """

    CLIENT_ASSERTION_TYPE = "urn:ietf:params:oauth:client-assertion-type:jwt-bearer"
    CLIENT_ASSERTION_TTL_SECONDS = 60
    DEFAULT_TOKEN_TTL_SECONDS = 3600
    CACHE_SAFETY_MARGIN_SECONDS = 60

    def __init__(self, httpClient: httpx.Client, cache: CacheInterface):
        self.httpClient = httpClient
        self.cache = cache

    def getAccessToken(self, registration: Registration, scopes: Sequence[str]) -> str:
        """Return a bearer token granting the scopes, from cache when one is still fresh."""
        scope = " ".join(scopes)
        cacheKey = buildCacheKey("access-token", registration.issuer, registration.clientId, scope)

        cached = self.cache.get(cacheKey)
        if isinstance(cached, str):
            return cached

        accessToken, ttl = self._requestAccessToken(registration, scope)
        self.cache.set(cacheKey, accessToken, ttl)
        return accessToken

    def _requestAccessToken(self, registration: Registration, scope: str) -> tuple[str, int]:
        response = self.httpClient.post(
            registration.platformAuthenticationTokenUrl,
            data={
                "grant_type": "client_credentials",
                "client_assertion_type": self.CLIENT_ASSERTION_TYPE,
                "client_assertion": self._buildClientAssertion(registration),
                "scope": scope,
            },
            headers={"Accept": "application/json"},
        )

        if response.status_code != 200:
            raise ServiceException(
                f'Access token request to "{registration.platformAuthenticationTokenUrl}" '
                f"failed with HTTP status {response.status_code}."
            )

        try:
            decoded = jsonObject(json.loads(response.text))
        except ValueError as error:
            raise ServiceException("Access token response was not valid JSON.") from error

        accessToken = decoded.get("access_token") if decoded is not None else None
        if not isinstance(accessToken, str):
            raise ServiceException('Access token response did not contain an "access_token".')

        expiresIn = decoded.get("expires_in") if decoded is not None else None
        if not isinstance(expiresIn, int) or isinstance(expiresIn, bool):
            expiresIn = self.DEFAULT_TOKEN_TTL_SECONDS

        return accessToken, max(0, expiresIn - self.CACHE_SAFETY_MARGIN_SECONDS)

    def _buildClientAssertion(self, registration: Registration) -> str:
        now = int(time.time())
        claims = {
            "iss": registration.clientId,
            "sub": registration.clientId,
            "aud": registration.accessTokenAudience(),
            "iat": now,
            "exp": now + self.CLIENT_ASSERTION_TTL_SECONDS,
            "jti": secrets.token_hex(16),
        }
        signingKey = registration.activeSigningKey()
        return jwt.encode(claims, signingKey.privateKey, algorithm="RS256", headers={"kid": signingKey.kid})
