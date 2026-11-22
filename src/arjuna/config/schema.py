"""Pydantic models for every config file Arjuna reads.

Design notes (see docs/decisions/0001-config-schema-and-hashing.md):

* Every model forbids unknown keys. A typo such as ``target_volatility`` must fail
  loudly rather than silently fall back to a default.
* Every model is frozen. Configs are values: they are hashed for the trial ledger,
  so nothing may mutate them after loading.
* Risk limits in environment configs have **no defaults**. Each environment must
  state its limits explicitly in YAML.
"""

from __future__ import annotations

import datetime as dt
from enum import StrEnum
from typing import Annotated, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

# --------------------------------------------------------------------------- base


class StrictModel(BaseModel):
    """Base for all config models: unknown keys are errors, instances are immutable."""

    model_config = ConfigDict(extra="forbid", frozen=True)


Fraction = Annotated[float, Field(gt=0.0, le=1.0)]
"""A number in (0, 1], e.g. an annualised vol or a weight as a fraction of NAV (net asset value)."""


NonNegFloat = Annotated[float, Field(ge=0.0)]
PosFloat = Annotated[float, Field(gt=0.0)]
PosInt = Annotated[int, Field(gt=0)]
Symbol = Annotated[str, Field(pattern=r"^[A-Z0-9.]{1,12}$")]


# ----------------------------------------------------------------------- universe


class AssetClass(StrEnum):
    EQUITY = "equity"
    BOND = "bond"
    COMMODITY = "commodity"
    CURRENCY = "currency"
    REAL_ESTATE = "real_estate"


class AssetCosts(StrictModel):
    """Per-asset trading-cost assumptions used by the backtest."""

    half_spread_bps: NonNegFloat = 1.0
    slippage_bps: NonNegFloat = 1.0
    commission_per_share: NonNegFloat = 0.0


class Asset(StrictModel):
    symbol: Symbol
    name: str
    asset_class: AssetClass
    costs: AssetCosts = AssetCosts()


class UniverseConfig(StrictModel):
    name: str
    currency: Annotated[str, Field(pattern=r"^[A-Z]{3}$")]
    assets: Annotated[tuple[Asset, ...], Field(min_length=1)]

    @model_validator(mode="after")
    def _unique_symbols(self) -> Self:
        symbols = [a.symbol for a in self.assets]
        dupes = sorted({s for s in symbols if symbols.count(s) > 1})
        if dupes:
            raise ValueError(f"duplicate symbols in universe {self.name!r}: {dupes}")
        return self

    @property
    def symbols(self) -> tuple[str, ...]:
        return tuple(a.symbol for a in self.assets)


# ----------------------------------------------------------------------- strategy


class SignalConfig(StrictModel):
    lookbacks: Annotated[tuple[PosInt, ...], Field(min_length=1)] = (21, 63, 126, 252)
    """Lookback windows in trading days. The final signal averages across them."""
    signal_type: Literal["sign", "scaled"] = "sign"

    @model_validator(mode="after")
    def _unique_lookbacks(self) -> Self:
        if len(set(self.lookbacks)) != len(self.lookbacks):
            raise ValueError(f"lookbacks must be unique, got {self.lookbacks}")
        return self


class VolConfig(StrictModel):
    halflife: PosFloat = 60.0
    """EWMA half-life in trading days."""
    min_vol: Fraction = 0.05
    """Floor on annualised vol, so very quiet assets don't get huge positions."""


class SizingConfig(StrictModel):
    target_vol: Fraction = 0.10
    """Annualised portfolio vol target."""
    portfolio_scaling: bool = True
    """Rescale weights so ex-ante portfolio vol (EWMA covariance) equals target_vol."""


class ConstraintsConfig(StrictModel):
    max_weight_per_asset: Fraction = 0.25
    max_gross_leverage: PosFloat = 1.0
    allow_short: bool = False

    @model_validator(mode="after")
    def _weight_within_leverage(self) -> Self:
        if self.max_weight_per_asset > self.max_gross_leverage:
            raise ValueError(
                f"max_weight_per_asset ({self.max_weight_per_asset}) cannot exceed "
                f"max_gross_leverage ({self.max_gross_leverage})"
            )
        return self


