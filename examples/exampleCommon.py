"""Shared pieces of the example tool and platform simulator.

The example is a two-process demo: tool.py is a minimal LTI 1.3 tool built
on the library, and simulator.py stands in for a platform like Brightspace
so the whole login, launch, AGS, NRPS, and Deep Linking flow runs locally.
Both read the config and keys that setupExample.py writes under one "home"
directory. Everything here is demo code, not part of the library.
"""

import html
import json
from collections.abc import Mapping
from http.server import BaseHTTPRequestHandler
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, urlsplit

from lti1p3 import FileCache, HttpResponse, Registration, ToolKeyPair

DEFAULT_HOME = Path(__file__).resolve().parent.parent / "working" / "example"
TOOL_KID = "tool-key-1"
SIMULATOR_KID = "simulator-key-1"


def loadConfig(home: Path) -> dict[str, Any]:
    """Read config.json from the home directory, or explain how to create it."""
    path = home / "config.json"
    if not path.is_file():
        raise SystemExit(f"Missing {path}. Run: python examples/setupExample.py --home {home}")
    return json.loads(path.read_text())


def loadKeyPair(home: Path, kid: str) -> ToolKeyPair:
    """Read a key pair that setupExample.py wrote to the keys directory."""
    keysDir = home / "keys"
    privatePath = keysDir / f"{kid}.private.pem"
    publicPath = keysDir / f"{kid}.public.pem"
    if not privatePath.is_file() or not publicPath.is_file():
        raise SystemExit(f"Missing key files for {kid} in {keysDir}. Run: python examples/setupExample.py --home {home}")
    return ToolKeyPair(kid, privatePath.read_text(), publicPath.read_text())


def toolRegistration(home: Path, config: Mapping[str, Any]) -> Registration:
    """The single Registration this demo tool has: the simulator, or whatever config.json points at."""
    simulatorBaseUrl = str(config["simulator_base_url"])
    platformAudience = config.get("platform_audience")
    return Registration(
        simulatorBaseUrl,
        str(config["client_id"]),
        [str(config["deployment_id"])],
        simulatorBaseUrl + "/authenticate",
        simulatorBaseUrl + "/token",
        simulatorBaseUrl + "/jwks",
        [loadKeyPair(home, str(config["tool_kid"]))],
        platformAudience if isinstance(platformAudience, str) else None,
    )


def toolCache(home: Path) -> FileCache:
    """The library's file cache, kept under the home directory."""
    return FileCache(home / "cache")


class ConfigRegistrationRepository:
    """The simplest RegistrationRepositoryInterface: this demo only ever talks to one platform."""

    def __init__(self, registration: Registration) -> None:
        self.registration = registration

    def findForLoginInitiation(self, issuer: str, clientId: str | None) -> Registration | None:
        if issuer != self.registration.issuer:
            return None
        if clientId is not None and clientId != self.registration.clientId:
            return None
        return self.registration

    def findForLaunch(self, issuer: str, clientId: str, deploymentId: str) -> Registration | None:
        if issuer != self.registration.issuer or clientId != self.registration.clientId:
            return None
        return self.registration if self.registration.hasDeployment(deploymentId) else None


class LaunchStore:
    """Remembers the last validated launch in a JSON file, standing in for a web session.

    The launch's `state` is single use, so the follow-up AGS, NRPS, and Deep
    Linking actions (separate HTTP requests) reuse what the launch already
    validated instead of validating again. A real tool keeps this in its
    session; a one-file store is enough for a single-user demo.
    """

    def __init__(self, home: Path) -> None:
        self.path = home / "last-launch.json"

    def save(self, launch: Mapping[str, Any]) -> None:
        self.path.write_text(json.dumps(launch, indent=2))

    def load(self) -> dict[str, Any] | None:
        return json.loads(self.path.read_text()) if self.path.is_file() else None


def escape(value: object) -> str:
    """HTML-escape a value for inclusion in a page."""
    return html.escape(str(value), quote=True)


