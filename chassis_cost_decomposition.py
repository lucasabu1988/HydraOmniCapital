"""
Cost Decomposition Analysis -- Where does every dollar go?
============================================================
Runs the COMPASS v8.2 backtest with MOC execution (Close[T+1]+2bps)
and Box Spread financing (SOFR+20bps), tracking EVERY cost component
separately to see the exact CAGR drag of each.

Components tracked:
  1. Slippage (2bps per side on MOC orders)
  2. Commissions ($0.001/share)
  3. Margin interest (SOFR+20bps on leveraged capital)
  4. Cash yield earned (T-Bill rate on uninvested cash)
  5. Overnight gap cost (implicit, from using T+1 vs T execution)

Also runs a ZERO-COST variant (no slippage, no commission, no margin,
no cash yield) to establish the pure signal alpha.
"""

import pandas as pd
import numpy as np
import os
from datetime import timedelta
import time as time_module
import warnings
warnings.filterwarnings('ignore')

# ============================================================================
# MOTOR PARAMETERS (LOCKED)
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

# Historical rates
FED_FUNDS_BY_YEAR = {
    2000: 0.0624, 2001: 0.0362, 2002: 0.0167, 2003: 0.0101, 2004: 0.0135,
    2005: 0.0322, 2006: 0.0497, 2007: 0.0502, 2008: 0.0193, 2009: 0.0016,
    2010: 0.0018, 2011: 0.0010, 2012: 0.0014, 2013: 0.0011, 2014: 0.0009,
    2015: 0.0013, 2016: 0.0039, 2017: 0.0100, 2018: 0.0191, 2019: 0.0216,
    2020: 0.0009, 2021: 0.0008, 2022: 0.0177, 2023: 0.0533, 2024: 0.0533,
    2025: 0.0450, 2026: 0.0400,
}
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
# DATA
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
# BACKTEST WITH FULL COST TRACKING
# ============================================================================