class RebalanceConfig(StrictModel):
    frequency: Literal["daily", "weekly", "monthly"] = "weekly"
    band: Annotated[float, Field(ge=0.0, lt=1.0)] = 0.02
    """No-trade band: only trade asset i if |w_target - w_current| > band."""


class BacktestConfig(StrictModel):
    start: dt.date
    end: dt.date | None = None
    """Inclusive end date; ``None`` means "latest available data"."""
    initial_capital: PosFloat = 100_000.0

    @model_validator(mode="after")
    def _start_before_end(self) -> Self:
        if self.end is not None and self.end <= self.start:
            raise ValueError(f"backtest end ({self.end}) must be after start ({self.start})")
        return self


class StrategyConfig(StrictModel):
    name: str
    strategy: str
    """Key into the strategy registry, e.g. ``trend_following``."""
    universe: UniverseConfig
    signal: SignalConfig = SignalConfig()
    vol: VolConfig = VolConfig()
    sizing: SizingConfig = SizingConfig()
    constraints: ConstraintsConfig = ConstraintsConfig()
    rebalance: RebalanceConfig = RebalanceConfig()
    backtest: BacktestConfig


# -------------------------------------------------------------------- environment


class EnvName(StrEnum):
    BACKTEST = "backtest"
    PAPER = "paper"
    LIVE = "live"


class BrokerKind(StrEnum):
    SIM = "sim"
    ALPACA_PAPER = "alpaca_paper"
    ALPACA_LIVE = "alpaca_live"


_ALLOWED_BROKERS: dict[EnvName, frozenset[BrokerKind]] = {
    EnvName.BACKTEST: frozenset({BrokerKind.SIM}),
    EnvName.PAPER: frozenset({BrokerKind.SIM, BrokerKind.ALPACA_PAPER}),
    EnvName.LIVE: frozenset({BrokerKind.ALPACA_LIVE}),
}


class LiveSwitch(StrictModel):
    enabled: bool = False
    """One of three independent gates for real money (with ARJUNA_ENV=live and
    --confirm-live). Never set this to true from code."""


class RiskLimits(StrictModel):
    """Pre-trade risk limits. No defaults on purpose: each environment states its own."""

    max_order_notional: PosFloat
    """Largest single order, in account currency."""
    max_daily_turnover: Fraction
    """Sum of |order notional| per day, as a fraction of NAV."""
    initial_deployment_max_turnover: PosFloat
    """Turnover cap for the one-off initial deployment from cash (ADR 0002). Only applies
    when the operator passes ``--initial-deployment`` *and* the broker holds no positions;
    the scheduled runner never uses it."""
    max_gross_leverage: PosFloat
    """Sum of |weights| after the trade."""
    reconcile_tolerance: Fraction
    """Max |broker weight - expected weight| per asset before the runner halts."""
    allowed_symbols: tuple[Symbol, ...] | None = None
    """Order whitelist. ``None`` means "the strategy's universe"."""

    @model_validator(mode="after")
    def _initial_deployment_bounds(self) -> Self:
        # Building a portfolio from cash trades at most its gross exposure, so a cap above
        # max_gross_leverage is never needed; a cap below the normal one makes no sense.
        if not (
            self.max_daily_turnover
            <= self.initial_deployment_max_turnover
            <= self.max_gross_leverage
        ):
            raise ValueError(
                "initial_deployment_max_turnover must lie between max_daily_turnover "
                f"({self.max_daily_turnover}) and max_gross_leverage "
                f"({self.max_gross_leverage}), got {self.initial_deployment_max_turnover}"
            )
        return self


class EnvironmentConfig(StrictModel):
    env: EnvName
    broker: BrokerKind
    live: LiveSwitch = LiveSwitch()
    risk: RiskLimits

    @model_validator(mode="after")
    def _consistent(self) -> Self:
        if self.broker not in _ALLOWED_BROKERS[self.env]:
            allowed = sorted(b.value for b in _ALLOWED_BROKERS[self.env])
            raise ValueError(
                f"broker {self.broker.value!r} is not allowed in env {self.env.value!r} "
                f"(allowed: {allowed})"
            )
        if self.live.enabled and self.env is not EnvName.LIVE:
            raise ValueError(f"live.enabled must be false outside the live env (env={self.env})")
        return self
