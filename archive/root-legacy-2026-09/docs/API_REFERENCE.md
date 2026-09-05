# HYDRA Dashboard API Reference

Base URL: `http://localhost:5000` (local) or Render.com deployment (cloud)

All endpoints return JSON via `Content-Type: application/json` unless noted otherwise.

---

## Core State

### `GET /api/state`

Primary endpoint returning full portfolio state with live prices.

**Response:**

| Field | Type | Description |
|-------|------|-------------|
| `status` | `string` | `"online"` or `"offline"` |
| `positions` | `object` | Map of symbol to position data (`shares`, `avg_cost`) |
| `cash` | `float` | Available cash balance |
| `portfolio_value` | `float` | Total portfolio value (cash + holdings) |
| `regime_score` | `float\|null` | Current market regime score |
| `trading_day_counter` | `int` | Number of trading days since inception |
| `portfolio` | `object` | Computed portfolio metrics (cash, value, invested) |
| `position_details` | `object` | Per-position enriched data (current price, PnL, stop levels) |
| `prices` | `object` | Live prices for all tracked symbols (SPY, ^GSPC, ES=F, etc.) |
| `prev_closes` | `object` | Previous close prices for tracked symbols |
| `universe` | `list[string]` | Current trading universe symbols |
| `universe_year` | `int\|null` | Year of the current universe |
| `config` | `object` | Always `{}` (algorithm parameters are confidential) |
| `chassis` | `object` | Execution chassis status (async fetching, order timeout, stale orders, validator stats) |
| `preclose` | `object` | Pre-close window status (`phase`, `signal_time`, `moc_deadline`, `entries_done`) |
| `implementation_shortfall` | `object` | IS metrics (`available`, `avg_is_bps`, `median_is_bps`, buy/sell breakdowns) |
| `hydra` | `object` | HYDRA sub-strategy status (Rattlesnake positions, Catalyst positions, EFA, capital allocation) |
| `price_data_age_seconds` | `int` | Seconds since last price fetch |
| `server_time` | `string` | ISO 8601 server timestamp |
| `engine` | `object` | Engine status dict (`running`, `started_at`, `cycles`) |

---

### `GET /api/health`

System health check with overall status assessment.

**Response:**

| Field | Type | Description |
|-------|------|-------------|
| `status` | `string` | `"healthy"`, `"degraded"`, or `"critical"` |
| `timestamp` | `string` | ISO 8601 timestamp |
| `engine_running` | `bool` | Whether the live engine thread is active |
| `price_freshness` | `float\|null` | Seconds since last price update |
| `engine` | `object` | Engine details: `running`, `uptime_minutes`, `cycles_completed`, `engine_iterations`, `last_cycle_at`, `ml_errors` |
| `data_feed` | `object` | Data feed health: `last_price_update`, `price_age_seconds`, `consecutive_failures`, `cache_size` |
| `portfolio` | `object` | Portfolio summary: `value`, `num_positions`, `cash`, `drawdown_pct` |
| `state` | `object` | State file info: `file_exists`, `last_modified`, `recovered_from` |

**Status logic:**
- `critical`: engine not running OR price data >300s stale
- `degraded`: no price data OR price data >60s stale OR ML errors present
- `healthy`: all systems nominal

---

### `GET /api/cycle-log`

Returns 5-day rotation cycle performance history.

**Response:** `list[object]` -- Array of cycle objects.

| Field | Type | Description |
|-------|------|-------------|
| `cycle_number` | `int` | Cycle sequence number |
| `status` | `string` | `"active"` or `"completed"` |
| `start_date` | `string\|null` | Cycle start date (YYYY-MM-DD) |
| `end_date` | `string\|null` | Cycle end date (YYYY-MM-DD) |
| `cycle_return_pct` | `float\|null` | Cycle return percentage |
| `hydra_return` | `float` | HYDRA holdings return (%) -- live-enriched for active cycles |
| `spy_return` | `float` | SPY return over same period (%) |
| `alpha` | `float` | HYDRA return minus SPY return (%) |
| `portfolio_start` | `float` | Portfolio value at cycle start |
| `portfolio_end` | `float` | Portfolio value at cycle end |
| `spy_start` | `float` | SPY price at cycle start |
| `spy_end` | `float` | SPY price at cycle end |

