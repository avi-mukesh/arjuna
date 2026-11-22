# 0001: Config schema and config hashing

- **Status:** accepted
- **Date:** 2026-11-19

## Context

Every backtest, sweep and walk-forward run is recorded in the trial ledger with a
config hash, and the deflated Sharpe ratio counts trials from that ledger. So we need
(a) configs that can't silently hold typos, and (b) a hash that changes exactly when
the *effective* configuration changes.

## Decision

1. **Pydantic v2 models with `extra="forbid"` and `frozen=True`** for every config.
   Unknown keys fail validation; loaded configs are immutable.
2. **Strategy files reference a universe by name** (`universe: us_etfs`), resolved to
   `configs/universes/<name>.yaml`. Inline mappings are also accepted.
3. **Risk limits in environment configs have no defaults.** Each environment states its
   limits in YAML. The env/broker pairing is validated (`live` ⇔ `alpaca_live`), and
   `live.enabled: true` is rejected outside the `live` env.
4. **The hash is SHA-256 of the validated model's canonical JSON** (`model_dump(mode="json")`,
   sorted keys, no whitespace), with the universe already resolved.

## Consequences

- YAML formatting, comments and key order don't affect the hash; writing out a default
  hashes the same as omitting it.
- Changing a default in `schema.py` changes the hash of every config relying on it. That
  is intended: the effective strategy changed.
- Cosmetic fields (`name`, asset display names) are included in the hash. Renaming a
  config therefore counts as a new trial. This over-counts N for the deflated Sharpe,
  which errs on the conservative side; revisit if it becomes noisy.
- Floats are hashed via their JSON repr, so `0.1` and `0.10` hash the same, but
  `0.1` vs `0.1000000001` do not. That's fine for hand-written configs.
