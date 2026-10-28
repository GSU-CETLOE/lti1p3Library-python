"""Tests for id_token validation using real signatures and the fixture server's JWKS."""

import base64
import json
import secrets
import time
from typing import Any

import httpx
import jwt
import pytest
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa

from arrayCache import ArrayCache
from fixturePlatformServer import FixturePlatformServer
from lti1p3.exceptions import InvalidLaunchException, InvalidLaunchReason
from lti1p3.registration import Registration, ToolKeyPair
from lti1p3.security import JwksFetcher, JwtValidator, buildJwk, generateKeyPair

ISSUER = "https://example.brightspace.com"
CLIENT_ID = "client-1"


def base64Url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


class ValidatorHarness:
    """One platform key pair, published at the fixture server, with helpers to issue and validate tokens."""

    def __init__(self, server: FixturePlatformServer, httpClient: httpx.Client) -> None:
        self.server = server
        self.httpClient = httpClient
        self.platformKeyPair = generateKeyPair("platform-kid")
        body = json.dumps({"keys": [buildJwk(self.platformKeyPair)]})
        server.queueResponse("GET", "/jwks", 200, {}, body)

    def registration(self) -> Registration:
        return Registration(
            ISSUER,
            CLIENT_ID,
            ["deployment-1"],
            ISSUER + "/d2l/lti/authenticate",
            ISSUER + "/core/connect/token",
            self.server.baseUrl() + "/jwks",
            [self.platformKeyPair],
        )

    def validator(self, clockSkewLeewaySeconds: int = 60) -> JwtValidator:
        return JwtValidator(JwksFetcher(self.httpClient, ArrayCache()), ArrayCache(), clockSkewLeewaySeconds)

    def issueToken(self, overrides: dict[str, Any] | None = None, keyPair: ToolKeyPair | None = None) -> str:
        now = int(time.time())
        claims: dict[str, Any] = {
            "iss": ISSUER,
            "aud": CLIENT_ID,
            "exp": now + 300,
            "iat": now,
            "nonce": secrets.token_hex(8),
            **(overrides or {}),
        }
        signingKey = keyPair or self.platformKeyPair
        return jwt.encode(claims, signingKey.privateKey, algorithm="RS256", headers={"kid": signingKey.kid})

    def assertRejectedWithReason(self, token: str, reason: InvalidLaunchReason, validator: JwtValidator | None = None):
        with pytest.raises(InvalidLaunchException) as caught:
            (validator or self.validator()).validate(token, self.registration())
        assert caught.value.reason is reason


@pytest.fixture
def harness(server: FixturePlatformServer, httpClient: httpx.Client) -> ValidatorHarness:
    return ValidatorHarness(server, httpClient)


class TestSignatureAndStructure:
    def test_validatesARealSignedTokenAndReturnsClaims(self, harness: ValidatorHarness):
        claims = harness.validator().validate(harness.issueToken({"sub": "user-1"}), harness.registration())
        assert claims["sub"] == "user-1"
        assert claims["iss"] == ISSUER

    def test_rejectsAnExpiredToken(self, harness: ValidatorHarness):
        now = int(time.time())
        harness.assertRejectedWithReason(
            harness.issueToken({"exp": now - 1000, "iat": now - 2000}), InvalidLaunchReason.Expired
        )

    def test_rejectsATokenNotYetValid(self, harness: ValidatorHarness):
        harness.assertRejectedWithReason(
            harness.issueToken({"iat": int(time.time()) + 1000}), InvalidLaunchReason.NotYetValid
        )

    def test_rejectsATokenWithAKidNotPresentInTheJwks(self, harness: ValidatorHarness):
        # Swap the header kid for an unknown one and re-sign with the correct key, so only the lookup fails.
        payloadSegment = harness.issueToken().split(".")[1]
        header = base64Url(json.dumps({"typ": "JWT", "alg": "RS256", "kid": "unknown-kid"}).encode())
        signingInput = f"{header}.{payloadSegment}"
        privateKey = serialization.load_pem_private_key(harness.platformKeyPair.privateKey.encode(), password=None)
        assert isinstance(privateKey, rsa.RSAPrivateKey)
        signature = privateKey.sign(signingInput.encode(), padding.PKCS1v15(), hashes.SHA256())
        harness.assertRejectedWithReason(f"{signingInput}.{base64Url(signature)}", InvalidLaunchReason.MalformedToken)

    def test_rejectsATokenWithoutAKid(self, harness: ValidatorHarness):
        token = jwt.encode({"iss": ISSUER}, harness.platformKeyPair.privateKey, algorithm="RS256")
        harness.assertRejectedWithReason(token, InvalidLaunchReason.MalformedToken)

    def test_rejectsATokenSignedByADifferentKey(self, harness: ValidatorHarness):
        impostor = generateKeyPair("platform-kid")
        harness.assertRejectedWithReason(harness.issueToken(keyPair=impostor), InvalidLaunchReason.InvalidSignature)

    def test_rejectsATokenWithATamperedPayloadUnderTheOriginalSignature(self, harness: ValidatorHarness):
        headerSegment, payloadSegment, signatureSegment = harness.issueToken({"sub": "user-1"}).split(".")
        payload = json.loads(base64.urlsafe_b64decode(payloadSegment + "=" * (-len(payloadSegment) % 4)))
        payload["sub"] = "attacker-controlled-user"
        tampered = f"{headerSegment}.{base64Url(json.dumps(payload).encode())}.{signatureSegment}"
        harness.assertRejectedWithReason(tampered, InvalidLaunchReason.InvalidSignature)

    def test_neverLeaksVendorJwtExceptionTypesAcrossThePublicApi(self, harness: ValidatorHarness):
        now = int(time.time())
        token = harness.issueToken({"exp": now - 1000, "iat": now - 2000})
        with pytest.raises(Exception) as caught:
            harness.validator().validate(token, harness.registration())
        assert isinstance(caught.value, InvalidLaunchException)
        assert isinstance(caught.value.__cause__, jwt.ExpiredSignatureError)

    def test_rejectsAnAlgNoneToken(self, harness: ValidatorHarness):
        header = base64Url(json.dumps({"typ": "JWT", "alg": "none"}).encode())
        payload = base64Url(
            json.dumps({"iss": ISSUER, "aud": CLIENT_ID, "exp": int(time.time()) + 300, "nonce": "n"}).encode()
        )
        harness.assertRejectedWithReason(f"{header}.{payload}.", InvalidLaunchReason.UnsupportedAlgorithm)

    def test_rejectsATokenWithoutThreeSegments(self, harness: ValidatorHarness):
        harness.assertRejectedWithReason("only.two", InvalidLaunchReason.MalformedToken)

    def test_rejectsATokenWhoseHeaderIsNotJson(self, harness: ValidatorHarness):
        harness.assertRejectedWithReason("!!!.payload.signature", InvalidLaunchReason.MalformedToken)

    def test_rejectsATokenWhoseHeaderHasNoAlg(self, harness: ValidatorHarness):
        header = base64Url(json.dumps({"typ": "JWT"}).encode())
        harness.assertRejectedWithReason(f"{header}.payload.signature", InvalidLaunchReason.MalformedToken)


