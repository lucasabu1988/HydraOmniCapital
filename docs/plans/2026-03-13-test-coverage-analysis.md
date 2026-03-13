# Test Coverage Analysis — 2026-03-13

## Current State

**Test execution**: 79 passing, 1 failing (`test_cleanup_old_files` in hydra_scratchpad)

### What IS Tested (~80 tests across 11 test files)

| Module | Test File | Tests | Coverage Quality |
|--------|-----------|-------|-----------------|
| `omnicapital_broker.py` | `test_ibkr_broker.py` | 53 | **Excellent** — mock mode, commissions, connections, orders, safety guards, reconciliation, audit |
| `hydra_tools.py` | `test_hydra_tools.py` | 11 | **Good** — tool format validation, executor dispatch, trade idempotency, daily limits |
| `hydra_scratchpad.py` | `test_hydra_scratchpad.py` | 9 | **Good** — daily files, entry format, tool call limits, phase resets, summarization |
| `hydra_prompts.py` | `test_hydra_prompts.py` | 6 | **Good** — phases, soul content, decision rules, per-phase instructions |
| `compass_overlays.py` | `test_overlays.py` | ~20 | **Good** — all 6 overlay signals + aggregation (needs pandas to run) |
| `compass/sp500_universe.py` | `test_sp500_universe.py` | 16 | **Good** — ticker normalization, caching, multi-source fetch (needs pandas) |
| `omnicapital_live.py` | `test_live_system.py` | 17 | **Partial** — scoring, volatility, leverage, regime detection. Misses execution loop |
| `src/signals/` | `test_signals.py` | ~26 | **Good** — momentum, MA, RSI, MACD, Bollinger, fundamentals (needs pandas) |
| `src/risk/` | `test_risk_management.py` | ~14 | **Good** — stops, sizing, trailing, sector exposure, rebalancing (needs pandas) |

### What is NOT Tested (0 tests)

**Priority 1 — Live System Critical Path**

1. **`compass_dashboard.py`** — Flask dashboard with 6+ API endpoints (`/api/state`, `/api/cycle-log`, `/api/equity`, `/api/annual-returns`, `/api/trade-analytics`, `/api/social-feed`). This is the primary interface for monitoring live trading. Zero route tests, zero response format validation.

2. **`omnicapital_live.py` execution loop** — `run_trading_day()`, `_apply_stops()`, `_rebalance_positions()`, `_update_cycle_log()`, `_ensure_active_cycle()` are all untested. These are the functions that actually open/close positions and manage the live portfolio. The existing tests only cover helper computations (scoring, regime detection).

3. **`compass_ml_learning.py`** — ML decision logging, learning aggregation, insights generation. The fail-safe wrappers that protect the live engine from ML crashes have zero tests verifying they actually catch exceptions.

4. **`omnicapital_data_feed.py`** — `YahooDataFeed` class (caching, rate limiting, error handling). Data feeds are the input to all trading decisions.

**Priority 2 — Operational Reliability**

5. **`compass_trade_analytics.py`** — Trade analytics (win rate, profit factor, drawdown analysis). Powers the `/api/trade-analytics` endpoint.

6. **`compass_fred_data.py`** — FRED economic data downloads used by overlays. If FRED fetching breaks, overlay signals go stale silently.

7. **`omnicapital_notifications.py`** — Email/alert notifications. No tests for formatting or delivery logic.

8. **`compass_dashboard_cloud.py`** — Cloud deployment variant. Should share test coverage with local dashboard.

**Priority 3 — src/ Module Layer**

9. **`src/core/engine.py`** — Core trading engine. Zero tests.
10. **`src/core/portfolio.py`** — Portfolio management. Zero tests.
11. **`src/data/data_provider.py`** — Data provider abstraction. Zero tests.
12. **`src/data/fundamental_provider.py`** — Fundamental data. Zero tests.
13. **`src/execution/executor.py`** — Trade execution. Zero tests.
14. **`src/strategies/`** — All 7 strategy modules (momentum, trend_following, mean_reversion, factor, risk_parity, consolidated, multi_strategy_engine). Zero tests.
15. **`src/signals/composite.py`** — Composite signal aggregation. Zero tests.

## Specific Gaps in Existing Tests

