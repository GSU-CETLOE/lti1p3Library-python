"""Deep Linking 2.0 content items and the tool's signed response to a Deep Linking request."""

import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import Protocol

import jwt

from lti1p3 import claimUris
from lti1p3.registration import Registration

type ContentItemData = dict[str, object]


class ContentItem(Protocol):
    """A single item in an LtiDeepLinkingResponse's `content_items` claim."""

    def toDict(self) -> ContentItemData:
        """The item as the JSON object the platform expects."""
        ...


@dataclass(frozen=True)
class ContentItemLineItem:
    """The optional `lineItem` of an `ltiResourceLink` item: asks the platform to create a gradebook column."""

    scoreMaximum: float
    label: str | None = None
    resourceId: str | None = None
    tag: str | None = None
    gradesReleased: bool | None = None

    def toDict(self) -> ContentItemData:
        """The line item as a JSON object, omitting unset optional fields."""
        data: ContentItemData = {"scoreMaximum": self.scoreMaximum}
        _putIfSet(data, "label", self.label)
        _putIfSet(data, "resourceId", self.resourceId)
        _putIfSet(data, "tag", self.tag)
        _putIfSet(data, "gradesReleased", self.gradesReleased)
        return data


@dataclass(frozen=True)
class LtiResourceLinkContentItem:
    """The most common item: a link back into this tool, optionally with a line item alongside it."""

    url: str | None = None
    title: str | None = None
    text: str | None = None
    custom: Mapping[str, str] = field(default_factory=dict[str, str])
    lineItem: ContentItemLineItem | None = None

    def toDict(self) -> ContentItemData:
        """The item as a JSON object, omitting unset optional fields."""
        data: ContentItemData = {"type": "ltiResourceLink"}
        _putIfSet(data, "url", self.url)
        _putIfSet(data, "title", self.title)
        _putIfSet(data, "text", self.text)
        if self.custom:
            data["custom"] = dict(self.custom)
        if self.lineItem is not None:
            data["lineItem"] = self.lineItem.toDict()
        return data


@dataclass(frozen=True)
class LinkContentItem:
    """A content item pointing to an arbitrary external URL."""

    url: str
    title: str | None = None
    text: str | None = None

    def toDict(self) -> ContentItemData:
        """The item as a JSON object, omitting unset optional fields."""
        data: ContentItemData = {"type": "link", "url": self.url}
        _putIfSet(data, "title", self.title)
        _putIfSet(data, "text", self.text)
        return data


@dataclass(frozen=True)
class FileContentItem:
    """A content item pointing to a downloadable file, optionally with a URL that expires."""

    url: str
    title: str | None = None
    text: str | None = None
    expiresAt: datetime | None = None

    def toDict(self) -> ContentItemData:
        """The item as a JSON object, omitting unset optional fields."""
        data: ContentItemData = {"type": "file", "url": self.url}
        _putIfSet(data, "title", self.title)
        _putIfSet(data, "text", self.text)
        if self.expiresAt is not None:
            data["expiresAt"] = self.expiresAt.isoformat(timespec="seconds")
        return data


@dataclass(frozen=True)
class HtmlContentItem:
    """A content item embedding a raw HTML fragment."""

    html: str
    title: str | None = None
    text: str | None = None

    def toDict(self) -> ContentItemData:
        """The item as a JSON object, omitting unset optional fields."""
        data: ContentItemData = {"type": "html", "html": self.html}
        _putIfSet(data, "title", self.title)
        _putIfSet(data, "text", self.text)
        return data


@dataclass(frozen=True)
class ImageContentItem:
    """A content item pointing to an image."""

    url: str
    title: str | None = None
    text: str | None = None
    width: int | None = None
    height: int | None = None

    def toDict(self) -> ContentItemData:
        """The item as a JSON object, omitting unset optional fields."""
        data: ContentItemData = {"type": "image", "url": self.url}
        _putIfSet(data, "title", self.title)
        _putIfSet(data, "text", self.text)
        _putIfSet(data, "width", self.width)
        _putIfSet(data, "height", self.height)
        return data


def _putIfSet(data: ContentItemData, key: str, value: object) -> None:
    if value is not None:
        data[key] = value


@dataclass(frozen=True)
class LtiDeepLinkingResponse:
    """The tool's signed response to a Deep Linking request.

    A JWT naming the selected content items, signed with the tool's active
    key so the platform can verify it against the tool's published JWKS.
    Per the Deep Linking 2.0 spec, `iss` and `aud` are reversed relative to
    the inbound launch: `iss` is the tool's client_id and `aud` is the
    platform's issuer, because the platform is the verifier here.
    """

    MESSAGE_TYPE = "LtiDeepLinkingResponse"
    TOKEN_TTL_SECONDS = 300

    registration: Registration
    deploymentId: str
    platformIssuer: str
    contentItems: Sequence[ContentItem]
    data: str | None = None

    def toJwt(self) -> str:
        """Sign and return the response JWT, to be posted in a form field named `JWT`."""
        now = int(time.time())
        signingKey = self.registration.activeSigningKey()

        claims: dict[str, object] = {
            "iss": self.registration.clientId,
            "aud": self.platformIssuer,
            "exp": now + self.TOKEN_TTL_SECONDS,
            "iat": now,
            claimUris.MESSAGE_TYPE: self.MESSAGE_TYPE,
            claimUris.VERSION: "1.3.0",
            claimUris.DEPLOYMENT_ID: self.deploymentId,
            claimUris.CONTENT_ITEMS: [item.toDict() for item in self.contentItems],
        }
        if self.data is not None:
            claims[claimUris.DATA] = self.data

        return jwt.encode(claims, signingKey.privateKey, algorithm="RS256", headers={"kid": signingKey.kid})
