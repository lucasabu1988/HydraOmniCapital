# AGENTS.md — OmniCapital HYDRA

This file provides context for AI coding agents (Codex, Claude, Gemini, etc.) working on this project.

## Project Summary

HYDRA is a quantitative momentum-based stock rotation system trading 40 US large-caps on 5-day cycles.
Live paper trading since March 6, 2026 with $100,000 initial capital. Deployed on Render.com (cloud)
and locally via Flask.

- **Core engine**: `omnicapital_live.py` — `COMPASSLive` class
- **Cloud dashboard**: `compass_dashboard_cloud.py` — Flask + gunicorn on Render
- **Local dashboard**: `compass_dashboard.py` — Flask on localhost:5000
- **ML system**: `compass_ml_learning.py` — decision logging + progressive learning
- **Algorithm**: `omnicapital_v84_compass.py` — **LOCKED, DO NOT MODIFY**
- **Broker**: `omnicapital_broker.py` — `PaperBroker` with Yahoo Finance price feed

## Critical Rules

1. **ALGORITHM IS LOCKED** — Do NOT modify signal logic in `omnicapital_v8_compass.py` or `omnicapital_v84_compass.py`. 40 experiments, 36 failed. The parameters are final.
2. **LEVERAGE_MAX = 1.0** — Never enable leverage. Broker margin at 6% destroys value.
3. **State files are sacred** — `state/compass_state_latest.json` is the source of truth. Always use atomic writes (`tmp + os.replace`). Never modify without backup.
4. **ML hooks are fail-safe** — All ML logging must be wrapped in `try/except`. Never crash the live engine.
5. **No secrets in commits** — `.env`, `omnicapital_config.json` are gitignored.
6. **Seed 666** — Use whenever randomness is needed.

## Architecture

```
compass_dashboard_cloud.py  — Cloud Flask app + engine runner (Render)
compass_dashboard.py        — Local Flask dashboard + engine runner
omnicapital_live.py         — COMPASSLive class (broker, signals, execution)
omnicapital_broker.py       — PaperBroker + YahooDataFeed
compass_ml_learning.py      — ML orchestrator (logging, learning, insights)
omnicapital_v84_compass.py  — Backtest algorithm (v8.4 parameters) [LOCKED]
static/js/dashboard.js      — Frontend JS (charts, cycle log, social feed)
static/css/dashboard.css    — Dashboard styles
templates/dashboard.html    — Dashboard HTML template (Spanish UI)
state/                      — Runtime state (JSON), cycle log, ML data
tests/                      — pytest tests (53 IBKR tests passing)
docs/                       — Design docs, plans, deployment guides
```

## Coding Conventions

- **Language**: Python 3.14.2 (Windows 11)
- **Style**: PEP 8, snake_case, UPPER_CASE constants
- **Logging**: `logging` module, logger per module
- **Error handling**: try/except for external calls (broker, data feeds, ML). Never crash the engine.
- **Imports**: stdlib > third-party > local. Optional imports with `_available` flag.
- **State**: JSON with indent=2 in `state/`. Atomic writes always.
- **Data**: pandas DataFrames for time series, dicts for state/config
- **No type annotations** on existing code
- **No docstrings** on existing functions
- **Commits**: conventional (`feat:`, `fix:`, `refactor:`, `docs:`)
- **Tests**: pytest, mock broker with `PaperBroker`

## API Endpoints

- `/api/state` — positions, cash, regime, portfolio metrics
- `/api/cycle-log` — 5-day rotation cycle history
- `/api/equity` — equity curve data
- `/api/annual-returns` — HYDRA vs SPY returns
- `/api/trade-analytics` — win rate, profit factor
- `/api/social-feed` — activity feed (SEC, Reddit, news)
- `/api/ml` — ML status, KPIs, interpretation
- `/api/ml-learning` — ML learning data and insights

## Key Parameters (v8.4 — DO NOT CHANGE)

