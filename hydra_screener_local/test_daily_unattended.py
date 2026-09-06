"""TASK-364 — daily.py --unattended: exit codes and notifications."""
import os
import sys

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import daily as daily_mod  # noqa: E402
import utils.notify as NT  # noqa: E402


def _quiet(monkeypatch, tmp_path):
    monkeypatch.setattr(daily_mod, "run_screener", lambda universe: 0)
    monkeypatch.setattr(daily_mod, "backup_history_after_run", lambda: None)
    monkeypatch.setattr(daily_mod, "print_tv_instructions", lambda: None)
    monkeypatch.setattr(daily_mod, "maybe_refresh_pnl", lambda x: None)
    monkeypatch.setattr("utils.runlog.DEFAULT_RUNS_DIR", tmp_path / "runs")
    monkeypatch.setattr(NT, "DEFAULT_LOG", tmp_path / "alerts.log")
    monkeypatch.delenv("HYDRA_NOTIFY", raising=False)
    sent = []
    monkeypatch.setattr(NT, "notify", lambda level, title, body="", **k: sent.append((level, title, body)) or {"file": True})
    return sent


def _ok_out():
    return {"today": "2026-09-08", "orders": [], "fills": [1] * 30, "state": None,
            "summary": {"total": 100000.0, "sleeves": {}}, "preflight": {"rows": []},
            "instructions_md": "x.md", "sector_warning": None}


def test_ok_run_exits_0_and_sends_summary(monkeypatch, tmp_path):
    sent = _quiet(monkeypatch, tmp_path)
    monkeypatch.setattr("portfolio_v9.run", lambda *a, **k: _ok_out())
    rc = daily_mod.main(["--skip-screener", "--no-instructions", "--v9", "--unattended"])
    assert rc == 0
    assert [s[0] for s in sent] == ["INFO"]
    assert "fills settled: 30" in sent[0][2]


def test_preflight_refusal_exits_2_with_alert(monkeypatch, tmp_path):
    sent = _quiet(monkeypatch, tmp_path)

    def refuse(*a, **k):
        raise SystemExit("preflight hard fail; pass --force to plan anyway")

    monkeypatch.setattr("portfolio_v9.run", refuse)
    monkeypatch.setattr("journal.append_error", lambda *a, **k: None)
    rc = daily_mod.main(["--skip-screener", "--no-instructions", "--v9", "--unattended"])
    assert rc == 2
    assert sent[0][0] == "ALERT" and "refused to plan" in sent[0][1] and "preflight hard fail" in sent[0][2]


def test_exception_exits_3_with_alert(monkeypatch, tmp_path):
    sent = _quiet(monkeypatch, tmp_path)

    def boom(*a, **k):
        raise RuntimeError("yfinance exploded")

    monkeypatch.setattr("portfolio_v9.run", boom)
    monkeypatch.setattr("journal.append_error", lambda *a, **k: None)
    rc = daily_mod.main(["--skip-screener", "--no-instructions", "--v9", "--unattended"])
    assert rc == 3
    assert sent[0][0] == "ALERT" and "RuntimeError: yfinance exploded" in sent[0][2]


def test_degraded_sends_a_warn_before_the_summary(monkeypatch, tmp_path):
    sent = _quiet(monkeypatch, tmp_path)
    out = _ok_out()
    out["sector_warning"] = "38% Other in the pool"
    monkeypatch.setattr("portfolio_v9.run", lambda *a, **k: out)
    rc = daily_mod.main(["--skip-screener", "--no-instructions", "--v9", "--unattended"])
    assert rc == 0
    assert [s[0] for s in sent] == ["WARN", "INFO"]


def test_screener_failure_with_v9_ok_exits_1(monkeypatch, tmp_path):
    sent = _quiet(monkeypatch, tmp_path)
    monkeypatch.setattr(daily_mod, "run_screener", lambda universe: 7)
    monkeypatch.setattr("portfolio_v9.run", lambda *a, **k: _ok_out())
    rc = daily_mod.main(["--no-instructions", "--v9", "--unattended"])
    assert rc == 1
    assert "screener (Pine artefacts) exited 7" in sent[-1][2]


def test_attended_mode_unchanged(monkeypatch, tmp_path):
    """Without --unattended the exit codes are the old ones (0 / 1) and nothing is sent."""
    sent = _quiet(monkeypatch, tmp_path)

    def refuse(*a, **k):
        raise SystemExit("preflight hard fail")

    monkeypatch.setattr("portfolio_v9.run", refuse)
    monkeypatch.setattr("journal.append_error", lambda *a, **k: None)
    rc = daily_mod.main(["--skip-screener", "--no-instructions", "--v9"])
    assert rc == 1 and sent == []


def test_file_transport_really_writes(monkeypatch, tmp_path):
    """End to end without the notify fake: the alerts log gets the ALERT line."""
    monkeypatch.setattr(daily_mod, "run_screener", lambda universe: 0)
    monkeypatch.setattr(daily_mod, "backup_history_after_run", lambda: None)
    monkeypatch.setattr(daily_mod, "print_tv_instructions", lambda: None)
    monkeypatch.setattr(daily_mod, "maybe_refresh_pnl", lambda x: None)
    monkeypatch.setattr("utils.runlog.DEFAULT_RUNS_DIR", tmp_path / "runs")
    monkeypatch.setattr(NT, "DEFAULT_LOG", tmp_path / "alerts.log")
    monkeypatch.delenv("HYDRA_NOTIFY", raising=False)

    def refuse(*a, **k):
        raise SystemExit("state x: unknown schema_version 9")

    monkeypatch.setattr("portfolio_v9.run", refuse)
    monkeypatch.setattr("journal.append_error", lambda *a, **k: None)
    rc = daily_mod.main(["--skip-screener", "--no-instructions", "--v9", "--unattended"])
    assert rc == 2
    txt = (tmp_path / "alerts.log").read_text(encoding="utf-8")
    assert "ALERT" in txt and "unknown schema_version 9" in txt
    assert isinstance(pd.Timestamp(txt.split()[0]), pd.Timestamp)     # ISO stamp first
