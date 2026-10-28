"""Tests for the https-or-loopback rule applied to platform and tool endpoints."""

from lti1p3.urlSecurity import isSecureUrl


class TestIsSecureUrl:
    def test_httpsUrlIsSecure(self):
        assert isSecureUrl("https://example.brightspace.com/d2l/.well-known/jwks")

    def test_plainHttpUrlToARemoteHostIsNotSecure(self):
        assert not isSecureUrl("http://example.brightspace.com/d2l/.well-known/jwks")

    def test_httpToLoopbackAddressesIsAllowedForLocalDevAndTesting(self):
        assert isSecureUrl("http://127.0.0.1:8080/jwks")
        assert isSecureUrl("http://localhost:8080/jwks")
        assert isSecureUrl("http://[::1]:8080/jwks")

    def test_httpsToLoopbackIsAlsoSecure(self):
        assert isSecureUrl("https://127.0.0.1:8443/jwks")

    def test_unparseableOrSchemelessUrlIsNotSecure(self):
        assert not isSecureUrl("not-a-url")
        assert not isSecureUrl("")

    def test_otherSchemesAreNotSecure(self):
        assert not isSecureUrl("ftp://example.com/jwks")
