"""Tests for handling the platform's OIDC third-party login initiation request."""

from urllib.parse import parse_qsl, urlsplit

import pytest

from arrayCache import ArrayCache
from inMemoryRegistrationRepository import InMemoryRegistrationRepository
from lti1p3.cache import buildCacheKey
from lti1p3.exceptions import InvalidLoginInitiationException, RegistrationNotFoundException
from lti1p3.oidcLogin import LoginInitiationHandler
from lti1p3.registration import Registration, ToolKeyPair
from lti1p3.responses import HttpResponse

ISSUER = "https://example.brightspace.com"
CLIENT_ID = "client-1"
REDIRECT_URI = "https://tool.example.com/lti/launch"


def registration() -> Registration:
    return Registration(
        ISSUER,
        CLIENT_ID,
        ["deployment-1"],
        ISSUER + "/d2l/lti/authenticate",
        ISSUER + "/core/connect/token",
        ISSUER + "/d2l/.well-known/jwks",
        [ToolKeyPair("kid-1", "priv", "pub")],
    )


def repositoryWithRegistration() -> InMemoryRegistrationRepository:
    repository = InMemoryRegistrationRepository()
    repository.add(registration())
    return repository


def handler(
    repository: InMemoryRegistrationRepository | None = None, cache: ArrayCache | None = None
) -> LoginInitiationHandler:
    return LoginInitiationHandler(repository or repositoryWithRegistration(), cache or ArrayCache())


def loginParams(**extra: str) -> dict[str, str]:
    return {"iss": ISSUER, "login_hint": "user-1", "target_link_uri": REDIRECT_URI, **extra}


def queryParamsFromLocation(response: HttpResponse) -> dict[str, str]:
    return dict(parse_qsl(urlsplit(response.headers["Location"]).query))


class TestRedirect:
    def test_buildsARedirectToThePlatformsAuthenticationEndpoint(self):
        response = handler().handle(loginParams(), REDIRECT_URI)

        assert response.statusCode == 302
        assert response.headers["Location"].startswith(ISSUER + "/d2l/lti/authenticate?")
        params = queryParamsFromLocation(response)
        assert params["scope"] == "openid"
        assert params["response_type"] == "id_token"
        assert params["client_id"] == CLIENT_ID
        assert params["redirect_uri"] == REDIRECT_URI
        assert params["login_hint"] == "user-1"
        assert params["response_mode"] == "form_post"
        assert params["prompt"] == "none"
        assert params["state"]
        assert params["nonce"]

    def test_appendsToAnAuthenticationUrlThatAlreadyHasAQueryString(self):
        repository = InMemoryRegistrationRepository()
        repository.add(
            Registration(
                ISSUER,
                CLIENT_ID,
                ["deployment-1"],
                ISSUER + "/authenticate?tenant=1",
                ISSUER + "/token",
                ISSUER + "/jwks",
                [ToolKeyPair("kid-1", "priv", "pub")],
            )
        )
        response = handler(repository).handle(loginParams(), REDIRECT_URI)
        assert response.headers["Location"].startswith(ISSUER + "/authenticate?tenant=1&")

    def test_passesThroughLtiMessageHintWhenPresent(self):
        response = handler().handle(loginParams(lti_message_hint="hint-value"), REDIRECT_URI)
        assert queryParamsFromLocation(response)["lti_message_hint"] == "hint-value"

    def test_omitsLtiMessageHintWhenAbsent(self):
        assert "lti_message_hint" not in queryParamsFromLocation(handler().handle(loginParams(), REDIRECT_URI))

    def test_stateAndNonceDifferBetweenRequests(self):
        loginHandler = handler()
        first = queryParamsFromLocation(loginHandler.handle(loginParams(), REDIRECT_URI))
        second = queryParamsFromLocation(loginHandler.handle(loginParams(), REDIRECT_URI))
        assert first["state"] != second["state"]
        assert first["nonce"] != second["nonce"]


class TestLoginState:
    def test_storesStateNonceTargetLinkUriAndDeploymentIdInTheCache(self):
        cache = ArrayCache()
        response = handler(cache=cache).handle(loginParams(lti_deployment_id="deployment-1"), REDIRECT_URI)

        params = queryParamsFromLocation(response)
        stored = cache.get(buildCacheKey("login-state", params["state"]))
        assert stored == {
            "nonce": params["nonce"],
            "target_link_uri": REDIRECT_URI,
            "deployment_id": "deployment-1",
            "issuer": ISSUER,
            "client_id": CLIENT_ID,
        }

    def test_deploymentIdIsNoneInCacheWhenNotSent(self):
        cache = ArrayCache()
        response = handler(cache=cache).handle(loginParams(), REDIRECT_URI)
        stored = cache.get(buildCacheKey("login-state", queryParamsFromLocation(response)["state"]))
        assert isinstance(stored, dict)
        assert stored["deployment_id"] is None

    def test_loginStateExpiresAfterTheConfiguredTtl(self):
        cache = ArrayCache()
        loginHandler = LoginInitiationHandler(repositoryWithRegistration(), cache, stateTtlSeconds=-1)
        response = loginHandler.handle(loginParams(), REDIRECT_URI)
        assert cache.get(buildCacheKey("login-state", queryParamsFromLocation(response)["state"])) is None


class TestValidation:
    def test_throwsWhenIssIsMissing(self):
        with pytest.raises(InvalidLoginInitiationException, match='"iss"'):
            handler().handle({"login_hint": "user-1", "target_link_uri": REDIRECT_URI}, REDIRECT_URI)

    def test_throwsWhenLoginHintIsMissing(self):
        with pytest.raises(InvalidLoginInitiationException, match='"login_hint"'):
            handler().handle({"iss": ISSUER, "target_link_uri": REDIRECT_URI}, REDIRECT_URI)

    def test_throwsWhenTargetLinkUriIsMissing(self):
        with pytest.raises(InvalidLoginInitiationException, match='"target_link_uri"'):
            handler().handle({"iss": ISSUER, "login_hint": "user-1"}, REDIRECT_URI)

    def test_throwsWhenARequiredParameterIsNotAString(self):
        with pytest.raises(InvalidLoginInitiationException, match='"iss"'):
            handler().handle({**loginParams(), "iss": ["a", "b"]}, REDIRECT_URI)

    def test_throwsWhenTargetLinkUriIsPlainHttpToARemoteHost(self):
        with pytest.raises(InvalidLoginInitiationException, match="target_link_uri"):
            handler().handle(loginParams(target_link_uri="http://tool.example.com/lti/launch"), REDIRECT_URI)

    def test_throwsWhenRedirectUriIsPlainHttpToARemoteHost(self):
        with pytest.raises(InvalidLoginInitiationException, match="redirect_uri"):
            handler().handle(loginParams(), "http://tool.example.com/lti/launch")

    def test_throwsWhenNoRegistrationMatches(self):
        with pytest.raises(RegistrationNotFoundException, match="https://unknown.example.com"):
            handler(InMemoryRegistrationRepository()).handle(loginParams(iss="https://unknown.example.com"), REDIRECT_URI)

    def test_errorNamesTheClientIdWhenOneWasSent(self):
        with pytest.raises(RegistrationNotFoundException, match='client_id "other"'):
            handler().handle(loginParams(client_id="other"), REDIRECT_URI)