class TestClaims:
    def test_rejectsMismatchedIssuerIncludingTrailingSlash(self, harness: ValidatorHarness):
        harness.assertRejectedWithReason(harness.issueToken({"iss": ISSUER + "/"}), InvalidLaunchReason.InvalidIssuer)

    def test_acceptsAStringAudienceMatchingClientId(self, harness: ValidatorHarness):
        claims = harness.validator().validate(harness.issueToken({"aud": CLIENT_ID}), harness.registration())
        assert claims["aud"] == CLIENT_ID

    def test_rejectsAStringAudienceNotMatchingClientId(self, harness: ValidatorHarness):
        harness.assertRejectedWithReason(harness.issueToken({"aud": "someone-else"}), InvalidLaunchReason.InvalidAudience)

    def test_acceptsAnArrayAudienceWithMatchingAzp(self, harness: ValidatorHarness):
        token = harness.issueToken({"aud": [CLIENT_ID, "other-client"], "azp": CLIENT_ID})
        assert harness.validator().validate(token, harness.registration())["aud"] == [CLIENT_ID, "other-client"]

    def test_rejectsAnArrayAudienceWithoutAzp(self, harness: ValidatorHarness):
        token = harness.issueToken({"aud": [CLIENT_ID, "other-client"]})
        harness.assertRejectedWithReason(token, InvalidLaunchReason.InvalidAudience)

    def test_rejectsAnArrayAudienceWithMismatchedAzp(self, harness: ValidatorHarness):
        token = harness.issueToken({"aud": [CLIENT_ID, "other-client"], "azp": "other-client"})
        harness.assertRejectedWithReason(token, InvalidLaunchReason.InvalidAudience)

    def test_rejectsAnArrayAudienceWithoutTheClientId(self, harness: ValidatorHarness):
        token = harness.issueToken({"aud": ["other-client"], "azp": CLIENT_ID})
        harness.assertRejectedWithReason(token, InvalidLaunchReason.InvalidAudience)

    def test_rejectsAMissingAudience(self, harness: ValidatorHarness):
        harness.assertRejectedWithReason(harness.issueToken({"aud": None}), InvalidLaunchReason.InvalidAudience)

    def test_acceptsATokenWhoseSubIsNullForAnonymousLaunches(self, harness: ValidatorHarness):
        claims = harness.validator().validate(harness.issueToken({"sub": None}), harness.registration())
        assert claims["sub"] is None

    def test_rejectsATokenMissingTheNonceClaim(self, harness: ValidatorHarness):
        harness.assertRejectedWithReason(harness.issueToken({"nonce": None}), InvalidLaunchReason.MissingNonce)

    def test_rejectsAReplayedNonce(self, harness: ValidatorHarness):
        token = harness.issueToken({"nonce": "fixed-nonce"})
        validator = harness.validator()
        validator.validate(token, harness.registration())
        harness.assertRejectedWithReason(token, InvalidLaunchReason.ReplayedNonce, validator)


class TestClockSkewLeeway:
    def test_appliesConfiguredClockSkewLeeway(self, harness: ValidatorHarness):
        now = int(time.time())
        token = harness.issueToken({"exp": now - 10, "iat": now - 20})
        assert harness.validator(clockSkewLeewaySeconds=30).validate(token, harness.registration())["iss"] == ISSUER

    def test_acceptsATokenWellWithinTheLeewayWindow(self, harness: ValidatorHarness):
        # A few seconds of margin either side of the boundary; the exact instant is racy against wall-clock time.
        now = int(time.time())
        token = harness.issueToken({"exp": now - 25, "iat": now - 60})
        assert harness.validator(clockSkewLeewaySeconds=30).validate(token, harness.registration())["iss"] == ISSUER

    def test_rejectsATokenClearlyBeyondTheLeewayWindow(self, harness: ValidatorHarness):
        now = int(time.time())
        token = harness.issueToken({"exp": now - 35, "iat": now - 60})
        harness.assertRejectedWithReason(token, InvalidLaunchReason.Expired, harness.validator(clockSkewLeewaySeconds=30))
