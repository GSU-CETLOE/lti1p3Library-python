"""Tests for RSA key pair generation."""

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa

import pytest

from lti1p3.exceptions import KeyGenerationException
from lti1p3.security import generateKeyPair


class TestGenerateKeyPair:
    def test_generatesAToolKeyPairWithTheGivenKid(self):
        keyPair = generateKeyPair("kid-1")
        assert keyPair.kid == "kid-1"
        assert keyPair.activeForSigning is True
        assert "BEGIN PRIVATE KEY" in keyPair.privateKey
        assert "BEGIN PUBLIC KEY" in keyPair.publicKey

    def test_generatesRealUsableRsaKeys(self):
        keyPair = generateKeyPair("kid-1")
        privateKey = serialization.load_pem_private_key(keyPair.privateKey.encode(), password=None)
        publicKey = serialization.load_pem_public_key(keyPair.publicKey.encode())
        assert isinstance(privateKey, rsa.RSAPrivateKey)
        assert isinstance(publicKey, rsa.RSAPublicKey)

        message = b"sign and verify round trip"
        signature = privateKey.sign(message, padding.PKCS1v15(), hashes.SHA256())
        publicKey.verify(signature, message, padding.PKCS1v15(), hashes.SHA256())

    def test_defaultKeySizeIsAtLeast2048Bits(self):
        publicKey = serialization.load_pem_public_key(generateKeyPair("kid-1").publicKey.encode())
        assert isinstance(publicKey, rsa.RSAPublicKey)
        assert publicKey.key_size >= 2048

    def test_honorsARequestedKeySize(self):
        publicKey = serialization.load_pem_public_key(generateKeyPair("kid-1", keyBits=3072).publicKey.encode())
        assert isinstance(publicKey, rsa.RSAPublicKey)
        assert publicKey.key_size == 3072

    def test_eachGeneratedKeyPairIsUnique(self):
        assert generateKeyPair("kid-1").privateKey != generateKeyPair("kid-2").privateKey

    def test_rejectsAKeySizeTheCryptoLibraryCannotGenerate(self):
        with pytest.raises(KeyGenerationException):
            generateKeyPair("kid-1", keyBits=16)
