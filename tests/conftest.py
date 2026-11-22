from __future__ import annotations

from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
CONFIGS = REPO_ROOT / "configs"


@pytest.fixture
def configs_dir() -> Path:
    return CONFIGS


@pytest.fixture
def strategy_path() -> Path:
    return CONFIGS / "strategies" / "trend_multi_asset.yaml"
