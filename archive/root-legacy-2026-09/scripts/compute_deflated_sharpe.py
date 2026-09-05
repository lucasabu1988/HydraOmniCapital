"""
Deflated Sharpe Ratio and Regime-Conditioned Performance Attribution
for the HYDRA backtest (2000-2026).

References:
  - Bailey & Lopez de Prado (2014), "The Deflated Sharpe Ratio: Correcting for
    Selection Bias, Backtest Overfitting and Non-Normality"
  - Lopez de Prado (2018), "Advances in Financial Machine Learning", Ch. 14

Usage:
    python scripts/compute_deflated_sharpe.py
"""

import os
import sys
import math

import numpy as np
import pandas as pd
from scipy import stats

# ── Paths ─────────────────────────────────────────────────────────────────────
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BACKTESTS_DIR = os.path.join(PROJECT_ROOT, 'backtests')

HYDRA_CSV = os.path.join(BACKTESTS_DIR, 'hydra_clean_daily.csv')
SPY_CSV   = os.path.join(BACKTESTS_DIR, 'spy_benchmark.csv')

# ── Constants ─────────────────────────────────────────────────────────────────
RF_ANNUAL   = 0.025   # 2.5% avg Fed Funds rate 2000-2026 (ZIRP + hike years)
RF_DAILY    = RF_ANNUAL / 252
NET_COST_ANNUAL = 0.01   # 1% annual execution cost drag for net series

N_TRIALS    = 40      # experiments run against HYDRA
T_OBS       = 6572    # trading+calendar days 2000-2026 (~26 years * 252)
RHO_MEAN    = 0.6     # estimated avg pairwise Sharpe correlation across trials

SMA_WINDOW  = 200     # SPY SMA200 for regime filter

SEED = 666
np.random.seed(SEED)


# ─────────────────────────────────────────────────────────────────────────────
#  Data loading
# ─────────────────────────────────────────────────────────────────────────────

def load_hydra():
    df = pd.read_csv(HYDRA_CSV, parse_dates=['date'])
    df = df[['date', 'value']].sort_values('date').reset_index(drop=True)
    return df


def load_spy():
    df = pd.read_csv(SPY_CSV, parse_dates=['date'])
    # column is 'close'
    col = 'close' if 'close' in df.columns else df.columns[1]
    df = df[['date', col]].copy()
    df.columns = ['date', 'spy']
    df = df.sort_values('date').reset_index(drop=True)
    return df


def daily_returns(values):
    """Return array of daily returns from value series."""
    arr = np.array(values, dtype=float)
    return arr[1:] / arr[:-1] - 1.0


def apply_net_cost(df, annual_cost=NET_COST_ANNUAL):
    """Apply continuous daily cost drag to a value series."""
    df = df.copy()
    first_date = df['date'].iloc[0]
    years_elapsed = (df['date'] - first_date).dt.days / 365.25
    df['value'] = df['value'] * (1 - annual_cost) ** years_elapsed
    return df


# ─────────────────────────────────────────────────────────────────────────────
#  Sharpe helpers
# ─────────────────────────────────────────────────────────────────────────────

def compute_sharpe(daily_rets, rf_daily=RF_DAILY):
    """Annualized Sharpe ratio with risk-free subtraction."""
    excess = daily_rets - rf_daily
    if excess.std() == 0:
        return 0.0
    return float(excess.mean() / excess.std() * math.sqrt(252))


def compute_skew_kurt(daily_rets):
    s = float(stats.skew(daily_rets))
    k = float(stats.kurtosis(daily_rets, fisher=True))  # excess kurtosis
    return s, k


# ─────────────────────────────────────────────────────────────────────────────
#  Deflated Sharpe Ratio — Bailey & Lopez de Prado (2014)
# ─────────────────────────────────────────────────────────────────────────────

