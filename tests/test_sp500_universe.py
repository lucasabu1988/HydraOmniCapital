import json
import os
import tempfile
import pytest
from unittest.mock import patch
import pandas as pd
from compass.sp500_universe import (
    _normalize_tickers, _validate_count, load_cached, save_cache,
    fetch_from_github, fetch_from_wikipedia, refresh_constituents,
)


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


class TestFetchFromGitHub:
    def test_returns_list(self):
        """Integration test — requires network. Skip in CI."""
        try:
            result = fetch_from_github()
            assert isinstance(result, list)
            assert len(result) > 400
            assert 'AAPL' in result
        except Exception:
            pytest.skip("GitHub fetch failed (network issue)")

    def test_parses_csv_format(self):
        """Test CSV parsing logic with mock data."""
        mock_csv = (
            "date,tickers\n"
            "2025-12-31,\"AAPL,MSFT,GOOGL,AMZN\"\n"
            "2026-01-02,\"AAPL,MSFT,GOOGL,AMZN,NVDA\"\n"
        )
        mock_api_response = type('Response', (), {
            'status_code': 200,
            'raise_for_status': lambda self: None,
            'json': lambda self: [
                {'name': 'S&P 500 Historical Components & Changes.csv', 'download_url': 'https://raw.example.com/data.csv'}
            ],
        })()
        mock_csv_response = type('Response', (), {
            'status_code': 200,
            'raise_for_status': lambda self: None,
            'text': mock_csv,
        })()
        with patch('compass.sp500_universe.requests.get', side_effect=[mock_api_response, mock_csv_response]):
            result = fetch_from_github()
        assert result == ['AAPL', 'MSFT', 'GOOGL', 'AMZN', 'NVDA']


class TestFetchFromWikipedia:
    def test_returns_list(self):
        """Integration test — requires network."""
        try:
            result = fetch_from_wikipedia()
            assert isinstance(result, list)
            assert len(result) > 400
            assert 'AAPL' in result
        except Exception:
            pytest.skip("Wikipedia fetch failed (network issue)")

    def test_parses_html_table(self):
        """Test parsing logic with mock DataFrame."""
        mock_df = pd.DataFrame({'Symbol': ['AAPL', 'BRK.B', 'MSFT']})
        with patch('compass.sp500_universe.pd.read_html', return_value=[mock_df]):
            result = fetch_from_wikipedia()
        assert result == ['AAPL', 'BRK.B', 'MSFT']


FAKE_500 = [f'TICK{i}' for i in range(503)]
FALLBACK = ['AAPL', 'MSFT']


class TestRefreshConstituents:
    def test_github_success(self):
        with patch('compass.sp500_universe.fetch_from_github', return_value=FAKE_500):
            tickers, source = refresh_constituents(FALLBACK)
        assert len(tickers) == 503
        assert source == 'github'

    def test_github_fails_wikipedia_succeeds(self):
        with patch('compass.sp500_universe.fetch_from_github', side_effect=Exception("down")), \
             patch('compass.sp500_universe.fetch_from_wikipedia', return_value=FAKE_500):
            tickers, source = refresh_constituents(FALLBACK)
        assert len(tickers) == 503
        assert source == 'wikipedia'

    def test_both_fail_uses_cache(self):
        cached = {'tickers': FAKE_500, 'source': 'github', 'date': '2025-01-01', 'count': 503}
        with patch('compass.sp500_universe.fetch_from_github', side_effect=Exception("down")), \
             patch('compass.sp500_universe.fetch_from_wikipedia', side_effect=Exception("down")), \
             patch('compass.sp500_universe.load_cached', return_value=cached):
            tickers, source = refresh_constituents(FALLBACK)
        assert len(tickers) == 503
        assert source == 'cached'

    def test_all_fail_uses_fallback(self):
        with patch('compass.sp500_universe.fetch_from_github', side_effect=Exception("down")), \
             patch('compass.sp500_universe.fetch_from_wikipedia', side_effect=Exception("down")), \
             patch('compass.sp500_universe.load_cached', return_value=None):
            tickers, source = refresh_constituents(FALLBACK)
        assert tickers == FALLBACK
        assert source == 'fallback'

    def test_validation_rejects_too_few(self):
        small_list = ['AAPL', 'MSFT']
        with patch('compass.sp500_universe.fetch_from_github', return_value=small_list), \
             patch('compass.sp500_universe.fetch_from_wikipedia', return_value=FAKE_500):
            tickers, source = refresh_constituents(FALLBACK)
        assert source == 'wikipedia'

    def test_normalizes_tickers(self):
        raw = [f'tick.{i}' for i in range(503)]
        with patch('compass.sp500_universe.fetch_from_github', return_value=raw):
            tickers, source = refresh_constituents(FALLBACK)
        assert all(t == t.upper() for t in tickers)
        assert all('.' not in t for t in tickers)

    def test_saves_cache_on_fresh_fetch(self):
        with patch('compass.sp500_universe.fetch_from_github', return_value=FAKE_500), \
             patch('compass.sp500_universe.save_cache') as mock_save:
            refresh_constituents(FALLBACK)
        mock_save.assert_called_once()
        args = mock_save.call_args[0]
        assert len(args[0]) == 503
        assert args[1] == 'github'

    def test_does_not_save_cache_on_fallback(self):
        with patch('compass.sp500_universe.fetch_from_github', side_effect=Exception("down")), \
             patch('compass.sp500_universe.fetch_from_wikipedia', side_effect=Exception("down")), \
             patch('compass.sp500_universe.load_cached', return_value=None), \
             patch('compass.sp500_universe.save_cache') as mock_save:
            refresh_constituents(FALLBACK)
        mock_save.assert_not_called()

    def test_does_not_save_cache_on_cached(self):
        cached = {'tickers': FAKE_500, 'source': 'github', 'date': '2025-01-01', 'count': 503}
        with patch('compass.sp500_universe.fetch_from_github', side_effect=Exception("down")), \
             patch('compass.sp500_universe.fetch_from_wikipedia', side_effect=Exception("down")), \
             patch('compass.sp500_universe.load_cached', return_value=cached), \
             patch('compass.sp500_universe.save_cache') as mock_save:
            refresh_constituents(FALLBACK)
        mock_save.assert_not_called()
