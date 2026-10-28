"""Typed reads over raw JWT claims, and the value objects hydrated from them.

Every claim value object hydrates through the accessor functions at the top
of this module, so type checks over the dynamically shaped claims mapping
live in one place rather than being scattered through business logic.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, ClassVar, cast

from lti1p3.exceptions import InvalidLaunchException, InvalidLaunchReason

type Claims = Mapping[str, object]


def requireString(data: Claims, key: str, context: str) -> str:
    """Return a non-empty string claim, or raise InvalidLaunchException naming the context."""
    value = data.get(key)
    if not isinstance(value, str) or value == "":
        raise InvalidLaunchException(
            InvalidLaunchReason.MissingRequiredClaim, f'{context} is missing required "{key}".'
        )
    return value


def optionalString(data: Claims, key: str) -> str | None:
    """Return the string claim, or None when it is missing, empty, or not a string."""
    value = data.get(key)
    return value if isinstance(value, str) and value != "" else None


def optionalInt(data: Claims, key: str) -> int | None:
    """Return the integer claim, or None when it is missing or not an integer (bools don't count)."""
    value = data.get(key)
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def optionalBool(data: Claims, key: str) -> bool | None:
    """Return the boolean claim, or None when it is missing or not a boolean."""
    value = data.get(key)
    return value if isinstance(value, bool) else None


def optionalStringList(data: Claims, key: str) -> list[str]:
    """Return the string entries of a list claim; an empty list when missing or not a list."""
    entries = jsonList(data.get(key))
    if entries is None:
        return []
    return [entry for entry in entries if isinstance(entry, str)]


def optionalArray(data: Claims, key: str) -> Claims | None:
    """Return the mapping claim, or None when it is missing or not a mapping."""
    return asClaims(data.get(key))


def asClaims(value: object) -> Claims | None:
    """Narrow an arbitrary decoded JSON value to a claims mapping, or None."""
    if not isinstance(value, Mapping):
        return None
    # A decoded JSON object always has string keys; the checker only knows it is a Mapping.
    return cast(Claims, value)


def jsonObject(value: object) -> dict[str, Any] | None:
    """Narrow a decoded JSON value to an object (a dict with string keys), or None."""
    if not isinstance(value, dict):
        return None
    # json.loads produces dicts keyed by str; the checker only knows it is a dict.
    return cast(dict[str, Any], value)


def jsonList(value: object) -> list[Any] | None:
    """Narrow a decoded JSON value to a list, or None."""
    if not isinstance(value, list):
        return None
    return cast(list[Any], value)


@dataclass(frozen=True)
class AgsEndpoint:
    """The Assignment and Grades Service `endpoint` claim.

    Names the line items collection URL, the single line item URL when the
    launch is associated with exactly one, and the granted AGS scopes. Can
    appear on any authorized LTI message, not just a resource link launch.
    """

    scopes: list[str]
    lineItemsUrl: str
    lineItemUrl: str | None

    @classmethod
    def fromClaimValue(cls, value: object) -> "AgsEndpoint | None":
        """Build from the raw claim, or None when it is absent or lacks a line items URL."""
        data = asClaims(value)
        if data is None:
            return None

        lineItemsUrl = optionalString(data, "lineitems")
        if lineItemsUrl is None:
            return None

        return cls(optionalStringList(data, "scope"), lineItemsUrl, optionalString(data, "lineitem"))


@dataclass(frozen=True)
class NrpsEndpoint:
    """The Names and Role Provisioning Service `namesroleservice` claim."""

    contextMembershipsUrl: str
    serviceVersions: list[str]

    @classmethod
    def fromClaimValue(cls, value: object) -> "NrpsEndpoint | None":
        """Build from the raw claim, or None when it is absent or lacks a memberships URL."""
        data = asClaims(value)
        if data is None:
            return None

        contextMembershipsUrl = optionalString(data, "context_memberships_url")
        if contextMembershipsUrl is None:
            return None

        return cls(contextMembershipsUrl, optionalStringList(data, "service_versions"))


@dataclass(frozen=True)
class Context:
    """The `context` claim: the course or group the launch happened in. Optional."""

    id: str
    label: str | None
    title: str | None
    types: list[str]

    @classmethod
    def fromClaimValue(cls, value: object) -> "Context | None":
        """Build from the raw claim, or None when it is absent or lacks an id."""
        data = asClaims(value)
        if data is None:
            return None

        contextId = optionalString(data, "id")
        if contextId is None:
            return None

        return cls(
            contextId,
            optionalString(data, "label"),
            optionalString(data, "title"),
            optionalStringList(data, "type"),
        )


@dataclass(frozen=True)
class DeepLinkingSettings:
    """The `deep_linking_settings` claim, required on a Deep Linking request.

    Says where to send the response, what content types and targets the
    platform accepts, and carries optional opaque `data` the tool must echo
    back unchanged.
    """

    deepLinkReturnUrl: str
    acceptTypes: list[str]
    acceptPresentationDocumentTargets: list[str]
    acceptMultiple: bool | None
    acceptLineItem: bool | None
    autoCreate: bool | None
    title: str | None
    text: str | None
    data: str | None

    @classmethod
    def fromClaimValue(cls, value: object, context: str) -> "DeepLinkingSettings":
        """Build from the raw claim, raising InvalidLaunchException when it or its return URL is missing."""
        data = asClaims(value)
        if data is None:
            raise InvalidLaunchException(
                InvalidLaunchReason.MissingRequiredClaim, f'{context} is missing the "deep_linking_settings" claim.'
            )

        return cls(
            requireString(data, "deep_link_return_url", context + " deep_linking_settings"),
            optionalStringList(data, "accept_types"),
            optionalStringList(data, "accept_presentation_document_targets"),
            optionalBool(data, "accept_multiple"),
            optionalBool(data, "accept_lineitem"),
            optionalBool(data, "auto_create"),
            optionalString(data, "title"),
            optionalString(data, "text"),
            optionalString(data, "data"),
        )


@dataclass(frozen=True)
class LaunchPresentation:
    """The `launch_presentation` claim: how the platform is displaying the tool. All optional."""

    documentTarget: str | None
    height: int | None
    width: int | None
    returnUrl: str | None
    locale: str | None

    @classmethod
    def fromClaimValue(cls, value: object) -> "LaunchPresentation | None":
        """Build from the raw claim, or None when it is absent."""
        data = asClaims(value)
        if data is None:
            return None

        return cls(
            optionalString(data, "document_target"),
            optionalInt(data, "height"),
            optionalInt(data, "width"),
            optionalString(data, "return_url"),
            optionalString(data, "locale"),
        )


@dataclass(frozen=True)
class Lis:
    """The `lis` claim: legacy LTI 1.1 identifiers some platforms still send. All optional."""

    personSourcedId: str | None
    courseOfferingSourcedId: str | None
    courseSectionSourcedId: str | None

    @classmethod
    def fromClaimValue(cls, value: object) -> "Lis | None":
        """Build from the raw claim, or None when it is absent."""
        data = asClaims(value)
        if data is None:
            return None

        return cls(
            optionalString(data, "person_sourcedid"),
            optionalString(data, "course_offering_sourcedid"),
            optionalString(data, "course_section_sourcedid"),
        )


@dataclass(frozen=True)
class ResourceLink:
    """The `resource_link` claim, required on a resource link launch."""

    id: str
    title: str | None
    description: str | None

    @classmethod
    def fromClaimValue(cls, value: object, context: str) -> "ResourceLink":
        """Build from the raw claim, raising InvalidLaunchException when it or its id is missing."""
        data = asClaims(value)
        if data is None:
            raise InvalidLaunchException(
                InvalidLaunchReason.MissingRequiredClaim, f'{context} is missing the "resource_link" claim.'
            )

        return cls(
            requireString(data, "id", context + " resource_link"),
            optionalString(data, "title"),
            optionalString(data, "description"),
        )


@dataclass(frozen=True)
class Roles:
    """The `roles` claim: a list of role URIs with predicates for the common ones.

    Deliberately not an enum. The LIS/LTI role vocabulary is open-ended, so
    institution-specific and future roles must pass through untouched.
    """

    INSTRUCTOR: ClassVar[str] = "http://purl.imsglobal.org/vocab/lis/v2/membership#Instructor"
    LEARNER: ClassVar[str] = "http://purl.imsglobal.org/vocab/lis/v2/membership#Learner"
    CONTENT_DEVELOPER: ClassVar[str] = "http://purl.imsglobal.org/vocab/lis/v2/membership#ContentDeveloper"
    TEACHING_ASSISTANT: ClassVar[str] = "http://purl.imsglobal.org/vocab/lis/v2/membership#TeachingAssistant"
    MENTOR: ClassVar[str] = "http://purl.imsglobal.org/vocab/lis/v2/membership#Mentor"
    ADMINISTRATOR: ClassVar[str] = "http://purl.imsglobal.org/vocab/lis/v2/institution/person#Administrator"

    roleUris: tuple[str, ...]

    @classmethod
    def fromClaimValue(cls, value: object) -> "Roles":
        """Build from the raw claim; a missing or malformed claim yields no roles."""
        entries = jsonList(value)
        if entries is None:
            return cls(())
        return cls(tuple(entry for entry in entries if isinstance(entry, str)))

    def all(self) -> list[str]:
        """Every role URI exactly as received."""
        return list(self.roleUris)

    def has(self, roleUri: str) -> bool:
        """Report whether the given role URI is present."""
        return roleUri in self.roleUris

    def isInstructor(self) -> bool:
        return self.has(self.INSTRUCTOR)

    def isLearner(self) -> bool:
        return self.has(self.LEARNER)

    def isContentDeveloper(self) -> bool:
        return self.has(self.CONTENT_DEVELOPER)

    def isTeachingAssistant(self) -> bool:
        return self.has(self.TEACHING_ASSISTANT)

    def isMentor(self) -> bool:
        return self.has(self.MENTOR)

    def isAdministrator(self) -> bool:
        return self.has(self.ADMINISTRATOR)


@dataclass(frozen=True)
class ToolPlatform:
    """The `tool_platform` claim: the platform instance making the launch."""

    guid: str
    name: str | None
    contactEmail: str | None
    description: str | None
    url: str | None
    productFamilyCode: str | None
    version: str | None

    @classmethod
    def fromClaimValue(cls, value: object) -> "ToolPlatform | None":
        """Build from the raw claim, or None when it is absent or lacks a guid."""
        data = asClaims(value)
        if data is None:
            return None

        guid = optionalString(data, "guid")
        if guid is None:
            return None

        return cls(
            guid,
            optionalString(data, "name"),
            optionalString(data, "contact_email"),
            optionalString(data, "description"),
            optionalString(data, "url"),
            optionalString(data, "product_family_code"),
            optionalString(data, "version"),
        )
