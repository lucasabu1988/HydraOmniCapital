"""
Box Spread Analysis -- Financing Cost Optimization
====================================================
Compares leverage financing strategies for COMPASS v8.2:

  A) Broker margin at 6.0% (current assumption)
  B) Box Spread at SOFR + 20bps (institutional financing)
  C) Box Spread at SOFR + 50bps (conservative estimate)

A Box Spread is a European-style options strategy on SPX that synthetically
replicates a risk-free loan. Selling a box spread = borrowing at near risk-free
rates, bypassing broker margin entirely.

All variants use MOC execution (Close[T+1] + 2bps) as the realistic baseline.
The ONLY variable that changes is the margin rate function.

Historical Fed Funds Rate is used as SOFR proxy (SOFR tracks Fed Funds tightly).
"""

import pandas as pd
import numpy as np
import os
from datetime import timedelta
import time as time_module
import warnings
warnings.filterwarnings('ignore')

# ============================================================================
# MOTOR PARAMETERS (LOCKED -- identical to production)
# ============================================================================
TOP_N = 40
MIN_AGE_DAYS = 63
MOMENTUM_LOOKBACK = 90
MOMENTUM_SKIP = 5
REGIME_SMA_PERIOD = 200
REGIME_CONFIRM_DAYS = 3
NUM_POSITIONS = 5
NUM_POSITIONS_RISK_OFF = 2
HOLD_DAYS = 5
POSITION_STOP_LOSS = -0.08
TRAILING_ACTIVATION = 0.05
TRAILING_STOP_PCT = 0.03
PORTFOLIO_STOP_LOSS = -0.15
RECOVERY_STAGE_1_DAYS = 63
RECOVERY_STAGE_2_DAYS = 126
TARGET_VOL = 0.15
LEVERAGE_MIN = 0.3
LEVERAGE_MAX = 2.0
VOL_LOOKBACK = 20
INITIAL_CAPITAL = 100_000
COMMISSION_PER_SHARE = 0.001

# ============================================================================
# FINANCING PARAMETERS
# ============================================================================

# Historical Fed Funds Rate (annual averages, used as SOFR proxy)
FED_FUNDS_BY_YEAR = {
    2000: 0.0624, 2001: 0.0362, 2002: 0.0167, 2003: 0.0101, 2004: 0.0135,
    2005: 0.0322, 2006: 0.0497, 2007: 0.0502, 2008: 0.0193, 2009: 0.0016,
    2010: 0.0018, 2011: 0.0010, 2012: 0.0014, 2013: 0.0011, 2014: 0.0009,
    2015: 0.0013, 2016: 0.0039, 2017: 0.0100, 2018: 0.0191, 2019: 0.0216,
    2020: 0.0009, 2021: 0.0008, 2022: 0.0177, 2023: 0.0533, 2024: 0.0533,
    2025: 0.0450, 2026: 0.0400,
}

# T-Bill yields for cash
TBILL_YIELD_BY_ERA = {
    2000: 0.055, 2001: 0.035, 2002: 0.016, 2003: 0.010, 2004: 0.022,
    2005: 0.040, 2006: 0.048, 2007: 0.045, 2008: 0.015, 2009: 0.002,
    2010: 0.001, 2011: 0.001, 2012: 0.001, 2013: 0.001, 2014: 0.001,
    2015: 0.002, 2016: 0.005, 2017: 0.013, 2018: 0.024, 2019: 0.021,
    2020: 0.004, 2021: 0.001, 2022: 0.030, 2023: 0.052, 2024: 0.050,
    2025: 0.043, 2026: 0.040,
}

