# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

# OmniCapital HYDRA — Project Guidelines

## Project Overview
Quantitative momentum trading system for S&P 500 large-caps. Live paper trading since Mar 6, 2026.
- **Algorithm**: HYDRA v8.4 (adaptive stops, bull override, sector limits, Rattlesnake + EFA + cash recycling)
- **Dashboard**: Flask @ localhost:5000 (`compass_dashboard.py`)
- **Live engine**: `omnicapital_live.py` (COMPASSLive class)
- **ML system**: `compass_ml_learning.py` (decision logging + progressive learning)
- **Cloud**: Render.com (`compass_dashboard_cloud.py` via gunicorn)

### Multi-Strategy System (HYDRA)
- **COMPASS v8.4** — S&P 500 cross-sectional momentum (primary strategy)
- **Rattlesnake v1.0** — Mean-reversion dip-buying
- **Catalyst** — Cross-asset trend (TLT/ZROZ/GLD/DBC above SMA200, 15% budget)
- **EFA** — International diversification
- **Cash Recycling** — COMPASS ↔ Rattlesnake capital flow (cap 75%)

### ML Learning System (3 phases)
- **Phase 1** (< 100 decisions): DecisionLogger logs every signal, entry, exit, skip
- **Phase 2** (100–500 decisions): FeatureStore builds feature vectors, OutcomeTracker resolves P&L
- **Phase 3** (> 500 decisions): LearningEngine trains models, InsightReporter surfaces parameter suggestions
- All ML code is fail-safe (try/except) — never crashes the live engine

## Critical Rules
- **ALGORITHM IS LOCKED** — 40 experiments, 36 failed. Do NOT modify signal logic in `omnicapital_v8_compass.py` or `omnicapital_v84_compass.py`
- **LEVERAGE_MAX = 1.0** — broker margin at 6% destroys value. Never enable leverage
- **Seed 666** — use whenever randomness is needed
- **No secrets in commits** — `.env`, `omnicapital_config.json` are gitignored
- **ML hooks are fail-safe** — all ML logging wrapped in try/except, never crash the live engine
- **State files are critical** — `state/compass_state_latest.json` is the source of truth for live positions

## Architecture
```
compass_dashboard.py    — Flask dashboard + live trading engine (main entry)
omnicapital_live.py     — COMPASSLive class (broker, signals, execution)
compass_ml_learning.py  — ML orchestrator (logging, learning, insights)
omnicapital_v84_compass.py — Backtest algorithm (v8.4 parameters)
static/js/dashboard.js  — Frontend JS (charts, cycle log, analytics)
static/css/dashboard.css — Dashboard styles
templates/dashboard.html — Dashboard HTML template
state/                  — Runtime state (JSON), cycle log, ML learning data
backtests/              — CSV results, backtest outputs
config/                 — Strategy YAML, broker config
compass/                — Python package (notifications, git_sync)
```

## Key Parameters (v8.4)
- Momentum: 90d lookback, 5d skip, 5d hold
- Positions: 5 (risk-on), adjustable by regime
- Adaptive stops: -6% to -15% (vol-scaled per position)
- Trailing: +5% / -3% (vol-scaled)
- Bull override: SPY > SMA200*103% & score>40% → +1 position
- Sector limit: max 3 per sector
- DD tiers: T1=-10%, T2=-20%, T3=-35%
- Crash brake: 5d=-6% or 10d=-10% → 15% leverage
- Exit renewal: max 10d, min profit 4%, momentum pctl 85%

## Coding Conventions
- **Language**: Python 3.14.2 (Windows 11)
- **Style**: PEP 8, snake_case functions/variables, UPPER_CASE constants
- **Logging**: `logging` module, logger per module (`logger = logging.getLogger(__name__)`)
- **Error handling**: try/except for external calls (broker, data feeds, ML hooks). Never crash the live engine
- **Imports**: stdlib → third-party → local. Optional imports with `_available` flag pattern
- **State persistence**: JSON files in `state/`. Always `json.dump` with indent=2
- **Data**: pandas DataFrames for time series, dicts for state/config
- **No type annotations** on existing code — don't add them unless writing new modules
- **No docstrings** on existing functions — don't add them retroactively
- **Commit style**: conventional commits (`feat:`, `fix:`, `refactor:`, `docs:`)

