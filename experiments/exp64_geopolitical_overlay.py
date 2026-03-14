"""
Experiment #64: Geopolitical Overlay -- HYDRA + Crucix Signal Integration
========================================================================
Tests whether macro/geopolitical signals improve HYDRA risk-adjusted returns
by scaling capital deployment during stress periods.

5 signals (rule-based thresholds, NOT fitted to HYDRA data):
  1. FRED VIX (VIXCLS) -- implied volatility spike
  2. FRED Yield Curve (T10Y2Y) -- inversion = recession signal
  3. GSCPI -- NY Fed Supply Chain Pressure Index
  4. WTI Crude Oil (DCOILWTICO) -- price spike = energy/supply stress
  5. GPR -- Caldara-Iacoviello Geopolitical Risk Index

Architecture: post-hoc daily scaling on HYDRA baseline equity curve.
Each signal produces a scalar [0.25, 1.0]. Multiplicative aggregation.
Floor = 0.25 (same as existing overlay system).

Baseline: HYDRA (COMPASS 50% + Rattlesnake 50% + EFA Filtered + Cash Recycling)
  = 14.45% CAGR, 0.91 Sharpe, -27.0% MaxDD (survivorship-corrected, 2000-2026)
"""
import pandas as pd
import numpy as np
import os
import sys
import io

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)

INITIAL_CAPITAL = 100_000
OVERLAY_FLOOR = 0.25

FRED_BASE_URL = 'https://fred.stlouisfed.org/graph/fredgraph.csv'
FRED_CACHE_DIR = os.path.join(BASE_DIR, 'data_cache', 'geopolitical')

# ============================================================================
# DATA DOWNLOADERS
# ============================================================================

def download_fred(series_id, start='1999-01-01', end='2026-12-31'):
    os.makedirs(FRED_CACHE_DIR, exist_ok=True)
    cache = os.path.join(FRED_CACHE_DIR, f'{series_id}.csv')
    if os.path.exists(cache):
        df = pd.read_csv(cache, index_col=0, parse_dates=True)
        s = df.iloc[:, 0].replace('.', np.nan).astype(float).dropna()
        return s.resample('D').ffill()

    import urllib.request
    url = f'{FRED_BASE_URL}?id={series_id}&cosd={start}&coed={end}'
    print(f"  [FRED] Downloading {series_id}...", end=' ')
    try:
        with urllib.request.urlopen(url, timeout=30) as resp:
            raw = resp.read().decode('utf-8')
        # Validate it's actual CSV, not HTML error page
        if raw.strip().startswith('<!DOCTYPE') or raw.strip().startswith('<html'):
            print(f"FAILED: got HTML instead of CSV")
            return None
        with open(cache, 'w') as f:
            f.write(raw)
        df = pd.read_csv(io.StringIO(raw), index_col=0, parse_dates=True)
        s = df.iloc[:, 0].replace('.', np.nan).astype(float).dropna()
        print(f"{len(s)} obs ({s.index[0].date()} to {s.index[-1].date()})")
        return s.resample('D').ffill()
    except Exception as e:
        print(f"FAILED: {e}")
        return None


def download_gscpi():
    """NY Fed Global Supply Chain Pressure Index (monthly, z-score normalized)."""
    os.makedirs(FRED_CACHE_DIR, exist_ok=True)
    cache = os.path.join(FRED_CACHE_DIR, 'GSCPI.csv')
    if os.path.exists(cache):
        df = pd.read_csv(cache, index_col=0, parse_dates=True)
        s = df.iloc[:, 0].dropna()
        return s.resample('D').ffill()

    import urllib.request
    url = 'https://www.newyorkfed.org/medialibrary/research/interactives/gscpi/downloads/gscpi_data.xlsx'
    print("  [GSCPI] Downloading from NY Fed...", end=' ')
    try:
        local_path = os.path.join(FRED_CACHE_DIR, 'gscpi_data.xlsx')
        urllib.request.urlretrieve(url, local_path)
        df = pd.read_excel(local_path, sheet_name='GSCPI Monthly Data')
        # Skip header rows (first 4 rows are metadata)
        df = df.dropna(subset=['Date', 'GSCPI'])
        s = pd.Series(df['GSCPI'].values, index=pd.to_datetime(df['Date']))
        s = s.dropna().sort_index()
        s.to_csv(cache, header=['GSCPI'])
        print(f"{len(s)} obs ({s.index[0].date()} to {s.index[-1].date()})")
        return s.resample('D').ffill()
    except Exception as e:
        print(f"FAILED: {e}")
        return None


