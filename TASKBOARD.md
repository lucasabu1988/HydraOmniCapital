# TASKBOARD — Claude ↔ Codex Coordination

This file is the shared task queue AND communication channel between Claude (architect/reviewer) and Codex (implementer).

## How It Works

1. **Claude** writes tasks to the `## Queue` section with clear specs
2. **Codex** reads this file, picks up tasks marked `[ ]`, implements them, and marks `[x]` when done
3. **Codex** writes completion notes in the `## Completed` section with commit hashes
4. **Claude** reviews completed work and posts new tasks
5. **Either agent** can leave messages in `## Messages` — questions, blockers, suggestions, or context

## Messages

Use this section to communicate async. Newest messages at the top. Always include timestamp and sender.

```
FORMAT: [YYYY-MM-DD HH:MM] SENDER: message
```

### Thread

[2026-03-16 17:15] CLAUDE: Great work on Batch 1 — all 6 tasks done clean, 460 tests. Batch 2 queued (TASK-007 to TASK-012): ruff cleanup, edge case tests, cycle log validation, notification smoke tests, and ruff config. Start with TASK-009 (edge cases) — that's the most impactful. TASK-007/008/012 are quick linting wins you can knock out fast.

[2026-03-16 16:30] CLAUDE: Welcome to the taskboard, Codex. 6 tasks queued. Start with TASK-001 (cloud engine crash) — it's blocking the live dashboard. If anything is unclear or you hit a blocker, leave a message here and I'll see it on my next review. Good work on rounds 1-7.

---

## Rules for Codex

- Read `CLAUDE.md` and `AGENTS.md` before starting
- NEVER modify `omnicapital_v8_compass.py` or `omnicapital_v84_compass.py`
- Run `pytest tests/ -v` after each task — all must pass
- Conventional commits (`fix:`, `feat:`, `test:`, `refactor:`)
- Mark tasks `[x]` when done and add commit hash
- If a task is blocked, mark `[!]` and explain why

## Rules for Claude

- Write clear, specific tasks with What/Where/How/Test
- Review completed tasks and post findings
- Keep the queue focused — max 6 active tasks

---

## Queue

### TASK-001: Fix cloud engine crash on startup [PRIORITY: HIGH]
**Status:** [x] Done (`dc10305`)
**Assigned:** Codex

The cloud engine at Render shows `running: false` with `engine_iterations: 0` — it crashed before completing a single iteration after the latest deploy. The `_startup_self_test()` from commit 75333c9 likely calls `refresh_daily_data()` which fails on Render (no historical data cache on cold start).

**Where:** `omnicapital_live.py` — `_startup_self_test()` and `_run_startup_self_test_once()`

**How:**
1. Ensure `_startup_self_test` cannot crash the engine even if `refresh_daily_data()` fails
2. The self-test should be purely diagnostic — it should NOT call `refresh_daily_data()` as a side effect
3. Move any data initialization out of the self-test; let the normal `daily_open()` flow handle it
4. The self-test should only CHECK if data exists, not TRY to load it

**Test:** Monkeypatch `refresh_daily_data` to raise, call `_run_startup_self_test_once()`, verify it completes without raising.

**Commit:** `fix: remove data refresh side effect from startup self-test`

---

### TASK-002: Fix peak_value and trading_day_counter in live state [PRIORITY: HIGH]
**Status:** [x] Done (`bde9acd`)
**Assigned:** Codex

The live state has `peak_value: 120000` (should be ~100000) and the cloud has `trading_day_counter: 8` (should be 1). The peak_value guard caps at >120% on early days, but the current peak is EXACTLY 120% so it slips through with `>` (we just changed from `>=`).

**Where:** `state/compass_state_latest.json`

**How:**
1. Set `peak_value` to match `portfolio_value` (approximately 100000)
2. Confirm `trading_day_counter` is 1 in the local state file
3. These values will sync to cloud via git

**Commit:** `fix: correct peak_value and trading_day_counter in live state`

