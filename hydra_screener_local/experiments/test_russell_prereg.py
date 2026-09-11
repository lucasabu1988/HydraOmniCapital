"""TASK-431: the prereg freeze, --cache, membership overlay. No engine, no panel cache."""
from __future__ import annotations

import os
import sys
import types

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import engine_backtest as EB  # noqa: E402
import redesign_lab as L  # noqa: E402
import run_russell_prereg as R  # noqa: E402


def test_prereg_file_hashes_to_the_pinned_amendment():
    freeze = R.verify_freeze()
    assert freeze["prereg_sha256"] == R.PINNED_PREREG_SHA256
    assert freeze["prereg_sha256"].startswith("3d5598d944ce887c")
    assert freeze["file_hashes"] == R.FROZEN_FILE_HASHES
    assert freeze["v9"]["stock_momentum_window"] == "mom12_7"
    assert freeze["v9"]["stock_cost_bp"] == 10.0
    assert freeze["config"]["ALGO_VERSION"] == "v9"
    assert freeze["config"]["MAX_PER_SECTOR"] == 5


def test_engine_backtest_accepts_cache_and_skips_a_missing_dir(tmp_path, capsys):
    rc = EB.main(["--cache", str(tmp_path / "nope")])
    assert rc == 0
    out = capsys.readouterr().out
    assert "SKIP" in out
    assert "close.pkl" in out


def test_resolve_cache_dir_accepts_a_directory_or_a_close_pkl(tmp_path):
    d = tmp_path / "panel"
    d.mkdir()
    pkl = d / "close.pkl"
    pkl.write_bytes(b"")
    assert EB.resolve_cache_dir(str(d)).endswith("panel")
    assert EB.resolve_cache_dir(str(pkl)).endswith("panel")
    assert EB.resolve_cache_dir(None, oos=True).endswith("_sweep_cache_oos")
    assert EB.resolve_cache_dir(None, oos=False).endswith("_sweep_cache")


def test_dry_run_verifies_freeze_and_does_not_need_the_panel(capsys):
    rc = R.main(["--dry-run", "--cache", os.path.join(R.HERE, "_no_such_cache")])
    assert rc == 0
    out = capsys.readouterr().out
    assert "freeze OK" in out
    assert "dry-run: engine not started" in out
    assert R.PINNED_PREREG_SHA256[:16] in out


def _tiny_panel():
    idx = pd.bdate_range("2020-01-01", periods=40)
    names = [f"N{i:02d}" for i in range(8)]
    close = pd.DataFrame(20.0, index=idx, columns=names)
    P = types.SimpleNamespace()
    P.close = close
    P.volume = pd.DataFrame(1_000_000.0, index=idx, columns=names)
    P.VOL20M = P.volume.copy()
    P.FLAT5 = pd.DataFrame(0, index=idx, columns=names)
    P.ADV_USD = close * 1_000_000.0
    P.CLOSE_ELIG = close.copy()
    P.ADV_USD_ELIG = P.ADV_USD.copy()
    P.JUMP252 = pd.DataFrame(0.0, index=idx, columns=names)
    P.pit_payload = {"updated": "wikipedia-must-not-be-used"}
    return P


def test_membership_overlay_drops_non_members_and_clears_wikipedia_payload():
    P = _tiny_panel()
    mem = pd.DataFrame(False, index=P.close.index, columns=P.close.columns)
    mem.loc[:, ["N00", "N01", "N02"]] = True
    orig = L.eligibility_mask
    restore = R.attach_russell_membership(P, mem)
    try:
        assert P.pit_payload is None
        c = dict(L.BASE)
        elig = L.eligibility_mask(P, 10, c)
        assert set(elig.index[elig]) <= {"N00", "N01", "N02"}
        assert not bool(elig[["N03", "N04", "N05", "N06", "N07"]].any())
    finally:
        restore()
    assert L.eligibility_mask is orig


def test_start_bar_is_max_of_warmup_and_first_membership_date():
    idx = pd.bdate_range("2005-01-03", periods=400)
    names = ["A", "B"]
    P = types.SimpleNamespace()
    P.close = pd.DataFrame(1.0, index=idx, columns=names)
    mem = pd.DataFrame(False, index=idx, columns=names)
    mem.iloc[50:, :] = True
    P.MEMBERSHIP = mem
    # warmup 280 > 50
    assert R.start_bar(P) == 280
    mem[:] = False
    mem.iloc[350:, :] = True
    P.MEMBERSHIP = mem
    assert R.start_bar(P) == 350


def test_verdict_fences_are_the_prereg_ones():
    assert R.verdict(d_sharpe=-0.10, dd_worse_pp=5.0, cost_frac=0.4) == "SURVIVE"
    assert R.verdict(d_sharpe=-0.09, dd_worse_pp=4.9, cost_frac=0.1) == "SURVIVE"
    assert R.verdict(d_sharpe=-0.25, dd_worse_pp=0.0, cost_frac=0.1) == "FAIL"
    assert R.verdict(d_sharpe=-0.05, dd_worse_pp=0.0, cost_frac=0.51) == "FAIL"
    assert R.verdict(d_sharpe=-0.18, dd_worse_pp=1.0, cost_frac=0.1) == "INCONCLUSIVE"
    assert R.verdict(d_sharpe=-0.05, dd_worse_pp=5.1, cost_frac=0.1) == "INCONCLUSIVE"


def test_caveat_table_is_its_own_rows_not_a_footnote():
    cov = dict(cell_coverage=0.8691, ghost_names=547, ghost_member_cells=196856,
               spliced_dropped=["BBBY", "SBNY"], honest_window="2010-2026",
               names=6048, names_requested=6547)
    t = R.caveat_table(cov)
    assert list(t["item"]) == [
        "cell_coverage", "ghost_names", "ghost_member_cells",
        "spliced_dropped", "honest_window", "names",
    ]
    assert float(t.loc[t["item"] == "cell_coverage", "value"].iloc[0]) == 0.8691
    assert t.loc[t["item"] == "spliced_dropped", "value"].iloc[0] == "BBBY,SBNY"


def test_align_book_ffills_sp_marks_onto_a_shifted_calendar():
    sp = pd.Series([1.0, 1.1, 1.2], index=pd.to_datetime(["2020-01-06", "2020-01-13", "2020-01-21"]))
    marks = pd.to_datetime(["2020-01-08", "2020-01-15", "2020-01-22"])
    got = R.align_book_to_marks(sp, pd.DatetimeIndex(marks))
    assert list(got.values) == [1.0, 1.1, 1.2]


def test_memmel_se_is_zero_on_identical_legs():
    rng = np.random.default_rng(431)
    x = pd.Series(rng.normal(0.001, 0.02, 200), index=pd.bdate_range("2015-01-01", periods=200))
    d = R.memmel_se(x, x)
    assert d["n"] == 200
    assert d["d_sharpe"] == 0.0
    assert d["se"] == 0.0
    assert d["rho"] == 1.0
