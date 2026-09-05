# HYDRA Reproducible Backtest — Design Spec

**Date**: 2026-04-06
**Status**: Draft — pending user review
**Author**: Claude Code brainstorming session
**Context**: Response to audit of dashboard number provenance (see chat transcript 2026-04-06)

## 1. Problem statement

The HYDRA dashboard shows "CAGR 14.5% / MaxDD -22.2% / Sharpe 1.01" as the headline performance number for the fund-comparison page. An audit of the data pipeline revealed that this number is a four-layer Frankenstein with no reproducible code path:

1. Base `hydra_corrected_daily.csv` — written by a script that is not in the repository (no `.py` file produces it)
2. Manual patch to 4 days in Jan-Mar 2022 (replaced returns with SPY returns) that mathematically cannot account for the reported MaxDD improvement from -53.6% to -31.2%
3. Blend with `exp68_4th_pillar_trend_gold.py` output (85% HYDRA + 10% trend + 5% gold) that overwrites the HYDRA base curve
4. Flat -1.0% annual "execution costs" subtraction via `scripts/generate_fund_comparison.py`

None of the HYDRA backtest scripts in the repo produce the number currently shown. The live engine (`omnicapital_live.py`) has its own inline implementation of v8.4 that differs from both `omnicapital_v84_compass.py` (locked by hookify, used for quoted backtest numbers) and `experiments/exp50_hydra_dynamic_pool.py` (uses LEV_FLOOR=0.15 instead of 0.30). Three nominally equivalent v8.4 implementations diverge silently.

This is the problem that GitHub issue #34 ("Unificar backtest y universo point-in-time") exists to solve, and it is a blocker for issue #37 (GO/NO-GO criteria for validating HYDRA's alpha).

## 2. Success criterion (decided)

"Defendible publicly" — a reproducible end-to-end COMPASS backtest that anyone can run with a single command from a versioned commit and obtain the same CSV byte-for-byte. Methodology must be defensible under academic peer review (PIT universe, T-bill cash yield, realistic execution model, per-trade costs). Fidelity with `omnicapital_live.py`'s instantaneous behavior is a primary goal but not an absolute constraint — small deltas with proper documentation are acceptable.

## 3. Scope (decided)

**In scope for v1**:
- COMPASS standalone (S&P 500 large-cap cross-sectional momentum, the primary HYDRA pillar)
- PIT universe from existing `data_cache/sp500_*` infrastructure (exp40/exp61 pipeline, ~882 tickers, 74% coverage)
- Signal logic imported from `omnicapital_live.py` (not `omnicapital_v84_compass.py`, not reimplemented from docs)
- Waterfall methodology reporting: baseline (live) → +T-bill → +next-open → +slippage/spread → NET HONEST
- Validation layer A (smoke tests, blocking for v1)
- CSV output in same schema as `backtests/hydra_clean_daily.csv` (drop-in compatible but writes to new filename `backtests/hydra_v2_results.csv`)

**Out of scope for v1 (deferred to incremental PRs)**:
- Rattlesnake mean-reversion (v1.1)
- Catalyst cross-asset trend (v1.2)
- EFA international overflow (v1.3)
- HydraCapitalManager cash recycling (v1.4)
- Validation layer B (cross-validate vs `compass_net_backtest.py`)
- Validation layer C (walk-forward against live state JSONs)
- Dashboard integration (the dashboard continues to show the current Frankenstein number with no changes until all pillars land)

**Explicit non-goals**:
- Not refactoring `omnicapital_live.py` (no changes to the live engine as part of this spec)
- Not fixing the crash brake "bug" discovered in issue #36 (the delta is marginal and belongs to a separate issue)
- Not replacing `backtest_lab.py` or any of the exp*.py files (they continue to exist for experimentation)

## 4. Architecture

### 4.1 Package layout

