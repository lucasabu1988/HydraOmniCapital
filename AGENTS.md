# AGENTS.md — HYDRA Local Screener

Short version for any coding agent. Full guidance: `CLAUDE.md`. Task board: `GROKBOARD.md`.
Checked against the code on 2026-09-06.

## Focus

The active project is **`hydra_screener_local/`**. **Production since 2026-09-07 is HYDRA v9**
(`config.ALGO_VERSION = "v9"`): a 50/50 T20-stocks + ETF-trend portfolio run from a weekly
instruction sheet (`portfolio_v9.py`, state in `state/`, engine `core/portfolio_engine.py`, SPEC
section 9). The momentum + regime screener (5-trading-day cycles, universe `"all"`, ~3000 US names
incl. Russell 2000) feeds sleeve A and still writes the v8.4 Pine artefacts (parked). COMPASS / Render / IBKR / root `tests/` live in
`archive/root-legacy-2026-09/` — do not revive, extend, or take parameters from them.
Older agent docs: `archive/docs-legacy-2026-09/`.

## Locked algorithm

Scoring — `core/signals.py`, `core/meta_layer.py`, gate thresholds in `config.py`, and
`HYDRA_ALGORITHM_SPEC.md` — changes only with Lucas's explicit approval (GROKBOARD rule 6).
The spec is the source of truth and `test_spec_compliance.py` enforces formulas and parameter
values. Filters and selection rules (liquidity, sector cap, zombie removal) are
implementation-specific and are not scoring, but they change the recommended list: measure.

Parameters live in `hydra_screener_local/config.py`. Read them there; the legacy "5 positions,
max 3 per sector, 5-day skip" list is not this system.

## Test

```
cd hydra_screener_local && python run_all_tests.py
```

Must exit 0 before a task is marked done. pytest-style files are routed through pytest; skips
are reported separately from passes. CI runs only this suite (legacy root tests are archived).

## Protocol

- Touch only the files a task declares. Stage specific files — never `git add -A`.
- If a file you need already has someone else's uncommitted changes: stop, mark the task `[!]`,
  post in GROKBOARD Messages.
- Conventional commits, English. Spec updated in the same commit when behaviour changes.
- Claude reviews every completed task; it is closed only after the review note.
- Read all of `.comms/` at session start.

## Do not get these wrong

- The Meta-Layer does not change the ranking; it only moves `dynamic_count`.
- Sector control is a hard cap at selection on GICS sectors; scores untouched; `"Other"` exempt;
  sectors resolved once in `screener.py`, never in `core/`.
- Horizons are trading days. Entry is the first executable price, not the signal close.
- `history/` is gitignored and may not exist in your clone.
- The measurement harness (`experiments/backtest_variant_sweep.py`) is S&P 500 survivors,
  2020-2026. Validate it (`--validate`) before trusting a number from it.
