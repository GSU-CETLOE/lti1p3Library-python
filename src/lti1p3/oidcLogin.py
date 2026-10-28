"""The two legs of the OIDC launch flow: login initiation and launch validation.

LoginInitiationHandler mints a `state` and `nonce` pair, records them with the
target_link_uri and deployment_id the platform sent, and redirects the browser
to the platform's authentication endpoint. LaunchValidator then checks the
id_token the platform posts back and, beyond the JWT-level checks, verifies
that its nonce, target_link_uri, and deployment_id match what was recorded for
that exact `state`. That closes the parameter-substitution gap between the
two legs of the flow.
"""

import secrets
from collections.abc import Mapping
from typing import Any
from urllib.parse import urlencode

from lti1p3 import claimUris
from lti1p3.cache import CacheInterface, buildCacheKey
from lti1p3.claims import jsonObject
from lti1p3.exceptions import (
    InvalidLaunchException,
    InvalidLaunchReason,
    InvalidLoginInitiationException,
    RegistrationNotFoundException,
)
from lti1p3.messages import LtiDeepLinkingRequest, LtiMessage, LtiResourceLinkRequest
from lti1p3.registration import Registration, RegistrationRepositoryInterface
from lti1p3.responses import HttpResponse
from lti1p3.security import JwtValidator
from lti1p3.urlSecurity import isSecureUrl

type RequestParams = Mapping[str, object]


def _requireStringParam(source: RequestParams, name: str) -> str:
    value = source.get(name)
    if not isinstance(value, str) or value == "":
        raise InvalidLoginInitiationException(f'Missing or invalid required parameter "{name}".')
    return value


def _optionalStringParam(source: RequestParams, name: str) -> str | None:
    value = source.get(name)
    return value if isinstance(value, str) and value != "" else None


class LoginInitiationHandler:
    """Handles the OIDC third-party login initiation request and builds the redirect to the platform.

    The platform sends the request as GET query parameters or a POST form
    body. Pass whichever your framework parsed, as a mapping of parameter
    name to value.
    """

    DEFAULT_STATE_TTL_SECONDS = 300

    def __init__(
        self,
        registrations: RegistrationRepositoryInterface,
        stateCache: CacheInterface,
        stateTtlSeconds: int = DEFAULT_STATE_TTL_SECONDS,
    ):
        self.registrations = registrations
        self.stateCache = stateCache
        self.stateTtlSeconds = stateTtlSeconds

    def handle(self, params: RequestParams, redirectUri: str) -> HttpResponse:
        """Validate the login request and return a 302 to the platform's authentication endpoint.

        redirectUri is this tool's launch URL, which the platform will POST
        the id_token to. It must be one of the redirect URIs registered with
        the platform.
        """
        issuer = _requireStringParam(params, "iss")
        loginHint = _requireStringParam(params, "login_hint")
        targetLinkUri = _requireStringParam(params, "target_link_uri")
        clientId = _optionalStringParam(params, "client_id")
        deploymentId = _optionalStringParam(params, "lti_deployment_id")
        messageHint = _optionalStringParam(params, "lti_message_hint")

        if not isSecureUrl(targetLinkUri):
            raise InvalidLoginInitiationException(
                'The "target_link_uri" must use https (or loopback for local dev/testing).'
            )
        if not isSecureUrl(redirectUri):
            raise InvalidLoginInitiationException("The redirect_uri must use https (or loopback for local dev/testing).")

        registration = self.registrations.findForLoginInitiation(issuer, clientId)
        if registration is None:
            clientIdNote = f' and client_id "{clientId}"' if clientId is not None else ""
            raise RegistrationNotFoundException(f'No registration found for issuer "{issuer}"{clientIdNote}.')

        state = secrets.token_hex(32)
        nonce = secrets.token_hex(32)

        self.stateCache.set(
            buildCacheKey("login-state", state),
            {
                "nonce": nonce,
                "target_link_uri": targetLinkUri,
                "deployment_id": deploymentId,
                "issuer": issuer,
                "client_id": registration.clientId,
            },
            self.stateTtlSeconds,
        )

        location = self._buildAuthenticationRequestUrl(registration, redirectUri, loginHint, state, nonce, messageHint)
        return HttpResponse(302, {"Location": location})

    @staticmethod
    def _buildAuthenticationRequestUrl(
        registration: Registration,
        redirectUri: str,
        loginHint: str,
        state: str,
        nonce: str,
        messageHint: str | None,
    ) -> str:
        params = {
            "scope": "openid",
            "response_type": "id_token",
            "client_id": registration.clientId,
            "redirect_uri": redirectUri,
            "login_hint": loginHint,
            "state": state,
            "response_mode": "form_post",
            "nonce": nonce,
            "prompt": "none",
        }
        if messageHint is not None:
            params["lti_message_hint"] = messageHint

        separator = "&" if "?" in registration.platformAuthenticationLoginUrl else "?"
        return registration.platformAuthenticationLoginUrl + separator + urlencode(params)


