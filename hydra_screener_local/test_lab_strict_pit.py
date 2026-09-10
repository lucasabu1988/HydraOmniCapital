"""ASTRA-05 — a fixed sector map may not be reported as point-in-time, and an absolute
currency filter may not be applied to dividend-adjusted closes.

Two ported audit probes (`test_adversarial.py`, Auditoria-Hydra-2026-09-06), assertions kept:

* `test_historical_sector_request_cannot_fall_back_to_live` — asking for 2005 with only a 2026
  snapshot on disk used to warn and then read the LIVE sector cache. It must fail instead.
* `test_future_dividend_does_not_change_historical_price_eligibility` — the lab's price and
  dollar-volume floors were applied to auto-adjusted closes, so a dividend paid later moved a
  historical bar below a floor it passed at the time.

No network, no state/, no data_cache/: every fixture here is synthetic.
"""
import os
import sys

import pandas as pd
import pytest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "experiments"))

from data.adjust import adjust, contemporaneous_close  # noqa: E402
from data.pit import PitMissing, require_sectors_at, write_sectors_snapshot  # noqa: E402

import redesign_lab as L  # noqa: E402
from redesign_lab import SectorMapper, resolve_sector_map  # noqa: E402


# ----------------------------------------------------------------- probe 1: strict PIT sectors
def test_historical_sector_request_cannot_fall_back_to_live(tmp_path):
    """Astra's probe, verbatim."""
    write_sectors_snapshot({'AAA': 'FutureTech'}, '20260905', unknown=[], pit_dir=tmp_path)
    with pytest.raises(Exception, match='(?i)(pit|snapshot|sector)'):
        resolve_sector_map(['AAA'], 'pit', '20050103', pit_dir=tmp_path, lookup=lambda _: 'FutureTech')


def test_strict_request_raises_pitmissing_and_never_calls_the_live_lookup(tmp_path):
    write_sectors_snapshot({"AAA": "FutureTech"}, "20260905", unknown=[], pit_dir=tmp_path)
    calls = []
    with pytest.raises(PitMissing):
        resolve_sector_map(["AAA"], "pit", "20050103", pit_dir=tmp_path,
                           lookup=lambda t: calls.append(t) or "Live")
    assert calls == []                       # the live cache is not consulted, not even once
    with pytest.raises(PitMissing):          # nor is an empty snapshot directory a licence
        require_sectors_at("20050103", pit_dir=tmp_path)


def test_strict_pit_resolves_the_classification_effective_at_each_date(tmp_path):
    write_sectors_snapshot({"AAA": "Tech", "BBB": "Energy"}, "20260801", unknown=[], pit_dir=tmp_path)
    write_sectors_snapshot({"AAA": "Health", "BBB": "Energy"}, "20260901", unknown=[], pit_dir=tmp_path)
    mp = SectorMapper(["AAA", "BBB"], "pit", None, pit_dir=tmp_path)
    assert mp.at("2026-08-15")["AAA"] == "Tech"          # per date, not one map for every date
    assert mp.at("2026-09-05")["AAA"] == "Health"
    with pytest.raises(PitMissing):
        mp.at("2005-01-03")                              # before the first snapshot: unknowable
    assert mp.info["pit_valid"] is True
    assert mp.info["snapshots_used"] == ["20260801", "20260901"]


def test_strict_pit_never_borrows_the_hand_made_bucket_map(tmp_path):
    """config.SECTOR_BUCKETS is a hand-made present-day map, not a dated observation. A name the
    snapshot does not carry is 'Other' = unknown at t (which the sector cap exempts)."""
    from config import SECTOR_BUCKETS
    known = next(iter(SECTOR_BUCKETS))
    write_sectors_snapshot({"AAA": "Tech"}, "20260905", unknown=[], pit_dir=tmp_path)
    m, info = resolve_sector_map(["AAA", known], "pit", "20260905", pit_dir=tmp_path)
    assert m[known] == "Other" and m[known] != SECTOR_BUCKETS[known]
    assert info["mode"] == "strict_pit" and info["n_fallback"] == 1
    # the fixed-map scenario is allowed to use it: it is reproducible, and labelled as not PIT
    m2, info2 = resolve_sector_map(["AAA", known], "fixed", "20260905", pit_dir=tmp_path)
    assert m2[known] == SECTOR_BUCKETS[known] and info2["pit_valid"] is False


def test_pinning_a_date_is_a_fixed_map_scenario_not_strict_pit(tmp_path):
    write_sectors_snapshot({"AAA": "Tech"}, "20260905", unknown=[], pit_dir=tmp_path)
    with pytest.raises(ValueError, match="fixed"):
        SectorMapper(["AAA"], "pit", "20260905", pit_dir=tmp_path)


