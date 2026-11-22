# 0003: Post-open notional market orders instead of market-on-open

- **Status:** accepted (Avi, 2026-11-22). Replaces "market-on-open orders when live" in CLAUDE.md and PLAN.md.
- **Date:** 2026-11-22

## Context

The original timing rule was: signal on the close of *t*, execute with market-on-open orders
(`time_in_force=opg`) at the open of *t+1*. With small live capital, whole-share rounding is
coarse (one SPY share ≈ 15% of a $4k account). That breaks the 2% no-trade band and the 1%
reconcile tolerance, so we need fractional shares.

Alpaca's fractional-shares documentation says fractional and notional orders are supported
only with `time_in_force=day`, not `opg`. So we can't have both fractional sizes and the
official opening price. (The same page contradicts itself about extended hours; paper testing
will settle it, and it doesn't affect this decision.)

Alternatives considered: splitting each order into a whole-share `opg` part plus a fractional
`day` remainder (twice the order handling, little benefit at small size); or whole shares
only, with enough capital for rounding not to matter (~$50k+). That second option stays
available as a later config change.

## Decision

- Signals are still computed on the close of day *t*.
- Orders are sent as **market orders with `time_in_force=day` and a `notional` (USD) amount**,
  a few minutes after the open of *t+1* (~09:31–09:35 ET).
- The runner becomes two scheduled jobs: **plan** after the close (21:30 UK) saves target
  weights and planned notionals; **submit** at ~09:31 America/New_York on the next trading day (schedule in New York time; UK and US clocks change on different dates), re-checks the kill
  switch, reconciles, recomputes notionals from current NAV, runs pre-trade checks and sends.
- Every symbol must have `fractionable = true` on Alpaca. The broker adapter checks this, and a
  non-fractionable symbol is a pre-trade error, not a silent fallback to whole shares.
- The **backtest still fills at the open of *t+1***, plus a configurable extra slippage
  to cover the gap between the official open and the post-open fill.

## Consequences

- Positions can be any size, so the backtest's weights carry over to small accounts.
- Fills are at the market price a few minutes after the open, not the opening auction price.
  Phase 7 measures this gap (implementation shortfall vs. the backtest's open price), and the
  extra slippage assumption is calibrated from it.
- Notionals have 2 decimal places, so tiny trades below the order planner's min-notional rule are dropped.
- Two EventBridge schedules instead of one: negligible cost.
- Fractional orders can't be short sales. That's fine while `allow_short: false`; revisit if
  shorting is ever enabled.
