# HYDRA ML Learning System Architecture

> Source: `compass_ml_learning.py`
> Module logger: `compass.ml`
> Last updated: 2026-03-16

## 1. Overview

The COMPASS ML Learning System is a progressive machine learning pipeline that learns from live paper trading decisions made by the HYDRA v8.4 algorithm. It operates as a passive observer -- it records every decision the algorithm makes (entries, exits, holds, skips, regime changes), tracks trade outcomes, and progressively builds statistical and ML models as data accumulates over weeks and months.

Key design principles:

- **Zero look-ahead bias** -- features are captured only from data available at decision time
- **Progressive learning** -- the system escalates from descriptive statistics to lightweight ML to full supervised learning as sample size grows
- **Fail-safe integration** -- every ML hook in the live engine is wrapped in `try/except`; the ML system can never crash the trading engine
- **Hypothesis, not fact** -- all model outputs are treated as suggestions, not directives. Parameter suggestions require >90% bootstrap confidence before surfacing
- **Regime-conditional** -- all analysis is segmented by market regime and volatility environment to avoid regime conflation

## 2. DecisionLogger

`DecisionLogger` is the instrumentation layer that captures every decision point in the COMPASS live engine.

### What it records

| Decision Type    | When It Fires                                           | Key Fields Populated                                  |
|------------------|---------------------------------------------------------|-------------------------------------------------------|
| `entry`          | After a BUY fill in `open_new_positions()`              | symbol, sector, momentum score/rank, vol, stop levels |
| `exit`           | After a SELL fill in `check_position_exits()`           | exit_reason, entry/exit price, PnL, days held         |
| `hold`           | Stop checked but not triggered (intraday)               | days_held, current_return, drawdown_from_high         |
| `skip`           | Stock considered but not selected during rotation        | skip_reason, universe_rank                            |
| `regime_change`  | Regime score transitions between buckets                 | old/new score, SPY context                            |

### DecisionRecord JSONL schema

Every decision is serialized as one JSON line in `decisions.jsonl`:

```
{
  "decision_id": "uuid4_hex",
  "decision_type": "entry|exit|hold|skip|regime_change",
  "timestamp": "ISO8601",
  "trading_day": int,
  "date": "YYYY-MM-DD",

  // Subject
  "symbol": "AAPL",
  "sector": "Technology",

  // Algorithm context at decision time
  "regime_score": 0.72,          // continuous [0,1]
  "regime_bucket": "bull",       // bull|mild_bull|mild_bear|bear
  "max_positions_target": 5,
  "current_n_positions": 4,
  "portfolio_value": 102500.0,
  "portfolio_drawdown": -0.02,
  "current_leverage": 1.0,
  "crash_cooldown": 0,

  // SPY context
  "spy_price": 520.0,
  "spy_sma200": 500.0,
  "spy_vs_sma200_pct": 0.04,
  "spy_sma50": 510.0,
  "spy_10d_vol": 0.15,
  "spy_20d_return": 0.03,

  // Stock-level features
  "momentum_score": 1.85,
  "momentum_rank": 0.92,
  "entry_vol_ann": 0.30,
  "entry_daily_vol": 0.019,
  "adaptive_stop_pct": -0.08,
  "trailing_stop_pct": -0.03,

  // Position state (hold/exit)
  "days_held": 5,
  "current_return": 0.03,
  "high_price": 185.0,
  "entry_price": 180.0,
  "drawdown_from_high": -0.01,

  // Exit-specific
  "exit_reason": "hold_expired|position_stop|trailing_stop|universe_rotation|regime_reduce",

  // Skip-specific
  "skip_reason": "not_top_n|sector_limit|quality_filter|no_cash",
  "skip_universe_rank": 8,

  "version": "8.4",
  "source": "live|backfill"
}
```

### OutcomeRecord JSONL schema

Written to `outcomes.jsonl` when a position closes. Links back to the entry via `entry_decision_id`:

```
{
  "outcome_id": "uuid4_hex",
  "entry_decision_id": "uuid4_hex",
  "symbol": "AAPL",
  "sector": "Technology",
  "entry_date": "2026-03-06",
  "exit_date": "2026-03-14",
  "trading_days_held": 7,
  "gross_return": 0.035,
  "pnl_usd": 350.0,
  "exit_reason": "hold_expired",

  // Denormalized entry context (for easy ML access)
  "entry_regime_score": 0.72,
  "entry_regime_bucket": "bull",
  "entry_momentum_score": 1.85,
  "entry_momentum_rank": 0.92,
  "entry_vol_ann": 0.30,
  "entry_daily_vol": 0.019,
  "entry_portfolio_drawdown": -0.02,
  "entry_spy_vs_sma200": 0.04,
  "entry_adaptive_stop": -0.08,

  // Outcome classification (labels for supervised learning)
  "outcome_label": "strong_win|weak_win|flat|weak_loss|stop_loss",
  "was_stopped": false,
  "was_trailed": false,
  "held_to_expiry": true,
  "beat_spy": true,
  "spy_return_during_hold": 0.01,
  "alpha_vs_spy": 0.025,
  "version": "8.4"
}
```

### Outcome classification rules

| Label         | Condition                                                   |
|---------------|-------------------------------------------------------------|
| `stop_loss`   | exit_reason is `position_stop_adaptive` or `position_stop`  |
| `strong_win`  | gross_return > +4%                                          |
| `weak_win`    | 0% < gross_return <= +4%                                    |
| `flat`        | -1% <= gross_return <= 0%                                   |
| `weak_loss`   | gross_return < -1% (and not stop_loss)                      |

### DailySnapshot JSONL schema

Written once per trading day to `daily_snapshots.jsonl`:

```
{
  "date": "YYYY-MM-DD",
  "trading_day": int,
  "portfolio_value": 102500.0,
  "cash": 20000.0,
  "peak_value": 103000.0,
  "drawdown": -0.005,
  "n_positions": 4,
  "leverage": 1.0,
  "crash_cooldown": 0,
  "regime_score": 0.72,
  "regime_bucket": "bull",
  "max_positions_target": 5,
  "spy_price": 520.0,
  "spy_sma200": 500.0,
  "spy_vs_sma200_pct": 0.04,
  "spy_10d_vol": 0.15,
  "spy_20d_return": 0.03,
  "positions": ["AAPL", "MSFT", "NVDA", "META"],
  "sectors_held": ["Technology"],
  "avg_entry_vol": 0.018,
  "avg_days_held": 4.5,
  "daily_pnl_pct": 0.005,
  "spy_daily_return": 0.003,
  "version": "8.4"
}
```

### Open entries tracking

`DecisionLogger` maintains a persistent index (`open_entries.json`) mapping `symbol -> entry context dict`. This allows linking exit outcomes back to their original entry decision, preserving entry-time context (regime score, portfolio drawdown, SPY position) even if those values have changed by exit time.

### Regime bucket thresholds

| Bucket       | Regime Score Range |
|--------------|--------------------|
| `bull`       | >= 0.65            |
| `mild_bull`  | 0.50 -- 0.65       |
| `mild_bear`  | 0.35 -- 0.50       |
| `bear`       | < 0.35             |

### Volatility bucket thresholds

| Bucket     | Daily Vol Range |
|------------|-----------------|
| `low_vol`  | < 1.5%          |
| `med_vol`  | 1.5% -- 3.0%    |
| `high_vol` | > 3.0%          |

## 3. FeatureStore

`FeatureStore` handles loading raw JSONL data and building ML-ready feature matrices. All features use only data available at decision time (no look-ahead bias).

### Data loading

Three loaders read from JSONL files, parsing line-by-line with `json.loads` and skipping malformed lines:

- `load_decisions(decision_type=None)` -- loads from `decisions.jsonl`, optionally filtered by type
- `load_outcomes()` -- loads from `outcomes.jsonl`
- `load_snapshots()` -- loads from `daily_snapshots.jsonl`, parses date column to datetime

### Entry feature matrix (`build_entry_feature_matrix`)

Joins outcomes with entry decisions on `entry_decision_id` -> `decision_id`. Each row is one completed trade. Feature categories:

| Category | Features | Description |
|----------|----------|-------------|
| A. Momentum signal | `feat_momentum_score`, `feat_momentum_rank`, `feat_momentum_score_sq` | Signal quality and non-linearity |
| B. Volatility regime | `feat_daily_vol`, `feat_ann_vol`, `feat_vol_low`, `feat_vol_high`, `feat_adaptive_stop` | Entry volatility + bucket dummies |
| C. Market regime | `feat_regime_score`, `feat_spy_vs_sma200`, `feat_regime_bull`, `feat_regime_mild_bull`, `feat_regime_mild_bear`, `feat_spy_10d_vol` | SPY trend + regime dummies |
| D. Portfolio state | `feat_portfolio_dd`, `feat_dd_severe`, `feat_leverage` | Drawdown and leverage at entry |
| E. Sector encoding | `feat_sector_technology`, `feat_sector_healthcare`, ... (8 sectors) | One-hot sector dummies |

Target columns: `target_return` (regression), `target_label` (5-class classification), `target_beat_spy` (binary).

### Stop feature matrix (`build_stop_feature_matrix`)

Built directly from outcomes (no join needed). Focused on stop-out prediction:

- Features: daily vol, adaptive stop, regime score, SPY vs SMA200, portfolio drawdown, momentum score/rank, days held, sector
- Target: `target_was_stopped` (binary), `target_return`

## 4. LearningEngine

The learning engine implements a three-phase progression based on how many trading days of data have been collected.

### Phase determination

| Phase | Trading Days | What Happens |
|-------|-------------|--------------|
| Phase 1 | 0 -- 62 | Statistical summaries only. No model training. |
| Phase 2 | 63 -- 251 (~3-12 months) | Lightweight regularized ML (Ridge, Logistic Regression) |
| Phase 3 | 252+ (~12+ months) | Full supervised learning (LightGBM or RandomForest) |

Phases are cumulative: Phase 2 runs Phase 1 stats + Phase 2 models. Phase 3 runs all three.

### Phase 1: Statistical summaries

Computed from completed trades (outcomes):

- **Overall stats**: mean return (with bootstrap 95% CI, 2000 resamples, seed 666), median return, std, win rate, stop rate, avg days held, best/worst, approximate Sharpe
- **Breakdowns**: by regime bucket, by sector, by exit reason, by vol bucket
- **Stop analysis**: total stops, overall stop rate, avg return when stopped vs. not stopped, stop rate by vol bucket

Minimum 2 trades per group to compute group-level stats.

### Phase 2: Lightweight models

Requires `scikit-learn`. Minimum 20 completed trades.

- **Ridge regression** (alpha=10.0, heavy regularization) for return prediction
- **Logistic regression** (C=0.1) for win/loss classification
- Cross-validation via `TimeSeriesSplit` to prevent temporal data leakage
- Features standardized with `StandardScaler`
- Outputs: R-squared CV score, AUC CV score, top 10 features by coefficient magnitude
- Model metadata saved as JSON (no binary pickle) to `models/phase2_ridge_meta.json`
- Explicit caution: "N<100; coefficients are regularized heavily. Do not over-interpret."

### Phase 3: Full ML

Requires 100+ completed trades.

- **LightGBM** (preferred): 200 estimators, learning rate 0.05, max depth 3, 8 leaves, subsample 0.8, random state 666
- **RandomForest** (fallback if LightGBM not installed): 200 estimators, max depth 4, min samples leaf 5
- 5-fold `TimeSeriesSplit` cross-validation
- Feature importance ranking for signal decay monitoring

## 5. StopParameterOptimizer

Analyzes completed trade outcomes to suggest adjustments to the adaptive stop parameters (`STOP_FLOOR`, `STOP_CEILING`, `STOP_DAILY_VOL_MULT`).

### Analysis logic

Requires at least 5 completed trades. Three analyses:

1. **Stop hit rate by vol bucket**:
   - Low-vol names: if stop rate > 20%, suggests loosening `STOP_FLOOR` from -6% to -7% or -8%
   - High-vol names: if stop rate < 5%, suggests tightening `STOP_CEILING` from -15% to -12% or -13%
   - Confidence tagged as "low" (<10 observations) or "medium" (10+)

