"""TASK-403: the Norgate builder, exercised end to end against a fake client.

The subscription is not bought, so the point of these tests is that the code is real: the guards
fire on the exact failures this repo already paid for (a current-list screen with no delisted
names, a suffix stripped onto a live ticker, cell coverage too thin to trust), and a clean panel
gets written. Auto-discovered by run_all_tests.py (pytest-routed: no __main__ block).
"""
import os
import sys

import numpy as np
import pandas as pd
import pytest

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "experiments"))

from build_russell_pit import (  # noqa: E402
    MIN_CELL_COVERAGE, NorgateClient, assert_no_suffix_collision, build, build_membership,
    build_prices, coverage, is_delisted_symbol, rewrite_coverage, validate,
)

DATES = pd.bdate_range("2005-01-03", periods=60)


class FakeNorgate:
    """The contract the wrapper expects, as documented in TASK-334."""

    def __init__(self, members: dict, prices: dict):
        self._members = members
        self._prices = prices

    def watchlist_symbols(self, watchlist):
        return sorted({sym for sym, _index in self._members} | set(self._prices))

    def index_constituent_timeseries(self, symbol, index_name, format=None):
        key = (symbol, index_name)
        if key not in self._members:
            raise KeyError(key)
        return pd.DataFrame({"Index Constituent": self._members[key]}, index=DATES)

    def price_timeseries(self, symbol, format=None):
        if symbol not in self._prices:
            raise KeyError(symbol)
        return self._prices[symbol]


def _price_frame(n=None, start=10.0, gaps=0):
    n = len(DATES) if n is None else n
    close = np.linspace(start, start * 1.5, n)
    if gaps:
        close = close.astype(float).copy()
        close[:gaps] = np.nan
    return pd.DataFrame({
        "Open": close, "Close": close, "Adjusted Close": close,
        "Volume": np.full(n, 1_000_000.0),
    }, index=DATES[:n])


def _clean_fake(n_live=8, n_dead=4):
    members, prices = {}, {}
    for i in range(n_live):
        sym = f"LIVE{i}"
        members[(sym, "Russell 1000")] = [True] * len(DATES)
        prices[sym] = _price_frame()
    for i in range(n_dead):
        sym = f"DEAD{i}-201910"
        members[(sym, "Russell 2000")] = [True] * len(DATES)
        prices[sym] = _price_frame(start=5.0)
    return FakeNorgate(members, prices)


def test_a_dated_suffix_is_what_marks_a_delisted_symbol():
    assert is_delisted_symbol("AABA-201910")
    assert not is_delisted_symbol("BRK-B")
    assert not is_delisted_symbol("AAPL")
    assert not is_delisted_symbol("X-2019")           # four digits is not a Norgate suffix


def test_stripping_a_suffix_onto_a_live_ticker_is_refused():
    with pytest.raises(ValueError, match="live ticker"):
        assert_no_suffix_collision(["AABA", "AABA-201910", "AAPL"])
    assert assert_no_suffix_collision(["AABA-201910", "AAPL"]) is None


def test_membership_is_the_union_of_the_two_indexes():
    fake = FakeNorgate(
        {("A", "Russell 1000"): [True] * 30 + [False] * 30,
         ("A", "Russell 2000"): [False] * 30 + [True] * 30},
        {"A": _price_frame()},
    )
    m = build_membership(NorgateClient(fake), ["A"])
    assert m["A"].all()                                # in one index or the other every day


def test_a_symbol_in_no_index_is_dropped_rather_than_assumed():
    fake = FakeNorgate({("A", "Russell 1000"): [False] * len(DATES)}, {"A": _price_frame()})
    with pytest.raises(ValueError, match="refusing to guess"):
        build_membership(NorgateClient(fake), ["A"])


def test_prices_keep_the_as_printed_close_next_to_the_adjusted_one():
    frames = build_prices(NorgateClient(_clean_fake()), ["LIVE0", "DEAD0-201910"])
    assert set(frames) == {"close", "close_raw", "open", "volume"}
    assert list(frames["close"].columns) == ["LIVE0", "DEAD0-201910"]
    assert frames["close_raw"].notna().to_numpy().all()


def test_coverage_counts_only_member_cells():
    fake = _clean_fake()
    client = NorgateClient(fake)
    syms = fake.watchlist_symbols(None)
    m = build_membership(client, syms)
    frames = build_prices(client, syms)
    cov = coverage(m, frames["close"])
    assert cov["cell_coverage"] == 1.0
    assert cov["names"] == 12 and cov["delisted_names"] == 4
    assert cov["delisted_with_prices"] == 4
    assert cov["names_requested"] == 12
    assert cov["names_without_prices"] == 0 and cov["missing_member_cells"] == 0
    assert validate(cov) == []


