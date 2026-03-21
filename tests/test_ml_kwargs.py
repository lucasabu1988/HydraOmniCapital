"""Tests for **kwargs support in DecisionLogger methods."""
import json
import tempfile
from pathlib import Path

import pytest

from compass_ml_learning import DecisionLogger


@pytest.fixture
def logger_tmpdir(tmp_path):
    dl = DecisionLogger(db_dir=str(tmp_path / "ml"))
    return dl, tmp_path / "ml"


def _read_last_jsonl(path):
    lines = Path(path).read_text(encoding="utf-8").strip().splitlines()
    return json.loads(lines[-1])


def _call_log_entry(dl, **extra_kwargs):
    return dl.log_entry(
        symbol="AAPL",
        sector="Technology",
        momentum_score=0.5,
        momentum_rank=0.8,
        entry_vol_ann=0.25,
        entry_daily_vol=0.016,
        adaptive_stop_pct=-0.08,
        trailing_stop_pct=-0.03,
        regime_score=0.6,
        max_positions_target=5,
        current_n_positions=3,
        portfolio_value=100000.0,
        portfolio_drawdown=-0.05,
        current_leverage=0.8,
        crash_cooldown=0,
        trading_day=10,
        spy_hist=None,
        stock_hist=None,
        source="backtest",
        **extra_kwargs,
    )


def _call_log_exit(dl, **extra_kwargs):
    dl.log_exit(
        symbol="AAPL",
        sector="Technology",
        exit_reason="hold_expired",
        entry_price=150.0,
        exit_price=160.0,
        pnl_usd=1000.0,
        days_held=5,
        high_price=162.0,
        entry_vol_ann=0.25,
        entry_daily_vol=0.016,
        adaptive_stop_pct=-0.08,
        entry_momentum_score=0.5,
        entry_momentum_rank=0.8,
        regime_score=0.6,
        max_positions_target=5,
        current_n_positions=3,
        portfolio_value=101000.0,
        portfolio_drawdown=-0.02,
        current_leverage=0.8,
        crash_cooldown=0,
        trading_day=15,
        spy_hist=None,
        spy_return_during_hold=0.03,
        source="backtest",
        **extra_kwargs,
    )


class TestLogEntryKwargs:
    def test_log_entry_merges_kwargs(self, logger_tmpdir):
        dl, db_dir = logger_tmpdir
        _call_log_entry(dl, reconstructed=True, recovery_date="2026-03-21")
        record = _read_last_jsonl(db_dir / "decisions.jsonl")
        assert record["reconstructed"] is True
        assert record["recovery_date"] == "2026-03-21"

    def test_log_entry_without_kwargs_unchanged(self, logger_tmpdir):
        dl, db_dir = logger_tmpdir
        _call_log_entry(dl)
        record = _read_last_jsonl(db_dir / "decisions.jsonl")
        assert "reconstructed" not in record
        assert record["symbol"] == "AAPL"
        assert record["decision_type"] == "entry"


class TestLogExitKwargs:
    def test_log_exit_merges_kwargs(self, logger_tmpdir):
        dl, db_dir = logger_tmpdir
        # Create an open entry first so exit has context
        _call_log_entry(dl)
        _call_log_exit(dl, reconstructed=True, recovery_date="2026-03-21")

        # Check the exit decision record
        decisions = (db_dir / "decisions.jsonl").read_text(encoding="utf-8").strip().splitlines()
        exit_record = json.loads(decisions[-1])
        assert exit_record["reconstructed"] is True
        assert exit_record["recovery_date"] == "2026-03-21"
        assert exit_record["decision_type"] == "exit"

        # Check the outcome record
        outcome = _read_last_jsonl(db_dir / "outcomes.jsonl")
        assert outcome["reconstructed"] is True
        assert outcome["recovery_date"] == "2026-03-21"