BROAD_POOL = [
    'AAPL', 'MSFT', 'NVDA', 'GOOGL', 'META', 'AVGO', 'ADBE', 'CRM', 'AMD',
    'INTC', 'CSCO', 'IBM', 'TXN', 'QCOM', 'ORCL', 'ACN', 'NOW', 'INTU',
    'AMAT', 'MU', 'LRCX', 'SNPS', 'CDNS', 'KLAC', 'MRVL',
    'BRK-B', 'JPM', 'V', 'MA', 'BAC', 'WFC', 'GS', 'MS', 'AXP', 'BLK',
    'SCHW', 'C', 'USB', 'PNC', 'TFC', 'CB', 'MMC', 'AIG',
    'UNH', 'JNJ', 'LLY', 'ABBV', 'MRK', 'PFE', 'TMO', 'ABT', 'DHR',
    'AMGN', 'BMY', 'MDT', 'ISRG', 'SYK', 'GILD', 'REGN', 'VRTX', 'BIIB',
    'AMZN', 'TSLA', 'WMT', 'HD', 'PG', 'COST', 'KO', 'PEP', 'NKE',
    'MCD', 'DIS', 'SBUX', 'TGT', 'LOW', 'CL', 'KMB', 'GIS', 'EL',
    'MO', 'PM',
    'XOM', 'CVX', 'COP', 'SLB', 'EOG', 'OXY', 'MPC', 'PSX', 'VLO',
    'GE', 'CAT', 'BA', 'HON', 'UNP', 'RTX', 'LMT', 'DE', 'UPS', 'FDX',
    'MMM', 'GD', 'NOC', 'EMR',
    'NEE', 'DUK', 'SO', 'D', 'AEP',
    'VZ', 'T', 'TMUS', 'CMCSA',
]


# ============================================================================
# MARGIN RATE FUNCTIONS
# ============================================================================

def margin_broker_6pct(year):
    """Fixed 6.0% broker margin (current IBKR-like assumption)."""
    return 0.06

def margin_box_spread_20bps(year):
    """Box Spread at SOFR + 20bps (institutional best case)."""
    return FED_FUNDS_BY_YEAR.get(year, 0.04) + 0.0020

def margin_box_spread_50bps(year):
    """Box Spread at SOFR + 50bps (conservative retail-accessible)."""
    return FED_FUNDS_BY_YEAR.get(year, 0.04) + 0.0050

def margin_ibkr_pro(year):
    """IBKR Pro margin rate: Fed Funds + 1.5% (tiered, approximate)."""
    return FED_FUNDS_BY_YEAR.get(year, 0.04) + 0.015


# ============================================================================
# DATA LOADING
# ============================================================================

def load_data():
    cache_dir = 'data_cache_parquet'
    data = {}
    for symbol in BROAD_POOL:
        pq = os.path.join(cache_dir, f'{symbol}.parquet')
        if os.path.exists(pq):
            df = pd.read_parquet(pq)
            if len(df) > 100:
                data[symbol] = df
    spy = pd.read_parquet(os.path.join(cache_dir, 'SPY.parquet'))
    return data, spy


def build_matrices(price_data, spy_data):
    all_dates = sorted(spy_data.index.tolist())
    symbols = sorted(price_data.keys())
    close_data = {}
    open_data = {}
    volume_data = {}
    for s in symbols:
        df = price_data[s]
        close_data[s] = df['Close'].reindex(all_dates)
        open_data[s] = df['Open'].reindex(all_dates)
        volume_data[s] = df['Volume'].reindex(all_dates)
    close_m = pd.DataFrame(close_data, index=all_dates)
    open_m = pd.DataFrame(open_data, index=all_dates)
    vol_m = pd.DataFrame(volume_data, index=all_dates)
    spy_close = spy_data['Close'].reindex(all_dates)
    return all_dates, close_m, open_m, vol_m, spy_close


