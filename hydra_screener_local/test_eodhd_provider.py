"""TASK-403: the EODHD provider and the PIT client it feeds, offline.

No network here: the transport is one injected `opener`, so every payload below is a real shape
copied from the live API (probed 2026-09-11 before the code was written) rather than a guess.
The live checks that cannot be faked - that TWTR really stops on 2022-10-27, that a bad code
returns HTTP 404, that 32_976 delisted common stocks come back - are in
`.comms/claude-task-403-eodhd-client-2026-09-11.md` with their numbers.

Auto-discovered by run_all_tests.py (pytest-routed: no __main__ block).
"""
from __future__ import annotations

import json
import os
import sys

import pandas as pd
import pytest

ROOT = os.path.dirname(os.path.abspath(__file__))
for _p in (ROOT, os.path.join(ROOT, "experiments")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from data.providers.base import BarProvider  # noqa: E402
from data.providers.eodhd_provider import (  # noqa: E402
    EODHDProvider, EodhdError, _redact, resolve_token,
)
from eodhd_pit_client import EodhdClient, load_membership_record  # noqa: E402

TOKEN = "t0k3n-not-real"

# One row shape per endpoint, as the live API returns them.
EOD_TWTR = [
    {"date": "2022-10-26", "open": 52.95, "high": 53.5, "low": 52.77, "close": 53.35,
     "adjusted_close": 53.35, "volume": 29698456},
    {"date": "2022-10-27", "open": 53.91, "high": 54.0, "low": 53.7, "close": 53.7,
     "adjusted_close": 53.7, "volume": 198415408},
]
EOD_AAPL = [
    {"date": "2022-10-26", "open": 150.96, "high": 151.99, "low": 148.04, "close": 149.35,
     "adjusted_close": 146.487, "volume": 88194200},
    {"date": "2022-10-27", "open": 148.07, "high": 149.05, "low": 144.13, "close": 144.8,
     "adjusted_close": 142.024, "volume": 109180200},
]
DELISTED = [
    {"Code": "TWTR", "Name": "Twitter Inc", "Country": "USA", "Exchange": "NYSE",
     "Currency": "USD", "Type": "Common Stock", "Isin": "US90184L1026"},
    {"Code": "BBBY", "Name": "Bed Bath & Beyond, Inc.", "Country": "USA", "Exchange": "NYSE",
     "Currency": "USD", "Type": "Common Stock", "Isin": "US6903701018"},
    {"Code": "0P0000V6X4", "Name": "Vanguard Target Retire Trust Plus 2040", "Country": "USA",
     "Exchange": "NYSE", "Currency": "USD", "Type": "FUND", "Isin": None},
]


def _fake_api(pages=None, *, fail=None):
    """An opener over the URL: no sockets, and it records what was asked."""
    pages = pages or {}
    calls = []

    def opener(url):
        calls.append(url)
        path = url.split("/api/", 1)[1].split("?", 1)[0]
        if fail and path in fail:
            raise fail[path]
        if path.startswith("exchange-symbol-list"):
            return json.dumps(pages.get("delisted", DELISTED))
        code = path.split("eod/", 1)[-1]
        if code not in pages:
            import urllib.error
            raise urllib.error.HTTPError(url, 404, "Not Found", None, None)
        return json.dumps(pages[code])

    opener.calls = calls
    return opener


def _provider(pages=None, **kw):
    return EODHDProvider(token=TOKEN, opener=_fake_api(pages), **kw)


# --- the provider ---------------------------------------------------------------------

def test_it_satisfies_the_bar_provider_protocol():
    """`BarProvider` is not runtime_checkable, so check the shape it documents."""
    import inspect

    sig = inspect.signature(_provider().fetch)
    assert list(sig.parameters) == list(inspect.signature(BarProvider.fetch).parameters)[1:]
    assert _provider().source == "eodhd"


def test_bars_come_back_long_with_both_closes():
    p = _provider({"TWTR.US": EOD_TWTR, "AAPL.US": EOD_AAPL})
    df = p.fetch(["TWTR", "AAPL"], "2022-10-01", "2022-10-31")
    assert list(df.columns) == ["ticker", "date", "close_adj", "close_raw", "volume"]
    aapl = df[df.ticker == "AAPL"]
    assert aapl.close_raw.tolist() == [149.35, 144.8]
    assert aapl.close_adj.tolist() == [146.487, 142.024], "adjusted close is not the printed one"
    twtr = df[df.ticker == "TWTR"]
    assert str(twtr.date.max().date()) == "2022-10-27", "the last bar is the delisting date"


def test_one_dead_ticker_does_not_kill_a_panel_wide_fetch():
    """A build over thousands of dead names must not die on one 404."""
    p = _provider({"TWTR.US": EOD_TWTR})
    df = p.fetch(["TWTR", "NOSUCHTICKERXYZ"], "2022-10-01", "2022-10-31")
    assert set(df.ticker) == {"TWTR"}
    assert "NOSUCHTICKERXYZ" in p.last_errors
    assert "404" in p.last_errors["NOSUCHTICKERXYZ"]


def test_the_window_and_the_us_suffix_reach_the_url():
    p = _provider({"TWTR.US": EOD_TWTR})
    p.fetch(["TWTR"], "2022-10-01", "2022-10-31")
    url = p._opener.calls[-1]
    assert "eod/TWTR.US" in url and "from=2022-10-01" in url and "to=2022-10-31" in url
    assert "period=d" in url


def test_an_explicit_exchange_suffix_is_left_alone():
    p = _provider({"TWTR.US": EOD_TWTR})
    p.eod("TWTR.US", "2022-10-01", "2022-10-31")
    assert p._opener.calls[-1].count(".US") == 1


def test_the_token_never_appears_in_an_error():
    """It is a paid credential in a gitignored .env; a traceback is not a place for it."""
    import urllib.error
    p = EODHDProvider(token=TOKEN, opener=_fake_api(
        fail={"user": urllib.error.URLError(f"connect failed for api_token={TOKEN}")}))
    with pytest.raises(EodhdError) as ei:
        p.get("user")
    assert TOKEN not in str(ei.value)
    assert "<redacted>" in str(ei.value)
    assert _redact(f"x {TOKEN} y", TOKEN) == "x <redacted> y"


def test_without_a_token_it_says_where_the_token_goes(monkeypatch):
    monkeypatch.delenv("EODHD_API_TOKEN", raising=False)
    monkeypatch.setattr("data.providers.eodhd_provider.resolve_token", lambda token=None: None)
    p = EODHDProvider(opener=_fake_api())
    with pytest.raises(EodhdError, match="EODHD_API_TOKEN"):
        p.get("user")


def test_the_environment_beats_the_dotenv_file(monkeypatch):
    monkeypatch.setenv("EODHD_API_TOKEN", "from-env")
    assert resolve_token() == "from-env"
    assert resolve_token("explicit") == "explicit", "an explicit token wins over the environment"


def test_the_delisted_list_is_equities_only_by_default():
    p = _provider()
    dead = p.delisted()
    assert set(dead) == {"TWTR", "BBBY"}, "a FUND is not a Russell member"
    assert p.delisted(types=None).keys() >= {"TWTR", "BBBY", "0P0000V6X4"}
    assert dead["TWTR"]["Isin"] == "US90184L1026"


def test_a_non_json_answer_is_an_error_not_a_crash():
    p = EODHDProvider(token=TOKEN, opener=lambda url: "<html>maintenance</html>")
    with pytest.raises(EodhdError, match="non-JSON"):
        p.get("user")


# --- the PIT client ------------------------------------------------------------------

RECORD = pd.DataFrame({
    "date": ["2022-06-24", "2022-06-24", "2023-06-23", "2023-06-23"],
    "ticker": ["TWTR", "AAPL", "TWTR", "AAPL"],
    "member": [1, 1, 0, 1],
    "source": ["kact998", "kact998", "ftse-rollforward", "ftse-rollforward"],
})


def _client(pages=None, **kw):
    return EodhdClient(_provider(pages), RECORD, **kw)


def test_the_record_becomes_a_dated_membership_frame():
    wide = load_membership_record(RECORD)
    assert list(wide.columns) == ["AAPL", "TWTR"]
    assert wide.loc[pd.Timestamp("2022-06-24"), "TWTR"]
    assert not wide.loc[pd.Timestamp("2023-06-23"), "TWTR"], "it left the index that June"


def test_a_missing_record_says_how_to_build_it(tmp_path):
    with pytest.raises(FileNotFoundError, match="russell_free_membership.py"):
        load_membership_record(str(tmp_path / "nope.csv"))


def test_symbols_are_every_name_that_was_ever_a_member():
    assert _client().symbols() == ["AAPL", "TWTR"]


def test_membership_is_the_same_series_for_both_russell_indexes():
    """The free record is Russell 3000; saying so beats implying a per-index answer."""
    c = _client()
    a = c.membership("TWTR", "Russell 1000")
    b = c.membership("TWTR", "Russell 2000")
    assert a.equals(b)
    assert c.membership("NOTHERE", "Russell 1000").empty


def test_prices_arrive_in_the_builders_column_names():
    c = _client({"AAPL.US": EOD_AAPL})
    df = c.prices("AAPL")
    assert {"Close", "Adjusted Close", "Volume", "Open"} <= set(df.columns)
    assert df["Close"].tolist() == [149.35, 144.8]
    assert df["Adjusted Close"].tolist() == [146.487, 142.024]
    assert isinstance(df.index, pd.DatetimeIndex)
    assert c.prices("NOSUCH").empty


def test_identity_comes_from_the_delisted_list_not_from_the_symbol():
    """Norgate marks a dead entity `AABA-201910`; EODHD has no suffix at all (TASK-325)."""
    import build_russell_pit as B

    c = _client()
    assert c.is_delisted("TWTR") and not c.is_delisted("AAPL")
    assert not B.is_delisted_symbol("TWTR"), "the suffix rule cannot see this, which is the point"


def test_the_builder_uses_the_clients_identity_and_writes_when_every_name_has_membership(tmp_path):
    """End to end through `build()`: identity comes from the list, not the suffix.

    A date cutoff is not a refusal (TASK-423 wolf note). Both names are in the record,
    so strict writes.
    """
    import build_russell_pit as B

    dates = pd.bdate_range("2022-06-24", periods=6)
    record = pd.DataFrame(True, index=dates, columns=["AAPL", "TWTR"])
    bars = {c: [{"date": str(d.date()), "close": 10.0 + i, "adjusted_close": 9.0 + i,
                 "volume": 1e6} for i, d in enumerate(dates)]
            for c in ("AAPL.US", "TWTR.US")}
    c = EodhdClient(_provider(bars), record)

    out = B.build(c, strict=True, dry_run=False, out_dir=str(tmp_path))
    assert out["problems"] == [], out["problems"]
    assert out["coverage"]["delisted_names"] == 1, "identity came from the list, not the suffix"
    assert out["coverage"]["names_requested"] >= out["coverage"]["names"]
    assert out["written"] == str(tmp_path)
    assert os.path.exists(os.path.join(str(tmp_path), "coverage.json"))


def _bars(dates, start_px=10.0):
    return [{"date": str(d.date()), "close": start_px + i, "adjusted_close": start_px + i - 1,
             "volume": 1e6} for i, d in enumerate(dates)]


def test_membership_tail_cut_on_three_synthetic_names():
    """TASK-423: normal death intact, spliced code cut, current member (tail) intact."""
    member_days = pd.bdate_range("2022-06-24", "2023-06-22")
    spliced_after = pd.bdate_range("2026-08-03", periods=4)
    dead_days = pd.DatetimeIndex(["2022-10-26", "2022-10-27"])
    live_days = pd.bdate_range("2022-06-24", "2026-09-10")
    record = pd.DataFrame({
        "date": (["2022-06-24"] * 3) + (["2023-06-23"] * 3) + (["2026-06-26"] * 3),
        "ticker": ["DEAD", "SPLICE", "LIVE"] * 3,
        "member": [1, 1, 1,  0, 0, 1,  0, 0, 1],
    })
    pages = {
        "DEAD.US": _bars(dead_days, 53.0),
        "SPLICE.US": _bars(member_days.append(spliced_after), 3.0),
        "LIVE.US": _bars(live_days, 100.0),
    }
    c = EodhdClient(_provider(pages), record, membership_tail_bars=10)
    assert c.cut_at_membership_tail is True
    assert c.membership_tail_bars == 10

    dead = c.prices("DEAD")
    assert [str(d.date()) for d in dead.index] == ["2022-10-26", "2022-10-27"]

    splice = c.prices("SPLICE")
    limit = c.membership_cut_date("SPLICE")
    assert limit is not None
    assert splice.index.max() <= limit
    assert splice.index.max() < pd.Timestamp("2026-08-03"), "the glued half is gone"

    live = c.prices("LIVE")
    assert live.index.max() == live_days[-1], "a current member is not trimmed"

    close = pd.concat([dead["Close"].rename("DEAD"),
                       splice["Close"].rename("SPLICE"),
                       live["Close"].rename("LIVE")], axis=1)
    assert c.identity_problems(close) == []


def test_cut_at_membership_tail_defaults_on_and_can_be_turned_off():
    """The flag is the declared default."""
    assert EodhdClient(_provider(), RECORD).cut_at_membership_tail is True
    c = EodhdClient(_provider(), RECORD, cut_at_membership_tail=False)
    assert c.cut_at_membership_tail is False


def test_a_code_with_no_membership_date_is_still_a_problem(tmp_path):
    """Fence does not degrade: no membership date -> no cut, strict still refuses."""
    import build_russell_pit as B

    dates = pd.bdate_range("2026-08-03", periods=6)
    record = pd.DataFrame({"date": ["2022-06-24"], "ticker": ["AAPL"], "member": [1]})
    pages = {
        "AAPL.US": _bars(pd.bdate_range("2022-06-24", periods=6), 140.0),
        "GHOST.US": _bars(dates, 1.0),
    }
    c = EodhdClient(_provider(pages), record, delisted={"GHOST": {"Code": "GHOST"}})
    assert c.last_membership_date("GHOST") is None
    ghost = c.prices("GHOST")
    assert ghost.index.max() == dates[-1], "uncuttable codes are not trimmed"

    out = B.build(c, strict=True, dry_run=False, out_dir=str(tmp_path),
                  symbols=["AAPL", "GHOST"])
    assert out["written"] is None
    assert any("GHOST" in p for p in out["problems"])
    assert any("TASK-423" in p for p in out["problems"])


def test_membership_cut_stats_are_two_figures_not_an_estimate():
    """columns_cut and member_cells_dropped, measured on an uncut close."""
    member_days = pd.bdate_range("2022-06-24", "2023-06-22")
    after = pd.bdate_range("2026-08-03", periods=4)
    record = pd.DataFrame({
        "date": ["2022-06-24", "2023-06-23"],
        "ticker": ["SPLICE", "SPLICE"],
        "member": [1, 0],
    })
    pages = {"SPLICE.US": _bars(member_days.append(after), 3.0)}
    c = EodhdClient(_provider(pages), record, cut_at_membership_tail=False)
    raw = c.prices("SPLICE")
    close = pd.DataFrame({"SPLICE": raw["Close"]})
    stats = c.membership_cut_stats(close)
    assert stats["columns_cut"] == 1
    assert stats["codes"] == ["SPLICE"]
    assert stats["uncuttable"] == []
    assert stats["member_cells_dropped"] == 0, (
        "the panel does not read prices after last membership, so no member-cell is lost"
    )