```
NuevoProyecto/
├── omnicapital_live.py              ← LIVE ENGINE (UNTOUCHED)
├── hydra_backtest/                  ← NEW PACKAGE
│   ├── __init__.py
│   ├── __main__.py                  ← CLI entrypoint
│   ├── data.py                      ← PIT universe, prices, T-bill, sectors
│   ├── engine.py                    ← Backtest loop (imports live pure fns)
│   ├── methodology.py               ← Waterfall corrections
│   ├── reporting.py                 ← CSV / JSON writers
│   ├── validation.py                ← Smoke tests (v1) + cross + walk (later)
│   ├── errors.py                    ← Custom exception hierarchy
│   └── tests/
│       ├── __init__.py
│       ├── test_data.py
│       ├── test_engine.py
│       ├── test_methodology.py
│       ├── test_validation.py
│       ├── test_integration.py
│       └── test_e2e.py              ← marked @pytest.mark.slow
├── backtests/
│   └── hydra_v2_results.csv         ← output (new, coexists with legacy CSVs)
└── docs/superpowers/specs/
    └── 2026-04-06-hydra-reproducible-backtest-design.md  ← this file
```

### 4.2 Guiding principle: consumer, not owner

`hydra_backtest/` is a **consumer** of COMPASS signal logic, not an owner. Pure functions from `omnicapital_live.py` are imported directly:

```python
# hydra_backtest/engine.py
from omnicapital_live import (
    compute_live_regime_score,      # line 526
    regime_score_to_positions,      # line 571
    compute_momentum_scores,        # line 602 — THE signal
    compute_volatility_weights,     # line 656
    compute_quality_filter,         # line 685
    compute_adaptive_stop,          # line 717
    compute_entry_vol,              # line 744
    filter_by_sector_concentration, # line 770
    compute_dynamic_leverage,       # line 793
    _dd_leverage,                   # line 811
    validate_universe,              # line 502 — has BRK-B bug, flagged
)
```

All of these are top-level pure functions in `omnicapital_live.py`. They take `config` as a parameter when needed and have no dependency on `self.broker`, `self.notifier`, threads, or clocks.

Functions that live as class methods on `COMPASSLive` (e.g., `get_current_leverage` at line 1396, the exit/entry loops inside `_run_cycle`) are reimplemented as pure equivalents in `engine.py` with docstrings pointing to the source line in the live engine. These pure equivalents have unit tests that compare outputs bit-for-bit against mocked live instances (parity tests).

Total reimplementation: ~300-400 lines, plus tests. Everything else is imported.

### 4.3 Key data types

```python
# engine.py
@dataclass(frozen=True)
class BacktestState:
    cash: float
    positions: dict                     # symbol -> PositionDict (mirrors live position_meta schema)
    peak_value: float
    crash_cooldown: int
    portfolio_value_history: tuple      # immutable rolling history

@dataclass(frozen=True)
class BacktestResult:
    config: dict                        # parameters used for the run
    daily_values: pd.DataFrame          # date, portfolio_value, cash, n_positions, leverage, drawdown, regime_score
    trades: pd.DataFrame                # symbol, entry_date, exit_date, exit_reason, entry_price, exit_price, pnl, return, sector
    decisions: list[dict]               # JSONL of every signal/entry/exit decision with reason
    exit_events: list[dict]             # exit metadata (was_stop_gap, stop_level, etc.)
    universe_size: dict[int, int]       # year → count of tradeable tickers
    started_at: datetime
    finished_at: datetime
    git_sha: str                        # commit hash at run time (reproducibility anchor)
    data_inputs_hash: str               # sha256 of price_data fingerprint
```

```python
# methodology.py
@dataclass(frozen=True)
class WaterfallTier:
    name: str                           # "baseline" | "t_bill" | "next_open" | "real_costs" | "net_honest"
    description: str
    cagr: float
    sharpe: float
    sortino: float
    calmar: float
    max_drawdown: float
    volatility: float
    win_rate: float
    total_trades: int
    final_value: float
    delta_cagr_bps: float               # vs previous tier
    delta_sharpe: float
    delta_maxdd_bps: float

@dataclass(frozen=True)
class WaterfallReport:
    tiers: list[WaterfallTier]          # [baseline, t_bill, next_open, real_costs, net_honest]
    baseline_result: BacktestResult
    net_honest_result: BacktestResult
```