## Testing
```bash
pytest tests/ -v                          # Unit tests
pytest tests/ -v -k "test_name"           # Single test
pytest tests/ -v --cov-fail-under=50      # With coverage threshold (CI default)
python tests/validate_live_system.py      # System validation
python scripts/simulate_live_trading.py   # Offline simulation
```
- Tests use pytest. Mock broker with `PaperBroker` or `IBKRBroker(mock=True)`
- 53 IBKR unit tests (all passing)
- Test files: `tests/test_*.py`, `tests/validate_*.py`
- **CI**: GitHub Actions runs `pytest` with coverage on push/PR to `main` (min 50% coverage)
- Coverage modules: compass_api_models, compass_dashboard, compass_dashboard_cloud, compass_ml_learning, omnicapital_broker, omnicapital_live

## Dashboard API Endpoints
- `/api/state` — current positions, cash, regime
- `/api/cycle-log` — 5-day rotation cycles
- `/api/equity` — equity curve data
- `/api/annual-returns` — COMPASS vs SPY bar chart
- `/api/trade-analytics` — win rate, profit factor

## Deployment
- **Local**: `python compass_dashboard.py` → Flask on port 5000
- **Cloud**: `render.yaml` → gunicorn on Render.com (health check: `/api/health`)
- **Docker**: Python 3.11-slim, gunicorn on port 10000
- **compass/**: Python package only (notifications, git_sync) — no file syncing needed
- **Data sources**: yfinance (primary, cached in `data_cache/`), Tiingo (optional), FRED (cash yield)

## Git Workflow
- Branch: `main` (single branch)
- Remote: `origin` → GitHub (lucasabu1988/HydraOmniCapital)
- Commit messages: conventional commits, Co-Authored-By for AI
- Push after each logical change set

## Skills
- **hydra-ops**: Operations skill for HYDRA system — deploy, debug, troubleshoot. Located at `~/.claude/skills/hydra-ops/SKILL.md`

## Planning & Documentation
- Design docs: `docs/plans/YYYY-MM-DD-<topic>-design.md`
- Implementation plans: `docs/plans/YYYY-MM-DD-<topic>-implementation.md`
- Use brainstorming skill for new features before coding
- Use writing-plans skill after design is approved
- Project docs: `docs/` (deployment guide, implementation guide, manifesto)

## Debugging
**Log locations:**
- Live engine: `logs/compass_live_YYYYMMDD.log`
- State snapshots: `state/compass_state_YYYYMMDD.json`
- ML decisions: `state/ml_learning/decisions.jsonl`
- Broker audit: `logs/ibkr_audit_YYYYMMDD.json`

**Common issues and diagnosis:**
- **Dashboard 404**: check Flask routes in `compass_dashboard.py`, verify endpoint exists
- **Sector "Unknown"**: check `position_meta` in state JSON has `sector` field
- **Cycle log not updating**: check `_update_cycle_log()` and `_ensure_active_cycle()` in `omnicapital_live.py`
- **ML not logging**: verify `_ml_available` is True, check `compass_ml_learning.py` imports
- **State corruption**: compare `compass_state_latest.json` vs dated backup, check JSON validity
- **Data feed timeout**: yfinance rate limits — check `data_cache/` for stale cache
- **Stop not firing**: check `entry_vol`/`entry_daily_vol` in position_meta (adaptive stop depends on these)

**Debugging workflow:**
1. Check logs first (`logs/compass_live_*.log`)
2. Validate state JSON (`python -c "import json; json.load(open('state/compass_state_latest.json'))"`)
3. Use Playwright for visual dashboard issues
4. Never modify live state without backup

## Code Review Checklist
Before completing any code change:
1. **Syntax check**: `python -c "import py_compile; py_compile.compile('file.py')"`
2. **State validation**: if state JSON modified, verify valid JSON
3. **No sync needed**: compass/ is now a pure Python package
4. **Visual check**: if frontend changed, verify with Playwright screenshot
5. **No debug code**: remove any temporary `print()` or test code
6. **ML fail-safe**: any new ML hooks must be wrapped in try/except

## Post-Implementation Workflow
After finishing any implementation:
1. **Simplify** — review changed code for reuse, quality, and efficiency; fix issues found
2. **Run tests** — `pytest tests/ -v` (unit) + syntax check on modified files
3. **Verify end-to-end** — if dashboard changed, Playwright screenshot; if live engine changed, validate state JSON
4. **Commit** — conventional commit with clear message, push if requested

## Subagent & Fork Strategy
- **Fork (no subagent_type)** for open-ended research — inherits context, shares cache. Use for: "what's the state of X", audit questions, investigation
- **Subagent (with type)** for fresh-perspective tasks — starts clean. Use for: code review, independent analysis
- **Parallel forks** when research splits into independent questions (launch all in one message)
- **Never peek** at fork output mid-flight — wait for completion notification
- **Never fabricate** fork results — if user asks before fork returns, say "still running"
- **Brief subagents fully** — they have zero context, explain what/why/what's been tried

## Simplify Reviews (3-agent parallel)
When reviewing code changes, launch 3 parallel review agents:
1. **Code Reuse** — search for existing utilities that could replace new code; flag duplicated functionality
2. **Code Quality** — redundant state, parameter sprawl, copy-paste, leaky abstractions, stringly-typed code
3. **Efficiency** — unnecessary work, missed concurrency, hot-path bloat, recurring no-op updates, memory leaks, overly broad operations
Fix real issues, skip false positives without arguing.

## Verification Plans
For non-trivial changes, create structured verification plans:
- Store in `~/.claude/plans/<slug>.md`
- Include: metadata, files being verified, preconditions, setup steps, verification steps with expected outcomes, cleanup
- Execute steps in order, report PASS/FAIL for each
- Stop on first FAIL — don't round up "almost working" to PASS

## Hookify Rules (active)
- `protect-state-files` — warns before editing live state JSON
- `block-algorithm-modification` — blocks edits to locked algorithm files
- `protect-secrets` — blocks edits to .env/config with credentials
- `verify-before-complete` — pre-completion verification checklist

## Autonomous Operations Mode
When performing ops tasks (deploy, debug, troubleshoot):
1. **Execute immediately** — make reasonable assumptions, don't block on ambiguity
2. **Minimize interruptions** — only ask when genuinely cannot proceed (e.g., fundamentally different approaches)
3. **Prefer action over planning** — start doing, don't over-plan simple tasks
4. **Be thorough** — complete full task including tests and verification without stopping to ask

## Careful Action Protocol
- **Freely take**: local, reversible actions (edit files, run tests, read logs)
- **Confirm first**: destructive ops (delete files/branches, reset --hard, force-push), shared-state actions (push, PR comments, external messages)
- **Never shortcut**: don't bypass safety checks (--no-verify), don't delete unfamiliar state — investigate first
- **Measure twice**: resolve merge conflicts rather than discarding; investigate lock files rather than deleting
- **Scope-match**: authorization for one action doesn't extend to all similar actions

## User Preferences
- Language: Spanish prompts, English code/commits
- Always commit and push when asked — no confirmation needed
- Dashboard changes should be verified visually (Playwright screenshots)
- Keep cloud and local dashboards in sync

## Agent & Plugin Autonomy
Agents and plugins should act **proactively** without being explicitly invoked:
- **code-reviewer / coderabbit**: Auto-review after any significant code change
- **code-simplifier**: Auto-simplify after implementing features or fixes
- **pr-review-toolkit**: Auto-analyze PRs when created
- **hookify**: Enforce rules continuously
- **serena**: Use for semantic code navigation whenever exploring the codebase
- **playwright**: Auto-screenshot dashboard after frontend changes
- **verification-before-completion**: Always verify before claiming work is done
- **systematic-debugging**: Auto-engage when errors or test failures occur
- **brainstorming**: Auto-engage before any new feature or algorithm change

Agents should intervene freely based on context — do not wait for explicit user invocation. If a plugin or agent is relevant to the current task, use it.

## Anti-Patterns (avoid these)
- **No premature abstractions** — don't create helpers/utilities for one-time operations; 3 similar lines > premature abstraction
- **No hypothetical design** — don't design for future requirements that don't exist yet
- **No unnecessary error handling** — don't add fallbacks for impossible scenarios; trust internal code, only validate at boundaries (user input, broker API, data feeds)
- **No over-engineering** — only make changes directly requested or clearly necessary; a bug fix doesn't need surrounding cleanup
- **No compatibility hacks** — don't rename unused _vars, re-export dead types, or add "// removed" comments; if unused, delete completely
- **No feature flags** for internal changes — just change the code directly