def compute_regime(spy_close):
    sma200 = spy_close.rolling(REGIME_SMA_PERIOD).mean()
    raw = spy_close > sma200
    regime = pd.Series(index=spy_close.index, dtype=bool)
    regime.iloc[:REGIME_SMA_PERIOD] = True
    current = True
    consec = 0
    last = True
    for i in range(REGIME_SMA_PERIOD, len(raw)):
        r = raw.iloc[i]
        if pd.isna(r):
            regime.iloc[i] = current
            continue
        if r == last:
            consec += 1
        else:
            consec = 1
            last = r
        if r != current and consec >= REGIME_CONFIRM_DAYS:
            current = r
        regime.iloc[i] = current
    return regime


def compute_top40(close_m, vol_m, all_dates):
    years = sorted(set(d.year for d in all_dates))
    annual = {}
    for year in years:
        mask = np.array([d.year == year - 1 for d in all_dates])
        if mask.sum() < 20:
            continue
        dv = (close_m.iloc[mask] * vol_m.iloc[mask]).mean().dropna()
        top = dv.nlargest(min(TOP_N, len(dv))).index.tolist()
        annual[year] = top
    return annual


# ============================================================================
# BACKTEST (parameterized margin rate)
# ============================================================================

def run_variant(close_m, open_m, spy_close, all_dates, annual_universe,
                margin_rate_func, label: str):
    """Run COMPASS backtest with MOC execution (Close[T+1]+2bps) and
    variable margin rate function.

    Execution: MOC (Close[T+1] + 2bps) -- fixed for all variants
    Variable: margin_rate_func(year) -> annual rate for leveraged capital
    """

    print(f"\n  [{label}] Running...")

    regime = compute_regime(spy_close)
    first_date = all_dates[0]
    symbols_list = close_m.columns.tolist()
    slip_rate = 2 / 10000.0  # Fixed 2bps MOC slippage

    def exec_price(i, symbol, direction):
        # MOC: execute at next day's Close + 2bps slippage
        if i + 1 < len(close_m):
            raw = close_m.iloc[i + 1][symbol]
            if pd.isna(raw) or raw <= 0:
                raw = close_m.iloc[i][symbol]
        else:
            raw = close_m.iloc[i][symbol]
        if pd.isna(raw) or raw <= 0:
            return None
        if direction == 'buy':
            return raw * (1.0 + slip_rate)
        else:
            return raw * (1.0 - slip_rate)

    cash = float(INITIAL_CAPITAL)
    positions = {}
    portfolio_values = []
    trades = []
    stop_events = []
    peak_value = float(INITIAL_CAPITAL)
    in_prot = False
    prot_stage = 0
    stop_day_idx = None

    # Tracking
    total_margin_cost = 0.0
    margin_cost_by_year = {}
    leveraged_days = 0

    for i, date in enumerate(all_dates):
        # Tradeable
        eligible = set(annual_universe.get(date.year, []))
        tradeable = []
        for s in eligible:
            if s not in symbols_list:
                continue
            cv = close_m.iloc[i][s]
            if pd.isna(cv):
                continue
            fv = close_m[s].first_valid_index()
            if fv is None:
                continue
            if date <= first_date + timedelta(days=30) or (date - fv).days >= MIN_AGE_DAYS:
                tradeable.append(s)

        # Portfolio value
        pv = cash
        for s, p in positions.items():
            cv = close_m.iloc[i][s]
            if not pd.isna(cv):
                pv += p['shares'] * cv

        if pv > peak_value and not in_prot:
            peak_value = pv

        # Recovery
        if in_prot and stop_day_idx is not None:
            ds = i - stop_day_idx
            ro = bool(regime.iloc[i]) if i < len(regime) else True
            if prot_stage == 1 and ds >= RECOVERY_STAGE_1_DAYS and ro:
                prot_stage = 2
            if prot_stage == 2 and ds >= RECOVERY_STAGE_2_DAYS and ro:
                in_prot = False
                prot_stage = 0
                peak_value = pv
                stop_day_idx = None

        dd = (pv - peak_value) / peak_value if peak_value > 0 else 0

        # Portfolio stop
        if dd <= PORTFOLIO_STOP_LOSS and not in_prot:
            stop_events.append(date)
            for s in list(positions.keys()):
                ep = exec_price(i, s, 'sell')
                p = positions[s]
                if ep is None:
                    cv = close_m.iloc[i][s]
                    ep = cv if not pd.isna(cv) else p['ep']
                cash += p['shares'] * ep - p['shares'] * COMMISSION_PER_SHARE
                pnl = (ep - p['ep']) * p['shares']
                trades.append({'pnl': pnl, 'ret': pnl / (p['ep'] * p['shares'])})
                del positions[s]
            in_prot = True
            prot_stage = 1
            stop_day_idx = i

        # Regime
        is_ro = bool(regime.iloc[i]) if i < len(regime) else True

        # Max pos & leverage
        if in_prot:
            max_pos = 2 if prot_stage == 1 else 3
            lev = 0.3 if prot_stage == 1 else 1.0
        elif not is_ro:
            max_pos = NUM_POSITIONS_RISK_OFF
            lev = 1.0
        else:
            max_pos = NUM_POSITIONS
            if i >= VOL_LOOKBACK + 1:
                rets = spy_close.iloc[i - VOL_LOOKBACK:i + 1].pct_change().dropna()
                if len(rets) >= VOL_LOOKBACK - 2:
                    rv = rets.std() * np.sqrt(252)
                    lev = max(LEVERAGE_MIN, min(LEVERAGE_MAX, TARGET_VOL / rv)) if rv > 0.01 else LEVERAGE_MAX
                else:
                    lev = 1.0
            else:
                lev = 1.0

        # Daily costs -- THIS IS THE VARIABLE PART
        if lev > 1.0:
            leveraged_days += 1
            year = date.year
            rate = margin_rate_func(year)
            daily_cost = rate / 252 * pv * (lev - 1) / lev
            cash -= daily_cost
            total_margin_cost += daily_cost
            if year not in margin_cost_by_year:
                margin_cost_by_year[year] = 0.0
            margin_cost_by_year[year] += daily_cost

        # Cash yield (T-Bill, same for all variants)
        if cash > 0:
            cash += cash * (TBILL_YIELD_BY_ERA.get(date.year, 0.035) / 252)

        # Exits
        for s in list(positions.keys()):
            p = positions[s]
            cv = close_m.iloc[i][s]
            if pd.isna(cv):
                continue
            exit_r = None
            if i - p['eidx'] >= HOLD_DAYS:
                exit_r = 'hold'
            pr = (cv - p['ep']) / p['ep']
            if pr <= POSITION_STOP_LOSS:
                exit_r = 'pos_stop'
            if cv > p['high']:
                p['high'] = cv
            if p['high'] > p['ep'] * (1 + TRAILING_ACTIVATION):
                if cv <= p['high'] * (1 - TRAILING_STOP_PCT):
                    exit_r = 'trail'
            if s not in tradeable:
                exit_r = 'univ'
            if exit_r is None and len(positions) > max_pos:
                prs = {}
                for s2, p2 in positions.items():
                    cv2 = close_m.iloc[i][s2]
                    if not pd.isna(cv2):
                        prs[s2] = (cv2 - p2['ep']) / p2['ep']
                if prs and s == min(prs, key=prs.get):
                    exit_r = 'reduce'
            if exit_r:
                ep = exec_price(i, s, 'sell')
                if ep is None:
                    ep = cv
                cash += p['shares'] * ep - p['shares'] * COMMISSION_PER_SHARE
                pnl = (ep - p['ep']) * p['shares']
                trades.append({'pnl': pnl, 'ret': pnl / (p['ep'] * p['shares'])})
                del positions[s]

        # Entries
        needed = max_pos - len(positions)
        if needed > 0 and cash > 1000 and len(tradeable) >= 5:
            scores = {}
            for s in tradeable:
                if s not in symbols_list or i < MOMENTUM_LOOKBACK + MOMENTUM_SKIP:
                    continue
                c0 = close_m.iloc[i][s]
                c5 = close_m.iloc[i - MOMENTUM_SKIP][s]
                c90 = close_m.iloc[i - MOMENTUM_LOOKBACK][s]
                if pd.isna(c0) or pd.isna(c5) or pd.isna(c90) or c90 <= 0 or c5 <= 0:
                    continue
                scores[s] = (c5 / c90 - 1) - (c0 / c5 - 1)
            avail = {s: sc for s, sc in scores.items() if s not in positions}
            if len(avail) >= needed:
                sel = [s for s, _ in sorted(avail.items(), key=lambda x: -x[1])[:needed]]
                vols = {}
                for s in sel:
                    if i < VOL_LOOKBACK + 1:
                        continue
                    r = close_m[s].iloc[i - VOL_LOOKBACK:i + 1].pct_change().dropna()
                    if len(r) >= VOL_LOOKBACK - 2:
                        v = r.std() * np.sqrt(252)
                        if v > 0.01:
                            vols[s] = v
                if vols:
                    rw = {s: 1.0 / v for s, v in vols.items()}
                    tw = sum(rw.values())
                    wts = {s: w / tw for s, w in rw.items()}
                else:
                    wts = {s: 1.0 / len(sel) for s in sel}

                eff_cap = cash * lev * 0.95
                for s in sel:
                    ep = exec_price(i, s, 'buy')
                    if ep is None:
                        continue
                    w = wts.get(s, 1.0 / len(sel))
                    pv_s = min(eff_cap * w, cash * 0.40)
                    sh = pv_s / ep
                    cost = sh * ep + sh * COMMISSION_PER_SHARE
                    if cost <= cash * 0.90:
                        positions[s] = {'ep': ep, 'shares': sh, 'eidx': i, 'high': ep}
                        cash -= cost

        portfolio_values.append(pv)

    # Metrics
    pv_series = pd.Series(portfolio_values, index=all_dates)
    final = pv_series.iloc[-1]
    years = len(pv_series) / 252
    cagr = (final / INITIAL_CAPITAL) ** (1 / years) - 1
    rets = pv_series.pct_change().dropna()
    vol = rets.std() * np.sqrt(252)
    sharpe = cagr / vol if vol > 0 else 0
    peak_s = pv_series.expanding().max()
    max_dd = ((pv_series - peak_s) / peak_s).min()
    trades_df = pd.DataFrame(trades)
    win_rate = (trades_df['pnl'] > 0).mean() if len(trades_df) > 0 else 0

    return {
        'label': label,
        'final': final,
        'cagr': cagr,
        'sharpe': sharpe,
        'max_dd': max_dd,
        'vol': vol,
        'trades': len(trades_df),
        'win_rate': win_rate,
        'stops': len(stop_events),
        'pv_series': pv_series,
        'total_margin_cost': total_margin_cost,
        'margin_cost_by_year': margin_cost_by_year,
        'leveraged_days': leveraged_days,
    }


