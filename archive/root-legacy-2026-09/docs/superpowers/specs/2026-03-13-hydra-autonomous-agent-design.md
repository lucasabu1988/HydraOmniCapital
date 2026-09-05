# HYDRA Autonomous Agent — Design Spec

## Overview

An autonomous Claude-powered trading agent that wraps the existing COMPASS/HYDRA momentum system. Runs as a Render Worker service (cloud, independent of local PC). Uses the Anthropic API to reason about each trading decision with contextual intelligence (earnings calendar, insider trades, market data via MCP) while keeping the momentum signal algorithm LOCKED.

**Broker:** PaperBroker (paper trading) initially. IBKR live after 3-6 months of validation.

## Architecture

```
┌─────────────────────── Render.com ───────────────────────┐
│                                                           │
│  ┌─────────────────┐     ┌──────────────────────────┐    │
│  │ Web Service      │     │ Worker Service            │    │
│  │ (dashboard cloud)│◄───►│ (HYDRA Agent)             │    │
│  │ gunicorn + Flask │disk │ hydra_agent.py            │    │
│  │ port 10000       │     │                            │    │
│  └─────────────────┘     │  Claude API (Anthropic)    │    │
│                           │  ├─ Tools (15 total)       │    │
│                           │  ├─ Scratchpad (JSONL)     │    │
│                           │  └─ SOUL.md (philosophy)   │    │
│                           └──────────────────────────┘    │
│                                       │                    │
│                              ┌────────▼────────┐          │
│                              │ Persistent Disk  │          │
│                              │ state/*.json     │          │
│                              │ scratchpad/*.jsonl│          │
│                              └─────────────────┘          │
└───────────────────────────────────────────────────────────┘
```

### Components

1. **`hydra_agent.py`** — Main process. Scheduling loop + Claude API integration
2. **`hydra_tools.py`** — Tool definitions (trading core, market intel, operations)
3. **`hydra_soul.md`** — Agent philosophy injected into system prompt
4. **`hydra_prompts.py`** — System prompt builder per phase (pre-market, intraday, pre-close, post-close)
5. **`hydra_scratchpad.py`** — Append-only JSONL decision logging with tool call limits

### State Ownership (CRITICAL)

**The Worker is the SOLE writer of state files.** The cloud dashboard becomes read-only (showcase mode) when the Worker is present. The existing `_run_cloud_engine()` thread in `compass_dashboard_cloud.py` must be disabled — otherwise two processes write `compass_state_latest.json` concurrently, causing lost updates.

Worker and dashboard share a Render persistent disk mounted at `/data/state`:
- `compass_state_latest.json` — portfolio state. **Written ONLY by Worker.**
- `cycle_log.json` — 5-day rotation cycles. **Written ONLY by Worker.**
- `agent_scratchpad/YYYY-MM-DD.jsonl` — daily decision log. **Written ONLY by Worker.**

Dashboard reads all files and exposes via API endpoints. New endpoint: `/api/agent/scratchpad`.

**Implementation:** `compass_dashboard_cloud.py` checks for env var `AGENT_MODE=true`. When set, the cloud engine thread is not started. The dashboard serves only as a read-only viewer.

## Agent Loop — Daily Timeline (ET)

### Phase 1: Pre-Market Briefing (06:00 ET)

Claude API call with phase=PRE_MARKET_BRIEFING:
- Read portfolio state (positions, cash, regime)
- Validate data feeds (yfinance responding, SPY price fresh)
- Check earnings calendar for held positions (next 48h)
- Check earnings calendar for top-10 momentum candidates
- Query insider trades for held positions (MCP)
- Log briefing to scratchpad
- Send WhatsApp notification with daily summary

### Phase 2: Intraday Monitor (09:30-15:25 ET, every 15 min)

Pure Python checks (NO Claude API call unless anomaly):
- Check adaptive stops for each position
- Check crash velocity (5d return < -6% or 10d return < -10%)
- Validate data feed freshness

