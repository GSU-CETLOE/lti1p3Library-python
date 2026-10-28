"""A real, in-memory RegistrationRepositoryInterface implementation for tests.

The same shape a host application's database-backed implementation follows.
"""

from lti1p3.registration import Registration


class InMemoryRegistrationRepository:
    """Holds registrations in a list and answers the two lookups the library makes."""

    def __init__(self) -> None:
        self.registrations: list[Registration] = []

    def add(self, registration: Registration) -> None:
        """Register a platform."""
        self.registrations.append(registration)

    def findForLoginInitiation(self, issuer: str, clientId: str | None) -> Registration | None:
        """Match on issuer, and on client_id when given; ambiguous issuer-only lookups return None."""
        matches = [
            registration
            for registration in self.registrations
            if registration.issuer == issuer and (clientId is None or registration.clientId == clientId)
        ]

        if clientId is None:
            return matches[0] if len(matches) == 1 else None

        return matches[0] if matches else None

    def findForLaunch(self, issuer: str, clientId: str, deploymentId: str) -> Registration | None:
        """Match on issuer, client_id, and deployment_id together."""
        for registration in self.registrations:
            if (
                registration.issuer == issuer
                and registration.clientId == clientId
                and registration.hasDeployment(deploymentId)
            ):
                return registration
        return None
