"""Tests for AGS line item CRUD, score publishing, and result reads against the fixture server."""

import json

import httpx
import pytest

from arrayCache import ArrayCache
from fixturePlatformServer import FixturePlatformServer
from lti1p3.accessToken import AccessTokenService
from lti1p3.ags import ActivityProgress, AssignmentsGradesService, GradingProgress, LineItem, Score
from lti1p3.claims import AgsEndpoint
from lti1p3.exceptions import ServiceException
from lti1p3.registration import Registration, ToolKeyPair
from lti1p3.security import generateKeyPair

ISSUER = "https://example.brightspace.com"
LINE_ITEM_SCOPE = "https://purl.imsglobal.org/spec/lti-ags/scope/lineitem"


@pytest.fixture(scope="module")
def toolKeyPair() -> ToolKeyPair:
    return generateKeyPair("tool-kid")


class AgsHarness:
    """A registration pointed at the fixture server, with a token already scripted."""

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
        self.service = AssignmentsGradesService(httpClient, AccessTokenService(httpClient, ArrayCache()))
        server.queueResponse("POST", "/token", 200, {}, json.dumps({"access_token": "access-token-1", "expires_in": 3600}))

    def endpoint(self) -> AgsEndpoint:
        endpoint = AgsEndpoint.fromClaimValue(
            {"scope": [LINE_ITEM_SCOPE], "lineitems": self.server.baseUrl() + "/ags/lineitems"}
        )
        assert endpoint is not None
        return endpoint

    def lineItemUrl(self) -> str:
        return self.server.baseUrl() + "/ags/lineitems/1"

    def queue(self, method: str, path: str, status: int, body: object) -> None:
        self.server.queueResponse(method, path, status, {}, body if isinstance(body, str) else json.dumps(body))


@pytest.fixture
def ags(server: FixturePlatformServer, httpClient: httpx.Client, toolKeyPair: ToolKeyPair) -> AgsHarness:
    return AgsHarness(server, httpClient, toolKeyPair)


