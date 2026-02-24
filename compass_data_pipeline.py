"""
COMPASS v8.2 Data Pipeline Quality Manager
============================================
Inspired by Google Cloud Data Science Guide (Chapter 1: MLOps + Data Preparation).

Manages the parquet data cache with quality scoring, validation,
anomaly detection, and a structured JSON manifest.

Usage:
    python compass_data_pipeline.py
"""

import os
import json
import numpy as np
import pandas as pd
from datetime import datetime, timedelta

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
CACHE_DIR = os.path.join(SCRIPT_DIR, 'data_cache_parquet')
MANIFEST_PATH = os.path.join(CACHE_DIR, 'data_manifest.json')
TRADING_DAYS_PER_YEAR = 252


class COMPASSDataPipeline:
    """Data pipeline manager for COMPASS v8.2 parquet cache."""

    def __init__(self, cache_dir=CACHE_DIR, manifest_path=MANIFEST_PATH):
        self.cache_dir = cache_dir
        self.manifest_path = manifest_path
        self.manifest = {}
        self.quality_report = {}

    def _get_parquet_files(self):
        """List all parquet files in cache directory."""
        if not os.path.isdir(self.cache_dir):
            return []
        return sorted([f for f in os.listdir(self.cache_dir) if f.endswith('.parquet')])

    def validate_ticker(self, filepath):
        """Run data quality checks on a single ticker parquet file.

        Returns dict with quality_score, issues list, and check results.
        """
        issues = []
        checks_passed = 0
        total_checks = 7

        try:
            df = pd.read_parquet(filepath)
        except Exception as e:
            return {
                'quality_score': 0,
                'issues': [f'Cannot read file: {e}'],
                'checks_passed': 0,
                'total_checks': total_checks,
                'row_count': 0,
            }

        row_count = len(df)
        if row_count == 0:
            return {
                'quality_score': 0,
                'issues': ['Empty file'],
                'checks_passed': 0,
                'total_checks': total_checks,
                'row_count': 0,
            }

        # Ensure Close column exists
        if 'Close' not in df.columns:
            return {
                'quality_score': 0,
                'issues': ['Missing Close column'],
                'checks_passed': 0,
                'total_checks': total_checks,
                'row_count': row_count,
            }

        close = df['Close']

        # Check 1: No NaN in Close
        nan_count = int(close.isna().sum())
        if nan_count == 0:
            checks_passed += 1
        else:
            issues.append(f'{nan_count} NaN values in Close')

        # Check 2: No zero or negative prices
        bad_prices = int((close <= 0).sum())
        if bad_prices == 0:
            checks_passed += 1
        else:
            issues.append(f'{bad_prices} zero/negative prices')

        # Check 3: No duplicate dates
        if hasattr(df.index, 'duplicated'):
            dupes = int(df.index.duplicated().sum())
        else:
            dupes = 0
        if dupes == 0:
            checks_passed += 1
        else:
            issues.append(f'{dupes} duplicate dates')

        # Check 4: No gaps > 5 business days
        if hasattr(df.index, 'to_series'):
            dates = pd.to_datetime(df.index)
            date_diffs = dates.to_series().diff().dt.days.dropna()
            large_gaps = int((date_diffs > 7).sum())  # 7 calendar days ~ 5 business days
        else:
            large_gaps = 0
        if large_gaps == 0:
            checks_passed += 1
        else:
            issues.append(f'{large_gaps} gaps > 5 business days')

        # Check 5: Volume is positive (where available)
        if 'Volume' in df.columns:
            zero_vol = int((df['Volume'] <= 0).sum())
            vol_ratio = zero_vol / row_count
            if vol_ratio < 0.05:  # Allow up to 5% zero-volume days
                checks_passed += 1
            else:
                issues.append(f'{zero_vol} zero-volume days ({vol_ratio*100:.1f}%)')
        else:
            checks_passed += 1  # No volume column = pass

        # Check 6: No single-day price changes > 50%
        daily_changes = close.pct_change().abs().dropna()
        spikes = int((daily_changes > 0.50).sum())
        if spikes == 0:
            checks_passed += 1
        else:
            issues.append(f'{spikes} daily price changes > 50%')

        # Check 7: Data freshness (within 5 business days of today)
        try:
            last_date = pd.to_datetime(df.index[-1])
            today = pd.Timestamp.now()
            days_stale = (today - last_date).days
            if days_stale <= 7:  # 7 calendar days ~ 5 business days
                checks_passed += 1
            else:
                issues.append(f'Data is {days_stale} days old')
        except (IndexError, TypeError):
            issues.append('Cannot determine last date')

        # Compute date range info
        try:
            first_date = pd.to_datetime(df.index[0]).strftime('%Y-%m-%d')
            last_date_str = pd.to_datetime(df.index[-1]).strftime('%Y-%m-%d')
            last_date_ts = pd.to_datetime(df.index[-1])
            freshness_days = (pd.Timestamp.now() - last_date_ts).days
        except (IndexError, TypeError):
            first_date = 'unknown'
            last_date_str = 'unknown'
            freshness_days = 999

        # Compute years covered
        try:
            date_range_days = (pd.to_datetime(df.index[-1]) - pd.to_datetime(df.index[0])).days
            years_covered = date_range_days / 365.25
        except (IndexError, TypeError):
            years_covered = 0

        # Quality score computation
        completeness = min(1.0, row_count / (TRADING_DAYS_PER_YEAR * max(years_covered, 0.1)))
        freshness_score = max(0, 1.0 - freshness_days / 10)
        anomaly_score = 1.0 - (spikes + nan_count + bad_prices) / max(row_count, 1)
        gap_score = 1.0 - large_gaps / max(row_count / 252, 1)

        quality_score = (
            completeness * 0.30 +
            freshness_score * 0.25 +
            max(0, anomaly_score) * 0.25 +
            max(0, gap_score) * 0.20
        ) * 100

        return {
            'quality_score': round(min(100, max(0, quality_score)), 1),
            'issues': issues,
            'checks_passed': checks_passed,
            'total_checks': total_checks,
            'row_count': row_count,
            'date_range': [first_date, last_date_str],
            'freshness_days': freshness_days,
            'years_covered': round(years_covered, 1),
            'completeness': round(completeness, 3),
        }

    def build_manifest(self):
        """Build complete manifest scanning all tickers."""
        parquet_files = self._get_parquet_files()
        tickers = {}
        alerts = []

        for filename in parquet_files:
            ticker = filename.replace('.parquet', '')
            filepath = os.path.join(self.cache_dir, filename)

            # File metadata
            file_size_kb = round(os.path.getsize(filepath) / 1024, 1)
            last_modified = datetime.fromtimestamp(os.path.getmtime(filepath)).isoformat()

            # Validation
            validation = self.validate_ticker(filepath)

            ticker_data = {
                'file_size_kb': file_size_kb,
                'last_modified': last_modified,
                **validation,
            }
            tickers[ticker] = ticker_data

            # Generate alerts
            if validation['quality_score'] < 70:
                alerts.append({
                    'ticker': ticker,
                    'level': 'error',
                    'message': f"Low quality score: {validation['quality_score']}",
                })
            elif validation['quality_score'] < 90:
                alerts.append({
                    'ticker': ticker,
                    'level': 'warning',
                    'message': f"Moderate quality score: {validation['quality_score']}",
                })

            if validation.get('freshness_days', 0) > 5:
                alerts.append({
                    'ticker': ticker,
                    'level': 'warning',
                    'message': f"Stale data: {validation['freshness_days']} days old",
                })

        # Compute aggregate stats
        scores = [t['quality_score'] for t in tickers.values()]
        avg_quality = round(np.mean(scores), 1) if scores else 0

        self.manifest = {
            'generated_at': datetime.now().isoformat(),
            'total_tickers': len(tickers),
            'avg_quality_score': avg_quality,
            'tickers': tickers,
            'alerts': alerts,
        }
        return self.manifest

    def save_manifest(self):
        """Save manifest to JSON file."""
        if not self.manifest:
            self.build_manifest()
        with open(self.manifest_path, 'w') as f:
            json.dump(self.manifest, f, indent=2, default=str)

    def get_quality_scorecard(self):
        """Return summary scorecard for dashboard."""
        if not self.manifest:
            self.build_manifest()

        tickers = self.manifest.get('tickers', {})
        scores = [t['quality_score'] for t in tickers.values()]

        excellent = sum(1 for s in scores if s >= 90)
        good = sum(1 for s in scores if 70 <= s < 90)
        poor = sum(1 for s in scores if s < 70)
        stale = [t for t, d in tickers.items() if d.get('freshness_days', 0) > 5]

        # Total data size
        total_size_mb = round(sum(t.get('file_size_kb', 0) for t in tickers.values()) / 1024, 1)
        total_rows = sum(t.get('row_count', 0) for t in tickers.values())

        return {
            'generated_at': self.manifest.get('generated_at', ''),
            'total_tickers': len(tickers),
            'avg_quality': self.manifest.get('avg_quality_score', 0),
            'excellent': excellent,
            'good': good,
            'poor': poor,
            'stale_tickers': stale,
            'stale_count': len(stale),
            'total_size_mb': total_size_mb,
            'total_rows': total_rows,
            'alerts': self.manifest.get('alerts', [])[:20],  # Limit to 20 alerts
        }

    def run_all(self):
        """Scan, validate, build manifest, return scorecard."""
        self.build_manifest()
        self.save_manifest()
        return self.get_quality_scorecard()


