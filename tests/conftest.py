"""Shared fixtures: the fixture platform server and an HTTP client pointed at it."""

from collections.abc import Iterator

import httpx
import pytest

from fixturePlatformServer import FixturePlatformServer


@pytest.fixture
def server() -> Iterator[FixturePlatformServer]:
    """A running fixture platform server, stopped after the test."""
    fixtureServer = FixturePlatformServer.start()
    try:
        yield fixtureServer
    finally:
        fixtureServer.stop()


@pytest.fixture
def httpClient() -> Iterator[httpx.Client]:
    """An httpx client with a short timeout, closed after the test."""
    with httpx.Client(timeout=5) as client:
        yield client
