# HYDRA Council — Design Spec

**Date:** 2026-03-14
**Status:** Approved
**Author:** Lucas + Claude

## Overview

A local Python executable (`hydra_council.py`) that runs 5 AI agents in a continuous live debate about the HYDRA portfolio. Agents argue from different perspectives, challenge each other, and deliver hourly analysis to Telegram. The system runs 7 AM–7 PM ET, producing ~60 messages/day.

## Agents

| # | Agent | Emoji | Role | Natural Bias | Speaks |
|---|-------|-------|------|-------------|--------|
| 1 | News Reporter | 🌐 | Intelligence | Neutral — reports geopolitical facts | 1st |
| 2 | Market Macro | 🏔️ | Context | Neutral — interprets market data | 2nd |
| 3 | Alpha Hunter | 🎯 | Offense | Find opportunity, increase exposure | 3rd |
| 4 | Risk Hawk | 🛡️ | Defense | Protect capital, reduce exposure | 4th |
| 5 | Portfolio Strategist | ⚖️ | Judge | Synthesize all views, final verdict | 5th |

### Debate Order

Each round follows a **thesis → antithesis → synthesis** flow:

1. **News Reporter** — scans web for breaking geopolitical/economic news, reports relevant facts
2. **Market Macro** — interprets market data + news context into market conditions
3. **Alpha Hunter** — identifies opportunities, momentum signals, entry candidates
4. **Risk Hawk** — challenges with risks, drawdown concerns, vol warnings
5. **Portfolio Strategist** — weighs all views, delivers consensus and recommendation

Each agent sees what the agents before them said in that round. The Strategist sees all four prior messages.

## Operating Window

- **Active:** 7:00 AM – 7:00 PM ET (Eastern Time)
- **Cadence:** Hourly heartbeat (one round per hour)
- **Silent:** Outside 7 AM–7 PM, process sleeps
- **Daily volume:** ~60 messages (12 hours × 5 agents)

## Data Sources

Each round begins by fetching fresh data:

| Data | Source | Method |
|------|--------|--------|
| Breaking news & geopolitics | Brave Search API | HTTP request |
| Current positions & cash | `state/compass_state_latest.json` | Local file read |
| SPY price & SMA200 | Yahoo Finance (yfinance) | Internet |
| VIX level | Yahoo Finance | Internet |
| Position live prices | Yahoo Finance | Internet |
| Sector performance | Yahoo Finance (sector ETFs) | Internet |
| Portfolio P&L since entry | Calculated from state + live prices | Computed |
| Regime status | Dashboard API (`/api/state`) | HTTP localhost or state file |

## Architecture

Single Python process, single file (`hydra_council.py`).

```
┌──────────────────────────────────────────┐
│              MAIN LOOP                    │
│  while 7AM <= now <= 7PM ET:             │
│    1. Web search for news headlines      │
│    2. Fetch market data (yfinance)       │
│    3. Read HYDRA state (JSON)            │
│    4. Read regime from dashboard/state   │
│    5. Build data brief (shared context)  │
│    6. Run debate round:                  │
│       News Reporter  → Claude API        │
│       Market Macro   → Claude API        │
│       Alpha Hunter   → Claude API        │
│       Risk Hawk      → Claude API        │
│       Strategist     → Claude API        │
│    7. Send 5 messages to Telegram        │
│    8. Log round to council_log/          │
│    9. Sleep until next hour              │
│  end while                               │
│  Sleep until 7AM next day                │
└──────────────────────────────────────────┘
```

### Core Function

```python
def agent_speak(role, system_prompt, data_brief, prior_messages) -> str:
    """Call Claude API with agent personality + data + debate context."""
    # system_prompt: fixed personality & expertise per agent
    # data_brief: market data, positions, news (same for all agents)
    # prior_messages: what earlier agents said this round
    # Returns: agent's message (100-200 words)
```

### Key Implementation Details

- **LLM:** Claude API (`claude-sonnet-4-6`) via Anthropic Python SDK
- **Telegram:** Bot API `POST /sendMessage`, same bot token as existing HYDRA notifications
- **Config:** API keys from `.env` (ANTHROPIC_API_KEY, TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID)
- **News search:** Brave Search API (`api.search.brave.com/res/v1/web/search`) — free tier 1 query/sec, 2000/month (plenty for 12/day). Requires `BRAVE_SEARCH_API_KEY` in `.env`. Fallback: if search fails, News Reporter states "no fresh headlines available" and comments on known ongoing stories from prior rounds
- **Intra-day context:** Each agent receives the previous round's messages to avoid repetition. News Reporter also receives prior round's headlines to skip already-reported stories. Context resets at 7 AM each day
- **Logging:** Each round appended to `state/council_log/{YYYY-MM-DD}.jsonl`
- **Estimated cost:** ~$1.00-2.00/day (5 agents × 12 rounds × ~2-3K tokens input + ~300 tokens output each, Sonnet pricing). Budget ceiling: $3.00/day
- **Run command:** `python hydra_council.py` (stays alive, Ctrl+C to stop)
- **Graceful shutdown:** SIGINT (Ctrl+C) finishes current agent call, logs partial round, then exits
- **Timing:** Rounds anchored to clock (7:00, 8:00, ..., 18:00). If a round takes longer than expected, next round starts at next hour mark (never skips, never compresses)
- **Round numbering:** 1-indexed from 7 AM (round 1 = 7:00, round 12 = 18:00)

