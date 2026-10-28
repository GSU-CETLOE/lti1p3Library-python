"""A platform simulator standing in for Brightspace, so the example tool can be exercised locally.

It offers an OIDC authentication endpoint, a JWKS, an OAuth2 token endpoint
that really verifies the tool's client assertion against the tool's JWKS,
and small AGS and NRPS endpoints backed by a JSON file. Not part of the
library, which implements only the tool side; demo code standing in for
what a real platform does.

Routes:
    GET  /                      "a course with a tool link in it"
    GET  /jwks                  the simulator's public key
    GET  /authenticate          issues a signed id_token and form-posts it to the tool
    POST /token                 verifies the client assertion, issues an access token
    *    /ags/lineitems...      Assignment and Grades Service
    GET  /nrps/memberships      Names and Role Provisioning Service
    POST /deep-link-return      verifies the tool's Deep Linking response JWT

Usage:
    python examples/simulator.py [--home DIR]
"""

import argparse
import json
import re
import sys
import time
from http.server import ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

import httpx
import jwt

sys.path.insert(0, str(Path(__file__).resolve().parent))

from exampleCommon import DEFAULT_HOME, ExampleHandler, escape, loadConfig, loadKeyPair, portOf, renderPage  # noqa: E402

from lti1p3 import ToolKeyPair, buildJwk, claimUris, renderFormPost  # noqa: E402

INSTRUCTOR = "http://purl.imsglobal.org/vocab/lis/v2/membership#Instructor"
LEARNER = "http://purl.imsglobal.org/vocab/lis/v2/membership#Learner"
AGS_SCOPES = [
    "https://purl.imsglobal.org/spec/lti-ags/scope/lineitem",
    "https://purl.imsglobal.org/spec/lti-ags/scope/score",
    "https://purl.imsglobal.org/spec/lti-ags/scope/result.readonly",
]


class Database:
    """A JSON-file gradebook, just enough for the AGS endpoints to behave statefully."""

    def __init__(self, path: Path) -> None:
        self.path = path
        if path.is_file():
            self.data: dict[str, Any] = json.loads(path.read_text())
        else:
            self.data = {"lineItems": {}, "results": {}, "nextLineItemId": 1}
            self._write()

    def _write(self) -> None:
        self.path.write_text(json.dumps(self.data, indent=2))

    def ensureDefaultLineItem(self) -> dict[str, Any]:
        """A demo line item, created on first use, so the single-line-item AGS flow has something to score."""
        lineItems: dict[str, Any] = self.data["lineItems"]
        if lineItems:
            return next(iter(lineItems.values()))
        return self.createLineItem({"scoreMaximum": 10.0, "label": "Demo Assignment", "resourceLinkId": "demo-resource-link"})

    def createLineItem(self, lineItem: dict[str, Any]) -> dict[str, Any]:
        lineItemId = str(self.data["nextLineItemId"])
        lineItem["id"] = lineItemId
        self.data["lineItems"][lineItemId] = lineItem
        self.data["nextLineItemId"] += 1
        self._write()
        return lineItem

    def getLineItem(self, lineItemId: str) -> dict[str, Any] | None:
        return self.data["lineItems"].get(lineItemId)

    def listLineItems(self) -> list[dict[str, Any]]:
        return list(self.data["lineItems"].values())

    def updateLineItem(self, lineItemId: str, lineItem: dict[str, Any]) -> dict[str, Any] | None:
        if lineItemId not in self.data["lineItems"]:
            return None
        lineItem["id"] = lineItemId
        self.data["lineItems"][lineItemId] = lineItem
        self._write()
        return lineItem

    def deleteLineItem(self, lineItemId: str) -> None:
        self.data["lineItems"].pop(lineItemId, None)
        self.data["results"].pop(lineItemId, None)
        self._write()

    def recordScore(self, lineItemId: str, score: dict[str, Any]) -> None:
        self.data["results"].setdefault(lineItemId, {})[str(score["userId"])] = score
        self._write()

    def listResults(self, lineItemId: str) -> list[dict[str, Any]]:
        return list(self.data["results"].get(lineItemId, {}).values())