Frozen dataclasses guarantee immutability — each transformation produces a new object, eliminating a class of bugs.

## 5. Data flow

```
CLI (__main__) → data.py (load) → engine.py (backtest loop)
                                      ↓
                                  BacktestResult (raw tier 0)
                                      ↓
                                  methodology.py (waterfall)
                                      ↓
                                  WaterfallReport (4 tiers + net honest)
                                      ↓
                                  validation.py (smoke tests, blocking)
                                      ↓
                                  reporting.py (CSV + JSON + stdout summary)
                                      ↓
                                  exit 0
```

Each stage is a pure function that takes immutable inputs and produces immutable outputs. No hidden state, no global mutation.

## 6. Backtest loop specification

### 6.1 Per-day execution sequence

For each trading day `date` with index `i` in `all_dates`:

1. **Mark-to-market valuation**: compute `portfolio_value = cash + sum(shares * Close[date])` for all open positions
2. **Universe resolution**: get PIT tradeable symbols for this date from `pit_universe`
3. **Regime score**: `compute_live_regime_score(spy_data.loc[:date])`
4. **Drawdown**: `(portfolio_value - peak_value) / peak_value`
5. **Leverage computation** (pure equivalent of `COMPASSLive.get_current_leverage`):
    - `dd_lev = _dd_leverage(drawdown, config)`
    - Crash brake check: if crash_cooldown > 0 or velocity triggers fire, `dd_lev = min(CRASH_LEVERAGE, dd_lev)` and bypass LEV_FLOOR (mirrors live behavior at `omnicapital_live.py:1444-1446`)
    - `vol_lev = compute_dynamic_leverage(spy_data.loc[:date], config)`
    - `target_lev = min(dd_lev, vol_lev)`
    - If not crash_active: `leverage = max(target_lev, LEV_FLOOR)`; else `leverage = target_lev`