def print_report(scorecard):
    """Print formatted data quality report to console."""
    print("=" * 70)
    print("  COMPASS v8.2 -- Data Pipeline Quality Scorecard")
    print("=" * 70)
    print()
    print(f"  {'Total tickers:':<25} {scorecard['total_tickers']}")
    print(f"  {'Avg quality score:':<25} {scorecard['avg_quality']}/100")
    print(f"  {'Excellent (>=90):':<25} {scorecard['excellent']}")
    print(f"  {'Good (70-89):':<25} {scorecard['good']}")
    print(f"  {'Poor (<70):':<25} {scorecard['poor']}")
    print(f"  {'Stale (>5 days):':<25} {scorecard['stale_count']}")
    print(f"  {'Total size:':<25} {scorecard['total_size_mb']} MB")
    print(f"  {'Total rows:':<25} {scorecard['total_rows']:,}")
    print()

    if scorecard['stale_tickers']:
        print(f"  STALE TICKERS: {', '.join(scorecard['stale_tickers'][:20])}")
        print()

    if scorecard['alerts']:
        print(f"  ALERTS ({len(scorecard['alerts'])} total):")
        for alert in scorecard['alerts'][:15]:
            level = alert['level'].upper()
            print(f"    [{level}] {alert['ticker']}: {alert['message']}")
        if len(scorecard['alerts']) > 15:
            print(f"    ... and {len(scorecard['alerts']) - 15} more")
        print()

    print("=" * 70)


if __name__ == '__main__':
    dp = COMPASSDataPipeline()
    scorecard = dp.run_all()
    print_report(scorecard)
