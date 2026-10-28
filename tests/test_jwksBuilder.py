"""Tests for building the tool's published JWKS document."""

import jwt
import pytest

from lti1p3.exceptions import InvalidRegistrationException
from lti1p3.registration import Registration, ToolKeyPair
from lti1p3.security import buildJwk, buildJwks, generateKeyPair


def registrationWithKeyPairs(*toolKeyPairs: ToolKeyPair) -> Registration:
    return Registration(
        "https://example.brightspace.com",
        "client-1",
        ["deployment-1"],
        "https://example.brightspace.com/d2l/lti/authenticate",
        "https://example.brightspace.com/core/connect/token",
        "https://example.brightspace.com/d2l/.well-known/jwks",
        list(toolKeyPairs),
    )


class TestBuildJwks:
    def test_buildsJwksDocumentWithOneEntryPerKey(self):
        jwks = buildJwks(registrationWithKeyPairs(generateKeyPair("kid-1")))
        assert len(jwks["keys"]) == 1
        key = jwks["keys"][0]
        assert key["kty"] == "RSA"
        assert key["use"] == "sig"
        assert key["alg"] == "RS256"
        assert key["kid"] == "kid-1"
        assert key["n"] != ""
        assert key["e"] != ""

    def test_buildJwkReturnsASingleJwkEntryForOneKeyPair(self):
        jwk = buildJwk(generateKeyPair("kid-1"))
        assert jwk["kty"] == "RSA"
        assert jwk["kid"] == "kid-1"
        assert "=" not in jwk["n"] and "+" not in jwk["n"] and "/" not in jwk["n"]

    def test_includesRotatedOutInactiveKeysSoPlatformCanStillVerifyThem(self):
        rotatedOut = generateKeyPair("old-kid")
        oldInactive = ToolKeyPair(rotatedOut.kid, rotatedOut.privateKey, rotatedOut.publicKey, activeForSigning=False)
        jwks = buildJwks(registrationWithKeyPairs(oldInactive, generateKeyPair("new-kid")))
        assert [key["kid"] for key in jwks["keys"]] == ["old-kid", "new-kid"]

    def test_jwkEncodingInteroperatesWithARealIndependentJwtLibrary(self):
        keyPair = generateKeyPair("kid-1")
        jwk = buildJwks(registrationWithKeyPairs(keyPair))["keys"][0]
        token = jwt.encode({"sub": "user-1"}, keyPair.privateKey, algorithm="RS256", headers={"kid": "kid-1"})
        decoded = jwt.decode(token, jwt.PyJWK.from_dict(jwk), algorithms=["RS256"])
        assert decoded["sub"] == "user-1"

    def test_throwsWhenPublicKeyIsNotValidPem(self):
        registration = registrationWithKeyPairs(ToolKeyPair("kid-1", "not-a-real-private-key", "not-a-real-public-key"))
        with pytest.raises(InvalidRegistrationException, match='Could not parse public key for kid "kid-1"'):
            buildJwks(registration)

    def test_throwsWhenPublicKeyIsNotRsa(self):
        from cryptography.hazmat.primitives import serialization
        from cryptography.hazmat.primitives.asymmetric import ec

        ecKey = ec.generate_private_key(ec.SECP256R1())
        publicPem = ecKey.public_key().public_bytes(
            serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
        )
        with pytest.raises(InvalidRegistrationException, match='Public key for kid "ec-kid" is not a valid RSA key'):
            buildJwk(ToolKeyPair("ec-kid", "irrelevant", publicPem.decode()))