class LaunchValidator:
    """Validates the platform's authentication response and produces the typed LtiMessage for it.

    The platform POSTs `state` and `id_token` to the tool's redirect URI.
    Pass the parsed form body as a mapping.
    """

    def __init__(
        self,
        registrations: RegistrationRepositoryInterface,
        stateCache: CacheInterface,
        jwtValidator: JwtValidator,
    ):
        self.registrations = registrations
        self.stateCache = stateCache
        self.jwtValidator = jwtValidator

    def validate(self, params: RequestParams) -> LtiMessage:
        """Validate the launch and return an LtiResourceLinkRequest or LtiDeepLinkingRequest.

        Raises InvalidLoginInitiationException for a missing parameter,
        RegistrationNotFoundException when the registration is gone, and
        InvalidLaunchException for every validation failure.
        """
        state = _requireStringParam(params, "state")
        idToken = _requireStringParam(params, "id_token")
        stateRecord = self._consumeLoginState(state)

        issuer = str(stateRecord.get("issuer"))
        clientId = str(stateRecord.get("client_id"))
        registration = self.registrations.findForLoginInitiation(issuer, clientId)
        if registration is None:
            raise RegistrationNotFoundException(
                f'No registration found for issuer "{issuer}" and client_id "{clientId}".'
            )

        claims = self.jwtValidator.validate(idToken, registration)
        self._assertRoundtripBinding(claims, stateRecord)

        deploymentId = claims.get(claimUris.DEPLOYMENT_ID)
        if not isinstance(deploymentId, str) or not registration.hasDeployment(deploymentId):
            raise InvalidLaunchException(
                InvalidLaunchReason.InvalidDeploymentId,
                'The id_token "deployment_id" is not registered for this platform.',
            )

        return self._buildMessage(claims)

    @staticmethod
    def _buildMessage(claims: dict[str, Any]) -> LtiMessage:
        messageType = claims.get(claimUris.MESSAGE_TYPE)
        if messageType == LtiResourceLinkRequest.MESSAGE_TYPE:
            return LtiResourceLinkRequest.fromClaims(claims)
        if messageType == LtiDeepLinkingRequest.MESSAGE_TYPE:
            return LtiDeepLinkingRequest.fromClaims(claims)

        raise InvalidLaunchException(
            InvalidLaunchReason.UnexpectedMessageType, f'Unsupported message_type "{messageType}".'
        )

    def _consumeLoginState(self, state: str) -> dict[str, Any]:
        """Read and delete the login state for this `state`, so each state is usable exactly once."""
        cacheKey = buildCacheKey("login-state", state)
        record = jsonObject(self.stateCache.get(cacheKey))
        if record is None:
            raise InvalidLaunchException(
                InvalidLaunchReason.InvalidState, 'The "state" parameter is missing, expired, or unknown.'
            )

        self.stateCache.delete(cacheKey)
        return record

    @staticmethod
    def _assertRoundtripBinding(claims: dict[str, Any], stateRecord: dict[str, Any]) -> None:
        if claims.get("nonce") != stateRecord.get("nonce"):
            raise InvalidLaunchException(
                InvalidLaunchReason.InvalidState, 'The id_token "nonce" does not match the one issued at login.'
            )

        if claims.get(claimUris.TARGET_LINK_URI) != stateRecord.get("target_link_uri"):
            raise InvalidLaunchException(
                InvalidLaunchReason.InvalidState,
                'The id_token "target_link_uri" does not match the one recorded at login initiation.',
            )

        expectedDeploymentId = stateRecord.get("deployment_id")
        if expectedDeploymentId is not None and claims.get(claimUris.DEPLOYMENT_ID) != expectedDeploymentId:
            raise InvalidLaunchException(
                InvalidLaunchReason.InvalidState,
                'The id_token "deployment_id" does not match the one sent at login initiation.',
            )
