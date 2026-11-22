"""Validation rules in arjuna.config.schema."""

from __future__ import annotations

from typing import Any

import pytest
from pydantic import ValidationError

from arjuna.config.schema import (
    ConstraintsConfig,
    EnvironmentConfig,
    RebalanceConfig,
    RiskLimits,
    SignalConfig,
    StrategyConfig,
    UniverseConfig,
    VolConfig,
)

UNIVERSE: dict[str, Any] = {
    "name": "tiny",
    "currency": "USD",
    "assets": [
        {"symbol": "SPY", "name": "S&P 500", "asset_class": "equity"},
        {"symbol": "IEF", "name": "7-10y", "asset_class": "bond"},
    ],
}

RISK: dict[str, Any] = {
    "max_order_notional": 1000,
    "max_daily_turnover": 0.5,
    "initial_deployment_max_turnover": 1.0,
    "max_gross_leverage": 1.0,
    "reconcile_tolerance": 0.01,
}


def minimal_strategy(**overrides: Any) -> dict[str, Any]:
    raw: dict[str, Any] = {
        "name": "t",
        "strategy": "trend_following",
        "universe": UNIVERSE,
        "backtest": {"start": "2010-01-01"},
    }
    raw.update(overrides)
    return raw


def test_minimal_strategy_gets_plan_defaults() -> None:
    cfg = StrategyConfig.model_validate(minimal_strategy())
    assert cfg.signal.lookbacks == (21, 63, 126, 252)
    assert cfg.vol.halflife == 60
    assert cfg.rebalance.frequency == "weekly"
    assert cfg.rebalance.band == 0.02
    assert cfg.constraints.allow_short is False
    assert cfg.constraints.max_gross_leverage == 1.0


def test_unknown_key_is_rejected() -> None:
    # A typo must fail loudly, not silently fall back to the default.
    with pytest.raises(ValidationError, match="target_volatility"):
        StrategyConfig.model_validate(minimal_strategy(sizing={"target_volatility": 0.2}))


def test_config_is_frozen() -> None:
    cfg = StrategyConfig.model_validate(minimal_strategy())
    with pytest.raises(ValidationError):
        cfg.sizing.target_vol = 0.5  # type: ignore[misc]


def test_duplicate_symbols_rejected() -> None:
    bad = {**UNIVERSE, "assets": [*UNIVERSE["assets"], UNIVERSE["assets"][0]]}
    with pytest.raises(ValidationError, match="duplicate symbols"):
        UniverseConfig.model_validate(bad)


@pytest.mark.parametrize("symbol", ["spy", "", "WAY_TOO_LONG_TICKER", "SP Y"])
def test_bad_symbols_rejected(symbol: str) -> None:
    bad = {**UNIVERSE, "assets": [{"symbol": symbol, "name": "x", "asset_class": "equity"}]}
    with pytest.raises(ValidationError):
        UniverseConfig.model_validate(bad)


def test_duplicate_lookbacks_rejected() -> None:
    with pytest.raises(ValidationError, match="unique"):
        SignalConfig(lookbacks=(21, 21))


@pytest.mark.parametrize("lookbacks", [(), (0,), (-5, 21)])
def test_invalid_lookbacks_rejected(lookbacks: tuple[int, ...]) -> None:
    with pytest.raises(ValidationError):
        SignalConfig(lookbacks=lookbacks)


@pytest.mark.parametrize("min_vol", [0.0, -0.1, 1.5])
def test_min_vol_must_be_a_fraction(min_vol: float) -> None:
    with pytest.raises(ValidationError):
        VolConfig(min_vol=min_vol)


@pytest.mark.parametrize("band", [-0.01, 1.0])
def test_band_range(band: float) -> None:
    with pytest.raises(ValidationError):
        RebalanceConfig(band=band)


def test_max_weight_cannot_exceed_leverage() -> None:
    with pytest.raises(ValidationError, match="cannot exceed"):
        ConstraintsConfig(max_weight_per_asset=0.6, max_gross_leverage=0.5)


def test_backtest_end_must_follow_start() -> None:
    with pytest.raises(ValidationError, match="must be after"):
        StrategyConfig.model_validate(
            minimal_strategy(backtest={"start": "2020-01-01", "end": "2019-01-01"})
        )


# ---------------------------------------------------------------- environments


def test_risk_limits_have_no_defaults() -> None:
    with pytest.raises(ValidationError):
        EnvironmentConfig.model_validate({"env": "paper", "broker": "alpaca_paper", "risk": {}})


def test_live_switch_defaults_off() -> None:
    cfg = EnvironmentConfig.model_validate({"env": "live", "broker": "alpaca_live", "risk": RISK})
    assert cfg.live.enabled is False


@pytest.mark.parametrize("env", ["backtest", "paper"])
def test_live_enabled_rejected_outside_live_env(env: str) -> None:
    broker = "sim" if env == "backtest" else "alpaca_paper"
    with pytest.raises(ValidationError, match=r"live\.enabled"):
        EnvironmentConfig.model_validate(
            {"env": env, "broker": broker, "live": {"enabled": True}, "risk": RISK}
        )


def test_initial_deployment_cap_is_required() -> None:
    risk = {k: v for k, v in RISK.items() if k != "initial_deployment_max_turnover"}
    with pytest.raises(ValidationError, match="initial_deployment_max_turnover"):
        RiskLimits.model_validate(risk)


@pytest.mark.parametrize("cap", [0.4, 1.5])
def test_initial_deployment_cap_bounds(cap: float) -> None:
    # Must be >= max_daily_turnover (0.5) and <= max_gross_leverage (1.0).
    with pytest.raises(ValidationError, match="must lie between"):
        RiskLimits.model_validate({**RISK, "initial_deployment_max_turnover": cap})


def test_initial_deployment_cap_may_equal_normal_cap() -> None:
    risk = RiskLimits.model_validate({**RISK, "initial_deployment_max_turnover": 0.5})
    assert risk.initial_deployment_max_turnover == risk.max_daily_turnover


@pytest.mark.parametrize(
    ("env", "broker"),
    [
        ("backtest", "alpaca_paper"),
        ("backtest", "alpaca_live"),
        ("paper", "alpaca_live"),
        ("live", "sim"),
        ("live", "alpaca_paper"),
    ],
)
def test_env_broker_mismatch_rejected(env: str, broker: str) -> None:
    with pytest.raises(ValidationError, match="not allowed"):
        EnvironmentConfig.model_validate({"env": env, "broker": broker, "risk": RISK})
