from __future__ import annotations

import requests

from stats_core.utils.ai_retry import retry_ai_call


def test_retry_ai_call_retries_on_timeout():
    calls = {"count": 0}

    def flaky():
        calls["count"] += 1
        if calls["count"] < 3:
            raise requests.Timeout("timeout")
        return "ok"

    result = retry_ai_call(flaky, retries=3, backoff_seconds=(0, 0, 0))
    assert result == "ok"
    assert calls["count"] == 3


def test_retry_ai_call_raises_non_timeout():
    def boom():
        raise ValueError("nope")

    try:
        retry_ai_call(boom, retries=3, backoff_seconds=(0, 0, 0))
        assert False, "expected ValueError"
    except ValueError:
        assert True
