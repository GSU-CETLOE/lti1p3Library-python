"""Tests for the typed LTI message objects built from validated claims."""

from typing import Any

import pytest

from lti1p3.claimUris import (
    AGS_ENDPOINT,
    CONTEXT,
    CUSTOM,
    DEEP_LINKING_SETTINGS,
    DEPLOYMENT_ID,
    MESSAGE_TYPE,
    NRPS_ENDPOINT,
    RESOURCE_LINK,
    ROLE_SCOPE_MENTOR,
    ROLES,
    TARGET_LINK_URI,
    VERSION,
)
from lti1p3.exceptions import InvalidLaunchException, InvalidLaunchReason
from lti1p3.messages import LtiDeepLinkingRequest, LtiMessage, LtiResourceLinkRequest


def resourceLinkClaims(**overrides: Any) -> dict[str, Any]:
    return {
        MESSAGE_TYPE: "LtiResourceLinkRequest",
        VERSION: "1.3.0",
        DEPLOYMENT_ID: "deployment-1",
        TARGET_LINK_URI: "https://tool.example.com/launch",
        RESOURCE_LINK: {"id": "resource-1"},
        **overrides,
    }


def deepLinkingClaims(**overrides: Any) -> dict[str, Any]:
    return {
        MESSAGE_TYPE: "LtiDeepLinkingRequest",
        VERSION: "1.3.0",
        DEPLOYMENT_ID: "deployment-1",
        TARGET_LINK_URI: "https://tool.example.com/deep-link",
        DEEP_LINKING_SETTINGS: {
            "deep_link_return_url": "https://example.com/deep-link-return",
            "accept_types": ["ltiResourceLink"],
        },
        **overrides,
    }


class TestLtiResourceLinkRequest:
    def test_parsesTheCommonAndResourceLinkClaims(self):
        request = LtiResourceLinkRequest.fromClaims(
            resourceLinkClaims(
                sub="user-1",
                **{
                    ROLES: ["http://purl.imsglobal.org/vocab/lis/v2/membership#Instructor"],
                    CUSTOM: {"foo": "bar", "number": 1},
                    CONTEXT: {"id": "ctx-1"},
                    ROLE_SCOPE_MENTOR: ["user-2"],
                },
            )
        )
        assert isinstance(request, LtiMessage)
        assert request.messageType == "LtiResourceLinkRequest"
        assert request.version == "1.3.0"
        assert request.deploymentId == "deployment-1"
        assert request.targetLinkUri == "https://tool.example.com/launch"
        assert request.subject == "user-1"
        assert request.roles.isInstructor()
        assert request.custom == {"foo": "bar"}
        assert request.context is not None and request.context.id == "ctx-1"
        assert request.roleScopeMentor == ["user-2"]
        assert request.resourceLink.id == "resource-1"
        assert request.rawClaims[RESOURCE_LINK] == {"id": "resource-1"}

    def test_optionalClaimsDefaultToNoneOrEmpty(self):
        request = LtiResourceLinkRequest.fromClaims(resourceLinkClaims())
        assert request.subject is None
        assert request.roles.all() == []
        assert request.context is None
        assert request.toolPlatform is None
        assert request.launchPresentation is None
        assert request.lis is None
        assert request.roleScopeMentor is None
        assert request.custom == {}

    def test_rejectsAnUnexpectedMessageType(self):
        with pytest.raises(InvalidLaunchException) as caught:
            LtiResourceLinkRequest.fromClaims(resourceLinkClaims(**{MESSAGE_TYPE: "LtiDeepLinkingRequest"}))
        assert caught.value.reason is InvalidLaunchReason.UnexpectedMessageType

    def test_rejectsAnUnsupportedVersion(self):
        with pytest.raises(InvalidLaunchException) as caught:
            LtiResourceLinkRequest.fromClaims(resourceLinkClaims(**{VERSION: "1.1.0"}))
        assert caught.value.reason is InvalidLaunchReason.UnsupportedVersion

    def test_rejectsAMissingResourceLink(self):
        with pytest.raises(InvalidLaunchException) as caught:
            LtiResourceLinkRequest.fromClaims(resourceLinkClaims(**{RESOURCE_LINK: None}))
        assert caught.value.reason is InvalidLaunchReason.MissingRequiredClaim

    def test_agsEndpointReturnsNoneWhenClaimIsAbsent(self):
        assert LtiResourceLinkRequest.fromClaims(resourceLinkClaims()).agsEndpoint() is None

    def test_agsEndpointParsesTheEndpointClaimWhenPresent(self):
        request = LtiResourceLinkRequest.fromClaims(
            resourceLinkClaims(
                **{
                    AGS_ENDPOINT: {
                        "scope": ["https://purl.imsglobal.org/spec/lti-ags/scope/lineitem"],
                        "lineitems": "https://example.com/ags/lineitems",
                        "lineitem": "https://example.com/ags/lineitems/1",
                    }
                }
            )
        )
        endpoint = request.agsEndpoint()
        assert endpoint is not None
        assert endpoint.lineItemsUrl == "https://example.com/ags/lineitems"
        assert endpoint.lineItemUrl == "https://example.com/ags/lineitems/1"

    def test_nrpsEndpointReturnsNoneWhenClaimIsAbsent(self):
        assert LtiResourceLinkRequest.fromClaims(resourceLinkClaims()).nrpsEndpoint() is None

    def test_nrpsEndpointParsesTheEndpointClaimWhenPresent(self):
        request = LtiResourceLinkRequest.fromClaims(
            resourceLinkClaims(
                **{
                    NRPS_ENDPOINT: {
                        "context_memberships_url": "https://example.com/nrps/context/1/memberships",
                        "service_versions": ["2.0"],
                    }
                }
            )
        )
        endpoint = request.nrpsEndpoint()
        assert endpoint is not None
        assert endpoint.contextMembershipsUrl == "https://example.com/nrps/context/1/memberships"


class TestLtiDeepLinkingRequest:
    def test_isAnLtiMessage(self):
        assert isinstance(LtiDeepLinkingRequest.fromClaims(deepLinkingClaims()), LtiMessage)

    def test_parsesDeepLinkingSettings(self):
        request = LtiDeepLinkingRequest.fromClaims(deepLinkingClaims())
        assert request.deepLinkingSettings.deepLinkReturnUrl == "https://example.com/deep-link-return"
        assert request.deepLinkingSettings.acceptTypes == ["ltiResourceLink"]

    def test_inheritsCommonLtiMessageProperties(self):
        request = LtiDeepLinkingRequest.fromClaims(deepLinkingClaims())
        assert request.deploymentId == "deployment-1"
        assert request.targetLinkUri == "https://tool.example.com/deep-link"

    def test_rejectsAMissingDeepLinkingSettingsClaim(self):
        with pytest.raises(InvalidLaunchException) as caught:
            LtiDeepLinkingRequest.fromClaims(deepLinkingClaims(**{DEEP_LINKING_SETTINGS: None}))
        assert caught.value.reason is InvalidLaunchReason.MissingRequiredClaim
