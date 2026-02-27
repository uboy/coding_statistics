import pytest

import stats_core.cli as cli
from stats_core.cli import parse_key_value_pairs


def test_parse_key_value_pairs() -> None:
    result = parse_key_value_pairs(["foo=1", "bar=baz"])
    assert result == {"foo": "1", "bar": "baz"}


def test_parse_key_value_pairs_invalid() -> None:
    with pytest.raises(ValueError):
        parse_key_value_pairs(["foo"])


def test_main_handles_keyboard_interrupt(monkeypatch, capsys) -> None:
    def _raise_interrupt(_args):
        raise KeyboardInterrupt()

    monkeypatch.setattr(cli, "cmd_run", _raise_interrupt)
    with pytest.raises(SystemExit) as exc:
        cli.main(["run", "--report", "jira_weekly"])
    assert exc.value.code == 130
    assert "Interrupted by user (Ctrl+C)." in capsys.readouterr().err

