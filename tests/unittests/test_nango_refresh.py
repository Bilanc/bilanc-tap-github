import json
import unittest
from datetime import datetime, timedelta
from unittest import mock

import requests

from tap_github import nango


def response(status, body=None, reason=None):
    result = requests.Response()
    result.status_code = status
    result.reason = reason
    if body is not None:
        result._content = json.dumps(body).encode()
    else:
        result._content = b""
    return result


def expires_in(**kwargs):
    return (datetime.utcnow() + timedelta(**kwargs)).strftime(
        nango.NANGO_EXPIRES_AT_FORMAT
    )


def ok_response(token="new-token", expires_at=None):
    return response(
        200,
        {
            "credentials": {
                "access_token": token,
                "expires_at": expires_at or expires_in(hours=7),
            }
        },
    )


def refresh_error(code="refresh_token_external_error", message="GitHub rejected it"):
    return response(400, {"error": {"code": code, "message": message}})


def config():
    return {"nango_connection_id": "conn-1", "nango_secret_key": "secret"}


@mock.patch("time.sleep", return_value=None)
@mock.patch("tap_github.nango.requests.get")
class TestRefreshNangoToken(unittest.TestCase):
    def urls(self, get):
        return [call.kwargs.get("url") or call.args[0] for call in get.call_args_list]

    def test_success_uses_force_refresh(self, get, _sleep):
        get.return_value = ok_response()

        cfg, expires_at = nango.refresh_nango_token(config())

        self.assertEqual(cfg["access_token"], "new-token")
        self.assertEqual(expires_at, get.return_value.json()["credentials"]["expires_at"])
        self.assertEqual(get.call_count, 1)
        self.assertIn("force_refresh=true", self.urls(get)[0])
        self.assertIn("provider_config_key=github-app-oauth", self.urls(get)[0])
        self.assertEqual(get.call_args.kwargs["timeout"], nango.NANGO_REQUEST_TIMEOUT)
        _sleep.assert_not_called()

    def test_400_on_force_refresh_retries_once_without_force_refresh(self, get, _sleep):
        get.side_effect = [refresh_error(), ok_response(token="held-token")]

        cfg, _ = nango.refresh_nango_token(config())

        self.assertEqual(cfg["access_token"], "held-token")
        urls = self.urls(get)
        self.assertEqual(len(urls), 2)
        self.assertIn("force_refresh=true", urls[0])
        self.assertNotIn("force_refresh", urls[1])
        _sleep.assert_called_once_with(nango.NANGO_FORCE_REFRESH_RETRY_DELAY)

    def test_400_fallback_token_expiring_within_margin_is_rejected(self, get, _sleep):
        get.side_effect = [
            refresh_error(),
            ok_response(token="held-token", expires_at=expires_in(minutes=10)),
        ]

        with self.assertRaises(nango.NangoRefreshError) as ctx:
            nango.refresh_nango_token(config())

        self.assertEqual(get.call_count, 2)
        self.assertIn("refresh_token_external_error: GitHub rejected it", str(ctx.exception))
        self.assertIn("too soon to use", str(ctx.exception))

    def test_400_fallback_api_key_without_expiry_is_accepted(self, get, _sleep):
        get.side_effect = [
            refresh_error(),
            response(200, {"credentials": {"apiKey": "ghp_x"}}),
        ]

        cfg, expires_at = nango.refresh_nango_token(config(), "github-pat")

        self.assertEqual(cfg["access_token"], "ghp_x")
        self.assertIsNone(expires_at)

    def test_400_twice_raises_with_nango_error_details(self, get, _sleep):
        get.side_effect = [
            refresh_error(),
            refresh_error(code="invalid_credentials", message="token revoked"),
        ]

        with self.assertRaises(nango.NangoRefreshError) as ctx:
            nango.refresh_nango_token(config())

        self.assertEqual(get.call_count, 2)
        self.assertEqual(ctx.exception.status_code, 400)
        self.assertIn("invalid_credentials: token revoked", str(ctx.exception))
        self.assertIn("conn-1", str(ctx.exception))

    def test_401_is_not_retried(self, get, _sleep):
        get.return_value = response(
            401, {"error": {"code": "invalid_secret_key", "message": "bad key"}}
        )

        with self.assertRaises(nango.NangoRefreshError) as ctx:
            nango.refresh_nango_token(config())

        self.assertEqual(get.call_count, 1)
        self.assertIn("401", str(ctx.exception))
        self.assertIn("invalid_secret_key: bad key", str(ctx.exception))
        _sleep.assert_not_called()

    def test_404_is_not_retried(self, get, _sleep):
        get.return_value = response(404, {"error": {"code": "unknown_connection"}})

        with self.assertRaises(nango.NangoRefreshError):
            nango.refresh_nango_token(config())

        self.assertEqual(get.call_count, 1)

    def test_5xx_is_retried_then_succeeds(self, get, _sleep):
        get.side_effect = [
            response(503, reason="Service Temporarily Unavailable"),
            response(504, reason="Gateway Time-out"),
            ok_response(),
        ]

        cfg, _ = nango.refresh_nango_token(config())

        self.assertEqual(cfg["access_token"], "new-token")
        self.assertEqual(get.call_count, 3)
        self.assertTrue(all("force_refresh=true" in url for url in self.urls(get)))

    def test_5xx_gives_up_after_max_tries(self, get, _sleep):
        get.return_value = response(503, reason="Service Temporarily Unavailable")

        with self.assertRaises(nango.NangoServerError) as ctx:
            nango.refresh_nango_token(config())

        self.assertEqual(get.call_count, nango.NANGO_MAX_TRIES)
        self.assertIn("503", str(ctx.exception))
        self.assertIn("Service Temporarily Unavailable", str(ctx.exception))

    def test_timeout_connection_and_chunked_encoding_errors_are_retried(
        self, get, _sleep
    ):
        get.side_effect = [
            requests.Timeout("timed out"),
            requests.ConnectionError("reset"),
            requests.exceptions.ChunkedEncodingError("Connection broken"),
            ok_response(),
        ]

        cfg, _ = nango.refresh_nango_token(config())

        self.assertEqual(cfg["access_token"], "new-token")
        self.assertEqual(get.call_count, 4)

    def test_api_key_connection_has_no_expiry(self, get, _sleep):
        get.return_value = response(200, {"credentials": {"apiKey": "ghp_x"}})

        cfg, expires_at = nango.refresh_nango_token(config(), "github-pat")

        self.assertEqual(cfg["access_token"], "ghp_x")
        self.assertIsNone(expires_at)
        self.assertIn("provider_config_key=github-pat", self.urls(get)[0])

    def test_missing_config_raises_before_any_request(self, get, _sleep):
        with self.assertRaises(ValueError):
            nango.refresh_nango_token({"nango_connection_id": "conn-1"})
        with self.assertRaises(ValueError):
            nango.refresh_nango_token({"nango_secret_key": "secret"})
        get.assert_not_called()