def download_gpr():
    """Caldara-Iacoviello Geopolitical Risk Index (monthly).

    Published in American Economic Review 2022.
    Measures: wars, sanctions, terrorism, trade conflicts via newspaper text analysis.
    100 = historical mean (1985-2019 normalization).
    """
    os.makedirs(FRED_CACHE_DIR, exist_ok=True)
    cache = os.path.join(FRED_CACHE_DIR, 'GPR.csv')
    if os.path.exists(cache):
        df = pd.read_csv(cache, index_col=0, parse_dates=True)
        s = df.iloc[:, 0].dropna()
        return s.resample('D').ffill()

    import urllib.request
    url = 'https://www.matteoiacoviello.com/gpr_files/data_gpr_export.xls'
    print("  [GPR] Downloading Caldara-Iacoviello GPR...", end=' ')
    try:
        local_path = os.path.join(FRED_CACHE_DIR, 'gpr_export.xls')
        urllib.request.urlretrieve(url, local_path)
        df = pd.read_excel(local_path)
        # File has 'month' and 'GPR' columns
        s = pd.Series(df['GPR'].values, index=pd.to_datetime(df['month']))
        s = s.dropna().sort_index()
        s.to_csv(cache, header=['GPR'])
        print(f"{len(s)} obs ({s.index[0].date()} to {s.index[-1].date()})")
        return s.resample('D').ffill()
    except Exception as e:
        print(f"FAILED: {e}")
        return None


def download_wti_crude():
    """WTI Crude Oil Price (daily, FRED DCOILWTICO).

    Signal: 20-day rolling z-score of price. High z-score = price spike = stress.
    More robust than weekly inventory data for daily overlay.
    """
    s = download_fred('DCOILWTICO')
    if s is None:
        return None
    # Compute 20-day rolling z-score of price level
    rolling_mean = s.rolling(60, min_periods=20).mean()
    rolling_std = s.rolling(60, min_periods=20).std()
    zscore = (s - rolling_mean) / rolling_std
    return zscore.dropna()


# ============================================================================
# GEOPOLITICAL OVERLAY -- RULE-BASED THRESHOLDS
# ============================================================================

