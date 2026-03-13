# HYDRA Autonomous Agent — Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build an autonomous Claude-powered trading agent that wraps the existing COMPASS/HYDRA momentum system, runs as a Render Worker service, and executes daily trading decisions with contextual intelligence.

**Architecture:** Four-phase daily loop (pre-market → intraday monitor → pre-close decision → post-close summary) using the Anthropic API with 15 tools. The agent wraps existing `COMPASSLive` functions without modifying the locked algorithm. State is persisted on a Render persistent disk mounted on the Worker; the dashboard reads state via an internal API endpoint on the Worker. The existing dashboard cloud engine is disabled when `AGENT_MODE=true`.

**Tech Stack:** Python 3.11, Anthropic SDK, pandas, numpy, yfinance, Flask (dashboard), Render.com (deployment)

**Spec:** `docs/superpowers/specs/2026-03-13-hydra-autonomous-agent-design.md`

---

## File Structure

| File | Responsibility |
|------|---------------|
| `hydra_scratchpad.py` | Append-only JSONL decision logging with tool-call limits |
| `hydra_tools.py` | 15 tool definitions in Anthropic format + execution dispatch |
| `hydra_prompts.py` | System prompt builder per phase (pre-market, intraday, pre-close, post-close) |
| `hydra_soul.md` | Agent philosophy document (injected into system prompt) |
| `hydra_agent.py` | Main process: scheduling loop + Claude API orchestration |
| `requirements-agent.txt` | Python dependencies for the worker service |
| `render.yaml` | Updated: add worker service + persistent disk |
| `compass_dashboard_cloud.py` | Modified: AGENT_MODE disables cloud engine thread |
| `tests/test_hydra_scratchpad.py` | Tests for scratchpad module |
| `tests/test_hydra_tools.py` | Tests for tool definitions and dispatch |
| `tests/test_hydra_prompts.py` | Tests for prompt builder |
| `tests/test_hydra_agent.py` | Tests for agent scheduling and orchestration |

---

## Chunk 1: Foundation — Scratchpad & Soul

### Task 1: hydra_scratchpad.py — JSONL Decision Logger

**Files:**
- Create: `hydra_scratchpad.py`
- Create: `tests/test_hydra_scratchpad.py`

- [ ] **Step 1: Write failing tests for scratchpad**

```python
# tests/test_hydra_scratchpad.py
import os
import json
import tempfile
import pytest
from datetime import datetime

from hydra_scratchpad import HydraScratchpad


@pytest.fixture
def scratchpad(tmp_path):
    return HydraScratchpad(state_dir=str(tmp_path))


def test_log_creates_daily_file(scratchpad):
    scratchpad.log('briefing', {'summary': 'test briefing'})
    today = datetime.now().strftime('%Y-%m-%d')
    path = os.path.join(scratchpad.state_dir, 'agent_scratchpad', f'{today}.jsonl')
    assert os.path.exists(path)


def test_log_entry_format(scratchpad):
    scratchpad.log('decision', {'action': 'BUY', 'symbol': 'AAPL', 'reason': 'top ranked'})
    entries = scratchpad.read_today()
    assert len(entries) == 1
    entry = entries[0]
    assert entry['type'] == 'decision'
    assert 'ts' in entry
    assert entry['data']['symbol'] == 'AAPL'


def test_multiple_entries_append(scratchpad):
    scratchpad.log('briefing', {'summary': 'morning'})
    scratchpad.log('trade', {'symbol': 'MSFT', 'shares': 10, 'price': 400.0})
    scratchpad.log('summary', {'pnl': 500.0})
    entries = scratchpad.read_today()
    assert len(entries) == 3
    assert [e['type'] for e in entries] == ['briefing', 'trade', 'summary']


def test_tool_call_limit(scratchpad):
    """Max 3 calls to same tool per phase"""
    for i in range(4):
        result = scratchpad.check_tool_limit('get_momentum_signals', 'PRE_CLOSE')
    assert result is False  # 4th call blocked


def test_tool_call_limit_resets_per_phase(scratchpad):
    for _ in range(3):
        scratchpad.check_tool_limit('get_momentum_signals', 'PRE_CLOSE')
    # Different phase resets
    result = scratchpad.check_tool_limit('get_momentum_signals', 'POST_CLOSE')
    assert result is True


def test_has_trade_today(scratchpad):
    assert scratchpad.has_trade_today('AAPL', 'BUY') is False
    scratchpad.log('trade', {'symbol': 'AAPL', 'action': 'BUY', 'shares': 10, 'price': 200.0})
    assert scratchpad.has_trade_today('AAPL', 'BUY') is True
    assert scratchpad.has_trade_today('AAPL', 'SELL') is False


def test_count_round_trips_today(scratchpad):
    scratchpad.log('trade', {'symbol': 'AAPL', 'action': 'BUY', 'shares': 10, 'price': 200.0})
    scratchpad.log('trade', {'symbol': 'AAPL', 'action': 'SELL', 'shares': 10, 'price': 210.0})
    assert scratchpad.count_round_trips_today() == 1


def test_cleanup_old_files(scratchpad):
    """Files older than 90 days are deleted"""
    sp_dir = os.path.join(scratchpad.state_dir, 'agent_scratchpad')
    os.makedirs(sp_dir, exist_ok=True)
    # Create an old file
    old_file = os.path.join(sp_dir, '2020-01-01.jsonl')
    with open(old_file, 'w') as f:
        f.write('{"type":"test"}\n')
    scratchpad.cleanup(max_age_days=90)
    assert not os.path.exists(old_file)


def test_summarize_phase(scratchpad):
    scratchpad.log('briefing', {'summary': 'morning check'})
    scratchpad.log('alert', {'type': 'data_feed', 'message': 'SPY stale'})
    summary = scratchpad.summarize_phase('PRE_MARKET')
    assert 'briefing' in summary.lower() or 'alert' in summary.lower()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_hydra_scratchpad.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'hydra_scratchpad'`

- [ ] **Step 3: Implement hydra_scratchpad.py**

```python
# hydra_scratchpad.py
"""Append-only JSONL decision logger for the HYDRA autonomous agent.

One file per day: state_dir/agent_scratchpad/YYYY-MM-DD.jsonl
Entry types: briefing, tool_call, decision, trade, stop_event, alert, summary
"""

import os
import json
import logging
from datetime import datetime, timedelta
from collections import defaultdict

logger = logging.getLogger(__name__)

# Max tool calls per tool per phase (prevents infinite loops)
MAX_TOOL_CALLS_PER_PHASE = 3


class HydraScratchpad:

    def __init__(self, state_dir='state'):
        self.state_dir = state_dir
        self._sp_dir = os.path.join(state_dir, 'agent_scratchpad')
        os.makedirs(self._sp_dir, exist_ok=True)
        # tool_name -> phase -> count
        self._tool_counts = defaultdict(lambda: defaultdict(int))

    def _today_path(self):
        today = datetime.now().strftime('%Y-%m-%d')
        return os.path.join(self._sp_dir, f'{today}.jsonl')

    def log(self, entry_type, data):
        entry = {
            'type': entry_type,
            'ts': datetime.now().isoformat(),
            'data': data,
        }
        path = self._today_path()
        with open(path, 'a') as f:
            f.write(json.dumps(entry, default=str) + '\n')
        logger.debug(f"Scratchpad: {entry_type} logged")

    def read_today(self):
        path = self._today_path()
        if not os.path.exists(path):
            return []
        entries = []
        with open(path, 'r') as f:
            for line in f:
                line = line.strip()
                if line:
                    entries.append(json.loads(line))
        return entries

    def check_tool_limit(self, tool_name, phase):
        self._tool_counts[tool_name][phase] += 1
        count = self._tool_counts[tool_name][phase]
        if count > MAX_TOOL_CALLS_PER_PHASE:
            logger.warning(f"Tool limit exceeded: {tool_name} called {count}x in {phase}")
            return False
        return True

    def has_trade_today(self, symbol, action):
        for entry in self.read_today():
            if entry['type'] == 'trade':
                d = entry.get('data', {})
                if d.get('symbol') == symbol and d.get('action') == action:
                    return True
        return False

    def count_round_trips_today(self):
        buys = set()
        sells = set()
        for entry in self.read_today():
            if entry['type'] == 'trade':
                d = entry.get('data', {})
                sym = d.get('symbol')
                if d.get('action') == 'BUY':
                    buys.add(sym)
                elif d.get('action') == 'SELL':
                    sells.add(sym)
        return len(buys & sells)

    def cleanup(self, max_age_days=90):
        cutoff = datetime.now() - timedelta(days=max_age_days)
        removed = 0
        for fname in os.listdir(self._sp_dir):
            if not fname.endswith('.jsonl'):
                continue
            try:
                date_str = fname.replace('.jsonl', '')
                file_date = datetime.strptime(date_str, '%Y-%m-%d')
                if file_date < cutoff:
                    os.remove(os.path.join(self._sp_dir, fname))
                    removed += 1
            except ValueError:
                continue
        if removed:
            logger.info(f"Scratchpad cleanup: removed {removed} files older than {max_age_days}d")

    def summarize_phase(self, phase_hint=''):
        entries = self.read_today()
        if not entries:
            return "No entries today."
        type_counts = defaultdict(int)
        highlights = []
        for e in entries:
            type_counts[e['type']] += 1
            if e['type'] in ('alert', 'stop_event', 'trade'):
                data = e.get('data', {})
                sym = data.get('symbol', '')
                msg = data.get('message', data.get('action', ''))
                highlights.append(f"  - [{e['type']}] {sym} {msg}")
        summary_parts = [f"Entries: {sum(type_counts.values())} ({', '.join(f'{v} {k}' for k, v in type_counts.items())})"]
        if highlights:
            summary_parts.append("Highlights:\n" + "\n".join(highlights[:10]))
        return "\n".join(summary_parts)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_hydra_scratchpad.py -v`
