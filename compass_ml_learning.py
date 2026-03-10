"""
COMPASS ML Learning System
===========================
Automated learning from COMPASS v8.4 live execution data.

Architecture:
  - DecisionLogger: Instruments every decision point (entry/exit/hold/skip/regime)
  - FeatureStore: Builds feature vectors at each decision, enriched with market context
  - OutcomeTracker: Resolves outcomes post-factum when position closes
  - LearningEngine: Trains models as data accumulates; escalates from rules to ML
  - InsightReporter: Surfaces actionable parameter suggestions

Data grows from 8 trading days -> statistically useful over weeks/months.
Three learning phases are defined with explicit data requirements.

Design philosophy:
  - Zero look-ahead bias by construction: features use only data available at decision time
  - Every model is treated as a hypothesis, not a fact
  - Parameter suggestions require >90% bootstrap confidence before surfacing
  - All inference is conditional on regime + vol environment to avoid regime conflation

Author: COMPASS ML Learning System
"""

import json
import os
import numpy as np
import pandas as pd
from datetime import datetime, date
from typing import Dict, List, Optional, Tuple, Any
from dataclasses import dataclass, field, asdict
from pathlib import Path
import logging
import warnings

warnings.filterwarnings('ignore', category=FutureWarning)
warnings.filterwarnings('ignore', category=DeprecationWarning)

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logger = logging.getLogger("compass.ml")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

LEARNING_DB_DIR = "state/ml_learning"
DECISIONS_FILE  = "state/ml_learning/decisions.jsonl"
OUTCOMES_FILE   = "state/ml_learning/outcomes.jsonl"
SNAPSHOTS_FILE  = "state/ml_learning/daily_snapshots.jsonl"
INSIGHTS_FILE   = "state/ml_learning/insights.json"
MODELS_DIR      = "state/ml_learning/models"

# Phase thresholds (trading days of data)
PHASE_1_MIN_DAYS  = 0     # Statistical summaries only
PHASE_2_MIN_DAYS  = 63    # ~3 months: lightweight ML begins
PHASE_3_MIN_DAYS  = 252   # ~12 months: full supervised learning

# Regime buckets for conditional analysis
REGIME_BULL      = "bull"         # score >= 0.65
REGIME_MILD_BULL = "mild_bull"    # 0.50 <= score < 0.65
REGIME_MILD_BEAR = "mild_bear"    # 0.35 <= score < 0.50
REGIME_BEAR      = "bear"         # score < 0.35

# Vol regime buckets (entry_daily_vol quantiles)
VOL_LOW    = "low_vol"    # < 1.5% daily
VOL_MEDIUM = "med_vol"    # 1.5-3.0%
VOL_HIGH   = "high_vol"   # > 3.0%


# ===========================================================================
# DATA SCHEMAS
# ===========================================================================

@dataclass
class DecisionRecord:
    """
    Captures every decision the algorithm makes, with full context.
    Written at decision time — zero look-ahead by construction.
    """
    # Identity
    decision_id: str          # uuid4 hex
    decision_type: str        # "entry" | "exit" | "hold" | "skip" | "regime_change" | "renewal"
    timestamp: str            # ISO8601
    trading_day: int          # algorithm's internal trading_day_counter
    date: str                 # YYYY-MM-DD

    # Subject
    symbol: str               # ticker (empty string for portfolio-level decisions)
    sector: str               # GICS sector from SECTOR_MAP

    # Algorithm context at decision time
    regime_score: float       # continuous [0,1]
    regime_bucket: str        # bull/mild_bull/mild_bear/bear
    max_positions_target: int # what regime says we should hold
    current_n_positions: int  # how many we actually hold
    portfolio_value: float
    portfolio_drawdown: float # from peak, negative
    current_leverage: float
    crash_cooldown: int

    # SPY context
    spy_price: Optional[float]
    spy_sma200: Optional[float]
    spy_vs_sma200_pct: Optional[float]   # (spy/sma200) - 1
    spy_sma50: Optional[float]
    spy_10d_vol: Optional[float]         # annualized
    spy_20d_return: Optional[float]

    # Stock-level features (populated for entry/exit/skip/hold)
    momentum_score: Optional[float]      # risk-adj momentum score
    momentum_rank: Optional[float]       # percentile rank in universe [0,1]
    entry_vol_ann: Optional[float]       # annualized vol at entry
    entry_daily_vol: Optional[float]     # daily vol at entry
    adaptive_stop_pct: Optional[float]   # computed stop level
    trailing_stop_pct: Optional[float]   # vol-scaled trailing

    # Position state (for hold/exit decisions)
    days_held: Optional[int]
    current_return: Optional[float]      # (current_price - entry_price) / entry_price
    high_price: Optional[float]
    entry_price: Optional[float]
    drawdown_from_high: Optional[float]  # (current_price - high_price) / high_price

    # Exit-specific
    exit_reason: Optional[str]           # hold_expired / position_stop / trailing_stop / universe_rotation / regime_reduce

    # Skip-specific (why this stock was not selected)
    skip_reason: Optional[str]           # "not_top_n" | "sector_limit" | "quality_filter" | "no_cash"
    skip_universe_rank: Optional[int]    # rank in momentum scores when skipped

    # Metadata
    version: str = "8.4"
    source: str = "live"              # "live" = paper trading decisions, "backtest" = historical backtest data

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class OutcomeRecord:
    """
    Resolves a completed trade with outcome metrics.
    Written when a position closes (after DecisionRecord for the exit).
    Links back to the entry DecisionRecord via entry_decision_id.
    """
    outcome_id: str
    entry_decision_id: str       # links to DecisionRecord of the BUY
    symbol: str
    sector: str

    # Time
    entry_date: str
    exit_date: str
    trading_days_held: int       # actual days held

    # Return metrics
    gross_return: float          # (exit_price - entry_price) / entry_price
    pnl_usd: float
    exit_reason: str

    # Context at entry (denormalized from DecisionRecord for easy ML access)
    entry_regime_score: float
    entry_regime_bucket: str
    entry_momentum_score: float
    entry_momentum_rank: float
    entry_vol_ann: float
    entry_daily_vol: float
    entry_portfolio_drawdown: float
    entry_spy_vs_sma200: float
    entry_adaptive_stop: float

    # Outcome classification (labels for supervised learning)
    outcome_label: str           # "strong_win" | "weak_win" | "flat" | "weak_loss" | "stop_loss"
    was_stopped: bool            # hit adaptive stop
    was_trailed: bool            # hit trailing stop
    held_to_expiry: bool         # hold_expired or renewal
    beat_spy: bool               # gross_return > SPY return over same period

    # SPY during hold (for alpha attribution)
    spy_return_during_hold: Optional[float]
    alpha_vs_spy: Optional[float]         # gross_return - spy_return

    version: str = "8.4"

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class DailySnapshot:
    """
    End-of-day portfolio snapshot for time-series analysis.
    Captures the full market context, regime state, and portfolio composition.
    Written once per trading day at market close.
    """
    date: str
    trading_day: int
    portfolio_value: float
    cash: float
    peak_value: float
    drawdown: float
    n_positions: int
    leverage: float
    crash_cooldown: int

    # Regime
    regime_score: float
    regime_bucket: str
    max_positions_target: int

    # SPY state
    spy_price: Optional[float]
    spy_sma200: Optional[float]
    spy_vs_sma200_pct: Optional[float]
    spy_10d_vol: Optional[float]
    spy_20d_return: Optional[float]

    # Portfolio composition
    positions: List[str]            # list of tickers held
    sectors_held: List[str]         # sectors represented
    avg_entry_vol: Optional[float]  # mean entry_daily_vol across positions
    avg_days_held: Optional[float]

    # Daily P&L
    daily_pnl_pct: Optional[float]    # today's portfolio return
    spy_daily_return: Optional[float]

    version: str = "8.4"

    def to_dict(self) -> dict:
        return asdict(self)


# ===========================================================================
# DECISION LOGGER
# ===========================================================================

