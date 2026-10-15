import time
from datetime import datetime, timedelta
from typing import Any, Dict, Optional, Tuple

import backoff
import requests
import singer

logger = singer.get_logger()

NANGO_API_URL = "https://api.nango.dev"
NANGO_REQUEST_TIMEOUT = 30
NANGO_MAX_TRIES = 5
NANGO_FORCE_REFRESH_RETRY_DELAY = 5
NANGO_EXPIRES_AT_FORMAT = "%Y-%m-%dT%H:%M:%SZ"
# The tap treats a Nango access token as stale this long before `expires_at`
# (Nango itself refreshes within 15 minutes of expiry). A token handed back by
# the no-force fallback must outlive this margin, otherwise every GitHub
# request would re-run the failing forced refresh.
NANGO_EXPIRY_MARGIN = timedelta(minutes=20)


class NangoServerError(Exception):
    """Nango answered with a 5xx; retried by `fetch_nango_connection`."""


class NangoRefreshError(Exception):
    """Nango could not serve credentials for the connection (non-retriable)."""

    def __init__(self, message: str, response: Optional[requests.Response] = None):
        super().__init__(message)
        self.response = response
        self.status_code = response.status_code if response is not None else None


def nango_error_details(response: requests.Response) -> str:
    """Return Nango's `error.code: error.message` from an error body.

    Only the error fields are surfaced so alerts never carry the connection
    payload (end user name/email, credentials).
    """
    try:
        body = response.json()
    except ValueError:
        body = None

    error = body.get("error") if isinstance(body, dict) else None
    if isinstance(error, dict):
        code = error.get("code") or error.get("type")
        message = error.get("message")
        details = ": ".join(str(part) for part in (code, message) if part)
        if details:
            return details
    if isinstance(error, str) and error:
        return error

    return (response.reason or "").strip() or f"HTTP {response.status_code}"


@backoff.on_exception(
    backoff.expo,
    (
        requests.Timeout,
        requests.ConnectionError,
        requests.exceptions.ChunkedEncodingError,
        NangoServerError,
    ),
    max_tries=NANGO_MAX_TRIES,
    factor=2,
)
def fetch_nango_connection(
    config: Dict[str, Any], provider_config_key: str, force_refresh: bool
) -> requests.Response:
    """GET the Nango connection, retrying timeouts, connection errors and 5xx."""
    url = (
        f"{NANGO_API_URL}/connection/{config.get('nango_connection_id')}"
        f"?provider_config_key={provider_config_key}"
    )
    if force_refresh:
        url += "&force_refresh=true"

    response = requests.get(
        url,
        headers={
            "Authorization": f"Bearer {config.get('nango_secret_key')}",
            "Content-Type": "application/json",
        },
        timeout=NANGO_REQUEST_TIMEOUT,
    )

    if response.status_code >= 500:
        raise NangoServerError(
            f"Nango returned {response.status_code} fetching connection "
            f"(force_refresh={force_refresh}): {nango_error_details(response)}"
        )

    return response


def _outlives_margin(expires_at: Optional[str]) -> bool:
    """True if the token is usable for longer than `NANGO_EXPIRY_MARGIN`."""
    if not expires_at:
        return True  # API key connections (github-pat) never expire
    try:
        expiry = datetime.strptime(expires_at, NANGO_EXPIRES_AT_FORMAT)
    except ValueError:
        return False
    return expiry - NANGO_EXPIRY_MARGIN > datetime.utcnow()


def refresh_nango_token(
    config: Dict[str, Any],
    provider_config_key: str = "github-app-oauth",
) -> Tuple[Dict[str, Any], Optional[str]]:
    """
    Get a Nango connection by its ID with force refresh.
    This is to ensure an always up to date access token is used.

    Transient failures are retried: timeouts, connection errors and Nango 5xx
    are backed off and retried; a 400 on the forced refresh (the provider
    rejected this one refresh, e.g. a rotated refresh token raced with another
    refresh) is retried once without `force_refresh`, since Nango still holds
    a valid token; that token is only accepted if it outlives
    `NANGO_EXPIRY_MARGIN`, so the caller does not loop on the failing forced
    refresh for a token that is about to expire. Any other non-2xx (401/403/404, or a 400 on both attempts)
    raises `NangoRefreshError` carrying Nango's error code and message.

    Args:
        config: The tap config (must contain nango_connection_id and nango_secret_key)
        provider_config_key: The Nango integration to use. Defaults to the GitHub
            App OAuth integration ("github-app-oauth"). Self-hosted GitHub
            Enterprise connections use a personal access token ("github-pat").

    Returns:
        Tuple of (updated config with access_token set, expires_at). expires_at is
        None for API key based connections (e.g. github-pat) which do not expire.

    Raises:
        ValueError: If the NANGO_SECRET_KEY is not configured
        NangoRefreshError: If Nango cannot serve credentials for the connection
        NangoServerError, requests.RequestException: If Nango stays unreachable
            after the retries
    """
    if not config.get("nango_secret_key"):
        raise ValueError("nango_secret_key not configured")

    if not config.get("nango_connection_id"):
        raise ValueError("nango_connection_id not configured")

    response = fetch_nango_connection(config, provider_config_key, force_refresh=True)

    forced_refresh_error = None
    if response.status_code == 400:
        forced_refresh_error = nango_error_details(response)
        logger.warning(
            "Nango returned 400 on force_refresh of connection (%s); retrying in "
            "%ss without force_refresh",
            forced_refresh_error,
            NANGO_FORCE_REFRESH_RETRY_DELAY,
        )
        time.sleep(NANGO_FORCE_REFRESH_RETRY_DELAY)
        response = fetch_nango_connection(
            config, provider_config_key, force_refresh=False
        )

    if not response.ok:
        raise NangoRefreshError(
            f"Nango returned {response.status_code} for connection "
            f"{config.get('nango_connection_id')} ({provider_config_key}): "
            f"{nango_error_details(response)}",
            response,
        )

    credentials = response.json().get("credentials", {})

    if forced_refresh_error is not None and not _outlives_margin(
        credentials.get("expires_at")
    ):
        raise NangoRefreshError(
            f"Nango returned 400 on force_refresh for connection "
            f"{config.get('nango_connection_id')} ({provider_config_key}): "
            f"{forced_refresh_error}; the token Nango still holds expires at "
            f"{credentials.get('expires_at')}, too soon to use",
            response,
        )

    # OAuth2 connections (github-app-oauth) return the token in `access_token`
    # with an `expires_at`. API key connections (github-pat) return the token in
    # `apiKey` and have no expiry.
    config["access_token"] = credentials.get("access_token") or credentials.get(
        "apiKey"
    )

    expires_at: str = credentials.get("expires_at")

    return config, expires_at