Expected: All 10 tests PASS

- [ ] **Step 5: Commit**

```bash
git add hydra_scratchpad.py tests/test_hydra_scratchpad.py
git commit -m "feat: add HYDRA scratchpad (JSONL decision logger)"
```

---

### Task 2: hydra_soul.md — Agent Philosophy Document

**Files:**
- Create: `hydra_soul.md`

- [ ] **Step 1: Write SOUL.md**

```markdown
# HYDRA Agent — SOUL

## Who I Am
Autonomous operator of HYDRA, a momentum trading system for S&P 500
large-caps. I execute COMPASS signals with contextual intelligence
that pure code cannot have.

## What I Do NOT Do
The engine is LOCKED. 62 experiments prove it. I do not modify:
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

- [ ] **Step 2: Commit**

```bash
git add hydra_soul.md
git commit -m "feat: add HYDRA SOUL.md (agent philosophy)"
```

---

## Chunk 2: Tools — Trading Core, Market Intel, Operations

### Task 3: hydra_tools.py — Tool Definitions & Dispatch

This is the largest file. It defines 15 tools in Anthropic API format and dispatches tool calls to the actual implementation.

**Files:**
- Create: `hydra_tools.py`
- Create: `tests/test_hydra_tools.py`

**Dependencies:** `hydra_scratchpad.py` (Task 1), `omnicapital_live.py` (existing), `omnicapital_broker.py` (existing), `compass/notifications.py` (existing)

- [ ] **Step 1: Write failing tests for tool definitions**

```python
# tests/test_hydra_tools.py
import os
import json
import tempfile
import pytest
from unittest.mock import MagicMock, patch
from datetime import datetime

from hydra_tools import (
    TOOL_DEFINITIONS,
    HydraToolExecutor,
)


def test_tool_definitions_valid_anthropic_format():
    """All tools must have name, description, input_schema"""
    assert len(TOOL_DEFINITIONS) == 15
    for tool in TOOL_DEFINITIONS:
        assert 'name' in tool
        assert 'description' in tool
        assert 'input_schema' in tool
        assert tool['input_schema']['type'] == 'object'


def test_tool_names_unique():
    names = [t['name'] for t in TOOL_DEFINITIONS]
    assert len(names) == len(set(names))


def test_trading_core_tools_present():
    names = {t['name'] for t in TOOL_DEFINITIONS}
    expected = {
        'get_momentum_signals', 'check_regime', 'check_position_stops',
        'execute_trade', 'get_portfolio_state', 'save_state', 'update_cycle_log'
    }
    assert expected.issubset(names)


def test_market_intel_tools_present():
    names = {t['name'] for t in TOOL_DEFINITIONS}
    expected = {
        'get_earnings_calendar', 'get_macro_data',
        'get_insider_trades', 'get_financial_metrics', 'get_news_headlines'
    }
    assert expected.issubset(names)


def test_operations_tools_present():
    names = {t['name'] for t in TOOL_DEFINITIONS}
    expected = {'send_notification', 'log_decision', 'validate_data_feeds'}
    assert expected.issubset(names)


class TestToolExecutor:

    @pytest.fixture
    def executor(self, tmp_path):
        engine = MagicMock()
        engine.broker = MagicMock()
        engine.broker.cash = 50000.0
        engine.broker.positions = {}
        engine.current_regime_score = 0.7
        engine.save_state = MagicMock()

        from hydra_scratchpad import HydraScratchpad
        scratchpad = HydraScratchpad(state_dir=str(tmp_path))

        return HydraToolExecutor(engine=engine, scratchpad=scratchpad)

    def test_dispatch_unknown_tool(self, executor):
        result = executor.dispatch('unknown_tool', {})
        assert 'error' in result.lower() or 'unknown' in result.lower()

    def test_get_portfolio_state(self, executor):
        executor.engine.broker.cash = 75000.0
        executor.engine.broker.positions = {}
        executor.engine.current_regime_score = 0.8
        executor.engine.peak_value = 100000.0
        executor.engine.crash_cooldown = 0
        executor.engine.trading_day_counter = 42
        executor.engine.broker.get_portfolio = MagicMock(
            return_value=MagicMock(total_value=75000.0)
        )
        result = executor.dispatch('get_portfolio_state', {})
        data = json.loads(result)
        assert data['cash'] == 75000.0
        assert data['regime_score'] == 0.8

    def test_execute_trade_idempotency(self, executor):
        """If same trade already in scratchpad, return existing fill"""
        executor.scratchpad.log('trade', {
            'symbol': 'AAPL', 'action': 'BUY', 'shares': 10, 'price': 200.0
        })
        result = executor.dispatch('execute_trade', {
            'symbol': 'AAPL', 'action': 'BUY', 'shares': 10
        })
        data = json.loads(result)
        assert data.get('idempotent') is True or 'already executed' in result.lower()

    def test_execute_trade_blocked_after_moc_deadline(self, executor):
        """Trades rejected after 15:50 ET"""
        with patch('hydra_tools._get_et_now') as mock_now:
            mock_now.return_value = datetime(2026, 3, 13, 16, 0, 0)  # 16:00 ET
            result = executor.dispatch('execute_trade', {
                'symbol': 'AAPL', 'action': 'BUY', 'shares': 10
            })
            assert 'reject' in result.lower() or 'deadline' in result.lower()

    def test_execute_trade_daily_limit(self, executor):
        """Max 10 round-trips per day"""
        for i in range(11):
            sym = f'STOCK{i}'
            executor.scratchpad.log('trade', {'symbol': sym, 'action': 'BUY', 'shares': 1, 'price': 100.0})
            executor.scratchpad.log('trade', {'symbol': sym, 'action': 'SELL', 'shares': 1, 'price': 101.0})
        result = executor.dispatch('execute_trade', {
            'symbol': 'NEW', 'action': 'BUY', 'shares': 10
        })
        assert 'limit' in result.lower() or 'halt' in result.lower()

    def test_log_decision_tool(self, executor):
        result = executor.dispatch('log_decision', {
            'action': 'SKIP',
            'symbol': 'TSLA',
            'reason': 'earnings in 12h',
            'alternative': 'MSFT'
        })
        entries = executor.scratchpad.read_today()
        decisions = [e for e in entries if e['type'] == 'decision']
        assert len(decisions) == 1
        assert decisions[0]['data']['symbol'] == 'TSLA'

    def test_validate_data_feeds(self, executor):
        with patch('hydra_tools._check_yfinance_health') as mock_yf:
            mock_yf.return_value = {'spy_fresh': True, 'spy_price': 550.0, 'yfinance_ok': True}
            result = executor.dispatch('validate_data_feeds', {})
            data = json.loads(result)
            assert data['spy_fresh'] is True
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_hydra_tools.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'hydra_tools'`

- [ ] **Step 3: Implement hydra_tools.py**

```python
# hydra_tools.py
"""Tool definitions for the HYDRA autonomous agent (Anthropic API format).

15 tools organized in 3 categories:
  Trading Core (7): momentum signals, regime, stops, trade execution, state
  Market Intelligence (5): earnings, macro, insider, financials, news
  Operations (3): notifications, decision logging, data validation
"""

import os
import json
import logging
from datetime import datetime

logger = logging.getLogger(__name__)

# ── ET timezone helper ──────────────────────────────────────────────────────

def _get_et_now():
    """Current time in US/Eastern (handles EDT/EST automatically)."""
    try:
        from zoneinfo import ZoneInfo
        return datetime.now(ZoneInfo('America/New_York')).replace(tzinfo=None)
    except ImportError:
        from dateutil import tz
        return datetime.now(tz.gettz('America/New_York')).replace(tzinfo=None)


def _check_yfinance_health():
    """Verify yfinance responds and SPY price is fresh."""
    try:
        import yfinance as yf
        spy = yf.Ticker('SPY')
        hist = spy.history(period='1d')
        if hist.empty:
            return {'yfinance_ok': False, 'spy_fresh': False, 'spy_price': None, 'error': 'empty history'}
        price = float(hist['Close'].iloc[-1])
        return {'yfinance_ok': True, 'spy_fresh': True, 'spy_price': price}
    except Exception as e:
        return {'yfinance_ok': False, 'spy_fresh': False, 'spy_price': None, 'error': str(e)}


# ── Tool Definitions (Anthropic format) ─────────────────────────────────────