def test_coverage_keeps_members_without_prices_in_the_denominator():
    """TASK-427: a requested name that never arrived must not vanish from both sides."""
    dates = pd.bdate_range("2022-06-24", periods=6)
    membership = pd.DataFrame(
        {"LIVE": [True] * 6, "GONE": [True] * 6},
        index=dates,
    )
    close = pd.DataFrame({"LIVE": [10.0] * 6}, index=dates)
    cov = coverage(membership, close, is_delisted=lambda s: False)
    assert cov["names"] == 1
    assert cov["names_requested"] == 2
    assert cov["names_without_prices"] == 1
    assert cov["missing_member_cells"] == 6
    assert cov["member_cells"] == 12
    assert cov["priced_member_cells"] == 6
    assert cov["cell_coverage"] == 0.5
    assert validate(cov, min_coverage=0.80, min_delisted=0.0)  # thin, and no delisted names


def test_a_panel_with_no_delisted_names_is_rejected_as_a_current_list_screen():
    fake = _clean_fake(n_live=8, n_dead=0)
    client = NorgateClient(fake)
    syms = fake.watchlist_symbols(None)
    cov = coverage(build_membership(client, syms), build_prices(client, syms)["close"])
    problems = validate(cov)
    assert any("current-list screen" in p for p in problems)


def test_thin_coverage_is_rejected_with_the_number_in_the_message():
    fake = _clean_fake()
    client = NorgateClient(fake)
    syms = fake.watchlist_symbols(None)
    m = build_membership(client, syms)
    close = build_prices(client, syms)["close"].copy()
    close.iloc[: int(len(close) * 0.5)] = np.nan       # half the member-days have no price
    cov = coverage(m, close)
    problems = validate(cov)
    assert any("cell coverage" in p for p in problems)
    assert cov["cell_coverage"] < MIN_CELL_COVERAGE


def test_a_delisted_name_with_no_price_history_is_rejected():
    members = {("LIVE0", "Russell 1000"): [True] * len(DATES)}
    prices = {"LIVE0": _price_frame()}
    for i in range(4):
        members[(f"DEAD{i}-201910", "Russell 2000")] = [True] * len(DATES)
    prices["DEAD0-201910"] = _price_frame(start=5.0)
    fake = FakeNorgate(members, prices)
    client = NorgateClient(fake)
    syms = ["LIVE0", "DEAD0-201910", "DEAD1-201910"]
    m = build_membership(client, syms)
    close = build_prices(client, syms)["close"]
    close = close.reindex(columns=syms)                # DEAD1 has no prices at all
    cov = coverage(m, close)
    assert any("no price history" in p for p in validate(cov))


def test_strict_mode_writes_nothing_when_a_guard_fails(tmp_path):
    fake = _clean_fake(n_live=8, n_dead=0)
    out = build(NorgateClient(fake), strict=True, out_dir=str(tmp_path))
    assert out["written"] is None
    assert out["problems"]
    assert not list(tmp_path.iterdir())


def test_a_clean_panel_is_written_with_its_coverage_next_to_it(tmp_path):
    out = build(NorgateClient(_clean_fake()), strict=True, out_dir=str(tmp_path))
    assert out["problems"] == []
    assert out["written"] == str(tmp_path)
    names = {p.name for p in tmp_path.iterdir()}
    assert {"close.pkl", "close_raw.pkl", "volume.pkl", "membership.pkl",
            "coverage.json"} <= names
    close = pd.read_pickle(tmp_path / "close.pkl")
    membership = pd.read_pickle(tmp_path / "membership.pkl")
    assert close.shape[1] == 12 and membership.shape[1] == 12
    import json
    cov = json.loads((tmp_path / "coverage.json").read_text(encoding="utf-8"))
    assert "honest_window" in cov and "ghost_names" in cov and "membership_first" in cov
    assert "spliced_dropped_n" in cov


def test_rewrite_coverage_recomputes_from_the_pkl_files(tmp_path):
    """TASK-427: the already-built panel is remeasured from disk, no provider."""
    dates = pd.bdate_range("2022-06-24", periods=4)
    membership = pd.DataFrame({"LIVE": True, "GONE": True}, index=dates)
    close = pd.DataFrame({"LIVE": [10.0] * 4}, index=dates)
    close.to_pickle(tmp_path / "close.pkl")
    membership.to_pickle(tmp_path / "membership.pkl")
    (tmp_path / "coverage.json").write_text("{}", encoding="utf-8")
    cov = rewrite_coverage(str(tmp_path), is_delisted=lambda s: False)
    assert cov["names_requested"] == 2
    assert cov["names_without_prices"] == 1
    assert cov["missing_member_cells"] == 4
    assert cov["cell_coverage"] == 0.5
    import json
    on_disk = json.loads((tmp_path / "coverage.json").read_text(encoding="utf-8"))
    assert on_disk["cell_coverage"] == 0.5


def test_dry_run_validates_without_writing(tmp_path):
    out = build(NorgateClient(_clean_fake()), strict=True, dry_run=True, out_dir=str(tmp_path))
    assert out["problems"] == [] and out["written"] is None
    assert not list(tmp_path.iterdir())


def test_without_the_subscription_the_client_says_what_to_buy():
    """The real reason TASK-403 is open: no data. The message names the product and the trap."""
    if "norgatedata" in sys.modules:
        pytest.skip("norgatedata is installed on this machine")
    with pytest.raises(RuntimeError, match="Norgate Data US Stocks Platinum"):
        NorgateClient()
