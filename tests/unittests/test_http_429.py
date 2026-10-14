import json
import unittest
from email.utils import formatdate
from unittest import mock

import requests

import tap_github


def response(status=429, headers=None):
    result = requests.Response()
    result.status_code = status
    result.headers.update(headers or {})
    result._content = json.dumps(
        {"message": "This endpoint is temporarily being throttled."}
    ).encode()
    return result


class TestThrottleDelay(unittest.TestCase):
    def test_fallback_increases_and_is_capped(self):
        self.assertEqual(
            [
                tap_github.get_throttle_delay(response(), attempt)
                for attempt in range(6)
            ],
            [60, 120, 240, 480, 600, 600],
        )

    def test_retry_after_is_a_minimum_not_capped(self):
        self.assertEqual(
            tap_github.get_throttle_delay(response(headers={"Retry-After": "900"}), 0),
            900,
        )
        self.assertEqual(
            tap_github.get_throttle_delay(response(headers={"Retry-After": "1"}), 1),
            120,
        )

    @mock.patch("time.time", return_value=1700000000)
    def test_retry_after_http_date(self, _time):
        headers = {"Retry-After": formatdate(1700000900, usegmt=True)}
        self.assertEqual(
            tap_github.get_throttle_delay(response(headers=headers), 0), 900
        )

    def test_invalid_retry_after_uses_fallback(self):
        for value in (None, "", "invalid", "-10", "nan", "inf", "-inf"):
            with self.subTest(value=value):
                self.assertEqual(
                    tap_github.get_throttle_delay(
                        response(headers={"Retry-After": value}), 0
                    ),
                    60,
                )

    @mock.patch("time.time", return_value=1700000000)
    def test_exhausted_primary_quota_honors_reset(self, _time):
        headers = {
            "X-RateLimit-Remaining": "0",
            "X-RateLimit-Reset": "1700003600",
            "Retry-After": "120",
        }
        self.assertEqual(
            tap_github.get_throttle_delay(response(headers=headers), 0), 3600
        )

    @mock.patch("time.time", return_value=1700000000)
    def test_secondary_limit_does_not_wait_for_primary_reset(self, _time):
        headers = {"X-RateLimit-Remaining": "11893", "X-RateLimit-Reset": "1700003424"}
        self.assertEqual(
            tap_github.get_throttle_delay(response(headers=headers), 0), 60
        )

    def test_invalid_or_missing_primary_reset_uses_fallback(self):
        for value in (None, "invalid"):
            headers = {"X-RateLimit-Remaining": "0"}
            if value is not None:
                headers["X-RateLimit-Reset"] = value
            with self.subTest(value=value):
                self.assertEqual(
                    tap_github.get_throttle_delay(response(headers=headers), 0), 60
                )


class TestHttp429Retry(unittest.TestCase):
    def setUp(self):
        self.request = self.patch("tap_github.session.request")
        self.sleep = self.patch("time.sleep")
        self.refresh = self.patch("tap_github.refresh_token_if_expired")
        self.patch("tap_github.get_request_timeout", return_value=300)

    def patch(self, target, **kwargs):
        patcher = mock.patch(target, **kwargs)
        self.addCleanup(patcher.stop)
        return patcher.start()

    def test_throttled_repo_info_retries_same_request_then_succeeds(self):
        success = response(200)
        self.request.side_effect = [
            response(headers={"Retry-After": "90", "X-RateLimit-Remaining": "11893"}),
            success,
        ]
        url = "https://api.github.com/repos/example/repo"
        headers = {"Accept": "application/vnd.github+json"}

        self.assertIs(tap_github.authed_get("repo_info", url, headers), success)

        self.assertEqual(
            self.request.call_args_list,
            [mock.call(method="get", url=url, headers=headers, timeout=300)] * 2,
        )
        self.sleep.assert_called_once_with(90)
        self.assertEqual(self.refresh.call_count, 2)

    def test_persistent_throttling_stops_after_five_requests(self):
        self.request.return_value = response()

        with self.assertRaisesRegex(tap_github.GithubException, "HTTP-error-code: 429"):
            tap_github.authed_get(
                "repo_info", "https://api.github.com/repos/example/repo"
            )

        self.assertEqual(self.request.call_count, 5)
        self.assertEqual(
            self.sleep.call_args_list,
            [mock.call(60), mock.call(120), mock.call(240), mock.call(480)],
        )

    def test_401_is_not_retried(self):
        self.request.return_value = response(401)
        with self.assertRaises(tap_github.BadCredentialsException):
            tap_github.authed_get(
                "repo_info", "https://api.github.com/repos/example/repo"
            )
        self.request.assert_called_once()
        self.sleep.assert_not_called()

    def test_success_does_not_sleep(self):
        self.request.return_value = response(200)
        self.assertEqual(
            tap_github.authed_get(
                "repo_info", "https://api.github.com/repos/example/repo"
            ).status_code,
            200,
        )
        self.request.assert_called_once()
        self.sleep.assert_not_called()

    def test_retry_log_does_not_dump_headers(self):
        self.request.side_effect = [
            response(
                headers={
                    "Retry-After": "invalid-sensitive-value",
                    "Authorization": "secret",
                }
            ),
            response(200),
        ]
        with mock.patch.object(tap_github.logger, "warning") as warning:
            tap_github.authed_get(
                "repo_info", "https://api.github.com/repos/example/repo"
            )
        warning.assert_called_once()
        message, *args = warning.call_args.args
        log = message % tuple(args)
        self.assertIn("retry 1/4 in 60 seconds", log)
        self.assertNotIn("invalid-sensitive-value", log)
        self.assertNotIn("secret", log)