**Escalate to Claude only if:**
- A stop is triggered → execute IMMEDIATELY (non-negotiable), then Claude logs reasoning post-hoc and notifies human
- Crash velocity alert → Claude evaluates severity and decides: reduce positions or halt entries
- Data feed failure → Claude decides: pause trading or use stale data

**Stops are automatic.** Claude has ZERO discretion on whether to execute a stop. The Python code executes the exit, then calls Claude to log the event, assess impact, and notify. This prevents the agent from rationalizing delayed exits.

### Phase 3: Pre-Close Decision (15:25 ET)

Claude API call with phase=PRE_CLOSE_DECISION. This is the main decision point:

1. Compute momentum signals (existing `compute_momentum_scores()`)
2. Identify exits: hold-expired positions (5+ days)
3. Identify entries: top-ranked candidates to fill empty slots
4. Claude evaluates each candidate:
   - Earnings within 24h? → SKIP, take next
   - Massive insider selling (>$10M in 7d)? → SKIP, take next
   - Sector limit (3 per sector) hit? → SKIP, take next
   - Data validation failure for ticker? → SKIP, take next
5. Execute trades in MOC window (15:30-15:50 ET)
6. Log every decision (action + reasoning) to scratchpad
7. Save state

### Phase 4: Post-Close Summary (16:05 ET)

Claude API call with phase=POST_CLOSE_SUMMARY:
- Read today's scratchpad
- Calculate daily P&L
- Update cycle log
- Generate summary notification
- Send WhatsApp with: trades executed, skips with reasons, P&L, regime status

### Between Phases

Python sleeps. No API calls. Cost-efficient.

## Tools

### Trading Core (7 tools)

| Tool | Function | Modifies State |
|------|----------|---------------|
| `get_momentum_signals` | Compute 90d/5d momentum ranking for universe | No |
| `check_regime` | SPY SMA200 sigmoid score + crash velocity | No |
| `check_position_stops` | Evaluate adaptive stops + trailing for each position | No |
| `execute_trade` | Submit BUY/SELL via broker (PaperBroker or IBKR) | **Yes** |
| `get_portfolio_state` | Read current positions, cash, P&L, regime from state JSON | No |
| `save_state` | Persist state to JSON (atomic write with temp file + rename) | **Yes** |
| `update_cycle_log` | Record rotation event in cycle_log.json | **Yes** |

### Market Intelligence (5 tools)

**Launch-ready tools** (yfinance/FRED, no paid subscriptions):

| Tool | Function | Source |
|------|----------|--------|
| `get_earnings_calendar` | Earnings dates for tickers, next 7 days | yfinance `.earnings_dates` |
| `get_macro_data` | VIX, credit spreads, FRED yields | yfinance + FRED API |

**Future tools** (require MCP subscription — graceful degradation if unavailable):

| Tool | Function | Source |
|------|----------|--------|
| `get_insider_trades` | Recent insider buying/selling for a ticker | MCP FactSet or Financial Datasets API |
| `get_financial_metrics` | P/E, market cap, margins snapshot | MCP Morningstar or S&P Global |
| `get_news_headlines` | Recent headlines for a ticker | MCP MT Newswires or Aiera |

**Graceful degradation:** The agent MUST function correctly with zero Market Intelligence tools. If `get_earnings_calendar` fails (yfinance returns empty), the agent proceeds with the entry (no skip) and logs: "earnings data unavailable, proceeding with signal." MCP tools are additive intelligence, not required.

### Operations (3 tools)

| Tool | Function |
|------|----------|
| `send_notification` | WhatsApp (CallMeBot) or Email alert |
| `log_decision` | Append decision + reasoning to scratchpad JSONL |
| `validate_data_feeds` | Verify yfinance responds, SPY price fresh (<5min), no NaN/outliers |

## Security & Guards

### Trade Execution Guards (in `execute_trade`)
- MOC deadline: reject orders after 15:50 ET
- Order size limit: $50K max per order
- Port verification: 7497 = paper only (when IBKR live)
- Circuit breaker: 2% max fill deviation
- Position count: max 5 (risk-on) or 2 (risk-off)

