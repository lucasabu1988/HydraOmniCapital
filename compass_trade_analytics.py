"""
COMPASS v8.4 Trade Analytics Engine
====================================
Inspired by Google Cloud Data Science Guide (Cases 3+6: Segmentation + Analysis).

Segments and analyzes all backtest trades by exit reason, market regime,
sector, year, day-of-week, and volatility environment to identify which
trade types contribute most to alpha.

Usage:
    python compass_trade_analytics.py
"""

import os
import numpy as np
import pandas as pd
from datetime import datetime

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
TRADES_CSV = os.path.join(SCRIPT_DIR, 'backtests', 'v84_compass_trades.csv')
DAILY_CSV = os.path.join(SCRIPT_DIR, 'backtests', 'v84_compass_daily.csv')

# GICS sector mapping for COMPASS universe
SECTOR_MAP = {
    # Technology
    'AAPL': 'Technology', 'MSFT': 'Technology', 'NVDA': 'Technology', 'GOOGL': 'Technology',
    'META': 'Technology', 'AVGO': 'Technology', 'ADBE': 'Technology', 'CRM': 'Technology',
    'AMD': 'Technology', 'INTC': 'Technology', 'CSCO': 'Technology', 'IBM': 'Technology',
    'TXN': 'Technology', 'QCOM': 'Technology', 'ORCL': 'Technology', 'ACN': 'Technology',
    'NOW': 'Technology', 'INTU': 'Technology', 'AMAT': 'Technology', 'MU': 'Technology',
    'LRCX': 'Technology', 'SNPS': 'Technology', 'CDNS': 'Technology', 'KLAC': 'Technology',
    'MRVL': 'Technology', 'PANW': 'Technology', 'NFLX': 'Technology',
    # Financials
    'BRK-B': 'Financials', 'JPM': 'Financials', 'V': 'Financials', 'MA': 'Financials',
    'BAC': 'Financials', 'WFC': 'Financials', 'GS': 'Financials', 'MS': 'Financials',
    'AXP': 'Financials', 'BLK': 'Financials', 'SCHW': 'Financials', 'C': 'Financials',
    'USB': 'Financials', 'PNC': 'Financials', 'TFC': 'Financials', 'CB': 'Financials',
    'MMC': 'Financials', 'AIG': 'Financials', 'COF': 'Financials',
    # Healthcare
    'UNH': 'Healthcare', 'JNJ': 'Healthcare', 'LLY': 'Healthcare', 'ABBV': 'Healthcare',
    'MRK': 'Healthcare', 'PFE': 'Healthcare', 'TMO': 'Healthcare', 'ABT': 'Healthcare',
    'DHR': 'Healthcare', 'AMGN': 'Healthcare', 'BMY': 'Healthcare', 'MDT': 'Healthcare',
    'ISRG': 'Healthcare', 'SYK': 'Healthcare', 'GILD': 'Healthcare', 'REGN': 'Healthcare',
    'VRTX': 'Healthcare', 'BIIB': 'Healthcare',
    # Consumer Discretionary + Staples
    'AMZN': 'Consumer', 'TSLA': 'Consumer', 'WMT': 'Consumer', 'HD': 'Consumer',
    'PG': 'Consumer', 'COST': 'Consumer', 'KO': 'Consumer', 'PEP': 'Consumer',
    'NKE': 'Consumer', 'MCD': 'Consumer', 'DIS': 'Consumer', 'SBUX': 'Consumer',
    'TGT': 'Consumer', 'LOW': 'Consumer', 'CL': 'Consumer', 'KMB': 'Consumer',
    'GIS': 'Consumer', 'EL': 'Consumer', 'MO': 'Consumer', 'PM': 'Consumer',
    # Energy
    'XOM': 'Energy', 'CVX': 'Energy', 'COP': 'Energy', 'SLB': 'Energy',
    'EOG': 'Energy', 'OXY': 'Energy', 'MPC': 'Energy', 'PSX': 'Energy', 'VLO': 'Energy',
    # Industrials
    'GE': 'Industrials', 'CAT': 'Industrials', 'BA': 'Industrials', 'HON': 'Industrials',
    'UNP': 'Industrials', 'RTX': 'Industrials', 'LMT': 'Industrials', 'DE': 'Industrials',
    'UPS': 'Industrials', 'FDX': 'Industrials', 'MMM': 'Industrials', 'GD': 'Industrials',
    'NOC': 'Industrials', 'EMR': 'Industrials',
    # Utilities
    'NEE': 'Utilities', 'DUK': 'Utilities', 'SO': 'Utilities', 'D': 'Utilities', 'AEP': 'Utilities',
    # Telecom / Communication
    'VZ': 'Telecom', 'T': 'Telecom', 'TMUS': 'Telecom', 'CMCSA': 'Telecom',
}


