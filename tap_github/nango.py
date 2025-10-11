import os
import requests
from typing import Dict, Any

def refresh_nango_token(
    config: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Get a Nango connection by its ID with force refresh.
    This is to ensure an always up to date access token is used.

    Args:
        connection_id: The ID of the connection to retrieve

    Returns:
        Dictionary containing the connection information

    Raises:
        ValueError: If the NANGO_SECRET_KEY is not configured
        requests.RequestException: If the API request fails
    """
    if not config.get("nango_secret_key"):
        raise ValueError("nango_secret_key not configured")
    
    if not config.get("nango_connection_id"):
        raise ValueError("nango_connection_id not configured")

    url = f"https://api.nango.dev/connection/{config.get('nango_connection_id')}?provider_config_key=github-app-oauth&force_refresh=true"

    response = requests.get(
        url,
        headers={
            "Authorization": f"Bearer {config.get('nango_secret_key')}",
            "Content-Type": "application/json",
        },
    )

    response.raise_for_status()

    response = response.json()

    config["access_token"] = response.get("credentials", {}).get("access_token")

    expires_at: str = response.get("credentials", {}).get("expires_at")

    return config, expires_at