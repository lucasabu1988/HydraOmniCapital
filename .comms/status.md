# Status Board

Each agent updates ONLY their own section. Read the other's section before starting work to avoid conflicts.

## Claude
**Updated:** 2026-09-07 01:30
**Working on:** HYDRA v9 (Lucas authorised 50/50 T20+ETF for production). Engine, ETF sleeve signals,
12-7 momentum option, tranche book move, SPEC 4.1/9, parity tests vs the executable simulator.
**Files I'm touching:** `core/portfolio_engine.py`, `core/tranche_book.py`, `core/signals.py`,
`sleeves/etf_trend.py`, `config.py` (V9 block + ALGO_VERSION only), `HYDRA_ALGORITHM_SPEC.md`,
`test_spec_compliance.py`, `test_portfolio_engine.py`, `experiments/tranche_book.py` (becomes a shim)
**Blockers:** none. Not touching `data/fetch.py`, `portfolio_v9.py`, `daily.py` (Grok, 339/340).

## Grok
**Updated:** 2026-09-07 02:20
**Working on:** idle. TASK-339 done, ready for review. TASK-340 waits for the engine
interface on the board; TASK-341 waits for Claude's engine commit.
**Files I'm touching:** none
**Blockers:** none. Not editing scoring, config, core/, screener.py, daily.py, or
Claude's dirty files.
