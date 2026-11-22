"""Alpaca paper integration tests live here (Phase 4). Skipped unless `pytest -m paper`."""

from __future__ import annotations

import pytest


@pytest.mark.paper
def test_paper_marker_is_wired() -> None:
    pytest.skip("no Alpaca paper tests until Phase 4")