class GeopoliticalOverlay:
    """Composite geopolitical/macro stress overlay.

    Each signal produces a scalar [OVERLAY_FLOOR, 1.0].
    Multiplicative aggregation with floor.

    Thresholds are from external references, NOT fitted to HYDRA data:
    - VIX: 30 = P85 historically (CBOE data, 1990-2025)
    - T10Y2Y: 0 = inversion threshold (textbook definition)
    - GSCPI: 1.5 std = significant pressure (NY Fed methodology)
    - WTI z-score: 2.0 = price spike above 2 std dev of 60d rolling
    - GPR: 150 = elevated risk (Caldara-Iacoviello, 100 = historical mean)
    """

    def __init__(self, vix, t10y2y, gscpi, wti_zscore, gpr):
        self.vix = vix
        self.t10y2y = t10y2y
        self.gscpi = gscpi
        self.wti_zscore = wti_zscore
        self.gpr = gpr

    def _get(self, series, date):
        if series is None or len(series) == 0:
            return None
        date_n = pd.Timestamp(date).normalize()
        prior = series[series.index <= date_n]
        if len(prior) == 0:
            return None
        return float(prior.iloc[-1])

    def compute_vix_scalar(self, date):
        """VIX > 30 = fear. Scale: 30 -> 1.0, 50 -> 0.50, 80+ -> 0.25"""
        val = self._get(self.vix, date)
        if val is None or val <= 30:
            return 1.0
        return max(OVERLAY_FLOOR, 1.0 - (val - 30) / 66.67 * 0.75)

    def compute_yield_curve_scalar(self, date):
        """T10Y2Y < 0 = inverted. Scale: 0 -> 1.0, -0.5 -> 0.80, -1.0+ -> 0.60"""
        val = self._get(self.t10y2y, date)
        if val is None or val >= 0:
            return 1.0
        return max(0.60, 1.0 + val * 0.40)  # -1.0 -> 0.60

    def compute_gscpi_scalar(self, date):
        """GSCPI > 1.5 = significant pressure. Scale: 1.5 -> 1.0, 3.0 -> 0.60, 4.5+ -> 0.25"""
        val = self._get(self.gscpi, date)
        if val is None or val <= 1.5:
            return 1.0
        return max(OVERLAY_FLOOR, 1.0 - (val - 1.5) / 4.0 * 0.75)

    def compute_wti_scalar(self, date):
        """WTI z-score > 2.0 = price spike. Scale: 2.0 -> 1.0, 3.0 -> 0.70, 4.0+ -> 0.40"""
        val = self._get(self.wti_zscore, date)
        if val is None or val <= 2.0:
            return 1.0
        return max(0.40, 1.0 - (val - 2.0) / 3.33 * 0.60)

    def compute_gpr_scalar(self, date):
        """GPR > 150 = elevated geopolitical risk. 100 = historical mean.
        Scale: 150 -> 1.0, 250 -> 0.60, 400+ -> 0.25"""
        val = self._get(self.gpr, date)
        if val is None or val <= 150:
            return 1.0
        return max(OVERLAY_FLOOR, 1.0 - (val - 150) / 333.33 * 0.75)

    def compute_composite(self, date):
        """Multiplicative aggregation with floor."""
        s_vix = self.compute_vix_scalar(date)
        s_yc = self.compute_yield_curve_scalar(date)
        s_gscpi = self.compute_gscpi_scalar(date)
        s_wti = self.compute_wti_scalar(date)
        s_gpr = self.compute_gpr_scalar(date)

        composite = s_vix * s_yc * s_gscpi * s_wti * s_gpr
        composite = max(OVERLAY_FLOOR, min(1.0, composite))

        return {
            'composite': composite,
            'vix': s_vix,
            'yield_curve': s_yc,
            'gscpi': s_gscpi,
            'wti': s_wti,
            'gpr': s_gpr,
        }


# ============================================================================
# SIMULATION
# ============================================================================

def run_with_overlay(baseline_pv, overlay, variant_name):
    """Apply geopolitical overlay to baseline HYDRA equity curve.

    Post-hoc: on each day, scale the daily return by the composite scalar.
    This simulates reducing position sizes during stress periods.
    """
    baseline_returns = baseline_pv.pct_change().fillna(0)
    portfolio = INITIAL_CAPITAL
    values = []
    scalars = []
    diagnostics = []

    for date, ret in baseline_returns.items():
        result = overlay.compute_composite(date)
        scalar = result['composite']

        adjusted_ret = ret * scalar
        portfolio *= (1 + adjusted_ret)
        values.append(portfolio)
        scalars.append(scalar)
        diagnostics.append(result)

    pv = pd.Series(values, index=baseline_returns.index)
    returns = pv.pct_change().dropna()
    years = len(pv) / 252

    scalar_series = pd.Series(scalars, index=baseline_returns.index)

    stress_days = (scalar_series < 0.99).sum()
    severe_days = (scalar_series < 0.50).sum()

    return {
        'name': variant_name,
        'pv': pv,
        'cagr': (pv.iloc[-1] / INITIAL_CAPITAL) ** (1 / years) - 1,
        'maxdd': (pv / pv.cummax() - 1).min(),
        'sharpe': returns.mean() / returns.std() * np.sqrt(252),
        'vol': returns.std() * np.sqrt(252),
        'sortino': returns.mean() / returns[returns < 0].std() * np.sqrt(252),
        'calmar': 0,
        'final': pv.iloc[-1],
        'scalar_mean': scalar_series.mean(),
        'stress_days': stress_days,
        'stress_pct': stress_days / len(pv) * 100,
        'severe_days': severe_days,
        'avg_scalar_when_stressed': scalar_series[scalar_series < 0.99].mean() if stress_days > 0 else 1.0,
        'scalars': scalar_series,
        'diagnostics': diagnostics,
    }