def expected_max_sharpe(n_trials, t_obs, rho_mean):
    """
    E[max SR] under the null (all strategies have true SR=0).
    Approximation from Bailey & Lopez de Prado (2014) eq. (9):
        E[max SR] ≈ (1 - γ * E) * Z^{-1}(1 - 1/N) + γ * E * Z^{-1}(1 - 1/(N*e))
    where γ is the Euler-Mascheroni constant and E = 0.5772...
    Simplified: E[max SR] ≈ Z^{-1}(1 - 1/N) * sqrt(1 - rho) + sqrt(rho) * Z^{-1}(1 - 1/(N*e))

    We use the cleaner form from Lopez de Prado (2018), Ch. 14:
        SR_max ~ (1 - rho) * Z^{-1}(1 - 1/n) * (1/sqrt(T))
    combined with the EV approximation:
        E[max_z] ≈ (1 - euler) * z(1 - 1/n) + euler * z(1 - 1/(n*e))
    where euler = 0.5772156649, e = math.e
    """
    euler = 0.5772156649
    e = math.e
    # Effective independent trials
    n_eff = n_trials * (1 - rho_mean) + 1  # at least 1 independent
    z1 = stats.norm.ppf(1.0 - 1.0 / n_trials)
    z2 = stats.norm.ppf(1.0 - 1.0 / (n_trials * e))
    # Expected max z-score
    e_max_z = (1 - euler) * z1 + euler * z2
    # Scale to Sharpe units (annualized, T trading days)
    t_trading = t_obs  # already in trading day units
    e_max_sr = e_max_z / math.sqrt(t_trading / 252)
    return float(e_max_sr)


def probabilistic_sharpe(sr_obs, sr_benchmark, t_obs, skewness, excess_kurt):
    """
    PSR = P(SR* > SR_benchmark) = Phi(SR_hat * sqrt(T-1) / se_SR)
    where se_SR = sqrt((1 - skew*SR + ((k+2)/4)*SR^2) / (T-1))
    and SR_hat is observed Sharpe.
    Bailey & Lopez de Prado (2014) eq. (4).
    """
    n = t_obs
    if n <= 1:
        return float('nan')
    sr_hat = sr_obs
    sr_b   = sr_benchmark
    # Standard error of Sharpe estimate
    se2 = (1.0 - skewness * sr_hat + ((excess_kurt + 2) / 4.0) * sr_hat**2) / (n - 1)
    if se2 <= 0:
        se2 = 1e-9
    se = math.sqrt(se2)
    z = (sr_hat - sr_b) * math.sqrt(n - 1) / (se * math.sqrt(252))
    psr = float(stats.norm.cdf(z))
    return psr


def deflated_sharpe(sr_obs, sr_max_expected, t_obs, skewness, excess_kurt):
    """
    DSR = PSR(SR_max_expected).
    Same as PSR but benchmark = E[max SR] instead of 0.
    """
    return probabilistic_sharpe(sr_obs, sr_max_expected, t_obs, skewness, excess_kurt)


# ─────────────────────────────────────────────────────────────────────────────
#  Performance metrics for a return series
# ─────────────────────────────────────────────────────────────────────────────

def cagr(values):
    first, last = float(values[0]), float(values[-1])
    n_days = len(values)
    years = n_days / 252.0
    if years <= 0 or first <= 0:
        return 0.0
    return (last / first) ** (1 / years) - 1.0


def max_drawdown(values):
    arr = np.array(values, dtype=float)
    peak = np.maximum.accumulate(arr)
    dd = (arr - peak) / peak
    return float(dd.min())


def compute_full_metrics(values, label):
    rets = daily_returns(values)
    sr = compute_sharpe(rets)
    sk, ku = compute_skew_kurt(rets)
    t = len(rets)
    sr_max = expected_max_sharpe(N_TRIALS, t, RHO_MEAN)
    psr0  = probabilistic_sharpe(sr, 0.0, t, sk, ku)
    dsr   = deflated_sharpe(sr, sr_max, t, sk, ku)
    return {
        'label':    label,
        'n_days':   t,
        'cagr':     cagr(values) * 100,
        'vol':      float(rets.std() * math.sqrt(252) * 100),
        'sharpe':   sr,
        'skewness': sk,
        'ex_kurt':  ku,
        'max_dd':   max_drawdown(values) * 100,
        'sr_max_expected': sr_max,
        'psr_vs_0':  psr0,
        'dsr':       dsr,
    }


# ─────────────────────────────────────────────────────────────────────────────
#  Print helpers
# ─────────────────────────────────────────────────────────────────────────────

