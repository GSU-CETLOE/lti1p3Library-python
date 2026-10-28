"""Tests for the scripted response and recorded request store behind the fixture server."""

from fixturePlatformServer import FixtureResponse, FixtureStore


class TestFixtureStore:
    def test_nextResponseReturnsNoneWhenNothingConfigured(self):
        assert FixtureStore().nextResponse("GET", "/jwks") is None

    def test_singleQueuedResponseIsServedRepeatedly(self):
        store = FixtureStore()
        headers = {"Content-Type": "application/json"}
        store.queueResponse("GET", "/jwks", 200, headers, '{"keys":[]}')
        first = store.nextResponse("GET", "/jwks")
        second = store.nextResponse("GET", "/jwks")
        assert first == FixtureResponse(200, headers, '{"keys":[]}')
        assert second == first

    def test_multipleQueuedResponsesAreConsumedInOrderThenStickToTheLast(self):
        store = FixtureStore()
        store.queueResponse("POST", "/token", 500, {}, "first")
        store.queueResponse("POST", "/token", 200, {}, "second")
        responses = [store.nextResponse("POST", "/token") for _ in range(3)]
        assert [response.status for response in responses if response] == [500, 200, 200]
        assert [response.body for response in responses if response] == ["first", "second", "second"]

    def test_responsesForDifferentRoutesAreIndependent(self):
        store = FixtureStore()
        store.queueResponse("GET", "/jwks", 200, {}, "jwks-body")
        store.queueResponse("GET", "/other", 200, {}, "other-body")
        jwks = store.nextResponse("GET", "/jwks")
        other = store.nextResponse("GET", "/other")
        assert jwks is not None and jwks.body == "jwks-body"
        assert other is not None and other.body == "other-body"

    def test_requestsForReturnsEmptyListWhenNoneRecorded(self):
        assert FixtureStore().requestsFor("GET", "/jwks") == []

    def test_recordedRequestsAreReturnedInOrder(self):
        store = FixtureStore()
        store.recordRequest("POST", "/ags/scores", {"Authorization": "Bearer one"}, "body-1", {})
        store.recordRequest("POST", "/ags/scores", {"authorization": "Bearer two"}, "body-2", {"page": "2"})
        requests = store.requestsFor("POST", "/ags/scores")
        assert len(requests) == 2
        assert requests[0].header("Authorization") == "Bearer one"
        assert requests[0].body == "body-1"
        assert requests[0].query == {}
        assert requests[1].header("Authorization") == "Bearer two"
        assert requests[1].body == "body-2"
        assert requests[1].query == {"page": "2"}

    def test_routesDistinguishNestedPathsAndIgnoreTrailingSlashes(self):
        store = FixtureStore()
        store.queueResponse("GET", "/ags/lineitems", 200, {}, "lineitems")
        store.queueResponse("GET", "/ags/lineitems/1", 200, {}, "lineitem-1")
        collection = store.nextResponse("GET", "/ags/lineitems/")
        single = store.nextResponse("get", "/ags/lineitems/1")
        assert collection is not None and collection.body == "lineitems"
        assert single is not None and single.body == "lineitem-1"
