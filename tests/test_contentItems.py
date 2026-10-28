"""Tests for the Deep Linking content item payloads."""

from datetime import UTC, datetime

from lti1p3.deepLinking import (
    ContentItemLineItem,
    FileContentItem,
    HtmlContentItem,
    ImageContentItem,
    LinkContentItem,
    LtiResourceLinkContentItem,
)


class TestLtiResourceLinkContentItem:
    def test_minimal(self):
        assert LtiResourceLinkContentItem().toDict() == {"type": "ltiResourceLink"}

    def test_withAllFields(self):
        item = LtiResourceLinkContentItem(
            url="https://tool.example.com/launch/1",
            title="A resource",
            text="Description",
            custom={"foo": "bar"},
            lineItem=ContentItemLineItem(100.0, label="Assignment 1"),
        )
        assert item.toDict() == {
            "type": "ltiResourceLink",
            "url": "https://tool.example.com/launch/1",
            "title": "A resource",
            "text": "Description",
            "custom": {"foo": "bar"},
            "lineItem": {"scoreMaximum": 100.0, "label": "Assignment 1"},
        }


class TestContentItemLineItem:
    def test_minimal(self):
        assert ContentItemLineItem(100.0).toDict() == {"scoreMaximum": 100.0}

    def test_withAllFields(self):
        lineItem = ContentItemLineItem(100.0, label="A", resourceId="res-1", tag="tag-1", gradesReleased=True)
        assert lineItem.toDict() == {
            "scoreMaximum": 100.0,
            "label": "A",
            "resourceId": "res-1",
            "tag": "tag-1",
            "gradesReleased": True,
        }


class TestOtherContentItems:
    def test_linkContentItem(self):
        item = LinkContentItem("https://example.com", title="A link")
        assert item.toDict() == {"type": "link", "url": "https://example.com", "title": "A link"}

    def test_fileContentItem(self):
        expiresAt = datetime(2026, 1, 1, tzinfo=UTC)
        data = FileContentItem("https://example.com/file.pdf", expiresAt=expiresAt).toDict()
        assert data["type"] == "file"
        assert data["url"] == "https://example.com/file.pdf"
        assert data["expiresAt"] == "2026-01-01T00:00:00+00:00"

    def test_htmlContentItem(self):
        item = HtmlContentItem("<p>Hello</p>", title="Greeting")
        assert item.toDict() == {"type": "html", "html": "<p>Hello</p>", "title": "Greeting"}

    def test_imageContentItem(self):
        item = ImageContentItem("https://example.com/image.png", width=100, height=200)
        assert item.toDict() == {
            "type": "image",
            "url": "https://example.com/image.png",
            "width": 100,
            "height": 200,
        }