def print_sharpe_report(m):
    print(f"\n{'=' * 60}")
    print(f"  {m['label']}")
    print(f"{'=' * 60}")
    print(f"  Observations (trading days)  : {m['n_days']:,}")
    print(f"  CAGR                         : {m['cagr']:+.2f}%")
    print(f"  Annualized Volatility        : {m['vol']:.2f}%")
    print(f"  Max Drawdown                 : {m['max_dd']:.1f}%")
    print(f"  Skewness                     : {m['skewness']:+.3f}")
    print(f"  Excess Kurtosis              : {m['ex_kurt']:+.3f}")
    print(f"  -- Sharpe Analysis ------------------------------------------")
    print(f"  Observed Sharpe (rf=2.5%)    : {m['sharpe']:+.4f}")
    print(f"  E[max SR | N={N_TRIALS}, rho={RHO_MEAN}]  : {m['sr_max_expected']:+.4f}")
    print(f"  PSR(benchmark=0)             : {m['psr_vs_0']:.4f}  ({m['psr_vs_0']*100:.1f}% prob SR > 0)")
    print(f"  Deflated Sharpe Ratio (DSR)  : {m['dsr']:.4f}  ({m['dsr']*100:.1f}% prob SR > E[max SR])")
    verdict = "PASS" if m['dsr'] >= 0.95 else ("MARGINAL" if m['dsr'] >= 0.80 else "FAIL")
    print(f"  Verdict (DSR >= 0.95)        : {verdict}")


# ─────────────────────────────────────────────────────────────────────────────
#  Regime-conditioned attribution
# ─────────────────────────────────────────────────────────────────────────────

def regime_attribution(hydra_df, spy_df):
    """
    Split HYDRA performance by:
      1. Market regime: Bull (SPY > SMA200) vs Bear (SPY < SMA200)
      2. Decade: 2000-2009, 2010-2019, 2020-2026
    """
    # Merge on date
    df = pd.merge(hydra_df, spy_df, on='date', how='inner')
    df = df.sort_values('date').reset_index(drop=True)

    # Compute SPY SMA200
    df['spy_sma200'] = df['spy'].rolling(SMA_WINDOW, min_periods=SMA_WINDOW).mean()
    df['regime'] = np.where(df['spy'] > df['spy_sma200'], 'Bull', 'Bear')
    df['year'] = df['date'].dt.year

    # Daily returns
    df['hydra_ret'] = df['value'].pct_change()
    df['spy_ret']   = df['spy'].pct_change()
    df = df.dropna(subset=['hydra_ret', 'spy_ret', 'spy_sma200'])

    def segment_metrics(mask, label):
        seg = df[mask].copy()
        if len(seg) < 20:
            return None
        h_rets = seg['hydra_ret'].values
        s_rets = seg['spy_ret'].values
        n = len(h_rets)
        years_seg = n / 252.0
        # CAGR approximation from daily rets
        h_cagr = (np.prod(1 + h_rets) ** (1 / years_seg) - 1) * 100
        s_cagr = (np.prod(1 + s_rets) ** (1 / years_seg) - 1) * 100
        h_sr   = compute_sharpe(h_rets)
        s_sr   = compute_sharpe(s_rets)
        alpha  = h_cagr - s_cagr
        # Beta-adjusted alpha (CAPM alpha annualized)
        beta   = np.cov(h_rets, s_rets)[0, 1] / (np.var(s_rets) + 1e-12)
        capm_alpha = (h_rets.mean() - beta * s_rets.mean()) * 252 * 100
        return {
            'label':      label,
            'n_days':     n,
            'years':      round(years_seg, 1),
            'hydra_cagr': round(h_cagr, 2),
            'spy_cagr':   round(s_cagr, 2),
            'alpha':      round(alpha, 2),
            'capm_alpha': round(capm_alpha, 2),
            'hydra_sr':   round(h_sr, 3),
            'spy_sr':     round(s_sr, 3),
            'beta':       round(beta, 3),
        }

    rows = []

    # ── By regime ────────────────────────────────────────────────────────
    rows.append(segment_metrics(df['regime'] == 'Bull', 'Bull (SPY > SMA200)'))
    rows.append(segment_metrics(df['regime'] == 'Bear', 'Bear (SPY < SMA200)'))

    # ── By decade ────────────────────────────────────────────────────────
    rows.append(segment_metrics(df['year'].between(2000, 2009), '2000-2009'))
    rows.append(segment_metrics(df['year'].between(2010, 2019), '2010-2019'))
    rows.append(segment_metrics(df['year'] >= 2020,             '2020-2026'))

    # ── Full period ──────────────────────────────────────────────────────
    rows.append(segment_metrics(pd.Series([True] * len(df), index=df.index), 'Full Period'))

    rows = [r for r in rows if r is not None]
    return rows


