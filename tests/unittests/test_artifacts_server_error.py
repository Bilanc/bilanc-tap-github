"""A repo whose artifacts endpoint keeps returning 5xx must not fail the sync.

Regression tests for the hourly-sync failure where GitHub answered HTTP 500 on
every retry of one repo's /actions/artifacts call, the exhausted
RetriableServerError escaped get_all_artifacts and the whole job (and its
export) was rolled back. The artifacts stream is skipped for that repo and its
bookmark is left untouched so it is retried on the next run.
"""
import unittest
from unittest import mock

import tap_github


class MockResponse:
    def __init__(self, payload):
        self._payload = payload
        self.links = {}

    def json(self):
        return self._payload


SCHEMA = {"type": "object"}
MDATA = {}
REPO = "gofundme/ssr-frontend"


def failing_pages(*args, **kwargs):
    raise tap_github.RetriableServerError("500 Internal Server Error")
    yield  # pylint: disable=unreachable


@mock.patch("tap_github.write_record")
@mock.patch("tap_github.singer.Transformer")
@mock.patch("tap_github.singer.write_bookmark")
@mock.patch("tap_github.authed_get_all_pages")
class TestArtifactsServerError(unittest.TestCase):
    def test_exhausted_5xx_skips_repo_and_keeps_bookmark(
        self, mocked_pages, mocked_bookmark, mocked_transformer, mocked_write_record
    ):
        mocked_pages.side_effect = failing_pages
        state = {"bookmarks": {REPO: {"artifacts": {"since": "2026-10-01T00:00:00Z"}}}}

        result = tap_github.get_all_artifacts(SCHEMA, REPO, state, MDATA, None)

        self.assertIs(result, state)
        mocked_bookmark.assert_not_called()
        mocked_write_record.assert_not_called()

    def test_completed_repo_advances_bookmark(
        self, mocked_pages, mocked_bookmark, mocked_transformer, mocked_write_record
    ):
        mocked_pages.return_value = iter(
            [MockResponse({"artifacts": [{"id": 1, "updated_at": "2026-10-11T00:00:00Z", "workflow_run": {"id": 9}}]})]
        )
        mocked_transformer.return_value.__enter__.return_value.transform.return_value = {}
        state = {"bookmarks": {REPO: {"artifacts": {"since": "2026-10-01T00:00:00Z"}}}}

        tap_github.get_all_artifacts(SCHEMA, REPO, state, MDATA, None)

        self.assertEqual(mocked_write_record.call_count, 1)
        self.assertEqual(mocked_bookmark.call_count, 1)
        self.assertEqual(mocked_bookmark.call_args.args[1:3], (REPO, "artifacts"))

    def test_other_errors_still_propagate(
        self, mocked_pages, mocked_bookmark, mocked_transformer, mocked_write_record
    ):
        def boom(*args, **kwargs):
            raise tap_github.AuthException("bad token")
            yield  # pylint: disable=unreachable

        mocked_pages.side_effect = boom
        with self.assertRaises(tap_github.AuthException):
            tap_github.get_all_artifacts(SCHEMA, REPO, {}, MDATA, None)
        mocked_bookmark.assert_not_called()


@mock.patch("tap_github.authed_get")
class TestBadGatewayPropagation(unittest.TestCase):
    def test_502_propagates_for_artifacts(self, mocked_get):
        mocked_get.side_effect = tap_github.BadGatewayError("502 Bad Gateway")
        with self.assertRaises(tap_github.BadGatewayError):
            list(tap_github.authed_get_all_pages("artifacts", "https://api.github.com/x"))

    def test_502_still_ends_other_streams_quietly(self, mocked_get):
        mocked_get.side_effect = tap_github.BadGatewayError("502 Bad Gateway")
        self.assertEqual(list(tap_github.authed_get_all_pages("commits", "https://api.github.com/x")), [])

    def test_artifacts_502_keeps_bookmark(self, mocked_get):
        mocked_get.side_effect = tap_github.BadGatewayError("502 Bad Gateway")
        state = {"bookmarks": {REPO: {"artifacts": {"since": "2026-10-01T00:00:00Z"}}}}
        with mock.patch("tap_github.singer.write_bookmark") as mocked_bookmark:
            tap_github.get_all_artifacts(SCHEMA, REPO, state, MDATA, None)
        mocked_bookmark.assert_not_called()
