import pytest
from compass.sp500_universe import _normalize_tickers, _validate_count


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
