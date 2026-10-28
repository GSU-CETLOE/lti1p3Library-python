"""Tests for the platform registration value object and its validation rules."""

from collections.abc import Sequence

import pytest

from lti1p3.exceptions import InvalidRegistrationException
from lti1p3.registration import Registration, ToolKeyPair

ISSUER = "https://example.brightspace.com"
LOGIN_URL = "https://example.brightspace.com/d2l/lti/authenticate"
TOKEN_URL = "https://example.brightspace.com/core/connect/token"
JWKS_URL = "https://example.brightspace.com/d2l/.well-known/jwks"


def keyPair(kid: str = "kid-1", activeForSigning: bool = True) -> ToolKeyPair:
    return ToolKeyPair(kid, "priv-" + kid, "pub-" + kid, activeForSigning)


def makeRegistration(
    issuer: str = ISSUER,
    clientId: str = "client-1",
    deploymentIds: Sequence[str] = ("deployment-1",),
    loginUrl: str = LOGIN_URL,
    tokenUrl: str = TOKEN_URL,
    jwksUrl: str = JWKS_URL,
    toolKeyPairs: Sequence[ToolKeyPair] | None = None,
    platformAudience: str | None = None,
) -> Registration:
    return Registration(
        issuer,
        clientId,
        deploymentIds,
        loginUrl,
        tokenUrl,
        jwksUrl,
        toolKeyPairs if toolKeyPairs is not None else [keyPair()],
        platformAudience,
    )


class TestPlatformAudience:
    def test_platformAudienceDefaultsToTheTokenUrl(self):
        registration = makeRegistration()
        assert registration.platformAudience is None
        assert registration.accessTokenAudience() == TOKEN_URL

    def test_configuredPlatformAudienceOverridesTheTokenUrl(self):
        registration = makeRegistration(platformAudience="https://platform.example.com/api/lti/authorize")
        assert registration.platformAudience == "https://platform.example.com/api/lti/authorize"
        assert registration.accessTokenAudience() == "https://platform.example.com/api/lti/authorize"

    def test_platformAudienceNeedNotBeAUrl(self):
        assert makeRegistration(platformAudience="platform-audience-identifier").accessTokenAudience() == (
            "platform-audience-identifier"
        )

    def test_rejectsBlankPlatformAudience(self):
        with pytest.raises(InvalidRegistrationException, match="platformAudience must not be empty"):
            makeRegistration(platformAudience="   ")


