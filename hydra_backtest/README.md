# hydra_backtest

Reproducible COMPASS standalone backtest for the HYDRA quantitative trading
system.

## What this is

A Python package that runs a COMPASS momentum backtest from 2000 to 2026
using point-in-time S&P 500 membership, producing a waterfall methodology
report (baseline → +T-bill → +next-open → +slippage → NET HONEST).

**This package is a consumer of `omnicapital_live.py`'s signal logic, not
an owner.** Pure functions are imported directly from the live engine.
Class methods that can't be imported are reimplemented as pure
equivalents with docstrings pointing to the source line.

## Why this exists

The legacy HYDRA dashboard number (14.5% CAGR / -22.2% MaxDD / 1.01 Sharpe)
was a four-layer Frankenstein with no reproducible code path. Three
nominally equivalent v8.4 implementations in the repo diverge silently.
This package is the foundation for resolving #34 (unify backtest and
live) and #37 (GO/NO-GO criteria).

See `docs/superpowers/specs/2026-04-06-hydra-reproducible-backtest-design.md`
for the full design.

## How to run

```bash
python -m hydra_backtest --start 2000-01-01 --end 2026-03-05
```

Outputs written to `backtests/`:

- `hydra_v2_daily.csv` — daily equity curve
- `hydra_v2_trades.csv` — all trades
- `hydra_v2_waterfall.json` — waterfall report (5 tiers)

And a summary table printed to stdout.

## How to test

```bash
# Fast unit + integration tests (< 30s total)
pytest hydra_backtest/tests/ -v -m "not slow"

# E2E full-run tests (~5 min, requires real data cache)
pytest hydra_backtest/tests/ -v -m slow

# With coverage
pytest hydra_backtest/tests/ -v --cov=hydra_backtest --cov-report=term-missing
```

## Architecture

```
data.py         — PIT universe, prices, yields, sectors, config validator
engine.py       — Backtest loop (imports live pure fns + pure equivalents)
methodology.py  — Waterfall corrections (T-bill, next-open, slippage)
validation.py   — Layer A smoke tests (blocking)
reporting.py    — CSV / JSON / stdout writers
errors.py       — Exception hierarchy (HydraBacktestError + subclasses)
__main__.py     — CLI entrypoint
```

All modules use frozen dataclasses for immutability. Each stage is a
pure function that takes immutable inputs and returns immutable outputs.

## Limitations (v1)

- **COMPASS only**: Rattlesnake, Catalyst, EFA, and cash recycling come in v1.1-v1.4
- **Fed Emergency overlay NOT applied**: out of scope for v1
- **Position renewal NOT applied**: v1 uses conservative "exit at hold_expired" always
- **PIT universe is ~827 tickers** (vs 1194 full historical S&P 500): residual bias documented
- **BRK-B excluded** by `validate_universe` regex bug (#13): fix will be absorbed when landed in live
