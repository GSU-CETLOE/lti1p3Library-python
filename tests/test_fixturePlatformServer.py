"""Tests for the real HTTP fixture server the integration tests run against."""

import httpx
import pytest

from fixturePlatformServer import FixturePlatformServer


class TestFixturePlatformServer:
    def test_respondsWithTheConfiguredResponseForARoute(self, server: FixturePlatformServer, httpClient: httpx.Client):
        server.queueResponse("GET", "/jwks", 200, {"Content-Type": "application/json"}, '{"keys":[]}')
        response = httpClient.get(server.baseUrl() + "/jwks")
        assert response.status_code == 200
        assert response.text == '{"keys":[]}'
        assert response.headers["Content-Type"] == "application/json"

    def test_returnsNotFoundForAnUnconfiguredRoute(self, server: FixturePlatformServer, httpClient: httpx.Client):
        assert httpClient.get(server.baseUrl() + "/never-configured").status_code == 404

    def test_recordsTheHeadersBodyAndQueryOfReceivedRequests(
        self, server: FixturePlatformServer, httpClient: httpx.Client
    ):
        server.queueResponse("POST", "/ags/scores", 200, {}, "{}")
        httpClient.post(
            server.baseUrl() + "/ags/scores?page=2",
            headers={"Authorization": "Bearer test-token"},
            content='{"scoreGiven":10}',
        )
        requests = server.receivedRequests("POST", "/ags/scores")
        assert len(requests) == 1
        assert requests[0].header("Authorization") == "Bearer test-token"
        assert requests[0].body == '{"scoreGiven":10}'
        assert requests[0].query == {"page": "2"}

    def test_twoServersRunIndependentlyOnDifferentPorts(self, server: FixturePlatformServer, httpClient: httpx.Client):
        second = FixturePlatformServer.start()
        try:
            assert server.baseUrl() != second.baseUrl()
            server.queueResponse("GET", "/route", 200, {}, "from-first")
            second.queueResponse("GET", "/route", 200, {}, "from-second")
            assert httpClient.get(server.baseUrl() + "/route").text == "from-first"
            assert httpClient.get(second.baseUrl() + "/route").text == "from-second"
        finally:
            second.stop()

    def test_stopTerminatesTheServer(self, httpClient: httpx.Client):
        server = FixturePlatformServer.start()
        baseUrl = server.baseUrl()
        server.stop()
        with pytest.raises(httpx.ConnectError):
            httpClient.get(baseUrl + "/anything")
