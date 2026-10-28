"""Tests for the tool signing key value object."""

import pytest

from lti1p3.exceptions import InvalidRegistrationException
from lti1p3.registration import ToolKeyPair


class TestToolKeyPair:
    def test_constructsWithValidValues(self):
        keyPair = ToolKeyPair(
            kid="kid-1",
            privateKey="-----BEGIN PRIVATE KEY-----\nabc\n-----END PRIVATE KEY-----",
            publicKey="-----BEGIN PUBLIC KEY-----\ndef\n-----END PUBLIC KEY-----",
            activeForSigning=True,
        )
        assert keyPair.kid == "kid-1"
        assert "BEGIN PRIVATE KEY" in keyPair.privateKey
        assert "BEGIN PUBLIC KEY" in keyPair.publicKey
        assert keyPair.activeForSigning is True

    def test_activeForSigningDefaultsToTrue(self):
        assert ToolKeyPair("kid-1", "priv", "pub").activeForSigning is True

    def test_canBeMarkedInactiveForSigning(self):
        assert ToolKeyPair("kid-1", "priv", "pub", activeForSigning=False).activeForSigning is False

    def test_rejectsEmptyKid(self):
        with pytest.raises(InvalidRegistrationException, match="kid must not be empty"):
            ToolKeyPair("", "priv", "pub")

    def test_rejectsBlankKid(self):
        with pytest.raises(InvalidRegistrationException):
            ToolKeyPair("   ", "priv", "pub")

    def test_rejectsEmptyPrivateKey(self):
        with pytest.raises(InvalidRegistrationException, match="privateKey must not be empty"):
            ToolKeyPair("kid-1", "", "pub")

    def test_rejectsEmptyPublicKey(self):
        with pytest.raises(InvalidRegistrationException, match="publicKey must not be empty"):
            ToolKeyPair("kid-1", "priv", "")