- Momentum: 90d lookback, 5d skip, 5d hold
- Positions: 5 (risk-on), adjustable by regime
- Adaptive stops: -6% to -15% (vol-scaled)
- Trailing: +5% / -3% (vol-scaled)
- Bull override: SPY > SMA200*103% & score>40%
- Sector limit: max 3 per sector
- Crash brake: 5d=-6% or 10d=-10%

## Testing

```bash
pytest tests/ -v                          # Unit tests
python tests/validate_live_system.py      # System validation
python -c "import py_compile; py_compile.compile('file.py')"  # Syntax check
```

## Deployment

- **Cloud**: Push to `main` > GitHub webhook > Render auto-deploy
- **Local**: `python compass_dashboard.py`
- **Cloud URL**: https://omnicapital.onrender.com

## Existing Docs

- `docs/plans/2026-03-10-ibkr-live-readiness-audit.md` — 10 open issues for IBKR migration
- `docs/plans/2026-03-15-4th-pillar-implementation.md` — Catalyst pillar integration
- `docs/PROJECT_STATE.md` — Overall project status

---

# Assigned Challenges for Codex

The following are the most impactful technical challenges, ordered by priority.
Each has a clear scope, acceptance criteria, and relevant file pointers.

---

## Challenge 1: Fix NaN Serialization Bug (CRITICAL)

**Problem**: `float('nan')` from numpy is serialized as bare `NaN` in JSON, which is invalid per RFC 8259. This crashes Flask's `jsonify()` on the `/api/ml-learning` endpoint, causing 500 errors.

**Files**:
- `compass_ml_learning.py` — `InsightReporter.save_insights()` (~line 1456)
- `state/ml_learning/insights.json` — contains `"avg_return_when_not_stopped": NaN`

**Fix**: Sanitize all float values before JSON serialization. Replace `NaN`/`Inf` with `null` (None). Apply both to the writer (prevent future NaN writes) and add a reader-side fix (handle existing corrupted files).

**Acceptance**:
- `insights.json` contains no bare `NaN` or `Inf` tokens
- `/api/ml-learning` returns valid JSON (200, not 500)
- `python -c "import json; json.load(open('state/ml_learning/insights.json'))"` succeeds
- All existing tests still pass

---

## Challenge 2: Test Suite for Cloud Dashboard (HIGH)

**Problem**: `compass_dashboard_cloud.py` (2,600+ lines) has zero tests. No coverage for Flask routes, API response structure, Yahoo Finance session management, engine startup, or error paths.

**Files**:
- `compass_dashboard_cloud.py` — the module to test
- `tests/` — add new test file `tests/test_cloud_dashboard.py`

**Scope**: Write tests for the critical API endpoints:
- `/api/state` — returns valid JSON with expected fields when state file exists/missing
- `/api/ml` — returns valid JSON with KPIs
- `/api/cycle-log` — returns array
- `/api/equity` — returns data or empty gracefully
- Price fetching: mock Yahoo Finance responses, test cache behavior, test failure paths
- Engine startup: test lock file acquisition, test `_HAS_ENGINE=False` path

**Acceptance**:
- New test file `tests/test_cloud_dashboard.py` with 15+ test cases
- Tests pass with `pytest tests/test_cloud_dashboard.py -v`
- Uses Flask test client, mocks external calls (Yahoo, SEC, Reddit)
- No new dependencies required

---

## Challenge 3: Test Suite for ML Learning System (HIGH)

**Problem**: `compass_ml_learning.py` has zero tests. The entire learning pipeline (decision logging, feature extraction, insight generation, Phase 1/2/3 progression) is untested.

**Files**:
- `compass_ml_learning.py` — the module to test
- `tests/` — add new test file `tests/test_ml_learning.py`