def run_baseline(baseline_pv):
    returns = baseline_pv.pct_change().dropna()
    years = len(baseline_pv) / 252
    cagr = (baseline_pv.iloc[-1] / INITIAL_CAPITAL) ** (1 / years) - 1
    maxdd = (baseline_pv / baseline_pv.cummax() - 1).min()
    sharpe = returns.mean() / returns.std() * np.sqrt(252)
    vol = returns.std() * np.sqrt(252)
    sortino = returns.mean() / returns[returns < 0].std() * np.sqrt(252)

    return {
        'name': 'HYDRA Baseline',
        'pv': baseline_pv,
        'cagr': cagr,
        'maxdd': maxdd,
        'sharpe': sharpe,
        'vol': vol,
        'sortino': sortino,
        'calmar': cagr / abs(maxdd) if maxdd != 0 else 0,
        'final': baseline_pv.iloc[-1],
        'stress_days': 0,
        'stress_pct': 0,
        'severe_days': 0,
    }


# ============================================================================
# INDIVIDUAL SIGNAL EXPERIMENTS
# ============================================================================

def run_single_signal(baseline_pv, signal_name, scalar_fn):
    baseline_returns = baseline_pv.pct_change().fillna(0)
    portfolio = INITIAL_CAPITAL
    values = []

    for date, ret in baseline_returns.items():
        scalar = scalar_fn(date)
        adjusted_ret = ret * scalar
        portfolio *= (1 + adjusted_ret)
        values.append(portfolio)

    pv = pd.Series(values, index=baseline_returns.index)
    returns = pv.pct_change().dropna()
    years = len(pv) / 252

    return {
        'name': signal_name,
        'pv': pv,
        'cagr': (pv.iloc[-1] / INITIAL_CAPITAL) ** (1 / years) - 1,
        'maxdd': (pv / pv.cummax() - 1).min(),
        'sharpe': returns.mean() / returns.std() * np.sqrt(252),
        'final': pv.iloc[-1],
    }


# ============================================================================
# MAIN
# ============================================================================

