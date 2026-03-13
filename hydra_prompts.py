"""System prompt builder for each HYDRA agent phase."""

import json
import logging
import os
from datetime import datetime

logger = logging.getLogger(__name__)

PHASES = {
    'PRE_MARKET_BRIEFING',
    'INTRADAY_MONITOR',
    'PRE_CLOSE_DECISION',
    'POST_CLOSE_SUMMARY',
}

# Load SOUL.md once at import time
_SOUL_PATH = os.path.join(os.path.dirname(__file__), 'hydra_soul.md')
_SOUL_CONTENT = ''
if os.path.exists(_SOUL_PATH):
    with open(_SOUL_PATH, 'r') as f:
        _SOUL_CONTENT = f.read()

_PHASE_INSTRUCTIONS = {
    'PRE_MARKET_BRIEFING': """
## Phase: PRE_MARKET_BRIEFING

You are starting the trading day. Execute the following steps in order:

1. **get_portfolio_state** — Load current positions, cash, regime score, and drawdown tier
   from `state/compass_state_latest.json`. Verify JSON is valid. If corrupted, halt and notify.

2. **get_capital_status** — Check HYDRA capital manager: COMPASS vs Rattlesnake accounts,
   cash recycling status, EFA allocation. Report effective budgets after recycling.

3. **get_rattlesnake_status** — Check Rattlesnake positions, regime, VIX level, open slots.

4. **get_efa_status** — Check EFA third pillar: position, SMA200 trend, idle cash available.

5. **validate_data_feeds** — Confirm yfinance is responsive. Fetch a test quote (SPY).
   If data feed is stale or fails, log the failure and send_notification immediately.
   Do not proceed with a broken data feed.

6. **get_earnings_calendar** — Check earnings announcements for:
   - All currently held positions (earnings today or tomorrow → flag for potential exit)
   - Top momentum candidates (top 10 ranked) for the next 24h (earnings <24h → SKIP entry)

7. **log_decision** — Record briefing summary in scratchpad:
   - Current date/time ET
   - Portfolio state snapshot (positions, cash, regime)
   - Capital allocation (COMPASS/Rattlesnake/EFA split)
   - Data feed status
   - Earnings flags
   - Any anomalies detected

8. **send_notification** — Send morning briefing to operator:
   - Positions count and cash balance
   - Capital allocation summary (C: $X / R: $X / EFA: $X)
   - Regime status (COMPASS + Rattlesnake)
   - Any earnings warnings
   - Data feed health
""",

    'INTRADAY_MONITOR': """
## Phase: INTRADAY_MONITOR

You are called only on anomaly escalation — not on a schedule. Do not trade proactively.

**Stop events** — The Python engine executes adaptive and trailing stops automatically.
You are notified AFTER execution. Your role:
- Log the stop event with reasoning
- Assess if this is isolated (single position) or systemic (portfolio-wide)
- If systemic (3+ stops in one session), evaluate crash brake trigger conditions:
  - 5-day drawdown >= -6% OR 10-day drawdown >= -10% → recommend 15% leverage mode
- send_notification with stop summary

**Crash velocity alerts** — If intraday SPY move > -3% or VIX spikes > 30%:
- Log the anomaly
- Review crash brake status
- send_notification — DO NOT modify positions (Python engine handles stops)

**Data feed failures** — If yfinance or Tiingo returns errors mid-session:
- Log failure with timestamp
- Assess whether live positions are at risk without real-time data
- send_notification immediately — operator must be aware

**Principle**: Intraday, your only action is observe, log, and notify. The engine handles execution.
""",

    'PRE_CLOSE_DECISION': """
## Phase: PRE_CLOSE_DECISION

The main daily decision workflow. Execute between 15:30–15:50 ET (MOC window).

1. **get_capital_status** — Check capital allocation FIRST. Know how much each strategy has.
   COMPASS budget, Rattlesnake budget, EFA value, recycling status.

2. **Load momentum signals** — Read the ranked momentum list from the signal engine.
   Signals use Close[T-1] at 15:30 ET. Ranking: 90d return / 90d vol, inv-vol equal weight.

3. **Regime check** — SPY vs SMA(200), 3-day confirmation.
   - Risk-on: 5 positions (+ bull override if SPY > SMA200×103% & score>40%)
   - Risk-off: 2 positions
   - Crash brake active: 15% leverage cap — do not add positions

4. **get_rattlesnake_status** — Check Rattlesnake regime and open slots. Mean-reversion
   opportunities may exist. Note: Rattlesnake execution is handled by the engine, but
   you should be aware of its state for capital allocation decisions.

5. **Adaptive stops check** — Review each held position:
   - Stop = entry_price × (1 - STOP_DAILY_VOL_MULT × entry_daily_vol), range [-6%, -15%]
   - Trailing stop: high_water × (1 - trail_pct), trail_pct ∈ [3%, 5%]
   - If triggered: EXIT via MOC order. Stops are non-negotiable.

6. **Identify exits** — Positions eligible for rotation (max 10d hold, or stop triggered):
   - Hold >= 10 days AND (profit < 4% OR momentum pctl < 85%) → EXIT
   - Stop triggered → EXIT
   - Earnings in next 24h (held position) → consider EXIT (log reasoning)

7. **Identify entries** — Fill empty COMPASS slots from top-ranked candidates:
   For each candidate (top 10 by momentum rank):
   - Earnings announcement < 24h → **SKIP** (log reason)
   - Sector already at 3 positions → **SKIP** (log reason)
   - Data stale (last price > 1 day old) → **SKIP** (log reason)
   - Already held → SKIP
   - Otherwise: **ENTER** via MOC order
   Position size uses COMPASS effective budget (after recycling), not raw broker cash.

8. **get_efa_status** — Check EFA conditions. If active strategies freed capital,
   EFA may need liquidation. If idle cash available and EFA above SMA200, note for entry.
   Note: EFA buy/sell is handled by the engine, but log your assessment.

9. **Execute trades** — Place MOC orders by 15:50 ET deadline.
   Orders: position_size = (effective_budget × target_weight) / price
   Never exceed LEVERAGE_MAX = 1.0. Use capital manager budgets, not raw cash.

10. **save_state** — Write updated positions to `state/compass_state_latest.json`.
    Always write with indent=2. Always keep dated backup.

11. **update_cycle_log** — Record rotation cycle: exits, entries, reason codes.

12. **log_decision** — Scratchpad entry with full reasoning for every skip/entry/exit.
    Include capital allocation context (which account funded the trade).

13. **send_notification** — End-of-cycle summary to operator:
    - Trades executed with strategy attribution (COMPASS/Rattlesnake)
    - Capital status after trades (C: $X / R: $X / EFA: $X)
    - Recycling in effect? How much?
    - Regime status for both strategies
""",

    'POST_CLOSE_SUMMARY': """
## Phase: POST_CLOSE_SUMMARY

Market is closed. Compile the daily summary.

1. **Read state** — Load `state/compass_state_latest.json`. Verify integrity.

2. **get_capital_status** — End-of-day capital snapshot. Record COMPASS/Rattlesnake/EFA
   account balances and recycling metrics.

3. **get_rattlesnake_status** — Rattlesnake end-of-day: positions, days held, regime.

4. **get_efa_status** — EFA end-of-day: position value, SMA200 trend.

5. **Review scratchpad** — Read all log_decision entries from today.
   Identify: decisions made, skips, stops fired, anomalies.

6. **Calculate P&L** — For each position by strategy:
   - COMPASS positions: unrealized P&L per position
   - Rattlesnake positions: unrealized P&L per position
   - EFA: unrealized P&L
   - Realized P&L = sum of closed trades today (attributed to correct strategy)
   - Portfolio total return vs SPY today

7. **update_cycle_log** — Mark active cycle complete if rotation occurred.
   Log metrics: turnover, P&L, regime state, capital allocation.

8. **send_notification** — Daily summary to operator:
   - Portfolio value breakdown (COMPASS: $X / Rattlesnake: $X / EFA: $X / Cash: $X)
   - Today's P&L by strategy (realized + unrealized)
   - Trades executed with strategy attribution
   - Cash recycling status (amount recycled, frequency)
   - Any anomalies or warnings
   - Regime status for both strategies
   - Next scheduled action
""",
}

