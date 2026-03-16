"""
Experiment #62b: HYDRA Recomposition with EFA — Survivorship-Corrected
======================================================================
Uses exp62 survivorship-corrected COMPASS daily + Rattlesnake daily + EFA
to produce the definitive HYDRA+EFA numbers.

Three variants:
  1. HYDRA (no EFA) — cash recycling only, idle cash earns nothing
  2. HYDRA + EFA Pure — all idle cash -> EFA, no filter
  3. HYDRA + EFA Filtered — idle cash -> EFA only when EFA > SMA200
"""
import pandas as pd
import numpy as np
import yfinance as yf
import os
import sys

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)

INITIAL_CAPITAL = 100_000
MAX_COMPASS_ALLOC = 0.75
BASE_COMPASS_ALLOC = 0.50
BASE_RATTLE_ALLOC = 0.50
EFA_SMA_PERIOD = 200


def load_efa():
    cache_path = os.path.join(BASE_DIR, 'data_cache', 'efa_daily.csv')
    if os.path.exists(cache_path):
        efa = pd.read_csv(cache_path, index_col=0, parse_dates=True)
        if len(efa) > 0 and 'close' in efa.columns:
            print(f"  EFA (cache): {efa.index[0].date()} to {efa.index[-1].date()}")
            return efa

    print("  Downloading EFA...")
    raw = yf.download('EFA', start='2001-01-01', end='2027-01-01', progress=False)
    if isinstance(raw.columns, pd.MultiIndex):
        raw.columns = raw.columns.get_level_values(0)
    efa = raw[['Close']].rename(columns={'Close': 'close'})
    efa['ret'] = efa['close'].pct_change()
    efa['sma200'] = efa['close'].rolling(EFA_SMA_PERIOD).mean()

    os.makedirs(os.path.dirname(cache_path), exist_ok=True)
    efa.to_csv(cache_path)
    print(f"  EFA (downloaded): {efa.index[0].date()} to {efa.index[-1].date()}")
    return efa


def run_hydra(df, efa, variant, use_efa=True, use_regime_filter=True):
    c_account = INITIAL_CAPITAL * BASE_COMPASS_ALLOC
    r_account = INITIAL_CAPITAL * BASE_RATTLE_ALLOC
    efa_value = 0.0
    portfolio_values = []
    efa_invested_days = 0
    efa_allocs = []

    for i in range(len(df)):
        date = df.index[i]
        r_exp = df['r_exposure'].iloc[i]
        total_value = c_account + r_account + efa_value

        # Cash recycling (R -> C)
        r_idle = r_account * (1.0 - r_exp)
        max_c = max(0, total_value * MAX_COMPASS_ALLOC - c_account)
        recycle = min(r_idle, max_c)
        c_effective = c_account + recycle
        r_effective = r_account - recycle

        # EFA allocation
        if use_efa:
            r_still_idle = r_effective * (1.0 - r_exp)
            idle_cash = r_still_idle

            efa_eligible = True
            if use_regime_filter and date in efa.index:
                sma = efa.loc[date, 'sma200']
                close = efa.loc[date, 'close']
                if pd.notna(sma) and close < sma:
                    efa_eligible = False

            target_efa = idle_cash if (date in efa.index and efa_eligible) else 0.0

            if target_efa > efa_value:
                r_effective -= (target_efa - efa_value)
                efa_value = target_efa
            elif target_efa < efa_value:
                r_effective += (efa_value - target_efa)
                efa_value = target_efa

        # Daily returns
        c_r = df['c_ret'].iloc[i]
        r_r = df['r_ret'].iloc[i]
        efa_ret = 0.0
        if use_efa and date in efa.index and efa_value > 0:
            efa_ret = efa.loc[date, 'ret']
            if pd.isna(efa_ret):
                efa_ret = 0.0
            efa_invested_days += 1

        c_new = c_effective * (1 + c_r)
        r_new = r_effective * (1 + r_r)
        efa_new = efa_value * (1 + efa_ret)

        recycled_after = recycle * (1 + c_r)
        c_account = c_new - recycled_after
        r_account = r_new + recycled_after
        efa_value = efa_new

        total_new = c_account + r_account + efa_value
        portfolio_values.append(total_new)
        efa_allocs.append(efa_value / total_new if total_new > 0 else 0)

    pv = pd.Series(portfolio_values, index=df.index)
    returns = pv.pct_change().dropna()
    years = len(df) / 252
    cagr = (pv.iloc[-1] / INITIAL_CAPITAL) ** (1 / years) - 1
    maxdd = (pv / pv.cummax() - 1).min()
    sharpe = returns.mean() / returns.std() * np.sqrt(252)
    vol = returns.std() * np.sqrt(252)
    sortino = returns.mean() / returns[returns < 0].std() * np.sqrt(252)
    calmar = cagr / abs(maxdd) if maxdd != 0 else 0

    efa_series = pd.Series(efa_allocs, index=df.index)

    return {
        'name': variant, 'pv': pv, 'cagr': cagr, 'maxdd': maxdd,
        'sharpe': sharpe, 'vol': vol, 'sortino': sortino, 'calmar': calmar,
        'final': pv.iloc[-1], 'efa_days': efa_invested_days,
        'efa_pct': efa_invested_days / len(df) * 100 if use_efa else 0,
        'avg_efa_alloc': efa_series.mean() * 100 if use_efa else 0,
        'efa_allocs': efa_series,
    }


