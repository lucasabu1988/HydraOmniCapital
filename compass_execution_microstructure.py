#!/usr/bin/env python3
"""
COMPASS v8.2 — Execution Microstructure Simulator
===================================================
Chassis-only improvement: simulates 5 execution strategies on 5,293 historical
trades using Parkinson volatility + Corwin-Schultz spread estimators from daily OHLCV.

Strategies:
    1. MOC Baseline     — Current: Close + 2bps slippage
    2. TWAP 15-min      — 5 child orders at 3-min intervals
    3. VWAP 15-min      — Volume-weighted children (U-shaped profile)
    4. Passive Limit    — Limit at mid-price, MOC fallback for unfilled
    5. Order Splitting  — Almgren-Chriss sqrt-impact at multiple capital tiers

Academic references:
    - Parkinson (1980): intraday volatility from High/Low
    - Corwin & Schultz (2012): bid-ask spread from 2-day High/Low
    - Almgren & Chriss (2000): optimal execution with market impact

NOTE: Algorithm (omnicapital_v8_compass.py) is LOCKED and NOT modified.
"""

import os
import math
import numpy as np
import pandas as pd
from datetime import datetime

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
TRADES_CSV = os.path.join(SCRIPT_DIR, 'backtests', 'v8_chassis_upgrade_trades.csv')
CACHE_DIR = os.path.join(SCRIPT_DIR, 'data_cache_parquet')
OUTPUT_CSV = os.path.join(SCRIPT_DIR, 'backtests', 'execution_microstructure_analysis.csv')
SEED = 666

# Trading session constants
TRADING_MINUTES = 390       # 9:30-16:00 ET = 390 minutes
CLOSE_WINDOW_MINUTES = 15   # Last 15 minutes for execution
N_TWAP_SLICES = 5           # Number of child orders for TWAP/VWAP
TWAP_INTERVAL_MIN = 3       # Minutes between child orders

# VWAP volume weights (U-shaped profile for last 15 min of session)
# Heavier at open of window (15:35) and close (15:50), lighter mid-period
VWAP_WEIGHTS = np.array([0.30, 0.20, 0.15, 0.15, 0.20])

# Capital tiers for order splitting analysis
CAPITAL_TIERS = [100_000, 250_000, 500_000, 1_000_000, 2_000_000]

# Cost assumptions (from chassis analysis)
BPS_TO_CAGR_RATIO = 0.355   # Each 1bps slippage ≈ 0.355% CAGR (derived: 2bps = 0.71% CAGR)