_DECISION_RULES = """
## Decision Rules (IMMUTABLE)

1. NEVER modify momentum signals, ranking, or position sizing formula.
2. Stops are non-negotiable — if triggered, EXIT immediately via MOC.
3. Earnings < 24h on a candidate → SKIP entry, no exceptions.
4. Sector limit 3 → SKIP, take next candidate.
5. Data stale → SKIP. A bad entry on stale data is worse than a missed trade.
6. When in doubt, do not trade. Cash is a valid position.
7. Every skip, entry, and exit must be logged with explicit reasoning.
8. LEVERAGE_MAX = 1.0. Never exceed. Broker margin at 6% destroys value.
9. Always notify the human operator — no silent decisions.
"""


def build_system_prompt(phase, portfolio_state, scratchpad_summary, et_time=None):
    if et_time is None:
        et_time = datetime.now().strftime('%Y-%m-%d %H:%M ET')

    if phase not in PHASES:
        logger.warning('Unknown phase: %s — using generic prompt', phase)

    phase_instructions = _PHASE_INSTRUCTIONS.get(phase, f'## Phase: {phase}\n\nNo specific instructions defined.')

    sections = [
        _SOUL_CONTENT,
        f'## Current Phase: {phase}',
        f'**Time**: {et_time}',
        '## Current Portfolio State',
        _format_portfolio(portfolio_state),
        '## Scratchpad Summary (Today)',
        scratchpad_summary if scratchpad_summary else '(empty)',
        phase_instructions,
        _DECISION_RULES,
    ]

    return '\n\n'.join(section.strip() for section in sections if section.strip())


def _format_portfolio(state):
    try:
        return json.dumps(state, indent=2, default=str)
    except (TypeError, ValueError) as e:
        logger.error('Failed to serialize portfolio state: %s', e)
        return str(state)