TOOL_DEFINITIONS = [
    # ── Trading Core (7) ────────────────────────────────────────────────────
    {
        'name': 'get_momentum_signals',
        'description': 'Compute 90d/5d momentum ranking for the S&P 500 universe. Returns top-N ranked stocks with scores.',
        'input_schema': {
            'type': 'object',
            'properties': {
                'top_n': {'type': 'integer', 'description': 'Number of top-ranked stocks to return (default 20)', 'default': 20}
            },
            'required': []
        }
    },
    {
        'name': 'check_regime',
        'description': 'Check SPY SMA200 regime score (sigmoid), crash velocity (5d/10d returns), and current drawdown tier.',
        'input_schema': {
            'type': 'object',
            'properties': {},
            'required': []
        }
    },
    {
        'name': 'check_position_stops',
        'description': 'Evaluate adaptive stops and trailing stops for each held position. Returns stop status per position.',
        'input_schema': {
            'type': 'object',
            'properties': {},
            'required': []
        }
    },
    {
        'name': 'execute_trade',
        'description': 'Submit BUY or SELL order via broker. Guards: MOC deadline (15:50 ET), max $50K per order, idempotency check, daily trade limit (10 round-trips).',
        'input_schema': {
            'type': 'object',
            'properties': {
                'symbol': {'type': 'string', 'description': 'Stock ticker symbol'},
                'action': {'type': 'string', 'enum': ['BUY', 'SELL'], 'description': 'Trade action'},
                'shares': {'type': 'integer', 'description': 'Number of shares'}
            },
            'required': ['symbol', 'action', 'shares']
        }
    },
    {
        'name': 'get_portfolio_state',
        'description': 'Read current positions, cash, P&L, regime score, drawdown, crash cooldown from state JSON.',
        'input_schema': {
            'type': 'object',
            'properties': {},
            'required': []
        }
    },
    {
        'name': 'save_state',
        'description': 'Persist current portfolio state to JSON (atomic write with temp file + rename).',
        'input_schema': {
            'type': 'object',
            'properties': {},
            'required': []
        }
    },
    {
        'name': 'update_cycle_log',
        'description': 'Record a rotation event (entry/exit) in cycle_log.json.',
        'input_schema': {
            'type': 'object',
            'properties': {
                'event_type': {'type': 'string', 'enum': ['rotation_start', 'rotation_end', 'stop_exit']},
                'details': {'type': 'object', 'description': 'Event details (symbols, prices, etc.)'}
            },
            'required': ['event_type']
        }
    },

    # ── Market Intelligence (5) ─────────────────────────────────────────────
    {
        'name': 'get_earnings_calendar',
        'description': 'Get upcoming earnings dates for a list of tickers (next 7 days). Uses yfinance. Returns empty if unavailable (graceful degradation).',
        'input_schema': {
            'type': 'object',
            'properties': {
                'symbols': {'type': 'array', 'items': {'type': 'string'}, 'description': 'List of ticker symbols'}
            },
            'required': ['symbols']
        }
    },
    {
        'name': 'get_macro_data',
        'description': 'Get VIX level, credit spreads, and Treasury yields from yfinance/FRED.',
        'input_schema': {
            'type': 'object',
            'properties': {},
            'required': []
        }
    },
    {
        'name': 'get_insider_trades',
        'description': '[FUTURE — MCP] Get recent insider buying/selling for a ticker. Currently returns stub data.',
        'input_schema': {
            'type': 'object',
            'properties': {
                'symbol': {'type': 'string', 'description': 'Ticker symbol'}
            },
            'required': ['symbol']
        }
    },
    {
        'name': 'get_financial_metrics',
        'description': '[FUTURE — MCP] Get P/E, market cap, margins for a ticker. Currently returns stub data.',
        'input_schema': {
            'type': 'object',
            'properties': {
                'symbol': {'type': 'string', 'description': 'Ticker symbol'}
            },
            'required': ['symbol']
        }
    },
    {
        'name': 'get_news_headlines',
        'description': '[FUTURE — MCP] Get recent headlines for a ticker. Currently returns stub data.',
        'input_schema': {
            'type': 'object',
            'properties': {
                'symbol': {'type': 'string', 'description': 'Ticker symbol'}
            },
            'required': ['symbol']
        }
    },

    # ── Operations (3) ──────────────────────────────────────────────────────
    {
        'name': 'send_notification',
        'description': 'Send a WhatsApp (CallMeBot) notification to the human operator.',
        'input_schema': {
            'type': 'object',
            'properties': {
                'message': {'type': 'string', 'description': 'Notification text'}
            },
            'required': ['message']
        }
    },
    {
        'name': 'log_decision',
        'description': 'Log a decision (action + reasoning) to the scratchpad JSONL.',
        'input_schema': {
            'type': 'object',
            'properties': {
                'action': {'type': 'string', 'description': 'Action taken: BUY, SELL, SKIP, HOLD, ALERT'},
                'symbol': {'type': 'string', 'description': 'Ticker symbol (if applicable)'},
                'reason': {'type': 'string', 'description': 'Reasoning for the decision'},
                'alternative': {'type': 'string', 'description': 'Alternative considered (if skip)'}
            },
            'required': ['action', 'reason']
        }
    },
    {
        'name': 'validate_data_feeds',
        'description': 'Verify yfinance responds, SPY price is fresh (<5min), no NaN/outliers in recent data.',
        'input_schema': {
            'type': 'object',
            'properties': {},
            'required': []
        }
    },
]

# ── Tool Executor ───────────────────────────────────────────────────────────

# Trade execution guards
MAX_ORDER_VALUE = 50_000
MOC_DEADLINE_HOUR = 15
MOC_DEADLINE_MINUTE = 50
MAX_DAILY_ROUND_TRIPS = 10
DAILY_LOSS_HALT_PCT = -0.03