class SimulatorHandler(ExampleHandler):
    """Routes for the platform simulator."""

    def route(self, method: str, path: str) -> None:
        self.config = loadConfig(self.home)
        self.toolBaseUrl = str(self.config["tool_base_url"])
        self.baseUrl = str(self.config["simulator_base_url"])
        self.keyPair = loadKeyPair(self.home, str(self.config["simulator_kid"]))
        self.database = Database(self.home / "simulator-db.json")

        if method == "GET" and path == "/":
            self.landing()
        elif method == "GET" and path == "/jwks":
            self.sendJson(200, {"keys": [buildJwk(self.keyPair)]})
        elif method == "GET" and path == "/authenticate":
            self.authenticate()
        elif method == "POST" and path == "/token":
            self.token()
        elif path.startswith("/ags/lineitems"):
            self.ags(method, path)
        elif method == "GET" and path == "/nrps/memberships":
            self.nrps()
        elif method == "POST" and path == "/deep-link-return":
            self.deepLinkReturn()
        else:
            self.sendNotFound(method, path)

    def landing(self) -> None:
        baseParams = {
            "iss": self.baseUrl,
            "login_hint": "demo-instructor-1",
            "target_link_uri": self.toolBaseUrl + "/launch",
            "lti_deployment_id": str(self.config["deployment_id"]),
        }
        loginUrl = self.toolBaseUrl + "/login?"
        resourceLinkUrl = loginUrl + urlencode({**baseParams, "lti_message_hint": "resource_link"})
        deepLinkingUrl = loginUrl + urlencode({**baseParams, "lti_message_hint": "deep_linking"})
        self.sendHtml(
            200,
            renderPage(
                "lti1p3 platform simulator",
                f"""<p>This stands in for a platform like D2L Brightspace, so the example tool can be launched and
tested locally without a real LMS. It is demo-only code, not part of the library.</p>
<p><a class="button" href="{escape(resourceLinkUrl)}">Launch as a resource link</a></p>
<p><a class="button" href="{escape(deepLinkingUrl)}">Launch as a Deep Linking request</a></p>""",
            ),
        )

    def authenticate(self) -> None:
        params = self.queryParams()
        required = ("client_id", "redirect_uri", "login_hint", "state", "nonce")
        if any(name not in params for name in required):
            self.sendErrorPage("Bad authentication request", "Missing one of client_id/redirect_uri/login_hint/state/nonce.")
            return

        now = int(time.time())
        claims: dict[str, Any] = {
            "iss": self.baseUrl,
            "aud": params["client_id"],
            "exp": now + 300,
            "iat": now,
            "nonce": params["nonce"],
            "sub": params["login_hint"],
            claimUris.VERSION: "1.3.0",
            claimUris.DEPLOYMENT_ID: str(self.config["deployment_id"]),
            claimUris.TARGET_LINK_URI: self.toolBaseUrl + "/launch",
            claimUris.ROLES: [INSTRUCTOR],
            claimUris.CONTEXT: {"id": "demo-context-1", "title": "Demo Course", "type": ["CourseSection"]},
            claimUris.TOOL_PLATFORM: {"guid": "simulator-guid", "name": "lti1p3 Simulator"},
            claimUris.CUSTOM: {"demo_custom_param": "hello-from-the-simulator"},
        }

        if params.get("lti_message_hint") == "deep_linking":
            claims[claimUris.MESSAGE_TYPE] = "LtiDeepLinkingRequest"
            claims[claimUris.DEEP_LINKING_SETTINGS] = {
                "deep_link_return_url": self.baseUrl + "/deep-link-return",
                "accept_types": ["ltiResourceLink"],
                "accept_multiple": False,
                "data": "demo-correlation-id",
            }
        else:
            lineItem = self.database.ensureDefaultLineItem()
            claims[claimUris.MESSAGE_TYPE] = "LtiResourceLinkRequest"
            claims[claimUris.RESOURCE_LINK] = {"id": "demo-resource-link", "title": "Demo Resource Link"}
            claims[claimUris.AGS_ENDPOINT] = {
                "scope": AGS_SCOPES,
                "lineitems": self.baseUrl + "/ags/lineitems",
                "lineitem": self.baseUrl + "/ags/lineitems/" + str(lineItem["id"]),
            }
            claims[claimUris.NRPS_ENDPOINT] = {
                "context_memberships_url": self.baseUrl + "/nrps/memberships",
                "service_versions": ["2.0"],
            }

        idToken = self._sign(claims)
        self.send(renderFormPost(params["redirect_uri"], {"state": params["state"], "id_token": idToken}))

    def token(self) -> None:
        form = self.formParams()
        clientAssertion = form.get("client_assertion")
        scope = form.get("scope", "")
        if clientAssertion is None:
            self.sendJson(400, {"error": "invalid_request", "error_description": "Missing client_assertion."})
            return

        # Mirrors the tool's Registration: the expected audience is the token endpoint unless overridden.
        platformAudience = self.config.get("platform_audience")
        expectedAudience = platformAudience if isinstance(platformAudience, str) else self.baseUrl + "/token"

        try:
            self._verifyToolJwt(clientAssertion, expectedAudience)
        except Exception as error:  # noqa: BLE001  (any verification failure is an invalid client)
            self.sendJson(400, {"error": "invalid_client", "error_description": str(error)})
            return

        now = int(time.time())
        accessToken = self._sign({"iss": "simulator", "scope": scope, "iat": now, "exp": now + 3600})
        self.sendJson(200, {"access_token": accessToken, "token_type": "Bearer", "expires_in": 3600, "scope": scope})

    def ags(self, method: str, path: str) -> None:
        if not self._requireValidAccessToken():
            return

        if path == "/ags/lineitems":
            if method == "GET":
                self.sendJson(200, self.database.listLineItems())
            elif method == "POST":
                self.sendJson(201, self.database.createLineItem(self.jsonBody()))
            else:
                self.sendJson(405, {"error": "method_not_allowed"})
            return

        scores = re.fullmatch(r"/ags/lineitems/([^/]+)/scores", path)
        if scores:
            if method != "POST":
                self.sendJson(405, {"error": "method_not_allowed"})
                return
            self.database.recordScore(scores.group(1), self.jsonBody())
            self.sendJson(200, {"success": True})
            return

        results = re.fullmatch(r"/ags/lineitems/([^/]+)/results", path)
        if results:
            if method != "GET":
                self.sendJson(405, {"error": "method_not_allowed"})
                return
            lineItemId = results.group(1)
            lineItemUrl = f"{self.baseUrl}/ags/lineitems/{lineItemId}"
            self.sendJson(
                200,
                [
                    {
                        "id": f"{lineItemUrl}/results/{score['userId']}",
                        "scoreOf": lineItemUrl,
                        "userId": score["userId"],
                        "resultScore": score.get("scoreGiven"),
                        "resultMaximum": score.get("scoreMaximum"),
                    }
                    for score in self.database.listResults(lineItemId)
                ],
            )
            return

        single = re.fullmatch(r"/ags/lineitems/([^/]+)", path)
        if single:
            lineItemId = single.group(1)
            if method == "GET":
                lineItem = self.database.getLineItem(lineItemId)
                self.sendJson(404, {"error": "not_found"}) if lineItem is None else self.sendJson(200, lineItem)
            elif method == "PUT":
                updated = self.database.updateLineItem(lineItemId, self.jsonBody())
                self.sendJson(404, {"error": "not_found"}) if updated is None else self.sendJson(200, updated)
            elif method == "DELETE":
                self.database.deleteLineItem(lineItemId)
                self.sendText(204, {}, "")
            else:
                self.sendJson(405, {"error": "method_not_allowed"})
            return

        self.sendJson(404, {"error": "not_found"})

    def nrps(self) -> None:
        if not self._requireValidAccessToken():
            return
        self.sendJson(
            200,
            {
                "id": self.baseUrl + "/nrps/memberships",
                "members": [
                    {"status": "Active", "name": "Ada Lovelace", "user_id": "demo-instructor-1", "roles": [INSTRUCTOR], "email": "ada@example.com"},
                    {"status": "Active", "name": "Alan Turing", "user_id": "demo-learner-1", "roles": [LEARNER], "email": "alan@example.com"},
                ],
            },
        )

    def deepLinkReturn(self) -> None:
        token = self.formParams().get("JWT")
        if token is None:
            self.sendErrorPage("Deep Linking response missing", 'Expected a form field named "JWT".')
            return

        try:
            claims = self._verifyToolJwt(token, self.baseUrl)
        except Exception as error:  # noqa: BLE001
            self.sendErrorPage("Deep Linking response verification failed", str(error))
            return

        items = claims.get(claimUris.CONTENT_ITEMS, [])
        itemsHtml = "".join(
            f"<li>{escape(item.get('type', '?'))}: {escape(item.get('title') or item.get('url') or '')}</li>" for item in items
        )
        self.sendHtml(
            200,
            renderPage(
                "Deep Linking response received and verified",
                f"""<p>The tool's signed response JWT verified successfully against its own JWKS.</p>
<p><strong>Selected content items:</strong></p>
<ul>{itemsHtml}</ul>
<p><a href="/">Back</a></p>""",
            ),
        )

    def _sign(self, claims: dict[str, Any]) -> str:
        return jwt.encode(claims, self.keyPair.privateKey, algorithm="RS256", headers={"kid": self.keyPair.kid})

    def _verifyToolJwt(self, token: str, expectedAudience: str) -> dict[str, Any]:
        """Fetch the tool's JWKS over real HTTP and verify a JWT the tool signed.

        The simulator's own small mirror of what JwksFetcher and JwtValidator do on the tool side.
        """
        with httpx.Client(timeout=10) as client:
            jwks = client.get(self.toolBaseUrl + "/jwks").json()
        keys = {key["kid"]: jwt.PyJWK.from_dict(key) for key in jwks["keys"]}
        kid = jwt.get_unverified_header(token).get("kid")
        if kid not in keys:
            raise ValueError(f'Unknown kid "{kid}" in the tool JWT.')

        claims = jwt.decode(token, keys[kid], algorithms=["RS256"], audience=expectedAudience)
        if "sub" in claims and claims["iss"] != claims["sub"]:
            raise ValueError('client_assertion "iss" and "sub" must match.')
        return claims

    def _requireValidAccessToken(self) -> bool:
        """Answer 401 and return False unless the request carries a bearer token the simulator issued."""
        token = self.bearerToken()
        if token is None:
            self.sendJson(401, {"error": "missing_bearer_token"})
            return False
        try:
            jwt.decode(token, self.keyPair.publicKey, algorithms=["RS256"])
        except jwt.PyJWTError:
            self.sendJson(401, {"error": "invalid_access_token"})
            return False
        return True


def simulatorKeyPairFor(home: Path) -> ToolKeyPair:
    """The simulator's signing key, for anything that wants to verify its tokens outside the server."""
    return loadKeyPair(home, str(loadConfig(home)["simulator_kid"]))


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the platform simulator for the example tool.")
    parser.add_argument("--home", type=Path, default=DEFAULT_HOME, help="Directory setupExample.py wrote to.")
    args = parser.parse_args()

    home: Path = args.home
    config = loadConfig(home)
    SimulatorHandler.home = home
    port = portOf(str(config["simulator_base_url"]))

    server = ThreadingHTTPServer(("127.0.0.1", port), SimulatorHandler)
    print(f"Platform simulator listening on {config['simulator_base_url']} (home: {home})", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
