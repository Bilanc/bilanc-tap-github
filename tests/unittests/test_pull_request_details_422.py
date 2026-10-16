import unittest
from unittest import mock

import tap_github


TOO_MANY_FILES_BODY = {
    "message": "The request could not be processed because too many files changed",
    "documentation_url": "https://docs.github.com/rest/pulls/pulls#get-a-pull-request",
    "status": "422",
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


class TestRaiseForErrorTooManyFiles422(unittest.TestCase):

    def test_too_many_files_422_on_pr_details_is_skipped(self):
        result = tap_github.raise_for_error(
            Mockresponse(422, TOO_MANY_FILES_BODY), "pull_request_details", 4000
        )
        self.assertIsNone(result)

    def test_too_many_files_422_on_other_source_still_unprocessable(self):
        with self.assertRaises(tap_github.UnprocessableError):
            tap_github.raise_for_error(
                Mockresponse(422, TOO_MANY_FILES_BODY), "pull_requests", 4000
            )

    def test_other_422_on_pr_details_still_unprocessable(self):
        body = {"message": "Validation Failed", "status": "422"}
        with self.assertRaises(tap_github.UnprocessableError):
            tap_github.raise_for_error(
                Mockresponse(422, body), "pull_request_details", 4000
            )


@mock.patch("time.sleep")
@mock.patch("tap_github.get_request_timeout", return_value=300)
@mock.patch("tap_github.refresh_token_if_expired")
@mock.patch("requests.Session.request")
class TestGetPullRequestDetailsTooManyFiles(unittest.TestCase):

    def test_returns_none_without_retrying(
        self, mocked_request, mocked_refresh, mocked_timeout, mocked_sleep
    ):
        mocked_request.return_value = Mockresponse(422, TOO_MANY_FILES_BODY)

        rec = tap_github.get_pull_request_details(
            {"url": "https://api.github.com/repos/org/repo/pulls/119"},
            {"type": "object", "properties": {}},
            "org/repo",
            {},
            [],
        )

        self.assertIsNone(rec)
        self.assertEqual(mocked_request.call_count, 1)

    def test_returns_record_on_200(
        self, mocked_request, mocked_refresh, mocked_timeout, mocked_sleep
    ):
        mocked_request.return_value = Mockresponse(
            200, {"id": 1, "number": 119, "changed_files": 3}
        )
        schema = {
            "type": "object",
            "properties": {
                "id": {"type": ["null", "integer"]},
                "number": {"type": ["null", "integer"]},
                "changed_files": {"type": ["null", "integer"]},
                "_sdc_repository": {"type": ["null", "string"]},
            },
        }

        rec = tap_github.get_pull_request_details(
            {"url": "https://api.github.com/repos/org/repo/pulls/119"},
            schema,
            "org/repo",
            {},
            [],
        )

        self.assertEqual(rec["number"], 119)
        self.assertEqual(rec["_sdc_repository"], "org/repo")
