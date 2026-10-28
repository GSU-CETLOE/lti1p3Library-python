"""Tests for the tool's signed Deep Linking response, verified with the tool's own JWKS."""

from typing import Any

import jwt

from lti1p3 import claimUris
from lti1p3.deepLinking import LinkContentItem, LtiDeepLinkingResponse, LtiResourceLinkContentItem
from lti1p3.registration import Registration
from lti1p3.security import buildJwks, generateKeyPair

ISSUER = "https://example.brightspace.com"
CLIENT_ID = "client-1"
DEPLOYMENT_ID = "deployment-1"


def registration() -> Registration:
    return Registration(
        ISSUER,
        CLIENT_ID,
        [DEPLOYMENT_ID],
        ISSUER + "/d2l/lti/authenticate",
        ISSUER + "/core/connect/token",
        ISSUER + "/d2l/.well-known/jwks",
        [generateKeyPair("tool-kid")],
    )


def decodeWithToolJwks(token: str, toolRegistration: Registration) -> dict[str, Any]:
    keySet = {key["kid"]: jwt.PyJWK.from_dict(key) for key in buildJwks(toolRegistration)["keys"]}
    kid = jwt.get_unverified_header(token)["kid"]
    return jwt.decode(token, keySet[kid], algorithms=["RS256"], audience=ISSUER)


class TestLtiDeepLinkingResponse:
    def test_producesARealJwtVerifiableWithTheToolsOwnJwks(self):
        toolRegistration = registration()
        token = LtiDeepLinkingResponse(
            toolRegistration, DEPLOYMENT_ID, ISSUER, [LinkContentItem("https://example.com")]
        ).toJwt()

        claims = decodeWithToolJwks(token, toolRegistration)
        assert claims["iss"] == CLIENT_ID
        assert claims["aud"] == ISSUER
        assert claims[claimUris.MESSAGE_TYPE] == "LtiDeepLinkingResponse"
        assert claims[claimUris.VERSION] == "1.3.0"
        assert claims[claimUris.DEPLOYMENT_ID] == DEPLOYMENT_ID
        assert claims["exp"] > claims["iat"]

    def test_includesAllContentItemsInOrder(self):
        toolRegistration = registration()
        token = LtiDeepLinkingResponse(
            toolRegistration,
            DEPLOYMENT_ID,
            ISSUER,
            [
                LtiResourceLinkContentItem(url="https://tool.example.com/1", title="First"),
                LinkContentItem("https://example.com/2", title="Second"),
            ],
        ).toJwt()

        contentItems = decodeWithToolJwks(token, toolRegistration)[claimUris.CONTENT_ITEMS]
        assert [item["type"] for item in contentItems] == ["ltiResourceLink", "link"]
        assert [item["title"] for item in contentItems] == ["First", "Second"]

    def test_echoesBackTheDataClaimWhenProvided(self):
        toolRegistration = registration()
        token = LtiDeepLinkingResponse(
            toolRegistration, DEPLOYMENT_ID, ISSUER, [LinkContentItem("https://example.com")], data="opaque-data-value"
        ).toJwt()
        assert decodeWithToolJwks(token, toolRegistration)[claimUris.DATA] == "opaque-data-value"

    def test_omitsTheDataClaimWhenNotProvided(self):
        toolRegistration = registration()
        token = LtiDeepLinkingResponse(
            toolRegistration, DEPLOYMENT_ID, ISSUER, [LinkContentItem("https://example.com")]
        ).toJwt()
        assert claimUris.DATA not in decodeWithToolJwks(token, toolRegistration)

    def test_signsWithTheActiveKeyAndNamesItsKidInTheHeader(self):
        toolRegistration = registration()
        token = LtiDeepLinkingResponse(toolRegistration, DEPLOYMENT_ID, ISSUER, []).toJwt()
        assert jwt.get_unverified_header(token)["kid"] == "tool-kid"