def run_with_cost_tracking(close_m, open_m, spy_close, all_dates, annual_universe,
                           slippage_bps, commission_per_share, margin_spread,
                           use_cash_yield, use_moc, label,
                           max_leverage=2.0, fixed_margin_rate=None):
    """Run backtest tracking every cost component separately.

    Args:
        slippage_bps: basis points slippage per side (0 = no slippage)
        commission_per_share: commission cost (0 = no commissions)
        margin_spread: spread over Fed Funds for margin (e.g. 0.002 for Box+20bps)
                       Use None for zero margin cost
        use_cash_yield: whether to apply T-Bill yield on cash
        use_moc: True = Close[T+1], False = Close[T]
        label: variant name
        max_leverage: cap on leverage (1.0 = no leverage, 2.0 = default)
        fixed_margin_rate: if set, use this fixed rate instead of FFR+spread
    """

    print(f"\n  [{label}] Running...")

    regime = compute_regime(spy_close)
    first_date = all_dates[0]
    symbols_list = close_m.columns.tolist()
    slip_rate = slippage_bps / 10000.0

    def exec_price(i, symbol, direction):
        if use_moc and i + 1 < len(close_m):
            raw = close_m.iloc[i + 1][symbol]
            if pd.isna(raw) or raw <= 0:
                raw = close_m.iloc[i][symbol]
        else:
            raw = close_m.iloc[i][symbol]
        if pd.isna(raw) or raw <= 0:
            return None, 0.0
        if direction == 'buy':
            slippage_cost = raw * slip_rate
            return raw * (1.0 + slip_rate), slippage_cost
        else:
            slippage_cost = raw * slip_rate
            return raw * (1.0 - slip_rate), slippage_cost

    cash = float(INITIAL_CAPITAL)
    positions = {}
    portfolio_values = []
    peak_value = float(INITIAL_CAPITAL)
    in_prot = False
    prot_stage = 0
    stop_day_idx = None

    # Cost accumulators
    total_slippage = 0.0
    total_commissions = 0.0
    total_margin_cost = 0.0
    total_cash_yield = 0.0
    total_trades = 0

    # Year-by-year tracking
    yearly_costs = {}

    for i, date in enumerate(all_dates):
        year = date.year
        if year not in yearly_costs:
            yearly_costs[year] = {
                'slippage': 0.0, 'commissions': 0.0,
                'margin': 0.0, 'cash_yield': 0.0, 'trades': 0
            }

        # Tradeable
        eligible = set(annual_universe.get(year, []))
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
            for s in list(positions.keys()):
                ep, slip_cost = exec_price(i, s, 'sell')
                p = positions[s]
                if ep is None:
                    cv = close_m.iloc[i][s]
                    ep = cv if not pd.isna(cv) else p['ep']
                    slip_cost = 0
                comm = p['shares'] * commission_per_share
                total_slippage += slip_cost * p['shares']
                total_commissions += comm
                yearly_costs[year]['slippage'] += slip_cost * p['shares']
                yearly_costs[year]['commissions'] += comm
                yearly_costs[year]['trades'] += 1
                total_trades += 1
                cash += p['shares'] * ep - comm
                del positions[s]
            in_prot = True
            prot_stage = 1
            stop_day_idx = i

        # Regime
        is_ro = bool(regime.iloc[i]) if i < len(regime) else True

        # Leverage
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
                    lev = max(LEVERAGE_MIN, min(max_leverage, TARGET_VOL / rv)) if rv > 0.01 else max_leverage
                else:
                    lev = 1.0
            else:
                lev = 1.0

        # Margin cost
        if lev > 1.0 and (margin_spread is not None or fixed_margin_rate is not None):
            if fixed_margin_rate is not None:
                rate = fixed_margin_rate
            else:
                rate = FED_FUNDS_BY_YEAR.get(year, 0.04) + margin_spread
            borrowed = pv * (lev - 1) / lev
            daily_margin = rate / 252 * borrowed
            cash -= daily_margin
            total_margin_cost += daily_margin
            yearly_costs[year]['margin'] += daily_margin

        # Cash yield
        if cash > 0 and use_cash_yield:
            daily_yield = cash * (TBILL_YIELD_BY_ERA.get(year, 0.035) / 252)
            cash += daily_yield
            total_cash_yield += daily_yield
            yearly_costs[year]['cash_yield'] += daily_yield

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
                ep, slip_cost = exec_price(i, s, 'sell')
                if ep is None:
                    ep = cv
                    slip_cost = 0
                comm = p['shares'] * commission_per_share
                total_slippage += slip_cost * p['shares']
                total_commissions += comm
                yearly_costs[year]['slippage'] += slip_cost * p['shares']
                yearly_costs[year]['commissions'] += comm
                yearly_costs[year]['trades'] += 1
                total_trades += 1
                cash += p['shares'] * ep - comm
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
                    ep, slip_cost = exec_price(i, s, 'buy')
                    if ep is None:
                        continue
                    w = wts.get(s, 1.0 / len(sel))
                    pv_s = min(eff_cap * w, cash * 0.40)
                    sh = pv_s / ep
                    comm = sh * commission_per_share
                    cost = sh * ep + comm
                    total_slippage += slip_cost * sh
                    total_commissions += comm
                    yearly_costs[year]['slippage'] += slip_cost * sh
                    yearly_costs[year]['commissions'] += comm
                    yearly_costs[year]['trades'] += 1
                    total_trades += 1
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

    return {
        'label': label,
        'final': final,
        'cagr': cagr,
        'sharpe': sharpe,
        'max_dd': max_dd,
        'vol': vol,
        'total_trades': total_trades,
        'total_slippage': total_slippage,
        'total_commissions': total_commissions,
        'total_margin_cost': total_margin_cost,
        'total_cash_yield': total_cash_yield,
        'yearly_costs': yearly_costs,
        'pv_series': pv_series,
    }


# ============================================================================
# MAIN
# ============================================================================

