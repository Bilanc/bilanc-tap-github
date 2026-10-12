import unittest
from unittest import mock

import requests

import tap_github


class Mockresponse:
    def __init__(self, status_code, json=None, headers=None):
        self.status_code = status_code
        self._json = json or {}
        self.headers = headers or {"X-RateLimit-Remaining": 1}
        self.links = {}
        self.text = ""

    def json(self):
        return self._json


CHUNKED_ERROR = requests.exceptions.ChunkedEncodingError(
    "Connection broken: InvalidChunkLength(got length b'', 0 bytes read)"
)


@mock.patch("time.sleep")
@mock.patch("tap_github.get_request_timeout", return_value=300)
@mock.patch("tap_github.refresh_token_if_expired")
@mock.patch("requests.Session.request")
class TestChunkedEncodingRetry(unittest.TestCase):
    """GitHub occasionally drops the connection mid-body (ChunkedEncodingError);
    authed_get should retry it like any other connection error."""

    def test_transient_chunked_encoding_error_is_retried(
        self, mocked_request, mocked_refresh, mocked_timeout, mocked_sleep
    ):
        mocked_request.side_effect = [CHUNKED_ERROR, CHUNKED_ERROR, Mockresponse(200)]

        resp = tap_github.authed_get("artifacts", "https://api.github.com/x")

        self.assertEqual(resp.status_code, 200)
        self.assertEqual(mocked_request.call_count, 3)

    def test_persistent_chunked_encoding_error_exhausts_retries(
        self, mocked_request, mocked_refresh, mocked_timeout, mocked_sleep
    ):
        mocked_request.side_effect = CHUNKED_ERROR

        with self.assertRaises(requests.exceptions.ChunkedEncodingError):
            tap_github.authed_get("artifacts", "https://api.github.com/x")

        self.assertEqual(mocked_request.call_count, 10)


if __name__ == "__main__":
    unittest.main()
