# Learning log

Avi's running notes and answers to the Socratic questions asked while building Arjuna.
Newest entries at the top.

---

## 2026-11-22: Phase 1 warm-up (trading calendar, dividend adjustment)

**Q1. Why isn't a Mon–Fri calendar (`pd.bdate_range`) good enough for "last 63 trading days"
and "last trading day of the week"?**

*Avi:* Counting 63 Mon–Fri days could give only 62 real trading days if one was a holiday,
and the backtest would see the same bar for the holiday and the day before.

*Feedback:* Right on both counts. The second point is the dangerous one. Reindexing onto
Mon–Fri and forward-filling gives the holiday a copy of the previous bar, i.e. a fake
**0% return day**. That biases vol estimates down (extra zeros) and makes EWMA decay count
days when nothing traded. It also breaks "last trading day of the week": in a Good Friday
week, the Mon–Fri calendar says rebalance on Friday, a day with no data, so the rebalance is
silently skipped or mislabelled. The backtest won't notice. Nothing crashes, the numbers are
just slightly wrong. Hence `data/calendar.py` built on the real NYSE calendar.

**Q2. Are vendor "adjusted" prices (past prices rewritten using later dividends) look-ahead bias?**

*Avi:* That sounds like look-ahead bias.

*Feedback:* A good instinct, but mostly **no, for returns**. Ratio back-adjustment multiplies
every price before an ex-dividend date by the same factor (1 − D/P). A return is a ratio of two
prices, so the factor cancels for any window that doesn't straddle the ex-date. A window that
does straddle it gets the *total* return (price change + dividend), which an investor at *t*
really earned and could compute from information known at *t*. So return-based signals and vol
from adjusted data don't leak the future.

Where it **does** go wrong:
- **Price levels.** Adjusted past prices are not prices anyone traded at. Share counts, lot
  rounding, min-notional rules or "price > $X" filters on adjusted levels use numbers that
  only exist with hindsight.
- **Stale caches.** Every new dividend rewrites the whole adjusted history, so a cached
  adjusted series silently disagrees with a fresh download.
- **Additive adjustment** (subtracting the dividend instead of scaling) does distort returns.

Design consequence for Phase 1: cache **raw** bars plus corporate actions, derive total returns
for signals/vol ourselves, and use raw prices for anything involving shares or dollars.

## 2026-11-24: Phase 1 cache (overlap re-fetch)

**Q1. In the simulation, why does the update after 28 Jun 2024 request from 14 Jun, not 1 Jul?**

*Avi:* We re-fetch the last 10 trading days counting from and including Fri 28 Jun. Juneteenth
(19 Jun) is a holiday, so counting back lands on 14 Jun.

*Feedback:* Exactly right. The overlap is positional on cached rows
(`existing.index[len - 10]`), so it's in trading days automatically. Its purpose is to replace
rows the vendor corrected after we cached them, e.g. a late dividend.

**Q2. What's the risk of making the overlap much bigger, e.g. 252 days?**

*Avi:* It would be expensive.

*Feedback:* Mostly not, actually. It's still **one request per symbol**; the response is just
252 rows instead of 10. The real costs are elsewhere:
- **Reproducibility.** The wider the window, the more past rows can silently change between runs.
  Re-running a backtest with the *same config hash* could give a different Sharpe than the one
  in the trial ledger, because the data underneath changed. (Lesson for Phase 3: record a data
  snapshot ID or hash with each trial, not just the config hash.)
- **Noise.** More rows compared means more `cached_rows_revised` warnings for trivial vendor
  float tweaks. Warnings that fire all the time get ignored.
- **It's a trade-off, not a fix.** Any window misses corrections older than itself; the backstop
  for those is an occasional `--refresh`.
So the overlap size trades catching late corrections against keeping history stable. 10 days
covers the usual case (dividends posted a day or two late).
