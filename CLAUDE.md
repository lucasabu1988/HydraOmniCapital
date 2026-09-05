# CLAUDE.md

Guidance for Claude Code working in this repository. Every fact here was checked against the
code on 2026-09-06; when this file and the code disagree, the code wins — then fix this file.

# HYDRA — Local Screener

## What this project is

A **momentum + regime-aware equity screener** that runs locally and hands its output to a
TradingView (Pine) indicator. It ranks a US universe daily, flags a dynamic number of names as
`recommended`, and is designed around **5-trading-day cycles**.

- Active code: `hydra_screener_local/` — everything you touch lives here.
- Universe in production: `UNIVERSE="all"` (S&P 500 ∪ Nasdaq-100 ∪ Dow ∪ Russell 1000 ∪ Russell
  2000, ~3000 names — roughly two-thirds mid/small caps).
- Hybrid flow: Python scores and selects; the user pastes `pine/hydra_last_summary.json` and
  `pine/watchlist.txt` into `pine/HYDRA_Screener.pine`. The authoritative `Rec?` flag is
  Python's, carried in that JSON.

**Everything at the repo root** (`compass_*.py`, `omnicapital_*.py`, `templates/`, `static/`,
root `tests/`) is the **frozen legacy** COMPASS engine + Render dashboard. `hydra_backtest/`
(the legacy backtest package) was deleted on 2026-09-06: it imported nine functions from
`omnicapital_live.py`, deleted on 2026-06-05, and had not been importable since. It lives in
git history (`git show e4b862a:hydra_backtest/`) if ever needed.
Do not revive it, extend it, or take parameters from it. `omnicapital_live.py` and
`omnicapital_broker.py` were deleted in the 2026-09-05 cleanup; docs that mention them are
archived under `archive/docs-legacy-2026-09/`.

## Critical rules

1. **The scoring algorithm is locked.** Formulas in `core/signals.py`, multipliers in
   `core/meta_layer.py`, gate thresholds in `config.py`, and `HYDRA_ALGORITHM_SPEC.md` change
   **only with Lucas's explicit approval** (GROKBOARD rule 6). The spec is the source of truth;
   `test_spec_compliance.py` enforces both the formulas and, since TASK-321, the parameter values
   in `config.py` against SPEC section 6. A scoring change lands with the spec updated in the
   same commit and measured numbers attached, or it does not land.
2. **Filters and selection rules are not scoring.** SPEC section 1 leaves them
   "implementation-specific": liquidity/price filters, the sector cap, zombie removal. They can
   change without a rule-6 approval, but they still change the recommended list — say so and
   measure it.
3. **Never anchor screener parameters on the legacy engine.** The old v8.4 list (5 positions,
   max 3 per sector, 90d momentum with a 5-day skip, adaptive stops) belongs to the frozen
   COMPASS engine and used a different sector taxonomy. Using it as a reference already caused
   one wrong change (TASK-318). Read `hydra_screener_local/config.py` instead.
4. **Verify, don't trust.** Three times in one week a test reported green without running, or a
   field was silently dropped, or a measurement ran on the wrong data. Before claiming a fix
   works: run the check that could actually fail, on real data where it exists.
5. **No secrets in commits.** `.env` and anything with credentials are gitignored.

## Architecture (`hydra_screener_local/`)

```
screener.py           — daily entry point: universe → fetch → filters → sectors → scoring → history/Pine
daily.py              — one-command ritual: runs screener.py, prints TradingView paste instructions
config.py             — all parameters (see below); SECTOR_BUCKETS fallback map; FILTERS; blacklist
HYDRA_ALGORITHM_SPEC.md — the algorithm, language-agnostic. Source of truth.

core/signals.py       — momentum, short-term features, strict filter, composite, dynamic count,
                        downtrend gate, output contract (SPEC 7)
core/meta_layer.py    — regime → aggression + pillar multipliers (see "facts" below)
core/regime.py        — rich regime from SPY (5 sub-scores, 30/25/20/15/10)
core/filters.py       — practical filters, zombie removal, sector cap at selection
core/history.py       — one JSON per run in history/ (gitignored)
core/tracking.py      — forward returns of recommended names, win-rate report (history/tracking/)

data/fetch.py         — batched yfinance download (prices + volume), 1y window
data/universe.py      — index constituents from several sources with JSON caches
data/sectors.py       — GICS sector cache; resolved once upstream in screener.py, never in core/

utils/display.py      — console tables
utils/trading_calendar.py — trading-day helpers shared by tracking and the Excel logger

pine/HYDRA_Screener.pine   — per-symbol Pine reimplementation + JSON parser (display layer)
generate_pine_watchlist.py, send_hydra_summary.py, validate_pine_contract.py — the hybrid bridge
log_cycle_positions.py, refresh_current_prices.py — Excel P&L tracker (backtest/portfolio_cycles.xlsx)
analyze_history.py, track_performance.py — reports over history/

experiments/backtest_variant_sweep.py — the validated point-in-time harness. `--validate`
                        proves it replicates generate_daily_candidates before any number is trusted.
run_all_tests.py      — the test runner (see Testing)
```

## Key parameters (from `config.py`, 2026-09-06)