if __name__ == '__main__':
    print("=" * 80)
    print("EXP64: GEOPOLITICAL OVERLAY -- HYDRA + CRUCIX SIGNAL INTEGRATION")
    print("=" * 80)

    # -- Load baseline HYDRA equity curve --
    print("\n[1/3] Loading baseline data...")
    hydra_path = os.path.join(BASE_DIR, 'backtests', 'exp62_hydra_efa_daily.csv')
    hydra_df = pd.read_csv(hydra_path, parse_dates=['date'], index_col='date')
    baseline_pv = hydra_df['value']
    print(f"  HYDRA baseline: {baseline_pv.index[0].date()} to {baseline_pv.index[-1].date()}, "
          f"{len(baseline_pv)} days ({len(baseline_pv)/252:.1f} years)")
    print(f"  ${INITIAL_CAPITAL:,.0f} -> ${baseline_pv.iloc[-1]:,.0f}")

    # -- Download geopolitical data --
    print("\n[2/3] Downloading geopolitical/macro data...")
    os.makedirs(FRED_CACHE_DIR, exist_ok=True)

    vix = download_fred('VIXCLS')
    t10y2y = download_fred('T10Y2Y')
    gscpi = download_gscpi()
    wti_z = download_wti_crude()
    gpr = download_gpr()

    print("\n  Data coverage:")
    for name, series in [('VIX', vix), ('T10Y2Y', t10y2y), ('GSCPI', gscpi),
                          ('WTI z-score', wti_z), ('GPR', gpr)]:
        if series is not None:
            print(f"    {name:<12}: {series.index[0].date()} to {series.index[-1].date()} ({len(series)} obs)")
        else:
            print(f"    {name:<12}: UNAVAILABLE")

    # -- Run simulations --
    print("\n[3/3] Running simulations...")

    r_base = run_baseline(baseline_pv)

    overlay = GeopoliticalOverlay(vix, t10y2y, gscpi, wti_z, gpr)
    r_full = run_with_overlay(baseline_pv, overlay, 'HYDRA + Geo Overlay (Full)')
    r_full['calmar'] = r_full['cagr'] / abs(r_full['maxdd']) if r_full['maxdd'] != 0 else 0

    # Individual signal tests
    signals_individual = []
    if vix is not None:
        ov = GeopoliticalOverlay(vix, None, None, None, None)
        signals_individual.append(run_single_signal(baseline_pv, 'VIX only', ov.compute_vix_scalar))

    if t10y2y is not None:
        ov = GeopoliticalOverlay(None, t10y2y, None, None, None)
        signals_individual.append(run_single_signal(baseline_pv, 'Yield Curve only', ov.compute_yield_curve_scalar))

    if gscpi is not None:
        ov = GeopoliticalOverlay(None, None, gscpi, None, None)
        signals_individual.append(run_single_signal(baseline_pv, 'GSCPI only', ov.compute_gscpi_scalar))

    if wti_z is not None:
        ov = GeopoliticalOverlay(None, None, None, wti_z, None)
        signals_individual.append(run_single_signal(baseline_pv, 'WTI Crude only', ov.compute_wti_scalar))

    if gpr is not None:
        ov = GeopoliticalOverlay(None, None, None, None, gpr)
        signals_individual.append(run_single_signal(baseline_pv, 'GPR only', ov.compute_gpr_scalar))

    # == Results ==
    print()
    print("=" * 80)
    print("  RESULTS -- COMPOSITE OVERLAY")
    print("=" * 80)

    header = f"  {'Metric':<22} {'HYDRA Baseline':>18} {'+ Geo Overlay':>18} {'Delta':>12}"
    print(header)
    print(f"  {'-'*72}")

    for label, key, fmt in [
        ('CAGR', 'cagr', '.2%'),
        ('Max DD', 'maxdd', '.2%'),
        ('Sharpe', 'sharpe', '.3f'),
        ('Sortino', 'sortino', '.3f'),
        ('Volatility', 'vol', '.2%'),
        ('Calmar', 'calmar', '.3f'),
    ]:
        v_base = r_base[key]
        v_overlay = r_full[key]
        delta = v_overlay - v_base
        print(f"  {label:<22} {format(v_base, fmt):>18} {format(v_overlay, fmt):>18} {format(delta, '+' + fmt):>12}")

    print(f"  {'Final Value':<22} ${r_base['final']:>16,.0f} ${r_full['final']:>16,.0f}")
    print()
    print(f"  Stress days (scalar < 1.0): {r_full['stress_days']} ({r_full['stress_pct']:.1f}%)")
    print(f"  Severe days (scalar < 0.5): {r_full['severe_days']}")
    print(f"  Avg scalar:                 {r_full['scalar_mean']:.3f}")
    print(f"  Avg scalar when stressed:   {r_full['avg_scalar_when_stressed']:.3f}")

    # Individual signal results
    print()
    print("=" * 80)
    print("  INDIVIDUAL SIGNAL ATTRIBUTION")
    print("=" * 80)
    print(f"  {'Signal':<20} {'CAGR':>10} {'MaxDD':>10} {'Sharpe':>10} {'dCAGR':>10} {'dSharpe':>10}")
    print(f"  {'-'*72}")
    print(f"  {'Baseline':<20} {r_base['cagr']:>9.2%} {r_base['maxdd']:>9.2%} {r_base['sharpe']:>10.3f} {'--':>10} {'--':>10}")
    for r in signals_individual:
        dc = r['cagr'] - r_base['cagr']
        ds = r['sharpe'] - r_base['sharpe']
        print(f"  {r['name']:<20} {r['cagr']:>9.2%} {r['maxdd']:>9.2%} {r['sharpe']:>10.3f} {dc:>+9.2%} {ds:>+10.3f}")
    print(f"  {'Full Composite':<20} {r_full['cagr']:>9.2%} {r_full['maxdd']:>9.2%} {r_full['sharpe']:>10.3f} "
          f"{r_full['cagr']-r_base['cagr']:>+9.2%} {r_full['sharpe']-r_base['sharpe']:>+10.3f}")

    # Annual returns comparison
    print()
    print("=" * 80)
    print("  ANNUAL RETURNS")
    print("=" * 80)
    print(f"  {'Year':<8} {'Baseline':>10} {'+ Overlay':>10} {'Delta':>10} {'Avg Scalar':>12}")
    print(f"  {'-'*52}")
    annual_base = r_base['pv'].resample('YE').last().pct_change().dropna()
    annual_overlay = r_full['pv'].resample('YE').last().pct_change().dropna()
    annual_scalar = r_full['scalars'].resample('YE').mean()

    for idx in sorted(set(annual_base.index) & set(annual_overlay.index)):
        y = idx.year
        ab = annual_base.loc[idx]
        ao = annual_overlay.loc[idx]
        sc = annual_scalar.loc[idx] if idx in annual_scalar.index else 1.0
        print(f"  {y:<8} {ab:>+9.1%} {ao:>+9.1%} {ao-ab:>+9.1%} {sc:>11.3f}")

    # Stress period analysis
    print()
    print("=" * 80)
    print("  STRESS PERIOD ANALYSIS")
    print("=" * 80)
    scalar_ts = r_full['scalars']
    stress_mask = scalar_ts < 0.99

    if stress_mask.any():
        stress_blocks = []
        in_block = False
        block_start = None
        for date, stressed in stress_mask.items():
            if stressed and not in_block:
                in_block = True
                block_start = date
            elif not stressed and in_block:
                in_block = False
                stress_blocks.append((block_start, date))
        if in_block:
            stress_blocks.append((block_start, stress_mask.index[-1]))

        stress_blocks.sort(key=lambda x: (x[1] - x[0]).days, reverse=True)
        print(f"  {'Period':<30} {'Days':>6} {'Avg Scalar':>12} {'Base Ret':>10} {'Ovl Ret':>10}")
        print(f"  {'-'*72}")
        for start, end in stress_blocks[:10]:
            days = (end - start).days
            avg_sc = scalar_ts.loc[start:end].mean()
            base_ret = (r_base['pv'].loc[end] / r_base['pv'].loc[start] - 1) if start in r_base['pv'].index else 0
            ovl_ret = (r_full['pv'].loc[end] / r_full['pv'].loc[start] - 1) if start in r_full['pv'].index else 0
            period_str = f"{start.date()} to {end.date()}"
            print(f"  {period_str:<30} {days:>5}d {avg_sc:>11.3f} {base_ret:>+9.1%} {ovl_ret:>+9.1%}")
    else:
        print("  No stress periods detected (all scalars >= 0.99)")

    # == Verdict ==
    print()
    print("=" * 80)
    dc = r_full['cagr'] - r_base['cagr']
    ds = r_full['sharpe'] - r_base['sharpe']
    dd = r_full['maxdd'] - r_base['maxdd']

    if ds > 0.05 and dd > 0:  # Better Sharpe AND better MaxDD (less negative)
        print(f"  VERDICT: GEOPOLITICAL OVERLAY APPROVED")
        print(f"    Sharpe {ds:+.3f} | MaxDD {dd:+.2%} | CAGR {dc:+.2%}")
        print(f"    Risk-adjusted improvement justifies the overlay.")
    elif ds > 0:
        print(f"  VERDICT: OVERLAY MARGINAL -- improves Sharpe ({ds:+.3f}) but CAGR {dc:+.2%}")
        print(f"    Consider: only if MaxDD improvement ({dd:+.2%}) outweighs CAGR drag.")
    elif dd > 0.02:  # MaxDD improved by >2pp
        print(f"  VERDICT: OVERLAY DEFENSIVE -- MaxDD improves ({dd:+.2%}) but costs CAGR ({dc:+.2%})")
        print(f"    May be valuable for live trading psychology (smaller drawdowns).")
    else:
        print(f"  VERDICT: GEOPOLITICAL OVERLAY REJECTED")
        print(f"    Sharpe {ds:+.3f} | MaxDD {dd:+.2%} | CAGR {dc:+.2%}")
        print(f"    Overlay reduces returns without meaningful risk improvement.")

    print("=" * 80)

    # Save results
    out_df = pd.DataFrame({
        'baseline': r_base['pv'],
        'overlay': r_full['pv'],
        'scalar': r_full['scalars'],
    })
    out_path = os.path.join(BASE_DIR, 'backtests', 'exp64_geopolitical_daily.csv')
    out_df.to_csv(out_path)
    print(f"\n  Saved: backtests/exp64_geopolitical_daily.csv")
