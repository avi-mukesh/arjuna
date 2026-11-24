# Total returns from raw prices

**Code:** `src/arjuna/data/returns.py` · **Tests:** `tests/unit/test_returns.py`

## Intuition
An ETF's price drops on its **ex-dividend date** by roughly the dividend, because new buyers
no longer get it. Holders lose nothing: share price plus cash is unchanged. A **split** (one
share becomes two at half the price) is also not a loss. A *price* return counts both as losses;
a **total return** counts what a holder actually earned.

## Formula
For session *t*, with raw close Cₜ, dividend per share Dₜ (ex-date *t*) and split factor Kₜ
(2.0 for a 2-for-1 split effective on *t*):

  rₜ = Kₜ · (Cₜ + Dₜ) / Cₜ₋₁ − 1

With no events (K = 1, D = 0) this is just Cₜ / Cₜ₋₁ − 1.

**Example.** TLT closes at $100; the next day it goes ex-dividend $1 and closes at $99:
price return −1%, total return (99 + 1)/100 − 1 = **0%**.

## Why cache raw prices and derive total returns ourselves
Vendors also publish **adjusted** prices: every price *before* an event is multiplied by
(1 − D/Cₜ₋₁) for dividends, or divided by K for splits.
- **Returns from adjusted prices are fine.** The factor cancels for windows that don't span
  the event, and windows that do span it get the total return. That's information an
  investor at *t* had, so this isn't look-ahead.
- **Adjusted price *levels* are not.** Nobody traded at them. Using them for share counts,
  lot rounding or price filters uses numbers that only exist with hindsight.
- **Adjusted series change every time a new dividend is paid**, so a cache of them goes stale.

So the cache stores raw OHLCV plus `div_cash` and `split_factor`. Signals and vol use total
returns; anything involving shares or dollars uses raw prices.

## Assumptions
- Dividends are reinvested at the ex-date close, with no tax or withholding. A UK investor in
  US ETFs pays 15% US withholding tax with a W-8BEN, so real-world total returns are slightly lower.
- `div_cash` is per *post-split* share on a day with both a split and a dividend.
- Tiingo's event data is correct. At download time we compare our returns with Tiingo's
  adjusted-close returns and log a warning if any day differs by more than 0.1%.

## How it breaks
- **Missing or wrong events:** a missed dividend shows up as a fake loss on the ex-date. That
  biases trend signals against high-yield assets like TLT by roughly their yield per year.
- **Wrong split convention** (K vs 1/K): a ±50% jump on the split day. The adjusted-close
  check catches it.
- **Distributions that aren't cash dividends** (return of capital, spin-offs) may not be in `div_cash`.

## Reference
- CRSP's definition of holding-period returns with distributions (the formula above):
  CRSP *Data Descriptions Guide*, "Returns".
- Tiingo end-of-day API documentation (fields `divCash`, `splitFactor`, `adjClose`):
  <https://www.tiingo.com/documentation/end-of-day>