2. **Average stop return analysis**:
   - If average return of stopped positions is > -4% (well above the -6% floor), warns that stops may be triggering on intraday noise
   - Suggests EOD close prices for stop checks or minimum hold period (2 days) before stop activates

3. **Trailing stop analysis**:
   - If trailing-stopped positions have avg return < +1%, warns trailing stop may activate too early
   - Suggests raising `TRAILING_ACTIVATION` from 5% to 6-8%

### Confidence threshold

All suggestions are annotated with confidence level. Only suggestions with sufficient statistical backing are surfaced. The system errs on the side of silence over false suggestions.

## 6. InsightReporter

The final aggregation layer that produces `state/ml_learning/insights.json`.

### Report structure

```
{
  "generated_at": "ISO8601",
  "trading_days": int,
  "learning_phase": 1|2|3,
  "phase_description": "human-readable phase explanation",
  "data_summary": {
    "total_decisions": int,
    "completed_trades": int,
    "daily_snapshots": int,
    "decisions_by_type": { "entry": N, "exit": N, "hold": N, "skip": N, ... }
  },
  "trade_analytics": { /* Phase 1 stats */ },
  "ml_models": { /* Phase 2 or 3 model results */ },
  "stop_analysis": { /* StopParameterOptimizer output */ },
  "portfolio_analytics": {
    "n_days": int,
    "start_value": float,
    "current_value": float,
    "total_return": float,
    "annualized_return_approx": float,
    "daily_sharpe_annualized": float,
    "max_drawdown": float,
    "daily_returns_mean": float,
    "daily_returns_std": float
  },
  "parameter_suggestions": [ /* high-confidence suggestions only */ ],
  "warnings": [ /* analytical warnings */ ],
  "next_milestone": "Phase N milestone description"
}
```

### Portfolio analytics

Computed from daily snapshots time series:
- Total and annualized return
- Daily Sharpe ratio (annualized with sqrt(252))
- Maximum drawdown from peak
- Daily returns mean and std

### Next milestone messages

- Phase 1: "Phase 2 ML begins in ~N trading days (~M months)"
- Phase 2: "Phase 3 full ML begins in ~N trading days (~M months)"
- Phase 3: "Retrain monthly. Monitor feature importance drift for signal decay."

## 7. Data Flow Diagram

```
                    COMPASS Live Engine (omnicapital_live.py)
                    ========================================
                              |
        +-----------+---------+---------+-----------+
        |           |         |         |           |
     on_entry   on_exit   on_hold   on_skip   on_end_of_day
        |           |         |         |           |
        v           v         v         v           v
  +-----------------------------------------------------------+
  |              COMPASSMLOrchestrator                         |
  |  (try/except wrapper -- never crashes the engine)         |
  +-----------------------------------------------------------+
        |           |         |         |           |
        v           v         v         v           v
  +-----------------------------------------------------------+
  |                    DecisionLogger                          |
  |  - Appends to decisions.jsonl (all decision types)        |
  |  - Appends to outcomes.jsonl (on exit only)               |
  |  - Appends to daily_snapshots.jsonl (end of day)          |
  |  - Maintains open_entries.json (entry->exit linking)      |
  +-----------------------------------------------------------+
        |                                           |
        v                                           v
  decisions.jsonl                          outcomes.jsonl
  daily_snapshots.jsonl                    open_entries.json
        |                                           |
        +------------------+------------------------+
                           |
                           v
                    +--------------+
                    | FeatureStore |
                    +--------------+
                    | load_decisions()
                    | load_outcomes()
                    | load_snapshots()
                    | build_entry_feature_matrix()
                    | build_stop_feature_matrix()
                    +--------------+
                           |
              +------------+------------+
              |                         |
              v                         v
     +----------------+    +------------------------+
     | LearningEngine |    | StopParameterOptimizer |
     +----------------+    +------------------------+
     | Phase 1: stats |    | Stop rate by vol bucket|
     | Phase 2: Ridge |    | Avg stop return check  |
     | Phase 3: LGBM  |    | Trailing stop check    |
     +----------------+    +------------------------+
              |                         |
              +------------+------------+
                           |
                           v
                  +-----------------+
                  | InsightReporter |
                  +-----------------+
                           |
                           v
              state/ml_learning/insights.json
```

