import pytest

from stats_core.cli import parse_key_value_pairs


def test_parse_key_value_pairs() -> None:
    result = parse_key_value_pairs(["foo=1", "bar=baz"])
    assert result == {"foo": "1", "bar": "baz"}


def test_parse_key_value_pairs_invalid() -> None:
    with pytest.raises(ValueError):
        parse_key_value_pairs(["foo"])

