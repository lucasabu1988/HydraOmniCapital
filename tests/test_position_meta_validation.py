import sys
from datetime import date
from pathlib import Path
from unittest.mock import MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

import omnicapital_live as live


def make_engine():
    engine = object.__new__(live.COMPASSLive)
    engine.position_meta = {}
    return engine


class TestValidatePositionMeta:

    def test_negative_entry_price_corrected(self):
        engine = make_engine()
        meta = {
            'AAPL': {
                'entry_price': -5,
                'entry_date': '2026-03-01',
                'sector': 'Technology',
            }
        }
        positions = {'AAPL': MagicMock()}
        result = engine._validate_position_meta(meta, positions)
        assert result['AAPL']['entry_price'] == 0.0

    def test_zero_entry_price_corrected(self):
        engine = make_engine()
        meta = {
            'MSFT': {
                'entry_price': 0,
                'entry_date': '2026-03-01',
                'sector': 'Technology',
            }
        }
        positions = {'MSFT': MagicMock()}
        result = engine._validate_position_meta(meta, positions)
        assert result['MSFT']['entry_price'] == 0.0

    def test_invalid_entry_date_corrected(self):
        engine = make_engine()
        meta = {
            'AAPL': {
                'entry_price': 150.0,
                'entry_date': 'not-a-date',
                'sector': 'Technology',
            }
        }
        positions = {'AAPL': MagicMock()}
        result = engine._validate_position_meta(meta, positions)
        assert result['AAPL']['entry_date'] == date.today().isoformat()

    def test_missing_entry_date_corrected(self):
        engine = make_engine()
        meta = {
            'AAPL': {
                'entry_price': 150.0,
                'sector': 'Technology',
            }
        }
        positions = {'AAPL': MagicMock()}
        result = engine._validate_position_meta(meta, positions)
        assert result['AAPL']['entry_date'] == date.today().isoformat()

    def test_stale_symbols_removed(self):
        engine = make_engine()
        meta = {
            'AAPL': {
                'entry_price': 150.0,
                'entry_date': '2026-03-01',
                'sector': 'Technology',
            },
            'GONE': {
                'entry_price': 50.0,
                'entry_date': '2026-01-01',
                'sector': 'Financials',
            },
        }
        positions = {'AAPL': MagicMock()}  # GONE not in positions
        result = engine._validate_position_meta(meta, positions)
        assert 'AAPL' in result
        assert 'GONE' not in result

    def test_empty_sector_corrected(self):
        engine = make_engine()
        meta = {
            'AAPL': {
                'entry_price': 150.0,
                'entry_date': '2026-03-01',
                'sector': '',
            }
        }
        positions = {'AAPL': MagicMock()}
        result = engine._validate_position_meta(meta, positions)
        assert result['AAPL']['sector'] == 'Unknown'

    def test_invalid_entry_vol_corrected(self):
        engine = make_engine()
        meta = {
            'AAPL': {
                'entry_price': 150.0,
                'entry_date': '2026-03-01',
                'sector': 'Technology',
                'entry_vol': -0.5,
            }
        }
        positions = {'AAPL': MagicMock()}
        result = engine._validate_position_meta(meta, positions)
        assert result['AAPL']['entry_vol'] == 0.01

    def test_invalid_entry_daily_vol_corrected(self):
        engine = make_engine()
        meta = {
            'AAPL': {
                'entry_price': 150.0,
                'entry_date': '2026-03-01',
                'sector': 'Technology',
                'entry_daily_vol': 'bad',
            }
        }
        positions = {'AAPL': MagicMock()}
        result = engine._validate_position_meta(meta, positions)
        assert result['AAPL']['entry_daily_vol'] == 0.01

    def test_valid_meta_passes_through(self):
        engine = make_engine()
        meta = {
            'AAPL': {
                'entry_price': 150.0,
                'entry_date': '2026-03-01',
                'sector': 'Technology',
                'entry_vol': 0.25,
                'entry_daily_vol': 0.02,
            }
        }
        positions = {'AAPL': MagicMock()}
        result = engine._validate_position_meta(meta, positions)
        assert result['AAPL']['entry_price'] == 150.0
        assert result['AAPL']['entry_date'] == '2026-03-01'
        assert result['AAPL']['sector'] == 'Technology'
        assert result['AAPL']['entry_vol'] == 0.25
        assert result['AAPL']['entry_daily_vol'] == 0.02
