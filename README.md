# Arjuna

> *Arjuna saw only the bird's eye.*

A focused, low-turnover systematic trading system. Strategy v1 is multi-asset trend
following with volatility targeting. The same pure strategy function runs in backtest,
paper and live modes; only the data provider and broker change.

- Spec and roadmap: [docs/PLAN.md](docs/PLAN.md)
- Working agreement for AI assistants: [CLAUDE.md](CLAUDE.md)
- Decisions: [docs/decisions/](docs/decisions/)

## Status

- Phase 0 (scaffold): done.
- Phase 1 (data layer): Tiingo daily bars, Parquet cache, NYSE calendar. Code done; first real download pending.

## Quick start

```bash
uv sync                                                   # create .venv and install locked deps
uv run pytest                                             # tests (paper-marked tests skipped)
uv run arjuna validate configs/strategies/trend_multi_asset.yaml
cp .env.example .env                                      # then put your TIINGO_API_KEY in .env
uv run --env-file .env arjuna data update configs/strategies/trend_multi_asset.yaml
uv run arjuna data status configs/strategies/trend_multi_asset.yaml
```