class TestLineItems:
    def test_createsALineItemAndReturnsItWithTheAssignedId(self, ags: AgsHarness):
        ags.queue("POST", "/ags/lineitems", 201, {"id": ags.lineItemUrl(), "scoreMaximum": 100.0, "label": "Assignment 1"})
        result = ags.service.createLineItem(ags.registration, ags.endpoint(), LineItem(None, 100.0, "Assignment 1"))
        assert result.id == ags.lineItemUrl()
        assert result.scoreMaximum == 100.0

    def test_sendsTheAccessTokenAndContentTypesOnTheCreateRequest(self, ags: AgsHarness):
        ags.queue("POST", "/ags/lineitems", 201, {"id": "x", "scoreMaximum": 100.0, "label": "Assignment 1"})
        ags.service.createLineItem(ags.registration, ags.endpoint(), LineItem(None, 100.0, "Assignment 1"))

        request = ags.server.receivedRequests("POST", "/ags/lineitems")[0]
        assert request.header("Authorization") == "Bearer access-token-1"
        assert request.header("Content-Type") == "application/vnd.ims.lis.v2.lineitem+json"
        assert request.header("Accept") == "application/vnd.ims.lis.v2.lineitem+json"
        assert json.loads(request.body) == {"scoreMaximum": 100.0, "label": "Assignment 1"}

    def test_requestsTheLineItemScopeForTheToken(self, ags: AgsHarness):
        ags.queue("GET", "/ags/lineitems", 200, [])
        ags.service.listLineItems(ags.registration, ags.endpoint())
        assert f"scope={LINE_ITEM_SCOPE}" in ags.server.receivedRequests("POST", "/token")[0].body.replace("%3A", ":").replace("%2F", "/")

    def test_listsLineItems(self, ags: AgsHarness):
        ags.queue(
            "GET",
            "/ags/lineitems",
            200,
            [{"id": "a", "scoreMaximum": 10.0, "label": "A"}, {"id": "b", "scoreMaximum": 20.0, "label": "B"}],
        )
        lineItems = ags.service.listLineItems(ags.registration, ags.endpoint())
        assert [lineItem.id for lineItem in lineItems] == ["a", "b"]
        request = ags.server.receivedRequests("GET", "/ags/lineitems")[0]
        assert request.header("Accept") == "application/vnd.ims.lis.v2.lineitemcontainer+json"

    def test_throwsWhenTheLineItemListIsNotAJsonArray(self, ags: AgsHarness):
        ags.queue("GET", "/ags/lineitems", 200, {"not": "a list"})
        with pytest.raises(ServiceException, match="was not a JSON array"):
            ags.service.listLineItems(ags.registration, ags.endpoint())

    def test_getsALineItemByUrl(self, ags: AgsHarness):
        ags.queue("GET", "/ags/lineitems/1", 200, {"id": ags.lineItemUrl(), "scoreMaximum": 100.0, "label": "Assignment 1"})
        assert ags.service.getLineItem(ags.registration, ags.lineItemUrl()).id == ags.lineItemUrl()

    def test_updatesALineItem(self, ags: AgsHarness):
        ags.queue("PUT", "/ags/lineitems/1", 200, {"id": ags.lineItemUrl(), "scoreMaximum": 50.0, "label": "Renamed"})
        result = ags.service.updateLineItem(
            ags.registration, ags.lineItemUrl(), LineItem(ags.lineItemUrl(), 50.0, "Renamed")
        )
        assert result.label == "Renamed"
        assert result.scoreMaximum == 50.0

    def test_deletesALineItem(self, ags: AgsHarness):
        ags.queue("DELETE", "/ags/lineitems/1", 204, "")
        ags.service.deleteLineItem(ags.registration, ags.lineItemUrl())
        assert len(ags.server.receivedRequests("DELETE", "/ags/lineitems/1")) == 1

    def test_throwsServiceExceptionOnNonSuccessfulStatus(self, ags: AgsHarness):
        ags.queue("POST", "/ags/lineitems", 403, {"error": "forbidden"})
        with pytest.raises(ServiceException, match="HTTP status 403"):
            ags.service.createLineItem(ags.registration, ags.endpoint(), LineItem(None, 100.0, "Assignment 1"))

    def test_throwsWhenTheResponseIsNotJson(self, ags: AgsHarness):
        ags.queue("GET", "/ags/lineitems/1", 200, "not json")
        with pytest.raises(ServiceException, match="not valid JSON"):
            ags.service.getLineItem(ags.registration, ags.lineItemUrl())


class TestScoresAndResults:
    def test_publishesAScoreWithCorrectBodyAndContentType(self, ags: AgsHarness):
        ags.queue("POST", "/ags/lineitems/1/scores", 200, {})
        score = Score("user-1", ActivityProgress.Completed, GradingProgress.FullyGraded, scoreGiven=8.5, scoreMaximum=10.0)
        ags.service.publishScore(ags.registration, ags.lineItemUrl() + "/", score)

        requests = ags.server.receivedRequests("POST", "/ags/lineitems/1/scores")
        assert len(requests) == 1
        assert requests[0].header("Content-Type") == "application/vnd.ims.lis.v1.score+json"
        sent = json.loads(requests[0].body)
        assert sent["userId"] == "user-1"
        assert sent["scoreGiven"] == 8.5
        assert sent["activityProgress"] == "Completed"
        assert sent["gradingProgress"] == "FullyGraded"

    def test_listsResults(self, ags: AgsHarness):
        ags.queue(
            "GET",
            "/ags/lineitems/1/results",
            200,
            [{"id": "r1", "scoreOf": ags.lineItemUrl(), "userId": "user-1", "resultScore": 8.5, "resultMaximum": 10.0}],
        )
        results = ags.service.listResults(ags.registration, ags.lineItemUrl())
        assert len(results) == 1
        assert results[0].userId == "user-1"
        assert results[0].resultScore == 8.5
        request = ags.server.receivedRequests("GET", "/ags/lineitems/1/results")[0]
        assert request.header("Accept") == "application/vnd.ims.lis.v2.resultcontainer+json"

    def test_throwsWhenTheResultListIsNotAJsonArray(self, ags: AgsHarness):
        ags.queue("GET", "/ags/lineitems/1/results", 200, {})
        with pytest.raises(ServiceException, match="was not a JSON array"):
            ags.service.listResults(ags.registration, ags.lineItemUrl())
