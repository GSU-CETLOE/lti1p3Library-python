"""Drives the example tool and simulator end to end, as real subprocesses, so the examples never go stale.

The flow mirrors what a person does in a browser: open the simulator's
landing page, follow the launch link to the tool's login endpoint, follow
the redirect to the simulator's authentication endpoint, submit the
form_post back to the tool's launch endpoint, then click through AGS, NRPS,
and Deep Linking.
"""

import re
import socket
import subprocess
import sys
import time
from collections.abc import Iterator
from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import Path
from typing import IO

import httpx
import pytest

EXAMPLES_DIR = Path(__file__).resolve().parent.parent / "examples"


def freePort() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


class FormParser(HTMLParser):
    """Collects the action and hidden inputs of the first form on a page."""

    def __init__(self) -> None:
        super().__init__()
        self.action: str | None = None
        self.fields: dict[str, str] = {}

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = dict(attrs)
        if tag == "form" and self.action is None:
            self.action = attributes.get("action")
        if tag == "input" and attributes.get("name") is not None:
            self.fields[str(attributes["name"])] = attributes.get("value") or ""


def parseForm(page: str) -> FormParser:
    parser = FormParser()
    parser.feed(page)
    return parser


@dataclass
class ExampleServers:
    """The running tool and simulator, plus the URLs they answer on."""

    toolBaseUrl: str
    simulatorBaseUrl: str
    processes: list[subprocess.Popen[str]]
    logDir: Path

    def logs(self) -> str:
        return "\n".join(f"--- {path.name} ---\n{path.read_text()}" for path in sorted(self.logDir.glob("*.log")))


def waitUntilServing(baseUrl: str, process: subprocess.Popen[str], logDir: Path) -> None:
    deadline = time.time() + 15
    while time.time() < deadline:
        if process.poll() is not None:
            raise RuntimeError(f"{baseUrl} exited early:\n" + "".join(path.read_text() for path in logDir.glob("*.log")))
        try:
            httpx.get(baseUrl + "/", timeout=1)
            return
        except httpx.HTTPError:
            time.sleep(0.1)
    raise RuntimeError(f"{baseUrl} did not start in time")


def startExampleProcess(script: str, home: Path, log: IO[str]) -> subprocess.Popen[str]:
    """Start one example server with its output going to a log file."""
    return subprocess.Popen(
        [sys.executable, str(EXAMPLES_DIR / script), "--home", str(home)],
        stdout=log,
        stderr=subprocess.STDOUT,
        text=True,
    )


def stopProcesses(processes: list[subprocess.Popen[str]]) -> None:
    for process in processes:
        process.terminate()
    for process in processes:
        process.wait(timeout=10)