### Trigger frequency

- **on_entry / on_exit / on_skip / on_hold**: every trading cycle (intraday)
- **on_end_of_day**: once per trading day at market close
- **run_learning()**: every 5 trading days (`trading_day_counter % 5 == 0`)

## 8. File Locations

All ML data lives under `state/ml_learning/`:

```
state/ml_learning/
  decisions.jsonl          # All decision records (entry, exit, hold, skip, regime_change)
  outcomes.jsonl           # Completed trade outcomes (one per closed position)
  daily_snapshots.jsonl    # End-of-day portfolio snapshots
  open_entries.json        # Active position -> entry decision_id mapping
  insights.json            # Latest generated insights report
  models/                  # Model metadata (JSON, no binary)
    phase2_ridge_meta.json # Ridge regression metadata (Phase 2)
```

### File format notes

- `.jsonl` files use JSON Lines format (one JSON object per line, append-only)
- All writes use a thread lock (`_ml_write_lock`) for concurrency safety
- JSON writes use atomic rename (`os.replace`) via temp file to prevent corruption
- All values are sanitized before writing: `datetime` -> ISO string, `numpy` types -> Python natives, non-finite floats -> `None`, circular references -> detected and raised

## 9. Fail-Safe Design

The ML system is designed to never interfere with live trading operations.

### COMPASSMLOrchestrator wrapper

Every public method on the orchestrator (`on_entry`, `on_exit`, `on_skip`, `on_hold`, `on_end_of_day`) wraps the underlying `DecisionLogger` call in a `try/except`:

```python
def on_entry(self, ...):
    try:
        return self.logger.log_entry(...)
    except Exception as e:
        logger.error(f"ML on_entry failed for {symbol}: {e}")
        return ""
```

If any ML operation fails -- file I/O, JSON serialization, feature computation, model training -- the error is logged and execution continues normally.

### Additional safety measures

- **JSONL append**: `_append_jsonl` has its own `try/except`; a write failure for one record does not lose previous data
- **Atomic writes**: JSON files use write-to-temp + `os.replace` to prevent half-written files
- **Thread lock**: `_ml_write_lock` prevents concurrent write corruption
- **Graceful degradation**: if `scikit-learn` or `lightgbm` is not installed, the system falls back to statistics-only or RandomForest
- **No algorithm modification**: the ML system is purely observational; it suggests parameter changes but never applies them automatically
- **Optional import pattern**: the live engine imports ML with an `_ml_available` flag; if the import fails, ML hooks are simply skipped

### Integration in omnicapital_live.py

```python
from compass_ml_learning import COMPASSMLOrchestrator
self.ml = COMPASSMLOrchestrator()

# In open_new_positions() after FILL:
self.ml.on_entry(symbol, sector, momentum_score, ...)

# In check_position_exits() after SELL FILL:
self.ml.on_exit(symbol, exit_reason, ...)

# In execute_preclose_entries(), for skipped stocks:
self.ml.on_skip(symbol, skip_reason, ...)

# At end of daily_open():
self.ml.on_end_of_day(...)

# Weekly (every 5 trading days):
if self.trading_day_counter % 5 == 0:
    self.ml.run_learning()
```

### Backfill capability

The `backfill_from_state_files()` function can reconstruct ML history from existing `compass_state_YYYYMMDD.json` files. It detects new entries by diffing positions between consecutive state snapshots, and processes known stop events from the latest state file. Backfilled records are tagged with `source: "backfill"` and use estimated values for fields not stored in state files (momentum scores default to 0.0/0.5).

### CLI

```bash
python compass_ml_learning.py backfill   # Seed ML DB from existing state files
python compass_ml_learning.py report     # Generate insights report
python compass_ml_learning.py status     # Print data inventory
```
