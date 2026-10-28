"""Shared plumbing for the AGS and NRPS clients: authenticated requests and JSON decoding."""

import json
from collections.abc import Sequence
from typing import Any

import httpx

from lti1p3.accessToken import AccessTokenService
from lti1p3.exceptions import ServiceException
from lti1p3.registration import Registration


def sendAuthorizedRequest(
    httpClient: httpx.Client,
    accessTokenService: AccessTokenService,
    registration: Registration,
    method: str,
    url: str,
    scopes: Sequence[str],
    accept: str,
    contentType: str | None = None,
    jsonBody: object = None,
    serviceName: str = "Service",
) -> httpx.Response:
    """Send a request with a bearer token for the scopes, raising ServiceException on a non-2xx status."""
    accessToken = accessTokenService.getAccessToken(registration, scopes)
    headers = {"Authorization": "Bearer " + accessToken, "Accept": accept}
    content: str | None = None
    if jsonBody is not None:
        headers["Content-Type"] = contentType or "application/json"
        content = json.dumps(jsonBody)

    response = httpClient.request(method, url, headers=headers, content=content)
    if response.status_code >= 300:
        raise ServiceException(
            f'{serviceName} request {method} "{url}" failed with HTTP status {response.status_code}.'
        )
    return response


def decodeJsonBody(response: httpx.Response, url: str, serviceName: str = "Service") -> Any:
    """Decode a JSON response body; an empty body decodes to None."""
    if response.text == "":
        return None

    try:
        return json.loads(response.text)
    except ValueError as error:
        raise ServiceException(f'{serviceName} response from "{url}" was not valid JSON.') from error
