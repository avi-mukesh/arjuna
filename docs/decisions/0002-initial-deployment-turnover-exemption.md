# 0002: Initial-deployment turnover exemption

- **Status:** accepted (Avi, 2026-11-22). Schema field added in Phase 0; runner logic lands in Phase 4.
- **Date:** 2026-11-22

## Context

The pre-trade check `risk.max_daily_turnover` (0.5 of NAV) is sized for normal weekly
rebalances, which nudge a few weights. Investing a new account from 100% cash needs
turnover close to the portfolio's gross exposure (~0.95), so the check would reject the
very first rebalance and the system could never get invested.

Alternatives considered: ramping in over two rebalances (half-invested for a week),
or raising `max_daily_turnover` to ~1.0 permanently (the check stops catching all but
huge errors). Avi chose a narrow exemption.

## Decision

Add a separate limit, `risk.initial_deployment_max_turnover`, to every environment
config. It is required (no default) and must satisfy
`max_daily_turnover <= initial_deployment_max_turnover <= max_gross_leverage`.

The runner uses it in place of `max_daily_turnover` **only when both** hold:

1. The operator passes `--initial-deployment` by hand. The scheduled runner never does.
2. The broker reports **zero open positions**. If any position exists, the flag is refused
   and the run halts with an alert. The exemption can't become a way round the normal cap.

Every other check still applies: the kill switch, `max_order_notional`,
`max_gross_leverage`, the symbol whitelist and reconciliation. Each use is logged and alerts.

## Consequences

- The normal turnover limit stays at 0.5 and keeps catching runaway rebalances.
- The first live/paper rebalance is a manual step. That's intended: a human watches it.
- Re-investing after liquidating everything also counts as an initial deployment.
