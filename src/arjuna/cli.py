"""Arjuna command-line interface.

So far: ``validate``, ``version`` and ``data update|status``. ``backtest``, ``sweep``,
``walkforward``, ``run`` and ``status`` arrive in later phases (see docs/PLAN.md).
"""

from __future__ import annotations

import datetime as dt
from pathlib import Path
from typing import Annotated

import typer
from pydantic import ValidationError

from arjuna import __version__
from arjuna.config import ConfigError, StrategyConfig, config_hash, load_strategy
from arjuna.data.cache import BarCache
from arjuna.data.calendar import TradingCalendar
from arjuna.data.provider import DataError
from arjuna.data.tiingo import TiingoProvider
from arjuna.logs import configure_logging

app = typer.Typer(no_args_is_help=True, add_completion=False, help="Arjuna trading system.")
data_app = typer.Typer(no_args_is_help=True, help="Download and inspect cached market data.")
app.add_typer(data_app, name="data")

DEFAULT_CACHE_DIR = Path("data/cache")
DEFAULT_HISTORY_START = dt.datetime(2000, 1, 1)

ConfigArg = Annotated[
    Path, typer.Argument(help="Strategy config YAML.", exists=True, dir_okay=False)
]
CacheDirOpt = Annotated[Path, typer.Option(help="Root directory of the Parquet cache.")]


def _load_or_exit(path: Path) -> StrategyConfig:
    try:
        return load_strategy(path)
    except (ConfigError, ValidationError) as exc:
        typer.echo(f"INVALID: {path}\n{exc}", err=True)
        raise typer.Exit(code=1) from exc


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
    cfg = _load_or_exit(path)
    typer.echo(f"OK       {cfg.name} ({cfg.strategy})")
    typer.echo(f"universe {cfg.universe.name}: {', '.join(cfg.universe.symbols)}")
    typer.echo(f"hash     {config_hash(cfg)}")


@data_app.command("update")
def data_update(
    config: ConfigArg,
    start: Annotated[
        dt.datetime, typer.Option(formats=["%Y-%m-%d"], help="First date for a fresh download.")
    ] = DEFAULT_HISTORY_START,
    cache_dir: CacheDirOpt = DEFAULT_CACHE_DIR,
    refresh: Annotated[bool, typer.Option(help="Re-download everything from --start.")] = False,
) -> None:
    """Download Tiingo daily bars for the config's universe into the Parquet cache.

    Fetches up to the last *completed* session before today, so a partial intraday bar is
    never cached. Needs TIINGO_API_KEY (run with `uv run --env-file .env ...`).
    """
    configure_logging()
    cfg = _load_or_exit(config)
    calendar = TradingCalendar()
    try:
        provider = TiingoProvider.from_env()
    except DataError as exc:
        typer.echo(f"ERROR: {exc}", err=True)
        raise typer.Exit(code=1) from exc
    cache = BarCache(cache_dir, provider.name, calendar)
    end = calendar.previous_session(dt.date.today())

    failed: list[str] = []
    with provider:
        for symbol in cfg.universe.symbols:
            try:
                res = cache.update(provider, symbol, start.date(), end, refresh=refresh)
            except DataError as exc:
                typer.echo(f"{symbol:<6} FAILED  {exc}", err=True)
                failed.append(symbol)
                continue
            revised = f"  ({res.rows_revised} revised)" if res.rows_revised else ""
            typer.echo(f"{symbol:<6} +{res.rows_added:<5} {res.first} .. {res.last}{revised}")
    if failed:
        typer.echo(f"{len(failed)} symbol(s) failed: {', '.join(failed)}", err=True)
        raise typer.Exit(code=1)


@data_app.command("status")
def data_status(
    config: ConfigArg,
    cache_dir: CacheDirOpt = DEFAULT_CACHE_DIR,
    source: Annotated[str, typer.Option(help="Cache source sub-directory.")] = "tiingo",
) -> None:
    """Show cached history per symbol. Exits 1 if any symbol has no cached data."""
    cfg = _load_or_exit(config)
    cache = BarCache(cache_dir, source, TradingCalendar())
    typer.echo(f"{'symbol':<7}{'rows':>6}  {'first':<11} {'last':<11} gaps")
    empty: list[str] = []
    for symbol in cfg.universe.symbols:
        try:
            st = cache.status(symbol)
        except DataError as exc:
            typer.echo(f"{symbol:<7} CORRUPT  {exc}", err=True)
            empty.append(symbol)
            continue
        if st.rows == 0:
            empty.append(symbol)
        gaps = len(st.missing_sessions)
        gap_note = f"{gaps} (first {st.missing_sessions[0]})" if gaps else "0"
        typer.echo(f"{symbol:<7}{st.rows:>6}  {st.first!s:<11} {st.last!s:<11} {gap_note}")
    if empty:
        typer.echo(f"no usable data for: {', '.join(empty)}", err=True)
        raise typer.Exit(code=1)


if __name__ == "__main__":
    app()
