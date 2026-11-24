"""Total returns from raw bars plus dividend and split events.

For session t with raw closes C, dividend per share D_t (ex-date t) and split factor
K_t (2.0 for a 2-for-1 split effective on t):

    r_t = K_t * (C_t + D_t) / C_{t-1} - 1

One share held over the close of t-1 becomes K_t shares on t, each worth C_t plus a D_t
dividend. With no events (K=1, D=0) this is the plain price return C_t / C_{t-1} - 1.
See docs/concepts/total-returns.md.
"""

from __future__ import annotations

import numpy as np
import pandas as pd


def total_returns(bars: pd.DataFrame) -> pd.Series:
    """Simple daily close-to-close total returns. The first row is NaN."""
    close = bars["close"]
    r = bars["split_factor"] * (close + bars["div_cash"]) / close.shift(1) - 1.0
    r.name = "total_return"
    return r.astype(np.float64)


def total_return_index(bars: pd.DataFrame, base: float = 1.0) -> pd.Series:
    """Cumulative total-return index starting at ``base`` on the first row."""
    # the value of $ base invested on the first day
    growth = (1.0 + total_returns(bars).fillna(0.0)).cumprod() * base
    growth.name = "total_return_index"
    return growth


def max_return_mismatch(bars: pd.DataFrame, adj_close: pd.Series) -> float:
    """Largest absolute gap between our total returns and a vendor's adjusted-close returns.

    Used as a data-quality check at download time: if our formula and the vendor's
    adjustment disagree, either the events or our convention are wrong.
    """
    ours = total_returns(bars)
    theirs = adj_close.pct_change()
    diff = (ours - theirs).abs().dropna()
    return float(diff.max()) if len(diff) else 0.0
