"""Loading the committed config files, universe resolution and config hashing."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml
from hypothesis import given, settings
from hypothesis import strategies as st
from pydantic import ValidationError

from arjuna.config import (
    ConfigError,
    config_hash,
    load_environment,
    load_strategy,
    load_universe,
)
from arjuna.config.loader import find_configs_dir
from arjuna.config.schema import EnvName, StrategyConfig

# ------------------------------------------------------------ committed files


def test_default_strategy_loads(strategy_path: Path) -> None:
    cfg = load_strategy(strategy_path)
    assert cfg.strategy == "trend_following"
    assert cfg.universe.name == "us_etfs"
    assert "SPY" in cfg.universe.symbols
    assert cfg.constraints.allow_short is False


@pytest.mark.parametrize("name", ["us_etfs", "ucits_etfs"])
def test_universes_load(configs_dir: Path, name: str) -> None:
    uni = load_universe(configs_dir / "universes" / f"{name}.yaml")
    assert uni.name == name
    assert len(uni.symbols) >= 10


@pytest.mark.parametrize("env", list(EnvName))
def test_environments_load(configs_dir: Path, env: EnvName) -> None:
    cfg = load_environment(configs_dir / "environments" / f"{env.value}.yaml")
    assert cfg.env is env


def test_committed_live_config_is_disabled(configs_dir: Path) -> None:
    """Safety regression test: the committed live.yaml must never enable live trading."""
    cfg = load_environment(configs_dir / "environments" / "live.yaml")
    assert cfg.live.enabled is False


def test_us_universe_matches_plan(configs_dir: Path) -> None:
    uni = load_universe(configs_dir / "universes" / "us_etfs.yaml")
    expected = {"SPY", "QQQ", "IWM", "EFA", "EEM", "IEF", "TLT", "TIP", "GLD", "DBC", "UUP", "VNQ"}
    assert set(uni.symbols) == expected


# ------------------------------------------------------------ loader errors


def test_missing_file(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="cannot read"):
        load_universe(tmp_path / "nope.yaml")


def test_non_mapping_yaml(tmp_path: Path) -> None:
    p = tmp_path / "list.yaml"
    p.write_text("- a\n- b\n")
    with pytest.raises(ConfigError, match="mapping"):
        load_universe(p)


def test_invalid_yaml(tmp_path: Path) -> None:
    p = tmp_path / "bad.yaml"
    p.write_text("a: [unclosed\n")
    with pytest.raises(ConfigError, match="invalid YAML"):
        load_universe(p)


def test_strategy_outside_configs_dir_needs_explicit_dir(
    tmp_path: Path, strategy_path: Path, configs_dir: Path
) -> None:
    copy = tmp_path / "s.yaml"
    copy.write_text(strategy_path.read_text())
    with pytest.raises(ConfigError, match="configs"):
        find_configs_dir(copy)
    assert load_strategy(copy, configs_dir=configs_dir).universe.name == "us_etfs"


def test_inline_universe(tmp_path: Path, configs_dir: Path, strategy_path: Path) -> None:
    raw = yaml.safe_load(strategy_path.read_text())
    raw["universe"] = yaml.safe_load((configs_dir / "universes" / "us_etfs.yaml").read_text())
    p = tmp_path / "inline.yaml"
    p.write_text(yaml.safe_dump(raw))
    assert load_strategy(p) == load_strategy(strategy_path)


def test_validation_error_surfaces(tmp_path: Path, configs_dir: Path) -> None:
    p = tmp_path / "bad.yaml"
    p.write_text("name: x\nstrategy: y\nuniverse: us_etfs\nbacktest: {start: 2010-01-01}\nfoo: 1\n")
    with pytest.raises(ValidationError, match="foo"):
        load_strategy(p, configs_dir=configs_dir)


# ------------------------------------------------------------ hashing


def _raw(strategy_path: Path, configs_dir: Path) -> dict[str, Any]:
    raw: dict[str, Any] = yaml.safe_load(strategy_path.read_text())
    raw["universe"] = yaml.safe_load((configs_dir / "universes" / "us_etfs.yaml").read_text())
    return raw


def test_hash_is_hex_sha256_and_deterministic(strategy_path: Path) -> None:
    h1 = config_hash(load_strategy(strategy_path))
    h2 = config_hash(load_strategy(strategy_path))
    assert h1 == h2
    assert len(h1) == 64
    int(h1, 16)


def test_hash_changes_when_a_parameter_changes(strategy_path: Path, configs_dir: Path) -> None:
    raw = _raw(strategy_path, configs_dir)
    base = config_hash(StrategyConfig.model_validate(raw))
    raw["sizing"] = {**raw["sizing"], "target_vol": 0.12}
    assert config_hash(StrategyConfig.model_validate(raw)) != base


def test_hash_changes_when_universe_changes(strategy_path: Path, configs_dir: Path) -> None:
    raw = _raw(strategy_path, configs_dir)
    base = config_hash(StrategyConfig.model_validate(raw))
    raw["universe"]["assets"] = raw["universe"]["assets"][:-1]
    assert config_hash(StrategyConfig.model_validate(raw)) != base


def test_omitted_default_hashes_like_explicit_default(
    strategy_path: Path, configs_dir: Path
) -> None:
    raw = _raw(strategy_path, configs_dir)
    explicit = config_hash(StrategyConfig.model_validate(raw))
    # These sections all equal the schema defaults in the committed file.
    for section in ("signal", "vol", "sizing", "constraints", "rebalance"):
        del raw[section]
    assert config_hash(StrategyConfig.model_validate(raw)) == explicit


@settings(max_examples=50)
@given(st.randoms(use_true_random=False))
def test_hash_ignores_yaml_key_order(rnd: Any) -> None:
    from tests.conftest import CONFIGS

    raw = _raw(CONFIGS / "strategies" / "trend_multi_asset.yaml", CONFIGS)
    expected = config_hash(StrategyConfig.model_validate(raw))

    def shuffle(obj: Any) -> Any:
        if isinstance(obj, dict):
            items = list(obj.items())
            rnd.shuffle(items)
            return {k: shuffle(v) for k, v in items}
        if isinstance(obj, list):
            return [shuffle(v) for v in obj]  # list order is meaningful; keep it
        return obj

    assert config_hash(StrategyConfig.model_validate(shuffle(raw))) == expected