---

### `GET /api/preflight`

Pre-market readiness checks for 9:30 ET open.

**Response:**

| Field | Type | Description |
|-------|------|-------------|
| `ready` | `bool` | All checks passed |
| `checks` | `object` | Individual check results (see below) |
| `server_time` | `string` | ISO 8601 timestamp |

**Checks object includes:** `market` (phase, time_et, seconds_to_open), `live_system` (ok, state_exists, state_age_seconds), `kill_switch` (ok, active), `data_feed` (ok, spy_price), `state_dir` (ok), `config` (ok), `regime` (spy_close, sma200, above_sma, regime, vol_20d, est_leverage), `chassis` (ok, async_fetching, data_validation, fill_circuit_breaker).

---

## Trading

### `GET /api/equity`

Returns HYDRA backtest equity curve data with milestones.

**Source:** `backtests/hydra_clean_daily.csv` (fallback: `v8_compass_daily.csv`)

**Response:**

| Field | Type | Description |
|-------|------|-------------|
| `equity` | `list[object]` | Downsampled equity points: `{date: string, value: float}` (every 10th row) |
| `milestones` | `list[object]` | Notable events: capital milestones ($1M-$5M), major drawdowns (>15%), ATH |

Each milestone: `{date, value, label, type}` where `type` is `"milestone"`, `"drawdown"`, or `"ath"`.

---

### `GET /api/annual-returns`

Returns COMPASS vs S&P 500 annual returns for bar chart.

**Response:**

| Field | Type | Description |
|-------|------|-------------|
| `data` | `list[object]` | Per-year returns: `{year: int, hydra: float, spy: float\|null}` |
| `positive_years` | `int` | Count of years with positive HYDRA returns |
| `total_years` | `int` | Total years in dataset |

---

### `GET /api/trade-analytics`

Returns trade segmentation analytics (exit reason, regime, sector breakdowns).

**Cache:** 1 hour

**Response:** Delegated to `COMPASSTradeAnalytics.run_all()`. Contains segmented trade statistics including win rates, profit factors, and performance by exit reason, regime, and sector.

On error: `{error: string}`

---

### `GET /api/live-chart`

Returns daily COMPASS vs S&P 500 indexed performance since live trading start.

**Cache:** 60 seconds

**Response:**

| Field | Type | Description |
|-------|------|-------------|
| `dates` | `list[string]` | Trading dates (YYYY-MM-DD) |
| `compass` | `list[float]` | COMPASS indexed values (base 100) |
| `spy` | `list[float]` | SPY indexed values (base 100) |
| `start_date` | `string` | First date in the series |

---

## Risk

### `GET /api/risk`

Returns portfolio risk metrics computed from live positions and historical data.

**Cache:** 5 minutes

**Response:**

| Field | Type | Description |
|-------|------|-------------|
| `computed_at` | `string` | ISO 8601 computation timestamp |
| `portfolio_value` | `float` | Current portfolio value |
| `cash` | `float` | Cash balance |
| `num_positions` | `int` | Number of open positions |
| `lookback_days` | `int` | Historical lookback window for risk calculations |
| `concentration_risk` | `float` | Herfindahl-based concentration metric |
| `sector_concentration` | `float` | Sector-level concentration metric |
| `correlation_risk` | `float` | Average pairwise correlation of holdings |
| `var_95` | `float` | 95% Value-at-Risk (dollar amount) |
| `var_95_pct` | `float` | 95% VaR as percentage of portfolio |
| `max_position_pct` | `float` | Largest single-position weight |
| `beta` | `float` | Portfolio beta vs SPY |
| `risk_score` | `float` | Composite risk score |
| `risk_label` | `string` | `"LOW"`, `"MODERATE"`, or `"HIGH"` |

