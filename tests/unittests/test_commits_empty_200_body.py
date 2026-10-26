import json
import unittest
from unittest import mock

from simplejson import JSONDecodeError

import tap_github


class Mockresponse:
    """Mimic requests.Response closely enough for authed_get: json() raises
    the same error requests does on a body that is not JSON."""

    def __init__(self, status_code, content=b"", links=None):
        self.status_code = status_code
        self.content = content
        self.text = content.decode("utf-8", errors="replace")
        self.headers = {"X-RateLimit-Remaining": 4000, "X-RateLimit-Reset": 0}
        self.links = links or {}

    def json(self):
        # simplejson's JSONDecodeError (a ValueError), as requests raises it
        if not self.content.strip():
            raise JSONDecodeError("Expecting value", "", 0)
        try:
            return json.loads(self.content)
        except ValueError:
            raise JSONDecodeError("Expecting value", self.text, 0)


class TestHasJsonBody(unittest.TestCase):

    def test_empty_body_is_not_json(self):
        self.assertFalse(tap_github.has_json_body(Mockresponse(200, b"")))

    def test_html_body_is_not_json(self):
        self.assertFalse(tap_github.has_json_body(Mockresponse(200, b"<html>502</html>")))

    def test_json_list_is_json(self):
        self.assertTrue(tap_github.has_json_body(Mockresponse(200, b"[]")))

    def test_json_object_is_json(self):
        self.assertTrue(tap_github.has_json_body(Mockresponse(200, b'{"a": 1}')))


@mock.patch("time.sleep")
@mock.patch("tap_github.get_request_timeout", return_value=300)
@mock.patch("tap_github.refresh_token_if_expired")
@mock.patch("requests.Session.request")
class TestAuthedGetRetriesEmpty200(unittest.TestCase):
    """Drive the real authed_get backoff loop with a 200/empty-body response,
    the shape GitHub returned for newscorp-ghfb list-commits (job u68p16vlzlogvqmb5z1n7)."""

    def test_transient_empty_200_is_retried(
        self, mocked_request, mocked_refresh, mocked_timeout, mocked_sleep
    ):
        mocked_request.side_effect = [
            Mockresponse(200, b""),
            Mockresponse(200, b""),
            Mockresponse(200, b"[]"),
        ]

        resp = tap_github.authed_get("commits", "https://api.github.com/x")

        self.assertEqual(resp.json(), [])
        self.assertEqual(mocked_request.call_count, 3)

    def test_persistent_empty_200_exhausts_retries(
        self, mocked_request, mocked_refresh, mocked_timeout, mocked_sleep
    ):
        mocked_request.return_value = Mockresponse(200, b"")

        with self.assertRaises(tap_github.RetriableServerError):
            tap_github.authed_get("commits", "https://api.github.com/x")

        self.assertEqual(mocked_request.call_count, 10)

    def test_valid_200_is_not_retried(
        self, mocked_request, mocked_refresh, mocked_timeout, mocked_sleep
    ):
        mocked_request.return_value = Mockresponse(200, b'{"default_branch": "main"}')

        resp = tap_github.authed_get("repo_info", "https://api.github.com/x")

        self.assertEqual(resp.json()["default_branch"], "main")
        self.assertEqual(mocked_request.call_count, 1)

    def test_404_still_returns_empty_object(
        self, mocked_request, mocked_refresh, mocked_timeout, mocked_sleep
    ):
        mocked_request.return_value = Mockresponse(404, b"")

        resp = tap_github.authed_get("commits", "https://api.github.com/x")

        self.assertEqual(resp.content, b"")
        self.assertEqual(resp._content, b"{}")
        self.assertEqual(mocked_request.call_count, 1)


if __name__ == "__main__":
    unittest.main()
