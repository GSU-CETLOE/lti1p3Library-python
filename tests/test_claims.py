"""Tests for the claim value objects hydrated from an id_token."""

import pytest

from lti1p3.claims import (
    AgsEndpoint,
    Context,
    DeepLinkingSettings,
    LaunchPresentation,
    Lis,
    NrpsEndpoint,
    ResourceLink,
    Roles,
    ToolPlatform,
)
from lti1p3.exceptions import InvalidLaunchException, InvalidLaunchReason

LINE_ITEM_SCOPE = "https://purl.imsglobal.org/spec/lti-ags/scope/lineitem"
SCORE_SCOPE = "https://purl.imsglobal.org/spec/lti-ags/scope/score"


class TestAgsEndpoint:
    def test_parsesScopesLineItemsUrlAndLineItemUrl(self):
        endpoint = AgsEndpoint.fromClaimValue(
            {
                "scope": [LINE_ITEM_SCOPE, SCORE_SCOPE],
                "lineitems": "https://example.com/ags/lineitems",
                "lineitem": "https://example.com/ags/lineitems/1",
            }
        )
        assert endpoint is not None
        assert endpoint.scopes == [LINE_ITEM_SCOPE, SCORE_SCOPE]
        assert endpoint.lineItemsUrl == "https://example.com/ags/lineitems"
        assert endpoint.lineItemUrl == "https://example.com/ags/lineitems/1"

    def test_lineItemUrlIsNoneWhenNotPresent(self):
        endpoint = AgsEndpoint.fromClaimValue({"scope": [], "lineitems": "https://example.com/ags/lineitems"})
        assert endpoint is not None
        assert endpoint.lineItemUrl is None

    def test_returnsNoneWhenClaimIsMissingOrWrongType(self):
        assert AgsEndpoint.fromClaimValue(None) is None
        assert AgsEndpoint.fromClaimValue("not-a-mapping") is None

    def test_returnsNoneWhenLineItemsUrlIsMissing(self):
        assert AgsEndpoint.fromClaimValue({"scope": []}) is None


class TestNrpsEndpoint:
    def test_parsesContextMembershipsUrlAndServiceVersions(self):
        endpoint = NrpsEndpoint.fromClaimValue(
            {"context_memberships_url": "https://example.com/nrps/context/1/memberships", "service_versions": ["2.0"]}
        )
        assert endpoint is not None
        assert endpoint.contextMembershipsUrl == "https://example.com/nrps/context/1/memberships"
        assert endpoint.serviceVersions == ["2.0"]

    def test_returnsNoneWhenClaimIsMissingOrWrongType(self):
        assert NrpsEndpoint.fromClaimValue(None) is None
        assert NrpsEndpoint.fromClaimValue("not-a-mapping") is None

    def test_returnsNoneWhenContextMembershipsUrlIsMissing(self):
        assert NrpsEndpoint.fromClaimValue({"service_versions": ["2.0"]}) is None


class TestDeepLinkingSettings:
    def test_parsesAllFields(self):
        settings = DeepLinkingSettings.fromClaimValue(
            {
                "deep_link_return_url": "https://example.com/deep-link-return",
                "accept_types": ["ltiResourceLink", "link"],
                "accept_presentation_document_targets": ["iframe", "window"],
                "accept_multiple": False,
                "accept_lineitem": True,
                "auto_create": True,
                "title": "Select content",
                "text": "Choose an item",
                "data": "opaque-data-value",
            },
            "context",
        )
        assert settings.deepLinkReturnUrl == "https://example.com/deep-link-return"
        assert settings.acceptTypes == ["ltiResourceLink", "link"]
        assert settings.acceptPresentationDocumentTargets == ["iframe", "window"]
        assert settings.acceptMultiple is False
        assert settings.acceptLineItem is True
        assert settings.autoCreate is True
        assert settings.title == "Select content"
        assert settings.text == "Choose an item"
        assert settings.data == "opaque-data-value"

    def test_optionalFieldsAreNoneWhenAbsent(self):
        settings = DeepLinkingSettings.fromClaimValue(
            {"deep_link_return_url": "https://example.com/deep-link-return"}, "context"
        )
        assert settings.acceptTypes == []
        assert settings.acceptPresentationDocumentTargets == []
        assert settings.acceptMultiple is None
        assert settings.acceptLineItem is None
        assert settings.autoCreate is None
        assert settings.title is None
        assert settings.text is None
        assert settings.data is None

    def test_throwsWhenClaimIsMissing(self):
        with pytest.raises(InvalidLaunchException):
            DeepLinkingSettings.fromClaimValue(None, "context")

    def test_throwsWhenDeepLinkReturnUrlIsMissing(self):
        with pytest.raises(InvalidLaunchException):
            DeepLinkingSettings.fromClaimValue({"accept_types": []}, "context")


class TestResourceLink:
    def test_parsesIdTitleAndDescription(self):
        resourceLink = ResourceLink.fromClaimValue(
            {"id": "resource-1", "title": "A resource", "description": "A description"}, "context"
        )
        assert resourceLink.id == "resource-1"
        assert resourceLink.title == "A resource"
        assert resourceLink.description == "A description"

    def test_titleAndDescriptionAreNoneWhenAbsent(self):
        resourceLink = ResourceLink.fromClaimValue({"id": "resource-1"}, "context")
        assert resourceLink.title is None
        assert resourceLink.description is None

    def test_throwsWhenTheClaimIsMissing(self):
        with pytest.raises(InvalidLaunchException) as caught:
            ResourceLink.fromClaimValue(None, "context")
        assert caught.value.reason is InvalidLaunchReason.MissingRequiredClaim

    def test_throwsWhenIdIsMissing(self):
        with pytest.raises(InvalidLaunchException):
            ResourceLink.fromClaimValue({"title": "A resource"}, "context")