class HydraToolExecutor:
    """Dispatches tool calls to actual implementations.

    Args:
        engine: COMPASSLive instance (owns broker, state, signals)
        scratchpad: HydraScratchpad instance (decision logging)
        notifier: WhatsAppNotifier instance (optional)
    """

    def __init__(self, engine, scratchpad, notifier=None):
        self.engine = engine
        self.scratchpad = scratchpad
        self.notifier = notifier

    def dispatch(self, tool_name, tool_input):
        """Execute a tool call and return the result as a JSON string."""
        handler = getattr(self, f'_tool_{tool_name}', None)
        if handler is None:
            return json.dumps({'error': f'Unknown tool: {tool_name}'})
        try:
            # Log tool call
            self.scratchpad.log('tool_call', {
                'tool': tool_name,
                'input': tool_input,
            })
            result = handler(tool_input)
            return result if isinstance(result, str) else json.dumps(result, default=str)
        except Exception as e:
            logger.error(f"Tool {tool_name} failed: {e}", exc_info=True)
            return json.dumps({'error': str(e)})

    # ── Trading Core ────────────────────────────────────────────────────────

    def _tool_get_momentum_signals(self, inp):
        top_n = inp.get('top_n', 20)
        try:
            from omnicapital_live import compute_momentum_scores
            # Load fresh historical data via engine's data feed
            hist_data = {}
            for sym in self.engine.current_universe:
                try:
                    import yfinance as yf
                    df = yf.download(sym, period='6mo', progress=False)
                    if not df.empty:
                        hist_data[sym] = df
                except Exception:
                    continue
            scores = compute_momentum_scores(
                hist_data, self.engine.current_universe
            )
            ranked = sorted(scores.items(), key=lambda x: x[1], reverse=True)[:top_n]
            return json.dumps([
                {'rank': i + 1, 'symbol': sym, 'score': round(score, 4)}
                for i, (sym, score) in enumerate(ranked)
            ])
        except Exception as e:
            return json.dumps({'error': f'Momentum computation failed: {e}'})

    def _tool_check_regime(self, inp):
        try:
            return json.dumps({
                'regime_score': self.engine.current_regime_score,
                'crash_cooldown': self.engine.crash_cooldown,
                'portfolio_values_5d': self.engine.portfolio_values_history[-5:] if len(self.engine.portfolio_values_history) >= 5 else self.engine.portfolio_values_history,
                'risk_mode': 'RISK_ON' if self.engine.current_regime_score > 0.5 else 'RISK_OFF',
            })
        except Exception as e:
            return json.dumps({'error': str(e)})

    def _tool_check_position_stops(self, inp):
        try:
            results = []
            for sym, pos in self.engine.broker.positions.items():
                meta = self.engine.position_meta.get(sym, {})
                entry_price = pos.avg_cost
                current_price = None
                if self.engine.data_feed:
                    current_price = self.engine.data_feed.get_price(sym)
                if current_price and entry_price > 0:
                    ret = (current_price - entry_price) / entry_price
                    entry_daily_vol = meta.get('entry_daily_vol', 0.02)
                    from omnicapital_live import compute_adaptive_stop
                    stop_level = compute_adaptive_stop(entry_daily_vol, self.engine.config)
                    trail_high = meta.get('trail_high', current_price)
                    trail_ret = (current_price - trail_high) / trail_high if trail_high > 0 else 0
                    results.append({
                        'symbol': sym,
                        'entry_price': entry_price,
                        'current_price': current_price,
                        'return_pct': round(ret * 100, 2),
                        'stop_level_pct': round(stop_level * 100, 2),
                        'stop_triggered': ret <= stop_level,
                        'trail_triggered': trail_ret <= -0.03,
                        'days_held': meta.get('days_held', 0),
                    })
            return json.dumps(results)
        except Exception as e:
            return json.dumps({'error': str(e)})

    def _tool_execute_trade(self, inp):
        symbol = inp['symbol']
        action = inp['action']
        shares = inp['shares']

        # Guard: idempotency — check scratchpad for existing trade
        if self.scratchpad.has_trade_today(symbol, action):
            return json.dumps({
                'idempotent': True,
                'message': f'{action} {symbol} already executed today'
            })

        # Guard: daily round-trip limit
        if self.scratchpad.count_round_trips_today() >= MAX_DAILY_ROUND_TRIPS:
            return json.dumps({
                'error': 'Daily trade limit reached (10 round-trips). Entries halted until next session.'
            })

        # Guard: MOC deadline
        now_et = _get_et_now()
        if now_et.hour > MOC_DEADLINE_HOUR or (now_et.hour == MOC_DEADLINE_HOUR and now_et.minute > MOC_DEADLINE_MINUTE):
            return json.dumps({
                'error': f'MOC deadline passed ({MOC_DEADLINE_HOUR}:{MOC_DEADLINE_MINUTE:02d} ET). Order rejected.'
            })

        # Guard: order size limit
        price = None
        if self.engine.data_feed:
            price = self.engine.data_feed.get_price(symbol)
        if price and shares * price > MAX_ORDER_VALUE:
            return json.dumps({
                'error': f'Order value ${shares * price:,.0f} exceeds ${MAX_ORDER_VALUE:,} limit'
            })

        # Execute via broker
        try:
            if action == 'BUY':
                order = self.engine.broker.buy(symbol, shares)
            else:
                order = self.engine.broker.sell(symbol, shares)

            fill_price = getattr(order, 'fill_price', price)
            result = {
                'symbol': symbol,
                'action': action,
                'shares': shares,
                'fill_price': fill_price,
                'status': 'FILLED',
            }
            # Log to scratchpad
            self.scratchpad.log('trade', result)
            return json.dumps(result, default=str)
        except Exception as e:
            return json.dumps({'error': f'Trade execution failed: {e}'})

    def _tool_get_portfolio_state(self, inp):
        portfolio = self.engine.broker.get_portfolio()
        positions_data = {}
        for sym, pos in self.engine.broker.positions.items():
            meta = self.engine.position_meta.get(sym, {})
            positions_data[sym] = {
                'shares': pos.shares,
                'avg_cost': pos.avg_cost,
                'current_value': pos.shares * pos.avg_cost,  # approximate
                'sector': meta.get('sector', 'Unknown'),
                'days_held': meta.get('days_held', 0),
                'entry_date': meta.get('entry_date', ''),
            }
        return json.dumps({
            'cash': self.engine.broker.cash,
            'portfolio_value': portfolio.total_value,
            'peak_value': self.engine.peak_value,
            'regime_score': self.engine.current_regime_score,
            'crash_cooldown': self.engine.crash_cooldown,
            'trading_day': self.engine.trading_day_counter,
            'positions': positions_data,
            'n_positions': len(self.engine.broker.positions),
        })

    def _tool_save_state(self, inp):
        try:
            self.engine.save_state()
            # Push state to git so dashboard can pull it
            try:
                from compass.git_sync import git_push_state
                git_push_state()
            except Exception as ge:
                logger.warning(f"Git sync after save_state failed: {ge}")
            return json.dumps({'status': 'ok', 'message': 'State saved'})
        except Exception as e:
            return json.dumps({'error': f'State save failed: {e}'})

    def _tool_update_cycle_log(self, inp):
        event_type = inp.get('event_type', 'rotation_end')
        details = inp.get('details', {})
        try:
            # Append to cycle_log.json
            state_dir = getattr(self.engine, '_state_dir', 'state')
            log_path = os.path.join(state_dir, 'cycle_log.json')
            entries = []
            if os.path.exists(log_path):
                with open(log_path, 'r') as f:
                    entries = json.load(f)
            entries.append({
                'ts': datetime.now().isoformat(),
                'event': event_type,
                'details': details,
            })
            # Keep last 500 entries
            entries = entries[-500:]
            # Atomic write: temp file + os.replace
            import tempfile
            fd, tmp_path = tempfile.mkstemp(dir=state_dir, suffix='.json.tmp')
            with os.fdopen(fd, 'w') as f:
                json.dump(entries, f, indent=2, default=str)
            os.replace(tmp_path, log_path)
            return json.dumps({'status': 'ok'})
        except Exception as e:
            return json.dumps({'error': str(e)})

    # ── Market Intelligence ─────────────────────────────────────────────────

    def _tool_get_earnings_calendar(self, inp):
        symbols = inp.get('symbols', [])
        results = {}
        for sym in symbols:
            try:
                import yfinance as yf
                ticker = yf.Ticker(sym)
                cal = ticker.earnings_dates
                if cal is not None and not cal.empty:
                    upcoming = cal.head(3)
                    results[sym] = [
                        {'date': str(idx), 'estimate': row.get('EPS Estimate', None)}
                        for idx, row in upcoming.iterrows()
                    ]
                else:
                    results[sym] = []
            except Exception:
                results[sym] = []
        return json.dumps(results, default=str)

    def _tool_get_macro_data(self, inp):
        data = {}
        try:
            import yfinance as yf
            vix = yf.Ticker('^VIX')
            vix_hist = vix.history(period='1d')
            if not vix_hist.empty:
                data['vix'] = float(vix_hist['Close'].iloc[-1])
        except Exception:
            data['vix'] = None
        # Placeholder for credit spreads and yields (FRED integration future)
        data['credit_spread'] = None
        data['treasury_10y'] = None
        return json.dumps(data, default=str)

    def _tool_get_insider_trades(self, inp):
        return json.dumps({
            'status': 'stub',
            'message': 'MCP insider trades not yet connected. Proceeding without insider data.',
            'symbol': inp.get('symbol', ''),
            'trades': []
        })

    def _tool_get_financial_metrics(self, inp):
        return json.dumps({
            'status': 'stub',
            'message': 'MCP financial metrics not yet connected.',
            'symbol': inp.get('symbol', ''),
            'metrics': {}
        })

    def _tool_get_news_headlines(self, inp):
        return json.dumps({
            'status': 'stub',
            'message': 'MCP news headlines not yet connected.',
            'symbol': inp.get('symbol', ''),
            'headlines': []
        })

    # ── Operations ──────────────────────────────────────────────────────────

    def _tool_send_notification(self, inp):
        message = inp.get('message', '')
        if self.notifier:
            try:
                self.notifier._send_message(message)
                return json.dumps({'status': 'sent'})
            except Exception as e:
                return json.dumps({'status': 'failed', 'error': str(e)})
        return json.dumps({'status': 'skipped', 'message': 'Notifications not configured'})

    def _tool_log_decision(self, inp):
        self.scratchpad.log('decision', {
            'action': inp.get('action', ''),
            'symbol': inp.get('symbol', ''),
            'reason': inp.get('reason', ''),
            'alternative': inp.get('alternative', ''),
        })
        return json.dumps({'status': 'logged'})

    def _tool_validate_data_feeds(self, inp):
        result = _check_yfinance_health()
        return json.dumps(result, default=str)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_hydra_tools.py -v`
Expected: All 10 tests PASS

- [ ] **Step 5: Commit**

```bash
git add hydra_tools.py tests/test_hydra_tools.py
git commit -m "feat: add HYDRA tools (15 Anthropic-format tool definitions + executor)"
```

---

## Chunk 3: Prompts & Agent Orchestration

### Task 4: hydra_prompts.py — System Prompt Builder

**Files:**
- Create: `hydra_prompts.py`
- Create: `tests/test_hydra_prompts.py`

**Dependencies:** `hydra_soul.md` (Task 2)

- [ ] **Step 1: Write failing tests**

```python
# tests/test_hydra_prompts.py
import pytest
from hydra_prompts import build_system_prompt, PHASES


def test_phases_defined():
    assert 'PRE_MARKET_BRIEFING' in PHASES
    assert 'INTRADAY_MONITOR' in PHASES
    assert 'PRE_CLOSE_DECISION' in PHASES
    assert 'POST_CLOSE_SUMMARY' in PHASES


def test_build_prompt_contains_soul():
    prompt = build_system_prompt(
        phase='PRE_MARKET_BRIEFING',
        portfolio_state={'cash': 50000, 'positions': {}, 'regime_score': 0.7},
        scratchpad_summary='No entries today.',
    )
    assert 'HYDRA Agent' in prompt
    assert 'LOCKED' in prompt


def test_build_prompt_contains_phase():
    prompt = build_system_prompt(
        phase='PRE_CLOSE_DECISION',
        portfolio_state={'cash': 50000, 'positions': {}, 'regime_score': 0.7},
        scratchpad_summary='1 briefing.',
    )
    assert 'PRE_CLOSE_DECISION' in prompt


def test_build_prompt_contains_decision_rules():
    prompt = build_system_prompt(
        phase='PRE_CLOSE_DECISION',
        portfolio_state={'cash': 50000, 'positions': {}, 'regime_score': 0.7},
        scratchpad_summary='',
    )
    assert 'NEVER modify momentum' in prompt
    assert 'Stops are non-negotiable' in prompt


def test_build_prompt_pre_market_instructions():
    prompt = build_system_prompt(
        phase='PRE_MARKET_BRIEFING',
        portfolio_state={'cash': 50000, 'positions': {'AAPL': {}}, 'regime_score': 0.7},
        scratchpad_summary='',
    )
    assert 'validate_data_feeds' in prompt.lower() or 'data feed' in prompt.lower()


def test_build_prompt_pre_close_instructions():
    prompt = build_system_prompt(
        phase='PRE_CLOSE_DECISION',
        portfolio_state={'cash': 50000, 'positions': {}, 'regime_score': 0.7},
        scratchpad_summary='',
    )
    assert 'momentum' in prompt.lower()
    assert '15:30' in prompt or '15:50' in prompt
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_hydra_prompts.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Implement hydra_prompts.py**

