import json
import os
import tempfile
import pytest
from unittest.mock import patch
from compass.sp500_universe import _normalize_tickers, _validate_count, load_cached, save_cache


class TestNormalizeTickers:
    def test_dot_to_dash(self):
        assert 'BRK-B' in _normalize_tickers(['BRK.B'])

    def test_uppercase(self):
        assert 'AAPL' in _normalize_tickers(['aapl'])

    def test_strip_whitespace(self):
        assert 'MSFT' in _normalize_tickers([' MSFT '])

    def test_deduplicate(self):
        result = _normalize_tickers(['AAPL', 'AAPL', 'aapl'])
        assert result.count('AAPL') == 1

    def test_empty_list(self):
        assert _normalize_tickers([]) == []

    def test_mixed(self):
        result = _normalize_tickers([' brk.b ', 'AAPL', 'aapl', 'MSFT'])
        assert sorted(result) == ['AAPL', 'BRK-B', 'MSFT']


class TestValidateCount:
    def test_valid_503(self):
        assert _validate_count(['X'] * 503) is True

    def test_valid_400(self):
        assert _validate_count(['X'] * 400) is True

    def test_valid_600(self):
        assert _validate_count(['X'] * 600) is True

    def test_too_few(self):
        assert _validate_count(['X'] * 399) is False

    def test_too_many(self):
        assert _validate_count(['X'] * 601) is False

    def test_empty(self):
        assert _validate_count([]) is False


class TestCacheOperations:
    def setup_method(self):
        self.tmp_dir = tempfile.mkdtemp()
        self.tmp_cache = os.path.join(self.tmp_dir, 'sp500_constituents.json')

    def teardown_method(self):
        if os.path.exists(self.tmp_cache):
            os.remove(self.tmp_cache)
        os.rmdir(self.tmp_dir)

    def test_save_and_load(self):
        tickers = ['AAPL', 'MSFT', 'GOOGL']
        with patch('compass.sp500_universe.CACHE_FILE', self.tmp_cache):
            save_cache(tickers, 'github')
            result = load_cached()
        assert result is not None
        assert result['tickers'] == tickers
        assert result['source'] == 'github'
        assert result['count'] == 3
        assert 'date' in result

    def test_load_missing_file(self):
        with patch('compass.sp500_universe.CACHE_FILE', '/nonexistent/path.json'):
            result = load_cached()
        assert result is None

    def test_load_corrupt_json(self):
        with open(self.tmp_cache, 'w') as f:
            f.write('not valid json{{{')
        with patch('compass.sp500_universe.CACHE_FILE', self.tmp_cache):
            result = load_cached()
        assert result is None