---

### `GET /api/montecarlo`

Returns Monte Carlo simulation results (10K paths, confidence bands).

**Cache:** Invalidated when source data files change (cycle_log.json or backtest CSV)

**Response:** Delegated to `COMPASSMonteCarlo.run_all()`. Contains simulation paths, percentile bands, and statistical projections.

On error: `{error: string}`

---

### `GET /api/ultimate-risk-news`

Returns curated risk/crisis news feed from Google News.

**Cache:** 5 minutes

**Response:**

| Field | Type | Description |
|-------|------|-------------|
| `status` | `string` | `"alert"` (messages found) or `"clear"` |
| `count` | `int` | Number of risk news items |
| `updated_at` | `string` | ISO 8601 timestamp of last fetch |
| `messages` | `list[object]` | News items with title, source, time, URL |

---

### `GET /api/overlay-status`

Returns current overlay signals (BSO, M2, FOMC) and diagnostics.

**Response:**

| Field | Type | Description |
|-------|------|-------------|
| `available` | `bool` | Whether overlay system is active |
| `capital_scalar` | `float` | Combined capital scalar (0.0-1.0) |
| `scalar_color` | `string` | `"green"` (>=0.90), `"yellow"` (>=0.60), `"red"` (<0.60) |
| `scalar_label` | `string` | `"Normal"`, `"Cautious"`, or `"Stressed"` |
| `position_floor` | `int\|null` | Fed emergency position floor |
| `per_overlay` | `object` | Individual overlay scalars: `{bso, m2, fomc}` (all float) |
| `fed_emergency_active` | `bool` | Whether Fed emergency mode is active |
| `credit_filter` | `object` | Credit filter data: `{hy_bps, excluded_sectors}` |

---

## Data

### `GET /api/price-debug`

Diagnostic endpoint for testing Yahoo Finance connectivity.

**Query Parameters:**

| Param | Type | Default | Description |
|-------|------|---------|-------------|
| `symbol` | `string` | `AAPL` | Stock symbol to test (1-5 uppercase letters) |

**Response:**

| Field | Type | Description |
|-------|------|-------------|
| `server_time` | `string` | ISO 8601 timestamp |
| `has_requests` | `bool` | Whether HTTP requests are available |
| `consecutive_failures` | `int` | Number of consecutive fetch failures |
| `cache_age_seconds` | `float\|null` | Age of price cache in seconds |
| `cached_symbols` | `list[string]` | Symbols currently in price cache |
| `showcase_mode` | `bool` | Whether showcase/demo mode is active |
| `tests` | `object` | Test results: `v7_status`, `v7_price`, `v8_status`, `v8_price` (or `*_error` on failure) |

---

### `GET /api/data-quality`

Returns data pipeline quality scorecard.

**Cache:** 30 minutes

**Response:** Delegated to `COMPASSDataPipeline.run_all()`. Contains data freshness, completeness, and quality metrics.

On error: `{error: string}`

---

### `GET /api/social-feed`

Returns social feed (news + Reddit + SEC filings + MarketWatch) for current holdings.

**Cache:** 5 minutes

**Response:**

| Field | Type | Description |
|-------|------|-------------|
| `messages` | `list[object]` | Feed items (up to 50), each with `time`, `title`, `source`, `url`, `symbol` |
| `symbols` | `list[string]` | Symbols used for the feed query |

Sources: yfinance news, Reddit, SeekingAlpha, SEC EDGAR filings, Google News, MarketWatch. Fetched in parallel.

---

### `GET /api/news`

Legacy alias for `/api/social-feed`. Returns identical response.

---

## ML

### `GET /api/ml-learning`

Returns ML learning log entries, insights, backtest data, and interpretation.

**Response:**

