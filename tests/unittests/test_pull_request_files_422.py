import unittest
from unittest import mock

import tap_github


DIFF_TOO_SLOW_BODY = {
    "message": "Server Error: Sorry, this diff is taking too long to generate.",
    "errors": [{"resource": "PullRequest", "field": "diff", "code": "not_available"}],
    "documentation_url": "https://docs.github.com/enterprise-server@3.20/rest/pulls/pulls#list-pull-requests-files",
    "status": "422",
}

FILES_SCHEMA = {
    "type": "object",
    "properties": {
        "id": {"type": ["null", "string"]},
        "sha": {"type": ["null", "string"]},
        "filename": {"type": ["null", "string"]},
        "pr_number": {"type": ["null", "integer"]},
        "pr_id": {"type": ["null", "integer"]},
        "_sdc_repository": {"type": ["null", "string"]},
    },
}


class Mockresponse:
    def __init__(self, status_code, json=None, text="", links=None):
        self.status_code = status_code
        self._json = json if json is not None else {}
        self.text = text or (str(json) if json else "")
        self.headers = {"X-RateLimit-Remaining": 4000, "X-RateLimit-Reset": 0}
        self.links = links or {}

    def json(self):
        return self._json


class TestRaiseForErrorDiffTooSlow422(unittest.TestCase):

    def test_diff_too_slow_422_on_pr_files_is_skipped(self):
        result = tap_github.raise_for_error(
            Mockresponse(422, DIFF_TOO_SLOW_BODY), "pull_request_files", 4000
        )
        self.assertIsNone(result)

    def test_diff_too_slow_422_on_other_source_still_unprocessable(self):
        with self.assertRaises(tap_github.UnprocessableError):
            tap_github.raise_for_error(
                Mockresponse(422, DIFF_TOO_SLOW_BODY), "pull_requests", 4000
            )

    def test_other_422_on_pr_files_still_unprocessable(self):
        body = {"message": "Validation Failed", "status": "422"}
        with self.assertRaises(tap_github.UnprocessableError):
            tap_github.raise_for_error(
                Mockresponse(422, body), "pull_request_files", 4000
            )


@mock.patch("time.sleep")
@mock.patch("tap_github.get_request_timeout", return_value=300)
@mock.patch("tap_github.refresh_token_if_expired")
@mock.patch("requests.Session.request")
class TestGetPullRequestFilesDiffTooSlow(unittest.TestCase):

    def test_yields_nothing_without_retrying(
        self, mocked_request, mocked_refresh, mocked_timeout, mocked_sleep
    ):
        mocked_request.return_value = Mockresponse(422, DIFF_TOO_SLOW_BODY)

        files = list(
            tap_github.get_pull_request_files(119, 1, FILES_SCHEMA, "org/repo", {}, [])
        )

        self.assertEqual(files, [])
        self.assertEqual(mocked_request.call_count, 1)

    def test_keeps_earlier_pages_when_a_later_page_422s(
        self, mocked_request, mocked_refresh, mocked_timeout, mocked_sleep
    ):
        mocked_request.side_effect = [
            Mockresponse(
                200,
                [{"sha": "abc", "filename": "a.py"}],
                links={"next": {"url": "https://api.github.com/next"}},
            ),
            Mockresponse(422, DIFF_TOO_SLOW_BODY),
        ]

        files = list(
            tap_github.get_pull_request_files(119, 1, FILES_SCHEMA, "org/repo", {}, [])
        )

        self.assertEqual([f["id"] for f in files], ["1-abc"])
        self.assertEqual(mocked_request.call_count, 2)
