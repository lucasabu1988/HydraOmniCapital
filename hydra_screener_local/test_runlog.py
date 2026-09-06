"""TASK-359 — run manifests. No network, no live-path wrap."""
from __future__ import annotations

import json
import logging
import os
import sys
from datetime import datetime

import pandas as pd
import pytest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from config import ALGO_VERSION, FILTERS, V9  # noqa: E402
import runlog_cli  # noqa: E402
from utils import runlog as R  # noqa: E402


def test_start_run_writes_manifest_and_log(tmp_path, monkeypatch):
    monkeypatch.setenv("HYDRA_BACKUP_DIR", "C:/secret/backups")
    monkeypatch.delenv("UNIVERSE", raising=False)
    ctx = R.start_run(
        "v9", ["portfolio_v9.py", "--capital", "100000"],
        runs_dir=tmp_path, now=datetime(2026, 9, 6, 15, 4, 5),
        git_info=("abc123def", False),
    )
    man = json.loads((ctx.directory / "manifest.json").read_text(encoding="utf-8"))
    assert ctx.directory.name == "20260906_150405_v9"
    assert man["git_commit"] == "abc123def" and man["git_dirty"] is False
    assert man["ALGO_VERSION"] == ALGO_VERSION
    assert man["config_sha256"]["V9"] == R._sha256_json(V9)
    assert man["config_sha256"]["FILTERS"] == R._sha256_json(FILTERS)
    assert man["argv"][0] == "portfolio_v9.py"
    assert man["env_set"] == ["HYDRA_BACKUP_DIR"]
    blob = json.dumps(man)
    assert "C:/secret/backups" not in blob and "100000" in blob  # argv may contain capital; env value must not
    assert man["exit_status"] is None
    assert (ctx.directory / "log.txt").exists()
    # file handler only — console (root) untouched
    assert all(not isinstance(h, logging.StreamHandler) or isinstance(h, logging.FileHandler)
               for h in ctx.logger.handlers)
    assert ctx.logger.propagate is False
    ctx.close_log()


def test_fingerprint_and_artifact_and_finish(tmp_path):
    ctx = R.start_run("daily", ["daily.py"], runs_dir=tmp_path, git_info=("c", True))
    idx = pd.bdate_range("2026-09-01", periods=3)
    px = pd.DataFrame({"AAA": [10.0, 11.0, 12.5], "BBB": [1.0, 1.0, 1.5]}, index=idx)
    fp = ctx.fingerprint("stocks", px)
    assert fp["last_bar"] == "2026-09-03"
    assert fp["shape"] == [3, 2]
    assert fp["last_row_sha256"] == R._sha256_json({"AAA": 12.5, "BBB": 1.5})
    ctx.artifact(tmp_path / "instructions.md")
    ctx.logger.info("hello from the run")
    man = ctx.finish(exit_status=0)
    assert man["exit_status"] == 0
    assert man["exception"] is None
    assert man["duration_s"] is not None
    assert man["git_dirty"] is True
    assert any("instructions.md" in a for a in man["artifacts"])
    log = (ctx.directory / "log.txt").read_text(encoding="utf-8")
    assert "hello from the run" in log
    ctx.close_log()


def test_finish_records_exception(tmp_path):
    ctx = R.start_run("x", ["x"], runs_dir=tmp_path, git_info=(None, False))
    ctx.finish(exit_status=3, exception=RuntimeError("boom"))
    man = R.load_manifest(ctx.directory)
    assert man["exit_status"] == 3
    assert "RuntimeError" in man["exception"] and "boom" in man["exception"]
    ctx.close_log()


def test_prune_keeps_last_n(tmp_path):
    for i in range(5):
        R.start_run("r", ["r"], runs_dir=tmp_path, now=datetime(2026, 9, 6, 12, 0, i), git_info=("c", False)).close_log()
    assert len(list(tmp_path.iterdir())) == 5
    n = R.prune(tmp_path, keep=3)
    left = sorted(p.name for p in tmp_path.iterdir())
    assert n == 2
    assert len(left) == 3
    assert left[0].startswith("20260906_120002")


def test_cli_last_and_prune(tmp_path, capsys):
    R.start_run("a", ["a"], runs_dir=tmp_path, now=datetime(2026, 9, 6, 10, 0, 0), git_info=("c", False)).close_log()
    later = R.start_run("b", ["b"], runs_dir=tmp_path, now=datetime(2026, 9, 6, 11, 0, 0), git_info=("c", False))
    later.close_log()
    rc = runlog_cli.main(["--last", "--dir", str(tmp_path)])
    assert rc == 0
    out = capsys.readouterr().out
    assert later.directory.name in out
    assert '"name": "b"' in out
    rc = runlog_cli.main(["--prune", "--keep", "1", "--dir", str(tmp_path)])
    assert rc == 0
    assert len(list(tmp_path.iterdir())) == 1
