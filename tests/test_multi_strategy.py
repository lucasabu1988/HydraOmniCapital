import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

import omnicapital_live as live


class DummyFeed:
    def __init__(self, prices=None):
        self.prices = dict(prices or {})

    def get_prices(self, symbols):
        return {symbol: self.prices[symbol] for symbol in symbols if symbol in self.prices}

    def get_price(self, symbol):
        return self.prices.get(symbol)

    def get_cache_age_seconds(self):
        return 0


def write_json(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding='utf-8')


def position_meta(symbol, entry_price, sector, **extra):
    payload = {
        'entry_price': entry_price,
        'entry_date': '2026-03-16',
        'entry_day_index': 3,
        'original_entry_day_index': 3,
        'high_price': entry_price,
        'entry_vol': 0.25,
        'entry_daily_vol': 0.016,
        'sector': sector,
    }
    payload.update(extra)
    return payload


def make_state():
    capital = live.HydraCapitalManager(100000.0)
    capital.efa_value = 2100.0
    capital.catalyst_account = 15000.0
    capital.compass_account = 82900.0

    base_universe = ['JNJ', 'GEV']
    for symbol in live.BROAD_POOL:
        if symbol in base_universe or symbol in {'TLT', 'GLD', 'DBC', live.EFA_SYMBOL}:
            continue
        base_universe.append(symbol)
        if len(base_universe) == 40:
            break

    return {
        'version': '8.4',
        'timestamp': '2026-03-16T15:35:00',
        'cash': 77560.0,
        'peak_value': 100000.0,
        'portfolio_value': 100000.0,
        'crash_cooldown': 0,
        'portfolio_values_history': [100000.0],
        'current_regime_score': 0.55,
        'trading_day_counter': 3,
        'last_trading_date': '2026-03-16',
        'positions': {
            'JNJ': {'shares': 10.0, 'avg_cost': 150.0},
            'GEV': {'shares': 10.0, 'avg_cost': 200.0},
            'TLT': {'shares': 20.0, 'avg_cost': 90.0},
            'GLD': {'shares': 5.0, 'avg_cost': 180.0},
            'DBC': {'shares': 40.0, 'avg_cost': 25.0},
            live.EFA_SYMBOL: {'shares': 30.0, 'avg_cost': 70.0},
        },
        'position_meta': {
            'JNJ': position_meta('JNJ', 150.0, 'Healthcare'),
            'GEV': position_meta('GEV', 200.0, 'Industrials'),
            'TLT': position_meta('TLT', 90.0, 'Catalyst (trend)', _catalyst=True),
            'GLD': position_meta('GLD', 180.0, 'Catalyst (gold)', _catalyst=True),
            'DBC': position_meta('DBC', 25.0, 'Catalyst (trend)', _catalyst=True),
            live.EFA_SYMBOL: position_meta(
                live.EFA_SYMBOL,
                70.0,
                'International Equity',
                _efa=True,
            ),
        },
        'current_universe': base_universe,
        'universe_year': 2026,
        '_universe_source': '',
        '_daily_open_done': True,
        '_preclose_entries_done': False,
        'overlay': {},
        'hydra': {
            'available': True,
            'rattle_positions': [],
            'rattle_regime': 'RISK_ON',
            'vix_current': 18.0,
            'efa_position': None,
            'catalyst_positions': [
                {'symbol': 'TLT', 'shares': 20.0, 'entry_price': 90.0, 'sub_strategy': 'trend'},
                {'symbol': 'GLD', 'shares': 5.0, 'entry_price': 180.0, 'sub_strategy': 'gold'},
                {'symbol': 'DBC', 'shares': 40.0, 'entry_price': 25.0, 'sub_strategy': 'trend'},
            ],
            'catalyst_day_counter': 2,
            'capital_manager': capital.to_dict(),
        },
        '_pre_rotation_positions_data': {},
        '_pre_rotation_cash': None,
        '_pre_rotation_value': None,
        'stats': {
            'cycles_completed': 0,
            'engine_iterations': 1,
            'uptime_minutes': 5,
        },
        'ml_error_counts': {
            'entry': 0,
            'exit': 0,
            'hold': 0,
            'skip': 0,
            'snapshot': 0,
        },
    }


@pytest.fixture
def trader(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(live, '_git_sync_available', False, raising=False)
    monkeypatch.setattr(live, '_ml_available', False, raising=False)
    monkeypatch.setattr(live, '_overlay_available', False, raising=False)
    monkeypatch.setattr(live, '_hydra_available', True, raising=False)
    feed = DummyFeed()
    monkeypatch.setattr(live, 'YahooDataFeed', lambda cache_duration: feed)
    monkeypatch.setattr(live.COMPASSLive, '_ensure_active_cycle', lambda self: None)

    config = live.CONFIG.copy()
    config['BROKER_TYPE'] = 'PAPER'
    config['PAPER_INITIAL_CASH'] = 100000

    trader = live.COMPASSLive(config)
    trader.broker.connect()
    trader.broker.fill_delay = 0
    trader.test_feed = feed
    return trader


def test_multi_strategy_positions_do_not_interfere_across_pillars(trader, tmp_path, monkeypatch):
    write_json(tmp_path / 'state' / 'compass_state_latest.json', make_state())
    trader.load_state()

    prices = {
        'JNJ': 151.0,
        'GEV': 195.0,
        'TLT': 88.0,
        'GLD': 182.0,
        'DBC': 26.0,
        live.EFA_SYMBOL: 72.0,
    }
    trader.test_feed.prices = dict(prices)

    monkeypatch.setattr(trader, 'get_max_positions', lambda: 5)
    trader.check_position_exits(prices)

    assert trader.trades_today == []
    assert set(trader.broker.get_positions()) == {'JNJ', 'GEV', 'TLT', 'GLD', 'DBC', live.EFA_SYMBOL}

    trader.current_universe = [symbol for symbol in trader.current_universe if symbol != 'GEV']
    trader.check_position_exits(prices)

    remaining = set(trader.broker.get_positions())
    assert 'GEV' not in remaining
    assert {'JNJ', 'TLT', 'GLD', 'DBC', live.EFA_SYMBOL} <= remaining
    assert len(trader.trades_today) == 1
    assert trader.trades_today[0]['symbol'] == 'GEV'
    assert trader.trades_today[0]['exit_reason'] == 'universe_rotation'
    assert all(
        trade['symbol'] not in {'TLT', 'GLD', 'DBC', live.EFA_SYMBOL}
        for trade in trader.trades_today
    )