def test_fixed_map_is_labelled_and_flagged_not_pit(tmp_path):
    write_sectors_snapshot({"AAA": "Tech"}, "20260905", unknown=[], pit_dir=tmp_path)
    mp = SectorMapper(["AAA"], "fixed", None, pit_dir=tmp_path)
    assert mp.info["mode"] == "fixed_map" and mp.info["pit_valid"] is False
    assert mp.at("2005-01-03") is mp.at("2026-09-05")            # one map for every date
    assert mp.at("2005-01-03")["AAA"] == "Tech"                  # the 2026 taxonomy, in 2005
    assert "FIXED-MAP SCENARIO" in mp.describe() and "NOT" in mp.describe()
    assert "excluded from PIT conclusions" in mp.describe()


def test_fixed_map_still_refuses_to_fabricate_a_map_without_any_snapshot(tmp_path):
    """The old behaviour printed a warning and read data_cache/sector_cache.json. No mode does."""
    with pytest.raises(PitMissing):
        resolve_sector_map(["AAA"], "fixed", None, pit_dir=tmp_path / "empty", lookup=lambda t: "L")
    with pytest.raises(PitMissing):
        SectorMapper(["AAA"], "pit", None, pit_dir=tmp_path / "empty").at("2026-09-05")
    # only an explicit sectors="live" reads the mutable cache, and it is labelled
    m, info = resolve_sector_map(["AAA"], "live", lookup=lambda t: "L")
    assert m == {"AAA": "L"} and info["mode"] == "live" and info["pit_valid"] is False


def test_info_carries_what_the_run_json_records(tmp_path):
    """engine_backtest / panel_methodology write sector_mode + sector_pit_valid + the snapshot
    identity next to pit_payload, so a reader can tell which mode produced the numbers."""
    write_sectors_snapshot({"AAA": "Tech"}, "20260905", unknown=[], pit_dir=tmp_path)
    _, info = resolve_sector_map(["AAA"], "fixed", None, pit_dir=tmp_path)
    assert {"source", "mode", "pit_valid", "snapshot_date", "snapshot"} <= set(info)
    ident = info["snapshot"]
    assert ident["kind"] == "sectors" and ident["date"] == "20260905"
    assert ident["present"] is True and ident["count"] == 1 and ident["path"].endswith("sectors_20260905.json")


# ------------------------------------------------- probe 2: eligibility needs today's currency
def test_future_dividend_does_not_change_historical_price_eligibility():
    """Astra's probe, assertion preserved, pointed at the series eligibility must use.

    `adjust` is correct total-return arithmetic: back-adjustment is what makes a ratio comparable
    across an ex-date, and the 6 USD bar becoming 4.0 is the right ANSWER TO A DIFFERENT QUESTION.
    What may not depend on the future is the absolute price test, so it reads the contemporaneous
    close instead.
    """
    idx = pd.to_datetime(['2026-09-14', '2026-09-15'])
    raw = pd.Series([6., 4.], index=idx)
    div = {'2026-09-15': 2.}
    # the defect, still reproducible on the total-return series itself
    assert adjust(raw.iloc[:1]).iloc[0] == pytest.approx(6.0)
    assert adjust(raw, dividends=div).iloc[0] == pytest.approx(4.0)      # 6 -> 4 with hindsight
    historical = contemporaneous_close(adjust(raw.iloc[:1]))
    hindsight = contemporaneous_close(adjust(raw, dividends=div), dividends=div).iloc[:1]
    assert (historical.iloc[0] >= 5.) == (hindsight.iloc[0] >= 5.), (historical.iloc[0], hindsight.iloc[0])
    assert historical.iloc[0] == pytest.approx(6.0) and hindsight.iloc[0] == pytest.approx(6.0)


def test_contemporaneous_close_round_trips_dividends_and_splits():
    idx = pd.bdate_range("2024-01-01", periods=6)
    raw = pd.Series([100.0, 102.0, 101.0, 103.0, 104.0, 105.0], index=idx)
    div = {"2024-01-03": 2.04, "2024-01-05": 1.03}
    splits = {"2024-01-04": 2.0}
    for events in ({}, dict(dividends=div), dict(splits=splits), dict(dividends=div, splits=splits)):
        back = contemporaneous_close(adjust(raw, **events), **events)
        pd.testing.assert_series_equal(back, raw, check_names=False, rtol=0, atol=1e-9)