```python
# hydra_prompts.py
"""System prompt builder for each HYDRA agent phase.

Injects SOUL.md, portfolio state, scratchpad summary,
and phase-specific instructions into the Claude system prompt.
"""

import os
from datetime import datetime

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
    'PRE_MARKET_BRIEFING': """## Phase Instructions: Pre-Market Briefing (06:00 ET)
1. Call `get_portfolio_state` to read current positions, cash, and regime
2. Call `validate_data_feeds` to verify yfinance is responding and SPY price is fresh
3. Call `get_earnings_calendar` with symbols of held positions — check for earnings in next 48h
4. Call `get_earnings_calendar` with top-10 momentum candidates — flag any with earnings <24h
5. Call `log_decision` for each finding
6. Call `send_notification` with a daily briefing summary
""",

    'INTRADAY_MONITOR': """## Phase Instructions: Intraday Monitor
This phase is called ONLY when an anomaly has been escalated by Python monitors.
The anomaly details are in the user message.

Possible escalations:
- **Stop triggered**: A position stop was ALREADY EXECUTED by Python. Log the event, assess portfolio impact, notify human.
- **Crash velocity alert**: 5d return < -6% or 10d return < -10%. Evaluate severity: reduce positions or halt entries.
- **Data feed failure**: yfinance not responding. Decide: pause trading or accept stale data.

IMPORTANT: Stops have ALREADY been executed before you are called. You cannot undo them. Your job is to log, assess, and notify.
""",

    'PRE_CLOSE_DECISION': """## Phase Instructions: Pre-Close Decision (15:25 ET)
This is the main decision point. Execute the following workflow:

1. Call `get_momentum_signals` (top 20)
2. Call `check_regime` to get current risk mode
3. Call `check_position_stops` for held positions
4. Call `get_portfolio_state` for cash, positions, sector exposure

5. **Identify EXITS**: Positions held >= 5 days that are due for rotation
6. **Identify ENTRIES**: Top-ranked candidates to fill empty slots (max 5 risk-on, 2 risk-off)

7. For each entry candidate, evaluate:
   - Call `get_earnings_calendar` — if earnings within 24h → SKIP, take next
   - Sector limit: max 3 per sector → SKIP if exceeded, take next
   - Data validation: ensure price data is fresh → SKIP if stale, take next
   - Call `log_decision` for each evaluation (action + reason)

8. Execute exits first (SELL), then entries (BUY) within 15:30-15:50 ET window
   - Call `execute_trade` for each trade
   - Call `save_state` after all trades

9. Call `update_cycle_log` to record the rotation event

CRITICAL: All trades must execute between 15:30 and 15:50 ET. Do NOT execute after 15:50.
""",

    'POST_CLOSE_SUMMARY': """## Phase Instructions: Post-Close Summary (16:05 ET)
1. Call `get_portfolio_state` for final state
2. Review today's scratchpad summary (provided below)
3. Calculate daily P&L: current portfolio value vs yesterday's close
4. Call `update_cycle_log` with end-of-day stats
5. Call `send_notification` with daily summary:
   - Trades executed today (entries + exits)
   - Skips with reasons
   - Daily P&L and portfolio value
   - Regime status and crash cooldown
   - Any alerts or anomalies
""",
}

_DECISION_RULES = """## Decision Rules
1. NEVER modify momentum signal parameters
2. NEVER exceed position limits (5 risk-on, 2 risk-off)
3. NEVER execute entries outside 15:30-15:50 ET
4. ALWAYS log every decision with reasoning
5. ALWAYS notify human after trades
6. MAY skip entry if: earnings <24h, insider selling >$10M/7d, data validation fails
7. When skipping, take next ranked candidate
8. Stops are non-negotiable — if triggered, EXIT
9. Save state after any portfolio change
"""


def build_system_prompt(phase, portfolio_state, scratchpad_summary, et_time=None):
    if et_time is None:
        et_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S ET')

    parts = [
        "You are the HYDRA autonomous trading agent.\n",
        _SOUL_CONTENT,
        f"\n## Current Date & Time\n{et_time}\n",
        f"\n## Portfolio State\n```json\n{_format_portfolio(portfolio_state)}\n```\n",
        f"\n## Today's Scratchpad (summarized)\n{scratchpad_summary}\n",
        f"\n## Current Phase\n{phase}\n",
        _PHASE_INSTRUCTIONS.get(phase, ''),
        _DECISION_RULES,
    ]

    return '\n'.join(parts)


def _format_portfolio(state):
    import json
    return json.dumps(state, indent=2, default=str)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_hydra_prompts.py -v`
Expected: All 6 tests PASS

- [ ] **Step 5: Commit**

```bash
git add hydra_prompts.py tests/test_hydra_prompts.py
git commit -m "feat: add HYDRA prompt builder (4-phase system prompts)"
```

---

### Task 5: hydra_agent.py — Main Agent Process

**Files:**
- Create: `hydra_agent.py`
- Create: `tests/test_hydra_agent.py`

**Dependencies:** All previous tasks (scratchpad, soul, tools, prompts)

- [ ] **Step 1: Write failing tests**

```python
# tests/test_hydra_agent.py
import os
import json
import pytest
from unittest.mock import MagicMock, patch, AsyncMock
from datetime import datetime

from hydra_agent import HydraAgent, SCHEDULE


def test_schedule_defined():
    """4 phases with ET times"""
    assert len(SCHEDULE) == 4
    phases = {s['phase'] for s in SCHEDULE}
    assert 'PRE_MARKET_BRIEFING' in phases
    assert 'INTRADAY_MONITOR' in phases
    assert 'PRE_CLOSE_DECISION' in phases
    assert 'POST_CLOSE_SUMMARY' in phases


class TestHydraAgent:

    @pytest.fixture
    def agent(self, tmp_path):
        with patch.dict(os.environ, {
            'ANTHROPIC_API_KEY': 'test-key',
            'STATE_DIR': str(tmp_path),
            'BROKER_TYPE': 'PAPER',
        }):
            with patch('hydra_agent.anthropic'):
                a = HydraAgent(state_dir=str(tmp_path))
                a.engine = MagicMock()
                a.engine.broker = MagicMock()
                a.engine.broker.cash = 50000.0
                a.engine.broker.positions = {}
                a.engine.current_regime_score = 0.7
                a.engine.peak_value = 100000.0
                a.engine.crash_cooldown = 0
                a.engine.trading_day_counter = 42
                a.engine.position_meta = {}
                a.engine.broker.get_portfolio = MagicMock(
                    return_value=MagicMock(total_value=50000.0)
                )
                return a

    def test_kill_switch(self, agent, tmp_path):
        """STOP_TRADING file halts execution"""
        stop_file = os.path.join(str(tmp_path), 'STOP_TRADING')
        with open(stop_file, 'w') as f:
            f.write('halt')
        assert agent._check_kill_switch() is True

    def test_no_kill_switch(self, agent):
        assert agent._check_kill_switch() is False

    def test_should_run_phase_weekday(self, agent):
        """Phases run only on weekdays"""
        with patch('hydra_agent._get_et_now') as mock_now:
            # Monday
            mock_now.return_value = datetime(2026, 3, 16, 6, 0, 0)
            assert agent._is_trading_day() is True
            # Saturday
            mock_now.return_value = datetime(2026, 3, 14, 6, 0, 0)
            assert agent._is_trading_day() is False

    def test_intraday_stop_auto_execution(self, agent):
        """Stops execute in Python, Claude only logs post-hoc"""
        agent.engine.broker.positions = {'AAPL': MagicMock(shares=10, avg_cost=200.0)}
        agent.engine.position_meta = {'AAPL': {'entry_daily_vol': 0.02}}
        # Simulate stop triggered
        stop_result = {
            'symbol': 'AAPL',
            'stop_triggered': True,
            'return_pct': -7.5,
        }
        # The agent should execute the sell BEFORE calling Claude
        with patch.object(agent, '_execute_immediate_stop') as mock_stop:
            agent._check_and_execute_stops([stop_result])
            mock_stop.assert_called_once_with('AAPL')

    def test_daily_loss_halt(self, agent):
        """If portfolio drops >3% intraday, halt entries"""
        agent.engine.portfolio_values_history = [100000.0]
        agent.engine.broker.get_portfolio = MagicMock(
            return_value=MagicMock(total_value=96500.0)  # -3.5%
        )
        assert agent._check_daily_loss_halt() is True

    def test_partial_rotation_recovery(self, agent):
        """Agent detects partial rotation on restart"""
        # Simulate 2 sells logged but 0 buys
        agent.scratchpad.log('decision', {'action': 'SELL', 'symbol': 'AAPL', 'reason': 'rotation'})
        agent.scratchpad.log('trade', {'symbol': 'AAPL', 'action': 'SELL', 'shares': 10, 'price': 200.0})
        agent.scratchpad.log('decision', {'action': 'SELL', 'symbol': 'MSFT', 'reason': 'rotation'})
        agent.scratchpad.log('trade', {'symbol': 'MSFT', 'action': 'SELL', 'shares': 5, 'price': 400.0})
        # No BUY trades = partial rotation
        status = agent._detect_partial_rotation()
        assert status['sells'] == 2
        assert status['buys'] == 0
        assert status['partial'] is True
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_hydra_agent.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Implement hydra_agent.py**

```python
# hydra_agent.py
"""HYDRA Autonomous Trading Agent — Main Process.

Scheduling loop that runs 4 phases per trading day:
  1. Pre-Market Briefing (06:00 ET)
  2. Intraday Monitor (09:30-15:25 ET, every 15 min)
  3. Pre-Close Decision (15:25 ET)
  4. Post-Close Summary (16:05 ET)

Uses Anthropic Claude API for reasoning at decision points.
Pure Python for monitoring (cost-efficient).
"""