| Field | Type | Description |
|-------|------|-------------|
| `log_entries` | `list[object]` | All entries (decisions, snapshots, outcomes, backtest daily data) sorted by timestamp |
| `insights` | `object` | ML insights from `state/ml_learning/insights.json` |
| `interpretation` | `string` | Markdown interpretation text (auto-regenerated every 5 days) |
| `kpis` | `object` | Key performance indicators (see below) |

**KPIs object:**

| Field | Type | Description |
|-------|------|-------------|
| `total_decisions` | `int` | Total ML decisions logged |
| `total_entries` | `int` | Entry decisions count |
| `total_exits` | `int` | Exit decisions count |
| `total_outcomes` | `int` | Completed trade outcomes |
| `total_snapshots` | `int` | Daily snapshots count |
| `trading_days` | `int` | Number of trading days tracked |
| `phase` | `int` | Learning phase (1=collecting, 2=learning, 3=mature) |
| `days_to_phase2` | `int` | Days remaining to reach phase 2 |
| `phase2_progress_pct` | `float` | Progress toward phase 2 (0-100%) |
| `backtest` | `object` | Backtest statistics: `start_date`, `end_date`, `trading_days`, `years`, `start_value`, `end_value`, `total_return`, `cagr`, `sharpe`, `max_drawdown` |
| `win_rate` | `float` | Fraction of profitable trades (optional) |
| `avg_return` | `float` | Average gross return per trade (optional) |
| `best_trade` | `float` | Best trade return (optional) |
| `worst_trade` | `float` | Worst trade return (optional) |
| `stop_rate` | `float` | Fraction of trades exited by stop-loss (optional) |
| `avg_alpha` | `float\|null` | Average alpha vs SPY per trade (optional) |
| `total_pnl` | `float` | Total PnL in USD (optional) |

---

### `GET /api/ml-diagnostics`

Returns ML system diagnostics and phase status.

**Response (200):**

| Field | Type | Description |
|-------|------|-------------|
| `phase` | `int` | Learning phase (0=not initialized, 1/2/3) |
| `total_decisions` | `int` | Total decisions in `decisions.jsonl` |
| `total_outcomes` | `int` | Total outcomes in `outcomes.jsonl` |
| `last_decision_date` | `string\|null` | Date of most recent decision (YYYY-MM-DD) |
| `files_ok` | `bool` | Whether both JSONL files exist |
| `error` | `string` | Error message (only when phase=0) |

**Phase thresholds:** phase 1 (<63 decisions), phase 2 (63-251), phase 3 (252+)

---

## Engine Control

### `POST /api/engine/start`

Starts the live trading engine.

**Request body:** None

**Response:**

| Field | Type | Description |
|-------|------|-------------|
| `ok` | `bool` | Whether the operation succeeded |
| `message` | `string` | Status message |
| `status` | `object` | Current engine status dict |

---

### `POST /api/engine/stop`

Stops the live trading engine.

**Request body:** None

**Response:**

| Field | Type | Description |
|-------|------|-------------|
| `ok` | `bool` | Whether the operation succeeded |
| `message` | `string` | Status message |
| `status` | `object` | Current engine status dict |

---

### `GET /api/engine/status`

Returns current engine status with iteration counts.

**Response:**

| Field | Type | Description |
|-------|------|-------------|
| `running` | `bool` | Whether engine is running |
| `started_at` | `string\|null` | ISO 8601 start time |
| `cycles` | `int` | Engine loop cycles |
| `engine_iterations` | `int` | Total engine iterations |
| `cycles_completed` | `int` | Trading cycles completed |

---

## Infrastructure

### `GET /api/execution-stats`

Returns order execution statistics from order history and IBKR audit logs.

**Response:**

| Field | Type | Description |
|-------|------|-------------|
| `total_orders` | `int` | Total orders in history |
| `fill_rate` | `float` | Fraction of orders filled (0.0-1.0) |
| `avg_fill_deviation_pct` | `float` | Average fill price deviation from expected (%) |
| `stale_orders_cancelled` | `int` | Orders cancelled due to timeout |

---

### `GET /api/execution-microstructure`

