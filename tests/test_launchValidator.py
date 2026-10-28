"""Tests for the full login initiation to launch round trip, using real signatures and the fixture server."""

import json
import time
from typing import Any
from urllib.parse import parse_qsl, urlsplit

import httpx
import jwt
import pytest

from arrayCache import ArrayCache
from fixturePlatformServer import FixturePlatformServer
from inMemoryRegistrationRepository import InMemoryRegistrationRepository
from lti1p3 import claimUris
from lti1p3.exceptions import (
    InvalidLaunchException,
    InvalidLaunchReason,
    InvalidLoginInitiationException,
    RegistrationNotFoundException,
)
from lti1p3.messages import LtiDeepLinkingRequest, LtiResourceLinkRequest
from lti1p3.oidcLogin import LaunchValidator, LoginInitiationHandler
from lti1p3.registration import Registration
from lti1p3.security import JwksFetcher, JwtValidator, buildJwk, generateKeyPair

ISSUER = "https://example.brightspace.com"
CLIENT_ID = "client-1"
DEPLOYMENT_ID = "deployment-1"
TOOL_REDIRECT_URI = "https://tool.example.com/lti/launch"
INSTRUCTOR = "http://purl.imsglobal.org/vocab/lis/v2/membership#Instructor"


class LaunchHarness:
    """A registered platform whose JWKS the fixture server publishes, plus the two handlers under test."""

    def __init__(self, server: FixturePlatformServer, httpClient: httpx.Client) -> None:
        self.server = server
        self.platformKeyPair = generateKeyPair("platform-kid")
        server.queueResponse("GET", "/jwks", 200, {}, json.dumps({"keys": [buildJwk(self.platformKeyPair)]}))

        self.repository = InMemoryRegistrationRepository()
        self.repository.add(
            Registration(
                ISSUER,
                CLIENT_ID,
                [DEPLOYMENT_ID],
                ISSUER + "/d2l/lti/authenticate",
                ISSUER + "/core/connect/token",
                server.baseUrl() + "/jwks",
                [self.platformKeyPair],
            )
        )
        self.stateCache = ArrayCache()
        self.loginHandler = LoginInitiationHandler(self.repository, self.stateCache)
        jwtValidator = JwtValidator(JwksFetcher(httpClient, ArrayCache()), ArrayCache())
        self.launchValidator = LaunchValidator(self.repository, self.stateCache, jwtValidator)

    def performLoginInitiation(self, deploymentId: str | None = DEPLOYMENT_ID) -> tuple[str, str]:
        """Run login initiation and return the (state, nonce) pair the redirect carries."""
        params = {"iss": ISSUER, "login_hint": "user-1", "target_link_uri": TOOL_REDIRECT_URI}
        if deploymentId is not None:
            params["lti_deployment_id"] = deploymentId
        response = self.loginHandler.handle(params, TOOL_REDIRECT_URI)
        query = dict(parse_qsl(urlsplit(response.headers["Location"]).query))
        return query["state"], query["nonce"]

    def issueToken(self, nonce: str, overrides: dict[str, Any] | None = None) -> str:
        now = int(time.time())
        claims: dict[str, Any] = {
            "iss": ISSUER,
            "aud": CLIENT_ID,
            "exp": now + 300,
            "iat": now,
            "nonce": nonce,
            "sub": "user-1",
            claimUris.MESSAGE_TYPE: "LtiResourceLinkRequest",
            claimUris.VERSION: "1.3.0",
            claimUris.DEPLOYMENT_ID: DEPLOYMENT_ID,
            claimUris.TARGET_LINK_URI: TOOL_REDIRECT_URI,
            claimUris.RESOURCE_LINK: {"id": "resource-1", "title": "A resource"},
            claimUris.ROLES: [INSTRUCTOR],
            **(overrides or {}),
        }
        return jwt.encode(
            claims, self.platformKeyPair.privateKey, algorithm="RS256", headers={"kid": self.platformKeyPair.kid}
        )

    def launch(self, state: str, idToken: str):
        return self.launchValidator.validate({"state": state, "id_token": idToken})

    def assertRejectedWithReason(self, state: str, idToken: str, reason: InvalidLaunchReason) -> None:
        with pytest.raises(InvalidLaunchException) as caught:
            self.launch(state, idToken)
        assert caught.value.reason is reason


@pytest.fixture
def harness(server: FixturePlatformServer, httpClient: httpx.Client) -> LaunchHarness:
    return LaunchHarness(server, httpClient)