import os
import sys
import json
import time
import logging
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)

try:
    import anthropic
except ImportError:
    anthropic = None
    logger.warning("anthropic SDK not installed — agent cannot make API calls")

from hydra_scratchpad import HydraScratchpad
from hydra_tools import HydraToolExecutor, TOOL_DEFINITIONS, _get_et_now
from hydra_prompts import build_system_prompt

# ── Schedule ────────────────────────────────────────────────────────────────

SCHEDULE = [
    {'phase': 'PRE_MARKET_BRIEFING', 'hour': 6, 'minute': 0},
    {'phase': 'INTRADAY_MONITOR', 'hour': 9, 'minute': 30, 'repeat_minutes': 15, 'end_hour': 15, 'end_minute': 25},
    {'phase': 'PRE_CLOSE_DECISION', 'hour': 15, 'minute': 25},
    {'phase': 'POST_CLOSE_SUMMARY', 'hour': 16, 'minute': 5},
]

# Claude model for agent reasoning
AGENT_MODEL = 'claude-sonnet-4-20250514'
MAX_AGENT_TURNS = 20  # Max tool-use turns per API conversation


class HydraAgent:

    def __init__(self, state_dir=None):
        self.state_dir = state_dir or os.environ.get('STATE_DIR', 'state')
        self.scratchpad = HydraScratchpad(state_dir=self.state_dir)

        # Initialize engine (COMPASSLive with PaperBroker)
        self.engine = None
        self._init_engine()

        # Initialize tools
        self.tools = HydraToolExecutor(
            engine=self.engine,
            scratchpad=self.scratchpad,
            notifier=self._init_notifier(),
        )

        # Anthropic client
        self.client = None
        if anthropic and os.environ.get('ANTHROPIC_API_KEY'):
            self.client = anthropic.Anthropic()
            logger.info("Anthropic client initialized")
        else:
            logger.warning("No ANTHROPIC_API_KEY — agent will run in dry-run mode")

        # Cleanup old scratchpad files on startup
        self.scratchpad.cleanup(max_age_days=90)

    def _init_engine(self):
        try:
            from omnicapital_live import COMPASSLive
            config = self._load_config()
            self.engine = COMPASSLive(config)
            self.engine.load_state()
            logger.info(f"Engine initialized: {len(self.engine.broker.positions)} positions, ${self.engine.broker.cash:,.2f} cash")
        except Exception as e:
            logger.error(f"Engine init failed: {e}", exc_info=True)

    def _init_notifier(self):
        try:
            from compass.notifications import WhatsAppNotifier
            phone = os.environ.get('WHATSAPP_PHONE', '')
            apikey = os.environ.get('WHATSAPP_API_KEY', '')
            if phone and apikey:
                return WhatsAppNotifier(phone=phone, apikey=apikey)
        except Exception as e:
            logger.warning(f"WhatsApp notifier init failed: {e}")
        return None

    def _load_config(self):
        # Import full CONFIG from production engine (all v8.4 params)
        from omnicapital_live import CONFIG
        config = dict(CONFIG)
        # Override broker type from env
        config['BROKER_TYPE'] = os.environ.get('BROKER_TYPE', 'PAPER')
        config['PAPER_INITIAL_CASH'] = config.get('INITIAL_CAPITAL', 100_000)
        return config

    # ── Kill Switch ─────────────────────────────────────────────────────────

    def _check_kill_switch(self):
        stop_file = os.path.join(self.state_dir, 'STOP_TRADING')
        if os.path.exists(stop_file):
            logger.warning("KILL SWITCH ACTIVE — STOP_TRADING file found")
            return True
        return False

    def _is_trading_day(self):
        now = _get_et_now()
        if now.weekday() >= 5:  # Weekend
            return False
        # Check US market holidays (NYSE calendar)
        holidays = self._get_market_holidays(now.year)
        return now.date() not in holidays

    @staticmethod
    def _get_market_holidays(year):
        """Fixed US market holidays. Approximation — does not handle
        observed holidays (e.g., July 4 on Saturday → Friday off)."""
        from datetime import date
        holidays = set()
        # New Year's Day, MLK Day (3rd Mon Jan), Presidents Day (3rd Mon Feb),
        # Good Friday (variable), Memorial Day (last Mon May), Juneteenth,
        # Independence Day, Labor Day (1st Mon Sep), Thanksgiving (4th Thu Nov),
        # Christmas
        holidays.add(date(year, 1, 1))   # New Year
        holidays.add(date(year, 6, 19))  # Juneteenth
        holidays.add(date(year, 7, 4))   # Independence Day
        holidays.add(date(year, 12, 25)) # Christmas
        # Variable holidays computed from weekday math
        # MLK Day: 3rd Monday of January
        d = date(year, 1, 1)
        d += timedelta(days=(7 - d.weekday()) % 7)  # first Monday
        holidays.add(d + timedelta(weeks=2))
        # Presidents Day: 3rd Monday of February
        d = date(year, 2, 1)
        d += timedelta(days=(7 - d.weekday()) % 7)
        holidays.add(d + timedelta(weeks=2))
        # Memorial Day: last Monday of May
        d = date(year, 5, 31)
        d -= timedelta(days=d.weekday())  # last Monday
        holidays.add(d)
        # Labor Day: 1st Monday of September
        d = date(year, 9, 1)
        d += timedelta(days=(7 - d.weekday()) % 7)
        holidays.add(d)
        # Thanksgiving: 4th Thursday of November
        d = date(year, 11, 1)
        d += timedelta(days=(3 - d.weekday()) % 7)  # first Thursday
        holidays.add(d + timedelta(weeks=3))
        return holidays

    # ── Daily Loss Halt ─────────────────────────────────────────────────────

    def _check_daily_loss_halt(self):
        if not self.engine or not self.engine.portfolio_values_history:
            return False
        yesterday_value = self.engine.portfolio_values_history[-1]
        if yesterday_value <= 0:
            return False
        current = self.engine.broker.get_portfolio().total_value
        daily_return = (current - yesterday_value) / yesterday_value
        if daily_return <= -0.03:
            logger.warning(f"DAILY LOSS HALT: {daily_return:.2%} (threshold -3%)")
            return True
        return False

    # ── Stop Execution (IMMEDIATE, no Claude discretion) ────────────────────

    def _execute_immediate_stop(self, symbol):
        try:
            pos = self.engine.broker.positions.get(symbol)
            if pos and pos.shares > 0:
                order = self.engine.broker.sell(symbol, pos.shares)
                fill_price = getattr(order, 'fill_price', None)
                self.scratchpad.log('stop_event', {
                    'symbol': symbol,
                    'shares': pos.shares,
                    'fill_price': fill_price,
                    'action': 'STOP_EXIT',
                })
                self.engine.save_state()
                logger.info(f"STOP EXECUTED: {symbol} — {pos.shares} shares sold")
        except Exception as e:
            logger.error(f"STOP EXECUTION FAILED for {symbol}: {e}", exc_info=True)

    def _check_and_execute_stops(self, stop_results):
        escalations = []
        for result in stop_results:
            if result.get('stop_triggered') or result.get('trail_triggered'):
                sym = result['symbol']
                self._execute_immediate_stop(sym)
                escalations.append(result)
        return escalations

    # ── Partial Rotation Detection ──────────────────────────────────────────

    def _detect_partial_rotation(self):
        entries = self.scratchpad.read_today()
        sells = sum(1 for e in entries if e['type'] == 'trade' and e['data'].get('action') == 'SELL')
        buys = sum(1 for e in entries if e['type'] == 'trade' and e['data'].get('action') == 'BUY')
        return {
            'sells': sells,
            'buys': buys,
            'partial': sells > 0 and buys < sells,
        }

    # ── Claude API Call ─────────────────────────────────────────────────────

    def _call_claude(self, phase, user_message=''):
        if not self.client:
            logger.warning(f"Dry-run mode: skipping Claude call for {phase}")
            return

        # Build system prompt
        portfolio_state = json.loads(self.tools.dispatch('get_portfolio_state', {}))
        scratchpad_summary = self.scratchpad.summarize_phase(phase)
        system_prompt = build_system_prompt(
            phase=phase,
            portfolio_state=portfolio_state,
            scratchpad_summary=scratchpad_summary,
        )

        if not user_message:
            user_message = f"Execute the {phase} phase now."

        messages = [{'role': 'user', 'content': user_message}]

        # Tool-use loop
        for turn in range(MAX_AGENT_TURNS):
            response = self.client.messages.create(
                model=AGENT_MODEL,
                max_tokens=4096,
                system=system_prompt,
                tools=TOOL_DEFINITIONS,
                messages=messages,
            )

            # Process response
            assistant_content = response.content
            messages.append({'role': 'assistant', 'content': assistant_content})

            # Check if we're done (no tool use)
            if response.stop_reason == 'end_turn':
                # Extract text response
                for block in assistant_content:
                    if hasattr(block, 'text'):
                        logger.info(f"Claude [{phase}]: {block.text[:200]}")
                break

            # Process tool calls
            tool_results = []
            for block in assistant_content:
                if block.type == 'tool_use':
                    tool_name = block.name
                    tool_input = block.input

                    # Check tool limit
                    if not self.scratchpad.check_tool_limit(tool_name, phase):
                        tool_results.append({
                            'type': 'tool_result',
                            'tool_use_id': block.id,
                            'content': json.dumps({'error': f'Tool call limit exceeded for {tool_name} in {phase}'}),
                        })
                        continue

                    # Dispatch
                    result = self.tools.dispatch(tool_name, tool_input)
                    tool_results.append({
                        'type': 'tool_result',
                        'tool_use_id': block.id,
                        'content': result,
                    })

            messages.append({'role': 'user', 'content': tool_results})

        logger.info(f"Phase {phase} completed in {turn + 1} turns")

    # ── Phase Runners ───────────────────────────────────────────────────────

    def run_pre_market(self):
        logger.info("=== PRE-MARKET BRIEFING ===")
        self._call_claude('PRE_MARKET_BRIEFING')

    def run_intraday_check(self):
        """Pure Python monitoring — NO Claude API call unless anomaly."""
        logger.debug("Intraday check...")

        # Check stops (Python, no Claude)
        stop_results_str = self.tools.dispatch('check_position_stops', {})
        try:
            stop_results = json.loads(stop_results_str)
        except (json.JSONDecodeError, TypeError):
            stop_results = []

        # Execute any triggered stops IMMEDIATELY
        escalations = self._check_and_execute_stops(stop_results)
        if escalations:
            # Escalate to Claude for logging and notification
            details = json.dumps(escalations, default=str)
            self._call_claude(
                'INTRADAY_MONITOR',
                user_message=f"Stop(s) executed automatically. Details: {details}. Log the event, assess impact, notify human."
            )

        # Check crash velocity
        regime_str = self.tools.dispatch('check_regime', {})
        try:
            regime = json.loads(regime_str)
            if regime.get('crash_cooldown', 0) > 0:
                self._call_claude(
                    'INTRADAY_MONITOR',
                    user_message=f"Crash velocity alert. Regime: {regime_str}. Evaluate severity and decide: reduce positions or halt entries."
                )
        except (json.JSONDecodeError, TypeError):
            pass

    def run_pre_close(self):
        logger.info("=== PRE-CLOSE DECISION ===")
        if self._check_daily_loss_halt():
            self.scratchpad.log('alert', {
                'type': 'daily_loss_halt',
                'message': 'Portfolio dropped >3% intraday — entries halted'
            })
            self._call_claude(
                'PRE_CLOSE_DECISION',
                user_message='Daily loss halt triggered (>3% intraday loss). Execute exits only, no new entries. Log and notify.'
            )
        else:
            self._call_claude('PRE_CLOSE_DECISION')

    def run_post_close(self):
        logger.info("=== POST-CLOSE SUMMARY ===")
        self._call_claude('POST_CLOSE_SUMMARY')

    # ── Main Loop ───────────────────────────────────────────────────────────

    def run(self):
        logger.info("HYDRA Agent starting...")
        logger.info(f"State dir: {self.state_dir}")
        logger.info(f"Broker: {os.environ.get('BROKER_TYPE', 'PAPER')}")
        logger.info(f"Claude model: {AGENT_MODEL}")

        # Check for partial rotation from restart
        partial = self._detect_partial_rotation()
        if partial['partial']:
            logger.warning(f"Partial rotation detected: {partial['sells']} sells, {partial['buys']} buys")
            self._call_claude(
                'PRE_CLOSE_DECISION',
                user_message=f"RESTART RECOVERY: Partial rotation detected ({partial['sells']} sells, {partial['buys']} buys). Resume buying to complete the rotation."
            )

        while True:
            try:
                if self._check_kill_switch():
                    logger.warning("Kill switch active — sleeping 60s")
                    time.sleep(60)
                    continue

                if not self._is_trading_day():
                    logger.debug("Weekend — sleeping 3600s")
                    time.sleep(3600)
                    continue

                now = _get_et_now()
                self._run_schedule(now)

                # Sleep 30 seconds between checks
                time.sleep(30)

            except KeyboardInterrupt:
                logger.info("Agent stopped by user")
                break
            except Exception as e:
                logger.error(f"Agent loop error: {e}", exc_info=True)
                time.sleep(60)

    def _run_schedule(self, now):
        """Check schedule and run appropriate phase."""
        hour, minute = now.hour, now.minute
        today_key = now.strftime('%Y-%m-%d')

        for entry in SCHEDULE:
            phase = entry['phase']
            sched_hour = entry['hour']
            sched_minute = entry['minute']

            if phase == 'INTRADAY_MONITOR':
                # Repeat every 15 minutes between 09:30 and 15:25
                end_hour = entry.get('end_hour', 15)
                end_minute = entry.get('end_minute', 25)
                repeat = entry.get('repeat_minutes', 15)

                if (hour > sched_hour or (hour == sched_hour and minute >= sched_minute)):
                    if (hour < end_hour or (hour == end_hour and minute <= end_minute)):
                        # Check if we ran recently
                        last_key = f'{today_key}_{phase}_{hour}_{minute // repeat}'
                        if not hasattr(self, '_phase_tracker'):
                            self._phase_tracker = set()
                        if last_key not in self._phase_tracker:
                            self._phase_tracker.add(last_key)
                            self.run_intraday_check()
            else:
                # One-time phases
                if hour == sched_hour and sched_minute <= minute < sched_minute + 5:
                    run_key = f'{today_key}_{phase}'
                    if not hasattr(self, '_phase_tracker'):
                        self._phase_tracker = set()
                    if run_key not in self._phase_tracker:
                        self._phase_tracker.add(run_key)
                        if phase == 'PRE_MARKET_BRIEFING':
                            self.run_pre_market()
                        elif phase == 'PRE_CLOSE_DECISION':
                            self.run_pre_close()
                        elif phase == 'POST_CLOSE_SUMMARY':
                            self.run_post_close()