### 1. `omnicapital_live.py` — The Execution Gap
The existing `test_live_system.py` tests computation helpers but skips the actual trading loop:
- `run_trading_day()` — orchestrates an entire day of trading. Untested.
- `_apply_stops()` — fires adaptive stops on live positions. Untested.
- `_rebalance_positions()` — the core buy/sell logic. Untested.
- `_update_cycle_log()` — cycle rotation tracking. Untested.
- State persistence round-trip (save → load → verify consistency). Only 1 shallow test.

### 2. `hydra_agent.py` — Agent Loop
`test_hydra_agent.py` and `test_hydra_integration.py` exist but only test initialization and basic dispatch. The full agent loop (API call → tool use → decision → execution) is untested.

### 3. Integration Tests
No test exercises the full pipeline: data feed → signal generation → position selection → broker execution → state update → dashboard display. Each component is tested in isolation (where tested at all) but the integration seams are untested.

### 4. Error Recovery
No tests verify behavior under failure conditions:
- What happens when yfinance returns stale/empty data?
- What happens when broker rejects an order mid-cycle?
- What happens when state JSON is corrupted?
- What happens when ML hooks throw exceptions during `run_trading_day()`?

### 5. Existing Bug
`test_hydra_scratchpad.py::test_cleanup_old_files` is **FAILING** — the cleanup function doesn't actually delete old scratchpad files. This is a real bug.

## Recommendations

### Quick Wins (high value, low effort)

1. **Dashboard API smoke tests** — Use Flask's test client to verify each endpoint returns 200 and valid JSON. ~50 lines per endpoint. This protects against regressions in the primary monitoring interface.

2. **ML fail-safe tests** — Create a test that patches `compass_ml_learning` to raise exceptions, then verify `run_trading_day()` continues without crashing. Validates the most critical safety guarantee in the system.

3. **State round-trip tests** — Save state → corrupt a field → load → verify graceful handling. Protects against the "state corruption" failure mode listed in CLAUDE.md debugging section.

4. **Fix `test_cleanup_old_files`** — The failing test reveals a real bug in `hydra_scratchpad.py` cleanup logic.

### Medium Effort, High Impact

5. **Execution loop test with PaperBroker** — Mock data feed, wire up PaperBroker, run `run_trading_day()` for a simulated day. Verify positions opened/closed match expected signal output. This is the single highest-value test you could write.

6. **Data feed error handling** — Test `YahooDataFeed` with mocked HTTP responses: timeouts, empty responses, partial data, rate limit errors. Verify caching and fallback behavior.

7. **Notification formatting** — Test that trade alerts and portfolio summaries render correctly without actually sending emails.

### Strategic Improvements

8. **Integration test harness** — Build a test fixture that wires up the full pipeline (data feed → live engine → broker → state) with mocks at the boundary (HTTP, email). Run a multi-day simulation and verify end-to-end consistency.

9. **Property-based tests for signals** — Use Hypothesis to generate random price series and verify momentum/volatility calculations never produce NaN, Inf, or out-of-range values.

10. **Dashboard visual regression** — Playwright screenshots of the dashboard after state changes, compared against baselines. Catches CSS/template regressions.

## Coverage Estimate

| Area | Lines (est.) | Tested | Coverage |
|------|-------------|--------|----------|
| Broker (`omnicapital_broker.py`) | ~800 | ~700 | ~85% |
| HYDRA tools/scratchpad/prompts | ~600 | ~400 | ~65% |
| Overlays (`compass_overlays.py`) | ~500 | ~350 | ~70% |
| Signals (`src/signals/`) | ~400 | ~300 | ~75% |
| Risk (`src/risk/`) | ~300 | ~200 | ~65% |
| S&P 500 universe | ~300 | ~250 | ~80% |
| Live engine (`omnicapital_live.py`) | ~1200 | ~200 | **~15%** |
| Dashboard (`compass_dashboard.py`) | ~800 | 0 | **0%** |
| ML learning (`compass_ml_learning.py`) | ~400 | 0 | **0%** |
| Data feed (`omnicapital_data_feed.py`) | ~300 | 0 | **0%** |
| Trade analytics | ~200 | 0 | **0%** |
| Notifications | ~200 | 0 | **0%** |
| `src/core/`, `src/execution/`, `src/strategies/` | ~1500 | 0 | **0%** |
| **Total** | **~7500** | **~2400** | **~32%** |

The most dangerous gap is the live engine execution loop at ~15% coverage — this is the code that moves real money, and its core functions (`run_trading_day`, `_apply_stops`, `_rebalance_positions`) have zero tests.