class TestConstruction:
    def test_constructsWithValidValues(self):
        registration = makeRegistration()
        assert registration.issuer == ISSUER
        assert registration.clientId == "client-1"
        assert registration.deploymentIds == ("deployment-1",)
        assert registration.platformAuthenticationLoginUrl == LOGIN_URL
        assert registration.platformAuthenticationTokenUrl == TOKEN_URL
        assert registration.platformJwksUrl == JWKS_URL
        assert len(registration.toolKeyPairs) == 1

    def test_listsAreStoredAsImmutableTuples(self):
        registration = makeRegistration(deploymentIds=["dep-a", "dep-b"], toolKeyPairs=[keyPair()])
        assert registration.deploymentIds == ("dep-a", "dep-b")
        assert isinstance(registration.toolKeyPairs, tuple)

    def test_rejectsEmptyIssuer(self):
        with pytest.raises(InvalidRegistrationException, match="issuer must not be empty"):
            makeRegistration(issuer="")

    def test_rejectsEmptyClientId(self):
        with pytest.raises(InvalidRegistrationException, match="clientId must not be empty"):
            makeRegistration(clientId="")

    def test_rejectsEmptyDeploymentIds(self):
        with pytest.raises(InvalidRegistrationException, match="at least one deployment id"):
            makeRegistration(deploymentIds=[])

    def test_rejectsBlankDeploymentId(self):
        with pytest.raises(InvalidRegistrationException, match="deployment ids must be non-empty strings"):
            makeRegistration(deploymentIds=["deployment-1", "   "])

    def test_rejectsEmptyLoginUrl(self):
        with pytest.raises(InvalidRegistrationException, match="platformAuthenticationLoginUrl must not be empty"):
            makeRegistration(loginUrl="")

    def test_rejectsEmptyTokenUrl(self):
        with pytest.raises(InvalidRegistrationException, match="platformAuthenticationTokenUrl must not be empty"):
            makeRegistration(tokenUrl="")

    def test_rejectsEmptyJwksUrl(self):
        with pytest.raises(InvalidRegistrationException, match="platformJwksUrl must not be empty"):
            makeRegistration(jwksUrl="")

    def test_rejectsAPlainHttpLoginUrlToARemoteHost(self):
        with pytest.raises(InvalidRegistrationException, match="platformAuthenticationLoginUrl must use https"):
            makeRegistration(loginUrl="http://example.brightspace.com/d2l/lti/authenticate")

    def test_rejectsAPlainHttpTokenUrlToARemoteHost(self):
        with pytest.raises(InvalidRegistrationException, match="platformAuthenticationTokenUrl must use https"):
            makeRegistration(tokenUrl="http://example.brightspace.com/core/connect/token")

    def test_rejectsAPlainHttpJwksUrlToARemoteHost(self):
        with pytest.raises(InvalidRegistrationException, match="platformJwksUrl must use https"):
            makeRegistration(jwksUrl="http://example.brightspace.com/d2l/.well-known/jwks")

    def test_allowsPlainHttpToLoopbackForLocalDevAndTesting(self):
        registration = makeRegistration(
            loginUrl="http://127.0.0.1:8080/auth",
            tokenUrl="http://127.0.0.1:8080/token",
            jwksUrl="http://127.0.0.1:8080/jwks",
        )
        assert registration.platformJwksUrl == "http://127.0.0.1:8080/jwks"

    def test_rejectsEmptyToolKeyPairs(self):
        with pytest.raises(InvalidRegistrationException, match="at least one tool key pair"):
            makeRegistration(toolKeyPairs=[])

    def test_rejectsZeroActiveSigningKeys(self):
        with pytest.raises(InvalidRegistrationException, match="exactly one active signing key, 0 given"):
            makeRegistration(toolKeyPairs=[keyPair("kid-1", False)])

    def test_rejectsMultipleActiveSigningKeys(self):
        with pytest.raises(InvalidRegistrationException, match="exactly one active signing key, 2 given"):
            makeRegistration(toolKeyPairs=[keyPair("kid-1", True), keyPair("kid-2", True)])

    def test_allowsRotatedInactiveKeyAlongsideActiveKey(self):
        registration = makeRegistration(toolKeyPairs=[keyPair("old-kid", False), keyPair("new-kid", True)])
        assert len(registration.toolKeyPairs) == 2


class TestLookups:
    def test_hasDeploymentReturnsTrueForKnownDeployment(self):
        registration = makeRegistration(deploymentIds=["dep-a", "dep-b"])
        assert registration.hasDeployment("dep-a")
        assert registration.hasDeployment("dep-b")

    def test_hasDeploymentReturnsFalseForUnknownDeployment(self):
        assert not makeRegistration(deploymentIds=["dep-a"]).hasDeployment("dep-z")

    def test_activeSigningKeyReturnsTheActiveKey(self):
        registration = makeRegistration(toolKeyPairs=[keyPair("old-kid", False), keyPair("new-kid", True)])
        assert registration.activeSigningKey().kid == "new-kid"

    def test_findKeyPairByKidFindsActiveAndInactiveKeys(self):
        registration = makeRegistration(toolKeyPairs=[keyPair("old-kid", False), keyPair("new-kid", True)])
        oldKey = registration.findKeyPairByKid("old-kid")
        newKey = registration.findKeyPairByKid("new-kid")
        assert oldKey is not None and oldKey.kid == "old-kid"
        assert newKey is not None and newKey.kid == "new-kid"

    def test_findKeyPairByKidReturnsNoneForUnknownKid(self):
        assert makeRegistration().findKeyPairByKid("unknown") is None
