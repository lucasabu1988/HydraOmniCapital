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
    """Calls beyond MAX_TOOL_CALLS_PER_PHASE are blocked"""
    from hydra_scratchpad import MAX_TOOL_CALLS_PER_PHASE
    for i in range(MAX_TOOL_CALLS_PER_PHASE + 1):
        result = scratchpad.check_tool_limit('get_momentum_signals', 'PRE_CLOSE')
    assert result is False  # call beyond limit blocked


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


def test_cleanup_is_noop(scratchpad):
    """cleanup() is a stub — does not raise"""
    scratchpad.cleanup(max_age_days=90)


def test_summarize_phase(scratchpad):
    scratchpad.log('briefing', {'summary': 'morning check'})
    scratchpad.log('alert', {'type': 'data_feed', 'message': 'SPY stale'})
    summary = scratchpad.summarize_phase('PRE_MARKET')
    assert 'briefing' in summary.lower() or 'alert' in summary.lower()