Returns execution microstructure analysis (strategy comparison, capital tiers).

**Cache:** 1 hour

**Response:** Delegated to `COMPASSExecutionMicrostructure.run_all()`. Contains strategy-level execution quality analysis.

On error: `{error: string}`

---

### `GET /api/logs`

Returns recent log file entries.

**Response:**

| Field | Type | Description |
|-------|------|-------------|
| `logs` | `list[string]` | Last 80 lines from the log file |

---

### `GET /api/agent-scratchpad`

Returns HYDRA agent scratchpad entries for a given day.

**Query Parameters:**

| Param | Type | Default | Description |
|-------|------|---------|-------------|
| `date` | `string` | Today (YYYY-MM-DD) | Date to retrieve scratchpad entries for |

**Response:**

| Field | Type | Description |
|-------|------|-------------|
| `date` | `string` | Requested date |
| `entries` | `list[object]` | JSONL entries for that day |
| `available_dates` | `list[string]` | Up to 30 most recent dates with scratchpad data (descending) |

---

### `GET /api/agent-heartbeat`

Returns HYDRA agent heartbeat status.

**Response:**

| Field | Type | Description |
|-------|------|-------------|
| `alive` | `bool` | Whether heartbeat is recent (<120 seconds) |
| `ts` | `string` | ISO 8601 timestamp of last heartbeat |
| `age_seconds` | `int` | Seconds since last heartbeat |
| `message` | `string` | Error message (only when no heartbeat file) |

---

## Comparison

### `GET /api/fund-comparison`

Returns HYDRA vs real-world momentum funds comparison data.

**Source:** `backtests/fund_comparison_data.json`

**Response:**

| Field | Type | Description |
|-------|------|-------------|
| `funds` | `list[object]` | Fund data with `annual_returns` (year -> return), CAGR, Sharpe, etc. |
| `crisis_periods` | `list[object]` | Crisis period performance comparisons |
| `notes` | `list[string]` | Generation notes (if data not available) |

---

### `GET /api/equity-comparison`

Returns COMPASS vs S&P 500 comparison with signal/net equity curves.

**Source:** `backtests/hydra_clean_daily.csv` + `backtests/spy_benchmark.csv`

**Response:**

| Field | Type | Description |
|-------|------|-------------|
| `data` | `list[object]` | Downsampled points: `{date: string, compass: float, spy: float, net: float}` |
| `compass_cagr` | `float` | Signal CAGR (%) |
| `spy_cagr` | `float` | SPY CAGR (%) |
| `net_cagr` | `float` | Net CAGR after 1% annual execution costs (%) |
| `compass_final` | `float` | Final signal portfolio value |
| `spy_final` | `float` | Final SPY-scaled value |
| `net_final` | `float` | Final net portfolio value |
| `years` | `float` | Total years in comparison |

Note: SPY is scaled to match COMPASS starting value. Net curve deducts 1.0% annual execution cost (MOC slippage + commissions).

---

### `GET /api/backtest/status`

Returns backtest data freshness and scheduler status.

**Response:**

| Field | Type | Description |
|-------|------|-------------|
| `running` | `bool` | Whether a backtest is currently running |
| `last_result` | `string\|null` | Result of last backtest run |
| `last_run_date` | `string\|null` | Date of last backtest run |
| `started_at` | `string\|null` | ISO 8601 start time of current/last run |
| `completed_at` | `string\|null` | ISO 8601 completion time |
| `csv_last_modified` | `string\|null` | ISO 8601 timestamp of backtest CSV last modification |
| `csv_age_hours` | `float\|null` | Hours since backtest CSV was last modified |
| `next_scheduled_run` | `string` | ISO 8601 timestamp of next scheduled backtest (weekdays 16:15 ET) |

---

## Other Endpoints

### `GET /`

Serves the main dashboard HTML page.

### `GET /robots.txt`

Returns robots.txt for search engine crawlers.

### `GET /sitemap.xml`

Returns sitemap XML for search engine indexing.