class COMPASSTradeAnalytics:
    """Trade outcome analytics engine for COMPASS v8.4 backtest trades."""

    def __init__(self, trades_csv=TRADES_CSV, daily_csv=DAILY_CSV):
        self.trades_csv = trades_csv
        self.daily_csv = daily_csv
        self.trades_df = None
        self.daily_df = None
        self.segments = {}

    def load_data(self):
        """Load and parse trade and daily CSVs."""
        self.trades_df = pd.read_csv(self.trades_csv, parse_dates=['entry_date', 'exit_date'])
        self.daily_df = pd.read_csv(self.daily_csv, parse_dates=['date'])
        for column in ('entry_date', 'exit_date'):
            if column in self.trades_df.columns:
                self.trades_df[column] = pd.to_datetime(self.trades_df[column], errors='coerce')
        if 'date' in self.daily_df.columns:
            self.daily_df['date'] = pd.to_datetime(self.daily_df['date'], errors='coerce')
        self.daily_df = self.daily_df.sort_values('date').reset_index(drop=True)

    def enrich_trades(self):
        """Add derived columns for segmentation."""
        df = self.trades_df.copy()

        # Holding days (business days)
        df['holding_days'] = (df['exit_date'] - df['entry_date']).dt.days

        # Time-based
        df['entry_year'] = df['entry_date'].dt.year
        df['entry_month'] = df['entry_date'].dt.month
        df['entry_dow'] = df['entry_date'].dt.dayofweek  # 0=Mon, 4=Fri
        df['entry_dow_name'] = df['entry_date'].dt.day_name()

        # Sector
        df['sector'] = df['symbol'].map(SECTOR_MAP).fillna('Other')

        # Win/Loss
        df['win'] = df['return'] > 0

        if df.empty:
            df['risk_on'] = pd.Series(dtype='object')
            df['leverage'] = pd.Series(dtype='float64')
            df['in_protection'] = pd.Series(dtype='bool')
            df['regime_at_entry'] = pd.Series(dtype='object')
            df['vol_environment'] = pd.Series(dtype='object')
            df['in_protection_at_entry'] = pd.Series(dtype='bool')
        else:
            # Regime at entry: merge with daily data
            if self.daily_df.empty:
                df['risk_on'] = np.nan
                df['leverage'] = np.nan
                df['in_protection'] = False
            else:
                daily_regime = self.daily_df[['date', 'risk_on', 'leverage', 'in_protection']].copy()
                df = pd.merge_asof(
                    df.sort_values('entry_date'),
                    daily_regime.sort_values('date'),
                    left_on='entry_date',
                    right_on='date',
                    direction='backward'
                )
            df['regime_at_entry'] = df['risk_on'].map({True: 'Risk-ON', False: 'Risk-OFF'}).fillna('Unknown')

            # Vol environment: based on leverage (low leverage = high vol targeting = high vol)
            df['vol_environment'] = np.where(df['leverage'] < 0.7, 'High Vol', 'Low Vol')

            # Protection mode at entry
            df['in_protection_at_entry'] = df['in_protection'].fillna(False)

        self.trades_df = df

    def _compute_segment_stats(self, df_segment):
        """Compute stats for a trade segment."""
        if len(df_segment) == 0:
            return None

        total_pnl_all = self.trades_df['pnl'].sum()
        total_pnl = df_segment['pnl'].sum()
        avg_ret = df_segment['return'].mean()
        std_ret = df_segment['return'].std()

        stats = {
            'count': int(len(df_segment)),
            'total_pnl': round(float(total_pnl), 2),
            'avg_pnl': round(float(df_segment['pnl'].mean()), 2),
            'avg_return_pct': round(float(avg_ret * 100), 2),
            'win_rate_pct': round(float(df_segment['win'].mean() * 100), 1),
            'avg_holding_days': round(float(df_segment['holding_days'].mean()), 1),
            'alpha_contribution_pct': round(float(total_pnl / total_pnl_all * 100), 1) if total_pnl_all != 0 else 0.0,
            'best_trade_pct': round(float(df_segment['return'].max() * 100), 2),
            'worst_trade_pct': round(float(df_segment['return'].min() * 100), 2),
        }

        # Simple Sharpe approximation
        if std_ret > 0 and len(df_segment) > 1:
            avg_hold = max(df_segment['holding_days'].mean(), 1)
            annualization = np.sqrt(252 / avg_hold)
            stats['sharpe'] = round(float(avg_ret / std_ret * annualization), 2)
        else:
            stats['sharpe'] = 0.0

        return stats

    def segment_by_exit_reason(self):
        """Segment trades by exit reason."""
        result = {}
        for reason, group in self.trades_df.groupby('exit_reason'):
            stats = self._compute_segment_stats(group)
            if stats:
                result[reason] = stats
        return result

    def segment_by_regime(self):
        """Segment by market regime at entry."""
        result = {}
        for regime, group in self.trades_df.groupby('regime_at_entry'):
            stats = self._compute_segment_stats(group)
            if stats:
                result[regime] = stats
        return result

    def segment_by_sector(self):
        """Segment by GICS sector."""
        result = {}
        for sector, group in self.trades_df.groupby('sector'):
            stats = self._compute_segment_stats(group)
            if stats:
                result[sector] = stats
        return result

    def segment_by_year(self):
        """Annual performance breakdown."""
        result = {}
        for year, group in self.trades_df.groupby('entry_year'):
            stats = self._compute_segment_stats(group)
            if stats:
                result[str(int(year))] = stats
        return result

    def segment_by_dow(self):
        """Segment by day of week at entry."""
        result = {}
        for dow_name, group in self.trades_df.groupby('entry_dow_name'):
            stats = self._compute_segment_stats(group)
            if stats:
                result[dow_name] = stats
        return result

    def segment_by_vol_environment(self):
        """Segment by volatility environment."""
        result = {}
        for vol, group in self.trades_df.groupby('vol_environment'):
            stats = self._compute_segment_stats(group)
            if stats:
                result[vol] = stats
        return result

    def get_overall_stats(self):
        """Compute overall trade statistics."""
        df = self.trades_df
        if df is None or len(df) == 0:
            return {
                'total_trades': 0,
                'total_pnl': 0.0,
                'avg_return_pct': 0.0,
                'win_rate_pct': 0.0,
                'avg_holding_days': 0.0,
                'unique_symbols': 0,
                'date_range': None,
            }

        entry_min = df['entry_date'].min()
        exit_max = df['exit_date'].max()
        date_range = None
        if not pd.isna(entry_min) and not pd.isna(exit_max):
            date_range = f"{entry_min.strftime('%Y-%m-%d')} to {exit_max.strftime('%Y-%m-%d')}"

        return {
            'total_trades': int(len(df)),
            'total_pnl': round(float(df['pnl'].sum()), 2),
            'avg_return_pct': round(float(df['return'].mean() * 100), 2),
            'win_rate_pct': round(float(df['win'].mean() * 100), 1),
            'avg_holding_days': round(float(df['holding_days'].mean()), 1),
            'unique_symbols': int(df['symbol'].nunique()),
            'date_range': date_range,
        }

    def get_summary(self):
        """Return JSON-serializable summary for dashboard API."""
        return {
            'generated_at': datetime.now().isoformat(),
            'overall': self.get_overall_stats(),
            'segments': {
                'exit_reason': self.segment_by_exit_reason(),
                'regime': self.segment_by_regime(),
                'sector': self.segment_by_sector(),
                'year': self.segment_by_year(),
                'dow': self.segment_by_dow(),
                'vol_environment': self.segment_by_vol_environment(),
            }
        }

    def run_all(self):
        """Load data, enrich, run all segments, return summary."""
        self.load_data()
        self.enrich_trades()
        return self.get_summary()


