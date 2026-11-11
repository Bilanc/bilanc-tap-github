"""The Copilot per-user daily report carries `ai_credits_used` (a float) on
records from mid-June 2026 onwards; older records have no such key."""
import json
import unittest
from datetime import datetime, timedelta
from unittest import mock

import tap_github


class MockResponse:
    def __init__(self, status_code=200, payload=None, lines=None):
        self.status_code = status_code
        self._payload = payload or {}
        self._lines = lines or []
        self.headers = {}

    def json(self):
        return self._payload

    def raise_for_status(self):
        pass

    def iter_lines(self, decode_unicode=False):
        return iter(self._lines)


SCHEMA = tap_github.load_schemas()[tap_github.COPILOT_USER_METRICS_STREAM]
YESTERDAY = datetime.utcnow().date() - timedelta(days=1)


def sync_report_lines(report_records):
    """Run the stream for yesterday only and return the records it wrote."""
    lines = [json.dumps(record) for record in report_records]
    with mock.patch("tap_github.enterprise_slug", None), mock.patch(
        "tap_github.organization", "acme"
    ), mock.patch("tap_github.singer.write_bookmark"), mock.patch(
        "tap_github.authed_get",
        return_value=MockResponse(payload={"download_links": ["https://reports.test/part-0"]}),
    ), mock.patch(
        "tap_github.requests.get", return_value=MockResponse(lines=lines)
    ), mock.patch("tap_github.get_request_timeout", return_value=300), mock.patch(
        "tap_github.write_record"
    ) as mocked_write:
        tap_github.get_copilot_user_metrics_1_day(
            SCHEMA, None, {}, {}, YESTERDAY.strftime("%Y-%m-%dT00:00:00Z")
        )
    return [call.args[1] for call in mocked_write.call_args_list]


class TestCopilotAiCreditsUsed(unittest.TestCase):
    def test_ai_credits_used_is_emitted_as_reported(self):
        # given
        report_records = [
            {"day": str(YESTERDAY), "user_login": "octocat", "ai_credits_used": 12.5},
            {"day": str(YESTERDAY), "user_login": "hubot", "ai_credits_used": 0.0},
        ]

        # when
        written = sync_report_lines(report_records)

        # then
        self.assertEqual([record["ai_credits_used"] for record in written], [12.5, 0.0])

    def test_record_without_ai_credits_used_emits_null(self):
        # given
        report_records = [{"day": str(YESTERDAY), "user_login": "octocat"}]

        # when
        written = sync_report_lines(report_records)

        # then
        self.assertEqual(len(written), 1)
        self.assertIsNone(written[0]["ai_credits_used"])