def renderPage(title: str, bodyHtml: str) -> str:
    """Wrap body HTML in a bare-bones page. The example is about LTI, not front-end polish."""
    return f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <title>{escape(title)}</title>
    <style>
        body {{ font-family: system-ui, sans-serif; max-width: 780px; margin: 2rem auto; line-height: 1.5; padding: 0 1rem; }}
        pre {{ background: #f4f4f4; padding: 1rem; overflow-x: auto; }}
        code {{ background: #f4f4f4; padding: 0.1rem 0.3rem; }}
        a.button {{ display: inline-block; padding: 0.5rem 1rem; background: #2a6; color: #fff; text-decoration: none; border-radius: 4px; margin: 0.25rem 0.25rem 0.25rem 0; }}
        table {{ border-collapse: collapse; margin: 1rem 0; }}
        td, th {{ border: 1px solid #ccc; padding: 0.25rem 0.5rem; text-align: left; }}
        .error {{ color: #a00; background: #fee; padding: 1rem; border-radius: 4px; }}
    </style>
</head>
<body>
<h1>{escape(title)}</h1>
{bodyHtml}
</body>
</html>
"""


class ExampleHandler(BaseHTTPRequestHandler):
    """Request handler base for both demo servers: parsing helpers and response helpers.

    Subclasses implement route(method, path) and send exactly one response.
    """

    home: Path

    def do_GET(self) -> None:  # noqa: N802  (the base class fixes these names)
        self._dispatch("GET")

    def do_POST(self) -> None:  # noqa: N802
        self._dispatch("POST")

    def do_PUT(self) -> None:  # noqa: N802
        self._dispatch("PUT")

    def do_DELETE(self) -> None:  # noqa: N802
        self._dispatch("DELETE")

    def _dispatch(self, method: str) -> None:
        path = urlsplit(self.path).path.rstrip("/") or "/"
        try:
            self.route(method, path)
        except SystemExit as error:
            self.sendErrorPage("Configuration problem", str(error))

    def route(self, method: str, path: str) -> None:
        """Handle one request; subclasses override."""
        self.sendNotFound(method, path)

    def queryParams(self) -> dict[str, str]:
        """The query string as a dict (last value wins)."""
        return dict(parse_qsl(urlsplit(self.path).query, keep_blank_values=True))

    def readBody(self) -> bytes:
        """The raw request body."""
        length = int(self.headers.get("Content-Length") or 0)
        return self.rfile.read(length) if length else b""

    def formParams(self) -> dict[str, str]:
        """An application/x-www-form-urlencoded body as a dict."""
        return dict(parse_qsl(self.readBody().decode("utf-8"), keep_blank_values=True))

    def jsonBody(self) -> Any:
        """A JSON request body, decoded."""
        return json.loads(self.readBody().decode("utf-8") or "null")

    def bearerToken(self) -> str | None:
        """The bearer token from the Authorization header, if any."""
        header = self.headers.get("Authorization") or ""
        return header[len("Bearer ") :] if header.startswith("Bearer ") else None

    def send(self, response: HttpResponse) -> None:
        """Send one of the library's HttpResponse values as-is."""
        self.sendText(response.statusCode, response.headers, response.body)

    def sendHtml(self, status: int, page: str) -> None:
        self.sendText(status, {"Content-Type": "text/html; charset=UTF-8"}, page)

    def sendJson(self, status: int, data: object) -> None:
        self.sendText(status, {"Content-Type": "application/json"}, json.dumps(data, indent=2))

    def sendErrorPage(self, title: str, message: str) -> None:
        self.sendHtml(400, renderPage(title, f'<p class="error">{escape(message)}</p>'))

    def sendNotFound(self, method: str, path: str) -> None:
        self.sendText(404, {"Content-Type": "text/plain"}, f"Not found: {method} {path}")

    def sendText(self, status: int, headers: Mapping[str, str], body: str) -> None:
        encoded = body.encode("utf-8")
        self.send_response(status)
        for name, value in headers.items():
            self.send_header(name, value)
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)


def portOf(url: str) -> int:
    """The port a base URL names, so each server listens where config.json says it lives."""
    port = urlsplit(url).port
    if port is None:
        raise SystemExit(f"{url} must name an explicit port for the demo servers.")
    return port
