"""Assignment and Grades Service 2.0: line item CRUD, score publishing, and result reads."""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import Enum

import httpx

from lti1p3.accessToken import AccessTokenService
from lti1p3.claims import AgsEndpoint, jsonList, jsonObject
from lti1p3.exceptions import ServiceException
from lti1p3.registration import Registration
from lti1p3.services import decodeJsonBody, sendAuthorizedRequest

SCOPE_LINE_ITEM = "https://purl.imsglobal.org/spec/lti-ags/scope/lineitem"
SCOPE_RESULT_READONLY = "https://purl.imsglobal.org/spec/lti-ags/scope/result.readonly"
SCOPE_SCORE = "https://purl.imsglobal.org/spec/lti-ags/scope/score"

CONTENT_TYPE_LINE_ITEM = "application/vnd.ims.lis.v2.lineitem+json"
CONTENT_TYPE_LINE_ITEM_CONTAINER = "application/vnd.ims.lis.v2.lineitemcontainer+json"
CONTENT_TYPE_SCORE = "application/vnd.ims.lis.v1.score+json"
CONTENT_TYPE_RESULT_CONTAINER = "application/vnd.ims.lis.v2.resultcontainer+json"

SERVICE_NAME = "AGS"


class ActivityProgress(Enum):
    """The `activityProgress` of a score: a closed, spec-defined set the tool chooses from."""

    Initialized = "Initialized"
    Started = "Started"
    InProgress = "InProgress"
    Submitted = "Submitted"
    Completed = "Completed"


class GradingProgress(Enum):
    """The `gradingProgress` of a score: a closed, spec-defined set the tool chooses from."""

    FullyGraded = "FullyGraded"
    Pending = "Pending"
    PendingManual = "PendingManual"
    Failed = "Failed"
    NotReady = "NotReady"


def _numberOrNone(value: object) -> float | None:
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else None


def _stringOrNone(value: object) -> str | None:
    return value if isinstance(value, str) else None


@dataclass(frozen=True)
class LineItem:
    """A gradebook column. `id` is None for one you are about to create; the platform assigns its URL."""

    id: str | None
    scoreMaximum: float
    label: str
    resourceId: str | None = None
    tag: str | None = None
    resourceLinkId: str | None = None

    def toDict(self) -> dict[str, object]:
        """The line item as the JSON object sent on create and update, omitting unset fields."""
        data: dict[str, object] = {"scoreMaximum": self.scoreMaximum, "label": self.label}
        for key, value in (
            ("resourceId", self.resourceId),
            ("tag", self.tag),
            ("resourceLinkId", self.resourceLinkId),
            ("id", self.id),
        ):
            if value is not None:
                data[key] = value
        return data

    @classmethod
    def fromResponseData(cls, data: object) -> "LineItem":
        """Build from a platform response, raising ServiceException when it is not a usable line item."""
        record = jsonObject(data)
        if record is None:
            raise ServiceException("AGS line item response was not a JSON object.")

        scoreMaximum = _numberOrNone(record.get("scoreMaximum"))
        if scoreMaximum is None:
            raise ServiceException('AGS line item response is missing a numeric "scoreMaximum".')

        label = record.get("label")
        if not isinstance(label, str) or label == "":
            raise ServiceException('AGS line item response is missing a "label".')

        return cls(
            _stringOrNone(record.get("id")),
            scoreMaximum,
            label,
            _stringOrNone(record.get("resourceId")),
            _stringOrNone(record.get("tag")),
            _stringOrNone(record.get("resourceLinkId")),
        )


@dataclass(frozen=True)
class Result:
    """A single entry from an AGS results read."""

    id: str
    scoreOf: str
    userId: str
    resultScore: float | None
    resultMaximum: float | None
    comment: str | None

    @classmethod
    def fromResponseData(cls, data: object) -> "Result":
        """Build from a platform response entry, raising ServiceException when required fields are missing."""
        record = jsonObject(data)
        if record is None:
            raise ServiceException("AGS result response entry was not a JSON object.")

        resultId = record.get("id")
        scoreOf = record.get("scoreOf")
        userId = record.get("userId")
        if not isinstance(resultId, str) or not isinstance(scoreOf, str) or not isinstance(userId, str):
            raise ServiceException("AGS result response entry is missing required fields.")

        return cls(
            resultId,
            scoreOf,
            userId,
            _numberOrNone(record.get("resultScore")),
            _numberOrNone(record.get("resultMaximum")),
            _stringOrNone(record.get("comment")),
        )


