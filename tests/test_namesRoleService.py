"""Tests for NRPS roster fetches, including Link-header pagination, against the fixture server."""

import json

import httpx
import pytest

from arrayCache import ArrayCache
from fixturePlatformServer import FixturePlatformServer
from lti1p3.accessToken import AccessTokenService
from lti1p3.claims import NrpsEndpoint
from lti1p3.exceptions import ServiceException
from lti1p3.nrps import Member, NamesRoleService
from lti1p3.registration import Registration, ToolKeyPair
from lti1p3.security import generateKeyPair

ISSUER = "https://example.brightspace.com"
INSTRUCTOR = "http://purl.imsglobal.org/vocab/lis/v2/membership#Instructor"
NO_ROLES: list[str] = []


@pytest.fixture(scope="module")
def toolKeyPair() -> ToolKeyPair:
    return generateKeyPair("tool-kid")


class NrpsHarness:
    def __init__(self, server: FixturePlatformServer, httpClient: httpx.Client, toolKeyPair: ToolKeyPair) -> None:
        self.server = server
        self.registration = Registration(
            ISSUER,
            "client-1",
            ["deployment-1"],
            ISSUER + "/d2l/lti/authenticate",
            server.baseUrl() + "/token",
            ISSUER + "/d2l/.well-known/jwks",
            [toolKeyPair],
        )
        self.service = NamesRoleService(httpClient, AccessTokenService(httpClient, ArrayCache()))
        server.queueResponse("POST", "/token", 200, {}, json.dumps({"access_token": "access-token-1", "expires_in": 3600}))

    def endpoint(self) -> NrpsEndpoint:
        endpoint = NrpsEndpoint.fromClaimValue(
            {"context_memberships_url": self.server.baseUrl() + "/nrps/memberships", "service_versions": ["2.0"]}
        )
        assert endpoint is not None
        return endpoint

    def queue(self, status: int, body: object, headers: dict[str, str] | None = None) -> None:
        payload = body if isinstance(body, str) else json.dumps(body)
        self.server.queueResponse("GET", "/nrps/memberships", status, headers or {}, payload)


@pytest.fixture
def nrps(server: FixturePlatformServer, httpClient: httpx.Client, toolKeyPair: ToolKeyPair) -> NrpsHarness:
    return NrpsHarness(server, httpClient, toolKeyPair)


class TestMember:
    def test_parsesAllFields(self):
        member = Member.fromResponseData(
            {
                "status": "Active",
                "name": "Ada Lovelace",
                "user_id": "user-1",
                "roles": [INSTRUCTOR],
                "email": "ada@example.com",
                "picture": "https://example.com/ada.jpg",
                "given_name": "Ada",
                "family_name": "Lovelace",
                "middle_name": None,
            }
        )
        assert member.userId == "user-1"
        assert member.status == "Active"
        assert member.name == "Ada Lovelace"
        assert member.roles == [INSTRUCTOR]
        assert member.email == "ada@example.com"
        assert member.picture == "https://example.com/ada.jpg"
        assert member.givenName == "Ada"
        assert member.familyName == "Lovelace"
        assert member.middleName is None

    def test_statusDefaultsToActiveAndRolesToEmptyWhenAbsent(self):
        member = Member.fromResponseData({"user_id": "user-1"})
        assert member.status == "Active"
        assert member.roles == []
        assert member.name is None
        assert member.email is None

    def test_throwsWhenNotAnObjectOrMissingUserId(self):
        with pytest.raises(ServiceException):
            Member.fromResponseData("not-an-object")
        with pytest.raises(ServiceException):
            Member.fromResponseData({"name": "Ada Lovelace"})


class TestNamesRoleService:
    def test_fetchesTheRoster(self, nrps: NrpsHarness):
        nrps.queue(
            200,
            {
                "id": nrps.server.baseUrl() + "/nrps/memberships",
                "members": [
                    {"status": "Active", "name": "Ada Lovelace", "user_id": "user-1", "roles": NO_ROLES},
                    {"status": "Active", "name": "Alan Turing", "user_id": "user-2", "roles": NO_ROLES},
                ],
            },
        )
        members = nrps.service.getMembers(nrps.registration, nrps.endpoint())
        assert [member.userId for member in members] == ["user-1", "user-2"]

    def test_sendsTheAccessTokenAsABearerHeaderAndTheMembershipAcceptType(self, nrps: NrpsHarness):
        nrps.queue(200, {"members": []})
        nrps.service.getMembers(nrps.registration, nrps.endpoint())
        request = nrps.server.receivedRequests("GET", "/nrps/memberships")[0]
        assert request.header("Authorization") == "Bearer access-token-1"
        assert request.header("Accept") == "application/vnd.ims.lti-nrps.v2.membershipcontainer+json"

    def test_followsLinkHeaderPaginationAcrossMultiplePages(self, nrps: NrpsHarness):
        secondPageUrl = nrps.server.baseUrl() + "/nrps/memberships?page=2"
        nrps.queue(200, {"members": [{"user_id": "user-1", "roles": NO_ROLES}]}, {"Link": f'<{secondPageUrl}>; rel="next"'})
        nrps.queue(200, {"members": [{"user_id": "user-2", "roles": NO_ROLES}]})

        members = nrps.service.getMembers(nrps.registration, nrps.endpoint())

        assert [member.userId for member in members] == ["user-1", "user-2"]
        requests = nrps.server.receivedRequests("GET", "/nrps/memberships")
        assert len(requests) == 2
        assert requests[1].query == {"page": "2"}

    def test_stopsWhenNoNextLinkIsPresent(self, nrps: NrpsHarness):
        nrps.queue(200, {"members": [{"user_id": "user-1", "roles": NO_ROLES}]}, {"Link": '<https://x>; rel="prev"'})
        nrps.service.getMembers(nrps.registration, nrps.endpoint())
        assert len(nrps.server.receivedRequests("GET", "/nrps/memberships")) == 1

    def test_throwsWhenHttpStatusIsNotSuccessful(self, nrps: NrpsHarness):
        nrps.queue(403, {"error": "forbidden"})
        with pytest.raises(ServiceException, match="HTTP status 403"):
            nrps.service.getMembers(nrps.registration, nrps.endpoint())

    def test_throwsWhenResponseHasNoMembersArray(self, nrps: NrpsHarness):
        nrps.queue(200, {})
        with pytest.raises(ServiceException, match='did not contain a "members" array'):
            nrps.service.getMembers(nrps.registration, nrps.endpoint())

    def test_throwsWhenResponseIsNotJson(self, nrps: NrpsHarness):
        nrps.queue(200, "not json")
        with pytest.raises(ServiceException, match="not valid JSON"):
            nrps.service.getMembers(nrps.registration, nrps.endpoint())