## Telegram Message Format

Each agent sends one message per round:

```
🌐 NEWS REPORTER [10:00 AM]
Top developments: China announced new export controls
on rare earth minerals — affects semiconductor supply
chain. EU digital services tax vote Thursday. Oil $78,
steady. Fed's Waller speaks at 2PM. No direct impact
on current positions but rare earth story worth
monitoring for tech momentum.

🏔️ MARKET MACRO [10:00 AM]
SPY $572.30 (+0.4%), above SMA200 ($548). VIX 14.2,
calm. Regime: RISK_ON. Tech leading (+0.8%), energy
lagging (-0.3%). Low-catalyst day. Rare earth story
could create tech headwinds if supply chain disruption
materializes but no price impact yet.

🎯 ALPHA HUNTER [10:00 AM]
XOM showing relative strength despite energy weakness —
divergence worth watching. NVDA momentum score rising
to 85th pctl. Our 5 positions all green today. No
rebalance due until Friday but ranked candidates look
strong. Comfortable holding.

🛡️ RISK HAWK [10:00 AM]
VIX at 14 is compressed — historically precedes
expansion. JNJ -0.6% from entry, approaching noise
zone. MRK also slightly red. Two defensive names
underperforming in risk-on — not alarming yet but
watching. Rare earth story is a tail risk for any
tech entries this cycle. Portfolio drawdown: -0.2%.

⚖️ STRATEGIST [10:00 AM]
Consensus: HOLD. Calm conditions, no urgency to act.
Risk Hawk flags vol compression and rare earth tail
risk — noted but not actionable yet. All positions
within normal range. Next rebalance Friday — no early
action warranted. Will revisit if rare earth story
develops or VIX breaks 16.
```

## Logging Format

Each round saved to `state/council_log/{YYYY-MM-DD}.jsonl`:

```json
{
  "timestamp": "2026-03-14T10:00:00-04:00",
  "round": 4,
  "data_brief": {
    "spy": 572.30,
    "vix": 14.2,
    "regime": "RISK_ON",
    "positions": {"XOM": "+3.0%", "WMT": "+2.4%", ...},
    "cash": 1066.27
  },
  "messages": [
    {"agent": "news_reporter", "text": "..."},
    {"agent": "market_macro", "text": "..."},
    {"agent": "alpha_hunter", "text": "..."},
    {"agent": "risk_hawk", "text": "..."},
    {"agent": "strategist", "text": "..."}
  ],
  "tokens_used": 5200,
  "cost_usd": 0.04
}
```

## Dependencies

- `anthropic` — Claude API SDK
- `yfinance` — market data
- `requests` — Telegram Bot API + news search
- `python-dotenv` — load .env
- `pytz` — ET timezone handling

## File Structure

```
hydra_council.py              — main executable (single file)
state/council_log/            — daily JSONL debate logs
.env                          — API keys (gitignored)
```

## Configuration

All config lives in `.env` (already gitignored):

```
ANTHROPIC_API_KEY=sk-ant-...
TELEGRAM_BOT_TOKEN=...
TELEGRAM_CHAT_ID=...
BRAVE_SEARCH_API_KEY=...
```

## Error Handling

- **Claude API failure:** Retry 3 times with exponential backoff (2s, 4s, 8s). If all 3 fail, skip that agent for the round — remaining agents still speak. Log the failure
- **yfinance failure:** Retry 3 times. If all fail, use last round's data (stale is better than nothing). Mark data as stale in the brief so agents know
- **Brave Search failure:** News Reporter says "no fresh headlines" and comments on known ongoing stories. Not a round-blocker
- **Telegram send failure:** Retry 3 times. If all fail, log the message (it's preserved in council_log). Don't block the round
- **Single agent failure:** Skip that agent, continue the round with remaining agents. Strategist adjusts if a voice is missing
- **Full round failure:** Log error, sleep until next hour, try again. Never crash the process

## Out of Scope

- No trade execution — agents observe and recommend, they don't act
- No cloud deployment — runs locally only
- No dashboard integration — Telegram is the sole output channel
- No event-triggered debates — hourly heartbeat only
- No persistent memory across days — each day starts fresh (logs are kept)

## Success Criteria

1. Script starts and runs continuously from 7 AM to 7 PM ET
2. 5 Telegram messages arrive every hour, on the hour
3. Each agent maintains consistent personality across rounds
4. Agents reference and challenge each other's points (not isolated monologues)
5. Market data is fresh (not stale/cached from prior rounds)
6. News headlines are current (not hallucinated)
7. Daily cost stays under $3.00
8. Process recovers gracefully from API errors (retry, don't crash)
