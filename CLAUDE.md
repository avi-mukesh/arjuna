# CLAUDE.md — Arjuna

> *Arjuna saw only the bird's eye.* This is a focused, low-turnover systematic trading system. Its first strategy is
> multi-asset trend following with volatility targeting. The aims are: (1) real, risk-controlled returns,
> (2) teaching Avi quant finance as it's built, and (3) a clean portfolio project for quant-developer roles.

The full spec and phased roadmap are in `docs/PLAN.md`. Read it before starting a new phase.

---

## Who you're working with

- Avi is a software engineer (Apex/C#/Python) with a First-class MMath degree. Treat him as mathematically strong but still learning quant practice.
- **Teaching mode:** when you implement a quant concept for the first time (vol targeting, EWMA vol, deflated Sharpe, walk-forward, etc.):
  1. Before writing code, ask Avi **one or two Socratic questions** about it, then wait for his answer. He wants to reason it out first.
  2. After implementing it, add or update a short note in `docs/concepts/<concept>.md` covering intuition, the formula, the assumptions it relies on, how it breaks, and one reference.
- **Terminal commands:** whenever you suggest or run a command, explain what it does, including every flag and argument.

---

## Non-negotiable safety rules

1. **No real-money orders without explicit human approval.** Live mode needs *all* of the following: `ARJUNA_ENV=live`, the `--confirm-live` CLI flag, and `live.enabled: true` in `configs/environments/live.yaml`. Never set any of these yourself.
2. **Never weaken risk limits** (`src/arjuna/risk/limits.py` or `risk:` blocks in configs) unless Avi asks for it in this session.
3. **Secrets:** never commit them, print them or log them. Locally they live in `.env`, which is gitignored; `.env.example` holds placeholders only. On AWS they live in Secrets Manager.
4. **Tests never touch a real broker.** Unit tests use `SimBroker`. Integration tests against Alpaca *paper* are marked `@pytest.mark.paper`, and tests that call a real data API (Tiingo) are marked `@pytest.mark.network`. Both are skipped by default.
5. **Kill switch:** every order path must check `risk.kill_switch.is_engaged()` before submitting. If the check fails or errors, no order is sent (fail closed).
6. The live runner must **reconcile** broker positions against expected positions before trading. If they differ by more than tolerance, it halts and alerts; it never "fixes" positions on its own.

---

## Core design principle: one strategy function, three modes

```
target_weights = strategy.target_weights(history_up_to_t, current_weights, config)
```

- Strategies are **pure functions** of the data available at time *t*. They do no I/O and make no broker calls.
- The same strategy code runs in `backtest`, `paper` and `live`. Only the `DataProvider` and `Broker` implementations change.
- `execution/order_planner.py` turns target weights into orders, applying the no-trade band, lot rounding and the min-notional rule.
- **Timing convention:** signals are computed on the close of day *t*. Orders execute at the open of *t+1*. When paper/live, they are notional market orders (`time_in_force=day`, fractional) sent a few minutes after the open (ADR 0003). The backtest fills at the open of *t+1* plus extra slippage for that gap, and must model exactly this.

### Look-ahead bias is the #1 bug to prevent
- `tests/test_no_lookahead.py`: perturb or shuffle all data after *t* and assert that signals and weights at *t* don't change. Every new signal must pass this test.
- Use only trading-calendar-aware date logic (`data/calendar.py`), never naive `pd.bdate_range`.

---

## Repo structure

```
arjuna/
├── CLAUDE.md
├── README.md
├── pyproject.toml               # uv-managed; ruff, mypy, pytest config
├── .env.example
├── .github/workflows/ci.yml     # ruff + mypy + pytest on push
├── configs/
│   ├── strategies/
│   │   └── trend_multi_asset.yaml
│   ├── universes/
│   │   ├── us_etfs.yaml
│   │   └── ucits_etfs.yaml      # LSE-listed equivalents (for a possible UK live broker)
│   └── environments/
│       ├── backtest.yaml
│       ├── paper.yaml
│       └── live.yaml            # live.enabled: false by default
├── src/arjuna/
│   ├── cli.py                   # `arjuna backtest|sweep|walkforward|run|status`
│   ├── config/                  # schema.py (Pydantic models), loader.py (YAML → models, config hashing)
│   ├── data/                    # provider.py (interface), tiingo.py, cache.py (Parquet), calendar.py, returns.py
│   ├── signals/                 # momentum.py, volatility.py (EWMA), base.py
│   ├── strategies/              # base.py (Strategy protocol), trend_following.py, registry.py
│   ├── portfolio/               # sizing.py (vol targeting), constraints.py (caps, leverage, long-only)
│   ├── risk/                    # limits.py, kill_switch.py
│   ├── execution/               # broker.py (interface), sim.py, alpaca.py, order_planner.py
│   ├── backtest/                # engine.py, costs.py, metrics.py, report.py
│   ├── research/                # sweep.py, walk_forward.py, deflated_sharpe.py, trial_ledger.py
│   ├── live/                    # runner.py, reconcile.py, alerts.py
│   ├── storage/                 # base.py, local.py, s3.py, dynamo.py
│   └── api/                     # FastAPI app (served via Lambda + Mangum)
├── frontend/                    # Vite + React + TypeScript; lightweight charts
├── infra/                       # AWS CDK (Python)
├── notebooks/                   # exploration only; never imported by src/
├── docs/
│   ├── PLAN.md
│   ├── concepts/                # teaching notes (one per concept)
│   ├── decisions/               # ADRs: 0001-broker-abstraction.md, ...
│   └── learning-log.md          # Avi's running notes and answers to questions
└── tests/
    ├── unit/
    ├── integration/             # @pytest.mark.paper
    └── test_no_lookahead.py
```

---

## Tech stack

- **Python 3.12**, managed with `uv`. Libraries: `pandas`, `numpy`, `pydantic` v2, `pyyaml`, `alpaca-py` (broker), `httpx` (Tiingo data, ADR 0004), `pyarrow`, `exchange_calendars`, `fastapi`, `mangum`, `boto3`, `typer`, `structlog`.
- Dev tooling: `pytest`, `hypothesis` (property tests), `ruff`, `mypy --strict` on `src/`.
- **Frontend:** Vite + React + TS, TradingView `lightweight-charts` for equity curves. Keep it light: no state-management library and no component framework beyond something minimal.
- **Infra:** AWS CDK in Python. **Cost target is under $5/month:** no NAT gateways, no RDS, no always-on containers.

## Commands

```bash
uv sync                                   # install deps from lockfile
uv run pytest                             # run tests (paper-marked tests skipped)
uv run pytest -m paper                    # run Alpaca paper integration tests
uv run --env-file .env pytest -m network  # run real Tiingo data tests
uv run --env-file .env arjuna data update configs/strategies/trend_multi_asset.yaml
uv run arjuna data status configs/strategies/trend_multi_asset.yaml
uv run ruff check . && uv run ruff format .
uv run mypy src
uv run arjuna backtest configs/strategies/trend_multi_asset.yaml
uv run arjuna sweep configs/strategies/trend_multi_asset.yaml --param signal.lookbacks --param sizing.target_vol
uv run arjuna walkforward configs/strategies/trend_multi_asset.yaml
uv run arjuna run --env paper --dry-run   # plan orders, print them, submit nothing
```

---

## Conventions

- Type hints everywhere. Pydantic for config, and frozen dataclasses for domain objects (`Order`, `Fill`, `Position`).
- Returns are **simple daily returns** unless a name says `log_`. Volatility is **annualised** with √252 unless suffixed `_daily`.
- Weights are fractions of NAV. Positive means long.
- Every backtest/sweep/walk-forward run is appended to the **trial ledger** (`research/trial_ledger.py`) with its config hash, date range and Sharpe. The deflated Sharpe ratio reads N from this ledger, so never bypass it.
- Use structured logs (`structlog`) with a `run_id` on every line.
- Small PR-sized changes, each with tests. Record any architectural decision as a short ADR in `docs/decisions/`.
- Keep `notebooks/` out of the import graph. If notebook code is worth keeping, move it into `src/` with tests.

## When unsure

Ask Avi rather than guessing on anything that touches money, risk limits, AWS cost or the strategy spec. For pure engineering choices, pick the simplest option, note it in an ADR, and carry on.