def print_report(summary):
    """Print formatted trade analytics report to console."""
    overall = summary['overall']
    print("=" * 80)
    print("  COMPASS v8.2 -- Trade Analytics Engine")
    print(f"  {overall['total_trades']:,} trades | {overall['unique_symbols']} symbols | {overall['date_range']}")
    print("=" * 80)
    print()
    print(f"  Overall: {overall['win_rate_pct']}% win rate | "
          f"avg {overall['avg_return_pct']}% return | "
          f"avg {overall['avg_holding_days']}d hold | "
          f"${overall['total_pnl']:,.0f} total PnL")
    print()

    for seg_name, seg_data in summary['segments'].items():
        print(f"  SEGMENT: {seg_name.upper().replace('_', ' ')}")
        print(f"  {'Category':<20} {'Count':>6} {'Win%':>7} {'AvgRet%':>9} {'AvgPnL':>10} {'Alpha%':>8} {'Sharpe':>7}")
        print("  " + "-" * 69)

        # Sort by alpha contribution
        sorted_items = sorted(seg_data.items(), key=lambda x: x[1]['alpha_contribution_pct'], reverse=True)
        for cat, stats in sorted_items:
            cat_str = str(cat)[:20]
            print(f"  {cat_str:<20} {stats['count']:>6} {stats['win_rate_pct']:>6.1f}% "
                  f"{stats['avg_return_pct']:>8.2f}% ${stats['avg_pnl']:>9,.0f} "
                  f"{stats['alpha_contribution_pct']:>7.1f}% {stats['sharpe']:>6.2f}")
        print()

    print("=" * 80)


if __name__ == '__main__':
    ta = COMPASSTradeAnalytics()
    summary = ta.run_all()
    print_report(summary)
