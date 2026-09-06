"""TASK-356 — evidence review over a synthetic 8-week journal. No network."""
import json
import os
import sys


sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import evidence_review as ER  # noqa: E402


def _rec(date, **kw):
    rec = {
        "date": date,
        "seen": {
            "stock_exposure": 0.8,
            "sector_cap_displaced": [],
            "degraded": None,
            "coverage": 0.97,
        },
        "did": {
            "transfers": 2,
            "interest_dollars": 1.0,
            "not_filled": 0,
            "hold_no_price": 0,
            "write_offs": 0,
            "write_off_dollars": 0.0,
            "slippage": {"rows": [
                {"sleeve": "stocks", "slippage_bp": 12.0},
                {"sleeve": "etf", "slippage_bp": 4.0},
            ]},
        },
        "book": {"total": 100000.0},
        "expectation": {
            "live_cumulative": 0.02,
            "step_return_percentile": 55.0,
            "cone": {"n_steps": 8, "p5": -8.0, "p50": 1.0, "p95": 12.0},
        },
        "process": {"preflight": {"hard": False, "warn": False}, "reconcile_residual": 10.0},
    }
    for k, v in kw.items():
        if k in rec and isinstance(rec[k], dict) and isinstance(v, dict):
            rec[k] = {**rec[k], **v}
        else:
            rec[k] = v
    return rec


def _eight(tmp_path):
    weeks = [
        _rec("2026-10-02"),
        _rec("2026-10-09", seen={"sector_cap_displaced": [{"ticker": "X", "sector": "Energy"}],
                                 "stock_exposure": 0.8, "degraded": None, "coverage": 0.97}),
        _rec("2026-10-16", process={"preflight": {"hard": True}, "reconcile_residual": 10.0}),
        _rec("2026-10-23", process={"preflight": {"hard": False}, "reconcile_residual": 800.0}),  # 0.8%
        _rec("2026-10-30", seen={"degraded": "cap sectorial no aplicado", "stock_exposure": 0.7,
                                 "sector_cap_displaced": [], "coverage": 0.91}),
        _rec("2026-11-06", did={"not_filled": 1, "hold_no_price": 2, "write_offs": 1,
                                "write_off_dollars": 12.0, "transfers": 2, "interest_dollars": 1.0,
                                "slippage": {"rows": []}}),
        _rec("2026-11-13"),
        _rec("2026-11-20", expectation={"live_cumulative": -0.12, "step_return_percentile": 4.0,
                                        "cone": {"n_steps": 8, "p5": -8.0, "p50": 1.0, "p95": 12.0}}),
    ]
    d = tmp_path / "journal"
    d.mkdir()
    for r in weeks:
        (d / f"{r['date']}.json").write_text(json.dumps(r), encoding="utf-8")
    return d, weeks


def test_eight_weeks_seven_questions(tmp_path):
    d, _ = _eight(tmp_path)
    recs = ER.load_journal(d, since="2026-10-01", until="2027-01-01")
    assert len(recs) == 8
    rep = ER.review(recs, "2026-Q4")
    assert rep["n"] == 8
    assert rep["n_displaced"] == 1
    assert rep["sectors"]["Energy"] == 1
    assert rep["not_filled"] == 1 and rep["hold_no_price"] == 2 and rep["write_offs"] == 1
    assert rep["n_degraded"] == 1
    assert rep["n_preflight_hard"] == 1
    kinds = {t["kind"] for t in rep["triggers"]}
    assert "preflight_hard_fail" in kinds
    assert "residual_gt_0.5pct" in kinds
    assert "drawdown_beyond_p95" in kinds
    text = ER.render(rep)
    for i in range(1, 8):
        assert f"## {i}." in text
    assert "hypothesis" in text.lower()


def test_quarter_filter(tmp_path):
    d, _ = _eight(tmp_path)
    label, since, until = ER.parse_quarter("2026-Q4")
    recs = ER.load_journal(d, since=since, until=until)
    assert [r["date"] for r in recs][0] >= "2026-10-01"
    assert all(r["date"] < "2027-01-01" for r in recs)


def test_cli_writes_comms_file(tmp_path):
    d, _ = _eight(tmp_path)
    out = tmp_path / "evidence-2026-Q4.md"
    rc = ER.main(["--quarter", "2026-Q4", "--journal-dir", str(d), "--out", str(out)])
    assert rc == 0 and out.exists()
    body = out.read_text(encoding="utf-8")
    assert "Evidence review" in body
    assert "TRIGGER" not in body or "preflight" in body.lower() or "Triggers" in body