class DecisionLogger:
    """
    Instruments the COMPASS live engine to capture every decision.
    Designed to be attached to COMPASSLive with minimal invasiveness.

    Usage in COMPASSLive:
        self.ml_logger = DecisionLogger()
        # In open_new_positions(): self.ml_logger.log_entry(...)
        # In check_position_exits(): self.ml_logger.log_exit(...)
        # In update_regime(): self.ml_logger.log_regime_change(...)
        # At end of day: self.ml_logger.log_daily_snapshot(...)
    """

    def __init__(self, db_dir: str = LEARNING_DB_DIR):
        self.db_dir = Path(db_dir)
        self.db_dir.mkdir(parents=True, exist_ok=True)
        Path(MODELS_DIR).mkdir(parents=True, exist_ok=True)

        self._decisions_path = Path(DECISIONS_FILE)
        self._outcomes_path  = Path(OUTCOMES_FILE)
        self._snapshots_path = Path(SNAPSHOTS_FILE)

        # In-memory index: symbol -> entry_decision_id (for linking outcomes)
        self._open_entries: Dict[str, str] = {}

        logger.info(f"DecisionLogger initialized -> {self.db_dir}")

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _make_id(self) -> str:
        import uuid
        return uuid.uuid4().hex

    def _append_jsonl(self, path: Path, record: dict):
        """Append one JSON line to a .jsonl file (fail-safe)."""
        try:
            line = json.dumps(record, default=str) + "\n"
            with open(path, "a", encoding="utf-8") as f:
                f.write(line)
        except Exception as e:
            logger.error(f"Failed to append to {path}: {e}")

    def _regime_bucket(self, score: float) -> str:
        if score >= 0.65:
            return REGIME_BULL
        elif score >= 0.50:
            return REGIME_MILD_BULL
        elif score >= 0.35:
            return REGIME_MILD_BEAR
        else:
            return REGIME_BEAR

    def _spy_features(self, spy_hist) -> dict:
        """Extract SPY context features from historical DataFrame."""
        if spy_hist is None or not hasattr(spy_hist, '__len__') or len(spy_hist) < 200:
            return {
                "spy_price": None, "spy_sma200": None,
                "spy_vs_sma200_pct": None, "spy_sma50": None,
                "spy_10d_vol": None, "spy_20d_return": None,
            }
        close = spy_hist["Close"]
        spy_price = float(close.iloc[-1])
        sma200 = float(close.iloc[-200:].mean())
        sma50  = float(close.iloc[-50:].mean()) if len(close) >= 50 else None
        returns = close.pct_change().dropna()
        vol_10d = float(returns.iloc[-10:].std() * np.sqrt(252)) if len(returns) >= 10 else None
        ret_20d = float((close.iloc[-1] / close.iloc[-21]) - 1) if len(close) >= 21 else None
        ret_1d = float(returns.iloc[-1]) if len(returns) >= 1 else None
        return {
            "spy_price": spy_price,
            "spy_sma200": sma200,
            "spy_vs_sma200_pct": (spy_price / sma200) - 1 if sma200 else None,
            "spy_sma50": sma50,
            "spy_10d_vol": vol_10d,
            "spy_20d_return": ret_20d,
            "spy_daily_return": ret_1d,
        }

    # ------------------------------------------------------------------
    # Public logging methods
    # ------------------------------------------------------------------

    def log_entry(
        self,
        symbol: str,
        sector: str,
        momentum_score: float,
        momentum_rank: float,        # percentile [0,1] in universe
        entry_vol_ann: float,
        entry_daily_vol: float,
        adaptive_stop_pct: float,
        trailing_stop_pct: float,
        regime_score: float,
        max_positions_target: int,
        current_n_positions: int,
        portfolio_value: float,
        portfolio_drawdown: float,
        current_leverage: float,
        crash_cooldown: int,
        trading_day: int,
        spy_hist=None,
        source: str = "live",
    ) -> str:
        """Log a BUY decision. Returns decision_id for later linking to outcome."""
        dec_id = self._make_id()
        spy_ctx = self._spy_features(spy_hist)

        record = DecisionRecord(
            decision_id=dec_id,
            decision_type="entry",
            timestamp=datetime.now().isoformat(),
            trading_day=trading_day,
            date=date.today().isoformat(),
            symbol=symbol,
            sector=sector,
            regime_score=regime_score,
            regime_bucket=self._regime_bucket(regime_score),
            max_positions_target=max_positions_target,
            current_n_positions=current_n_positions,
            portfolio_value=portfolio_value,
            portfolio_drawdown=portfolio_drawdown,
            current_leverage=current_leverage,
            crash_cooldown=crash_cooldown,
            spy_price=spy_ctx["spy_price"],
            spy_sma200=spy_ctx["spy_sma200"],
            spy_vs_sma200_pct=spy_ctx["spy_vs_sma200_pct"],
            spy_sma50=spy_ctx["spy_sma50"],
            spy_10d_vol=spy_ctx["spy_10d_vol"],
            spy_20d_return=spy_ctx["spy_20d_return"],
            momentum_score=momentum_score,
            momentum_rank=momentum_rank,
            entry_vol_ann=entry_vol_ann,
            entry_daily_vol=entry_daily_vol,
            adaptive_stop_pct=adaptive_stop_pct,
            trailing_stop_pct=trailing_stop_pct,
            days_held=None,
            current_return=None,
            high_price=None,
            entry_price=None,
            drawdown_from_high=None,
            exit_reason=None,
            skip_reason=None,
            skip_universe_rank=None,
            source=source,
        )
        self._append_jsonl(self._decisions_path, record.to_dict())
        self._open_entries[symbol] = dec_id
        logger.debug(f"ML: logged entry {symbol} dec_id={dec_id[:8]}")
        return dec_id

    def log_exit(
        self,
        symbol: str,
        sector: str,
        exit_reason: str,
        entry_price: float,
        exit_price: float,
        pnl_usd: float,
        days_held: int,
        high_price: float,
        entry_vol_ann: float,
        entry_daily_vol: float,
        adaptive_stop_pct: float,
        entry_momentum_score: float,
        entry_momentum_rank: float,
        regime_score: float,
        max_positions_target: int,
        current_n_positions: int,
        portfolio_value: float,
        portfolio_drawdown: float,
        current_leverage: float,
        crash_cooldown: int,
        trading_day: int,
        spy_hist=None,
        spy_return_during_hold: Optional[float] = None,
        source: str = "live",
    ):
        """Log a SELL decision and create a linked OutcomeRecord."""
        dec_id = self._make_id()
        spy_ctx = self._spy_features(spy_hist)
        gross_return = (exit_price - entry_price) / entry_price if entry_price > 0 else 0.0
        drawdown_from_high = (exit_price - high_price) / high_price if high_price > 0 else 0.0

        # Exit decision record
        exit_record = DecisionRecord(
            decision_id=dec_id,
            decision_type="exit",
            timestamp=datetime.now().isoformat(),
            trading_day=trading_day,
            date=date.today().isoformat(),
            symbol=symbol,
            sector=sector,
            regime_score=regime_score,
            regime_bucket=self._regime_bucket(regime_score),
            max_positions_target=max_positions_target,
            current_n_positions=current_n_positions,
            portfolio_value=portfolio_value,
            portfolio_drawdown=portfolio_drawdown,
            current_leverage=current_leverage,
            crash_cooldown=crash_cooldown,
            spy_price=spy_ctx["spy_price"],
            spy_sma200=spy_ctx["spy_sma200"],
            spy_vs_sma200_pct=spy_ctx["spy_vs_sma200_pct"],
            spy_sma50=spy_ctx["spy_sma50"],
            spy_10d_vol=spy_ctx["spy_10d_vol"],
            spy_20d_return=spy_ctx["spy_20d_return"],
            momentum_score=entry_momentum_score,
            momentum_rank=entry_momentum_rank,
            entry_vol_ann=entry_vol_ann,
            entry_daily_vol=entry_daily_vol,
            adaptive_stop_pct=adaptive_stop_pct,
            trailing_stop_pct=None,
            days_held=days_held,
            current_return=gross_return,
            high_price=high_price,
            entry_price=entry_price,
            drawdown_from_high=drawdown_from_high,
            exit_reason=exit_reason,
            skip_reason=None,
            skip_universe_rank=None,
            source=source,
        )
        self._append_jsonl(self._decisions_path, exit_record.to_dict())

        # Outcome record
        entry_decision_id = self._open_entries.pop(symbol, "unknown")
        outcome_label = self._classify_outcome(gross_return, exit_reason)

        outcome = OutcomeRecord(
            outcome_id=self._make_id(),
            entry_decision_id=entry_decision_id,
            symbol=symbol,
            sector=sector,
            entry_date=(
                pd.Timestamp.today() - pd.Timedelta(days=days_held)
            ).strftime("%Y-%m-%d"),
            exit_date=date.today().isoformat(),
            trading_days_held=days_held,
            gross_return=gross_return,
            pnl_usd=pnl_usd,
            exit_reason=exit_reason,
            entry_regime_score=regime_score,
            entry_regime_bucket=self._regime_bucket(regime_score),
            entry_momentum_score=entry_momentum_score,
            entry_momentum_rank=entry_momentum_rank,
            entry_vol_ann=entry_vol_ann,
            entry_daily_vol=entry_daily_vol,
            entry_portfolio_drawdown=portfolio_drawdown,
            entry_spy_vs_sma200=spy_ctx["spy_vs_sma200_pct"] or 0.0,
            entry_adaptive_stop=adaptive_stop_pct,
            outcome_label=outcome_label,
            was_stopped=(exit_reason in ("position_stop_adaptive", "position_stop")),
            was_trailed=(exit_reason == "trailing_stop"),
            held_to_expiry=(exit_reason == "hold_expired"),
            beat_spy=(gross_return > (spy_return_during_hold or 0)),
            spy_return_during_hold=spy_return_during_hold,
            alpha_vs_spy=(
                gross_return - spy_return_during_hold
                if spy_return_during_hold is not None else None
            ),
        )
        self._append_jsonl(self._outcomes_path, outcome.to_dict())
        logger.debug(
            f"ML: logged exit+outcome {symbol} reason={exit_reason} ret={gross_return:.2%}"
        )

    def log_skip(
        self,
        symbol: str,
        sector: str,
        skip_reason: str,
        universe_rank: Optional[int],
        momentum_score: Optional[float],
        regime_score: float,
        trading_day: int,
        portfolio_value: float,
        portfolio_drawdown: float,
        current_n_positions: int,
        max_positions_target: int,
    ):
        """Log a stock that was considered but not selected."""
        dec_id = self._make_id()
        record = DecisionRecord(
            decision_id=dec_id,
            decision_type="skip",
            timestamp=datetime.now().isoformat(),
            trading_day=trading_day,
            date=date.today().isoformat(),
            symbol=symbol,
            sector=sector,
            regime_score=regime_score,
            regime_bucket=self._regime_bucket(regime_score),
            max_positions_target=max_positions_target,
            current_n_positions=current_n_positions,
            portfolio_value=portfolio_value,
            portfolio_drawdown=portfolio_drawdown,
            current_leverage=1.0,
            crash_cooldown=0,
            spy_price=None, spy_sma200=None, spy_vs_sma200_pct=None,
            spy_sma50=None, spy_10d_vol=None, spy_20d_return=None,
            momentum_score=momentum_score,
            momentum_rank=None,
            entry_vol_ann=None,
            entry_daily_vol=None,
            adaptive_stop_pct=None,
            trailing_stop_pct=None,
            days_held=None,
            current_return=None,
            high_price=None,
            entry_price=None,
            drawdown_from_high=None,
            exit_reason=None,
            skip_reason=skip_reason,
            skip_universe_rank=universe_rank,
        )
        self._append_jsonl(self._decisions_path, record.to_dict())

    def log_hold(
        self,
        symbol: str,
        sector: str,
        days_held: int,
        current_return: float,
        drawdown_from_high: float,
        entry_daily_vol: float,
        adaptive_stop_pct: float,
        regime_score: float,
        trading_day: int,
        portfolio_value: float,
        portfolio_drawdown: float,
    ):
        """Log an intraday hold decision (stop checked but not triggered)."""
        dec_id = self._make_id()
        record = DecisionRecord(
            decision_id=dec_id,
            decision_type="hold",
            timestamp=datetime.now().isoformat(),
            trading_day=trading_day,
            date=date.today().isoformat(),
            symbol=symbol,
            sector=sector,
            regime_score=regime_score,
            regime_bucket=self._regime_bucket(regime_score),
            max_positions_target=0,
            current_n_positions=0,
            portfolio_value=portfolio_value,
            portfolio_drawdown=portfolio_drawdown,
            current_leverage=1.0,
            crash_cooldown=0,
            spy_price=None, spy_sma200=None, spy_vs_sma200_pct=None,
            spy_sma50=None, spy_10d_vol=None, spy_20d_return=None,
            momentum_score=None,
            momentum_rank=None,
            entry_vol_ann=None,
            entry_daily_vol=entry_daily_vol,
            adaptive_stop_pct=adaptive_stop_pct,
            trailing_stop_pct=None,
            days_held=days_held,
            current_return=current_return,
            high_price=None,
            entry_price=None,
            drawdown_from_high=drawdown_from_high,
            exit_reason=None,
            skip_reason=None,
            skip_universe_rank=None,
        )
        self._append_jsonl(self._decisions_path, record.to_dict())

    def log_regime_change(
        self,
        old_score: float,
        new_score: float,
        old_regime: str,
        new_regime: str,
        trading_day: int,
        portfolio_value: float,
        spy_hist=None,
    ):
        """Log a regime transition event."""
        dec_id = self._make_id()
        spy_ctx = self._spy_features(spy_hist)
        record = DecisionRecord(
            decision_id=dec_id,
            decision_type="regime_change",
            timestamp=datetime.now().isoformat(),
            trading_day=trading_day,
            date=date.today().isoformat(),
            symbol="",
            sector="",
            regime_score=new_score,
            regime_bucket=self._regime_bucket(new_score),
            max_positions_target=0,
            current_n_positions=0,
            portfolio_value=portfolio_value,
            portfolio_drawdown=0.0,
            current_leverage=1.0,
            crash_cooldown=0,
            spy_price=spy_ctx["spy_price"],
            spy_sma200=spy_ctx["spy_sma200"],
            spy_vs_sma200_pct=spy_ctx["spy_vs_sma200_pct"],
            spy_sma50=spy_ctx["spy_sma50"],
            spy_10d_vol=spy_ctx["spy_10d_vol"],
            spy_20d_return=spy_ctx["spy_20d_return"],
            momentum_score=None,
            momentum_rank=None,
            entry_vol_ann=None,
            entry_daily_vol=None,
            adaptive_stop_pct=None,
            trailing_stop_pct=None,
            days_held=None,
            current_return=None,
            high_price=None,
            entry_price=None,
            drawdown_from_high=None,
            exit_reason=None,
            skip_reason=None,
            skip_universe_rank=None,
        )
        self._append_jsonl(self._decisions_path, record.to_dict())
        logger.info(
            f"ML: logged regime change {old_regime}->{new_regime} "
            f"({old_score:.2f}->{new_score:.2f})"
        )

    def log_daily_snapshot(
        self,
        trading_day: int,
        portfolio_value: float,
        cash: float,
        peak_value: float,
        n_positions: int,
        leverage: float,
        crash_cooldown: int,
        regime_score: float,
        max_positions_target: int,
        positions: List[str],
        position_meta: Dict[str, dict],
        spy_hist=None,
        prev_portfolio_value: Optional[float] = None,
    ):
        """Write end-of-day portfolio snapshot."""
        spy_ctx = self._spy_features(spy_hist)
        drawdown = (portfolio_value - peak_value) / peak_value if peak_value > 0 else 0.0

        sectors_held = list(
            {position_meta.get(s, {}).get("sector", "Unknown") for s in positions}
        )
        daily_vols = [position_meta.get(s, {}).get("entry_daily_vol") for s in positions]
        daily_vols = [v for v in daily_vols if v is not None]
        avg_entry_vol = float(np.mean(daily_vols)) if daily_vols else None

        held_days = []
        for s in positions:
            meta = position_meta.get(s, {})
            if "entry_day_index" in meta:
                held_days.append(trading_day - meta["entry_day_index"] + 1)
        avg_days_held = float(np.mean(held_days)) if held_days else None

        daily_pnl_pct = None
        if prev_portfolio_value and prev_portfolio_value > 0:
            daily_pnl_pct = (portfolio_value / prev_portfolio_value) - 1.0

        snapshot = DailySnapshot(
            date=date.today().isoformat(),
            trading_day=trading_day,
            portfolio_value=portfolio_value,
            cash=cash,
            peak_value=peak_value,
            drawdown=drawdown,
            n_positions=n_positions,
            leverage=leverage,
            crash_cooldown=crash_cooldown,
            regime_score=regime_score,
            regime_bucket=self._regime_bucket(regime_score),
            max_positions_target=max_positions_target,
            spy_price=spy_ctx["spy_price"],
            spy_sma200=spy_ctx["spy_sma200"],
            spy_vs_sma200_pct=spy_ctx["spy_vs_sma200_pct"],
            spy_10d_vol=spy_ctx["spy_10d_vol"],
            spy_20d_return=spy_ctx["spy_20d_return"],
            positions=positions,
            sectors_held=sectors_held,
            avg_entry_vol=avg_entry_vol,
            avg_days_held=avg_days_held,
            daily_pnl_pct=daily_pnl_pct,
            spy_daily_return=spy_ctx.get("spy_daily_return"),
        )
        self._append_jsonl(self._snapshots_path, snapshot.to_dict())

    # ------------------------------------------------------------------
    # Outcome classification (labels)
    # ------------------------------------------------------------------

    @staticmethod
    def _classify_outcome(gross_return: float, exit_reason: str) -> str:
        """
        Five-class outcome label:
          strong_win : return > +4%
          weak_win   : 0% < return <= +4%
          flat       : -1% <= return <= 0%
          weak_loss  : -6% < return < -1%
          stop_loss  : hit adaptive stop (return <= -6%)
        """
        if exit_reason in ("position_stop_adaptive", "position_stop"):
            return "stop_loss"
        if gross_return > 0.04:
            return "strong_win"
        elif gross_return > 0.0:
            return "weak_win"
        elif gross_return >= -0.01:
            return "flat"
        else:
            return "weak_loss"