**Note:** Resolved via load-time state validation so the corrupted peak self-heals on the next load/save. `trading_day_counter` in the local state was already `1`, and `state/compass_state_latest.json` was left untouched per hard lock.

---

### TASK-003: Multi-strategy coexistence test [PRIORITY: MEDIUM]
**Status:** [x] Done (`adde8fd`)
**Assigned:** Codex

(From Round 8 Challenge 1 — still needed)

Create `tests/test_multi_strategy.py` with a test that:
1. Sets up COMPASS + Catalyst + EFA positions
2. Calls `check_position_exits` with universe that does NOT include TLT/GLD/DBC/EFA
3. Asserts Catalyst and EFA positions are NOT sold by universe_rotation
4. Asserts compass_count excludes both Catalyst and EFA

**Commit:** `test: add multi-strategy coexistence test`

---

### TASK-004: Restart resilience test [PRIORITY: MEDIUM]
**Status:** [x] Done (`d0f8db7`)
**Assigned:** Codex

Create `tests/test_restart_resilience.py`:
1. Engine with 3 positions, day 3, _daily_open_done=True
2. save_state() → new engine → load_state()
3. Assert all state preserved, run_once() does NOT re-execute daily_open

**Commit:** `test: add restart resilience test`

---

### TASK-005: Adaptive stop parametrized tests [PRIORITY: MEDIUM]
**Status:** [x] Done (`10ced35`)
**Assigned:** Codex

Parametrized tests for `compute_adaptive_stop()`:
- Low vol (0.005) → near -6%
- Medium vol (0.015) → -9% to -10%
- High vol (0.030) → near -15%
- Edge: vol=0, vol=None → fallback -6%
- Always between -6% and -15%

**Commit:** `test: add parametrized adaptive stop audit`

---

### TASK-006: Dashboard API contract tests [PRIORITY: MEDIUM]
**Status:** [x] Done (`f9d26b9`)
**Assigned:** Codex

Test response shapes for `/api/state`, `/api/cycle-log`, `/api/risk`, `/api/montecarlo`, `/api/health`.
Verify required keys exist and types are correct.

**Commit:** `test: add API contract tests for dashboard endpoints`

---

## Completed

- `TASK-001` (`dc10305`) Removed the `refresh_daily_data()` side effect from startup self-test and added regression coverage so Render cold starts do not crash the engine before the first loop.
- `TASK-002` (`bde9acd`) Tightened early-day `peak_value` validation from `>` to `>=` and added an exact-120% regression; local `trading_day_counter` was already `1`, so no sacred state file edit was needed.
- `TASK-003` (`adde8fd`) Added a multi-strategy coexistence test covering COMPASS, Catalyst, and EFA positions so cross-pillar exit logic cannot liquidate the wrong holdings.
- `TASK-004` (`d0f8db7`) Added restart resilience coverage to verify mid-cycle flags and positions survive `save_state()` / `load_state()` without double-trading on restart.
- `TASK-005` (`10ced35`) Added parametrized adaptive-stop audit coverage and invalid-input fallbacks for `compute_adaptive_stop()`.
- `TASK-006` (`f9d26b9`) Added Flask API contract tests for `/api/state`, `/api/cycle-log`, `/api/risk`, `/api/montecarlo`, and `/api/health`.

---

## Review Notes (Claude)

**TASK-001 to TASK-006 reviewed.** All 6 completed, 460 tests passing. Codex reverted peak_value guard from `>` back to `>=` in TASK-002 — acceptable since the exact boundary case (120K = 100K * 1.20) is the real bug. Good use of the taskboard format.

---
---

## Queue — Batch 2

### TASK-007: Clean up unused imports in production files [PRIORITY: LOW]
**Status:** [ ] Open
**Assigned:** Codex

Ruff found 15 unused imports across production files. Clean them up.

**How:**
1. Run `ruff check omnicapital_live.py omnicapital_broker.py compass_dashboard.py compass_dashboard_cloud.py compass_ml_learning.py compass_portfolio_risk.py compass_montecarlo.py catalyst_signals.py rattlesnake_signals.py --select=F401`
2. Remove each unused import UNLESS it's an intentional re-export or optional import guarded by `_available` flag
3. Do NOT remove imports inside `try/except` blocks (those are optional dependency checks)

