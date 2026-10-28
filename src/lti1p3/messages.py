"""The typed LTI messages a validated launch produces.

Each message is hydrated once from the validated claims mapping. Nothing
downstream touches raw claims for the fields modeled here; rawClaims stays
available for anything the model does not cover.
"""

from dataclasses import dataclass
from typing import Any, ClassVar

from lti1p3 import claimUris
from lti1p3.claims import (
    AgsEndpoint,
    Claims,
    Context,
    DeepLinkingSettings,
    LaunchPresentation,
    Lis,
    NrpsEndpoint,
    ResourceLink,
    Roles,
    ToolPlatform,
    optionalArray,
    optionalString,
    optionalStringList,
    requireString,
)
from lti1p3.exceptions import InvalidLaunchException, InvalidLaunchReason

LTI_VERSION = "1.3.0"


@dataclass(frozen=True, kw_only=True)
class LtiMessage:
    """Base for every LTI message type, holding the claims common to all of them."""

    messageType: str
    version: str
    deploymentId: str
    targetLinkUri: str
    subject: str | None
    roles: Roles
    context: Context | None
    toolPlatform: ToolPlatform | None
    launchPresentation: LaunchPresentation | None
    lis: Lis | None
    roleScopeMentor: list[str] | None
    custom: dict[str, str]
    rawClaims: Claims

    @staticmethod
    def commonPropertiesFromClaims(claims: Claims, expectedMessageType: str) -> dict[str, Any]:
        """Validate and read the claims shared by every message type, as constructor keyword arguments."""
        messageType = requireString(claims, claimUris.MESSAGE_TYPE, "LTI message")
        if messageType != expectedMessageType:
            raise InvalidLaunchException(
                InvalidLaunchReason.UnexpectedMessageType,
                f'Expected message_type "{expectedMessageType}", got "{messageType}".',
            )

        version = requireString(claims, claimUris.VERSION, "LTI message")
        if version != LTI_VERSION:
            raise InvalidLaunchException(
                InvalidLaunchReason.UnsupportedVersion, f'Expected LTI version "{LTI_VERSION}", got "{version}".'
            )

        customClaim = optionalArray(claims, claimUris.CUSTOM) or {}
        custom = {key: value for key, value in customClaim.items() if isinstance(value, str)}
        roleScopeMentor = optionalStringList(claims, claimUris.ROLE_SCOPE_MENTOR)

        return {
            "messageType": messageType,
            "version": version,
            "deploymentId": requireString(claims, claimUris.DEPLOYMENT_ID, "LTI message"),
            "targetLinkUri": requireString(claims, claimUris.TARGET_LINK_URI, "LTI message"),
            "subject": optionalString(claims, "sub"),
            "roles": Roles.fromClaimValue(claims.get(claimUris.ROLES)),
            "context": Context.fromClaimValue(claims.get(claimUris.CONTEXT)),
            "toolPlatform": ToolPlatform.fromClaimValue(claims.get(claimUris.TOOL_PLATFORM)),
            "launchPresentation": LaunchPresentation.fromClaimValue(claims.get(claimUris.LAUNCH_PRESENTATION)),
            "lis": Lis.fromClaimValue(claims.get(claimUris.LIS)),
            "roleScopeMentor": roleScopeMentor or None,
            "custom": custom,
            "rawClaims": claims,
        }

    def agsEndpoint(self) -> AgsEndpoint | None:
        """The AGS `endpoint` claim, if the platform granted this launch access to it.

        It can appear on any authorized message, not just a resource link
        launch, so it lives here rather than on a specific subclass.
        """
        return AgsEndpoint.fromClaimValue(self.rawClaims.get(claimUris.AGS_ENDPOINT))

    def nrpsEndpoint(self) -> NrpsEndpoint | None:
        """The NRPS `namesroleservice` claim, if the platform granted this launch access to it."""
        return NrpsEndpoint.fromClaimValue(self.rawClaims.get(claimUris.NRPS_ENDPOINT))


@dataclass(frozen=True, kw_only=True)
class LtiResourceLinkRequest(LtiMessage):
    """The core LTI message: a user clicking a resource link in the platform and launching into the tool."""

    MESSAGE_TYPE: ClassVar[str] = "LtiResourceLinkRequest"

    resourceLink: ResourceLink

    @classmethod
    def fromClaims(cls, claims: Claims) -> "LtiResourceLinkRequest":
        """Build from validated claims, raising InvalidLaunchException on a wrong type, version, or missing claim."""
        common = cls.commonPropertiesFromClaims(claims, cls.MESSAGE_TYPE)
        resourceLink = ResourceLink.fromClaimValue(claims.get(claimUris.RESOURCE_LINK), cls.MESSAGE_TYPE)
        return cls(**common, resourceLink=resourceLink)


@dataclass(frozen=True, kw_only=True)
class LtiDeepLinkingRequest(LtiMessage):
    """A platform asking the tool to let the user pick content to link back into the platform."""

    MESSAGE_TYPE: ClassVar[str] = "LtiDeepLinkingRequest"

    deepLinkingSettings: DeepLinkingSettings

    @classmethod
    def fromClaims(cls, claims: Claims) -> "LtiDeepLinkingRequest":
        """Build from validated claims, raising InvalidLaunchException on a wrong type, version, or missing claim."""
        common = cls.commonPropertiesFromClaims(claims, cls.MESSAGE_TYPE)
        settings = DeepLinkingSettings.fromClaimValue(claims.get(claimUris.DEEP_LINKING_SETTINGS), cls.MESSAGE_TYPE)
        return cls(**common, deepLinkingSettings=settings)
