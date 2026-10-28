"""Tests for typed reads over the raw claims mapping decoded from a JWT."""

import pytest

from lti1p3.claims import optionalArray, optionalBool, optionalInt, optionalString, optionalStringList, requireString
from lti1p3.exceptions import InvalidLaunchException, InvalidLaunchReason


class TestRequireString:
    def test_returnsThePresentValue(self):
        assert requireString({"key": "value"}, "key", "context") == "value"

    def test_throwsWhenMissing(self):
        with pytest.raises(InvalidLaunchException) as caught:
            requireString({}, "key", "context")
        assert caught.value.reason is InvalidLaunchReason.MissingRequiredClaim

    def test_throwsWhenEmpty(self):
        with pytest.raises(InvalidLaunchException):
            requireString({"key": ""}, "key", "context")

    def test_throwsWhenWrongType(self):
        with pytest.raises(InvalidLaunchException):
            requireString({"key": 123}, "key", "context")


class TestOptionalReads:
    def test_optionalStringReturnsNoneWhenMissingEmptyOrWrongType(self):
        assert optionalString({}, "key") is None
        assert optionalString({"key": ""}, "key") is None
        assert optionalString({"key": 123}, "key") is None

    def test_optionalStringReturnsTheValueWhenPresent(self):
        assert optionalString({"key": "value"}, "key") == "value"

    def test_optionalIntReturnsTheIntWhenPresent(self):
        assert optionalInt({"key": 42}, "key") == 42

    def test_optionalIntReturnsNoneWhenMissingOrWrongType(self):
        assert optionalInt({}, "key") is None
        assert optionalInt({"key": "not-an-int"}, "key") is None
        assert optionalInt({"key": "42"}, "key") is None
        assert optionalInt({"key": True}, "key") is None

    def test_optionalBoolReturnsTheBoolWhenPresent(self):
        assert optionalBool({"key": True}, "key") is True
        assert optionalBool({"key": False}, "key") is False

    def test_optionalBoolReturnsNoneWhenMissingOrWrongType(self):
        assert optionalBool({}, "key") is None
        assert optionalBool({"key": "true"}, "key") is None

    def test_optionalStringListFiltersOutNonStringEntries(self):
        assert optionalStringList({"key": ["a", "b", 123, None]}, "key") == ["a", "b"]

    def test_optionalStringListReturnsEmptyListWhenMissingOrWrongType(self):
        assert optionalStringList({}, "key") == []
        assert optionalStringList({"key": "not-a-list"}, "key") == []

    def test_optionalArrayReturnsTheMappingWhenPresent(self):
        assert optionalArray({"key": {"a": 1}}, "key") == {"a": 1}

    def test_optionalArrayReturnsNoneWhenMissingOrWrongType(self):
        assert optionalArray({}, "key") is None
        assert optionalArray({"key": "not-a-mapping"}, "key") is None
