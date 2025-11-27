"""
Shared helpers for source adapters.
"""

from __future__ import annotations

import json
from typing import Any, Dict, Iterable, Mapping, Optional
from time import sleep

import requests

MAX_RETRIES = 3
RETRY_DELAY = 2

# Global cache manager instance (set by collector)
_cache_manager: Optional[Any] = None


def set_cache_manager(cache_manager: Any) -> None:
    """Set the global cache manager for API requests."""
    global _cache_manager
    _cache_manager = cache_manager


def make_api_request(
    session: requests.Session,
    url: str,
    *,
    auth: requests.auth.AuthBase | tuple[str, str] | None = None,
    remove_prefix: str | None = None,
    timeout: int = 30,
    params: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any] | list[Any] | None:
    """
    Simple retry-enabled GET helper returning JSON with optional caching.
    """
    # Check cache first
    if _cache_manager:
        cached = _cache_manager.get_api_response(url, method="GET", params=params)
        if cached is not None:
            return cached

    # Make request
    for attempt in range(MAX_RETRIES):
        try:
            resp = session.get(url, auth=auth, timeout=timeout, params=params)
            resp.raise_for_status()
            text = resp.text
            if remove_prefix and text.startswith(remove_prefix):
                text = text[len(remove_prefix) :]
            result = json.loads(text)

            # Cache successful response
            if _cache_manager:
                _cache_manager.set_api_response(url, result, method="GET", params=params)

            return result
        except requests.exceptions.HTTPError as exc:
            if exc.response is not None and exc.response.status_code in {401, 404}:
                raise
        except (requests.exceptions.RequestException, json.JSONDecodeError):
            pass

        if attempt < MAX_RETRIES - 1:
            sleep(RETRY_DELAY)
    return None


def safe_get(data: Mapping[str, Any] | None, *keys: str, default: Any = "") -> Any:
    current: Any = data
    for key in keys:
        if isinstance(current, Mapping):
            current = current.get(key)
        else:
            return default
    return current if current is not None else default