class TestRoles:
    def test_isInstructorReturnsTrueWhenTheRoleUriIsPresent(self):
        roles = Roles.fromClaimValue([Roles.INSTRUCTOR])
        assert roles.isInstructor()
        assert not roles.isLearner()

    def test_isLearnerReturnsTrueWhenTheRoleUriIsPresent(self):
        roles = Roles.fromClaimValue([Roles.LEARNER])
        assert roles.isLearner()
        assert not roles.isInstructor()

    def test_otherPredicatesMatchTheirRoleUris(self):
        assert Roles.fromClaimValue([Roles.CONTENT_DEVELOPER]).isContentDeveloper()
        assert Roles.fromClaimValue([Roles.TEACHING_ASSISTANT]).isTeachingAssistant()
        assert Roles.fromClaimValue([Roles.MENTOR]).isMentor()
        assert Roles.fromClaimValue([Roles.ADMINISTRATOR]).isAdministrator()

    def test_hasReturnsTrueForAnyRoleUriPresent(self):
        roles = Roles.fromClaimValue(["https://example.com/some-custom-institution-role"])
        assert roles.has("https://example.com/some-custom-institution-role")
        assert not roles.has("https://example.com/other-role")

    def test_allReturnsEveryRoleUriExactlyAsReceived(self):
        roles = Roles.fromClaimValue([Roles.INSTRUCTOR, "https://example.com/custom-role"])
        assert roles.all() == [Roles.INSTRUCTOR, "https://example.com/custom-role"]

    def test_unrecognizedRoleUrisDoNotCauseAnError(self):
        roles = Roles.fromClaimValue(["https://example.com/a-role-this-library-has-never-heard-of"])
        assert not roles.isInstructor()
        assert roles.all() == ["https://example.com/a-role-this-library-has-never-heard-of"]

    def test_fromClaimValueDefaultsToEmptyWhenMissingOrWrongType(self):
        assert Roles.fromClaimValue(None).all() == []
        assert Roles.fromClaimValue("not-a-list").all() == []

    def test_fromClaimValueFiltersOutNonStringEntries(self):
        assert Roles.fromClaimValue([Roles.INSTRUCTOR, 123, None]).all() == [Roles.INSTRUCTOR]


class TestContext:
    def test_parsesAllFields(self):
        context = Context.fromClaimValue({"id": "ctx-1", "label": "C1", "title": "Course 1", "type": ["CourseSection"]})
        assert context is not None
        assert context.id == "ctx-1"
        assert context.label == "C1"
        assert context.title == "Course 1"
        assert context.types == ["CourseSection"]

    def test_returnsNoneWhenMissingOrWithoutAnId(self):
        assert Context.fromClaimValue(None) is None
        assert Context.fromClaimValue({"title": "Course 1"}) is None


class TestToolPlatform:
    def test_parsesAllFields(self):
        platform = ToolPlatform.fromClaimValue(
            {
                "guid": "platform-guid",
                "name": "Brightspace",
                "contact_email": "admin@example.com",
                "description": "A platform",
                "url": "https://example.brightspace.com",
                "product_family_code": "desire2learn",
                "version": "20.26",
            }
        )
        assert platform is not None
        assert platform.guid == "platform-guid"
        assert platform.name == "Brightspace"
        assert platform.contactEmail == "admin@example.com"
        assert platform.description == "A platform"
        assert platform.url == "https://example.brightspace.com"
        assert platform.productFamilyCode == "desire2learn"
        assert platform.version == "20.26"

    def test_returnsNoneWhenMissingOrWithoutAGuid(self):
        assert ToolPlatform.fromClaimValue(None) is None
        assert ToolPlatform.fromClaimValue({"name": "Brightspace"}) is None


class TestLaunchPresentation:
    def test_parsesAllFields(self):
        presentation = LaunchPresentation.fromClaimValue(
            {"document_target": "iframe", "height": 400, "width": 800, "return_url": "https://x", "locale": "en-US"}
        )
        assert presentation is not None
        assert presentation.documentTarget == "iframe"
        assert presentation.height == 400
        assert presentation.width == 800
        assert presentation.returnUrl == "https://x"
        assert presentation.locale == "en-US"

    def test_allFieldsAreOptional(self):
        presentation = LaunchPresentation.fromClaimValue({})
        assert presentation is not None
        assert presentation.documentTarget is None
        assert LaunchPresentation.fromClaimValue(None) is None


class TestLis:
    def test_parsesAllFields(self):
        lis = Lis.fromClaimValue(
            {"person_sourcedid": "p-1", "course_offering_sourcedid": "o-1", "course_section_sourcedid": "s-1"}
        )
        assert lis is not None
        assert lis.personSourcedId == "p-1"
        assert lis.courseOfferingSourcedId == "o-1"
        assert lis.courseSectionSourcedId == "s-1"

    def test_returnsNoneWhenMissing(self):
        assert Lis.fromClaimValue(None) is None
