from __future__ import annotations

from pathlib import Path

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