class COMPASSExecutionMicrostructure:
    """Simulates execution strategies on historical COMPASS trades."""

    def __init__(self):
        self.trades = None
        self.ohlcv_cache = {}   # {symbol: DataFrame}
        self.rng = np.random.default_rng(seed=SEED)
        self.results = {}

    # ------------------------------------------------------------------
    # Data Loading
    # ------------------------------------------------------------------
    def load_data(self):
        """Load trades CSV and per-ticker parquet OHLCV data."""
        self.trades = pd.read_csv(TRADES_CSV, parse_dates=['entry_date', 'exit_date'])

        # Load parquet data for all traded symbols
        symbols = self.trades['symbol'].unique()
        loaded, missing = 0, 0
        for sym in symbols:
            parquet_path = os.path.join(CACHE_DIR, f'{sym}.parquet')
            if os.path.exists(parquet_path):
                df = pd.read_parquet(parquet_path)
                df.index = pd.to_datetime(df.index)
                self.ohlcv_cache[sym] = df
                loaded += 1
            else:
                missing += 1

        print(f"[LOAD] {len(self.trades)} trades, {loaded} tickers loaded, {missing} missing parquet")
        return self

    # ------------------------------------------------------------------
    # Intraday Modeling from Daily OHLCV
    # ------------------------------------------------------------------
    def _parkinson_vol(self, high, low):
        """Parkinson (1980) intraday volatility estimator from High/Low.
        sigma = sqrt(1/(4*ln(2)) * (ln(H/L))^2)
        """
        if high <= 0 or low <= 0 or low >= high:
            return 0.01  # fallback 1%
        log_hl = math.log(high / low)
        return math.sqrt(log_hl ** 2 / (4 * math.log(2)))

    def _corwin_schultz_spread(self, high_t, low_t, high_t1, low_t1):
        """Corwin & Schultz (2012) bid-ask spread estimator from 2-day High/Low.
        Returns spread as a fraction (e.g., 0.001 = 10bps).
        """
        try:
            beta = (math.log(high_t / low_t)) ** 2 + (math.log(high_t1 / low_t1)) ** 2
            h_max = max(high_t, high_t1)
            l_min = min(low_t, low_t1)
            gamma = (math.log(h_max / l_min)) ** 2

            k = 3 - 2 * math.sqrt(2)
            alpha = (math.sqrt(2 * beta) - math.sqrt(beta)) / k - math.sqrt(gamma / k)

            spread = 2 * (math.exp(alpha) - 1) / (1 + math.exp(alpha))
            return max(spread, 0.0001)  # floor at 1bps
        except (ValueError, ZeroDivisionError):
            return 0.001  # fallback 10bps

    def _get_ohlcv(self, symbol, date):
        """Get OHLCV row for a symbol on a specific date (nearest available)."""
        if symbol not in self.ohlcv_cache:
            return None
        df = self.ohlcv_cache[symbol]
        date_ts = pd.Timestamp(date)

        if date_ts in df.index:
            return df.loc[date_ts]

        # Find nearest available date (within 5 business days)
        mask = (df.index >= date_ts - pd.Timedelta(days=7)) & (df.index <= date_ts + pd.Timedelta(days=7))
        nearby = df.loc[mask]
        if len(nearby) > 0:
            idx = (nearby.index - date_ts).abs().argmin()
            return nearby.iloc[idx]
        return None

    def _get_prev_ohlcv(self, symbol, date):
        """Get OHLCV for the previous trading day."""
        if symbol not in self.ohlcv_cache:
            return None
        df = self.ohlcv_cache[symbol]
        date_ts = pd.Timestamp(date)
        prior = df.loc[df.index < date_ts]
        if len(prior) > 0:
            return prior.iloc[-1]
        return None

    def _compute_intraday_metrics(self, symbol, date):
        """Compute Parkinson vol, C-S spread, and 15-min vol for a trade date."""
        row = self._get_ohlcv(symbol, date)
        prev = self._get_prev_ohlcv(symbol, date)

        if row is None:
            return {'parkinson_vol': 0.01, 'cs_spread': 0.001, 'vol_15min': 0.001, 'adv': 1e9}

        h, l = row['High'], row['Low']
        vol_daily = self._parkinson_vol(h, l)
        vol_15min = vol_daily * math.sqrt(CLOSE_WINDOW_MINUTES / TRADING_MINUTES)

        # Corwin-Schultz spread (needs prev day)
        if prev is not None:
            cs_spread = self._corwin_schultz_spread(h, l, prev['High'], prev['Low'])
        else:
            cs_spread = 0.001  # fallback 10bps

        # Average daily dollar volume
        close = row['Close']
        volume = row['Volume']
        adv = close * volume if close > 0 and volume > 0 else 1e9

        return {
            'parkinson_vol': vol_daily,
            'cs_spread': cs_spread,
            'vol_15min': vol_15min,
            'adv': adv,
            'close': close,
            'high': h,
            'low': l,
        }

    # ------------------------------------------------------------------
    # Strategy Simulators
    # ------------------------------------------------------------------
    # All strategies return (fill_price, directional_slippage_bps)
    # Slippage is DIRECTIONAL: positive = cost to trader
    #   Buy:  fill > fair_price → positive slippage (bad)
    #   Sell: fill < fair_price → positive slippage (bad)
    # ------------------------------------------------------------------

    def _simulate_moc(self, price, is_buy, metrics):
        """MOC Baseline: Close + 2bps slippage (current model).
        This is the control: matches compass_net_backtest.py exactly.
        """
        slip_frac = 0.0002  # 2bps
        if is_buy:
            fill = price * (1 + slip_frac)
        else:
            fill = price * (1 - slip_frac)
        return fill, 2.0

    def _simulate_twap(self, price, is_buy, metrics):
        """TWAP 15-min: 5 equal child orders spread over 15 minutes.

        Key insight: splitting a single MOC into 5 orders averaging across
        the last 15 minutes reduces timing risk (variance reduction via
        averaging) and allows smaller orders to access better prices.
        Net effect: reduces the fixed 2bps MOC slippage to ~1bps per child
        (because each child is a smaller fraction of close volume), plus
        the averaging effect reduces variance.
        """
        # Each child order incurs 1bps slippage (vs 2bps for single MOC)
        # because smaller order = less impact on close auction
        child_slip_frac = 0.0001  # 1bps per child

        # Variance reduction from averaging: each child has small random
        # timing offset, but the average converges to fair price.
        # The noise is zero-mean, so it doesn't add systematic slippage.
        vol_15 = metrics['vol_15min']
        noise_per_child = self.rng.normal(0, vol_15 / N_TWAP_SLICES, size=N_TWAP_SLICES)

        child_fills = []
        for i in range(N_TWAP_SLICES):
            child_price = price * (1 + noise_per_child[i])
            if is_buy:
                child_fills.append(child_price * (1 + child_slip_frac))
            else:
                child_fills.append(child_price * (1 - child_slip_frac))

        avg_fill = np.mean(child_fills)

        # Directional slippage: how much worse than fair price
        if is_buy:
            slip_bps = (avg_fill - price) / price * 10000
        else:
            slip_bps = (price - avg_fill) / price * 10000

        return avg_fill, slip_bps

    def _simulate_vwap(self, price, is_buy, metrics):
        """VWAP 15-min: volume-weighted children (U-shaped profile).

        Same as TWAP but weights children by typical end-of-day volume:
        heavier execution at 15:35 and 15:50 (when liquidity peaks),
        lighter in the middle. Slightly better than equal-weighted TWAP
        because it places more volume when order books are deeper.
        """
        child_slip_frac = 0.0001  # 1bps per child
        vol_15 = metrics['vol_15min']
        noise_per_child = self.rng.normal(0, vol_15 / N_TWAP_SLICES, size=N_TWAP_SLICES)

        child_fills = []
        for i in range(N_TWAP_SLICES):
            child_price = price * (1 + noise_per_child[i])
            if is_buy:
                child_fills.append(child_price * (1 + child_slip_frac))
            else:
                child_fills.append(child_price * (1 - child_slip_frac))

        avg_fill = np.average(child_fills, weights=VWAP_WEIGHTS)

        if is_buy:
            slip_bps = (avg_fill - price) / price * 10000
        else:
            slip_bps = (price - avg_fill) / price * 10000

        return avg_fill, slip_bps

    def _simulate_passive(self, price, is_buy, metrics):
        """Passive Limit: place limit at mid-price to capture spread.

        Instead of crossing the spread (paying the ask for buys), place
        a limit order at or near the bid. If filled, you save the full
        bid-ask spread. Unfilled orders fall back to MOC.

        The Corwin-Schultz spread estimator gives us the bid-ask spread
        from daily High/Low. Passive limit captures ~50% of this spread.
        We cap the estimated spread at 20bps for S&P 500 large-caps
        (the C-S estimator can overestimate for volatile days).
        """
        # Cap C-S spread at realistic level for S&P 500 large-caps
        cs_spread = min(metrics['cs_spread'], 0.002)  # cap at 20bps
        spread_capture = cs_spread * 0.5  # capture half the spread

        # Fill probability: 95% for large-caps at $20K order size
        fill_prob = 0.95

        if self.rng.random() < fill_prob:
            # Filled at limit: save spread_capture vs crossing
            # Slippage = MOC_baseline - spread_savings
            # MOC is 2bps. Passive saves spread_capture_bps.
            spread_capture_bps = spread_capture * 10000
            effective_slip_bps = max(0.3, 2.0 - spread_capture_bps)

            if is_buy:
                fill = price * (1 + effective_slip_bps / 10000)
            else:
                fill = price * (1 - effective_slip_bps / 10000)
        else:
            # Unfilled → fallback to MOC with small urgency premium
            effective_slip_bps = 2.5  # 2bps MOC + 0.5bps urgency
            if is_buy:
                fill = price * (1 + effective_slip_bps / 10000)
            else:
                fill = price * (1 - effective_slip_bps / 10000)

        return fill, effective_slip_bps

    def _simulate_split(self, price, is_buy, metrics, capital_tier):
        """Order Splitting: Almgren-Chriss sqrt-impact model at given capital tier.

        Market impact = k * sqrt(Q/V) where Q = order size, V = daily volume.
        At $100K capital, Q ≈ $19K vs V ≈ $2.8B → impact ≈ 0.08bps (negligible).
        At $1M capital, Q ≈ $190K → impact ≈ 0.26bps (still small for large-caps).
        """
        position_value = capital_tier * 0.95 / 5  # 5 positions
        adv = metrics['adv']

        if adv > 0:
            participation_rate = position_value / adv
            impact_bps = 10 * math.sqrt(participation_rate)
        else:
            impact_bps = 0.1

        # Total slippage = base timing cost (1bps) + market impact
        base_slip = 1.0
        total_slip = base_slip + impact_bps

        if is_buy:
            fill = price * (1 + total_slip / 10000)
        else:
            fill = price * (1 - total_slip / 10000)

        return fill, total_slip

    # ------------------------------------------------------------------
    # Main Simulation Engine
    # ------------------------------------------------------------------
    def run_simulation(self):
        """Run all 5 strategies on all trades. Returns per-trade results DataFrame."""
        results = []
        n_total = len(self.trades)

        for idx, trade in self.trades.iterrows():
            sym = trade['symbol']
            entry_date = trade['entry_date']
            exit_date = trade['exit_date']
            entry_price = trade['entry_price']
            exit_price = trade['exit_price']
            original_return = trade['return']
            original_pnl = trade['pnl']

            # Get intraday metrics for entry and exit dates
            entry_metrics = self._compute_intraday_metrics(sym, entry_date)
            exit_metrics = self._compute_intraday_metrics(sym, exit_date)

            # Simulate each strategy
            row = {
                'symbol': sym,
                'entry_date': entry_date,
                'exit_date': exit_date,
                'exit_reason': trade['exit_reason'],
                'entry_price': entry_price,
                'exit_price': exit_price,
                'original_return': original_return,
                'original_pnl': original_pnl,
                'parkinson_vol_entry': entry_metrics['parkinson_vol'],
                'parkinson_vol_exit': exit_metrics['parkinson_vol'],
                'cs_spread_entry': entry_metrics['cs_spread'],
                'cs_spread_exit': exit_metrics['cs_spread'],
                'vol_15min_entry': entry_metrics['vol_15min'],
                'vol_15min_exit': exit_metrics['vol_15min'],
                'adv_entry': entry_metrics['adv'],
            }

            # 1. MOC Baseline
            entry_fill, entry_slip = self._simulate_moc(entry_price, True, entry_metrics)
            exit_fill, exit_slip = self._simulate_moc(exit_price, False, exit_metrics)
            row['moc_entry_slip_bps'] = entry_slip
            row['moc_exit_slip_bps'] = exit_slip
            row['moc_total_slip_bps'] = entry_slip + exit_slip
            row['moc_pnl'] = (exit_fill - entry_fill) / entry_fill

            # 2. TWAP 15-min
            entry_fill_t, entry_slip_t = self._simulate_twap(entry_price, True, entry_metrics)
            exit_fill_t, exit_slip_t = self._simulate_twap(exit_price, False, exit_metrics)
            row['twap_entry_slip_bps'] = entry_slip_t
            row['twap_exit_slip_bps'] = exit_slip_t
            row['twap_total_slip_bps'] = entry_slip_t + exit_slip_t
            row['twap_pnl'] = (exit_fill_t - entry_fill_t) / entry_fill_t

            # 3. VWAP 15-min
            entry_fill_v, entry_slip_v = self._simulate_vwap(entry_price, True, entry_metrics)
            exit_fill_v, exit_slip_v = self._simulate_vwap(exit_price, False, exit_metrics)
            row['vwap_entry_slip_bps'] = entry_slip_v
            row['vwap_exit_slip_bps'] = exit_slip_v
            row['vwap_total_slip_bps'] = entry_slip_v + exit_slip_v
            row['vwap_pnl'] = (exit_fill_v - entry_fill_v) / entry_fill_v

            # 4. Passive Limit
            entry_fill_p, entry_slip_p = self._simulate_passive(entry_price, True, entry_metrics)
            exit_fill_p, exit_slip_p = self._simulate_passive(exit_price, False, exit_metrics)
            row['passive_entry_slip_bps'] = entry_slip_p
            row['passive_exit_slip_bps'] = exit_slip_p
            row['passive_total_slip_bps'] = entry_slip_p + exit_slip_p
            row['passive_pnl'] = (exit_fill_p - entry_fill_p) / entry_fill_p

            # 5. Order Splitting (at each capital tier)
            for tier in CAPITAL_TIERS:
                tier_key = f'{tier // 1000}K'
                entry_fill_s, entry_slip_s = self._simulate_split(
                    entry_price, True, entry_metrics, tier)
                exit_fill_s, exit_slip_s = self._simulate_split(
                    exit_price, False, exit_metrics, tier)
                row[f'split_{tier_key}_entry_slip_bps'] = entry_slip_s
                row[f'split_{tier_key}_exit_slip_bps'] = exit_slip_s
                row[f'split_{tier_key}_total_slip_bps'] = entry_slip_s + exit_slip_s
                row[f'split_{tier_key}_pnl'] = (exit_fill_s - entry_fill_s) / entry_fill_s

            results.append(row)

            if (idx + 1) % 1000 == 0:
                print(f"  [SIM] {idx + 1}/{n_total} trades processed...")

        self.sim_results = pd.DataFrame(results)
        print(f"[SIM] Complete: {len(self.sim_results)} trades simulated across 5 strategies")
        return self.sim_results

    # ------------------------------------------------------------------
    # Aggregation
    # ------------------------------------------------------------------
    def compute_strategy_stats(self):
        """Aggregate per-trade results into strategy-level statistics."""
        df = self.sim_results
        n = len(df)

        strategies = {}

        # MOC Baseline
        moc_avg_slip = df['moc_total_slip_bps'].mean()
        strategies['moc_baseline'] = {
            'name': 'MOC Baseline',
            'description': 'Market-on-Close, 2bps fixed slippage (current model)',
            'avg_slippage_bps': round(moc_avg_slip, 2),
            'median_slippage_bps': round(df['moc_total_slip_bps'].median(), 2),
            'std_slippage_bps': round(df['moc_total_slip_bps'].std(), 2),
            'savings_vs_moc_bps': 0.0,
            'cagr_recovery_pct': 0.0,
            'avg_trade_return': round(df['moc_pnl'].mean() * 100, 4),
        }

        # TWAP
        twap_avg_slip = df['twap_total_slip_bps'].mean()
        twap_savings = moc_avg_slip - twap_avg_slip
        strategies['twap_15min'] = {
            'name': 'TWAP 15-min',
            'description': '5 child orders at 3-min intervals, 1bps each',
            'avg_slippage_bps': round(twap_avg_slip, 2),
            'median_slippage_bps': round(df['twap_total_slip_bps'].median(), 2),
            'std_slippage_bps': round(df['twap_total_slip_bps'].std(), 2),
            'savings_vs_moc_bps': round(twap_savings, 2),
            'cagr_recovery_pct': round(twap_savings * BPS_TO_CAGR_RATIO, 3),
            'avg_trade_return': round(df['twap_pnl'].mean() * 100, 4),
        }

        # VWAP
        vwap_avg_slip = df['vwap_total_slip_bps'].mean()
        vwap_savings = moc_avg_slip - vwap_avg_slip
        strategies['vwap_15min'] = {
            'name': 'VWAP 15-min',
            'description': 'Volume-weighted children (U-shaped profile)',
            'avg_slippage_bps': round(vwap_avg_slip, 2),
            'median_slippage_bps': round(df['vwap_total_slip_bps'].median(), 2),
            'std_slippage_bps': round(df['vwap_total_slip_bps'].std(), 2),
            'savings_vs_moc_bps': round(vwap_savings, 2),
            'cagr_recovery_pct': round(vwap_savings * BPS_TO_CAGR_RATIO, 3),
            'avg_trade_return': round(df['vwap_pnl'].mean() * 100, 4),
        }

        # Passive Limit
        pass_avg_slip = df['passive_total_slip_bps'].mean()
        pass_savings = moc_avg_slip - pass_avg_slip
        strategies['passive_limit'] = {
            'name': 'Passive Limit',
            'description': 'Limit at mid-price, 95% fill rate, MOC fallback',
            'avg_slippage_bps': round(pass_avg_slip, 2),
            'median_slippage_bps': round(df['passive_total_slip_bps'].median(), 2),
            'std_slippage_bps': round(df['passive_total_slip_bps'].std(), 2),
            'savings_vs_moc_bps': round(pass_savings, 2),
            'cagr_recovery_pct': round(pass_savings * BPS_TO_CAGR_RATIO, 3),
            'avg_trade_return': round(df['passive_pnl'].mean() * 100, 4),
        }

        self.strategies = strategies

        # Capital tier analysis (order splitting)
        tiers = {}
        for tier in CAPITAL_TIERS:
            tier_key = f'{tier // 1000}K'
            col = f'split_{tier_key}_total_slip_bps'
            avg_slip = df[col].mean()
            savings = moc_avg_slip - avg_slip

            # Recommended strategy per tier
            if tier <= 100_000:
                rec = 'passive_limit'
            elif tier <= 250_000:
                rec = 'twap_15min'
            elif tier <= 500_000:
                rec = 'vwap_15min'
            else:
                rec = 'vwap_split'

            tiers[tier_key] = {
                'capital': tier,
                'capital_formatted': f'${tier:,.0f}',
                'position_size': round(tier * 0.95 / 5, 0),
                'avg_impact_bps': round(avg_slip - 1.0, 2),  # subtract base slip
                'total_slip_bps': round(avg_slip, 2),
                'savings_vs_moc_bps': round(savings, 2),
                'cagr_recovery_pct': round(savings * BPS_TO_CAGR_RATIO, 3),
                'recommended_strategy': rec,
            }

        self.capital_tiers = tiers

        # Intraday model stats
        self.intraday_model = {
            'avg_parkinson_vol_pct': round(df['parkinson_vol_entry'].mean() * 100, 3),
            'median_parkinson_vol_pct': round(df['parkinson_vol_entry'].median() * 100, 3),
            'avg_cs_spread_bps': round(df['cs_spread_entry'].mean() * 10000, 1),
            'median_cs_spread_bps': round(df['cs_spread_entry'].median() * 10000, 1),
            'avg_15min_vol_bps': round(df['vol_15min_entry'].mean() * 10000, 1),
            'avg_adv_million': round(df['adv_entry'].mean() / 1e6, 1),
        }

        return self

    # ------------------------------------------------------------------
    # Output
    # ------------------------------------------------------------------
    def get_summary(self):
        """Return JSON-serializable summary for dashboard API."""
        return {
            'generated_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            'trade_count': len(self.sim_results),
            'backtest_period': f"{self.trades['entry_date'].min().strftime('%Y-%m-%d')} to {self.trades['exit_date'].max().strftime('%Y-%m-%d')}",
            'strategies': self.strategies,
            'capital_tiers': self.capital_tiers,
            'intraday_model': self.intraday_model,
            'strategy_chart_data': [
                {
                    'strategy': v['name'],
                    'avg_slippage_bps': v['avg_slippage_bps'],
                    'savings_vs_moc_bps': v['savings_vs_moc_bps'],
                    'cagr_recovery_pct': v['cagr_recovery_pct'],
                }
                for k, v in self.strategies.items()
            ],
        }

    def save_csv(self):
        """Save detailed per-trade results to CSV."""
        self.sim_results.to_csv(OUTPUT_CSV, index=False)
        print(f"[SAVE] Per-trade results saved to {OUTPUT_CSV}")

    def run_all(self):
        """Orchestrate full analysis pipeline."""
        self.load_data()
        self.run_simulation()
        self.compute_strategy_stats()
        self.save_csv()
        return self.get_summary()