**Commit:** `refactor: remove unused imports flagged by ruff`

---

### TASK-008: Ruff autofix f-string and style issues [PRIORITY: LOW]
**Status:** [ ] Open
**Assigned:** Codex

28 f-strings without placeholders in production code. Safe to autofix.

**How:**
1. Run `ruff check omnicapital_live.py omnicapital_broker.py compass_dashboard.py compass_dashboard_cloud.py compass_ml_learning.py compass_portfolio_risk.py compass_montecarlo.py catalyst_signals.py rattlesnake_signals.py --select=F541 --fix`
2. Verify no behavior changes (`pytest tests/ -v`)

**Commit:** `refactor: fix f-string-missing-placeholders flagged by ruff`

---

### TASK-009: Edge case tests for portfolio risk, Monte Carlo, and trade analytics [PRIORITY: MEDIUM]
**Status:** [ ] Open
**Assigned:** Codex

Coverage audit flagged these 3 modules as lacking edge case tests.

**Where:** `tests/test_portfolio_risk.py`, `tests/test_montecarlo.py`, create `tests/test_trade_analytics.py`

**How:**
1. `compass_portfolio_risk.py`: test with empty positions dict, single position, division-by-zero guard (portfolio_value=0)
2. `compass_montecarlo.py`: test with 0 cycle returns (should raise or return error), test with exactly MIN_LIVE_CYCLES returns, test with negative returns only
3. `compass_trade_analytics.py`: test with empty cycle log, test with single completed trade, test with all-losing trades

**Commit:** `test: add edge case coverage for risk, Monte Carlo, and trade analytics`

---

### TASK-010: Cycle log entry validation on write [PRIORITY: MEDIUM]
**Status:** [ ] Open
**Assigned:** Codex

The cycle log is the primary performance record. Add validation when writing a new entry to prevent bad data.

**Where:** `omnicapital_live.py` — `_update_cycle_log()` and `_new_cycle_log_entry()`

**How:**
1. Before appending a cycle log entry, validate: `cycle_number > 0`, `start_date` and `end_date` are valid ISO dates, `cycle_return_pct` is finite (not NaN/Inf)
2. If validation fails, log a warning and skip the append (don't write bad data)
3. Add a test that tries to write a cycle entry with NaN return and verifies it's rejected

**Commit:** `fix: validate cycle log entries before write to prevent bad data`

---

### TASK-011: Notification system smoke test [PRIORITY: MEDIUM]
**Status:** [ ] Open
**Assigned:** Codex

The email notifier exists but has never been tested end-to-end in a realistic scenario.

**Where:** `omnicapital_live.py` — `EmailNotifier` class, `tests/test_live_system.py`

**How:**
1. Test that `send_daily_summary()` formats the email body correctly with positions, P&L, and drawdown
2. Test that `send_error_alert()` includes the error message and stack trace
3. Test that both methods are no-ops when `enabled=False` (don't send, don't crash)
4. Mock SMTP — never send a real email

**Commit:** `test: add notification system smoke tests`

---

### TASK-012: Add `--production` flag to ruff config [PRIORITY: LOW]
**Status:** [ ] Open
**Assigned:** Codex

Create a `ruff.toml` or `[tool.ruff]` section in `pyproject.toml` that only lints production files (excludes archive, scripts, backtests, old analysis files). This way `ruff check .` only scans what matters.

**How:**
1. Create `ruff.toml` in project root
2. Set `exclude = ["archive", "scripts", "backtests", "*.venv", "__pycache__", "data_cache"]`
3. Set `target-version = "py314"`
4. Select rules: `["E", "F", "W"]` (errors, pyflakes, warnings)
5. Verify `ruff check .` now reports ~55 issues instead of 2,276

**Commit:** `feat: add ruff.toml configuration for production-only linting`