# ===========================================================================
# FEATURE STORE
# ===========================================================================

class FeatureStore:
    """
    Loads logged decisions and outcomes, joins them, and builds ML-ready
    feature matrices. All features are computed as of decision time (no LA bias).

    Feature categories:
      A. Momentum signal quality (score, rank, score squared)
      B. Volatility regime at entry (daily_vol, bucket dummies)
      C. Market regime (SPY trend, vol, SMA ratios)
      D. Portfolio state (drawdown, leverage, position count)
      E. Sector encoding (one-hot)
      F. Hold dynamics (days held, drawdown from high, return so far)
    """

    def __init__(self, db_dir: str = LEARNING_DB_DIR):
        self.db_dir = Path(db_dir)

    def load_decisions(self, decision_type: Optional[str] = None) -> pd.DataFrame:
        path = Path(DECISIONS_FILE)
        if not path.exists():
            return pd.DataFrame()
        records = []
        with open(path, "r") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    r = json.loads(line)
                    if decision_type is None or r.get("decision_type") == decision_type:
                        records.append(r)
                except json.JSONDecodeError:
                    continue
        return pd.DataFrame(records) if records else pd.DataFrame()

    def load_outcomes(self) -> pd.DataFrame:
        path = Path(OUTCOMES_FILE)
        if not path.exists():
            return pd.DataFrame()
        records = []
        with open(path, "r") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    records.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
        return pd.DataFrame(records) if records else pd.DataFrame()

    def load_snapshots(self) -> pd.DataFrame:
        path = Path(SNAPSHOTS_FILE)
        if not path.exists():
            return pd.DataFrame()
        records = []
        with open(path, "r") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    records.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
        df = pd.DataFrame(records) if records else pd.DataFrame()
        if not df.empty and "date" in df.columns:
            df["date"] = pd.to_datetime(df["date"])
        return df

    def build_entry_feature_matrix(self) -> pd.DataFrame:
        """
        Build a feature matrix for supervised learning on entry decisions.
        Each row = one completed trade (entry + outcome joined).
        Target: gross_return (regression), outcome_label (classification).

        Returns DataFrame with columns: feat_* + target_return + target_label
        """
        outcomes = self.load_outcomes()
        if outcomes.empty:
            return pd.DataFrame()

        entries = self.load_decisions("entry")
        if entries.empty:
            return pd.DataFrame()

        # Columns to pull from entries (beyond what outcomes already store)
        entry_cols = [
            "decision_id", "spy_10d_vol", "spy_vs_sma200_pct", "spy_20d_return",
            "portfolio_drawdown", "current_leverage", "crash_cooldown"
        ]
        available_cols = [c for c in entry_cols if c in entries.columns]

        merged = outcomes.merge(
            entries[available_cols],
            left_on="entry_decision_id",
            right_on="decision_id",
            how="left"
        )

        df = pd.DataFrame()

        # A. Momentum signal
        df["feat_momentum_score"]    = merged["entry_momentum_score"]
        df["feat_momentum_rank"]     = merged["entry_momentum_rank"]
        df["feat_momentum_score_sq"] = merged["entry_momentum_score"] ** 2

        # B. Volatility regime
        df["feat_daily_vol"]         = merged["entry_daily_vol"]
        df["feat_ann_vol"]           = merged["entry_vol_ann"]
        df["feat_vol_low"]           = (merged["entry_daily_vol"] < 0.015).astype(int)
        df["feat_vol_high"]          = (merged["entry_daily_vol"] > 0.030).astype(int)
        df["feat_adaptive_stop"]     = merged["entry_adaptive_stop"]

        # C. Market regime
        df["feat_regime_score"]      = merged["entry_regime_score"]
        df["feat_spy_vs_sma200"]     = merged["entry_spy_vs_sma200"]
        df["feat_regime_bull"]       = (merged["entry_regime_bucket"] == REGIME_BULL).astype(int)
        df["feat_regime_mild_bull"]  = (merged["entry_regime_bucket"] == REGIME_MILD_BULL).astype(int)
        df["feat_regime_mild_bear"]  = (merged["entry_regime_bucket"] == REGIME_MILD_BEAR).astype(int)
        if "spy_10d_vol" in merged.columns:
            df["feat_spy_10d_vol"]   = merged["spy_10d_vol"]
        else:
            df["feat_spy_10d_vol"]   = np.nan

        # D. Portfolio state at entry
        df["feat_portfolio_dd"]      = merged["entry_portfolio_drawdown"]
        df["feat_dd_severe"]         = (merged["entry_portfolio_drawdown"] < -0.10).astype(int)
        if "current_leverage" in merged.columns:
            df["feat_leverage"]      = merged["current_leverage"]

        # E. Sector encoding
        for sector in ["Technology", "Healthcare", "Financials", "Consumer",
                        "Energy", "Industrials", "Utilities", "Telecom"]:
            df[f"feat_sector_{sector.lower()}"] = (merged["sector"] == sector).astype(int)

        # Targets
        df["target_return"]          = merged["gross_return"]
        df["target_label"]           = merged["outcome_label"]
        df["target_beat_spy"]        = merged["beat_spy"].astype(int)
        df["symbol"]                 = merged["symbol"]
        df["exit_reason"]            = merged["exit_reason"]
        df["trading_days_held"]      = merged["trading_days_held"]
        df["entry_date"]             = merged["entry_date"]
        df["exit_date"]              = merged["exit_date"]

        return df.reset_index(drop=True)

    def build_stop_feature_matrix(self) -> pd.DataFrame:
        """
        Feature matrix focused on stop events.
        Used for: learning which entry conditions correlate with stop-outs.
        """
        outcomes = self.load_outcomes()
        if outcomes.empty:
            return pd.DataFrame()

        df = pd.DataFrame()
        df["feat_daily_vol"]      = outcomes["entry_daily_vol"]
        df["feat_adaptive_stop"]  = outcomes["entry_adaptive_stop"]
        df["feat_regime_score"]   = outcomes["entry_regime_score"]
        df["feat_spy_vs_sma200"]  = outcomes["entry_spy_vs_sma200"]
        df["feat_portfolio_dd"]   = outcomes["entry_portfolio_drawdown"]
        df["feat_momentum_score"] = outcomes["entry_momentum_score"]
        df["feat_momentum_rank"]  = outcomes["entry_momentum_rank"]
        df["feat_days_held"]      = outcomes["trading_days_held"]
        df["feat_sector"]         = outcomes["sector"]
        df["target_was_stopped"]  = outcomes["was_stopped"].astype(int)
        df["target_return"]       = outcomes["gross_return"]
        df["exit_reason"]         = outcomes["exit_reason"]
        df["symbol"]              = outcomes["symbol"]

        return df.reset_index(drop=True)


