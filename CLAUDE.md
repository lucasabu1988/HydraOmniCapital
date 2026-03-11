# OmniCapital HYDRA — Project Guidelines

## Project Overview
Quantitative momentum trading system for S&P 500 large-caps. Live paper trading since Mar 6, 2026.
- **Algorithm**: HYDRA v8.4 (adaptive stops, bull override, sector limits, Rattlesnake + EFA + cash recycling)
- **Dashboard**: Flask @ localhost:5000 (`compass_dashboard.py`)
- **Live engine**: `omnicapital_live.py` (COMPASSLive class)
- **ML system**: `compass_ml_learning.py` (decision logging + progressive learning)
- **Cloud**: Render.com (`compass_dashboard_cloud.py` via gunicorn)

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
static/js/dashboard.js  — Frontend JS (charts, cycle log, social feed)
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
python tests/validate_live_system.py      # System validation
python scripts/simulate_live_trading.py   # Offline simulation
```
- Tests use pytest. Mock broker with `PaperBroker` or `IBKRBroker(mock=True)`
- 53 IBKR unit tests (all passing)
- Test files: `tests/test_*.py`, `tests/validate_*.py`

## Dashboard API Endpoints
- `/api/state` — current positions, cash, regime
- `/api/cycle-log` — 5-day rotation cycles
- `/api/equity` — equity curve data
- `/api/annual-returns` — COMPASS vs SPY bar chart
- `/api/trade-analytics` — win rate, profit factor
- `/api/social-feed` — activity feed

## Deployment
- **Local**: `python compass_dashboard.py` → Flask on port 5000
- **Cloud**: `render.yaml` → gunicorn on Render.com
- **compass/**: Python package only (notifications, git_sync) — no file syncing needed

## Git Workflow
- Branch: `main` (single branch)
- Remote: `origin` → GitHub (lucasabu1988/NuevoProyecto)
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

## Hookify Rules (active)
- `protect-state-files` — warns before editing live state JSON
- `block-algorithm-modification` — blocks edits to locked algorithm files
- `protect-secrets` — blocks edits to .env/config with credentials
- `verify-before-complete` — pre-completion verification checklist

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
