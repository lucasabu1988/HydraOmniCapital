# Codex Master Prompt — HYDRA Project

You are working on the HYDRA project, a quantitative momentum trading system. Read `AGENTS.md` first for full project context, architecture, and coding conventions.

## Your Mission

Execute **all 6 challenges** listed in `AGENTS.md`, one at a time, in order. For each challenge, create a **separate commit** on the `main` branch. Do NOT create feature branches — commit directly to `main`.

---

## Execution Protocol

For **each** challenge, follow these steps exactly:

### Step 1 — Read
Read the target file(s) listed in the challenge. Understand the existing code structure, imports, and patterns before writing anything.

### Step 2 — Implement
Write the fix or test file. Follow the project's coding conventions:
- PEP 8, snake_case, UPPER_CASE constants
- `logging` module (not print)
- `try/except` for external calls
- `import` order: stdlib > third-party > local
- No type annotations on existing code
- No docstrings on existing functions
- JSON writes: always `indent=2`

### Step 3 — Verify
Run these commands after each change:
```bash
# Syntax check on every modified .py file
python -c "import py_compile; py_compile.compile('filename.py')"

# Run ALL existing tests (nothing should break)
pytest tests/ -v

# For JSON fixes, also validate:
python -c "import json; json.load(open('state/ml_learning/insights.json'))"
```

### Step 4 — Commit
```bash
git add <specific-files-only>
git commit -m "<type>: <description>"
```
Use conventional commits: `fix:`, `test:`, `refactor:`. Never `git add .` — always add specific files.

---

## Challenge Details

### Challenge 1: Fix NaN Serialization (CRITICAL)

**What**: `float('nan')` is serialized as bare `NaN` in JSON — invalid per RFC 8259. Crashes `/api/ml-learning`.

**Where**:
- `compass_ml_learning.py` — find `InsightReporter.save_insights()` method
- `state/ml_learning/insights.json` line 102: `"avg_return_when_not_stopped": NaN`

**How**:
1. Create a helper function `_sanitize_for_json(obj)` that recursively walks dicts/lists and replaces `float('nan')`, `float('inf')`, `float('-inf')` with `None`.
2. In `InsightReporter.save_insights()`, call `_sanitize_for_json(report)` before `json.dump()`.
3. Also fix the existing corrupted file: read `insights.json` as text, replace `NaN` with `null`, write it back.
4. Search for ALL other `json.dump` / `json.dumps` calls in `compass_ml_learning.py` and apply the same sanitization.

**Verify**:
```bash
python -c "import json; json.load(open('state/ml_learning/insights.json'))"
python -c "import py_compile; py_compile.compile('compass_ml_learning.py')"
pytest tests/ -v
```

**Commit**: `fix: sanitize NaN/Inf in ML insights JSON serialization`

---

### Challenge 2: Test Suite for Cloud Dashboard (HIGH)

**What**: `compass_dashboard_cloud.py` (2,600+ lines) has zero tests.

**Where**: Create `tests/test_cloud_dashboard.py`

**How**:
1. Read `compass_dashboard_cloud.py` to understand Flask app structure and routes.
2. Use Flask test client (`app.test_client()`).
3. Mock all external dependencies: Yahoo Finance API calls, file I/O for state files, SEC/Reddit fetches.
4. Write 15+ test cases covering:

```python
import pytest
import json
from unittest.mock import patch, MagicMock
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

# Test categories:
# 1. /api/state — with state file present, with state file missing
# 2. /api/ml — returns valid JSON with expected structure
# 3. /api/cycle-log — returns array (empty or populated)
# 4. /api/equity — returns data or graceful empty
# 5. /api/trade-analytics — returns valid structure
# 6. /api/social-feed — mocked external calls
# 7. Price fetching — mock Yahoo responses, cache hits, cache misses, failure paths
# 8. Engine startup — _HAS_ENGINE=True vs False paths
# 9. Error paths — missing files, invalid JSON, network failures
```

5. Follow the pattern from existing test files (see `tests/test_ibkr_broker.py` for style reference).

**Verify**:
```bash
python -c "import py_compile; py_compile.compile('tests/test_cloud_dashboard.py')"
pytest tests/test_cloud_dashboard.py -v
pytest tests/ -v  # all tests still pass
```

**Commit**: `test: add cloud dashboard test suite (15+ cases)`

---

### Challenge 3: Test Suite for ML Learning System (HIGH)

**What**: `compass_ml_learning.py` has zero tests.

**Where**: Create `tests/test_ml_learning.py`