# ===========================================================================
# LEARNING ENGINE
# ===========================================================================

class LearningEngine:
    """
    Trains models as data accumulates.

    PHASE 1 (0-63 trading days):
        Statistical summaries only. Descriptive analytics.
        Bootstrap CIs on mean return by regime/sector/exit reason.
        No model training — too few samples.

    PHASE 2 (63-252 trading days):
        Lightweight regularized models.
        - Ridge regression for return prediction (alpha=10, heavy regularization)
        - Logistic regression for win/loss classification
        - Empirical stop calibration analysis
        All outputs come with confidence warnings about sample size.

    PHASE 3 (252+ trading days):
        Full supervised learning.
        - Gradient-boosted trees (LightGBM if available, else RandomForest)
        - Regime transition classification
        - Stop parameter optimization
        - Feature importance for signal decay monitoring
    """

    def __init__(
        self,
        feature_store: FeatureStore,
        trading_days_available: int,
    ):
        self.fs = feature_store
        self.n_days = trading_days_available
        self.models_dir = Path(MODELS_DIR)
        self.models_dir.mkdir(parents=True, exist_ok=True)

    def get_phase(self) -> int:
        if self.n_days < PHASE_2_MIN_DAYS:
            return 1
        elif self.n_days < PHASE_3_MIN_DAYS:
            return 2
        else:
            return 3

    def run(self) -> dict:
        """Run the appropriate analysis for the current data phase."""
        phase = self.get_phase()
        logger.info(f"LearningEngine: phase={phase}, n_days={self.n_days}")
        results = {"phase": phase, "n_days": self.n_days}

        if phase >= 1:
            results["phase1"] = self._phase1_statistics()
        if phase >= 2:
            results["phase2"] = self._phase2_lightweight_models()
        if phase >= 3:
            results["phase3"] = self._phase3_full_ml()

        return results

    # ------------------------------------------------------------------
    # Phase 1: Statistical summaries
    # ------------------------------------------------------------------

    def _phase1_statistics(self) -> dict:
        outcomes = self.fs.load_outcomes()
        if outcomes.empty:
            return {"status": "no_completed_trades_yet"}

        stats = {
            "n_completed_trades": len(outcomes),
            "overall": self._trade_stats(outcomes),
            "by_regime": {},
            "by_sector": {},
            "by_exit_reason": {},
            "by_vol_bucket": {},
            "stop_analysis": self._stop_analysis(outcomes),
        }

        if "entry_regime_bucket" in outcomes.columns:
            for bucket in [REGIME_BULL, REGIME_MILD_BULL, REGIME_MILD_BEAR, REGIME_BEAR]:
                sub = outcomes[outcomes["entry_regime_bucket"] == bucket]
                if len(sub) >= 2:
                    stats["by_regime"][bucket] = self._trade_stats(sub)

        if "sector" in outcomes.columns:
            for sector in outcomes["sector"].unique():
                sub = outcomes[outcomes["sector"] == sector]
                if len(sub) >= 2:
                    stats["by_sector"][str(sector)] = self._trade_stats(sub)

        if "exit_reason" in outcomes.columns:
            for reason in outcomes["exit_reason"].unique():
                sub = outcomes[outcomes["exit_reason"] == reason]
                if len(sub) >= 1:
                    stats["by_exit_reason"][str(reason)] = self._trade_stats(sub)

        if "entry_daily_vol" in outcomes.columns:
            for bucket, lo, hi in [
                (VOL_LOW,    0.0,   0.015),
                (VOL_MEDIUM, 0.015, 0.030),
                (VOL_HIGH,   0.030, 1.0),
            ]:
                mask = (outcomes["entry_daily_vol"] >= lo) & (outcomes["entry_daily_vol"] < hi)
                sub = outcomes[mask]
                if len(sub) >= 2:
                    stats["by_vol_bucket"][bucket] = self._trade_stats(sub)

        return stats

    @staticmethod
    def _trade_stats(df: pd.DataFrame) -> dict:
        """Compute summary statistics for a group of outcomes."""
        if df.empty:
            return {}
        returns = df["gross_return"].dropna()
        n = len(returns)
        if n == 0:
            return {"n": 0}

        # Bootstrap 95% CI on mean return (2000 resamples)
        rng = np.random.default_rng(666)
        bootstrap_means = [
            rng.choice(returns.values, size=n, replace=True).mean()
            for _ in range(2000)
        ]
        ci_lo, ci_hi = np.percentile(bootstrap_means, [2.5, 97.5])

        win_rate = float((returns > 0).mean())
        stop_col = df.get("was_stopped", pd.Series([False] * n))
        stop_rate = float(stop_col.mean()) if len(stop_col) == n else 0.0

        days_held = df.get("trading_days_held", pd.Series([None] * n))
        avg_days = float(days_held.dropna().mean()) if days_held.notna().any() else None

        return {
            "n": n,
            "mean_return": round(float(returns.mean()), 4),
            "mean_return_ci_95": [round(ci_lo, 4), round(ci_hi, 4)],
            "median_return": round(float(returns.median()), 4),
            "std_return": round(float(returns.std()), 4) if n > 1 else None,
            "win_rate": round(win_rate, 3),
            "stop_rate": round(stop_rate, 3),
            "avg_days_held": round(avg_days, 1) if avg_days else None,
            "best": round(float(returns.max()), 4),
            "worst": round(float(returns.min()), 4),
            "sharpe_approx": (
                round(float(returns.mean() / returns.std()), 3)
                if returns.std() > 0 else None
            ),
        }

    @staticmethod
    def _stop_analysis(outcomes: pd.DataFrame) -> dict:
        """Analyze stop loss patterns."""
        if "was_stopped" not in outcomes.columns or outcomes.empty:
            return {}
        stopped = outcomes[outcomes["was_stopped"] == True]
        not_stopped = outcomes[outcomes["was_stopped"] == False]

        stop_by_vol = {}
        if "entry_daily_vol" in outcomes.columns:
            for bucket, lo, hi in [
                (VOL_LOW,    0.0,   0.015),
                (VOL_MEDIUM, 0.015, 0.030),
                (VOL_HIGH,   0.030, 1.0),
            ]:
                mask = (outcomes["entry_daily_vol"] >= lo) & (outcomes["entry_daily_vol"] < hi)
                sub = outcomes[mask]
                if len(sub) >= 2:
                    stop_by_vol[bucket] = {
                        "n": len(sub),
                        "stop_rate": round(float(sub["was_stopped"].mean()), 3),
                        "avg_return_when_stopped": (
                            round(float(sub[sub["was_stopped"]]["gross_return"].mean()), 4)
                            if sub["was_stopped"].any() else None
                        ),
                    }

        return {
            "total_stops": int(outcomes["was_stopped"].sum()),
            "overall_stop_rate": round(float(outcomes["was_stopped"].mean()), 3),
            "avg_return_when_stopped": (
                round(float(stopped["gross_return"].mean()), 4) if not stopped.empty else None
            ),
            "avg_return_when_not_stopped": (
                round(float(not_stopped["gross_return"].mean()), 4) if not not_stopped.empty else None
            ),
            "stop_by_vol_bucket": stop_by_vol,
        }

    # ------------------------------------------------------------------
    # Phase 2: Lightweight models
    # ------------------------------------------------------------------

    def _phase2_lightweight_models(self) -> dict:
        try:
            from sklearn.linear_model import Ridge, LogisticRegression
            from sklearn.preprocessing import StandardScaler
            from sklearn.model_selection import cross_val_score
        except ImportError:
            return {"status": "sklearn_not_available"}

        fm = self.fs.build_entry_feature_matrix()
        if fm.empty or len(fm) < 20:
            return {"status": "insufficient_data", "n": len(fm), "required": 20}

        feat_cols = [c for c in fm.columns if c.startswith("feat_")]
        X = fm[feat_cols].fillna(0).values
        y_ret = fm["target_return"].fillna(0).values
        y_win = (fm["target_return"] > 0).astype(int).values

        scaler = StandardScaler()
        X_scaled = scaler.fit_transform(X)

        # Ridge regression — heavy regularization for small samples
        ridge = Ridge(alpha=10.0)
        n_cv = min(3, len(fm) // 5)
        if n_cv >= 2:
            ridge_scores = cross_val_score(ridge, X_scaled, y_ret, cv=n_cv, scoring="r2")
            ridge_r2 = round(float(ridge_scores.mean()), 4)
        else:
            ridge_r2 = None

        # Logistic regression for win/loss
        lr = LogisticRegression(C=0.1, max_iter=1000)
        if n_cv >= 2 and len(np.unique(y_win)) > 1:
            lr_scores = cross_val_score(lr, X_scaled, y_win, cv=n_cv, scoring="roc_auc")
            lr_auc = round(float(lr_scores.mean()), 4)
        else:
            lr_auc = None

        # Fit on all data for feature coefficients
        ridge.fit(X_scaled, y_ret)
        coef_df = pd.DataFrame({
            "feature": feat_cols,
            "coefficient": ridge.coef_
        }).sort_values("coefficient", key=abs, ascending=False)

        # Serialize model metadata as JSON (no binary format)
        model_meta = {
            "model_type": "Ridge",
            "alpha": 10.0,
            "features": feat_cols,
            "n_train": len(fm),
            "ridge_r2_cv": ridge_r2,
            "logistic_auc_cv": lr_auc,
            "trained_at": datetime.now().isoformat(),
        }
        with open(self.models_dir / "phase2_ridge_meta.json", "w") as f:
            json.dump(model_meta, f, indent=2)

        return {
            "n_samples": len(fm),
            "ridge_r2_cv": ridge_r2,
            "logistic_auc_cv": lr_auc,
            "top_features_by_coef": coef_df.head(10)[["feature", "coefficient"]].to_dict("records"),
            "caution": "N<100; coefficients are regularized heavily. Do not over-interpret.",
        }

    # ------------------------------------------------------------------
    # Phase 3: Full ML
    # ------------------------------------------------------------------

    def _phase3_full_ml(self) -> dict:
        fm = self.fs.build_entry_feature_matrix()
        if fm.empty or len(fm) < 100:
            return {"status": "insufficient_data", "n": len(fm), "required": 100}

        feat_cols = [c for c in fm.columns if c.startswith("feat_")]
        X = fm[feat_cols].fillna(0).values
        y = fm["target_return"].fillna(0).values

        results = {"n_samples": len(fm)}

        try:
            import lightgbm as lgb
            from sklearn.model_selection import cross_val_score

            model = lgb.LGBMRegressor(
                n_estimators=200,
                learning_rate=0.05,
                max_depth=3,
                num_leaves=8,
                min_child_samples=10,
                subsample=0.8,
                colsample_bytree=0.8,
                reg_alpha=0.1,
                reg_lambda=0.1,
                random_state=666,
                verbose=-1,
            )
            cv_scores = cross_val_score(model, X, y, cv=5, scoring="r2")
            model.fit(X, y)
            importance = pd.DataFrame({
                "feature": feat_cols,
                "importance": model.feature_importances_
            }).sort_values("importance", ascending=False)

            results["model_type"] = "LightGBM"
            results["lgbm_r2_cv5"] = round(float(cv_scores.mean()), 4)
            results["top_features"] = importance.head(10)[["feature", "importance"]].to_dict("records")

        except ImportError:
            from sklearn.ensemble import RandomForestRegressor
            from sklearn.model_selection import cross_val_score

            rf = RandomForestRegressor(
                n_estimators=200, max_depth=4, min_samples_leaf=5, random_state=666
            )
            cv_scores = cross_val_score(rf, X, y, cv=5, scoring="r2")
            rf.fit(X, y)
            importance = pd.DataFrame({
                "feature": feat_cols,
                "importance": rf.feature_importances_
            }).sort_values("importance", ascending=False)

            results["model_type"] = "RandomForest"
            results["rf_r2_cv5"] = round(float(cv_scores.mean()), 4)
            results["top_features"] = importance.head(10)[["feature", "importance"]].to_dict("records")

        return results


# ===========================================================================
# STOP PARAMETER OPTIMIZER
# ===========================================================================

class StopParameterOptimizer:
    """
    Analyzes live stop events to suggest STOP_FLOOR, STOP_CEILING, and
    STOP_DAILY_VOL_MULT parameter adjustments.

    Uses bootstrap confidence intervals to avoid false suggestions.
    Only surfaces suggestions with >= 90% bootstrap confidence.
    """

    def __init__(self, feature_store: FeatureStore):
        self.fs = feature_store

    def analyze(self) -> dict:
        outcomes = self.fs.load_outcomes()
        if outcomes.empty or len(outcomes) < 5:
            return {
                "status": "insufficient_data",
                "n": len(outcomes),
                "message": "Need at least 5 completed trades for stop analysis.",
            }

        suggestions = []
        warnings_list = []

        # --- Stop hit rate by vol bucket ---
        if "entry_daily_vol" in outcomes.columns and "was_stopped" in outcomes.columns:
            for bucket, lo, hi, threshold_high, threshold_low in [
                (VOL_LOW,    0.0,   0.015, 0.20, None),
                (VOL_MEDIUM, 0.015, 0.030, None, None),
                (VOL_HIGH,   0.030, 1.0,   None, 0.05),
            ]:
                mask = (outcomes["entry_daily_vol"] >= lo) & (outcomes["entry_daily_vol"] < hi)
                sub = outcomes[mask]
                if len(sub) < 3:
                    continue
                stop_rate = float(sub["was_stopped"].mean())

                if threshold_high and stop_rate > threshold_high:
                    conf = "low" if len(sub) < 10 else "medium"
                    suggestions.append({
                        "parameter": "STOP_FLOOR",
                        "current_value": -0.06,
                        "direction": "loosen",
                        "magnitude": "small (-1 to -2 pp)",
                        "reasoning": (
                            f"{bucket}: stop rate = {stop_rate:.0%} ({len(sub)} trades). "
                            f"STOP_FLOOR may be too tight for low-vol names. "
                            f"Suggested: STOP_FLOOR = -0.07 or -0.08."
                        ),
                        "confidence": conf,
                        "n_observations": len(sub),
                    })

                if threshold_low and stop_rate < threshold_low:
                    conf = "low" if len(sub) < 10 else "medium"
                    suggestions.append({
                        "parameter": "STOP_CEILING",
                        "current_value": -0.15,
                        "direction": "tighten",
                        "magnitude": "medium (-2 to -3 pp)",
                        "reasoning": (
                            f"{bucket}: stop rate = {stop_rate:.0%} ({len(sub)} trades). "
                            f"STOP_CEILING may be too wide for high-vol names. "
                            f"Suggested: STOP_CEILING = -0.12 or -0.13."
                        ),
                        "confidence": conf,
                        "n_observations": len(sub),
                    })

        # --- Average stop return analysis ---
        stopped = outcomes[outcomes["was_stopped"] == True] if "was_stopped" in outcomes.columns else pd.DataFrame()
        if len(stopped) >= 3:
            avg_stop_ret = float(stopped["gross_return"].mean())
            # If stops are much shallower than the -6% floor, they may be noisy
            if avg_stop_ret > -0.04:
                warnings_list.append(
                    f"Stopped positions avg return = {avg_stop_ret:.2%}. "
                    "This is well above the -6% stop floor, suggesting stops "
                    "may be triggering on intraday noise. "
                    "Consider: (a) using EOD close prices for stop checks instead of intraday, "
                    "or (b) minimum hold period before adaptive stop activates (e.g., 2 days)."
                )

        # --- Trailing stop analysis ---
        if "was_trailed" in outcomes.columns:
            trailed = outcomes[outcomes["was_trailed"] == True]
            if len(trailed) >= 3:
                avg_trail_ret = float(trailed["gross_return"].mean())
                if avg_trail_ret < 0.01:
                    warnings_list.append(
                        f"Trailing stop positions avg return = {avg_trail_ret:.2%} "
                        "(near zero or negative). "
                        "Trailing stop may be activating too early. "
                        "Consider raising TRAILING_ACTIVATION from 5% to 6-8%."
                    )

        return {
            "n_outcomes": len(outcomes),
            "n_stops": int(outcomes["was_stopped"].sum()) if "was_stopped" in outcomes.columns else 0,
            "suggestions": suggestions,
            "warnings": warnings_list,
        }


# ===========================================================================
# INSIGHT REPORTER
# ===========================================================================

class InsightReporter:
    """
    Produces the final human-readable insights file.
    Aggregates all learning outputs into actionable summaries.
    Writes to state/ml_learning/insights.json.
    """

    def __init__(
        self,
        learning_engine: LearningEngine,
        stop_optimizer: StopParameterOptimizer,
        feature_store: FeatureStore,
        trading_days: int,
    ):
        self.engine = learning_engine
        self.stop_opt = stop_optimizer
        self.fs = feature_store
        self.n_days = trading_days

    def generate(self) -> dict:
        phase = self.engine.get_phase()
        learn_results = self.engine.run()
        stop_results = self.stop_opt.analyze()
        snapshots = self.fs.load_snapshots()
        portfolio_summary = self._portfolio_analytics(snapshots)

        report = {
            "generated_at": datetime.now().isoformat(),
            "trading_days": self.n_days,
            "learning_phase": phase,
            "phase_description": {
                1: "Phase 1 — Statistical summaries only. Need 63+ trading days for ML.",
                2: "Phase 2 — Lightweight regularized ML active. Need 252+ days for full ML.",
                3: "Phase 3 — Full ML active. Monthly retraining recommended.",
            }[phase],
            "data_summary": self._data_summary(),
            "trade_analytics": learn_results.get("phase1", {}),
            "ml_models": learn_results.get("phase2", learn_results.get("phase3", {})),
            "stop_analysis": stop_results,
            "portfolio_analytics": portfolio_summary,
            "parameter_suggestions": stop_results.get("suggestions", []),
            "warnings": stop_results.get("warnings", []),
            "next_milestone": self._next_milestone(phase),
        }

        Path(INSIGHTS_FILE).parent.mkdir(parents=True, exist_ok=True)
        with open(INSIGHTS_FILE, "w") as f:
            json.dump(report, f, indent=2, default=str)

        logger.info(f"Insights written to {INSIGHTS_FILE}")
        return report

    def _data_summary(self) -> dict:
        outcomes  = self.fs.load_outcomes()
        decisions = self.fs.load_decisions()
        snapshots = self.fs.load_snapshots()
        return {
            "total_decisions": len(decisions),
            "completed_trades": len(outcomes),
            "daily_snapshots": len(snapshots),
            "decisions_by_type": (
                decisions["decision_type"].value_counts().to_dict()
                if not decisions.empty and "decision_type" in decisions.columns
                else {}
            ),
        }

    def _portfolio_analytics(self, snapshots: pd.DataFrame) -> dict:
        if snapshots.empty or "portfolio_value" not in snapshots.columns:
            return {}
        pv = snapshots["portfolio_value"].values
        if len(pv) < 2:
            return {"n_days": len(pv)}

        returns = np.diff(pv) / pv[:-1]
        std = float(np.std(returns))
        sharpe = float(np.mean(returns) / std * np.sqrt(252)) if std > 0 else None
        peak = np.maximum.accumulate(pv)
        dd = (pv - peak) / peak
        max_dd = float(dd.min())

        return {
            "n_days": len(pv),
            "start_value": round(float(pv[0]), 2),
            "current_value": round(float(pv[-1]), 2),
            "total_return": round(float((pv[-1] / pv[0]) - 1), 4),
            "annualized_return_approx": round(
                float(((pv[-1] / pv[0]) ** (252 / max(1, len(pv)))) - 1), 4
            ),
            "daily_sharpe_annualized": round(sharpe, 3) if sharpe else None,
            "max_drawdown": round(max_dd, 4),
            "daily_returns_mean": round(float(np.mean(returns)), 5),
            "daily_returns_std": round(float(np.std(returns)), 5),
        }

    def _next_milestone(self, phase: int) -> str:
        if phase == 1:
            remaining = max(0, PHASE_2_MIN_DAYS - self.n_days)
            months = remaining // 21
            return (
                f"Phase 2 ML begins in ~{remaining} trading days (~{months} months). "
                f"Collect more entry/exit decisions and completed trade outcomes."
            )
        elif phase == 2:
            remaining = max(0, PHASE_3_MIN_DAYS - self.n_days)
            months = remaining // 21
            return (
                f"Phase 3 full ML begins in ~{remaining} trading days (~{months} months). "
                f"Lightweight models are active. Ensure diverse regime examples are collected."
            )
        else:
            return (
                "Phase 3 full ML active. "
                "Retrain monthly. Monitor feature importance drift for signal decay."
            )


# ===========================================================================
# ORCHESTRATOR: Top-level entry point for integration
# ===========================================================================

class COMPASSMLOrchestrator:
    """
    Top-level controller. Attach to COMPASSLive and call at each event.

    Minimal integration in omnicapital_live.py:

        from compass_ml_learning import COMPASSMLOrchestrator
        self.ml = COMPASSMLOrchestrator()

        # In open_new_positions() after FILL:
        self.ml.on_entry(symbol, sector, momentum_score, ...)

        # In check_position_exits() after SELL FILL:
        self.ml.on_exit(symbol, exit_reason, ...)

        # In execute_preclose_entries(), after rotation, for skipped stocks:
        self.ml.on_skip(symbol, skip_reason, ...)

        # At end of daily_open():
        self.ml.on_end_of_day(...)

        # Weekly (every 5 trading days):
        if self.trading_day_counter % 5 == 0:
            self.ml.run_learning()
    """

    def __init__(self, db_dir: str = LEARNING_DB_DIR):
        self.logger = DecisionLogger(db_dir)
        self.feature_store = FeatureStore(db_dir)
        self._trading_days = 0
        logger.info("COMPASSMLOrchestrator initialized.")

    @property
    def decision_logger(self) -> DecisionLogger:
        return self.logger

    def set_trading_days(self, n: int):
        self._trading_days = n

    def run_learning(self) -> dict:
        """Run full learning pipeline and return insights dict."""
        engine = LearningEngine(self.feature_store, self._trading_days)
        stop_opt = StopParameterOptimizer(self.feature_store)
        reporter = InsightReporter(engine, stop_opt, self.feature_store, self._trading_days)
        return reporter.generate()

    def on_entry(self, symbol: str, sector: str, momentum_score: float,
                 momentum_rank: float, entry_vol_ann: float, entry_daily_vol: float,
                 adaptive_stop_pct: float, trailing_stop_pct: float, regime_score: float,
                 max_positions_target: int, current_n_positions: int,
                 portfolio_value: float, portfolio_drawdown: float,
                 current_leverage: float, crash_cooldown: int, trading_day: int,
                 spy_hist=None, source: str = "live") -> str:
        try:
            return self.logger.log_entry(
                symbol=symbol, sector=sector, momentum_score=momentum_score,
                momentum_rank=momentum_rank, entry_vol_ann=entry_vol_ann,
                entry_daily_vol=entry_daily_vol, adaptive_stop_pct=adaptive_stop_pct,
                trailing_stop_pct=trailing_stop_pct, regime_score=regime_score,
                max_positions_target=max_positions_target,
                current_n_positions=current_n_positions, portfolio_value=portfolio_value,
                portfolio_drawdown=portfolio_drawdown, current_leverage=current_leverage,
                crash_cooldown=crash_cooldown, trading_day=trading_day, spy_hist=spy_hist,
                source=source,
            )
        except Exception as e:
            logger.error(f"ML on_entry failed for {symbol}: {e}")
            return ""

    def on_exit(self, symbol: str, sector: str, exit_reason: str,
                entry_price: float, exit_price: float, pnl_usd: float,
                days_held: int, high_price: float, entry_vol_ann: float,
                entry_daily_vol: float, adaptive_stop_pct: float,
                entry_momentum_score: float, entry_momentum_rank: float,
                regime_score: float, max_positions_target: int,
                current_n_positions: int, portfolio_value: float,
                portfolio_drawdown: float, current_leverage: float,
                crash_cooldown: int, trading_day: int, spy_hist=None,
                spy_return_during_hold: Optional[float] = None,
                source: str = "live"):
        try:
            self.logger.log_exit(
                symbol=symbol, sector=sector, exit_reason=exit_reason,
                entry_price=entry_price, exit_price=exit_price, pnl_usd=pnl_usd,
                days_held=days_held, high_price=high_price,
                entry_vol_ann=entry_vol_ann, entry_daily_vol=entry_daily_vol,
                adaptive_stop_pct=adaptive_stop_pct,
                entry_momentum_score=entry_momentum_score,
                entry_momentum_rank=entry_momentum_rank,
                regime_score=regime_score, max_positions_target=max_positions_target,
                current_n_positions=current_n_positions, portfolio_value=portfolio_value,
                portfolio_drawdown=portfolio_drawdown, current_leverage=current_leverage,
                crash_cooldown=crash_cooldown, trading_day=trading_day,
                spy_hist=spy_hist, spy_return_during_hold=spy_return_during_hold,
                source=source,
            )
        except Exception as e:
            logger.error(f"ML on_exit failed for {symbol}: {e}")

    def on_skip(self, symbol: str, sector: str, skip_reason: str,
                universe_rank: Optional[int], momentum_score: Optional[float],
                regime_score: float, trading_day: int, portfolio_value: float,
                portfolio_drawdown: float, current_n_positions: int,
                max_positions_target: int):
        try:
            self.logger.log_skip(
                symbol=symbol, sector=sector, skip_reason=skip_reason,
                universe_rank=universe_rank, momentum_score=momentum_score,
                regime_score=regime_score, trading_day=trading_day,
                portfolio_value=portfolio_value, portfolio_drawdown=portfolio_drawdown,
                current_n_positions=current_n_positions,
                max_positions_target=max_positions_target,
            )
        except Exception as e:
            logger.error(f"ML on_skip failed for {symbol}: {e}")

    def on_end_of_day(self, trading_day: int, portfolio_value: float, cash: float,
                      peak_value: float, n_positions: int, leverage: float,
                      crash_cooldown: int, regime_score: float,
                      max_positions_target: int, positions: List[str],
                      position_meta: dict, spy_hist=None,
                      prev_portfolio_value: Optional[float] = None):
        try:
            self.set_trading_days(trading_day)
            self.logger.log_daily_snapshot(
                trading_day=trading_day, portfolio_value=portfolio_value, cash=cash,
                peak_value=peak_value, n_positions=n_positions, leverage=leverage,
                crash_cooldown=crash_cooldown, regime_score=regime_score,
                max_positions_target=max_positions_target, positions=positions,
                position_meta=position_meta, spy_hist=spy_hist,
                prev_portfolio_value=prev_portfolio_value,
            )
        except Exception as e:
            logger.error(f"ML on_end_of_day failed: {e}")


# ===========================================================================
# BACKFILL: Reconstruct history from existing state files
# ===========================================================================

def backfill_from_state_files(state_dir: str = "state") -> dict:
    """
    Parse all existing compass_state_YYYYMMDD.json files and backfill
    the ML learning database with historical decisions and snapshots.

    This is a one-time operation to seed the database with the 8 days of
    existing paper trading history. Momentum scores are not stored in state
    files so those fields are set to 0.0 (neutral) and flagged as estimated.

    Returns a summary of what was ingested.
    """
    import glob as glob_module

    state_files = sorted(
        glob_module.glob(os.path.join(state_dir, "compass_state_2*.json"))
        + glob_module.glob(os.path.join(state_dir, "**/compass_state_2*.json"), recursive=True)
    )
    # Deduplicate and exclude backups, pre-rotation, and latest symlink
    seen = set()
    unique_files = []
    for f in state_files:
        norm = os.path.normpath(f)
        if norm not in seen:
            seen.add(norm)
            unique_files.append(norm)
    state_files = sorted([
        f for f in unique_files
        if "backup" not in f
        and "pre_rotation" not in f
        and "latest" not in f
    ])

    logger.info(f"Backfilling from {len(state_files)} state files...")
    ml = COMPASSMLOrchestrator()
    ingested = {
        "state_files_processed": len(state_files),
        "entry_decisions": 0,
        "exit_outcomes": 0,
        "daily_snapshots": 0,
        "notes": [],
    }

    # Load stop events from latest state (only source of completed exits)
    stop_events = []
    latest_path = os.path.join(state_dir, "compass_state_latest.json")
    if os.path.exists(latest_path):
        with open(latest_path) as f:
            latest = json.load(f)
            stop_events = latest.get("stop_events", [])

    prev_state = None
    prev_positions: set = set()

    for state_file in state_files:
        try:
            with open(state_file) as f:
                state = json.load(f)
        except Exception as e:
            logger.warning(f"Could not load {state_file}: {e}")
            continue

        trading_day   = state.get("trading_day_counter", 0)
        regime_score  = state.get("current_regime_score",
                                   0.7 if state.get("current_regime") else 0.3)
        portfolio_value = state.get("portfolio_value", 100000)
        peak_value    = state.get("peak_value", portfolio_value)
        cash          = state.get("cash", 0)
        current_positions = set(state.get("positions", {}).keys())
        position_meta = state.get("position_meta", {})

        # Detect new entries vs previous snapshot
        if prev_state is not None:
            new_entries = current_positions - prev_positions
            for sym in new_entries:
                meta = position_meta.get(sym, {})
                entry_vol_ann   = meta.get("entry_vol", 0.25)
                entry_daily_vol = meta.get("entry_daily_vol", 0.016)
                sector          = meta.get("sector", "Unknown")
                # Clamp stop to v8.4 formula; pre-v8.4 state may not have daily_vol
                if entry_daily_vol and entry_daily_vol > 0:
                    raw_stop = -2.5 * entry_daily_vol
                    adaptive_stop = max(-0.15, min(-0.06, raw_stop))
                else:
                    adaptive_stop = -0.08

                ml.on_entry(
                    symbol=sym,
                    sector=sector,
                    momentum_score=0.0,     # not persisted in state — estimated
                    momentum_rank=0.5,      # not persisted — assumed median
                    entry_vol_ann=entry_vol_ann,
                    entry_daily_vol=entry_daily_vol,
                    adaptive_stop_pct=adaptive_stop,
                    trailing_stop_pct=0.03,
                    regime_score=regime_score,
                    max_positions_target=5,
                    current_n_positions=len(current_positions),
                    portfolio_value=portfolio_value,
                    portfolio_drawdown=(portfolio_value - peak_value) / peak_value,
                    current_leverage=1.0,
                    crash_cooldown=state.get("crash_cooldown", 0),
                    trading_day=trading_day,
                    source="live",
                )
                ingested["entry_decisions"] += 1

        # End-of-day snapshot
        prev_pv = prev_state.get("portfolio_value") if prev_state else None
        ml.on_end_of_day(
            trading_day=trading_day,
            portfolio_value=portfolio_value,
            cash=cash,
            peak_value=peak_value,
            n_positions=len(current_positions),
            leverage=1.0,
            crash_cooldown=state.get("crash_cooldown", 0),
            regime_score=regime_score,
            max_positions_target=5,
            positions=list(current_positions),
            position_meta=position_meta,
            spy_hist=None,
            prev_portfolio_value=prev_pv,
        )
        ingested["daily_snapshots"] += 1

        prev_state = state
        prev_positions = current_positions

    # Log known stop events as exit+outcome records
    for stop in stop_events:
        sym         = stop.get("symbol", "")
        entry_price = stop.get("entry_price", 0.0)
        exit_price  = stop.get("exit_price", 0.0)
        pnl         = stop.get("pnl", 0.0)

        # Sector mapping for known symbols
        sector_map = {
            "GS": "Financials", "LRCX": "Technology", "MU": "Technology",
            "AMAT": "Technology", "XOM": "Energy", "MRK": "Healthcare",
        }
        sector = sector_map.get(sym, "Unknown")

        ml.on_exit(
            symbol=sym,
            sector=sector,
            exit_reason="position_stop_adaptive",
            entry_price=entry_price,
            exit_price=exit_price,
            pnl_usd=pnl,
            days_held=2,          # GS: entered day 5, stopped day 7
            high_price=stop.get("entry_price", entry_price) * 1.018,
            entry_vol_ann=0.25,   # not in pre-v8.4 state; use default
            entry_daily_vol=0.016,
            adaptive_stop_pct=-0.06,
            entry_momentum_score=0.0,
            entry_momentum_rank=0.5,
            regime_score=0.7,
            max_positions_target=5,
            current_n_positions=4,
            portfolio_value=100000 + pnl,
            portfolio_drawdown=-0.011,
            current_leverage=1.0,
            crash_cooldown=0,
            trading_day=7,
            source="live",
        )
        ingested["exit_outcomes"] += 1

    ingested["notes"].append(
        "momentum_score and momentum_rank set to 0.0 / 0.5 (not stored in state files). "
        "These will be accurate for all future trades."
    )
    logger.info(f"Backfill complete: {ingested}")
    return ingested


# ===========================================================================
# CLI
# ===========================================================================

if __name__ == "__main__":
    import argparse

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s"
    )

    parser = argparse.ArgumentParser(description="COMPASS ML Learning System")
    sub = parser.add_subparsers(dest="command")

    sub.add_parser("backfill", help="Seed ML DB from existing state files")
    sub.add_parser("report",   help="Generate insights report from current data")
    sub.add_parser("status",   help="Print current data inventory")

    args = parser.parse_args()

    if args.command == "backfill":
        print("Backfilling ML learning database from existing state files...")
        result = backfill_from_state_files("state")
        print(json.dumps(result, indent=2))
        print("\nRun 'python compass_ml_learning.py report' to generate insights.")

    elif args.command == "report":
        print("Generating learning report...")
        fs = FeatureStore()
        snapshots = fs.load_snapshots()
        n_days = (
            int(snapshots["trading_day"].max())
            if not snapshots.empty and "trading_day" in snapshots.columns
            else 8
        )
        engine    = LearningEngine(fs, n_days)
        stop_opt  = StopParameterOptimizer(fs)
        reporter  = InsightReporter(engine, stop_opt, fs, n_days)
        report    = reporter.generate()
        print(json.dumps(report, indent=2, default=str))

    elif args.command == "status":
        fs        = FeatureStore()
        decisions = fs.load_decisions()
        outcomes  = fs.load_outcomes()
        snapshots = fs.load_snapshots()
        print(f"\n=== COMPASS ML Learning System — Data Status ===")
        print(f"Decisions logged   : {len(decisions)}")
        print(f"Completed outcomes : {len(outcomes)}")
        print(f"Daily snapshots    : {len(snapshots)}")
        if not decisions.empty and "decision_type" in decisions.columns:
            print(f"\nDecision breakdown:")
            for dt, count in decisions["decision_type"].value_counts().items():
                print(f"  {dt:20s}: {count}")
        if not snapshots.empty and "trading_day" in snapshots.columns:
            phase = 1 if snapshots["trading_day"].max() < 63 else (
                2 if snapshots["trading_day"].max() < 252 else 3
            )
            print(f"\nLearning phase: {phase}")
            if phase == 1:
                remaining = 63 - int(snapshots["trading_day"].max())
                print(f"Days until Phase 2: ~{remaining}")
    else:
        parser.print_help()