| Parameter | Value | Notes |
|---|---|---|
| `MOMENTUM_LOOKBACK` | 90 | risk-adjusted: ret90 / vol63 (annualised) |
| `MOMENTUM_SKIP` | 5 | **defined but NOT applied**; open decision TASK-319 |
| `SHORT_TERM_LOOKBACK` / `PROXIMITY_HIGH_DAYS` | 10 / 20 | |
| `SHORT_TERM_BOOST` | 0.35 | strict bonus is +18% (hardcoded in signals.py) |
| `VOL_SURGE_THRESHOLD` / `MIN_VOL_THRESHOLD` | 1.50 / 1.0 | missing volume **fails** strict (SPEC 5) |
| `REGIME_SMA` / `MIN_REGIME_SCORE` | 200 / 0.35 | gate flag is `regime >= 0.35 * 0.85` |
| `ENABLE_DOWNTREND_GATE`, `GATE_MAX_DIST_TO_HIGH_PCT`, `GATE_MIN_RET_SHORT_PCT` | True, -8.0, -5.0 | "only-negative" rule: `ret_10d < 0` is necessary |
| `ENABLE_SECTOR_CONTROL` / `MAX_PER_SECTOR` | True / 5 | hard cap on **GICS** sectors at selection |
| `SECTOR_FETCH_BUDGET_SECONDS` | 120 | sector resolution upstream, time-boxed |
| dynamic count | `clamp(round(14 × aggression × compass), 6, 28)` | hardcoded in signals.py |
| `COST_BP_PER_SIDE` | 10 | modelled cost for sweep and tracking reports |
| `FILTERS` | min_avg_volume 100000 shares, min_price 5.0 | |
| `UNIVERSE` | "all" | |

If you need a value, read `config.py`. This table exists to stop legacy numbers being reused,
not to be copied from.

## Facts agents keep getting wrong

- **The Meta-Layer does not change the ranking.** `aggression` and `pillar_factor` are one
  positive scalar for every ticker that day (Spearman 1.000 between regimes). It only moves
  `dynamic_count` and the regime flag. `Rattlesnake`/`Catalyst`/`EFA` multipliers never reach
  scoring. Documented in SPEC 4.4; do not describe it as a style tilt.
- **Sector control is a hard cap at selection**, not a score penalty. Scores are untouched;
  the list is picked walking down the ranking and skipping a full sector. `"Other"` (unknown
  sector) is exempt. Sectors come from `data/sectors.py` and are resolved **once in
  screener.py** — `core/` does no network I/O.
- **Horizons are trading days.** The system is a 5-trading-day cycle; anything measuring in
  calendar days is a bug (the audit found tracking doing exactly that).
- **Entry is the first executable price** (the bar after the signal), never the close that
  generated the signal.
- **Regime is computed on SPY** while the universe is Russell-heavy. Known weakness (audit R1);
  changing it is a scoring change and waits for out-of-sample data (TASK-324).
- **`history/` is gitignored and exists on one disk.** It is the only record of what was
  recommended. Do not assume a fresh clone has it; tests that need it must skip, not fail.
- **The measurement harness is only S&P 500, 2020-2026, current constituents.** Survivorship
  bias in the direction that flatters momentum. Every number from it carries that caveat.

## Testing

```bash
cd hydra_screener_local && python run_all_tests.py      # the suite that matters
python run_all_tests.py --list                          # what it discovers
python -m pytest test_volume_watchdog.py -q             # any single pytest-style file
```

- The runner routes files that define `test_*` functions but have no `__main__` block through
  pytest — running them as scripts used to report `[PASS]` without executing anything.
- Skips are reported separately from passes (`N passed, M skipped`). A skip is not a pass.
- `test_hybrid_integration.py` skips when `history/` is absent.
- CI (`.github/workflows/test.yml`) runs two jobs: `test` (frozen legacy, root `pytest tests/`,
  informational coverage) and `screener` (`hydra_screener_local/run_all_tests.py`, since
  2026-09-06). A red `screener` job is about this project; a red `test` job is about the legacy.

## Claude ↔ Grok protocol

Two agents share this working tree: **Claude** (architect/reviewer) and **Grok** (implementer).

- `GROKBOARD.md` is the formal task board (queue, messages newest-first, completed). `.comms/`
  holds coordination notes, design notes and audits; each agent edits only its own section of
  `.comms/status.md`.
- Rules 1-9 on the board, in short: touch only a task's declared `Files:`; stage specific files,
  never `git add -A`; conventional commits; the suite must exit 0 before marking done; task
  states `[ ]`/`[~]`/`[x]`/`[!]`; no scoring or spec changes without approval; if a file you
  need has someone else's uncommitted changes, **stop and post**; every completed task is closed
  only after Claude's review note.
- Read all of `.comms/` at session start.

## Conventions

- Python 3.14 on Windows 11. PEP 8, snake_case, UPPER_CASE constants. Match the surrounding
  file: no retroactive type annotations or docstrings on old code.
- `pct_change(fill_method=None)` always — the pandas default is deprecated and pads gaps.
- External calls (yfinance, HTTP) are wrapped and never crash a run; the scoring path stays
  pure and offline.
- Windows consoles are cp1252: never let a UTF-8 print take down a runner or a test.
- Commits: conventional (`feat:`, `fix:`, `test:`, `refactor:`, `docs:`), body explains why and
  cites measured numbers when behaviour changes, `Co-Authored-By` for AI.
- Language: prompts in Spanish, code and commits in English.

## Careful action protocol

- Free: local, reversible edits; running tests; reading logs and history.
- Commit and push after each logical change set — the user does not want to be asked.
- Confirm first: deleting files or branches, `reset --hard`, force-push, anything that reverses
  a decision Lucas made explicitly.
- Never `--no-verify`; never resolve someone else's uncommitted work by discarding it.
- Authorization for one change does not extend to similar ones.

## Post-implementation

1. Run the check that could fail (real data where it exists, not only gap-free synthetics).
2. `python run_all_tests.py` exits 0.
3. Spec updated in the same commit if behaviour changed.
4. Commit with numbers, push.
