"""A tool's registration against one platform, and the repository contract the host app implements."""

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol

from lti1p3.exceptions import InvalidRegistrationException
from lti1p3.urlSecurity import isSecureUrl


@dataclass(frozen=True)
class ToolKeyPair:
    """One of the tool's RSA signing keys, as PEM strings.

    A Registration holds a list of these to support key rotation: an old key
    stays published in the tool's JWKS, so the platform can still verify
    tokens signed before rotation, even after a new key becomes
    activeForSigning.
    """

    kid: str
    privateKey: str
    publicKey: str
    activeForSigning: bool = True

    def __post_init__(self) -> None:
        if not self.kid.strip():
            raise InvalidRegistrationException("ToolKeyPair kid must not be empty.")
        if not self.privateKey.strip():
            raise InvalidRegistrationException("ToolKeyPair privateKey must not be empty.")
        if not self.publicKey.strip():
            raise InvalidRegistrationException("ToolKeyPair publicKey must not be empty.")


@dataclass(frozen=True)
class Registration:
    """A single tool registration against one platform (issuer + client_id).

    Covers the deployments, endpoints, and signing keys needed to validate
    launches and call back into platform services. platformAudience is the
    "aud" to use in the client assertion sent to the token endpoint; None
    means the token URL itself, which is what the 1EdTech Security Framework
    specifies and most platforms expect.
    """

    issuer: str
    clientId: str
    deploymentIds: Sequence[str]
    platformAuthenticationLoginUrl: str
    platformAuthenticationTokenUrl: str
    platformJwksUrl: str
    toolKeyPairs: Sequence[ToolKeyPair]
    platformAudience: str | None = None

    def __post_init__(self) -> None:
        if not self.issuer.strip():
            raise InvalidRegistrationException("Registration issuer must not be empty.")
        if not self.clientId.strip():
            raise InvalidRegistrationException("Registration clientId must not be empty.")
        if len(self.deploymentIds) == 0:
            raise InvalidRegistrationException("Registration must have at least one deployment id.")
        if any(not deploymentId.strip() for deploymentId in self.deploymentIds):
            raise InvalidRegistrationException("Registration deployment ids must be non-empty strings.")

        self._requireSecureUrl("platformAuthenticationLoginUrl", self.platformAuthenticationLoginUrl)
        self._requireSecureUrl("platformAuthenticationTokenUrl", self.platformAuthenticationTokenUrl)
        self._requireSecureUrl("platformJwksUrl", self.platformJwksUrl)

        if self.platformAudience is not None and not self.platformAudience.strip():
            raise InvalidRegistrationException(
                "Registration platformAudience must not be empty when provided (pass None to use the token url)."
            )

        if len(self.toolKeyPairs) == 0:
            raise InvalidRegistrationException("Registration must have at least one tool key pair.")

        activeSigningKeyCount = sum(1 for keyPair in self.toolKeyPairs if keyPair.activeForSigning)
        if activeSigningKeyCount != 1:
            raise InvalidRegistrationException(
                f"Registration must have exactly one active signing key, {activeSigningKeyCount} given."
            )

        # Sequences become tuples so the registration is immutable all the way down.
        object.__setattr__(self, "deploymentIds", tuple(self.deploymentIds))
        object.__setattr__(self, "toolKeyPairs", tuple(self.toolKeyPairs))

    @staticmethod
    def _requireSecureUrl(name: str, url: str) -> None:
        if not url.strip():
            raise InvalidRegistrationException(f"Registration {name} must not be empty.")
        if not isSecureUrl(url):
            raise InvalidRegistrationException(
                f"Registration {name} must use https (or loopback for local dev/testing)."
            )

    def accessTokenAudience(self) -> str:
        """The "aud" for the client assertion: the configured override, otherwise the token endpoint."""
        return self.platformAudience if self.platformAudience is not None else self.platformAuthenticationTokenUrl

    def hasDeployment(self, deploymentId: str) -> bool:
        """Report whether the given deployment id belongs to this registration."""
        return deploymentId in self.deploymentIds

    def activeSigningKey(self) -> ToolKeyPair:
        """The one key pair marked active for signing outbound JWTs."""
        for keyPair in self.toolKeyPairs:
            if keyPair.activeForSigning:
                return keyPair

        # Unreachable: construction guarantees exactly one active signing key.
        raise InvalidRegistrationException("No active signing key found.")

    def findKeyPairByKid(self, kid: str) -> ToolKeyPair | None:
        """Find a key pair, active or rotated out, by its key id."""
        for keyPair in self.toolKeyPairs:
            if keyPair.kid == kid:
                return keyPair
        return None


class RegistrationRepositoryInterface(Protocol):
    """Implemented by the host application to look up its stored platform registrations.

    This library ships no persistence of its own.
    """

    def findForLoginInitiation(self, issuer: str, clientId: str | None) -> Registration | None:
        """Look up a registration during OIDC login initiation, when client_id may be absent.

        Return None (never raise) when nothing matches, and also when clientId
        is None and more than one registration exists for the issuer: the
        request is ambiguous and cannot be resolved safely.
        """
        ...

    def findForLaunch(self, issuer: str, clientId: str, deploymentId: str) -> Registration | None:
        """Look up a registration to validate an inbound launch.

        Return None (never raise) when no registration matches the issuer and
        client_id, or when the match does not include deploymentId.
        """
        ...
