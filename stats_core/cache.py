"""
Centralized caching system for API requests and link processing results.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
from datetime import datetime
import atexit
import signal
import sys
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


class CacheManager:
    """
    Manages caching of API responses and processed link results.
    
    Cache structure:
    {
        "api": {
            "cache_key_hash": {
                "url": "...",
                "method": "GET",
                "response": {...},
                "cached_at": "2025-01-01T00:00:00"
            }
        },
        "links": {
            "url": {
                "data": [...],
                "cached_at": "2025-01-01T00:00:00"
            }
        }
    }
    """

    def __init__(
        self,
        cache_file: str = "data/cache/cache.json",
        enabled: bool = True,
        ttl_days: int = 0,
    ):
        """
        Initialize cache manager.

        Args:
            cache_file: Path to JSON cache file
            enabled: Whether caching is enabled
            ttl_days: Time-to-live in days (0 = no expiration)
        """
        self.cache_file = cache_file
        self.enabled = enabled
        self.ttl_days = ttl_days
        self._cache: Dict[str, Any] = {"api": {}, "links": {}}
        self._load()
        self._hooks_registered = False
        self._prev_handlers: Dict[int, Any] = {}
        self._register_exit_hooks()

    def _load(self) -> None:
        """Load cache from file."""
        if not self.enabled:
            logger.info("Cache is disabled")
            return
        if not os.path.exists(self.cache_file):
            logger.info(f"Cache file {self.cache_file} does not exist, starting with empty cache")
            return
        try:
            with open(self.cache_file, "r", encoding="utf-8") as f:
                self._cache = json.load(f)
            # Ensure structure
            if "api" not in self._cache:
                self._cache["api"] = {}
            if "links" not in self._cache:
                self._cache["links"] = {}
            link_count = len(self._cache.get("links", {}))
            api_count = len(self._cache.get("api", {}))
            logger.info(f"Loaded cache from {self.cache_file}: {link_count} links, {api_count} API responses")
        except Exception as e:
            logger.warning(f"Failed to load cache from {self.cache_file}: {e}")
            self._cache = {"api": {}, "links": {}}

    def save(self) -> None:
        """Save cache to file."""
        if not self.enabled:
            logger.debug("Cache is disabled, skipping save")
            return
        try:
            parent = os.path.dirname(self.cache_file)
            if parent:
                os.makedirs(parent, exist_ok=True)
            with open(self.cache_file, "w", encoding="utf-8") as f:
                json.dump(self._cache, f, ensure_ascii=False, indent=2)
            link_count = len(self._cache.get("links", {}))
            api_count = len(self._cache.get("api", {}))
            logger.info(f"Cache saved to {self.cache_file}: {link_count} links, {api_count} API responses")
        except Exception as e:
            logger.error(f"Failed to save cache to {self.cache_file}: {e}")

    # ---- Lifecycle helpers ----
    def _register_exit_hooks(self) -> None:
        """
        Register atexit and signal handlers to persist cache on shutdown
        (normal exit, Ctrl+C, SIGTERM where available).
        """
        if self._hooks_registered:
            return
        self._hooks_registered = True

        # atexit will run on normal interpreter exit (and on KeyboardInterrupt unless force-killed)
        atexit.register(self.save)

        def _make_handler(signum):
            def _handler(signum_, frame):
                logger.info("Signal %s received, saving cache before exit.", signum_)
                try:
                    self.save()
                finally:
                    prev = self._prev_handlers.get(signum_)
                    # Call previous handler if it exists and is callable
                    if callable(prev):
                        prev(signum_, frame)
                    elif prev in (signal.SIG_DFL, None):
                        # Default handling: exit with code 1
                        sys.exit(1)
            return _handler

        for sig in ("SIGINT", "SIGTERM"):
            if hasattr(signal, sig):
                signum = getattr(signal, sig)
                try:
                    prev = signal.getsignal(signum)
                    self._prev_handlers[signum] = prev
                    signal.signal(signum, _make_handler(signum))
                except Exception as e:
                    logger.debug("Unable to register signal handler for %s: %s", sig, e)

    def _make_api_key(self, url: str, method: str = "GET", params: Optional[Dict] = None) -> str:
        """Generate cache key for API request."""
        key_data = f"{method}:{url}"
        if params:
            # Sort params for consistent keys
            sorted_params = json.dumps(params, sort_keys=True)
            key_data += f":{sorted_params}"
        return hashlib.sha256(key_data.encode()).hexdigest()

    def get_api_response(
        self, url: str, method: str = "GET", params: Optional[Dict] = None
    ) -> Optional[Any]:
        """
        Get cached API response.

        Returns:
            Cached response data or None if not found/expired
        """
        if not self.enabled:
            return None
        key = self._make_api_key(url, method, params)
        entry = self._cache["api"].get(key)
        if not entry:
            return None
        if self._is_expired(entry.get("cached_at")):
            del self._cache["api"][key]
            return None
        logger.debug(f"Cache hit for API: {url}")
        return entry.get("response")

    def set_api_response(
        self, url: str, response: Any, method: str = "GET", params: Optional[Dict] = None
    ) -> None:
        """Cache API response."""
        if not self.enabled:
            return
        key = self._make_api_key(url, method, params)
        self._cache["api"][key] = {
            "url": url,
            "method": method,
            "params": params,
            "response": response,
            "cached_at": datetime.utcnow().isoformat(),
        }
        logger.debug(f"Cached API response for: {url}")

    def get_link_result(self, url: str) -> Optional[Any]:
        """
        Get cached result for a processed link.

        Returns:
            Cached data or None if not found/expired
        """
        if not self.enabled:
            logger.debug(f"Cache disabled, not checking cache for: {url}")
            return None
        entry = self._cache["links"].get(url)
        if not entry:
            logger.debug(f"Cache miss for link: {url}")
            return None
        if self._is_expired(entry.get("cached_at")):
            logger.debug(f"Cache entry expired for link: {url}")
            del self._cache["links"][url]
            return None
        logger.info(f"Cache hit for link: {url}")
        return entry.get("data")

    def set_link_result(self, url: str, data: Any) -> None:
        """Cache processed link result."""
        if not self.enabled:
            logger.debug(f"Cache disabled, not caching link: {url}")
            return
        self._cache["links"][url] = {
            "data": data,
            "cached_at": datetime.utcnow().isoformat(),
        }
        logger.debug(f"Cached link result for: {url}")
        logger.info(f"Link cached: {url} (total cached links: {len(self._cache.get('links', {}))})")

    def _is_expired(self, cached_at: Optional[str]) -> bool:
        """Check if cache entry is expired."""
        if not cached_at or self.ttl_days == 0:
            return False
        try:
            cached_dt = datetime.fromisoformat(cached_at)
            age = (datetime.utcnow() - cached_dt).days
            return age > self.ttl_days
        except Exception:
            return True

    def clear(self, section: Optional[str] = None) -> None:
        """
        Clear cache.

        Args:
            section: "api", "links", or None to clear all
        """
        if section == "api":
            self._cache["api"] = {}
        elif section == "links":
            self._cache["links"] = {}
        else:
            self._cache = {"api": {}, "links": {}}
        logger.info(f"Cache cleared: {section or 'all'}")

    def get_stats(self) -> Dict[str, int]:
        """Get cache statistics."""
        return {
            "api_entries": len(self._cache.get("api", {})),
            "link_entries": len(self._cache.get("links", {})),
        }

