"""Load YAML config files into validated Pydantic models, and hash them.

Strategy files name their universe (``universe: us_etfs``); the loader resolves
that to ``<configs_dir>/universes/us_etfs.yaml``. An inline mapping also works.

The config hash is taken over the *validated* model, not the raw YAML, so:

* key order, comments and whitespace in the YAML don't change the hash;
* omitting a key and writing out its default give the same hash;
* changing a default in ``schema.py`` *does* change the hash of every config that
  relied on it, which is what the trial ledger needs.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel

from arjuna.config.schema import EnvironmentConfig, StrategyConfig, UniverseConfig


class ConfigError(Exception):
    """A config file is missing, unreadable, or not a YAML mapping."""


def read_yaml(path: Path) -> dict[str, Any]:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ConfigError(f"cannot read config {path}: {exc}") from exc
    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise ConfigError(f"invalid YAML in {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise ConfigError(f"{path} must contain a YAML mapping at the top level")
    return data


def find_configs_dir(path: Path) -> Path:
    """Return the nearest ancestor of ``path`` called ``configs``."""
    for parent in path.resolve().parents:
        if parent.name == "configs":
            return parent
    raise ConfigError(f"{path} is not inside a 'configs' directory; pass configs_dir explicitly")


def load_universe(path: Path) -> UniverseConfig:
    return UniverseConfig.model_validate(read_yaml(path))


def load_strategy(path: Path, configs_dir: Path | None = None) -> StrategyConfig:
    raw = read_yaml(path)
    universe = raw.get("universe")
    if isinstance(universe, str):
        base = configs_dir if configs_dir is not None else find_configs_dir(path)
        raw["universe"] = read_yaml(base / "universes" / f"{universe}.yaml")
    return StrategyConfig.model_validate(raw)


def load_environment(path: Path) -> EnvironmentConfig:
    return EnvironmentConfig.model_validate(read_yaml(path))


def config_hash(model: BaseModel) -> str:
    """SHA-256 of the model's canonical JSON form (sorted keys, no whitespace)."""
    canonical = json.dumps(
        model.model_dump(mode="json"), sort_keys=True, separators=(",", ":"), ensure_ascii=True
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