class _Panel:
    """The minimum `eligibility_mask` reads. Volume is flat, so only price moves the mask."""

    def __init__(self, close, close_elig=None, volume=1e6):
        self.close = close
        self.volume = pd.DataFrame(volume, index=close.index, columns=close.columns)
        self.ADV_USD = (self.close * self.volume).rolling(1).mean()
        self.CLOSE_ELIG = close_elig
        self.ADV_USD_ELIG = None if close_elig is None else (close_elig * self.volume).rolling(1).mean()
        self.VOL20M = self.volume.rolling(1).mean()
        self.FLAT5 = pd.DataFrame(0.0, index=close.index, columns=close.columns)
        self.JUMP252 = pd.DataFrame(0.0, index=close.index, columns=close.columns)


def test_lab_eligibility_mask_is_invariant_to_a_future_dividend():
    idx = pd.to_datetime(["2026-09-14", "2026-09-15"])
    raw = pd.DataFrame({"AAA": [6.0, 4.0]}, index=idx)
    div = {"2026-09-15": 2.0}
    hist = adjust(raw["AAA"].iloc[:1]).to_frame("AAA")               # what was knowable on 09-14
    hind = adjust(raw["AAA"], dividends=div).to_frame("AAA")         # the same bar, seen later
    c = dict(L.BASE)                                                 # min_dollar_vol = 5e6
    with_raw_hist = L.eligibility_mask(_Panel(hist, close_elig=raw.iloc[:1]), 0, c)["AAA"]
    with_raw_hind = L.eligibility_mask(_Panel(hind, close_elig=raw), 0, c)["AAA"]
    assert bool(with_raw_hist) == bool(with_raw_hind) is True        # 6 USD passes in both runs
    # and the defect it fixes: on adjusted closes the future dividend alone flips eligibility
    assert bool(L.eligibility_mask(_Panel(hist), 0, c)["AAA"]) is True
    assert bool(L.eligibility_mask(_Panel(hind), 0, c)["AAA"]) is False


class _WidePanel(_Panel):
    """60 names so `rank_day` passes its 50-name floor, with flat hand-set feature panels."""

    def __init__(self, cheap_adj, cheap_raw=None, n=60):
        idx = pd.to_datetime(["2026-09-14", "2026-09-15"])
        cols = ["CHEAP"] + [f"T{i:02d}" for i in range(n - 1)]
        close = pd.DataFrame(50.0, index=idx, columns=cols)
        close["CHEAP"] = cheap_adj
        elig = None
        if cheap_raw is not None:
            elig = close.copy()
            elig["CHEAP"] = cheap_raw
        super().__init__(close, close_elig=elig, volume=1e6)
        flat = lambda v: pd.DataFrame(v, index=idx, columns=cols)   # noqa: E731
        self.VOL63, self.MOM, self.RET10 = flat(0.2), flat(0.5), flat(5.0)
        self.MOM_12_1 = self.MOM_6_1 = self.MOM_12_7 = self.MOM
        self.DIST20, self.VRATIO = flat(-1.0), flat(1.0)
        self.SECTOR = {}


def test_rank_day_keeps_a_name_a_future_dividend_would_have_disqualified():
    """The mask decides who gets scored at all: a name that printed 6 USD is in the ranked frame
    when eligibility reads the contemporaneous close, and vanishes when it reads the adjusted one."""
    c = dict(L.BASE)
    with_raw = L.rank_day(_WidePanel([4.0, 4.0], cheap_raw=[6.0, 6.0]), 0, c)
    without = L.rank_day(_WidePanel([4.0, 4.0]), 0, c)
    assert "CHEAP" in with_raw.index and "CHEAP" not in without.index
    assert len(with_raw) == len(without) + 1                       # nothing else moved


def test_eligibility_panel_labels_or_refuses_adjusted_closes(tmp_path, capsys):
    idx = pd.to_datetime(["2026-09-14", "2026-09-15"])
    P = _Panel(pd.DataFrame({"AAA": [6.0, 4.0]}, index=idx))
    P.CACHE_DIR = str(tmp_path)
    elig, adv, label = L.attach_eligibility_panel(P)
    assert elig is None and adv is None and label.startswith("adjusted")
    assert "look-ahead" in label and "WARNING" in capsys.readouterr().out
    with pytest.raises(FileNotFoundError, match="ASTRA-05b"):
        L.attach_eligibility_panel(P, require_contemporaneous=True)
    raw = pd.DataFrame({"AAA": [6.0, 4.0]}, index=idx)
    raw.to_pickle(os.path.join(str(tmp_path), L.RAW_CLOSE_PKL))
    elig, adv, label = L.attach_eligibility_panel(P)
    assert label.startswith("contemporaneous") and float(elig.iloc[0]["AAA"]) == 6.0
    pd.testing.assert_frame_equal(adv, (raw * P.volume).rolling(20).mean())   # raw, not adjusted
