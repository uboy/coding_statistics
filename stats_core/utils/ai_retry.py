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
) -> T:
    if retries < 1:
        return fn()

    if logger is None:
        logger = logging.getLogger(__name__)

    delays = list(backoff_seconds)
    if not delays:
        delays = [0.0] * retries

    for attempt in range(1, retries + 1):
        try:
            return fn()
        except (
            requests.Timeout,
            requests.exceptions.ReadTimeout,
            requests.exceptions.ConnectTimeout,
        ) as exc:
            if attempt >= retries:
                raise
            delay = delays[min(attempt - 1, len(delays) - 1)]
            logger.warning("AI request timeout (attempt %s/%s). Retrying in %ss.", attempt, retries, delay)
            if delay > 0:
                time.sleep(delay)

    return fn()
