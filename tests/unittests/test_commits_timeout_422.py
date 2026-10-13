import json
import os
import unittest
from unittest import mock

import tap_github


TIMEOUT_BODY = {
    "message": "The request is taking too long to process.",
    "documentation_url": "https://docs.github.com/rest/commits/commits#list-commits",
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


def load_commits_schema():
    path = os.path.join(os.path.dirname(tap_github.__file__), "schemas", "commits.json")
    with open(path) as f:
        return json.load(f)


REPO = "org/repo"
START_DATE = "2026-01-01T00:00:00Z"


class TestRaiseForError422(unittest.TestCase):

    def test_timeout_422_is_retriable(self):
        with self.assertRaises(tap_github.RetriableServerError):
            tap_github.raise_for_error(Mockresponse(422, TIMEOUT_BODY), "commits", 4000)

    def test_other_422_still_unprocessable(self):
        body = {"message": "Validation Failed", "status": "422"}
        with self.assertRaises(tap_github.UnprocessableError):
            tap_github.raise_for_error(Mockresponse(422, body), "commits", 4000)

    def test_pagination_cap_422_still_unprocessable(self):
        body = {"message": "In order to keep the API fast for everyone, pagination is limited for this resource. Only the first 10000 results are available."}
        with self.assertRaises(tap_github.UnprocessableError):
            tap_github.raise_for_error(Mockresponse(422, body), "issues", 4000)


@mock.patch("time.sleep")
@mock.patch("tap_github.get_request_timeout", return_value=300)
@mock.patch("tap_github.refresh_token_if_expired")
@mock.patch("requests.Session.request")
class TestAuthedGetRetriesTimeout422(unittest.TestCase):
    """Drive the real authed_get backoff loop."""

    def test_transient_timeout_422_is_retried(
        self, mocked_request, mocked_refresh, mocked_timeout, mocked_sleep
    ):
        mocked_request.side_effect = [
            Mockresponse(422, TIMEOUT_BODY),
            Mockresponse(422, TIMEOUT_BODY),
            Mockresponse(200, []),
        ]

        resp = tap_github.authed_get("commits", "https://api.github.com/x")

        self.assertEqual(resp.status_code, 200)
        self.assertEqual(mocked_request.call_count, 3)

    def test_persistent_timeout_422_exhausts_retries(
        self, mocked_request, mocked_refresh, mocked_timeout, mocked_sleep
    ):
        mocked_request.return_value = Mockresponse(422, TIMEOUT_BODY)

        with self.assertRaises(tap_github.RetriableServerError):
            tap_github.authed_get("commits", "https://api.github.com/x")

        self.assertEqual(mocked_request.call_count, 10)

    def test_other_422_is_not_retried(
        self, mocked_request, mocked_refresh, mocked_timeout, mocked_sleep
    ):
        mocked_request.return_value = Mockresponse(422, {"message": "Validation Failed"})

        with self.assertRaises(tap_github.UnprocessableError):
            tap_github.authed_get("commits", "https://api.github.com/x")

        self.assertEqual(mocked_request.call_count, 1)


@mock.patch("tap_github.write_record")
@mock.patch("tap_github.get_default_branch", return_value="main")
@mock.patch("tap_github.authed_get")
class TestCommitsServerErrorSkipsRepo(unittest.TestCase):

    def test_exhausted_server_error_skips_repo_without_bookmark(
        self, mocked_authed_get, mocked_branch, mocked_write_record
    ):
        mocked_authed_get.side_effect = tap_github.RetriableServerError("422 timeout")
        state = {}

        result = tap_github.get_all_commits(load_commits_schema(), REPO, state, [], START_DATE)

        self.assertIs(result, state)
        self.assertIsNone(tap_github.get_bookmark(state, REPO, "commits", "since", None))
        mocked_write_record.assert_not_called()

    def test_exhausted_server_error_keeps_existing_bookmark(
        self, mocked_authed_get, mocked_branch, mocked_write_record
    ):
        mocked_authed_get.side_effect = tap_github.RetriableServerError("422 timeout")
        state = {"bookmarks": {REPO: {"commits": {"since": "2026-02-01T00:00:00Z"}}}}

        tap_github.get_all_commits(load_commits_schema(), REPO, state, [], START_DATE)

        self.assertEqual(
            tap_github.get_bookmark(state, REPO, "commits", "since", None),
            "2026-02-01T00:00:00Z",
        )

    def test_other_errors_still_propagate(
        self, mocked_authed_get, mocked_branch, mocked_write_record
    ):
        mocked_authed_get.side_effect = tap_github.BadCredentialsException("401")

        with self.assertRaises(tap_github.BadCredentialsException):
            tap_github.get_all_commits(load_commits_schema(), REPO, {}, [], START_DATE)

    def test_success_writes_records(
        self, mocked_authed_get, mocked_branch, mocked_write_record
    ):
        commit = {
            "sha": "abc123",
            "commit": {"message": "m", "author": {"date": "2026-03-01T00:00:00Z"}},
        }
        mocked_authed_get.return_value = Mockresponse(200, [commit])

        with mock.patch("tap_github.get_commit_pull_request_ids", return_value=[]), \
                mock.patch.dict(tap_github._commit_stats_cache, {(REPO, "abc123"): {}}):
            state = {}
            tap_github.get_all_commits(load_commits_schema(), REPO, state, [], START_DATE)

        self.assertEqual(mocked_write_record.call_count, 1)
        self.assertIsNotNone(tap_github.get_bookmark(state, REPO, "commits", "since", None))


if __name__ == "__main__":
    unittest.main()