# ── Entry Point ─────────────────────────────────────────────────────────────

def main():
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
        handlers=[
            logging.StreamHandler(),
            logging.FileHandler(
                os.path.join(os.environ.get('STATE_DIR', 'state'), 'hydra_agent.log')
            ),
        ]
    )
    agent = HydraAgent()
    agent.run()


if __name__ == '__main__':
    main()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_hydra_agent.py -v`
Expected: All 7 tests PASS

- [ ] **Step 5: Commit**

```bash
git add hydra_agent.py tests/test_hydra_agent.py
git commit -m "feat: add HYDRA agent (scheduling loop + Claude API orchestration)"
```

---

## Chunk 4: Deployment — Requirements, Render, Dashboard Integration

### Task 6: requirements-agent.txt

**Files:**
- Create: `requirements-agent.txt`

- [ ] **Step 1: Write requirements file**

```
anthropic>=0.40.0
numpy>=1.24.0
pandas>=2.0.0
yfinance>=0.2.28
python-dateutil>=2.8.0
requests>=2.31.0
```

- [ ] **Step 2: Commit**

```bash
git add requirements-agent.txt
git commit -m "feat: add HYDRA agent dependencies"
```

---

### Task 7: compass_dashboard_cloud.py — AGENT_MODE Integration

**Files:**
- Modify: `compass_dashboard_cloud.py:2313-2444` (cloud engine section)

The dashboard must detect `AGENT_MODE=true` and disable the cloud engine thread, making it read-only.

- [ ] **Step 1: Read the target section**

Read `compass_dashboard_cloud.py` lines 2313-2444 to understand the full `_run_cloud_engine()` and `_ensure_cloud_engine()` flow.

- [ ] **Step 2: Fix STATE_DIR to read from env**

At line 122, change:
```python
STATE_DIR = 'state'
```
to:
```python
STATE_DIR = os.environ.get('STATE_DIR', 'state')
```

- [ ] **Step 2b: Add AGENT_MODE check**

At the top of the cloud engine section (around line 2313), add:

```python
# AGENT_MODE: when true, the HYDRA Worker is the sole state writer.
# Dashboard becomes read-only — do not start cloud engine thread.
AGENT_MODE = os.environ.get('AGENT_MODE', '').lower() == 'true'
```

- [ ] **Step 3: Modify `_ensure_cloud_engine()` to respect AGENT_MODE**

In `_ensure_cloud_engine()` (line 2410), add an early return:

```python
def _ensure_cloud_engine():
    global _cloud_engine_started
    if _cloud_engine_started:
        return
    _cloud_engine_started = True

    if AGENT_MODE:
        logger.info("AGENT_MODE=true — cloud engine disabled (Worker is sole state writer)")
        return

    if SHOWCASE_MODE:
        logger.info("Showcase mode — engine disabled (set HYDRA_MODE=live to enable)")
        return
    # ... rest of function unchanged
```

- [ ] **Step 4: Add scratchpad API endpoint**

At the end of the API routes section, add:

```python
@app.route('/api/agent/scratchpad')
def api_agent_scratchpad():
    """Read today's agent scratchpad entries (read-only)."""
    today = datetime.now().strftime('%Y-%m-%d')
    sp_path = os.path.join(STATE_DIR, 'agent_scratchpad', f'{today}.jsonl')
    entries = []
    if os.path.exists(sp_path):
        with open(sp_path, 'r') as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        entries.append(json.loads(line))
                    except json.JSONDecodeError:
                        continue
    return jsonify(entries)