@dataclass(frozen=True)
class Score:
    """A score publish payload. The timestamp defaults to now and should be timezone-aware when given."""

    userId: str
    activityProgress: ActivityProgress
    gradingProgress: GradingProgress
    scoreGiven: float | None = None
    scoreMaximum: float | None = None
    comment: str | None = None
    timestamp: datetime | None = None

    def toDict(self) -> dict[str, object]:
        """The score as the JSON object posted to the line item's scores URL."""
        timestamp = self.timestamp if self.timestamp is not None else datetime.now(UTC)
        data: dict[str, object] = {
            "userId": self.userId,
            "activityProgress": self.activityProgress.value,
            "gradingProgress": self.gradingProgress.value,
            "timestamp": timestamp.isoformat(timespec="seconds"),
        }
        for key, value in (("scoreGiven", self.scoreGiven), ("scoreMaximum", self.scoreMaximum), ("comment", self.comment)):
            if value is not None:
                data[key] = value
        return data


class AssignmentsGradesService:
    """Line item CRUD, score publish, and result read against a platform's AGS endpoints.

    Line item listing fetches a single page and does not follow Link-header
    pagination, which matches what a tool typically needs: its own resource
    link's line items, not every line item in a course.
    """

    def __init__(self, httpClient: httpx.Client, accessTokenService: AccessTokenService):
        self.httpClient = httpClient
        self.accessTokenService = accessTokenService

    def listLineItems(self, registration: Registration, endpoint: AgsEndpoint) -> list[LineItem]:
        """The line items in the endpoint's collection (first page only)."""
        response = self._request(
            registration, "GET", endpoint.lineItemsUrl, [SCOPE_LINE_ITEM], CONTENT_TYPE_LINE_ITEM_CONTAINER
        )
        entries = jsonList(decodeJsonBody(response, endpoint.lineItemsUrl, SERVICE_NAME))
        if entries is None:
            raise ServiceException(f'AGS line items response from "{endpoint.lineItemsUrl}" was not a JSON array.')
        return [LineItem.fromResponseData(entry) for entry in entries]

    def createLineItem(self, registration: Registration, endpoint: AgsEndpoint, lineItem: LineItem) -> LineItem:
        """Create a line item and return it as the platform stored it, including its assigned id."""
        response = self._request(
            registration, "POST", endpoint.lineItemsUrl, [SCOPE_LINE_ITEM], CONTENT_TYPE_LINE_ITEM, lineItem.toDict()
        )
        return LineItem.fromResponseData(decodeJsonBody(response, endpoint.lineItemsUrl, SERVICE_NAME))

    def getLineItem(self, registration: Registration, lineItemUrl: str) -> LineItem:
        """Read one line item by its URL."""
        response = self._request(registration, "GET", lineItemUrl, [SCOPE_LINE_ITEM], CONTENT_TYPE_LINE_ITEM)
        return LineItem.fromResponseData(decodeJsonBody(response, lineItemUrl, SERVICE_NAME))

    def updateLineItem(self, registration: Registration, lineItemUrl: str, lineItem: LineItem) -> LineItem:
        """Replace a line item and return it as the platform stored it."""
        response = self._request(
            registration, "PUT", lineItemUrl, [SCOPE_LINE_ITEM], CONTENT_TYPE_LINE_ITEM, lineItem.toDict()
        )
        return LineItem.fromResponseData(decodeJsonBody(response, lineItemUrl, SERVICE_NAME))

    def deleteLineItem(self, registration: Registration, lineItemUrl: str) -> None:
        """Delete a line item."""
        self._request(registration, "DELETE", lineItemUrl, [SCOPE_LINE_ITEM], "application/json")

    def publishScore(self, registration: Registration, lineItemUrl: str, score: Score) -> None:
        """Post a score to the line item's scores URL."""
        self._request(
            registration, "POST", lineItemUrl.rstrip("/") + "/scores", [SCOPE_SCORE], CONTENT_TYPE_SCORE, score.toDict()
        )

    def listResults(self, registration: Registration, lineItemUrl: str) -> list[Result]:
        """Read the results recorded for the line item."""
        resultsUrl = lineItemUrl.rstrip("/") + "/results"
        response = self._request(
            registration, "GET", resultsUrl, [SCOPE_RESULT_READONLY], CONTENT_TYPE_RESULT_CONTAINER
        )
        entries = jsonList(decodeJsonBody(response, resultsUrl, SERVICE_NAME))
        if entries is None:
            raise ServiceException(f'AGS results response from "{resultsUrl}" was not a JSON array.')
        return [Result.fromResponseData(entry) for entry in entries]

    def _request(
        self,
        registration: Registration,
        method: str,
        url: str,
        scopes: Sequence[str],
        contentType: str,
        jsonBody: object = None,
    ) -> httpx.Response:
        return sendAuthorizedRequest(
            self.httpClient,
            self.accessTokenService,
            registration,
            method,
            url,
            scopes,
            accept=contentType,
            contentType=contentType,
            jsonBody=jsonBody,
            serviceName=SERVICE_NAME,
        )
