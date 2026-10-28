"""A minimal LTI 1.3 tool built on the library, served with the standard library's HTTP server.

Routes:
    GET  /                  what this is
    GET  /jwks              the tool's public keys (JwksBuilder)
    GET  /login             OIDC login initiation (LoginInitiationHandler)
    POST /launch            the platform's authentication response (LaunchValidator)
    GET  /ags-score         publish a demo score and read results back (AssignmentsGradesService)
    GET  /nrps-roster       fetch the course roster (NamesRoleService)
    POST /deep-link-submit  sign and post back a Deep Linking response (LtiDeepLinkingResponse)

Usage:
    python examples/tool.py [--home DIR]
"""

import argparse
import sys
from http.server import ThreadingHTTPServer
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent))

from exampleCommon import (  # noqa: E402
    DEFAULT_HOME,
    ConfigRegistrationRepository,
    ExampleHandler,
    LaunchStore,
    escape,
    loadConfig,
    portOf,
    renderPage,
    toolCache,
    toolRegistration,
)

from lti1p3.claims import jsonObject  # noqa: E402
from lti1p3 import (  # noqa: E402
    AccessTokenService,
    ActivityProgress,
    AssignmentsGradesService,
    GradingProgress,
    JwksFetcher,
    JwtValidator,
    LaunchValidator,
    LoginInitiationHandler,
    LtiDeepLinkingRequest,
    LtiDeepLinkingResponse,
    LtiException,
    LtiResourceLinkContentItem,
    LtiResourceLinkRequest,
    NamesRoleService,
    NrpsEndpoint,
    Score,
    buildJwks,
    renderFormPost,
)