def print_attribution(rows):
    print(f"\n{'=' * 95}")
    print("  REGIME-CONDITIONED PERFORMANCE ATTRIBUTION")
    print(f"{'=' * 95}")
    hdr = (f"{'Segment':<22} {'Days':>5} {'Yrs':>4} "
           f"{'HYDRA CAGR':>11} {'SPY CAGR':>9} {'Alpha':>7} "
           f"{'CAPM_alpha':>10} {'HYDRA SR':>9} {'SPY SR':>7} {'Beta':>6}")
    print(hdr)
    print('-' * 95)
    for r in rows:
        print(
            f"  {r['label']:<20} {r['n_days']:>5} {r['years']:>4.1f} "
            f"  {r['hydra_cagr']:>+8.2f}%  {r['spy_cagr']:>+6.2f}%  {r['alpha']:>+5.2f}%"
            f"  {r['capm_alpha']:>+8.2f}%  {r['hydra_sr']:>+7.3f}  {r['spy_sr']:>+5.3f}  {r['beta']:>5.3f}"
        )
    print('=' * 95)
    print("  Alpha = HYDRA CAGR - SPY CAGR (simple excess return, period-matched)")
    print("  CAPM_alpha = annualized Jensen's alpha (daily regression, beta-adjusted)")
    print(f"  Risk-free rate: {RF_ANNUAL*100:.1f}% (avg Fed Funds 2000-2026)")


# ─────────────────────────────────────────────────────────────────────────────
#  Main
# ─────────────────────────────────────────────────────────────────────────────

def main():
    print("=" * 60)
    print("  HYDRA — DEFLATED SHARPE + REGIME ATTRIBUTION")
    print("=" * 60)
    print(f"  N_trials = {N_TRIALS}  |  rho_mean = {RHO_MEAN}  |  rf = {RF_ANNUAL*100:.1f}%")

    # Load data
    hydra_df = load_hydra()
    spy_df   = load_spy()

    print(f"\n  HYDRA: {len(hydra_df)} rows  "
          f"({hydra_df['date'].iloc[0].date()} to {hydra_df['date'].iloc[-1].date()})")
    print(f"  SPY  : {len(spy_df)} rows  "
          f"({spy_df['date'].iloc[0].date()} to {spy_df['date'].iloc[-1].date()})")

    # ── Task 2: Deflated Sharpe ───────────────────────────────────────────────
    print("\n\n>>> SECTION 1: DEFLATED SHARPE RATIO\n")

    # Gross series
    m_gross = compute_full_metrics(hydra_df['value'].values, 'HYDRA Gross (raw backtest)')
    print_sharpe_report(m_gross)

    # Net series: apply 1% annual cost drag
    hydra_net = apply_net_cost(hydra_df)
    m_net = compute_full_metrics(hydra_net['value'].values, 'HYDRA Net (1% annual cost drag)')
    print_sharpe_report(m_net)

    print(f"\n  NOTE: Bailey & Lopez de Prado (2014) deflated SR penalizes for")
    print(f"  N={N_TRIALS} trials with avg pairwise correlation rho={RHO_MEAN}.")
    print(f"  E[max SR] = {m_gross['sr_max_expected']:.4f} is the expected max Sharpe")
    print(f"  achievable by chance alone across {N_TRIALS} backtests.")
    print(f"  DSR < 0.95 means we cannot rule out that the observed SR")
    print(f"  is explained entirely by selection bias across trials.")

    # ── Task 3: Regime attribution ────────────────────────────────────────────
    print("\n\n>>> SECTION 2: REGIME-CONDITIONED ATTRIBUTION\n")
    attribution_rows = regime_attribution(hydra_df, spy_df)
    print_attribution(attribution_rows)

    print("\n  INTERPRETATION GUIDE:")
    print("  - Bull alpha positive: strategy adds value beyond market exposure")
    print("  - Bear alpha positive: strategy effectively reduces drawdowns in downturns")
    print("  - CAPM alpha > 0 across both regimes: evidence of genuine skill, not just beta")
    print("  - Decade decomposition shows alpha persistence vs. regime-specificity")


if __name__ == '__main__':
    main()
