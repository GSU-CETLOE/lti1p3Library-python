"""A real HTTP server standing in for the platform in tests.

JWKS fetches, token exchanges, AGS, and NRPS calls are exercised against
real HTTP rather than a mocked client. Script what the server answers with
queueResponse() and inspect what it received with receivedRequests(). The
server runs in a background thread of the test process, so the store it
shares with the tests is plain memory behind a lock.
"""

import json
import threading
from collections.abc import Mapping
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qsl, urlsplit


@dataclass(frozen=True)
class FixtureResponse:
    """A scripted answer for one route."""

    status: int
    headers: dict[str, str]
    body: str


@dataclass(frozen=True)
class RecordedRequest:
    """What the server saw for one request."""

    headers: dict[str, str]
    body: str
    query: dict[str, str] = field(default_factory=dict[str, str])

    def header(self, name: str) -> str | None:
        """Look up a header without caring about case."""
        wanted = name.lower()
        for key, value in self.headers.items():
            if key.lower() == wanted:
                return value
        return None


class FixtureStore:
    """Scripted responses and recorded requests, keyed by method and path.

    A queue of responses is consumed in order and the last one sticks, so a
    route scripted once answers every call, and a route scripted twice
    answers differently the first time.
    """

    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.responses: dict[tuple[str, str], list[FixtureResponse]] = {}
        self.requests: dict[tuple[str, str], list[RecordedRequest]] = {}

    def queueResponse(self, method: str, path: str, status: int, headers: Mapping[str, str], body: str) -> None:
        """Script a response for the route."""
        with self.lock:
            self.responses.setdefault(self._route(method, path), []).append(
                FixtureResponse(status, dict(headers), body)
            )

    def nextResponse(self, method: str, path: str) -> FixtureResponse | None:
        """Take the next scripted response for the route, keeping the last one; None when nothing is scripted."""
        with self.lock:
            queue = self.responses.get(self._route(method, path))
            if not queue:
                return None
            return queue.pop(0) if len(queue) > 1 else queue[0]

    def recordRequest(
        self, method: str, path: str, headers: Mapping[str, str], body: str, query: Mapping[str, str]
    ) -> None:
        """Remember a request the server received."""
        with self.lock:
            self.requests.setdefault(self._route(method, path), []).append(
                RecordedRequest(dict(headers), body, dict(query))
            )

    def requestsFor(self, method: str, path: str) -> list[RecordedRequest]:
        """Every request received for the route, in order."""
        with self.lock:
            return list(self.requests.get(self._route(method, path), []))

    @staticmethod
    def _route(method: str, path: str) -> tuple[str, str]:
        return (method.upper(), "/" + path.strip("/"))


class FixturePlatformServer:
    """A ThreadingHTTPServer on an ephemeral loopback port that answers from a FixtureStore."""

    def __init__(self) -> None:
        self.store = FixtureStore()
        store = self.store

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, format: str, *args: object) -> None:  # noqa: A002  (signature is fixed by the base class)
                pass

            def _serve(self) -> None:
                parts = urlsplit(self.path)
                query = dict(parse_qsl(parts.query, keep_blank_values=True))
                length = int(self.headers.get("Content-Length") or 0)
                body = self.rfile.read(length).decode("utf-8") if length else ""
                store.recordRequest(self.command, parts.path, dict(self.headers.items()), body, query)

                response = store.nextResponse(self.command, parts.path)
                if response is None:
                    payload = json.dumps({"error": "no_fixture_configured", "method": self.command, "path": parts.path})
                    self._write(404, {"Content-Type": "application/json"}, payload)
                    return

                self._write(response.status, response.headers, response.body)

            def _write(self, status: int, headers: Mapping[str, str], body: str) -> None:
                encoded = body.encode("utf-8")
                self.send_response(status)
                for name, value in headers.items():
                    self.send_header(name, value)
                self.send_header("Content-Length", str(len(encoded)))
                self.end_headers()
                self.wfile.write(encoded)

            do_GET = _serve
            do_POST = _serve
            do_PUT = _serve
            do_DELETE = _serve

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.stopped = False

    @classmethod
    def start(cls) -> "FixturePlatformServer":
        """Create and start a server."""
        server = cls()
        server.thread.start()
        return server

    def baseUrl(self) -> str:
        """The http://127.0.0.1:<port> root of this server."""
        return f"http://127.0.0.1:{self.server.server_address[1]}"

    def queueResponse(self, method: str, path: str, status: int, headers: Mapping[str, str], body: str) -> None:
        """Script a response for a route."""
        self.store.queueResponse(method, path, status, headers, body)

    def receivedRequests(self, method: str, path: str) -> list[RecordedRequest]:
        """Every request received for the route, in order."""
        return self.store.requestsFor(method, path)

    def stop(self) -> None:
        """Shut the server down; safe to call more than once."""
        if self.stopped:
            return
        self.stopped = True
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)