class ToolHandler(ExampleHandler):
    """Routes for the demo tool."""

    def route(self, method: str, path: str) -> None:
        config = loadConfig(self.home)
        self.config = config
        self.toolBaseUrl = str(config["tool_base_url"])
        self.simulatorBaseUrl = str(config["simulator_base_url"])
        self.registration = toolRegistration(self.home, config)
        self.cache = toolCache(self.home)
        self.launches = LaunchStore(self.home)

        if method == "GET" and path == "/":
            self.index()
        elif method == "GET" and path == "/jwks":
            self.sendJson(200, buildJwks(self.registration))
        elif path == "/login":
            self.login(method)
        elif method == "POST" and path == "/launch":
            self.launch()
        elif method == "GET" and path == "/ags-score":
            self.agsScore()
        elif method == "GET" and path == "/nrps-roster":
            self.nrpsRoster()
        elif method == "POST" and path == "/deep-link-submit":
            self.deepLinkSubmit()
        else:
            self.sendNotFound(method, path)

    def index(self) -> None:
        self.sendHtml(
            200,
            renderPage(
                "lti1p3 example tool",
                f"""<p>This is a minimal LTI 1.3 tool built on the <code>lti1p3</code> library. It does nothing
on its own; a platform launches it.</p>
<p>To try it without a real platform, this example bundles a small simulator. Open
<a href="{escape(self.simulatorBaseUrl)}/">{escape(self.simulatorBaseUrl)}/</a> and click through.
That page plays the role of the platform, the thing that normally has a "launch tool" link inside a course.</p>""",
            ),
        )

    def login(self, method: str) -> None:
        params = self.formParams() if method == "POST" else self.queryParams()
        handler = LoginInitiationHandler(ConfigRegistrationRepository(self.registration), self.cache)
        try:
            self.send(handler.handle(params, self.toolBaseUrl + "/launch"))
        except LtiException as error:
            self.sendErrorPage("Login initiation failed", str(error))

    def launch(self) -> None:
        with httpx.Client(timeout=10) as httpClient:
            jwtValidator = JwtValidator(JwksFetcher(httpClient, self.cache), self.cache)
            validator = LaunchValidator(ConfigRegistrationRepository(self.registration), self.cache, jwtValidator)
            try:
                message = validator.validate(self.formParams())
            except LtiException as error:
                self.sendErrorPage("Launch failed", str(error))
                return

        agsEndpoint = message.agsEndpoint()
        nrpsEndpoint = message.nrpsEndpoint()
        launch = {
            "message_type": message.messageType,
            "subject": message.subject,
            "roles": message.roles.all(),
            "custom": message.custom,
            "deployment_id": message.deploymentId,
            "ags_endpoint": None
            if agsEndpoint is None
            else {"lineitems": agsEndpoint.lineItemsUrl, "lineitem": agsEndpoint.lineItemUrl, "scope": agsEndpoint.scopes},
            "nrps_endpoint": None
            if nrpsEndpoint is None
            else {
                "context_memberships_url": nrpsEndpoint.contextMembershipsUrl,
                "service_versions": nrpsEndpoint.serviceVersions,
            },
        }

        if isinstance(message, LtiDeepLinkingRequest):
            settings = message.deepLinkingSettings
            launch["deep_linking_settings"] = {"deep_link_return_url": settings.deepLinkReturnUrl, "data": settings.data}
            self.launches.save(launch)
            self.sendHtml(
                200,
                renderPage(
                    "Deep Linking request received",
                    f"""<p>The platform is asking this tool to let the user pick content to link back.</p>
<p><strong>Accepted types:</strong> {escape(", ".join(settings.acceptTypes))}</p>
<p><strong>Return URL:</strong> {escape(settings.deepLinkReturnUrl)}</p>
<form method="post" action="deep-link-submit">
    <label>Title of the item to send back:
        <input type="text" name="title" value="Selected demo item" required>
    </label>
    <button type="submit">Send selection back to platform</button>
</form>""",
                ),
            )
            return

        if isinstance(message, LtiResourceLinkRequest):
            self.launches.save(launch)
            rolesHtml = "".join(f"<li>{escape(role)}</li>" for role in message.roles.all())
            customHtml = (
                "<p><em>none</em></p>"
                if not message.custom
                else "<pre>" + escape("\n".join(f"{key}: {value}" for key, value in message.custom.items())) + "</pre>"
            )
            actions = ""
            if agsEndpoint is not None:
                actions += '<p><a class="button" href="ags-score">Publish a demo score (AGS)</a></p>'
            if nrpsEndpoint is not None:
                actions += '<p><a class="button" href="nrps-roster">Fetch course roster (NRPS)</a></p>'
            self.sendHtml(
                200,
                renderPage(
                    "Resource link launch successful",
                    f"""<p><strong>Subject:</strong> {escape(message.subject or "(anonymous launch, no sub claim)")}</p>
<p><strong>Deployment:</strong> {escape(message.deploymentId)}</p>
<p><strong>Resource link:</strong> {escape(message.resourceLink.id)}: {escape(message.resourceLink.title or "(untitled)")}</p>
<p><strong>Roles:</strong></p>
<ul>{rolesHtml}</ul>
<p><strong>Custom parameters:</strong></p>
{customHtml}
{actions}""",
                ),
            )
            return

        self.sendErrorPage("Unsupported launch", "Unhandled message type: " + message.messageType)

    def agsScore(self) -> None:
        launch = self.launches.load()
        if launch is None:
            self.sendErrorPage("No launch on record", f"Launch this tool from the simulator first: {self.simulatorBaseUrl}/")
            return

        agsData = jsonObject(launch.get("ags_endpoint"))
        lineItemUrl = agsData.get("lineitem") if agsData is not None else None
        subject = launch.get("subject")
        if not isinstance(lineItemUrl, str):
            self.sendErrorPage("AGS not available", "This launch was not granted a single AGS line item.")
            return
        if not isinstance(subject, str):
            self.sendErrorPage("AGS not available", "This was an anonymous launch. AGS needs a user id to score.")
            return

        with httpx.Client(timeout=10) as httpClient:
            ags = AssignmentsGradesService(httpClient, AccessTokenService(httpClient, self.cache))
            try:
                ags.publishScore(
                    self.registration,
                    lineItemUrl,
                    Score(subject, ActivityProgress.Completed, GradingProgress.FullyGraded, scoreGiven=8.5, scoreMaximum=10.0),
                )
                results = ags.listResults(self.registration, lineItemUrl)
            except LtiException as error:
                self.sendErrorPage("AGS call failed", str(error))
                return

        rows = "".join(
            f"<tr><td>{escape(result.userId)}</td><td>{escape(result.resultScore)}</td><td>{escape(result.resultMaximum)}</td></tr>"
            for result in results
        )
        self.sendHtml(
            200,
            renderPage(
                "AGS score published",
                f"""<p>Published a score of 8.5 / 10.0 for <code>{escape(subject)}</code>, then read the results back
from the platform (a real HTTP round trip to the simulator's AGS endpoints):</p>
<table>
<tr><th>User</th><th>Score</th><th>Max</th></tr>
{rows}
</table>
<p><a href="/">Back</a>. Re-launch from <a href="{escape(self.simulatorBaseUrl)}/">the simulator</a> to try again.</p>""",
            ),
        )

    def nrpsRoster(self) -> None:
        launch = self.launches.load()
        if launch is None:
            self.sendErrorPage("No launch on record", f"Launch this tool from the simulator first: {self.simulatorBaseUrl}/")
            return

        endpoint = NrpsEndpoint.fromClaimValue(launch.get("nrps_endpoint"))
        if endpoint is None:
            self.sendErrorPage("NRPS not available", "This launch was not granted access to the roster.")
            return

        with httpx.Client(timeout=10) as httpClient:
            nrps = NamesRoleService(httpClient, AccessTokenService(httpClient, self.cache))
            try:
                members = nrps.getMembers(self.registration, endpoint)
            except LtiException as error:
                self.sendErrorPage("NRPS call failed", str(error))
                return

        rows = "".join(
            f"<tr><td>{escape(member.userId)}</td><td>{escape(member.name or '')}</td>"
            f"<td>{escape(member.status)}</td><td>{escape(', '.join(member.roles))}</td></tr>"
            for member in members
        )
        self.sendHtml(
            200,
            renderPage(
                "NRPS roster",
                f"""<p>Fetched the course roster from the platform (a real HTTP round trip to the simulator's NRPS endpoint):</p>
<table>
<tr><th>User ID</th><th>Name</th><th>Status</th><th>Roles</th></tr>
{rows}
</table>
<p><a href="/">Back</a>. Re-launch from <a href="{escape(self.simulatorBaseUrl)}/">the simulator</a> to try again.</p>""",
            ),
        )

    def deepLinkSubmit(self) -> None:
        launch = self.launches.load()
        settings = jsonObject(launch.get("deep_linking_settings")) if launch is not None else None
        if launch is None or settings is None:
            self.sendErrorPage("No Deep Linking request on record", f"Launch from the simulator first: {self.simulatorBaseUrl}/")
            return

        deploymentId = launch.get("deployment_id")
        returnUrl = settings.get("deep_link_return_url")
        if not isinstance(deploymentId, str) or not isinstance(returnUrl, str):
            self.sendErrorPage("Deep Linking response failed", "Missing deployment_id or deep_link_return_url on record.")
            return

        title = self.formParams().get("title", "").strip() or "Selected demo item"
        data = settings.get("data")
        response = LtiDeepLinkingResponse(
            self.registration,
            deploymentId,
            self.simulatorBaseUrl,
            [LtiResourceLinkContentItem(url=self.toolBaseUrl + "/launch", title=title)],
            data=data if isinstance(data, str) else None,
        )
        self.send(renderFormPost(returnUrl, {"JWT": response.toJwt()}))


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the example LTI 1.3 tool.")
    parser.add_argument("--home", type=Path, default=DEFAULT_HOME, help="Directory setupExample.py wrote to.")
    args = parser.parse_args()

    home: Path = args.home
    config = loadConfig(home)
    ToolHandler.home = home
    port = portOf(str(config["tool_base_url"]))

    server = ThreadingHTTPServer(("127.0.0.1", port), ToolHandler)
    print(f"Example tool listening on {config['tool_base_url']} (home: {home})", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
