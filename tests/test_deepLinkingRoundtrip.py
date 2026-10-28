"""The whole Deep Linking flow: login, launch, build a signed response, render the form post, verify it."""

import json
import time
from urllib.parse import parse_qsl, urlsplit

import httpx
import jwt

from arrayCache import ArrayCache
from fixturePlatformServer import FixturePlatformServer
from inMemoryRegistrationRepository import InMemoryRegistrationRepository
from lti1p3 import claimUris
from lti1p3.deepLinking import LtiDeepLinkingResponse, LtiResourceLinkContentItem
from lti1p3.messages import LtiDeepLinkingRequest
from lti1p3.oidcLogin import LaunchValidator, LoginInitiationHandler
from lti1p3.registration import Registration
from lti1p3.responses import renderFormPost
from lti1p3.security import JwksFetcher, JwtValidator, buildJwk, buildJwks, generateKeyPair

ISSUER = "https://example.brightspace.com"
CLIENT_ID = "client-1"
DEPLOYMENT_ID = "deployment-1"
TOOL_DEEP_LINK_URI = "https://tool.example.com/lti/deep-link"
PLATFORM_DEEP_LINK_RETURN_URL = "https://example.brightspace.com/deep-link-return"


class TestDeepLinkingRoundtrip:
    def test_fullDeepLinkingRoundtripProducesAValidSignedFormPost(
        self, server: FixturePlatformServer, httpClient: httpx.Client
    ):
        # The fixture server plays the platform and publishes the platform's signing key at /jwks.
        platformKeyPair = generateKeyPair("platform-kid")
        toolKeyPair = generateKeyPair("tool-kid")
        server.queueResponse("GET", "/jwks", 200, {}, json.dumps({"keys": [buildJwk(platformKeyPair)]}))

        registration = Registration(
            ISSUER,
            CLIENT_ID,
            [DEPLOYMENT_ID],
            ISSUER + "/d2l/lti/authenticate",
            ISSUER + "/core/connect/token",
            server.baseUrl() + "/jwks",
            [toolKeyPair],
        )
        repository = InMemoryRegistrationRepository()
        repository.add(registration)
        stateCache = ArrayCache()

        # Step 1: login initiation.
        redirect = LoginInitiationHandler(repository, stateCache).handle(
            {
                "iss": ISSUER,
                "login_hint": "user-1",
                "target_link_uri": TOOL_DEEP_LINK_URI,
                "lti_deployment_id": DEPLOYMENT_ID,
            },
            TOOL_DEEP_LINK_URI,
        )
        authParams = dict(parse_qsl(urlsplit(redirect.headers["Location"]).query))

        # Step 2: the platform issues a real signed Deep Linking request id_token.
        now = int(time.time())
        idToken = jwt.encode(
            {
                "iss": ISSUER,
                "aud": CLIENT_ID,
                "exp": now + 300,
                "iat": now,
                "nonce": authParams["nonce"],
                "sub": "instructor-1",
                claimUris.MESSAGE_TYPE: "LtiDeepLinkingRequest",
                claimUris.VERSION: "1.3.0",
                claimUris.DEPLOYMENT_ID: DEPLOYMENT_ID,
                claimUris.TARGET_LINK_URI: TOOL_DEEP_LINK_URI,
                claimUris.DEEP_LINKING_SETTINGS: {
                    "deep_link_return_url": PLATFORM_DEEP_LINK_RETURN_URL,
                    "accept_types": ["ltiResourceLink"],
                    "accept_multiple": False,
                    "data": "roundtrip-correlation-id",
                },
            },
            platformKeyPair.privateKey,
            algorithm="RS256",
            headers={"kid": platformKeyPair.kid},
        )

        # Step 3: the tool validates the launch.
        jwtValidator = JwtValidator(JwksFetcher(httpClient, ArrayCache()), ArrayCache())
        request = LaunchValidator(repository, stateCache, jwtValidator).validate(
            {"state": authParams["state"], "id_token": idToken}
        )
        assert isinstance(request, LtiDeepLinkingRequest)
        assert request.deepLinkingSettings.deepLinkReturnUrl == PLATFORM_DEEP_LINK_RETURN_URL

        # Step 4: the tool builds and signs the Deep Linking response.
        responseJwt = LtiDeepLinkingResponse(
            registration,
            request.deploymentId,
            ISSUER,
            [LtiResourceLinkContentItem(url="https://tool.example.com/launch/selected-item", title="Selected item")],
            data=request.deepLinkingSettings.data,
        ).toJwt()

        # Step 5: render the auto-submitting form post back to the platform.
        html = renderFormPost(request.deepLinkingSettings.deepLinkReturnUrl, {"JWT": responseJwt}).body
        assert f'action="{PLATFORM_DEEP_LINK_RETURN_URL}"' in html
        assert 'name="JWT"' in html
        assert 'name="id_token"' not in html

        # Step 6: the platform verifies the response JWT against the tool's own JWKS.
        toolKeys = {key["kid"]: jwt.PyJWK.from_dict(key) for key in buildJwks(registration)["keys"]}
        decoded = jwt.decode(responseJwt, toolKeys["tool-kid"], algorithms=["RS256"], audience=ISSUER)
        assert decoded["iss"] == CLIENT_ID
        assert decoded["aud"] == ISSUER
        assert decoded[claimUris.DATA] == "roundtrip-correlation-id"
        assert decoded[claimUris.CONTENT_ITEMS] == [
            {"type": "ltiResourceLink", "url": "https://tool.example.com/launch/selected-item", "title": "Selected item"}
        ]
