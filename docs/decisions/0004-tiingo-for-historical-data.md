# 0004: Tiingo for historical daily data; Alpaca for trading only

- **Status:** accepted (Avi, 2026-11-22). Replaces "Alpaca daily bars" in Phase 1 of PLAN.md.
- **Date:** 2026-11-22

## Context

The backtest starts in 2008 so that it covers the 2008 crisis. Trend following's main selling
point is crisis behaviour, so losing that period matters. As far as we know, Alpaca's historical
stock data only goes back to about 2016.

The cache design (learning log, 2026-11-22) stores **raw** bars plus dividend and split events
and derives total returns itself. Vendor-adjusted prices rewrite history whenever a new dividend
is paid, so a cache of them goes stale.

Alternatives considered: yfinance (unofficial scraper, breaks, grey-area terms), Stooq (mostly
adjusted-only, no separate dividend data), EODHD/Norgate (paid, over the <$5/month budget).

## Decision

- **Tiingo's end-of-day API** (free tier, API key in `TIINGO_API_KEY`) is the source of
  historical daily bars. One request per symbol returns raw OHLCV plus `divCash` and
  `splitFactor`, which is exactly the cache format we want.
- **Alpaca is the broker only** (paper and live orders, positions, account). Which source feeds
  the *live* runner's fresh bars is decided in Phase 4. The `DataProvider` interface keeps that
  swappable. One open question: whether Tiingo's end-of-day prices are published early
  enough for a run shortly after the close.
- Tests never call Tiingo. Real-API tests are marked `@pytest.mark.network` and skipped by default.

## Consequences

- Backtest data and live fills come from different sources, which can disagree slightly.
  Phase 7's tracking-error report will show any gap.
- The free tier has rate limits and is licensed for personal use. That's fine for ~12 ETFs and
  incremental daily updates. Check the current limits before relying on them.