# ============================================================================
# MAIN
# ============================================================================

if __name__ == "__main__":
    print("=" * 80)
    print("BOX SPREAD ANALYSIS -- Leverage Financing Optimization")
    print("=" * 80)
    print("All variants use: MOC execution (Close[T+1] + 2bps)")
    print("Variable: margin rate on leveraged capital")

    t0 = time_module.time()

    # Load data
    print("\n[1/3] Loading data (Parquet cache)...")
    price_data, spy_data = load_data()
    print(f"  Loaded {len(price_data)} symbols + SPY")

    print("[2/3] Building aligned matrices...")
    all_dates, close_m, open_m, vol_m, spy_close = build_matrices(price_data, spy_data)
    print(f"  Matrix: {len(all_dates)} dates x {len(close_m.columns)} symbols")

    print("[3/3] Computing annual Top-40...")
    annual = compute_top40(close_m, vol_m, all_dates)

    # Define variants -- same execution, different margin rates
    variants = [
        (margin_broker_6pct,       "A: Broker 6.0% (current)"),
        (margin_ibkr_pro,          "B: IBKR Pro (FFR+1.5%)"),
        (margin_box_spread_50bps,  "C: Box Spread (SOFR+50bps)"),
        (margin_box_spread_20bps,  "D: Box Spread (SOFR+20bps)"),
    ]

    print("\n" + "=" * 80)
    print("RUNNING 4 FINANCING VARIANTS")
    print("=" * 80)

    results = []
    for margin_func, label in variants:
        r = run_variant(close_m, open_m, spy_close, all_dates, annual,
                       margin_rate_func=margin_func, label=label)
        results.append(r)
        print(f"    -> CAGR: {r['cagr']:.2%} | Sharpe: {r['sharpe']:.3f} | "
              f"MaxDD: {r['max_dd']:.1%} | Final: ${r['final']:,.0f} | "
              f"Margin cost: ${r['total_margin_cost']:,.0f}")

    t_total = time_module.time() - t0

    # ========================================================================
    # RESULTS
    # ========================================================================
    print("\n" + "=" * 80)
    print("RESULTS -- Box Spread Financing Analysis")
    print("=" * 80)

    A = results[0]  # Broker 6%
    B = results[1]  # IBKR Pro
    C = results[2]  # Box +50bps
    D = results[3]  # Box +20bps

    print(f"\n  {'Variant':<35} {'CAGR':>8} {'Sharpe':>8} {'MaxDD':>8} "
          f"{'Final':>14} {'Margin$':>12} {'WR':>6}")
    print(f"  {'-'*95}")
    for r in results:
        print(f"  {r['label']:<35} {r['cagr']:>7.2%} {r['sharpe']:>8.3f} "
              f"{r['max_dd']:>7.1%} ${r['final']:>12,.0f} ${r['total_margin_cost']:>11,.0f} "
              f"{r['win_rate']:>5.1%}")

    # Savings vs broker
    print(f"\n  {'='*70}")
    print(f"  SAVINGS vs BROKER 6% (Variant A)")
    print(f"  {'='*70}")
    for r in results[1:]:
        cagr_gain = r['cagr'] - A['cagr']
        margin_saved = A['total_margin_cost'] - r['total_margin_cost']
        final_gain = r['final'] - A['final']
        print(f"  {r['label']:<35}")
        print(f"    CAGR gain:     {cagr_gain:>+8.2%}")
        print(f"    Margin saved:  ${margin_saved:>12,.0f}")
        print(f"    Final gain:    ${final_gain:>12,.0f}")
        print(f"    Sharpe gain:   {r['sharpe'] - A['sharpe']:>+8.3f}")
        print()

    # Year-by-year rate comparison
    print(f"  {'='*70}")
    print(f"  EFFECTIVE MARGIN RATES BY YEAR")
    print(f"  {'='*70}")
    print(f"  {'Year':<6} {'Fed Funds':>10} {'Broker 6%':>10} {'IBKR Pro':>10} "
          f"{'Box+50bp':>10} {'Box+20bp':>10} {'Savings':>10}")
    print(f"  {'-'*70}")

    for year in sorted(FED_FUNDS_BY_YEAR.keys()):
        if year < 2000 or year > 2026:
            continue
        ff = FED_FUNDS_BY_YEAR[year]
        broker = 0.06
        ibkr = ff + 0.015
        box50 = ff + 0.005
        box20 = ff + 0.002
        saving = broker - box20
        print(f"  {year:<6} {ff:>9.2%} {broker:>9.2%} {ibkr:>9.2%} "
              f"{box50:>9.2%} {box20:>9.2%} {saving:>+9.2%}")

    # Key insight
    print(f"\n  {'='*70}")
    print(f"  KEY INSIGHTS")
    print(f"  {'='*70}")

    box_best = D  # SOFR+20bps
    total_saved = A['total_margin_cost'] - box_best['total_margin_cost']
    cagr_diff = box_best['cagr'] - A['cagr']

    print(f"  1. Box Spread (SOFR+20bps) saves ${total_saved:,.0f} in margin over 26 years")
    print(f"  2. CAGR improvement: {cagr_diff:+.2%} ({A['cagr']:.2%} -> {box_best['cagr']:.2%})")
    print(f"  3. Sharpe improvement: {box_best['sharpe'] - A['sharpe']:+.3f}")
    print(f"  4. Days with leverage > 1.0x: {A['leveraged_days']:,} ({A['leveraged_days']/len(all_dates)*100:.1f}%)")

    # ZIRP era analysis
    zirp_saved_a = sum(A['margin_cost_by_year'].get(y, 0) for y in range(2009, 2022))
    zirp_saved_d = sum(box_best['margin_cost_by_year'].get(y, 0) for y in range(2009, 2022))
    print(f"\n  ZIRP ERA (2009-2021) -- where Box Spreads shine:")
    print(f"    Broker 6% margin cost:     ${zirp_saved_a:>12,.0f}")
    print(f"    Box Spread margin cost:    ${zirp_saved_d:>12,.0f}")
    print(f"    Savings during ZIRP alone: ${zirp_saved_a - zirp_saved_d:>12,.0f}")
    print(f"    Broker charged 6% while risk-free rate was 0.1%-0.2%")
    print(f"    Box Spread would have charged 0.3%-0.4%")

    # Risk assessment
    print(f"\n  {'='*70}")
    print(f"  RISK ASSESSMENT")
    print(f"  {'='*70}")
    print(f"  Box Spread risk:     ZERO (synthetic T-bill, European SPX options)")
    print(f"  Execution complexity: MODERATE")
    print(f"    - Need Level 3/4 options approval at most brokers")
    print(f"    - SPX options are European-style (no early assignment risk)")
    print(f"    - Typical box: sell high-strike call spread + buy high-strike put spread")
    print(f"    - Roll every 90 days, ~4 trades/year")
    print(f"    - Available at: IBKR, Schwab, TD Ameritrade, Tastyworks")
    print(f"  MaxDD unchanged:     {A['max_dd']:.1%} vs {box_best['max_dd']:.1%}")
    print(f"  Win rate unchanged:  {A['win_rate']:.1%} vs {box_best['win_rate']:.1%}")
    print(f"  Stops unchanged:     {A['stops']} vs {box_best['stops']}")

    # Total execution time
    print(f"\n  Total time: {t_total:.0f}s ({t_total/len(variants):.0f}s per variant)")

    # Save results
    os.makedirs('backtests', exist_ok=True)
    comp = pd.DataFrame([{
        'variant': r['label'],
        'cagr_pct': round(r['cagr'] * 100, 2),
        'sharpe': round(r['sharpe'], 3),
        'max_dd_pct': round(r['max_dd'] * 100, 1),
        'final_value': round(r['final'], 0),
        'total_margin_cost': round(r['total_margin_cost'], 0),
        'leveraged_days': r['leveraged_days'],
        'trades': r['trades'],
        'win_rate_pct': round(r['win_rate'] * 100, 1),
        'stops': r['stops'],
    } for r in results])
    comp.to_csv('backtests/box_spread_comparison.csv', index=False)
    print(f"\n  Saved: backtests/box_spread_comparison.csv")

    # Save daily equity curves for all variants
    equity_df = pd.DataFrame({r['label']: r['pv_series'] for r in results})
    equity_df.index.name = 'date'
    equity_df.to_csv('backtests/box_spread_equity_curves.csv')
    print(f"  Saved: backtests/box_spread_equity_curves.csv")

    print("\n" + "=" * 80)
    print("BOX SPREAD ANALYSIS COMPLETE")
    print("=" * 80)
