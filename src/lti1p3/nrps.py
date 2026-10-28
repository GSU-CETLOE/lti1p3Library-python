"""Names and Role Provisioning Service 2.0: the roster for the launch's context."""

import re
from dataclasses import dataclass

import httpx

from lti1p3.accessToken import AccessTokenService
from lti1p3.claims import NrpsEndpoint, jsonList, jsonObject, optionalStringList
from lti1p3.exceptions import ServiceException
from lti1p3.registration import Registration
from lti1p3.services import decodeJsonBody, sendAuthorizedRequest

SCOPE_READONLY = "https://purl.imsglobal.org/spec/lti-nrps/scope/contextmembership.readonly"
CONTENT_TYPE_MEMBERSHIP_CONTAINER = "application/vnd.ims.lti-nrps.v2.membershipcontainer+json"
SERVICE_NAME = "NRPS"
NEXT_LINK_PATTERN = re.compile(r'<([^>]+)>\s*;\s*rel="next"')


def _stringOrNone(value: object) -> str | None:
    return value if isinstance(value, str) else None


@dataclass(frozen=True)
class Member:
    """A single roster entry. `roles` uses the same open LTI/LIS role vocabulary as the launch `roles` claim."""

    userId: str
    status: str
    name: str | None
    roles: list[str]
    email: str | None
    picture: str | None
    givenName: str | None
    familyName: str | None
    middleName: str | None

    @classmethod
    def fromResponseData(cls, data: object) -> "Member":
        """Build from a platform response entry, raising ServiceException when it has no user_id."""
        record = jsonObject(data)
        if record is None:
            raise ServiceException("NRPS member entry was not a JSON object.")

        userId = record.get("user_id")
        if not isinstance(userId, str) or userId == "":
            raise ServiceException('NRPS member entry is missing "user_id".')

        status = record.get("status")
        return cls(
            userId,
            status if isinstance(status, str) and status != "" else "Active",
            _stringOrNone(record.get("name")),
            optionalStringList(record, "roles"),
            _stringOrNone(record.get("email")),
            _stringOrNone(record.get("picture")),
            _stringOrNone(record.get("given_name")),
            _stringOrNone(record.get("family_name")),
            _stringOrNone(record.get("middle_name")),
        )


class NamesRoleService:
    """Fetches the roster for the launch's context, following `Link: rel="next"` pagination."""

    def __init__(self, httpClient: httpx.Client, accessTokenService: AccessTokenService):
        self.httpClient = httpClient
        self.accessTokenService = accessTokenService

    def getMembers(self, registration: Registration, endpoint: NrpsEndpoint) -> list[Member]:
        """Every member of the context, across all pages."""
        members: list[Member] = []
        url: str | None = endpoint.contextMembershipsUrl

        while url is not None:
            response = sendAuthorizedRequest(
                self.httpClient,
                self.accessTokenService,
                registration,
                "GET",
                url,
                [SCOPE_READONLY],
                accept=CONTENT_TYPE_MEMBERSHIP_CONTAINER,
                serviceName=SERVICE_NAME,
            )
            decoded = jsonObject(decodeJsonBody(response, url, SERVICE_NAME))
            entries = jsonList(decoded.get("members")) if decoded is not None else None
            if entries is None:
                raise ServiceException(f'NRPS response from "{url}" did not contain a "members" array.')

            members.extend(Member.fromResponseData(entry) for entry in entries)
            url = self._nextPageUrl(response)

        return members

    @staticmethod
    def _nextPageUrl(response: httpx.Response) -> str | None:
        match = NEXT_LINK_PATTERN.search(response.headers.get("Link", ""))
        return match.group(1) if match else None