class TestSuccessfulLaunches:
    def test_fullLoginToLaunchRoundtripProducesATypedResourceLinkRequest(self, harness: LaunchHarness):
        state, nonce = harness.performLoginInitiation()
        result = harness.launch(state, harness.issueToken(nonce))

        assert isinstance(result, LtiResourceLinkRequest)
        assert result.subject == "user-1"
        assert result.deploymentId == DEPLOYMENT_ID
        assert result.targetLinkUri == TOOL_REDIRECT_URI
        assert result.resourceLink.id == "resource-1"
        assert result.resourceLink.title == "A resource"
        assert result.roles.isInstructor()
        assert not result.roles.isLearner()

    def test_dispatchesToLtiDeepLinkingRequestWhenMessageTypeIsDeepLinking(self, harness: LaunchHarness):
        state, nonce = harness.performLoginInitiation()
        token = harness.issueToken(
            nonce,
            {
                claimUris.MESSAGE_TYPE: "LtiDeepLinkingRequest",
                claimUris.DEEP_LINKING_SETTINGS: {
                    "deep_link_return_url": "https://example.com/deep-link-return",
                    "accept_types": ["ltiResourceLink"],
                },
            },
        )
        result = harness.launch(state, token)
        assert isinstance(result, LtiDeepLinkingRequest)
        assert result.deepLinkingSettings.deepLinkReturnUrl == "https://example.com/deep-link-return"

    def test_anonymousLaunchWithNoSubjectIsAcceptedAndModeledAsNone(self, harness: LaunchHarness):
        state, nonce = harness.performLoginInitiation()
        assert harness.launch(state, harness.issueToken(nonce, {"sub": None})).subject is None

    def test_launchWithoutADeploymentIdAtLoginStillChecksTheRegistration(self, harness: LaunchHarness):
        state, nonce = harness.performLoginInitiation(deploymentId=None)
        assert harness.launch(state, harness.issueToken(nonce)).deploymentId == DEPLOYMENT_ID

    def test_capturesCustomParametersContextAndToolPlatform(self, harness: LaunchHarness):
        state, nonce = harness.performLoginInitiation()
        token = harness.issueToken(
            nonce,
            {
                claimUris.CUSTOM: {"foo": "bar"},
                claimUris.CONTEXT: {"id": "ctx-1", "title": "Course 1", "type": ["CourseSection"]},
                claimUris.TOOL_PLATFORM: {"guid": "platform-guid", "name": "Brightspace"},
            },
        )
        result = harness.launch(state, token)
        assert result.custom == {"foo": "bar"}
        assert result.context is not None and result.context.id == "ctx-1"
        assert result.toolPlatform is not None and result.toolPlatform.guid == "platform-guid"


class TestRejectedLaunches:
    def test_rejectsAMissingState(self, harness: LaunchHarness):
        with pytest.raises(InvalidLoginInitiationException, match='"state"'):
            harness.launchValidator.validate({"id_token": "x"})

    def test_rejectsAMissingIdToken(self, harness: LaunchHarness):
        with pytest.raises(InvalidLoginInitiationException, match='"id_token"'):
            harness.launchValidator.validate({"state": "x"})

    def test_rejectsAnUnknownOrExpiredState(self, harness: LaunchHarness):
        harness.assertRejectedWithReason("bogus-state", harness.issueToken("irrelevant"), InvalidLaunchReason.InvalidState)

    def test_rejectsAReplayedState(self, harness: LaunchHarness):
        state, nonce = harness.performLoginInitiation()
        harness.launch(state, harness.issueToken(nonce))
        harness.assertRejectedWithReason(state, harness.issueToken(nonce), InvalidLaunchReason.InvalidState)

    def test_rejectsWhenTheRegistrationDisappearedAfterLogin(self, harness: LaunchHarness):
        state, nonce = harness.performLoginInitiation()
        harness.repository.registrations.clear()
        with pytest.raises(RegistrationNotFoundException):
            harness.launch(state, harness.issueToken(nonce))

    def test_rejectsATokenWhoseNonceDoesNotMatchTheOneIssuedAtLogin(self, harness: LaunchHarness):
        state, _ = harness.performLoginInitiation()
        harness.assertRejectedWithReason(state, harness.issueToken("a-different-nonce"), InvalidLaunchReason.InvalidState)

    def test_rejectsATokenWhoseTargetLinkUriDoesNotMatchLoginInitiation(self, harness: LaunchHarness):
        state, nonce = harness.performLoginInitiation()
        token = harness.issueToken(nonce, {claimUris.TARGET_LINK_URI: "https://tool.example.com/some-other-link"})
        harness.assertRejectedWithReason(state, token, InvalidLaunchReason.InvalidState)

    def test_rejectsATokenWhoseDeploymentIdDoesNotMatchLoginInitiation(self, harness: LaunchHarness):
        state, nonce = harness.performLoginInitiation()
        token = harness.issueToken(nonce, {claimUris.DEPLOYMENT_ID: "some-other-deployment"})
        harness.assertRejectedWithReason(state, token, InvalidLaunchReason.InvalidState)

    def test_rejectsADeploymentIdTheRegistrationDoesNotKnow(self, harness: LaunchHarness):
        state, nonce = harness.performLoginInitiation(deploymentId=None)
        token = harness.issueToken(nonce, {claimUris.DEPLOYMENT_ID: "unregistered-deployment"})
        harness.assertRejectedWithReason(state, token, InvalidLaunchReason.InvalidDeploymentId)

    def test_rejectsAnUnexpectedMessageType(self, harness: LaunchHarness):
        state, nonce = harness.performLoginInitiation()
        token = harness.issueToken(nonce, {claimUris.MESSAGE_TYPE: "LtiSubmissionReviewRequest"})
        harness.assertRejectedWithReason(state, token, InvalidLaunchReason.UnexpectedMessageType)

    def test_rejectsAnUnsupportedLtiVersion(self, harness: LaunchHarness):
        state, nonce = harness.performLoginInitiation()
        token = harness.issueToken(nonce, {claimUris.VERSION: "1.1.0"})
        harness.assertRejectedWithReason(state, token, InvalidLaunchReason.UnsupportedVersion)

    def test_rejectsATokenMissingTheResourceLinkClaim(self, harness: LaunchHarness):
        state, nonce = harness.performLoginInitiation()
        token = harness.issueToken(nonce, {claimUris.RESOURCE_LINK: None})
        harness.assertRejectedWithReason(state, token, InvalidLaunchReason.MissingRequiredClaim)

    def test_rejectsAnExpiredTokenThroughTheJwtValidator(self, harness: LaunchHarness):
        state, nonce = harness.performLoginInitiation()
        now = int(time.time())
        token = harness.issueToken(nonce, {"exp": now - 1000, "iat": now - 2000})
        harness.assertRejectedWithReason(state, token, InvalidLaunchReason.Expired)