**How**:
1. Read `compass_ml_learning.py` fully — understand all classes: `DecisionLogger`, `FeatureStore`, `OutcomeTracker`, `InsightReporter`, `LearningEngine`.
2. Use `tmp_path` pytest fixture for isolated file I/O (don't touch real state files).
3. Write 15+ test cases:

```python
# Test categories:
# 1. DecisionLogger.log_entry() — writes valid JSONL line with expected fields
# 2. DecisionLogger.log_exit() — writes exit record
# 3. DecisionLogger.log_skip() — writes skip record
# 4. DecisionLogger.log_hold() — writes hold record
# 5. FeatureStore.build_entry_feature_matrix() — empty input returns empty DataFrame
# 6. FeatureStore.build_entry_feature_matrix() — populated input has expected columns
# 7. InsightReporter.save_insights() — output is valid JSON (no NaN)
# 8. InsightReporter.save_insights() — handles numpy NaN values gracefully
# 9. _classify_outcome() — win threshold boundary
# 10. _classify_outcome() — loss threshold boundary
# 11. _classify_outcome() — stopped_out classification
# 12. LearningEngine.run() — Phase 1 gate blocks with <63 days
# 13. LearningEngine.run() — handles empty decisions file
# 14. JSONL format — each line is valid JSON independently
# 15. Concurrent write safety — no partial lines in JSONL
```

**Verify**:
```bash
python -c "import py_compile; py_compile.compile('tests/test_ml_learning.py')"
pytest tests/test_ml_learning.py -v
pytest tests/ -v
```

**Commit**: `test: add ML learning system test suite (15+ cases)`

---

### Challenge 4: Yahoo Finance Thread Safety (HIGH)

**What**: `_yf_session` and `_yf_crumb` are module-level globals mutated without locking.

**Where**: `compass_dashboard_cloud.py` — search for `_yf_session`, `_yf_crumb`, `_yf_get_session`

**How**:
1. Add a new lock at module level: `_yf_session_lock = threading.Lock()`
2. Wrap ALL reads/writes of `_yf_session` and `_yf_crumb` with this lock.
3. In `_yf_get_session()`: acquire lock, check if session exists, create if not, return.
4. In the crumb reset path (where `_yf_crumb = None`): acquire lock before resetting.
5. Ensure this lock is SEPARATE from `_price_cache_lock` to avoid deadlocks.
6. Lock ordering rule: always acquire `_yf_session_lock` BEFORE `_price_cache_lock` if both needed.

**Verify**:
```bash
python -c "import py_compile; py_compile.compile('compass_dashboard_cloud.py')"
pytest tests/ -v
```

**Commit**: `fix: add thread safety lock for Yahoo Finance session/crumb globals`

---

### Challenge 5: Dashboard dd_leverage Display Bug (MEDIUM)

**What**: `dashboard.js` reads `p.dd_leverage` but API returns it under `recovery.dd_leverage`.

**Where**:
- `static/js/dashboard.js` — search for `dd_leverage`
- `compass_dashboard_cloud.py` — search for `dd_leverage` in `compute_portfolio_metrics()`
- `compass_dashboard.py` — same endpoint (keep local and cloud in sync)

**How**:
1. Read both dashboard files to understand how `dd_leverage` is returned in the API.
2. Read `dashboard.js` to see how it's consumed.
3. Choose ONE approach (prefer flattening in the API since JS expects flat):
   - Option A: In the API response, add `dd_leverage` at the top level of the portfolio dict.
   - Option B: In JS, read from `recovery.dd_leverage` instead.
4. Apply the same fix to BOTH `compass_dashboard_cloud.py` AND `compass_dashboard.py`.

**Verify**:
```bash
python -c "import py_compile; py_compile.compile('compass_dashboard_cloud.py')"
python -c "import py_compile; py_compile.compile('compass_dashboard.py')"
pytest tests/ -v
```

**Commit**: `fix: expose dd_leverage at top level in portfolio API response`

---

### Challenge 6: SPY Context in ML Skip/Hold Records (MEDIUM)

**What**: `log_skip()` and `log_hold()` hardcode `spy_price=None, spy_sma200=None`.

**Where**:
- `compass_ml_learning.py` — `log_skip()` and `log_hold()` methods
- `omnicapital_live.py` — find where `log_skip()` and `log_hold()` are CALLED

**How**:
1. In `compass_ml_learning.py`: add `spy_price`, `spy_sma200`, `spy_regime_score` parameters to `log_skip()` and `log_hold()` with default `None` (backward compatible).
2. In `omnicapital_live.py`: find the call sites for `log_skip()` and `log_hold()`. At those locations, the engine already has SPY data available (it computes regime scores). Pass the SPY data through.
3. Wrap all changes in `try/except` (ML fail-safe rule).
4. Do NOT modify existing records in `decisions.jsonl` — it's append-only.

**Verify**:
```bash
python -c "import py_compile; py_compile.compile('compass_ml_learning.py')"
python -c "import py_compile; py_compile.compile('omnicapital_live.py')"
pytest tests/ -v
```

**Commit**: `fix: pass SPY context to ML skip/hold decision records`

---

## Final Checklist

After all 6 challenges are done:

```bash
# Full test suite
pytest tests/ -v

# Validate state file
python -c "import json; json.load(open('state/compass_state_latest.json'))"

# Validate insights JSON
python -c "import json; json.load(open('state/ml_learning/insights.json'))"

# Syntax check all modified files
python -c "import py_compile; py_compile.compile('compass_ml_learning.py')"
python -c "import py_compile; py_compile.compile('compass_dashboard_cloud.py')"
python -c "import py_compile; py_compile.compile('compass_dashboard.py')"
python -c "import py_compile; py_compile.compile('omnicapital_live.py')"
python -c "import py_compile; py_compile.compile('tests/test_cloud_dashboard.py')"
python -c "import py_compile; py_compile.compile('tests/test_ml_learning.py')"

# Git log to confirm 6 commits
git log --oneline -6
```

## Files You Must NEVER Modify

- `omnicapital_v8_compass.py` — locked algorithm
- `omnicapital_v84_compass.py` — locked algorithm
- `.env` — secrets
- `omnicapital_config.json` — secrets
- `state/compass_state_latest.json` — live engine state (only fix `insights.json`)
- `state/ml_learning/decisions.jsonl` — append-only, never edit existing records

## When Stuck

- Read the existing test files in `tests/` for style patterns (especially `test_ibkr_broker.py`)
- Read `AGENTS.md` for architecture context
- Read `CLAUDE.md` for full project guidelines
- If a test import fails, check that `sys.path.insert(0, str(Path(__file__).parent.parent))` is at the top
- If `compass_dashboard_cloud.py` fails to import (heavy dependencies), mock the imports in tests
