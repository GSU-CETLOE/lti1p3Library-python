"""Tests for the client_credentials JWT-bearer token exchange against the fixture token endpoint."""

import json
from urllib.parse import parse_qs

import httpx
import jwt
import pytest

from arrayCache import ArrayCache
from fixturePlatformServer import FixturePlatformServer
from lti1p3.accessToken import AccessTokenService
from lti1p3.exceptions import ServiceException
from lti1p3.registration import Registration, ToolKeyPair
from lti1p3.security import buildJwks, generateKeyPair

ISSUER = "https://example.brightspace.com"
CLIENT_ID = "client-1"


@pytest.fixture(scope="module")
def toolKeyPair() -> ToolKeyPair:
    return generateKeyPair("tool-kid")


def registration(
    server: FixturePlatformServer, toolKeyPair: ToolKeyPair, platformAudience: str | None = None
) -> Registration:
    return Registration(
        ISSUER,
        CLIENT_ID,
        ["deployment-1"],
        ISSUER + "/d2l/lti/authenticate",
        server.baseUrl() + "/token",
        ISSUER + "/d2l/.well-known/jwks",
        [toolKeyPair],
        platformAudience,
    )


def service(httpClient: httpx.Client, cache: ArrayCache | None = None) -> AccessTokenService:
    return AccessTokenService(httpClient, cache or ArrayCache())


def queueTokenResponse(server: FixturePlatformServer, body: dict[str, object], status: int = 200) -> None:
    server.queueResponse("POST", "/token", status, {}, json.dumps(body))


def sentForm(server: FixturePlatformServer, index: int = 0) -> dict[str, str]:
    return {name: values[0] for name, values in parse_qs(server.receivedRequests("POST", "/token")[index].body).items()}


def decodeClientAssertion(assertion: str, toolRegistration: Registration, audience: str) -> dict[str, object]:
    keys = {key["kid"]: jwt.PyJWK.from_dict(key) for key in buildJwks(toolRegistration)["keys"]}
    return jwt.decode(assertion, keys["tool-kid"], algorithms=["RS256"], audience=audience)