class TestOutlivesMargin(unittest.TestCase):
    def test_margin_matches_tap_early_refresh(self):
        self.assertEqual(nango.NANGO_EXPIRY_MARGIN, timedelta(minutes=20))

    def test_boundaries(self):
        self.assertTrue(nango._outlives_margin(None))
        self.assertTrue(nango._outlives_margin(expires_in(minutes=21)))
        self.assertFalse(nango._outlives_margin(expires_in(minutes=19)))
        self.assertFalse(nango._outlives_margin(expires_in(minutes=-5)))
        self.assertFalse(nango._outlives_margin("not-a-date"))


class TestNangoErrorDetails(unittest.TestCase):
    def test_prefers_code_and_message(self):
        self.assertEqual(
            nango.nango_error_details(refresh_error()),
            "refresh_token_external_error: GitHub rejected it",
        )

    def test_legacy_type_field(self):
        resp = response(400, {"error": {"type": "unknown_connection", "message": "nope"}})
        self.assertEqual(nango.nango_error_details(resp), "unknown_connection: nope")

    def test_string_error(self):
        self.assertEqual(
            nango.nango_error_details(response(400, {"error": "Bad Request"})),
            "Bad Request",
        )

    def test_non_json_body_falls_back_to_reason_without_leaking_body(self):
        resp = requests.Response()
        resp.status_code = 503
        resp.reason = "Service Temporarily Unavailable"
        resp._content = b"<html><body>nginx</body></html>"
        self.assertEqual(
            nango.nango_error_details(resp), "Service Temporarily Unavailable"
        )

    def test_connection_payload_without_error_is_not_echoed(self):
        resp = response(400, {"end_user": {"email": "someone@example.com"}}, reason="Bad Request")
        self.assertEqual(nango.nango_error_details(resp), "Bad Request")