### Agent-Level Guards
- Tool call limit: max 3 calls to same tool per phase (prevents loops)
- Query similarity detection: warns if repeating nearly identical queries
- Algorithm parameters: NOT exposed as tools — Claude cannot modify momentum lookback, stop levels, etc.
- Kill switch: `STOP_TRADING` file halts all execution
- **Daily trade limit: max 10 round-trip trades per day** (2 full rotations). If exceeded, halt all entries until next session
- **Daily loss halt: if portfolio drops >3% intraday, halt all entries** until next session. Exits (stops) still execute.

### Trade Idempotency
- Before executing any trade, `execute_trade` checks today's scratchpad for existing `trade` entries with the same symbol and action
- If a matching trade already exists (e.g., from a retry after API timeout), the tool returns the existing fill instead of submitting a duplicate order
- This prevents double-buying on Claude API retries or agent restarts mid-phase

### Deploy Freeze Window
- **No deploys between 15:25-16:05 ET.** This is an operational rule enforced by documentation, not code
- If the agent detects on startup that it is within an active trading window (15:25-16:05), it checks the scratchpad for partial rotations and resumes from where it left off
- Partial rotation detection: count `trade` entries in today's scratchpad vs expected trades from the last `decision` entries

### State Protection
- Atomic writes (temp file + os.replace) for all JSON state files
- State backup before any trade execution
- Fallback chain: latest → dated backup → HALT

## SOUL.md — Agent Philosophy

```markdown
# HYDRA Agent — SOUL

## Who I Am
Autonomous operator of HYDRA, a momentum trading system for S&P 500
large-caps. I execute COMPASS signals with contextual intelligence
that pure code cannot have.

## What I Do NOT Do
The engine is LOCKED. 68 experiments prove it. I do not modify:
- Momentum signal (90d lookback, 5d skip, 5d hold)
- Ranking (return/vol normalized, inv-vol equal weight)
- Adaptive stops (-6% to -15%, STOP_DAILY_VOL_MULT=2.5 × entry_daily_vol)
- Trailing stops (+5% / -3%, vol-scaled)
- Position count (5 risk-on, 2 risk-off)
- Regime filter (SPY SMA200, 3-day confirmation)
- Bull override (SPY > SMA200×103% & score>40% → +1 position)
- Sector limit (max 3 per sector)
- Drawdown tiers (T1=-10%, T2=-20%, T3=-35%)
- Crash brake (5d=-6% or 10d=-10% → 15% leverage)
- Exit renewal (max 10d, min profit 4%, momentum pctl 85%)
- HYDRA allocation (COMPASS 50%, Rattlesnake 50%, cash recycling)

## What I DO
I operate the chassis:
- WHEN to execute (timing within MOC window)
- WHAT context to consider (earnings, insider trades, news)
- HOW to handle edge cases (data failures, state corruption)
- WHEN to notify the human

## My Principles
1. Cash is king in protection mode
2. Skip > override — take the next candidate, never modify ranking
3. Every decision logged with reasoning (scratchpad)
4. Always notify — the human must know what I did and why
5. When in doubt, do not trade
```

## Scratchpad Format

One JSONL file per day: `state/agent_scratchpad/YYYY-MM-DD.jsonl`

Entry types:
- `briefing` — Pre-market state summary
- `tool_call` — Tool invocation with args and result
- `decision` — Agent decision with action, symbol, reason, alternative
- `trade` — Executed trade with symbol, shares, price, order_type
- `stop_event` — Stop triggered with symbol, return, action taken
- `alert` — Anomaly detected (data feed, crash velocity, etc.)
- `summary` — End-of-day summary with stats

Each entry has: `type`, `ts` (ISO 8601), `data` or specific fields.