**Scope**:
- `DecisionLogger`: test `log_entry()`, `log_exit()`, `log_skip()`, `log_hold()` — verify JSONL output format
- `FeatureStore`: test `build_entry_feature_matrix()` with empty/populated data
- `InsightReporter`: test `save_insights()` produces valid JSON (no NaN)
- `_classify_outcome`: test boundary conditions (win/loss/stopped thresholds)
- `LearningEngine.run()`: test Phase 1 gate (needs 63 days minimum)

**Acceptance**:
- New test file `tests/test_ml_learning.py` with 15+ test cases
- Tests pass with `pytest tests/test_ml_learning.py -v`
- Covers NaN edge cases, empty data, and normal operation
- No new dependencies

---

## Challenge 4: Yahoo Finance Thread Safety (HIGH)

**Problem**: `_yf_session` and `_yf_crumb` are module-level globals mutated without locking. Under gunicorn with threads, concurrent requests can corrupt the session mid-request.

**Files**:
- `compass_dashboard_cloud.py` — `_yf_get_session()` (~line 220), `_yf_crumb` reset (~line 277)

**Fix**: Protect `_yf_session` and `_yf_crumb` with a dedicated `threading.Lock()` (separate from `_price_cache_lock`). Ensure the crumb reset path is atomic.

**Acceptance**:
- `_yf_session` and `_yf_crumb` access is lock-protected
- No deadlocks with existing `_price_cache_lock`
- Syntax check passes
- Existing tests still pass

---

## Challenge 5: Dashboard `dd_leverage` Display Bug (MEDIUM)

**Problem**: `dashboard.js` line ~123 reads `p.dd_leverage` but the API returns it nested under `recovery.dd_leverage`. The "DD SCALING" pill never shows the actual leverage percentage.

**Files**:
- `static/js/dashboard.js` — position card rendering (~line 123)
- `compass_dashboard_cloud.py` — `compute_portfolio_metrics()` (~line 647)

**Fix**: Either flatten `dd_leverage` to the top level in the API response, or update the JS to read from the correct nested path. Choose the approach that's most consistent with how other fields are accessed.

**Acceptance**:
- DD SCALING pill shows actual leverage % when drawdown tiers are active
- No regression in position card rendering
- Both cloud and local dashboards updated consistently

---

## Challenge 6: SPY Context in ML Skip/Hold Records (MEDIUM)

**Problem**: `log_skip()` and `log_hold()` hardcode `spy_price=None, spy_sma200=None`, creating systematic missing data in ~40% of ML decision records.

**Files**:
- `compass_ml_learning.py` — `log_skip()` (~line 571), `log_hold()` (~line 620)
- `omnicapital_live.py` — caller sites where skip/hold decisions are logged

**Fix**: Pass SPY context (price, SMA200, regime score) to `log_skip()` and `log_hold()` at the call sites, similar to how `log_entry()` receives them.

**Acceptance**:
- New skip/hold records in `decisions.jsonl` have populated SPY fields
- Existing records are not modified (append-only log)
- ML fail-safe: all changes wrapped in try/except
- Existing tests pass

---

## Challenge 7: Engine Lifecycle Robustness & Health Monitoring (HIGH)

**Problem**: The cloud engine thread (`_run_cloud_engine`) dies silently and the dashboard serves stale data indefinitely. The recent fix in `_ensure_cloud_engine()` adds thread-alive checks and stale lock recovery, but the system still lacks:
1. **No health endpoint** — there's no way to externally verify if the engine is alive and processing cycles
2. **No alerting** — nobody knows the engine died until someone manually checks the dashboard
3. **Silent data staleness** — the dashboard happily serves hours/days-old prices with no visible warning
4. **No engine death logging** — when the `while True` loop in `_run_cloud_engine` catches an exception and sleeps 5 min, it logs locally but this is lost on Render free tier (logs rotate fast)
5. **Race condition on lock reclaim** — two workers could simultaneously detect a stale lock and both try to reclaim it

