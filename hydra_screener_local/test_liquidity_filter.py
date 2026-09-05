"""apply_practical_filters: dollar-volume liquidity (audit D3) is measured in USD, not shares."""
import numpy as np
import pandas as pd

from core.filters import apply_practical_filters

IDX = pd.bdate_range(end="2026-09-04", periods=30)


def _panel():
    # Three names, all pass the SHARE filter (>=100k), only two pass $5M/day.
    prices = pd.DataFrame({
        "CHEAP": np.full(30, 6.0),      # $6 x 150k = $0.9M/day  -> thin
        "MID":   np.full(30, 40.0),     # $40 x 150k = $6M/day   -> ok
        "BIG":   np.full(30, 300.0),    # $300 x 150k = $45M/day -> ok
        "NOVOL": np.full(30, 50.0),     # no volume data at all
    }, index=IDX)
    volumes = pd.DataFrame({"CHEAP": 150_000.0, "MID": 150_000.0, "BIG": 150_000.0}, index=IDX)
    return prices, volumes


def test_share_filter_alone_keeps_the_thin_name_and_drops_unproven():
    prices, volumes = _panel()
    out, bd = apply_practical_filters(prices, volumes=volumes, min_avg_volume=100_000, min_price=5.0)
    assert "CHEAP" in out.columns            # 150k shares passes the share filter
    assert "NOVOL" not in out.columns        # no volume data cannot prove liquidity (used to KeyError)
    assert bd["volume"] == 1
    assert bd["dollar_volume"] == 0


def test_dollar_volume_filter_removes_the_thin_name():
    prices, volumes = _panel()
    out, bd = apply_practical_filters(prices, volumes=volumes, min_avg_volume=100_000, min_price=5.0,
                                      min_dollar_volume=5_000_000)
    assert sorted(out.columns) == ["BIG", "MID"]
    assert bd["volume"] == 1                 # NOVOL, by the share filter
    assert bd["dollar_volume"] == 1          # CHEAP: $0.9M/day


def test_dollar_volume_filter_is_inert_without_volume_data():
    prices, _ = _panel()
    out, bd = apply_practical_filters(prices, volumes=None, min_avg_volume=0, min_price=5.0,
                                      min_dollar_volume=5_000_000)
    assert list(out.columns) == list(prices.columns)
    assert bd["dollar_volume"] == 0
