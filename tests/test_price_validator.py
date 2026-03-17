import math
import sys
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import omnicapital_live as live


def make_validator():
    return live.DataValidator({
        'MIN_VALID_PRICE': 1.0,
        'MAX_VALID_PRICE': 1000.0,
        'MAX_PRICE_CHANGE_PCT': 0.50,
    })


def test_is_valid_price_accepts_normal_price():
    validator = make_validator()

    assert validator.is_valid_price('AAPL', 150.0) is True


def test_is_valid_price_rejects_zero():
    validator = make_validator()

    assert validator.is_valid_price('AAPL', 0.0) is False


def test_is_valid_price_rejects_negative_price():
    validator = make_validator()

    assert validator.is_valid_price('AAPL', -5.0) is False


def test_is_valid_price_rejects_nan():
    validator = make_validator()

    assert validator.is_valid_price('AAPL', float('nan')) is False


def test_validate_price_freshness_accepts_recent_price():
    validator = make_validator()
    validator._price_history['AAPL'] = [(datetime.now() - timedelta(minutes=1), 150.0)]

    assert validator.validate_price_freshness('AAPL', max_age_seconds=300) is True


def test_validate_price_freshness_rejects_stale_price():
    validator = make_validator()
    validator._price_history['AAPL'] = [(datetime.now() - timedelta(hours=2), 150.0)]

    assert validator.validate_price_freshness('AAPL', max_age_seconds=300) is False


def test_validate_batch_filters_invalid_prices_and_records_valid_ones():
    validator = make_validator()
    prices = {f'SYM{i}': 100.0 + i for i in range(10)}
    prices['ZERO'] = 0.0
    prices['NAN'] = float('nan')

    valid = validator.validate_batch(prices)

    assert len(valid) == 10
    assert 'ZERO' not in valid
    assert 'NAN' not in valid
    assert validator.get_stats()['total_validated'] == 12
    assert validator.get_stats()['total_rejected'] == 1
    assert validator.get_stats()['symbols_tracked'] == 10


def test_record_price_and_get_stats_track_symbols_and_history():
    validator = make_validator()

    validator.record_price('AAPL', 100.0)
    validator.record_price('AAPL', 105.0)
    validator.record_price('MSFT', 200.0)

    stats = validator.get_stats()

    assert stats['symbols_tracked'] == 2
    assert stats['total_validated'] == 0
    assert stats['total_rejected'] == 0
    assert stats['rejection_rate'] == 0.0
    assert len(validator._price_history['AAPL']) == 2
    assert math.isclose(validator._price_history['AAPL'][-1][1], 105.0)