# ======================================================================
# Standalone Report
# ======================================================================
def print_report(summary):
    """Pretty-print execution microstructure analysis."""
    sep = '=' * 72
    thin = '-' * 72

    print(f"\n{sep}")
    print("  COMPASS v8.2 — EXECUTION MICROSTRUCTURE ANALYSIS")
    print(f"  Generated: {summary['generated_at']}")
    print(f"  Trades analyzed: {summary['trade_count']}")
    print(f"  Period: {summary['backtest_period']}")
    print(sep)

    # Strategy comparison table
    print(f"\n{'STRATEGY COMPARISON':^72}")
    print(thin)
    header = f"{'Strategy':<20} {'Avg Slip':>10} {'Savings':>10} {'CAGR Rec':>10} {'Avg Ret':>10}"
    print(header)
    print(f"{'':.<20} {'(bps)':>10} {'(bps)':>10} {'(%)':>10} {'(%)':>10}")
    print(thin)

    for key, s in summary['strategies'].items():
        savings_str = f"+{s['savings_vs_moc_bps']:.2f}" if s['savings_vs_moc_bps'] > 0 else f"{s['savings_vs_moc_bps']:.2f}"
        cagr_str = f"+{s['cagr_recovery_pct']:.3f}" if s['cagr_recovery_pct'] > 0 else f"{s['cagr_recovery_pct']:.3f}"
        print(f"{s['name']:<20} {s['avg_slippage_bps']:>10.2f} {savings_str:>10} {cagr_str:>10} {s['avg_trade_return']:>10.4f}")
    print(thin)

    # Capital tier recommendations
    print(f"\n{'CAPITAL TIER RECOMMENDATIONS':^72}")
    print(thin)
    header2 = f"{'Tier':<12} {'Pos Size':>12} {'Impact':>10} {'Total Slip':>10} {'Savings':>10} {'Strategy':>16}"
    print(header2)
    print(thin)

    for key, t in summary['capital_tiers'].items():
        savings_str = f"+{t['savings_vs_moc_bps']:.2f}" if t['savings_vs_moc_bps'] > 0 else f"{t['savings_vs_moc_bps']:.2f}"
        print(f"${t['capital']:>10,.0f} ${t['position_size']:>10,.0f} {t['avg_impact_bps']:>10.2f} {t['total_slip_bps']:>10.2f} {savings_str:>10} {t['recommended_strategy']:>16}")
    print(thin)

    # Intraday model stats
    m = summary['intraday_model']
    print(f"\n{'INTRADAY MODEL STATISTICS':^72}")
    print(thin)
    print(f"  Avg Parkinson Volatility:   {m['avg_parkinson_vol_pct']:.3f}%  (daily)")
    print(f"  Median Parkinson Volatility: {m['median_parkinson_vol_pct']:.3f}%  (daily)")
    print(f"  Avg Corwin-Schultz Spread:  {m['avg_cs_spread_bps']:.1f} bps")
    print(f"  Median C-S Spread:          {m['median_cs_spread_bps']:.1f} bps")
    print(f"  Avg 15-min Close Volatility: {m['avg_15min_vol_bps']:.1f} bps")
    print(f"  Avg Daily Dollar Volume:    ${m['avg_adv_million']:.1f}M")
    print(thin)

    # Key findings
    best_strategy = max(summary['strategies'].items(), key=lambda x: x[1]['savings_vs_moc_bps'])
    print(f"\n{'KEY FINDINGS':^72}")
    print(thin)
    print(f"  Best strategy: {best_strategy[1]['name']}")
    print(f"  Slippage savings: +{best_strategy[1]['savings_vs_moc_bps']:.2f} bps vs MOC baseline")
    print(f"  CAGR recovery:   +{best_strategy[1]['cagr_recovery_pct']:.3f}%")
    print(f"  At $100K: Passive Limit recommended (minimal market impact)")
    print(f"  At $500K+: VWAP + Order Splitting recommended (impact grows with sqrt)")
    print(f"  Note: Each 1bps saved = ~{BPS_TO_CAGR_RATIO:.3f}% CAGR recovery")
    print(sep)


if __name__ == '__main__':
    em = COMPASSExecutionMicrostructure()
    summary = em.run_all()
    print_report(summary)
