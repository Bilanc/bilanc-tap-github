import requests
from typing import Dict, Any

def refresh_nango_token(
    config: Dict[str, Any],
    provider_config_key: str = "github-app-oauth",
) -> Dict[str, Any]:
    """
    Get a Nango connection by its ID with force refresh.
    This is to ensure an always up to date access token is used.

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
        requests.RequestException: If the API request fails
    """
    if not config.get("nango_secret_key"):
        raise ValueError("nango_secret_key not configured")

    if not config.get("nango_connection_id"):
        raise ValueError("nango_connection_id not configured")

    url = (
        f"https://api.nango.dev/connection/{config.get('nango_connection_id')}"
        f"?provider_config_key={provider_config_key}&force_refresh=true"
    )

    response = requests.get(
        url,
        headers={
            "Authorization": f"Bearer {config.get('nango_secret_key')}",
            "Content-Type": "application/json",
        },
    )

    response.raise_for_status()

    credentials = response.json().get("credentials", {})

    # OAuth2 connections (github-app-oauth) return the token in `access_token`
    # with an `expires_at`. API key connections (github-pat) return the token in
    # `apiKey` and have no expiry.
    config["access_token"] = credentials.get("access_token") or credentials.get(
        "apiKey"
    )

    expires_at: str = credentials.get("expires_at")

    return config, expires_at