Dashboard exposes via `/api/agent/scratchpad` (GET, returns today's entries as JSON array).

## System Prompt Structure

```
You are the HYDRA autonomous trading agent.

{SOUL.md}

## Current Date & Time
{ET timestamp}

## Portfolio State
{positions, cash, regime_score, portfolio_value, days_in_cycle}

## Today's Scratchpad (summarized)
{For PRE_MARKET: empty. For INTRADAY/PRE_CLOSE: summary of earlier phases
 (briefing alerts, stop events). For POST_CLOSE: summary of all phases.
 Full entries only for current phase to control token cost.}

## Current Phase
{PRE_MARKET_BRIEFING | INTRADAY_MONITOR | PRE_CLOSE_DECISION | POST_CLOSE_SUMMARY}

## Phase-Specific Instructions
{varies by phase — briefing tasks, monitoring rules, decision workflow, summary format}

## Decision Rules
1. NEVER modify momentum signal parameters
2. NEVER exceed position limits (5 risk-on, 2 risk-off)
3. NEVER execute entries outside 15:30-15:50 ET
4. ALWAYS log every decision with reasoning
5. ALWAYS notify human after trades
6. MAY skip entry if: earnings <24h, insider selling >$10M/7d, data validation fails
7. When skipping, take next ranked candidate
8. Stops are non-negotiable — if triggered, EXIT
9. Save state after any portfolio change
```

## Deployment

### render.yaml (updated)

Two services sharing a persistent disk:
- `omnicapital-dashboard` (web) — existing Flask dashboard
- `hydra-agent` (worker) — new autonomous agent

### Dependencies (requirements-agent.txt)

```
anthropic>=0.40.0
numpy>=1.24.0
pandas>=2.0.0
yfinance>=0.2.28
python-dateutil>=2.8.0
requests>=2.31.0
```

### Environment Variables

- `ANTHROPIC_API_KEY` — Claude API access
- `STATE_DIR` — path to persistent disk (default: `/data/state`)
- `BROKER_TYPE` — PAPER (default) or IBKR
- `NOTIFICATION_ENABLED` — true/false
- `WHATSAPP_API_KEY` — CallMeBot API key (optional)

### Cost Estimate

| Item | Monthly Cost |
|------|-------------|
| Render Worker (Starter or Standard) | $7-25 |
| Render Disk 1GB | $0.25 |
| Anthropic API (~5 calls/day × 8-10K avg tokens × Sonnet) | $6-18 |
| MCP connectors (free tier initially) | $0 |
| **Total** | **$13-43** |

**Note:** Starter plan ($7) has 512MB RAM — may be tight with pandas+numpy+yfinance for 500-stock universe. Memory profiling required during pre-deploy validation. If >400MB, use Standard plan ($25). Pre-close phase prompts with full portfolio state + scratchpad + momentum rankings may reach 10-15K input tokens per call.

### Scratchpad Retention
- JSONL files retained for 90 days, then auto-deleted by a cleanup in the agent's startup routine
- At ~50 entries/day × 500 bytes = ~25KB/day = ~2.3MB per 90 days — negligible on 1GB disk

## File Structure

```
hydra_agent.py          — Main process: scheduling loop + Claude orchestration
hydra_tools.py          — Tool definitions (Anthropic tool format)
hydra_prompts.py        — System prompt builder per phase
hydra_scratchpad.py     — JSONL append-only decision logger
hydra_soul.md           — Agent philosophy document
requirements-agent.txt  — Python dependencies for the agent
```

## Success Criteria

1. Agent runs 24/7 on Render without crashes for 7+ consecutive days
2. Pre-close decisions execute within the 15:30-15:50 ET window
3. Every trade has a scratchpad entry with reasoning
4. Earnings skips are logged and the next candidate is taken correctly
5. WhatsApp notifications arrive for daily briefing and post-close summary
6. State JSON remains valid (no corruption) across deploys/restarts
7. PaperBroker trades match what COMPASS would do (minus justified skips)
8. API cost stays under $45/month
9. Daily trade count never exceeds 10 round-trips
10. Stops execute immediately (zero delay from Claude reasoning)
11. Agent resumes correctly after restart mid-trading-day (partial rotation recovery)
12. Memory usage stays under 400MB (Starter plan) or 1GB (Standard plan)
