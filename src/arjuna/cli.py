"""Arjuna command-line interface.

Phase 0 only has ``validate``. ``backtest``, ``sweep``, ``walkforward``, ``run`` and
``status`` arrive in later phases (see docs/PLAN.md).
"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer
from pydantic import ValidationError

from arjuna import __version__
from arjuna.config import ConfigError, config_hash, load_strategy

app = typer.Typer(no_args_is_help=True, add_completion=False, help="Arjuna trading system.")


@app.callback()
def main() -> None:
    """Arjuna: multi-asset trend following with volatility targeting."""


@app.command()
def version() -> None:
    """Print the installed Arjuna version."""
    typer.echo(__version__)


@app.command()
def validate(
    path: Annotated[
        Path, typer.Argument(help="Strategy config YAML.", exists=True, dir_okay=False)
    ],
) -> None:
    """Load and validate a strategy config, then print its config hash."""
    try:
        cfg = load_strategy(path)
    except (ConfigError, ValidationError) as exc:
        typer.echo(f"INVALID: {path}\n{exc}", err=True)
        raise typer.Exit(code=1) from exc
    typer.echo(f"OK       {cfg.name} ({cfg.strategy})")
    typer.echo(f"universe {cfg.universe.name}: {', '.join(cfg.universe.symbols)}")
    typer.echo(f"hash     {config_hash(cfg)}")


if __name__ == "__main__":
    app()