6. **Max positions**: `get_max_positions_pure(regime_score, spy_data.loc[:date], config)` — includes bull override
7. **Daily costs**: margin cost if leverage > 1.0 (n/a with LEVERAGE_MAX=1.0 in production), cash yield on idle cash
8. **Compute quality filter**: `compute_quality_filter(price_data, tradeable, date)`
9. **Compute scores ONCE**: `compute_momentum_scores(price_data, quality_syms, date, all_dates, i)` — reused by exits (renewal check) and entries
10. **Apply exits** (pure equivalent of live's `_check_exits`, order preserved):
    - Hold expired (with renewal check using `should_renew_position`)
    - Position stop (adaptive, vol-scaled)
    - Trailing stop (vol-scaled activation)
    - Universe rotation (symbol no longer in tradeable)
    - Regime reduce (worst-performing excess position)
11. **Apply entries** (pure equivalent of live entry loop):
    - Rank available scores
    - Sector concentration filter
    - Inverse-vol weights
    - Effective capital = cash * leverage * 0.95 (5% buffer)
    - For each selected: compute shares, check `cost + commission <= cash * 0.90`, open position
12. **Record daily snapshot**
13. **Update state** (peak, cooldown, portfolio_value_history)

### 6.2 Execution mode parameter

`execution_mode: str = 'same_close'` (default) or `'next_open'`.

For `'same_close'`: entry/exit price is `price_data[symbol].loc[date, 'Close']`.

For `'next_open'`: entry/exit price is `price_data[symbol].loc[all_dates[i+1], 'Open']`. If `i + 1 >= len(all_dates)` or the symbol doesn't trade on the next day, the action is skipped (position carries). Entry records use `next_date` as `entry_date` and `i+1` as `entry_idx` so the hold counter runs from the fill day, not the signal day (lesson from `experiments/exp75_next_open_execution.py`).

Gap-through on stops is implicit: if the stop condition fires at `Close[T]` and `Open[T+1] < stop_level`, the realistic fill is `Open[T+1]`, which is worse than the stop level (that's gap-through loss).

## 7. Methodology waterfall specification

### 7.1 Tier definitions

| Tier | Name | Correction | Cash yield | Execution | Per-trade cost |
|---:|---|---|---|---|---|
| 0 | baseline | none (live behavior) | Aaa IG Corporate (FRED DAAA) | same_close | IBKR commissions only (live's `COMMISSION_PER_SHARE`) |
| 1 | t_bill | swap cash yield | T-bill 3M (FRED DGS3MO) | same_close | same as tier 0 |
| 2 | next_open | tier 1 + realistic exec | T-bill | next_open | same as tier 0 |
| 3 | real_costs | tier 2 + slippage/spread | T-bill | next_open | IBKR commissions + 2bps slippage + 0.5bp half-spread (round-trip) |
| net_honest | alias for tier 3 | | | | |

### 7.2 Computation approach

Tiers 0, 1, 2 require **separate full backtest runs** because each correction affects downstream decisions (cash yield affects compounding → portfolio_value → drawdown → leverage → decisions; next-open affects fills → cash → position sizing).

Tier 3 is **post-processing** of tier 2's `BacktestResult`: for each trade, apply slippage + spread to entry and exit prices, recompute pnl, regenerate equity curve. This is mathematically valid because per-trade costs at these levels (4.5bps round-trip) are too small to change signal ordering or stop condition evaluation.

Total: 3 full backtest runs + 1 post-process. Estimated runtime: ~4-6 minutes total on cached data.

### 7.3 Cost parameters (decided)

- `COMMISSION_PER_SHARE = 0.0035` (IBKR tiered commission, matches `omnicapital_broker.py:IBKRBroker`)
- `COMMISSION_CAP_PCT = 0.01` (1% of trade value cap, per IBKR tiered)
- `SLIPPAGE_BPS = 2.0` (conservative for S&P 500 large caps, mid of AQR 0.23% and retail momentum 0.80%)
- `HALF_SPREAD_BPS = 0.5` (typical bid-ask for SPX large caps in regular hours)
- Round-trip cost (tier 3 addition): 5 bps per trade. At ~197 trades/year turnover, this is ~98 bps annual drag.

## 8. Validation strategy

### 8.1 Layer A — Smoke tests (BLOCKING for v1)

`hydra_backtest/validation.py::run_smoke_tests(result)` runs after each backtest run, before reporting. Any failure raises `HydraBacktestValidationError` and aborts.

**Mathematical invariants**:
1. No lookahead: each decision's `data_date` ≤ `decision_timestamp`
2. Cash conservation: `abs((cash + sum(positions) + realized_pnl) - expected) < 1e-6` per bar
3. No NaN in `daily_values`
4. `peak_value` monotonic non-decreasing
5. `drawdown ∈ [-1.0, 0]` always
6. `leverage ∈ [CRASH_LEVERAGE, LEVERAGE_MAX]` always (0.15 to 1.0)
7. `n_positions ∈ [0, NUM_POSITIONS + bull_override_max]` always

**Statistical sanity**:
8. Daily return vol annualized in `[5%, 40%]`
9. No daily return > +15% or < -15% (except hardcoded allowlist for known crashes)
10. Sharpe positive (warn, not fail, if negative)
11. Trades per year in `[50, 500]`

**Config consistency**:
12. `exit_reason == 'position_stop'` implies `return < 0` and `return ≈ adaptive_stop ± 1pp`
13. `exit_reason == 'hold_expired'` implies `days_held ≥ HOLD_DAYS` (except renewals)
14. Max positions per sector ≤ `MAX_PER_SECTOR` in every bar

**Target runtime**: <2 seconds for a 26-year backtest.

### 8.2 Layer B — Cross-validation (v1.1, not in v1)

Run `compass_net_backtest.py` in parallel on the same PIT universe, compute cumulative return divergence, assert tracking error per year ≤ 50 bps. Non-blocking: used as a "dramatic change detector", not an absolute gate.

### 8.3 Layer C — Walk-forward against live (v1.2, not in v1)

Parse `state/compass_state_*.json` files from 2026-03-06 onwards. For each day, compare backtest decisions against live decisions (position set equality, cash ±1%, entry_dates match, exit events match). Zero-divergence tolerance for decisions. Non-blocking for v1 due to complexity of parsing live state schema.

## 9. Error handling

**Philosophy**: fail loud, never silent. No `try/except: pass`. Offline analysis, no reason to swallow errors.

Exception hierarchy (`hydra_backtest/errors.py`):
- `HydraBacktestError` (base)
  - `HydraDataError` (input data problems)
  - `HydraBacktestValidationError` (smoke test failures)
    - `HydraBacktestLookaheadError` (specific: lookahead detected)

**Case handling**:
- Missing ticker during signal compute: log WARNING, exclude from bar; if >10% of universe missing, raise `HydraDataError`
- Missing SPY date: raise `HydraDataError` (no fallback, SPY is critical)
- NaN momentum score: exclude ticker, log DEBUG
- Negative cash after trade: raise `HydraBacktestValidationError` (should never happen)
- Lookahead detected: raise `HydraBacktestLookaheadError` with symbol and date
- Invalid config: validate at start by porting the validation logic from `COMPASSLive._validate_config` (`omnicapital_live.py:1032`) as a pure function in `hydra_backtest/data.py`. Raise `HydraDataError` on failure.

## 10. Testing strategy

### 10.1 Test pyramid

- **Unit tests**: ~60, <1s each, cover pure functions in every module
- **Integration tests**: ~8, ~30s each, run 1-3 year backtests with small synthetic or real cached universes
- **E2E tests**: ~2, ~5 min each, marked `@pytest.mark.slow`, run full 2000-2026 and verify determinism

### 10.2 Critical tests

- `test_engine.py::test_parity_apply_exits_trailing_stop` — fixture of 3 days, 5 symbols, compares `apply_exits` output against mocked live instance (guardian of live-parity property)
- `test_data.py::test_pit_universe_anti_survivorship` — for fixed historical dates, verify returned universe does NOT include tickers delisted before that date
- `test_engine.py::test_determinism` — two runs with same seed produce byte-identical CSV outputs (reproducibility anchor)
- `test_integration.py::test_waterfall_monotonicity` — tier 0 ≥ tier 1 ≥ tier 2 ≥ tier 3 in CAGR (±5bp tolerance for noise)

### 10.3 Coverage targets

- 80% line coverage in `hydra_backtest/` overall (CI gate)
- 100% line coverage in `methodology.py` and `validation.py` (critical, small, easy to cover)
- E2E tests are excluded from coverage default run

### 10.4 CI integration

Add to existing `.github/workflows/ci.yml`:
```yaml
- name: Test hydra_backtest package
  run: pytest hydra_backtest/tests/ -v --cov=hydra_backtest --cov-fail-under=80 -m "not slow"
```

E2E slow tests run on-demand with `pytest hydra_backtest/tests/ -m slow`.

## 11. Fixed parameters

| Parameter | Value | Rationale |
|---|---|---|
| Time range | 2000-01-01 → 2026-03-05 | Day before paper trading start → backtest is fully out-of-sample vs live |
| Walk-forward range (v1.2) | 2026-03-06 → today | Where state JSONs exist |
| Initial capital | $100,000 | Match live config |
| Seed | 666 | Project convention |
| PIT source | `data_cache/sp500_constituents_history.pkl` + `sp500_universe_prices.pkl` | Existing infrastructure from exp40/exp61, 882 tickers, 74% coverage of 1194 historical S&P 500 members |
| T-bill series | FRED DGS3MO | Academic standard for risk-free rate |
| Aaa series (tier 0) | FRED DAAA | Matches current live CONFIG |
| Slippage | 2 bps | Conservative for S&P 500 large caps |
| Half-spread | 0.5 bps | Typical SPX bid-ask |
| IBKR commission | $0.0035/share, 1% notional cap | Matches `omnicapital_broker.py:IBKRBroker` tiered |
| Signal source | `omnicapital_live.py` top-level pure functions | Canonical live engine, not v8.4 locked spec |
| Dashboard update | NOT in v1 | Dashboard continues showing Frankenstein number until HYDRA full (v1.4) lands |

## 12. Open questions / risks

1. **882/1194 ticker coverage**: ~26% of historical S&P 500 members are not in the PIT price cache. Residual survivorship bias is non-zero. v1 ships with this limitation documented in the CLI output and spec. Mitigation: flag the specific missing tickers in smoke test output so future work can prioritize filling gaps. Escalation: if residual bias turns out to be >50bps CAGR (measured by comparing against a known-complete subset), switch to Norgate Data.

2. **Parity test coverage of live**: the `test_parity_apply_exits_*` tests cover specific scenarios (trailing stop, hold expired, etc.) but cannot exhaustively prove the pure equivalents match the live class methods in every corner case. We rely on the fact that the pure functions imported directly from live are not reimplemented, and the reimplemented ones (~300-400 lines) are the smallest possible surface. Periodic re-running of parity tests when the live engine is modified is the ongoing mitigation.

3. **BRK-B regex bug in `validate_universe`**: issue #13 — the regex `^[A-Z]{1,5}$` rejects tickers with hyphens. We import `validate_universe` as-is to faithfully reproduce live behavior, but this means BRK-B is silently excluded from both the live and the backtest. The backtest spec documents this as a known issue that should be fixed in a separate PR (modifying `omnicapital_live.py:498`). The backtest automatically absorbs the fix when it lands.

4. **Data cache consistency**: the PIT universe data was generated by a pipeline that isn't fully in the repo (exp61 predecessors used scripts that were removed). v1 treats the cached pickles as trusted inputs but checksums them on load and records the hash in `BacktestResult.data_inputs_hash` for reproducibility auditing.

5. **Long-term package structure**: this v1 is COMPASS-only. Adding Rattlesnake (v1.1) and the remaining pillars may reveal that the current module boundaries (`data.py`, `engine.py`, `methodology.py`) need refactoring. The spec commits to reviewing the boundaries at the v1.1 milestone and adjusting if necessary rather than optimizing upfront.

## 13. Incremental roadmap (summary)

| Version | Scope | Blockers |
|---|---|---|
| v1.0 | COMPASS standalone + Layer A validation + waterfall + CSV output | Nothing |
| v1.1 | Add Rattlesnake pillar + its own parity tests + Layer B cross-validation | v1.0 merged |
| v1.2 | Add Catalyst pillar + Layer C walk-forward against live state JSONs | v1.1 merged, state JSON parser stable |
| v1.3 | Add EFA pillar (idle cash overflow) | v1.2 merged |
| v1.4 | Add HydraCapitalManager cash recycling + HYDRA full integration | v1.3 merged |
| v1.5 | Replace dashboard `hydra_clean_daily.csv` with `hydra_v2_results.csv`, update `scripts/generate_fund_comparison.py`, archive the Frankenstein | v1.4 merged and validated |

Each version is its own PR with its own tests, its own validation gate, its own commit trail. The dashboard number is the final dependency, not the first.

## 14. Non-goals (explicit)

- Not building a generic backtest framework (vectorbt, backtrader, etc.)
- Not optimizing for backtest speed beyond "runs in a reasonable time" (target ~2 min per tier)
- Not producing a tutorial or public documentation (spec is for internal audit)
- Not refactoring `omnicapital_live.py` to extract a pure core (that's a separate effort, bigger in scope)
- Not adding new strategies beyond the existing HYDRA four pillars
- Not changing signal parameters, stop logic, or risk rules (LOCKED per CLAUDE.md)

## 15. Success criteria (measurable)

v1 is considered complete when:

1. `python -m hydra_backtest --start 2000-01-01 --end 2026-03-05` runs to completion without errors on a clean checkout
2. Two consecutive runs produce byte-identical `backtests/hydra_v2_results.csv`
3. All smoke tests (Layer A) pass
4. Unit + integration test coverage ≥ 80% in CI
5. Waterfall report prints 4 tiers with monotonic CAGR degradation
6. The spec self-review passes (no placeholders, no contradictions)
7. User approves the spec in review

v1 does NOT require:
- Matching the current dashboard number
- Matching `compass_net_backtest.py` output
- Replacing anything in the dashboard

Those are v1.1 (B) and v1.5 (dashboard) concerns.
