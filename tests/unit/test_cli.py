from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

from arjuna import __version__
from arjuna.cli import app
from arjuna.config import config_hash, load_strategy

runner = CliRunner()


def test_version() -> None:
    result = runner.invoke(app, ["version"])
    assert result.exit_code == 0
    assert __version__ in result.output


def test_validate_ok(strategy_path: Path) -> None:
    result = runner.invoke(app, ["validate", str(strategy_path)])
    assert result.exit_code == 0, result.output
    assert config_hash(load_strategy(strategy_path)) in result.output


def test_validate_invalid(tmp_path: Path) -> None:
    configs = tmp_path / "configs" / "strategies"
    configs.mkdir(parents=True)
    bad = configs / "bad.yaml"
    bad.write_text("name: x\n")
    result = runner.invoke(app, ["validate", str(bad)])
    assert result.exit_code == 1
    assert "INVALID" in result.output


# ------------------------------------------------------------------ data commands


def test_data_status_reports_cached_symbols(strategy_path: Path, tmp_path: Path) -> None:
    import datetime as dt

    from arjuna.data.cache import BarCache
    from tests.unit.bars_helpers import CAL, make_bars

    cache = BarCache(tmp_path, "tiingo", CAL)
    bars = make_bars(dt.date(2024, 1, 2), dt.date(2024, 3, 28))
    cache._write("SPY", bars, requested_start=dt.date(2024, 1, 2))

    result = runner.invoke(
        app, ["data", "status", str(strategy_path), "--cache-dir", str(tmp_path)]
    )
    assert "SPY" in result.output
    assert str(len(bars)) in result.output
    assert result.exit_code == 1  # the other 11 symbols have no data yet
    assert "no usable data" in result.output


def test_data_update_without_key_fails_cleanly(
    strategy_path: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("TIINGO_API_KEY", raising=False)
    result = runner.invoke(
        app, ["data", "update", str(strategy_path), "--cache-dir", str(tmp_path)]
    )
    assert result.exit_code == 1
    assert "TIINGO_API_KEY" in result.output