**Files**:
- `compass_dashboard_cloud.py` — `_ensure_cloud_engine()` (~line 3671), `_run_cloud_engine()` (~line 3596), `_engine_status` dict (~line 3510)
- `tests/test_cloud_dashboard.py` — add tests for engine lifecycle (if Challenge 2 completed, extend; otherwise create)

**Scope**:

### 7a. Health check endpoint
Add `GET /api/health` that returns:
```json
{
  "status": "healthy" | "degraded" | "down",
  "engine_alive": true/false,
  "last_price_update": "ISO timestamp",
  "price_age_seconds": 45,
  "last_cycle_close": "ISO timestamp",
  "uptime_seconds": 12345,
  "positions_count": 6,
  "portfolio_value": 100069
}
```
- `healthy`: engine alive + prices < 5 min old
- `degraded`: engine alive but prices > 5 min old, OR engine dead but market closed
- `down`: engine dead during market hours

### 7b. Stale data warning in API responses
Add a `_data_freshness` field to `/api/state` response:
```json
{
  "_data_freshness": {
    "status": "live" | "stale" | "offline",
    "price_age_seconds": 45,
    "engine_alive": true
  }
}
```
The frontend (`dashboard.js`) should show a visible warning banner when `status != "live"`.

### 7c. Engine death counter and crash history
Track in `_engine_status`:
- `crash_count`: number of times the engine crashed and restarted
- `last_crash_at`: ISO timestamp of last crash
- `last_crash_error`: string of last exception
- `restarts`: list of last 5 restart timestamps

Expose this in `/api/health` so we can see if the engine is crash-looping.

### 7d. Lock file race condition fix
The current lock reclaim in `_ensure_cloud_engine()` has a TOCTOU race: two workers read the PID, both see it dead, both try to unlink+recreate. Fix with a retry loop or use `fcntl.flock()` (Linux) as a secondary lock during reclaim.

### 7e. Tests
Write tests for:
- Engine thread dies → next request restarts it
- Stale lock file with dead PID → reclaimed successfully
- `/api/health` returns correct status for each scenario
- `_data_freshness` reflects actual data age

**Acceptance**:
- `GET /api/health` returns correct status based on engine state
- `/api/state` includes `_data_freshness`
- Dashboard shows visible warning when data is stale (>5 min old prices or engine dead)
- Engine crash history is tracked and exposed
- Lock reclaim is race-safe
- All tests pass: `pytest tests/ -v`
- Syntax check passes on all modified files

---

## Task Board

**Check `TASKBOARD.md` first.** It contains the live task queue managed by Claude. Tasks there take priority over the challenges below. Pick up any task marked `[ ] Open` and `Assigned: Codex`.

When you complete a task:
1. Mark it `[x]` in TASKBOARD.md
2. Add the commit hash in the Completed section
3. Move to the next open task

## How to Work

1. **One challenge per commit** — keep changes focused and reviewable
2. **Read the file first** — understand context before modifying
3. **You can modify production code** — fix bugs, add observability, improve robustness. You have earned this trust.
4. **Run syntax check** after changes: `python -c "import py_compile; py_compile.compile('filename.py')"`
5. **Run existing tests**: `pytest tests/ -v` — nothing should break
6. **Before committing**: run `git diff --stat` to confirm all changed files are intentional
7. **Conventional commits**: `fix:`, `test:`, `feat:`, `refactor:`
8. **Hard locks — NEVER modify**:
   - `omnicapital_v8_compass.py`, `omnicapital_v84_compass.py` — algorithm is LOCKED
   - `.env`, `omnicapital_config.json` — secrets
   - `state/compass_state_latest.json` — live engine state
   - `state/ml_learning/decisions.jsonl` — append-only log
9. **Soft rules**:
   - ML hooks must be fail-safe (try/except, never crash the engine)
   - No dead code — if a feature requires a method that doesn't exist on the current data feed, don't ship it
   - No hypothetical design — solve real problems, not future ones
   - Atomic writes for state files (tmp + os.replace)
