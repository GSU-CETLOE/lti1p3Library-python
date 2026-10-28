"""Every exception this library raises, under one base type.

Vendor exceptions from the JWT library are never allowed to cross the public
API boundary. JwtValidator catches and remaps them to InvalidLaunchException,
keeping the original as the exception's cause.
"""

from enum import Enum, auto


class LtiException(RuntimeError):
    """Base type for every exception thrown by this library, so consumers can catch one type."""


class InvalidLaunchReason(Enum):
    """Why an inbound launch (id_token) failed validation.

    Carried on InvalidLaunchException so callers can tell failure modes apart
    for logging or telemetry without a combinatorial exception hierarchy.
    """

    UnsupportedAlgorithm = auto()
    MalformedToken = auto()
    InvalidSignature = auto()
    Expired = auto()
    NotYetValid = auto()
    InvalidIssuer = auto()
    InvalidAudience = auto()
    MissingNonce = auto()
    ReplayedNonce = auto()
    InvalidState = auto()
    InvalidDeploymentId = auto()
    MissingRequiredClaim = auto()
    UnexpectedMessageType = auto()
    UnsupportedVersion = auto()


class InvalidLaunchException(LtiException):
    """Raised when an inbound launch (id_token) fails validation."""

    def __init__(self, reason: InvalidLaunchReason, message: str) -> None:
        super().__init__(message)
        self.reason = reason


class InvalidLoginInitiationException(LtiException):
    """Raised when an OIDC login initiation request is missing a required parameter or has a bad one."""


class InvalidRegistrationException(LtiException):
    """Raised when a Registration or ToolKeyPair is constructed with invalid data."""


class KeyGenerationException(LtiException):
    """Raised when generating or reading an RSA key pair fails."""


class RegistrationNotFoundException(LtiException):
    """Raised when no Registration matches the issuer, client_id, or deployment_id of a request."""


class ServiceException(LtiException):
    """Raised when a call to a platform service (JWKS, token, AGS, NRPS) fails or returns nonsense."""