@pytest.fixture(scope="module")
def servers(tmp_path_factory: pytest.TempPathFactory) -> Iterator[ExampleServers]:
    home = tmp_path_factory.mktemp("example-home")
    logDir = tmp_path_factory.mktemp("example-logs")
    toolPort, simulatorPort = freePort(), freePort()

    setup = subprocess.run(
        [
            sys.executable,
            str(EXAMPLES_DIR / "setupExample.py"),
            "--home",
            str(home),
            "--tool-port",
            str(toolPort),
            "--simulator-port",
            str(simulatorPort),
        ],
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert setup.returncode == 0, setup.stderr
    assert "Setup complete." in setup.stdout
    assert (home / "config.json").is_file()
    assert (home / "keys" / "tool-key-1.private.pem").is_file()

    processes: list[subprocess.Popen[str]] = []
    logs: list[IO[str]] = []
    for script in ("tool.py", "simulator.py"):
        log = (logDir / f"{script}.log").open("w")
        logs.append(log)
        processes.append(startExampleProcess(script, home, log))

    running = ExampleServers(f"http://localhost:{toolPort}", f"http://localhost:{simulatorPort}", processes, logDir)
    try:
        waitUntilServing(running.toolBaseUrl, processes[0], logDir)
        waitUntilServing(running.simulatorBaseUrl, processes[1], logDir)
        yield running
    finally:
        stopProcesses(processes)
        for log in logs:
            log.close()


@pytest.fixture
def browser() -> Iterator[httpx.Client]:
    with httpx.Client(timeout=30, follow_redirects=False) as client:
        yield client


def launchFromSimulator(browser: httpx.Client, servers: ExampleServers, buttonText: str) -> httpx.Response:
    """Click a launch link on the simulator's landing page and carry the flow through to the tool's launch page."""
    landing = browser.get(servers.simulatorBaseUrl + "/")
    assert landing.status_code == 200, servers.logs()
    match = re.search(rf'href="([^"]+)">{re.escape(buttonText)}</a>', landing.text)
    assert match is not None, landing.text
    loginUrl = match.group(1).replace("&amp;", "&")

    redirect = browser.get(loginUrl)
    assert redirect.status_code == 302, redirect.text + servers.logs()
    authenticate = browser.get(redirect.headers["Location"])
    assert authenticate.status_code == 200, authenticate.text

    form = parseForm(authenticate.text)
    assert form.action is not None and form.action == servers.toolBaseUrl + "/launch"
    assert set(form.fields) == {"state", "id_token"}
    return browser.post(form.action, data=form.fields)


class TestResourceLinkLaunch:
    def test_loginLaunchAgsAndNrpsAgainstTheSimulator(self, browser: httpx.Client, servers: ExampleServers):
        launch = launchFromSimulator(browser, servers, "Launch as a resource link")
        assert launch.status_code == 200, launch.text + servers.logs()
        assert "Resource link launch successful" in launch.text
        assert "demo-instructor-1" in launch.text
        assert "demo-resource-link" in launch.text
        assert "hello-from-the-simulator" in launch.text

        score = browser.get(servers.toolBaseUrl + "/ags-score")
        assert score.status_code == 200, score.text + servers.logs()
        assert "AGS score published" in score.text
        assert "<td>demo-instructor-1</td><td>8.5</td><td>10.0</td>" in score.text

        roster = browser.get(servers.toolBaseUrl + "/nrps-roster")
        assert roster.status_code == 200, roster.text + servers.logs()
        assert "Ada Lovelace" in roster.text
        assert "Alan Turing" in roster.text

    def test_aReplayedLaunchIsRejected(self, browser: httpx.Client, servers: ExampleServers):
        landing = browser.get(servers.simulatorBaseUrl + "/")
        loginUrl = re.search(r'href="([^"]+)">Launch as a resource link</a>', landing.text)
        assert loginUrl is not None
        redirect = browser.get(loginUrl.group(1).replace("&amp;", "&"))
        form = parseForm(browser.get(redirect.headers["Location"]).text)
        assert form.action is not None

        first = browser.post(form.action, data=form.fields)
        assert first.status_code == 200
        replay = browser.post(form.action, data=form.fields)
        assert replay.status_code == 400
        assert "Launch failed" in replay.text

    def test_theToolPublishesItsJwks(self, browser: httpx.Client, servers: ExampleServers):
        jwks = browser.get(servers.toolBaseUrl + "/jwks").json()
        assert [key["kid"] for key in jwks["keys"]] == ["tool-key-1"]
        assert jwks["keys"][0]["kty"] == "RSA"


class TestDeepLinking:
    def test_deepLinkingRequestResponseAndPlatformVerification(self, browser: httpx.Client, servers: ExampleServers):
        launch = launchFromSimulator(browser, servers, "Launch as a Deep Linking request")
        assert launch.status_code == 200, launch.text + servers.logs()
        assert "Deep Linking request received" in launch.text
        assert servers.simulatorBaseUrl + "/deep-link-return" in launch.text

        submitted = browser.post(servers.toolBaseUrl + "/deep-link-submit", data={"title": "Chapter 3 quiz"})
        assert submitted.status_code == 200, submitted.text + servers.logs()
        form = parseForm(submitted.text)
        assert form.action is not None and form.action == servers.simulatorBaseUrl + "/deep-link-return"
        assert set(form.fields) == {"JWT"}

        verified = browser.post(form.action, data=form.fields)
        assert verified.status_code == 200, verified.text + servers.logs()
        assert "Deep Linking response received and verified" in verified.text
        assert "ltiResourceLink: Chapter 3 quiz" in verified.text


class TestWithoutALaunch:
    def test_actionsExplainThatALaunchIsNeededFirst(self, tmp_path: Path):
        # A fresh home with no launch on record: the AGS action must not crash, it must explain.
        toolPort, simulatorPort = freePort(), freePort()
        subprocess.run(
            [sys.executable, str(EXAMPLES_DIR / "setupExample.py"), "--home", str(tmp_path), "--tool-port", str(toolPort), "--simulator-port", str(simulatorPort)],
            check=True,
            capture_output=True,
            timeout=60,
        )
        with (tmp_path / "tool.log").open("w") as log:
            process = startExampleProcess("tool.py", tmp_path, log)
            try:
                waitUntilServing(f"http://localhost:{toolPort}", process, tmp_path)
                response = httpx.get(f"http://localhost:{toolPort}/ags-score", timeout=10)
                assert response.status_code == 400
                assert "No launch on record" in response.text
            finally:
                stopProcesses([process])
