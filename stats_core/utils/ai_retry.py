from __future__ import annotations

import logging
import time
from typing import Callable, Iterable, TypeVar

import requests

T = TypeVar("T")


def retry_ai_call(
    fn: Callable[[], T],
    *,
    retries: int = 3,
    backoff_seconds: Iterable[float] = (1.0, 2.0, 3.0),
    logger: logging.Logger | None = None,
    retry_exceptions: tuple[type[BaseException], ...] | None = None,
) -> T:
    if retries < 1:
        return fn()

    if logger is None:
        logger = logging.getLogger(__name__)

    if retry_exceptions is None:
        retry_exceptions = (
            requests.Timeout,
            requests.exceptions.ReadTimeout,
            requests.exceptions.ConnectTimeout,
        )

    delays = list(backoff_seconds)
    if not delays:
        delays = [0.0] * retries

    for attempt in range(1, retries + 1):
        try:
            return fn()
        except retry_exceptions as exc:
            if attempt >= retries:
                raise
            delay = delays[min(attempt - 1, len(delays) - 1)]
            # Keep retry noise out of user-facing progress/log stream by default.
            logger.debug(
                "AI request retryable error (attempt %s/%s): %s. Retrying in %ss.",
                attempt,
                retries,
                exc,
                delay,
            )
            if delay > 0:
                time.sleep(delay)

    return fn()
