# Arjuna — Spec & Roadmap

## 1. Strategy v1: multi-asset trend following with vol targeting

### Universe (configurable, in `configs/universes/`)
Default `us_etfs.yaml` covers the main asset classes:
- Equities: SPY, QQQ, IWM, EFA, EEM
- Bonds: IEF, TLT, TIP
- Commodities/gold: GLD, DBC
- Dollar: UUP
- Real estate: VNQ

> **UK caveat:** UK retail investors are often blocked from buying US-domiciled ETFs at UK-regulated brokers because of
> product-disclosure (KID/PRIIPs, now being replaced by the FCA's CCI regime) rules. Check what your live broker actually allows before
> going live. `ucits_etfs.yaml` maps each sleeve to an LSE-listed UCITS equivalent, so switching universes is a config change.

### Signal
For each asset *i* and each lookback L ∈ `signal.lookbacks` (default `[21, 63, 126, 252]` trading days):
- `signal_type: sign` → s = sign(r_{t-L,t})
- `signal_type: scaled` → s = clip( r_{t-L,t} / (σ_i · √(L/252)), −2, 2 ) / 2

The final signal for each asset is the average across lookbacks, so it lies in [−1, 1].

### Volatility estimate
EWMA of daily returns with `vol.halflife` (default 60 days), annualised. Floor it at `vol.min_vol` so that very low-vol assets don't get huge positions.

### Sizing
- Per-asset: w_i = s_i · (σ_target_asset / σ_i), where σ_target_asset = `sizing.target_vol` / √N (a naive equal-risk split that ignores correlation).
- Portfolio overlay (`sizing.portfolio_scaling: true`): estimate the covariance (EWMA), then scale all weights so ex-ante portfolio vol = `sizing.target_vol`.
- Constraints:
  - `max_weight_per_asset`
  - `max_gross_leverage` (default 1.0)
  - `allow_short` (default **false**: long/flat). Starting long/flat works with a cash account and needs no margin.

### Rebalancing
- `rebalance.frequency: weekly` (default; signals are computed on the last trading day of the week).
- **No-trade band:** only trade asset *i* if |w_target − w_current| > `rebalance.band` (default 0.02). This is the main turnover control.
- Signal at the close of *t*, execution at the open of *t+1*. Paper/live send notional `day` market orders a few minutes after the open; the backtest fills at the open plus extra slippage (ADR 0003).

### Costs (`backtest/costs.py`)
Per-asset `half_spread_bps` + `slippage_bps` + `commission_per_share` (0 for Alpaca). The report must always show both gross and net results, plus the **cost drag**.

### Benchmarks
SPY buy-and-hold, 60/40 SPY/IEF (rebalanced monthly), and an equal-weight universe.

## 2. Metrics (`backtest/metrics.py`)
CAGR, annualised vol, Sharpe, Sortino, max drawdown and its duration, Calmar, annual turnover, cost drag, % time invested, monthly returns heatmap, rolling 1y Sharpe, and correlation to SPY. Also report crisis-period returns (2020-03, 2022) separately: trend following's selling point is "crisis alpha".

## 3. Robustness toolkit (`research/`)
- **Parameter sweep:** a grid over any config path(s) → heatmap of Sharpe. Look for a **plateau, not a peak**.
- **Walk-forward:** rolling or anchored train/test windows. Choose parameters in-sample, apply them out-of-sample, and stitch the OOS returns together. Report the OOS/IS Sharpe ratio.
- **Trial ledger:** an append-only record of every run (config hash, dates, Sharpe, skew, kurtosis, number of observations).
- **Deflated Sharpe Ratio** (Bailey & López de Prado, 2014). Uses N from the ledger plus the skew and kurtosis of returns, and gives the probability that the true Sharpe is > 0 after accounting for selection across trials.
- Optional later: Probability of Backtest Overfitting (CSCV), and a block bootstrap of returns for Sharpe confidence intervals.

## 4. Live/paper runner (`live/runner.py`)
Steps on each scheduled run:
1. Check the trading calendar. Exit if it's not a rebalance day.
2. Check the kill switch. If it's engaged, or the check errors, exit and alert.
3. Pull fresh daily bars, then compute target weights with the *same* strategy function.
4. **Reconcile** broker positions against the last stored expected positions. If they differ beyond tolerance, halt and alert.
5. Plan orders (band, rounding, min notional), then run pre-trade risk checks:
   - max order notional
   - max daily turnover
   - max gross leverage
   - allowed-symbols whitelist
6. Submit orders, or skip this step if `--dry-run`. This is a separate **submit** job a few minutes after the next open: re-check the kill switch, reconcile, recompute notionals from current NAV, re-run the pre-trade checks, then send fractional notional market orders (`time_in_force=day`). Symbols must be `fractionable` on Alpaca (ADR 0003).
   - The first rebalance from cash may use `--initial-deployment`, which swaps in `risk.initial_deployment_max_turnover` only if the account holds no positions (ADR 0002).
7. Persist targets, orders and (on the next run) fills. Send a summary alert.

### Tracking error (key paper-trading output)
A daily job compares paper fills against the prices the backtest assumed, giving the **implementation shortfall** in bps.

## 5. AWS architecture (CDK, `infra/`)
- **EventBridge Scheduler** → **Lambda (container image)** for the runner, on two schedules: **plan** Mon–Fri at 21:30 UK time, after the US close (the runner decides whether it's a rebalance day), and **submit** at ~09:31 America/New_York on the next trading day. Set the schedule's timezone to New York, not UK: the US and UK change clocks on different dates, so a fixed 14:31 UK time drifts by an hour for a few weeks each year.
- **S3:** a Parquet data cache, backtest reports, and the frontend's static build.
- **DynamoDB** (on-demand), single-table: runs, targets, orders, fills, positions snapshots, and the kill-switch flag.
- **Secrets Manager:** broker API keys, with separate secrets for paper and live.
- **API Gateway HTTP API → Lambda (FastAPI + Mangum)** for the frontend.
- **CloudFront** in front of the S3 frontend. **Cognito** user pool with a single user, because the frontend can toggle the kill switch.
- **CloudWatch alarms** (runner errors, runner didn't run, reconciliation failure) → **SNS** email to Avi.
- Optional later: a scheduled Fargate task for heavy sweeps/walk-forwards, so laptop runs aren't needed.

## 6. Frontend (light)
Pages:
1. **Dashboard:** equity curve (paper/live vs. backtest replay), current weights vs. targets, latest run status, kill switch toggle (with a confirm dialog).
2. **Backtests:** list of runs from the trial ledger. Click one to see its metrics, equity curve and drawdown chart.
3. **New backtest:** pick a strategy config, override a few params, launch it (async), and view the result.
4. **Orders/fills:** a table with implementation shortfall.

## 7. Roadmap

| Phase | Deliverable | Done when |
|---|---|---|
| 0 | Scaffold: uv, ruff, mypy, pytest, CI, config schema + loader | `uv run pytest` passes in CI |
| 1 | Data layer: Tiingo daily bars (raw + dividends/splits, ADR 0004), Parquet cache, trading calendar | Cached history for the universe; calendar tests pass |
| 2 | Signals, vol, sizing, strategy, backtest engine, costs, metrics, CLI | `arjuna backtest` prints a report; no-lookahead test passes |
| 3 | Research: sweep, walk-forward, trial ledger, DSR | Sweep heatmap and walk-forward OOS report produced |
| 4 | Broker interface, SimBroker, Alpaca paper adapter, order planner, risk checks, local runner | `arjuna run --env paper --dry-run` prints sensible orders |
| 5 | AWS: CDK stacks, scheduled runner, storage, secrets, alarms | Runner trades paper on schedule; an alert arrives on failure |
| 6 | API + frontend | Dashboard live behind Cognito |
| 7 | **Paper period ≥ 3 months** + tracking-error report | Shortfall understood; paper results consistent with backtest |
| 8 | Live, small fixed capital (human-gated) | Avi explicitly approves |

## 8. Later strategy ideas (plug in via `strategies/registry.py`)
- Volatility risk premium: defined-risk XSP/SPX put spreads (reuse the MC pricing engine for Greeks).
- Pairs / stat-arb: Kalman hedge ratio + OU spread.
- Strategy-level portfolio: allocate risk across strategies.