class TestAccessTokenService:
    def test_returnsTheAccessTokenFromASuccessfulResponse(self, server: FixturePlatformServer, httpClient: httpx.Client, toolKeyPair: ToolKeyPair):
        queueTokenResponse(server, {"access_token": "token-abc", "token_type": "Bearer", "expires_in": 3600})
        assert service(httpClient).getAccessToken(registration(server, toolKeyPair), ["scope-a"]) == "token-abc"

    def test_sendsTheCorrectGrantTypeClientAssertionTypeAndHeaders(self, server: FixturePlatformServer, httpClient: httpx.Client, toolKeyPair: ToolKeyPair):
        queueTokenResponse(server, {"access_token": "token-abc", "expires_in": 3600})
        service(httpClient).getAccessToken(registration(server, toolKeyPair), ["scope-a", "scope-b"])

        requests = server.receivedRequests("POST", "/token")
        assert len(requests) == 1
        assert requests[0].header("Content-Type") == "application/x-www-form-urlencoded"
        assert requests[0].header("Accept") == "application/json"
        sent = sentForm(server)
        assert sent["grant_type"] == "client_credentials"
        assert sent["client_assertion_type"] == "urn:ietf:params:oauth:client-assertion-type:jwt-bearer"
        assert sent["scope"] == "scope-a scope-b"

    def test_clientAssertionIsARealJwtSignedByTheToolWithCorrectClaims(self, server: FixturePlatformServer, httpClient: httpx.Client, toolKeyPair: ToolKeyPair):
        queueTokenResponse(server, {"access_token": "token-abc", "expires_in": 3600})
        toolRegistration = registration(server, toolKeyPair)
        service(httpClient).getAccessToken(toolRegistration, ["scope-a"])

        claims = decodeClientAssertion(
            sentForm(server)["client_assertion"], toolRegistration, toolRegistration.platformAuthenticationTokenUrl
        )
        assert claims["iss"] == CLIENT_ID
        assert claims["sub"] == CLIENT_ID
        assert claims["aud"] == toolRegistration.platformAuthenticationTokenUrl
        assert isinstance(claims["jti"], str) and claims["jti"]
        iat, exp = claims["iat"], claims["exp"]
        assert isinstance(iat, int) and isinstance(exp, int) and exp > iat

    def test_clientAssertionUsesTheConfiguredAudienceWhenRegistrationSetsOne(self, server: FixturePlatformServer, httpClient: httpx.Client, toolKeyPair: ToolKeyPair):
        queueTokenResponse(server, {"access_token": "token-abc", "expires_in": 3600})
        audience = "https://platform.example.com/api/lti/authorize"
        toolRegistration = registration(server, toolKeyPair, audience)
        service(httpClient).getAccessToken(toolRegistration, ["scope-a"])

        claims = decodeClientAssertion(sentForm(server)["client_assertion"], toolRegistration, audience)
        assert claims["aud"] == audience
        assert claims["aud"] != toolRegistration.platformAuthenticationTokenUrl

    def test_cachesTheAccessTokenAndDoesNotRequestASecondTokenForTheSameScopes(self, server: FixturePlatformServer, httpClient: httpx.Client, toolKeyPair: ToolKeyPair):
        queueTokenResponse(server, {"access_token": "token-abc", "expires_in": 3600})
        tokenService = service(httpClient)
        toolRegistration = registration(server, toolKeyPair)
        tokenService.getAccessToken(toolRegistration, ["scope-a"])
        tokenService.getAccessToken(toolRegistration, ["scope-a"])
        assert len(server.receivedRequests("POST", "/token")) == 1

    def test_requestsANewTokenForADifferentScopeSet(self, server: FixturePlatformServer, httpClient: httpx.Client, toolKeyPair: ToolKeyPair):
        queueTokenResponse(server, {"access_token": "token-abc", "expires_in": 3600})
        queueTokenResponse(server, {"access_token": "token-def", "expires_in": 3600})
        tokenService = service(httpClient)
        toolRegistration = registration(server, toolKeyPair)
        assert tokenService.getAccessToken(toolRegistration, ["scope-a"]) == "token-abc"
        assert tokenService.getAccessToken(toolRegistration, ["scope-b"]) == "token-def"
        assert len(server.receivedRequests("POST", "/token")) == 2

    def test_doesNotCacheBeyondTheTokensExpiryMinusSafetyMargin(self, server: FixturePlatformServer, httpClient: httpx.Client, toolKeyPair: ToolKeyPair):
        queueTokenResponse(server, {"access_token": "token-abc", "expires_in": 30})
        queueTokenResponse(server, {"access_token": "token-def", "expires_in": 3600})
        tokenService = service(httpClient)
        toolRegistration = registration(server, toolKeyPair)
        assert tokenService.getAccessToken(toolRegistration, ["scope-a"]) == "token-abc"
        assert tokenService.getAccessToken(toolRegistration, ["scope-a"]) == "token-def"
        assert len(server.receivedRequests("POST", "/token")) == 2

    def test_assumesAnHourWhenExpiresInIsMissing(self, server: FixturePlatformServer, httpClient: httpx.Client, toolKeyPair: ToolKeyPair):
        queueTokenResponse(server, {"access_token": "token-abc"})
        tokenService = service(httpClient)
        toolRegistration = registration(server, toolKeyPair)
        tokenService.getAccessToken(toolRegistration, ["scope-a"])
        tokenService.getAccessToken(toolRegistration, ["scope-a"])
        assert len(server.receivedRequests("POST", "/token")) == 1

    def test_throwsWhenHttpStatusIsNotSuccessful(self, server: FixturePlatformServer, httpClient: httpx.Client, toolKeyPair: ToolKeyPair):
        queueTokenResponse(server, {"error": "invalid_client"}, 400)
        with pytest.raises(ServiceException, match="HTTP status 400"):
            service(httpClient).getAccessToken(registration(server, toolKeyPair), ["scope-a"])

    def test_throwsWhenResponseBodyIsNotValidJson(self, server: FixturePlatformServer, httpClient: httpx.Client, toolKeyPair: ToolKeyPair):
        server.queueResponse("POST", "/token", 200, {}, "not json")
        with pytest.raises(ServiceException, match="not valid JSON"):
            service(httpClient).getAccessToken(registration(server, toolKeyPair), ["scope-a"])

    def test_throwsWhenAccessTokenFieldIsMissing(self, server: FixturePlatformServer, httpClient: httpx.Client, toolKeyPair: ToolKeyPair):
        queueTokenResponse(server, {"token_type": "Bearer"})
        with pytest.raises(ServiceException, match="access_token"):
            service(httpClient).getAccessToken(registration(server, toolKeyPair), ["scope-a"])
