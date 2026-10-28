"""Tests for the AGS line item, score, and result payloads."""

from datetime import UTC, datetime

import pytest

from lti1p3.ags import ActivityProgress, GradingProgress, LineItem, Result, Score
from lti1p3.exceptions import ServiceException


class TestLineItem:
    def test_toDictOmitsNoneFieldsAndIdWhenNotSet(self):
        assert LineItem(None, 100.0, "Assignment 1").toDict() == {"scoreMaximum": 100.0, "label": "Assignment 1"}

    def test_toDictIncludesOptionalFieldsWhenSet(self):
        lineItem = LineItem("https://example.com/lineitems/1", 100.0, "Assignment 1", "res-1", "tag-1", "link-1")
        assert lineItem.toDict() == {
            "scoreMaximum": 100.0,
            "label": "Assignment 1",
            "resourceId": "res-1",
            "tag": "tag-1",
            "resourceLinkId": "link-1",
            "id": "https://example.com/lineitems/1",
        }

    def test_fromResponseDataParsesAllFields(self):
        lineItem = LineItem.fromResponseData(
            {
                "id": "https://example.com/lineitems/1",
                "scoreMaximum": 100,
                "label": "Assignment 1",
                "resourceId": "res-1",
                "tag": "tag-1",
                "resourceLinkId": "link-1",
            }
        )
        assert lineItem.id == "https://example.com/lineitems/1"
        assert lineItem.scoreMaximum == 100.0
        assert isinstance(lineItem.scoreMaximum, float)
        assert lineItem.label == "Assignment 1"
        assert lineItem.resourceId == "res-1"
        assert lineItem.tag == "tag-1"
        assert lineItem.resourceLinkId == "link-1"

    def test_fromResponseDataAllowsOptionalFieldsToBeAbsent(self):
        lineItem = LineItem.fromResponseData({"scoreMaximum": 50, "label": "Quiz"})
        assert lineItem.id is None
        assert lineItem.resourceId is None
        assert lineItem.tag is None
        assert lineItem.resourceLinkId is None

    def test_fromResponseDataThrowsWhenNotAnObject(self):
        with pytest.raises(ServiceException):
            LineItem.fromResponseData("not-an-object")

    def test_fromResponseDataThrowsWhenScoreMaximumIsMissingOrNotNumeric(self):
        with pytest.raises(ServiceException):
            LineItem.fromResponseData({"label": "Assignment 1"})
        with pytest.raises(ServiceException):
            LineItem.fromResponseData({"label": "Assignment 1", "scoreMaximum": True})

    def test_fromResponseDataThrowsWhenLabelIsMissing(self):
        with pytest.raises(ServiceException):
            LineItem.fromResponseData({"scoreMaximum": 100})


class TestResult:
    def test_parsesAllFields(self):
        result = Result.fromResponseData(
            {
                "id": "https://example.com/results/1",
                "scoreOf": "https://example.com/lineitems/1",
                "userId": "user-1",
                "resultScore": 8.5,
                "resultMaximum": 10,
                "comment": "Nice work",
            }
        )
        assert result.id == "https://example.com/results/1"
        assert result.scoreOf == "https://example.com/lineitems/1"
        assert result.userId == "user-1"
        assert result.resultScore == 8.5
        assert result.resultMaximum == 10.0
        assert result.comment == "Nice work"

    def test_optionalFieldsAreNoneWhenAbsent(self):
        result = Result.fromResponseData({"id": "r", "scoreOf": "l", "userId": "user-1"})
        assert result.resultScore is None
        assert result.resultMaximum is None
        assert result.comment is None

    def test_throwsWhenNotAnObject(self):
        with pytest.raises(ServiceException):
            Result.fromResponseData("not-an-object")

    def test_throwsWhenARequiredFieldIsMissing(self):
        with pytest.raises(ServiceException):
            Result.fromResponseData({"id": "x", "scoreOf": "y"})


class TestScore:
    def test_toDictIncludesRequiredFieldsAndDefaultsTimestampToNow(self):
        data = Score("user-1", ActivityProgress.Completed, GradingProgress.FullyGraded).toDict()
        assert data["userId"] == "user-1"
        assert data["activityProgress"] == "Completed"
        assert data["gradingProgress"] == "FullyGraded"
        assert isinstance(data["timestamp"], str) and "+00:00" in data["timestamp"]
        assert "scoreGiven" not in data
        assert "scoreMaximum" not in data
        assert "comment" not in data

    def test_toDictIncludesOptionalFieldsWhenSet(self):
        timestamp = datetime(2026, 1, 1, tzinfo=UTC)
        data = Score(
            "user-1",
            ActivityProgress.Completed,
            GradingProgress.FullyGraded,
            scoreGiven=8.5,
            scoreMaximum=10.0,
            comment="Nice work",
            timestamp=timestamp,
        ).toDict()
        assert data["scoreGiven"] == 8.5
        assert data["scoreMaximum"] == 10.0
        assert data["comment"] == "Nice work"
        assert data["timestamp"] == "2026-01-01T00:00:00+00:00"

    def test_progressOnlyUpdateOmitsScoreGiven(self):
        assert "scoreGiven" not in Score("user-1", ActivityProgress.InProgress, GradingProgress.Pending).toDict()

    def test_progressEnumsCarryTheSpecValues(self):
        assert [member.value for member in ActivityProgress] == [
            "Initialized",
            "Started",
            "InProgress",
            "Submitted",
            "Completed",
        ]
        assert [member.value for member in GradingProgress] == [
            "FullyGraded",
            "Pending",
            "PendingManual",
            "Failed",
            "NotReady",
        ]
