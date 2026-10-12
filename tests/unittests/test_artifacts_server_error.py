import json
import os
import unittest
from unittest import mock

import tap_github


class Mockresponse:
    def __init__(self, status_code, json, links=None):
        self.status_code = status_code
        self._json = json
        self.links = links or {}

    def json(self):
        return self._json


def load_artifacts_schema():
    path = os.path.join(
        os.path.dirname(tap_github.__file__), "schemas", "artifacts.json"
    )
    with open(path) as f:
        return json.load(f)


REPO = "org/repo"
START_DATE = "2026-01-01T00:00:00Z"


@mock.patch("tap_github.write_record")
@mock.patch("tap_github.authed_get")
class TestArtifactsServerError(unittest.TestCase):

    def test_server_error_skips_repo_without_bookmark(self, mocked_authed_get, mocked_write_record):
        mocked_authed_get.side_effect = tap_github.RetriableServerError("500 Server Error")
        state = {}

        result = tap_github.get_all_artifacts(load_artifacts_schema(), REPO, state, [], START_DATE)

        self.assertIs(result, state)
        self.assertIsNone(tap_github.get_bookmark(state, REPO, "artifacts", "since", None))
        mocked_write_record.assert_not_called()

    def test_server_error_keeps_existing_bookmark(self, mocked_authed_get, mocked_write_record):
        mocked_authed_get.side_effect = tap_github.RetriableServerError("500 Server Error")
        state = {"bookmarks": {REPO: {"artifacts": {"since": "2026-02-01T00:00:00Z"}}}}

        tap_github.get_all_artifacts(load_artifacts_schema(), REPO, state, [], START_DATE)

        self.assertEqual(
            tap_github.get_bookmark(state, REPO, "artifacts", "since", None),
            "2026-02-01T00:00:00Z",
        )

    def test_success_writes_records_and_bookmark(self, mocked_authed_get, mocked_write_record):
        artifact = {
            "id": 1,
            "name": "build",
            "updated_at": "2026-03-01T00:00:00Z",
            "workflow_run": {"id": 42},
        }
        mocked_authed_get.return_value = Mockresponse(200, {"artifacts": [artifact]})
        state = {}

        tap_github.get_all_artifacts(load_artifacts_schema(), REPO, state, [], START_DATE)

        self.assertEqual(mocked_write_record.call_count, 1)
        self.assertIsNotNone(tap_github.get_bookmark(state, REPO, "artifacts", "since", None))

    def test_other_errors_still_propagate(self, mocked_authed_get, mocked_write_record):
        mocked_authed_get.side_effect = tap_github.BadCredentialsException("401")

        with self.assertRaises(tap_github.BadCredentialsException):
            tap_github.get_all_artifacts(load_artifacts_schema(), REPO, {}, [], START_DATE)
