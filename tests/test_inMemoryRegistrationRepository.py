"""Tests for the in-memory registration repository used by the test suite."""

from inMemoryRegistrationRepository import InMemoryRegistrationRepository
from lti1p3.registration import Registration, ToolKeyPair


def registration(issuer: str, clientId: str, deploymentId: str = "deployment-1") -> Registration:
    return Registration(
        issuer,
        clientId,
        [deploymentId],
        issuer + "/auth",
        issuer + "/token",
        issuer + "/jwks",
        [ToolKeyPair("kid-1", "priv", "pub")],
    )


class TestInMemoryRegistrationRepository:
    def test_findsByIssuerAloneWhenOnlyOneRegistrationMatches(self):
        repository = InMemoryRegistrationRepository()
        only = registration("https://one.example.com", "client-1")
        repository.add(only)
        assert repository.findForLoginInitiation("https://one.example.com", None) is only

    def test_returnsNoneForAmbiguousIssuerWithoutClientId(self):
        repository = InMemoryRegistrationRepository()
        repository.add(registration("https://shared.example.com", "client-1"))
        repository.add(registration("https://shared.example.com", "client-2"))
        assert repository.findForLoginInitiation("https://shared.example.com", None) is None

    def test_findsByIssuerAndClientIdWhenBothGiven(self):
        repository = InMemoryRegistrationRepository()
        repository.add(registration("https://shared.example.com", "client-1"))
        second = registration("https://shared.example.com", "client-2")
        repository.add(second)
        assert repository.findForLoginInitiation("https://shared.example.com", "client-2") is second

    def test_returnsNoneWhenNoRegistrationMatchesTheIssuer(self):
        assert InMemoryRegistrationRepository().findForLoginInitiation("https://unknown.example.com", None) is None

    def test_findForLaunchRequiresIssuerClientIdAndDeploymentToAllMatch(self):
        repository = InMemoryRegistrationRepository()
        only = registration("https://one.example.com", "client-1", "deployment-1")
        repository.add(only)
        assert repository.findForLaunch("https://one.example.com", "client-1", "deployment-1") is only
        assert repository.findForLaunch("https://one.example.com", "client-1", "wrong-deployment") is None
        assert repository.findForLaunch("https://one.example.com", "wrong-client", "deployment-1") is None
        assert repository.findForLaunch("https://wrong.example.com", "client-1", "deployment-1") is None
