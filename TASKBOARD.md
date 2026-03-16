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
**Status:** [ ] Open
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
**Status:** [ ] Open
**Assigned:** Codex

The live state has `peak_value: 120000` (should be ~100000) and the cloud has `trading_day_counter: 8` (should be 1). The peak_value guard caps at >120% on early days, but the current peak is EXACTLY 120% so it slips through with `>` (we just changed from `>=`).

**Where:** `state/compass_state_latest.json`

**How:**
1. Set `peak_value` to match `portfolio_value` (approximately 100000)
2. Confirm `trading_day_counter` is 1 in the local state file
3. These values will sync to cloud via git

**Commit:** `fix: correct peak_value and trading_day_counter in live state`

---

### TASK-003: Multi-strategy coexistence test [PRIORITY: MEDIUM]
**Status:** [ ] Open
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
**Status:** [ ] Open
**Assigned:** Codex

Create `tests/test_restart_resilience.py`:
1. Engine with 3 positions, day 3, _daily_open_done=True
2. save_state() → new engine → load_state()
3. Assert all state preserved, run_once() does NOT re-execute daily_open

**Commit:** `test: add restart resilience test`

---

### TASK-005: Adaptive stop parametrized tests [PRIORITY: MEDIUM]
**Status:** [ ] Open
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
**Status:** [ ] Open
**Assigned:** Codex

Test response shapes for `/api/state`, `/api/cycle-log`, `/api/risk`, `/api/montecarlo`, `/api/health`.
Verify required keys exist and types are correct.

**Commit:** `test: add API contract tests for dashboard endpoints`

---

## Completed

_No completed tasks yet._

---

## Review Notes (Claude)

_Claude writes review findings here after checking completed work._
