"""GitHub only serves Copilot daily reports for days within the last year.

Regression tests for the full-sync failure where a stale connector start_date
(and no copilot bookmark) made the tap request a day older than a year, GitHub
answered HTTP 400 and the whole sync exited.
"""
import unittest
from datetime import datetime, timedelta
from unittest import mock

import tap_github


class MockResponse:
    def __init__(self, status_code, payload=None):
        self.status_code = status_code
        self._payload = payload or {}
        self.headers = {}

    def json(self):
        return self._payload


SCHEMA = {"type": "object"}
MDATA = {}
STALE_START_DATE = (datetime.utcnow() - timedelta(days=445)).strftime("%Y-%m-%dT00:00:00Z")


def requested_day(call):
    return call.args[1].split("day=")[1]


@mock.patch("tap_github.enterprise_slug", None)
@mock.patch("tap_github.organization", "acme")
@mock.patch("tap_github.singer.write_bookmark")
@mock.patch("tap_github.authed_get")
class TestCopilotDayClamp(unittest.TestCase):
    def test_stale_start_date_is_clamped_to_github_window(
        self, mocked_get, mocked_bookmark
    ):
        # 403 makes the stream stop after the first request, so we only
        # care about which day it asked for.
        mocked_get.return_value = MockResponse(403, {"message": "forbidden"})

        tap_github.get_copilot_user_metrics_1_day(SCHEMA, None, {}, MDATA, STALE_START_DATE)

        expected = datetime.utcnow().date() - timedelta(days=tap_github.COPILOT_REPORT_MAX_AGE_DAYS)
        self.assertEqual(mocked_get.call_count, 1)
        self.assertEqual(requested_day(mocked_get.call_args), expected.strftime("%Y-%m-%d"))

    def test_recent_start_date_is_not_clamped(self, mocked_get, mocked_bookmark):
        mocked_get.return_value = MockResponse(403, {"message": "forbidden"})
        recent = datetime.utcnow().date() - timedelta(days=10)

        tap_github.get_copilot_user_metrics_1_day(
            SCHEMA, None, {}, MDATA, recent.strftime("%Y-%m-%dT00:00:00Z")
        )

        self.assertEqual(requested_day(mocked_get.call_args), recent.strftime("%Y-%m-%d"))

    def test_stale_bookmark_is_clamped_too(self, mocked_get, mocked_bookmark):
        mocked_get.return_value = MockResponse(403, {"message": "forbidden"})
        stale_day = (datetime.utcnow().date() - timedelta(days=500)).strftime("%Y-%m-%d")
        state = {"bookmarks": {"acme": {"copilot_user_metrics_1_day": {"last_day": stale_day}}}}

        tap_github.get_copilot_user_metrics_1_day(SCHEMA, None, state, MDATA, STALE_START_DATE)

        expected = datetime.utcnow().date() - timedelta(days=tap_github.COPILOT_REPORT_MAX_AGE_DAYS)
        self.assertEqual(requested_day(mocked_get.call_args), expected.strftime("%Y-%m-%d"))

    def test_http_400_skips_stream_without_failing_sync(self, mocked_get, mocked_bookmark):
        mocked_get.return_value = MockResponse(
            400, {"message": "Invalid day parameter. Expected format: YYYY-MM-DD"}
        )
        state = {}

        result = tap_github.get_copilot_user_metrics_1_day(
            SCHEMA, None, state, MDATA, STALE_START_DATE
        )

        self.assertIs(result, state)
        # One rejected request, then stop; don't walk the remaining days.
        self.assertEqual(mocked_get.call_count, 1)
        mocked_bookmark.assert_not_called()


@mock.patch("tap_github.get_request_timeout", return_value=300)
@mock.patch("tap_github.refresh_token_if_expired")
@mock.patch("tap_github.session.request")
class TestAuthedGetPassesCopilot400Through(unittest.TestCase):
    def test_copilot_400_is_returned_not_raised(self, mocked_request, _refresh, _timeout):
        mocked_request.return_value = MockResponse(400, {"message": "Invalid day parameter"})

        resp = tap_github.authed_get(
            tap_github.COPILOT_USER_METRICS_STREAM, "https://api.github.com/x?day=2025-07-21"
        )

        self.assertEqual(resp.status_code, 400)

    def test_other_streams_still_raise_on_400(self, mocked_request, _refresh, _timeout):
        mocked_request.return_value = MockResponse(400, {"message": "bad"})

        with self.assertRaises(tap_github.BadRequestException):
            tap_github.authed_get("commits", "https://api.github.com/x")