if __name__ == "__main__":
    print("=" * 80)
    print("COST DECOMPOSITION ANALYSIS -- Where does every dollar go?")
    print("=" * 80)

    t0 = time_module.time()

    print("\n[1/3] Loading data...")
    price_data, spy_data = load_data()
    print(f"  Loaded {len(price_data)} symbols + SPY")

    print("[2/3] Building matrices...")
    all_dates, close_m, open_m, vol_m, spy_close = build_matrices(price_data, spy_data)
    print(f"  Matrix: {len(all_dates)} dates x {len(close_m.columns)} symbols")

    print("[3/3] Computing annual Top-40...")
    annual = compute_top40(close_m, vol_m, all_dates)

    # ====================================================================
    # Run variants: progressively adding costs
    # ====================================================================
    print("\n" + "=" * 80)
    print("RUNNING 8 COST VARIANTS")
    print("=" * 80)

    # Each tuple: (slip, comm, margin_spread, cash_yield, moc, label, max_lev, fixed_rate)
    variant_configs = [
        (0,   0.0,   None,  False, False, "1: Pure signal (Close[T], zero cost)",      2.0, None),
        (0,   0.0,   None,  False, True,  "2: + MOC execution (Close[T+1])",           2.0, None),
        (2,   0.0,   None,  False, True,  "3: + Slippage (2bps)",                      2.0, None),
        (2,   0.001, None,  False, True,  "4: + Commissions ($0.001/sh)",               2.0, None),
        (2,   0.001, 0.002, False, True,  "5: + Margin (Box SOFR+20bps)",              2.0, None),
        (2,   0.001, 0.002, True,  True,  "6: + Cash yield (T-Bill) = FULL BOX",       2.0, None),
        (2,   0.001, None,  True,  True,  "7: NO LEVERAGE (max 1.0x, no margin)",      1.0, None),
        (2,   0.001, None,  True,  True,  "8: FULL + Broker 6% (for comparison)",      2.0, 0.06),
    ]

    results = []
    for slip, comm, margin, cyield, moc, label, max_lev, fixed_rate in variant_configs:
        r = run_with_cost_tracking(
            close_m, open_m, spy_close, all_dates, annual,
            slippage_bps=slip, commission_per_share=comm,
            margin_spread=margin, use_cash_yield=cyield,
            use_moc=moc, label=label,
            max_leverage=max_lev, fixed_margin_rate=fixed_rate)
        results.append(r)
        print(f"    -> CAGR: {r['cagr']:.2%} | Sharpe: {r['sharpe']:.3f} | Final: ${r['final']:,.0f}")

    t_total = time_module.time() - t0

    # ====================================================================
    # RESULTS
    # ====================================================================
    print("\n" + "=" * 80)
    print("COST DECOMPOSITION RESULTS")
    print("=" * 80)

    print(f"\n  {'Variant':<45} {'CAGR':>8} {'Sharpe':>8} {'Final':>14}")
    print(f"  {'-'*78}")
    for r in results:
        print(f"  {r['label']:<45} {r['cagr']:>7.2%} {r['sharpe']:>8.3f} ${r['final']:>12,.0f}")

    # Incremental impact (first 6 = progressive cost addition)
    print(f"\n  {'='*78}")
    print(f"  INCREMENTAL IMPACT OF EACH COST COMPONENT")
    print(f"  {'='*78}")
    print(f"  {'Component':<45} {'CAGR Delta':>10} {'$ Impact':>14}")
    print(f"  {'-'*70}")

    components = [
        ("Pure signal alpha (Close[T], no costs)", results[0]['cagr'], results[0]['final']),
        ("MOC execution (Close[T] -> Close[T+1])", results[1]['cagr'] - results[0]['cagr'], results[1]['final'] - results[0]['final']),
        ("Slippage (2bps per side)", results[2]['cagr'] - results[1]['cagr'], results[2]['final'] - results[1]['final']),
        ("Commissions ($0.001/share)", results[3]['cagr'] - results[2]['cagr'], results[3]['final'] - results[2]['final']),
        ("Margin interest (Box SOFR+20bps)", results[4]['cagr'] - results[3]['cagr'], results[4]['final'] - results[3]['final']),
        ("Cash yield (T-Bill on idle cash)", results[5]['cagr'] - results[4]['cagr'], results[5]['final'] - results[4]['final']),
    ]

    for name, cagr_delta, dollar_impact in components:
        if name.startswith("Pure"):
            print(f"  {name:<45} {cagr_delta:>9.2%} ${dollar_impact:>12,.0f}")
        else:
            print(f"  {name:<45} {cagr_delta:>+9.2%} ${dollar_impact:>+12,.0f}")

    print(f"  {'-'*70}")
    print(f"  {'NET REALISTIC (MOC + Box Spread)':<45} {results[5]['cagr']:>9.2%} ${results[5]['final']:>12,.0f}")

    # ====================================================================
    # LEVERAGE ANALYSIS
    # ====================================================================
    no_lev = results[6]    # max 1.0x, no margin, with cash yield
    box_lev = results[5]   # full with Box Spread leverage
    broker_lev = results[7]  # full with Broker 6% leverage

    print(f"\n  {'='*78}")
    print(f"  LEVERAGE ANALYSIS -- Is borrowing worth it?")
    print(f"  {'='*78}")
    print(f"  {'Metric':<35} {'No Leverage':>15} {'Box Spread':>15} {'Broker 6%':>15}")
    print(f"  {'-'*82}")
    print(f"  {'Max leverage':<35} {'1.0x':>15} {'2.0x':>15} {'2.0x':>15}")
    print(f"  {'CAGR':<35} {no_lev['cagr']:>14.2%} {box_lev['cagr']:>14.2%} {broker_lev['cagr']:>14.2%}")
    print(f"  {'Sharpe':<35} {no_lev['sharpe']:>15.3f} {box_lev['sharpe']:>15.3f} {broker_lev['sharpe']:>15.3f}")
    print(f"  {'Max Drawdown':<35} {no_lev['max_dd']:>14.1%} {box_lev['max_dd']:>14.1%} {broker_lev['max_dd']:>14.1%}")
    print(f"  {'Final Value':<35} ${no_lev['final']:>14,.0f} ${box_lev['final']:>14,.0f} ${broker_lev['final']:>14,.0f}")
    print(f"  {'Margin cost':<35} ${'0':>14} ${box_lev['total_margin_cost']:>14,.0f} ${broker_lev['total_margin_cost']:>14,.0f}")
    print(f"  {'Cash yield':<35} ${no_lev['total_cash_yield']:>14,.0f} ${box_lev['total_cash_yield']:>14,.0f} ${broker_lev['total_cash_yield']:>14,.0f}")

    print(f"\n  LEVERAGE IMPACT:")
    lev_gain_box = box_lev['cagr'] - no_lev['cagr']
    lev_gain_broker = broker_lev['cagr'] - no_lev['cagr']
    print(f"  Leverage adds (Box):     {lev_gain_box:+.2%} CAGR ({no_lev['cagr']:.2%} -> {box_lev['cagr']:.2%})")
    print(f"  Leverage adds (Broker):  {lev_gain_broker:+.2%} CAGR ({no_lev['cagr']:.2%} -> {broker_lev['cagr']:.2%})")
    print(f"  Leverage cost (Box):     ${box_lev['total_margin_cost']:,.0f}")
    print(f"  Leverage cost (Broker):  ${broker_lev['total_margin_cost']:,.0f}")
    print(f"  Leverage extra DD (Box): {box_lev['max_dd'] - no_lev['max_dd']:+.1%}")

    if lev_gain_box > 0:
        print(f"\n  VERDICT: Leverage IS worth it with Box Spread financing")
        print(f"    +{lev_gain_box:.2%} CAGR for ${box_lev['total_margin_cost']:,.0f} in interest")
        print(f"    ${box_lev['final'] - no_lev['final']:+,.0f} extra final value")
    else:
        print(f"\n  VERDICT: Leverage is NOT worth it -- costs exceed gains")

    if lev_gain_broker > 0:
        print(f"  With Broker 6%: leverage adds +{lev_gain_broker:.2%} CAGR but costs ${broker_lev['total_margin_cost']:,.0f}")
    else:
        print(f"  With Broker 6%: leverage DESTROYS value ({lev_gain_broker:+.2%} CAGR)")
        print(f"    Better to run at 1.0x max and skip margin entirely")

    # Absolute cost totals for the FULL variant
    full = results[5]
    print(f"\n  {'='*78}")
    print(f"  ABSOLUTE COST TOTALS (full variant: MOC + Box Spread)")
    print(f"  {'='*78}")
    print(f"  {'Cost Component':<35} {'Total $':>14} {'Per Trade':>12} {'Annual Avg':>12}")
    print(f"  {'-'*75}")

    n_years = len(all_dates) / 252
    n_trades = max(full['total_trades'], 1)

    print(f"  {'Slippage (2bps MOC)':<35} ${full['total_slippage']:>13,.0f} "
          f"${full['total_slippage']/n_trades:>11,.2f} "
          f"${full['total_slippage']/n_years:>11,.0f}")
    print(f"  {'Commissions ($0.001/sh)':<35} ${full['total_commissions']:>13,.0f} "
          f"${full['total_commissions']/n_trades:>11,.2f} "
          f"${full['total_commissions']/n_years:>11,.0f}")
    print(f"  {'Margin interest (Box+20bps)':<35} ${full['total_margin_cost']:>13,.0f} "
          f"${full['total_margin_cost']/n_trades:>11,.2f} "
          f"${full['total_margin_cost']/n_years:>11,.0f}")
    total_costs = full['total_slippage'] + full['total_commissions'] + full['total_margin_cost']
    print(f"  {'-'*75}")
    print(f"  {'TOTAL COSTS (paid)':<35} ${total_costs:>13,.0f} "
          f"${total_costs/n_trades:>11,.2f} "
          f"${total_costs/n_years:>11,.0f}")
    print(f"  {'Cash yield (earned)':<35} ${full['total_cash_yield']:>13,.0f} "
          f"${full['total_cash_yield']/n_trades:>11,.2f} "
          f"${full['total_cash_yield']/n_years:>11,.0f}")
    net_costs = total_costs - full['total_cash_yield']
    print(f"  {'NET COSTS (paid - earned)':<35} ${net_costs:>13,.0f} "
          f"${net_costs/n_trades:>11,.2f} "
          f"${net_costs/n_years:>11,.0f}")

    # Broker 6% comparison is now variant #8
    box = results[5]   # Full Box Spread
    broker = results[7]  # Full Broker 6%

    print(f"\n  {'='*78}")
    print(f"  COMPARISON: BOX SPREAD vs BROKER 6%")
    print(f"  {'='*78}")
    print(f"  {'Metric':<35} {'Broker 6%':>15} {'Box SOFR+20bp':>15} {'Savings':>12}")
    print(f"  {'-'*80}")
    print(f"  {'CAGR':<35} {broker['cagr']:>14.2%} {box['cagr']:>14.2%} {box['cagr']-broker['cagr']:>+11.2%}")
    print(f"  {'Sharpe':<35} {broker['sharpe']:>15.3f} {box['sharpe']:>15.3f} {box['sharpe']-broker['sharpe']:>+12.3f}")
    print(f"  {'Margin cost total':<35} ${broker['total_margin_cost']:>14,.0f} ${box['total_margin_cost']:>14,.0f} ${broker['total_margin_cost']-box['total_margin_cost']:>11,.0f}")
    print(f"  {'Final value':<35} ${broker['final']:>14,.0f} ${box['final']:>14,.0f} ${box['final']-broker['final']:>+11,.0f}")

    # Year-by-year costs
    print(f"\n  {'='*78}")
    print(f"  YEAR-BY-YEAR COST BREAKDOWN (Box Spread variant)")
    print(f"  {'='*78}")
    print(f"  {'Year':<6} {'Slippage':>10} {'Commiss':>10} {'Margin':>10} "
          f"{'CashYld':>10} {'NetCost':>10} {'Trades':>8}")
    print(f"  {'-'*68}")

    for year in sorted(full['yearly_costs'].keys()):
        yc = full['yearly_costs'][year]
        net = yc['slippage'] + yc['commissions'] + yc['margin'] - yc['cash_yield']
        print(f"  {year:<6} ${yc['slippage']:>9,.0f} ${yc['commissions']:>9,.0f} "
              f"${yc['margin']:>9,.0f} ${yc['cash_yield']:>9,.0f} ${net:>9,.0f} "
              f"{yc['trades']:>8}")

    # Summary
    print(f"\n  {'='*78}")
    print(f"  FINAL SUMMARY -- COST WATERFALL")
    print(f"  {'='*78}")
    print(f"  Pure signal alpha:          {results[0]['cagr']:.2%} CAGR (ideal, no costs)")
    print(f"  After MOC execution:        {results[1]['cagr']:.2%} CAGR (overnight gap: {results[1]['cagr']-results[0]['cagr']:+.2%})")
    print(f"  After slippage (2bps):      {results[2]['cagr']:.2%} CAGR (slippage: {results[2]['cagr']-results[1]['cagr']:+.2%})")
    print(f"  After commissions:          {results[3]['cagr']:.2%} CAGR (commissions: {results[3]['cagr']-results[2]['cagr']:+.2%})")
    print(f"  After Box Spread margin:    {results[4]['cagr']:.2%} CAGR (margin: {results[4]['cagr']-results[3]['cagr']:+.2%})")
    print(f"  After cash yield:           {results[5]['cagr']:.2%} CAGR (cash yield: {results[5]['cagr']-results[4]['cagr']:+.2%})")
    print(f"\n  Total friction:             {results[5]['cagr']-results[0]['cagr']:+.2%} CAGR")
    print(f"  Signal retention:           {results[5]['cagr']/results[0]['cagr']*100:.1f}% of pure alpha captured")

    print(f"\n  {'='*78}")
    print(f"  LEVERAGE DECISION MATRIX")
    print(f"  {'='*78}")
    print(f"  {'Option':<40} {'CAGR':>8} {'Sharpe':>8} {'MaxDD':>8} {'Final':>14}")
    print(f"  {'-'*80}")
    print(f"  {'No leverage (1.0x max)':<40} {no_lev['cagr']:>7.2%} {no_lev['sharpe']:>8.3f} {no_lev['max_dd']:>7.1%} ${no_lev['final']:>12,.0f}")
    print(f"  {'Leverage + Box Spread (SOFR+20bp)':<40} {box_lev['cagr']:>7.2%} {box_lev['sharpe']:>8.3f} {box_lev['max_dd']:>7.1%} ${box_lev['final']:>12,.0f}")
    print(f"  {'Leverage + Broker 6%':<40} {broker_lev['cagr']:>7.2%} {broker_lev['sharpe']:>8.3f} {broker_lev['max_dd']:>7.1%} ${broker_lev['final']:>12,.0f}")

    print(f"\n  Total time: {t_total:.0f}s")

    # Save
    os.makedirs('backtests', exist_ok=True)
    comp = pd.DataFrame([{
        'variant': r['label'],
        'cagr_pct': round(r['cagr'] * 100, 2),
        'sharpe': round(r['sharpe'], 3),
        'final_value': round(r['final'], 0),
        'total_slippage': round(r['total_slippage'], 0),
        'total_commissions': round(r['total_commissions'], 0),
        'total_margin': round(r['total_margin_cost'], 0),
        'total_cash_yield': round(r['total_cash_yield'], 0),
        'total_trades': r['total_trades'],
    } for r in results])
    comp.to_csv('backtests/cost_decomposition.csv', index=False)
    print(f"\n  Saved: backtests/cost_decomposition.csv")

    print("\n" + "=" * 80)
    print("COST DECOMPOSITION COMPLETE")
    print("=" * 80)