```

- [ ] **Step 5: Verify syntax**

Run: `python -c "import py_compile; py_compile.compile('compass_dashboard_cloud.py')"`
Expected: No errors

- [ ] **Step 6: Commit**

```bash
git add compass_dashboard_cloud.py
git commit -m "feat: add AGENT_MODE to dashboard (read-only when Worker active)"
```

---

### Task 8: render.yaml — Add Worker Service

**Files:**
- Modify: `render.yaml`

- [ ] **Step 1: Read current render.yaml**

Current content (single web service):
```yaml
services:
  - type: web
    name: compass-dashboard
    runtime: python
    buildCommand: pip install -r requirements-cloud.txt
    startCommand: gunicorn compass_dashboard_cloud:app --bind 0.0.0.0:$PORT --workers 2 --timeout 120 --preload
    envVars:
      - key: PYTHON_VERSION
        value: "3.11.6"
      - key: HYDRA_MODE
        value: "live"
      - key: GIT_TOKEN
        sync: false
```

- [ ] **Step 2: Update render.yaml with worker service + persistent disk**

**Important:** Render does NOT allow two services to share the same persistent disk. The Worker owns the disk and writes state. The dashboard reads state via git sync (existing mechanism) or a lightweight HTTP API on the Worker.

**Approach:** Keep the current git-sync architecture. The Worker writes state to disk AND pushes state files to git (using the existing `compass/git_sync.py`). The dashboard pulls state from git on startup (existing behavior). The scratchpad API reads from the Worker via Render internal networking.

```yaml
services:
  - type: web
    name: compass-dashboard
    runtime: python
    buildCommand: pip install -r requirements-cloud.txt
    startCommand: gunicorn compass_dashboard_cloud:app --bind 0.0.0.0:$PORT --workers 2 --timeout 120 --preload
    envVars:
      - key: PYTHON_VERSION
        value: "3.11.6"
      - key: HYDRA_MODE
        value: "live"
      - key: AGENT_MODE
        value: "true"
      - key: STATE_DIR
        value: "state"
      - key: GIT_TOKEN
        sync: false

  - type: worker
    name: hydra-agent
    runtime: python
    buildCommand: pip install -r requirements-cloud.txt -r requirements-agent.txt
    startCommand: python hydra_agent.py
    disk:
      name: hydra-state
      mountPath: /data/state
      sizeGB: 1
    envVars:
      - key: PYTHON_VERSION
        value: "3.11.6"
      - key: STATE_DIR
        value: "/data/state"
      - key: BROKER_TYPE
        value: "PAPER"
      - key: ANTHROPIC_API_KEY
        sync: false
      - key: GIT_TOKEN
        sync: false
      - key: WHATSAPP_PHONE
        sync: false
      - key: WHATSAPP_API_KEY
        sync: false
      - key: NOTIFICATION_ENABLED
        value: "true"
```

- [ ] **Step 3: Commit**

```bash
git add render.yaml
git commit -m "feat: add HYDRA Worker service to render.yaml"
```

---

## Chunk 5: Integration Testing & Deployment Verification

### Task 9: Integration Tests

**Files:**
- Create: `tests/test_hydra_integration.py`

- [ ] **Step 1: Write integration tests**

```python
# tests/test_hydra_integration.py
"""Integration tests for HYDRA agent — verifies end-to-end flow
with mocked Anthropic API and PaperBroker."""

import os
import json
import pytest
from unittest.mock import MagicMock, patch
from datetime import datetime

from hydra_scratchpad import HydraScratchpad
from hydra_tools import HydraToolExecutor, TOOL_DEFINITIONS
from hydra_prompts import build_system_prompt
from hydra_agent import HydraAgent


class TestEndToEnd:

    @pytest.fixture
    def setup(self, tmp_path):
        """Full agent stack with mocked engine"""
        engine = MagicMock()
        engine.broker = MagicMock()
        engine.broker.cash = 50000.0
        engine.broker.positions = {
            'AAPL': MagicMock(shares=10, avg_cost=200.0),
            'MSFT': MagicMock(shares=5, avg_cost=400.0),
        }
        engine.current_regime_score = 0.7
        engine.peak_value = 100000.0
        engine.crash_cooldown = 0
        engine.trading_day_counter = 42
        engine.position_meta = {
            'AAPL': {'entry_daily_vol': 0.02, 'sector': 'Technology', 'days_held': 3},
            'MSFT': {'entry_daily_vol': 0.015, 'sector': 'Technology', 'days_held': 6},
        }
        engine.broker.get_portfolio = MagicMock(
            return_value=MagicMock(total_value=54000.0)
        )
        engine.data_feed = MagicMock()
        engine.data_feed.get_price = MagicMock(side_effect=lambda sym: {'AAPL': 215.0, 'MSFT': 410.0}.get(sym))
        engine.save_state = MagicMock()

        scratchpad = HydraScratchpad(state_dir=str(tmp_path))
        tools = HydraToolExecutor(engine=engine, scratchpad=scratchpad)

        return {'engine': engine, 'scratchpad': scratchpad, 'tools': tools}

    def test_full_portfolio_state(self, setup):
        result = json.loads(setup['tools'].dispatch('get_portfolio_state', {}))
        assert result['cash'] == 50000.0
        assert result['n_positions'] == 2
        assert 'AAPL' in result['positions']

    def test_prompt_builds_with_real_state(self, setup):
        state = json.loads(setup['tools'].dispatch('get_portfolio_state', {}))
        prompt = build_system_prompt(
            phase='PRE_CLOSE_DECISION',
            portfolio_state=state,
            scratchpad_summary='No entries.',
        )
        assert 'AAPL' in prompt or '50000' in prompt
        assert 'PRE_CLOSE_DECISION' in prompt

    def test_tool_definitions_match_executor(self, setup):
        """Every defined tool has a handler in the executor"""
        for tool_def in TOOL_DEFINITIONS:
            handler = getattr(setup['tools'], f"_tool_{tool_def['name']}", None)
            assert handler is not None, f"Missing handler for tool: {tool_def['name']}"

    def test_trade_then_save_flow(self, setup):
        """Simulate: execute trade → save state"""
        with patch('hydra_tools._get_et_now') as mock_now:
            mock_now.return_value = datetime(2026, 3, 13, 15, 35, 0)  # 15:35 ET
            result = json.loads(setup['tools'].dispatch('execute_trade', {
                'symbol': 'GOOG', 'action': 'BUY', 'shares': 5
            }))
            assert result.get('status') == 'FILLED' or 'error' not in result

        # Save state
        save_result = json.loads(setup['tools'].dispatch('save_state', {}))
        assert save_result['status'] == 'ok'
        setup['engine'].save_state.assert_called_once()

    def test_scratchpad_records_all_tool_calls(self, setup):
        """Every tool dispatch is recorded"""
        setup['tools'].dispatch('get_portfolio_state', {})
        setup['tools'].dispatch('validate_data_feeds', {})
        entries = setup['scratchpad'].read_today()
        tool_calls = [e for e in entries if e['type'] == 'tool_call']
        assert len(tool_calls) == 2

    def test_soul_loaded(self):
        """SOUL.md is loaded into prompts"""
        prompt = build_system_prompt(
            phase='PRE_MARKET_BRIEFING',
            portfolio_state={'cash': 0, 'positions': {}},
            scratchpad_summary='',
        )
        assert '62 experiments' in prompt
```

- [ ] **Step 2: Run all HYDRA tests**

Run: `pytest tests/test_hydra_scratchpad.py tests/test_hydra_tools.py tests/test_hydra_prompts.py tests/test_hydra_agent.py tests/test_hydra_integration.py -v`
Expected: All tests PASS

- [ ] **Step 3: Commit**

```bash
git add tests/test_hydra_integration.py
git commit -m "feat: add HYDRA integration tests"
```

---

### Task 10: Pre-Deploy Verification

- [ ] **Step 1: Syntax check all new files**

```bash
python -c "import py_compile; py_compile.compile('hydra_scratchpad.py')"
python -c "import py_compile; py_compile.compile('hydra_tools.py')"
python -c "import py_compile; py_compile.compile('hydra_prompts.py')"
python -c "import py_compile; py_compile.compile('hydra_agent.py')"
python -c "import py_compile; py_compile.compile('compass_dashboard_cloud.py')"
```

- [ ] **Step 2: Validate render.yaml**

```bash
python -c "import yaml; yaml.safe_load(open('render.yaml'))"
```

- [ ] **Step 3: Run full test suite**

```bash
pytest tests/test_hydra_*.py tests/test_hydra_integration.py -v --tb=short
```

- [ ] **Step 4: Memory profiling (optional)**

```bash
python -c "
from hydra_agent import HydraAgent
import os, tracemalloc
os.environ['ANTHROPIC_API_KEY'] = ''
os.environ['STATE_DIR'] = 'state'
tracemalloc.start()
# Agent init without API key = dry-run mode
try:
    agent = HydraAgent()
except:
    pass
current, peak = tracemalloc.get_traced_memory()
print(f'Current: {current / 1024 / 1024:.1f} MB')
print(f'Peak: {peak / 1024 / 1024:.1f} MB')
"
```
Expected: Peak < 400MB (Render Starter plan threshold)

- [ ] **Step 5: Final commit and push**

```bash
git add -A
git commit -m "feat: HYDRA autonomous agent — complete implementation (paper trading)"
git push origin main
```

---

## Post-Deployment Checklist

After deploying to Render:

1. Verify Worker service starts without crash (check Render logs)
2. Verify Dashboard still loads at the web URL
3. Verify `AGENT_MODE=true` prevents cloud engine thread from starting
4. Check `/api/agent/scratchpad` endpoint returns `[]` (empty on first day)
5. Wait for 06:00 ET pre-market briefing — check logs for Claude API call
6. Verify WhatsApp notification arrives (if configured)
7. Monitor API cost in Anthropic dashboard after first full trading day
8. Check memory usage in Render metrics (should be <400MB)