if __name__ == '__main__':
    print("=" * 80)
    print("EXP62b: HYDRA RECOMPOSITION — SURVIVORSHIP-CORRECTED + EFA")
    print("=" * 80)

    # Load data
    print("\nLoading data...")
    c62 = pd.read_csv(os.path.join(BASE_DIR, 'backtests', 'exp62_survivorship_daily.csv'),
                      parse_dates=['date']).set_index('date')
    print(f"  COMPASS (exp62 corrected): {c62.index[0].date()} to {c62.index[-1].date()}, {len(c62)} rows")

    rattle = pd.read_csv(os.path.join(BASE_DIR, 'backtests', 'rattlesnake_daily.csv'),
                         index_col=0, parse_dates=True)
    print(f"  Rattlesnake:               {rattle.index[0].date()} to {rattle.index[-1].date()}, {len(rattle)} rows")

    efa = load_efa()

    # Align
    c_ret = c62['value'].pct_change()
    r_ret = rattle['value'].pct_change()
    r_exposure = rattle['exposure']

    df = pd.DataFrame({
        'c_ret': c_ret,
        'r_ret': r_ret,
        'r_exposure': r_exposure,
    }).dropna()
    print(f"  Aligned period:            {df.index[0].date()} to {df.index[-1].date()}, {len(df)} days ({len(df)/252:.1f} years)")

    # Run 3 variants
    print("\nRunning simulations...")
    r1 = run_hydra(df, efa, 'HYDRA (no EFA)', use_efa=False)
    r2 = run_hydra(df, efa, 'HYDRA + EFA Pure', use_efa=True, use_regime_filter=False)
    r3 = run_hydra(df, efa, 'HYDRA + EFA Filtered', use_efa=True, use_regime_filter=True)

    # Results table
    print()
    print("=" * 80)
    print("  RESULTS")
    print("=" * 80)
    header = f"  {'Metric':<18} {'HYDRA (no EFA)':>16} {'+ EFA Pure':>16} {'+ EFA Filtered':>16}"
    print(header)
    print(f"  {'-'*68}")
    for label, key, fmt in [
        ('CAGR', 'cagr', '.2%'),
        ('Max DD', 'maxdd', '.2%'),
        ('Sharpe', 'sharpe', '.2f'),
        ('Sortino', 'sortino', '.2f'),
        ('Calmar', 'calmar', '.2f'),
        ('Volatility', 'vol', '.2%'),
    ]:
        v1 = format(r1[key], fmt)
        v2 = format(r2[key], fmt)
        v3 = format(r3[key], fmt)
        print(f"  {label:<18} {v1:>16} {v2:>16} {v3:>16}")

    print(f"  {'Final Value':<18} ${r1['final']:>14,.0f} ${r2['final']:>14,.0f} ${r3['final']:>14,.0f}")
    print(f"  {'EFA Days (%)':<18} {'N/A':>16} {r2['efa_pct']:>15.1f}% {r3['efa_pct']:>15.1f}%")
    print(f"  {'Avg EFA Alloc':<18} {'N/A':>16} {r2['avg_efa_alloc']:>15.1f}% {r3['avg_efa_alloc']:>15.1f}%")

    # Deltas
    print()
    for r in [r2, r3]:
        dc = r['cagr'] - r1['cagr']
        ds = r['sharpe'] - r1['sharpe']
        dd = r['maxdd'] - r1['maxdd']
        print(f"  {r['name']} vs no-EFA:")
        print(f"    CAGR {dc:+.2%} | Sharpe {ds:+.2f} | MaxDD {dd:+.2%}")

    # Annual returns comparison
    print()
    print(f"  {'Year':<8} {'No EFA':>10} {'Pure':>10} {'Filtered':>10}")
    print(f"  {'-'*40}")
    for r in [r1, r2, r3]:
        r['annual'] = r['pv'].resample('YE').last().pct_change().dropna()
    years = sorted(set(r1['annual'].index) & set(r2['annual'].index) & set(r3['annual'].index))
    for idx in years:
        y = idx.year
        a1 = r1['annual'].loc[idx]
        a2 = r2['annual'].loc[idx]
        a3 = r3['annual'].loc[idx]
        print(f"  {y:<8} {a1:>+9.1%} {a2:>+9.1%} {a3:>+9.1%}")

    # Verdict
    print()
    best = r3 if r3['sharpe'] >= r2['sharpe'] else r2
    if best['cagr'] > r1['cagr'] and best['sharpe'] >= r1['sharpe']:
        print(f"  VERDICT: EFA APPROVED")
        print(f"    {best['name']} adds {best['cagr']-r1['cagr']:+.2%} CAGR, {best['sharpe']-r1['sharpe']:+.2f} Sharpe")
    elif best['cagr'] > r1['cagr']:
        print(f"  VERDICT: EFA MARGINAL — adds CAGR but risk-adjusted is mixed")
    else:
        print(f"  VERDICT: EFA REJECTED — no improvement")

    # Save
    best_out = pd.DataFrame({'value': best['pv']})
    best_out.to_csv(os.path.join(BASE_DIR, 'backtests', 'exp62_hydra_efa_daily.csv'))
    print(f"\n  Saved: backtests/exp62_hydra_efa_daily.csv")
    print("=" * 80)
