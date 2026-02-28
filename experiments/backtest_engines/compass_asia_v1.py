"""
COMPASS Asia v1 — Asian Large-Cap Momentum Backtest
==================================================================================
Experiment #32: Apply the EXACT COMPASS v8.2 algorithm (locked, no changes) to an
Asian stock universe (~100 large-caps from Japan, Hong Kong, Australia, South Korea,
Taiwan, Singapore) with ^N225 (Nikkei 225) as regime filter.

Only differences vs omnicapital_v8_compass.py:
  1. BROAD_POOL -> ~100 Asian large-caps (6 markets)
  2. Regime filter: ^N225 (Nikkei 225) replaces SPY
     - ^N225 data from 1990 -> full 2000-2026 coverage
  3. No pence fix needed (no GBP-denominated market)
  4. Cache/output file names use 'asia_' prefix
  5. Comparison section vs COMPASS US

ALL PARAMETERS ARE IDENTICAL TO COMPASS v8.2. ZERO ALGORITHMIC CHANGES.
"""

import pandas as pd
import numpy as np
import yfinance as yf
from datetime import datetime, timedelta
import pickle
import os
from typing import Dict, List, Tuple, Optional
import warnings
warnings.filterwarnings('ignore')

# ============================================================================
# PARAMETROS (IDENTICAL TO COMPASS v8.2 -- DO NOT MODIFY)
# ============================================================================

# Universe
TOP_N = 40
MIN_AGE_DAYS = 63

# Signal
MOMENTUM_LOOKBACK = 90
MOMENTUM_SKIP = 5
MIN_MOMENTUM_STOCKS = 20

# Regime
REGIME_SMA_PERIOD = 200
REGIME_CONFIRM_DAYS = 3

# Positions
NUM_POSITIONS = 5
NUM_POSITIONS_RISK_OFF = 2
HOLD_DAYS = 5

# Position-level risk
POSITION_STOP_LOSS = -0.08
TRAILING_ACTIVATION = 0.05
TRAILING_STOP_PCT = 0.03

# Portfolio-level risk
PORTFOLIO_STOP_LOSS = -0.15

# Recovery stages
RECOVERY_STAGE_1_DAYS = 63
RECOVERY_STAGE_2_DAYS = 126

# Leverage & Vol targeting
TARGET_VOL = 0.15
LEVERAGE_MIN = 0.3
LEVERAGE_MAX = 1.0
VOL_LOOKBACK = 20

# Costs
INITIAL_CAPITAL = 100_000
MARGIN_RATE = 0.06
COMMISSION_PER_SHARE = 0.001
CASH_YIELD_RATE = 0.035

# Data
START_DATE = '2000-01-01'  # ^N225 has data from 1990 -> full period
END_DATE = '2026-02-09'

# Regime index
REGIME_INDEX = '^N225'  # Nikkei 225 (Japan, largest Asian market)

# Asian broad pool (~100 large-caps, 6 markets)
BROAD_POOL = [
    # ============================================================
    # JAPAN (.T) — 40 stocks
    # ============================================================
    # Tech / Electronics
    '6758.T',   # Sony
    '6861.T',   # Keyence
    '6902.T',   # Denso
    '6501.T',   # Hitachi
    '6594.T',   # Nidec
    '6971.T',   # Kyocera
    '6752.T',   # Panasonic
    '4063.T',   # Shin-Etsu Chemical
    '6723.T',   # Renesas
    '6857.T',   # Advantest

    # Autos
    '7203.T',   # Toyota
    '7267.T',   # Honda
    '7269.T',   # Suzuki
    '7201.T',   # Nissan

    # Financials
    '8306.T',   # MUFG
    '8316.T',   # Sumitomo Mitsui
    '8411.T',   # Mizuho
    '8766.T',   # Tokio Marine
    '8591.T',   # ORIX

    # Pharma / Healthcare
    '4502.T',   # Takeda
    '4568.T',   # Daiichi Sankyo
    '4519.T',   # Chugai
    '4503.T',   # Astellas
    '4523.T',   # Eisai

    # Consumer / Retail
    '9983.T',   # Fast Retailing (Uniqlo)
    '9984.T',   # SoftBank Group
    '2914.T',   # Japan Tobacco
    '4452.T',   # Kao
    '3382.T',   # Seven & i

    # Industrials
    '6301.T',   # Komatsu
    '7011.T',   # Mitsubishi Heavy
    '7751.T',   # Canon
    '6503.T',   # Mitsubishi Electric
    '8001.T',   # ITOCHU
    '8058.T',   # Mitsubishi Corp
    '8031.T',   # Mitsui & Co

    # Materials / Energy
    '5020.T',   # ENEOS
    '5401.T',   # Nippon Steel
    '4005.T',   # Sumitomo Chemical
    '8035.T',   # Tokyo Electron

    # ============================================================
    # HONG KONG (.HK) — 20 stocks
    # ============================================================
    '0005.HK',  # HSBC
    '0700.HK',  # Tencent
    '9988.HK',  # Alibaba
    '1299.HK',  # AIA Group
    '0941.HK',  # China Mobile
    '0388.HK',  # HKEX
    '0883.HK',  # CNOOC
    '2318.HK',  # Ping An
    '0027.HK',  # Galaxy Entertainment
    '1928.HK',  # Sands China
    '0016.HK',  # Sun Hung Kai Properties
    '0001.HK',  # CK Hutchison
    '0011.HK',  # Hang Seng Bank
    '0002.HK',  # CLP Holdings
    '0003.HK',  # HK & China Gas
    '0006.HK',  # Power Assets
    '0066.HK',  # MTR Corp
    '0012.HK',  # Henderson Land
    '1038.HK',  # CK Infrastructure
    '0267.HK',  # CITIC Pacific

    # ============================================================
    # AUSTRALIA (.AX) — 18 stocks
    # ============================================================
    'BHP.AX',   # BHP
    'CBA.AX',   # Commonwealth Bank
    'CSL.AX',   # CSL Ltd
    'NAB.AX',   # National Australia Bank
    'WBC.AX',   # Westpac
    'ANZ.AX',   # ANZ Banking
    'WES.AX',   # Wesfarmers
    'WOW.AX',   # Woolworths
    'MQG.AX',   # Macquarie Group
    'RIO.AX',   # Rio Tinto
    'FMG.AX',   # Fortescue Metals
    'TLS.AX',   # Telstra
    'WDS.AX',   # Woodside Energy
    'ALL.AX',   # Aristocrat Leisure
    'STO.AX',   # Santos
    'GMG.AX',   # Goodman Group
    'TCL.AX',   # Transurban
    'COL.AX',   # Coles Group

    # ============================================================
    # SOUTH KOREA (.KS) — 12 stocks
    # ============================================================
    '005930.KS', # Samsung Electronics
    '000660.KS', # SK Hynix
    '051910.KS', # LG Chem
    '006400.KS', # Samsung SDI
    '035420.KS', # NAVER
    '005380.KS', # Hyundai Motor
    '055550.KS', # Shinhan Financial
    '105560.KS', # KB Financial
    '012330.KS', # Hyundai Mobis
    '068270.KS', # Celltrion
    '035720.KS', # Kakao
    '003550.KS', # LG

    # ============================================================
    # TAIWAN (.TW) — 8 stocks
    # ============================================================
    '2330.TW',   # TSMC
    '2317.TW',   # Hon Hai (Foxconn)
    '2454.TW',   # MediaTek
    '2881.TW',   # Fubon Financial
    '2882.TW',   # Cathay Financial
    '1303.TW',   # Nan Ya Plastics
    '2308.TW',   # Delta Electronics
    '1301.TW',   # Formosa Plastics

    # ============================================================
    # SINGAPORE (.SI) — 5 stocks
    # ============================================================
    'D05.SI',    # DBS Group
    'O39.SI',    # OCBC
    'U11.SI',    # UOB
    'Z74.SI',    # Singapore Telecom
    'C38U.SI',   # CapitaLand Integrated
]

print("=" * 80)
print("COMPASS ASIA v1 — Asian Large-Cap Momentum")
print("Experiment #32: COMPASS v8.2 engine applied to Asian universe")
print("=" * 80)
print(f"\nBroad pool: {len(BROAD_POOL)} Asian stocks | Top-{TOP_N} annual rotation")
print(f"  Japan (.T): 40 | Hong Kong (.HK): 20 | Australia (.AX): 18")
print(f"  South Korea (.KS): 12 | Taiwan (.TW): 8 | Singapore (.SI): 5")
print(f"Signal: Momentum {MOMENTUM_LOOKBACK}d (skip {MOMENTUM_SKIP}d) + Inverse Vol sizing")
print(f"Regime: Nikkei 225 SMA{REGIME_SMA_PERIOD} | Vol target: {TARGET_VOL:.0%}")
print(f"Hold: {HOLD_DAYS}d | Pos stop: {POSITION_STOP_LOSS:.0%} | Port stop: {PORTFOLIO_STOP_LOSS:.0%}")
print(f"Period: {START_DATE} to {END_DATE}")
print()


# ============================================================================
# DATA FUNCTIONS
# ============================================================================

def download_asia_pool() -> Dict[str, pd.DataFrame]:
    """Download/load cached data for the Asian broad pool."""
    cache_file = f'data_cache/asia_broad_pool_{START_DATE}_{END_DATE}.pkl'

    if os.path.exists(cache_file):
        print("[Cache] Loading Asian broad pool data...")
        try:
            with open(cache_file, 'rb') as f:
                return pickle.load(f)
        except Exception:
            print("[Cache] Failed to load, re-downloading...")

    print(f"[Download] Downloading {len(BROAD_POOL)} Asian symbols...")
    data = {}
    failed = []

    for i, symbol in enumerate(BROAD_POOL):
        try:
            df = yf.download(symbol, start=START_DATE, end=END_DATE, progress=False)
            if not df.empty and len(df) > 100:
                df.columns = [c[0] if isinstance(c, tuple) else c for c in df.columns]
                data[symbol] = df
                if (i + 1) % 20 == 0:
                    print(f"  [{i+1}/{len(BROAD_POOL)}] Downloaded {len(data)} symbols...")
            else:
                failed.append(symbol)
        except Exception:
            failed.append(symbol)

    print(f"[Download] {len(data)} symbols valid, {len(failed)} failed")
    if failed:
        print(f"  Failed: {failed}")

    os.makedirs('data_cache', exist_ok=True)
    with open(cache_file, 'wb') as f:
        pickle.dump(data, f)

    return data


def download_regime_index() -> pd.DataFrame:
    """Download Nikkei 225 index for regime filter."""
    cache_file = f'data_cache/N225_{START_DATE}_{END_DATE}.csv'

    if os.path.exists(cache_file):
        print("[Cache] Loading Nikkei 225 data...")
        df = pd.read_csv(cache_file, index_col=0, parse_dates=True)
        return df

    print(f"[Download] Downloading {REGIME_INDEX}...")
    df = yf.download(REGIME_INDEX, start=START_DATE, end=END_DATE, progress=False)
    df.columns = [c[0] if isinstance(c, tuple) else c for c in df.columns]

    os.makedirs('data_cache', exist_ok=True)
    df.to_csv(cache_file)
    return df


def compute_annual_top40(price_data: Dict[str, pd.DataFrame]) -> Dict[int, List[str]]:
    """For each year, compute top-40 by avg daily dollar volume (prior year data).
    Uses raw local currency Close*Volume (multi-currency, no conversion)."""
    all_dates = set()
    for df in price_data.values():
        all_dates.update(df.index)
    all_dates = sorted(list(all_dates))
    years = sorted(set(d.year for d in all_dates))

    annual_universe = {}

    for year in years:
        if year == years[0]:
            ranking_end = pd.Timestamp(f'{year}-02-01', tz=all_dates[0].tz if hasattr(all_dates[0], 'tz') and all_dates[0].tz else None)
            ranking_start = pd.Timestamp(f'{year-1}-01-01', tz=all_dates[0].tz if hasattr(all_dates[0], 'tz') and all_dates[0].tz else None)
        else:
            ranking_end = pd.Timestamp(f'{year}-01-01', tz=all_dates[0].tz if hasattr(all_dates[0], 'tz') and all_dates[0].tz else None)
            ranking_start = pd.Timestamp(f'{year-1}-01-01', tz=all_dates[0].tz if hasattr(all_dates[0], 'tz') and all_dates[0].tz else None)

        scores = {}
        for symbol, df in price_data.items():
            mask = (df.index >= ranking_start) & (df.index < ranking_end)
            window = df.loc[mask]
            if len(window) < 20:
                continue
            dollar_vol = (window['Close'] * window['Volume']).mean()
            scores[symbol] = dollar_vol

        ranked = sorted(scores.items(), key=lambda x: x[1], reverse=True)
        top_n = [s for s, _ in ranked[:TOP_N]]
        annual_universe[year] = top_n

        if year > years[0] and year - 1 in annual_universe:
            prev = set(annual_universe[year - 1])
            curr = set(top_n)
            added = curr - prev
            removed = prev - curr
            if added or removed:
                print(f"  {year}: Top-{TOP_N} | +{len(added)} added, -{len(removed)} removed")
        else:
            print(f"  {year}: Initial top-{TOP_N} = {len(top_n)} stocks")

    return annual_universe


# ============================================================================
# SIGNAL & REGIME FUNCTIONS (IDENTICAL LOGIC)
# ============================================================================

def compute_regime(regime_data: pd.DataFrame) -> pd.Series:
    """
    Compute market regime based on Nikkei 225 vs SMA200.
    Returns Series: True = RISK_ON, False = RISK_OFF.
    Requires REGIME_CONFIRM_DAYS consecutive days to switch.
    """
    regime_close = regime_data['Close']
    sma200 = regime_close.rolling(REGIME_SMA_PERIOD).mean()

    raw_signal = regime_close > sma200

    regime = pd.Series(index=regime_close.index, dtype=bool)
    regime.iloc[:REGIME_SMA_PERIOD] = True  # Default RISK_ON until enough data

    current_regime = True
    consecutive_count = 0
    last_raw = True

    for i in range(REGIME_SMA_PERIOD, len(raw_signal)):
        raw = raw_signal.iloc[i]
        if pd.isna(raw):
            regime.iloc[i] = current_regime
            continue

        if raw == last_raw:
            consecutive_count += 1
        else:
            consecutive_count = 1
            last_raw = raw

        if raw != current_regime and consecutive_count >= REGIME_CONFIRM_DAYS:
            current_regime = raw
        regime.iloc[i] = current_regime

    return regime


def compute_momentum_scores(price_data: Dict[str, pd.DataFrame],
                           tradeable: List[str],
                           date: pd.Timestamp,
                           all_dates: List[pd.Timestamp],
                           date_idx: int) -> Dict[str, float]:
    """Compute cross-sectional momentum score. IDENTICAL to COMPASS v8.2."""
    scores = {}

    for symbol in tradeable:
        if symbol not in price_data:
            continue
        df = price_data[symbol]
        if date not in df.index:
            continue

        needed = MOMENTUM_LOOKBACK + MOMENTUM_SKIP
        try:
            sym_idx = df.index.get_loc(date)
        except KeyError:
            continue

        if sym_idx < needed:
            continue

        close_today = df['Close'].iloc[sym_idx]
        close_skip = df['Close'].iloc[sym_idx - MOMENTUM_SKIP]
        close_lookback = df['Close'].iloc[sym_idx - MOMENTUM_LOOKBACK]

        if close_lookback <= 0 or close_skip <= 0 or close_today <= 0:
            continue

        momentum_90d = (close_skip / close_lookback) - 1.0
        skip_5d = (close_today / close_skip) - 1.0
        score = momentum_90d - skip_5d
        scores[symbol] = score

    return scores


def compute_volatility_weights(price_data: Dict[str, pd.DataFrame],
                               selected: List[str],
                               date: pd.Timestamp) -> Dict[str, float]:
    """Compute inverse-volatility weights. IDENTICAL to COMPASS v8.2."""
    vols = {}

    for symbol in selected:
        if symbol not in price_data:
            continue
        df = price_data[symbol]
        if date not in df.index:
            continue

        sym_idx = df.index.get_loc(date)
        if sym_idx < VOL_LOOKBACK + 1:
            continue

        returns = df['Close'].iloc[sym_idx - VOL_LOOKBACK:sym_idx + 1].pct_change().dropna()
        if len(returns) < VOL_LOOKBACK - 2:
            continue

        vol = returns.std() * np.sqrt(252)
        if vol > 0.01:
            vols[symbol] = vol

    if not vols:
        return {s: 1.0 / len(selected) for s in selected}

    raw_weights = {s: 1.0 / v for s, v in vols.items()}
    total = sum(raw_weights.values())
    return {s: w / total for s, w in raw_weights.items()}


def compute_dynamic_leverage(regime_data: pd.DataFrame, date: pd.Timestamp) -> float:
    """Compute leverage via vol targeting using Nikkei 225 as proxy. IDENTICAL logic."""
    if date not in regime_data.index:
        return 1.0

    idx = regime_data.index.get_loc(date)
    if idx < VOL_LOOKBACK + 1:
        return 1.0

    returns = regime_data['Close'].iloc[idx - VOL_LOOKBACK:idx + 1].pct_change().dropna()
    if len(returns) < VOL_LOOKBACK - 2:
        return 1.0

    realized_vol = returns.std() * np.sqrt(252)
    if realized_vol < 0.01:
        return LEVERAGE_MAX

    leverage = TARGET_VOL / realized_vol
    return max(LEVERAGE_MIN, min(LEVERAGE_MAX, leverage))


# ============================================================================
# BACKTEST (IDENTICAL ENGINE)
# ============================================================================

def get_tradeable_symbols(price_data: Dict[str, pd.DataFrame],
                         date: pd.Timestamp,
                         first_date: pd.Timestamp,
                         annual_universe: Dict[int, List[str]]) -> List[str]:
    """Return tradeable symbols from top-40 for that year."""
    eligible = set(annual_universe.get(date.year, []))
    tradeable = []
    for symbol in eligible:
        if symbol not in price_data:
            continue
        df = price_data[symbol]
        if date not in df.index:
            continue
        symbol_first_date = df.index[0]
        days_since_start = (date - symbol_first_date).days
        if date <= first_date + timedelta(days=30):
            tradeable.append(symbol)
        elif days_since_start >= MIN_AGE_DAYS:
            tradeable.append(symbol)
    return tradeable


def run_backtest(price_data: Dict[str, pd.DataFrame],
                 annual_universe: Dict[int, List[str]],
                 regime_data: pd.DataFrame) -> Dict:
    """Run COMPASS Asia backtest. Engine IDENTICAL to v8.2."""

    print("\n" + "=" * 80)
    print("RUNNING COMPASS ASIA BACKTEST")
    print("=" * 80)

    # Get all trading dates from stock data
    all_dates = set()
    for df in price_data.values():
        all_dates.update(df.index)
    all_dates = sorted(list(all_dates))
    first_date = all_dates[0]

    # Compute regime from Nikkei 225
    print("\nComputing market regime (Nikkei 225 vs SMA200)...")
    regime = compute_regime(regime_data)

    print(f"Period: {all_dates[0].strftime('%Y-%m-%d')} to {all_dates[-1].strftime('%Y-%m-%d')}")
    print(f"Trading days: {len(all_dates)}")
    print(f"Regime index data: {regime_data.index[0].strftime('%Y-%m-%d')} to {regime_data.index[-1].strftime('%Y-%m-%d')}")

    # Portfolio state
    cash = float(INITIAL_CAPITAL)
    positions = {}
    portfolio_values = []
    trades = []
    stop_events = []

    peak_value = float(INITIAL_CAPITAL)
    in_protection_mode = False
    protection_stage = 0
    stop_loss_day_index = None
    post_stop_base = None

    risk_on_days = 0
    risk_off_days = 0

    current_year = None

    for i, date in enumerate(all_dates):
        if date.year != current_year:
            current_year = date.year

        tradeable_symbols = get_tradeable_symbols(price_data, date, first_date, annual_universe)

        # --- Calculate portfolio value ---
        portfolio_value = cash
        for symbol, pos in list(positions.items()):
            if symbol in price_data and date in price_data[symbol].index:
                price = price_data[symbol].loc[date, 'Close']
                portfolio_value += pos['shares'] * price

        # --- Update peak ---
        if portfolio_value > peak_value and not in_protection_mode:
            peak_value = portfolio_value

        # --- Check recovery from protection mode ---
        if in_protection_mode and stop_loss_day_index is not None:
            days_since_stop = i - stop_loss_day_index
            is_regime_on = True
            if date in regime.index:
                is_regime_on = bool(regime.loc[date])

            if protection_stage == 1 and days_since_stop >= RECOVERY_STAGE_1_DAYS and is_regime_on:
                protection_stage = 2
                print(f"  [RECOVERY S1] {date.strftime('%Y-%m-%d')}: Stage 2 | Value: ${portfolio_value:,.0f}")

            if protection_stage == 2 and days_since_stop >= RECOVERY_STAGE_2_DAYS and is_regime_on:
                in_protection_mode = False
                protection_stage = 0
                peak_value = portfolio_value
                stop_loss_day_index = None
                post_stop_base = None
                print(f"  [RECOVERY S2] {date.strftime('%Y-%m-%d')}: Full recovery | Value: ${portfolio_value:,.0f}")

        # --- Drawdown ---
        drawdown = (portfolio_value - peak_value) / peak_value if peak_value > 0 else 0

        # --- Portfolio stop loss ---
        if drawdown <= PORTFOLIO_STOP_LOSS and not in_protection_mode:
            stop_events.append({
                'date': date,
                'portfolio_value': portfolio_value,
                'drawdown': drawdown
            })
            print(f"\n  [STOP LOSS] {date.strftime('%Y-%m-%d')}: DD {drawdown:.1%} | Value: ${portfolio_value:,.0f}")

            for symbol in list(positions.keys()):
                if symbol in price_data and date in price_data[symbol].index:
                    exit_price = price_data[symbol].loc[date, 'Close']
                    pos = positions[symbol]
                    proceeds = pos['shares'] * exit_price
                    commission = pos['shares'] * COMMISSION_PER_SHARE
                    cash += proceeds - commission
                    pnl = (exit_price - pos['entry_price']) * pos['shares'] - commission
                    trades.append({
                        'symbol': symbol,
                        'entry_date': pos['entry_date'],
                        'exit_date': date,
                        'exit_reason': 'portfolio_stop',
                        'pnl': pnl,
                        'return': pnl / (pos['entry_price'] * pos['shares'])
                    })
                del positions[symbol]

            in_protection_mode = True
            protection_stage = 1
            stop_loss_day_index = i
            post_stop_base = cash

        # --- Regime ---
        is_risk_on = True
        if date in regime.index:
            is_risk_on = bool(regime.loc[date])
        if is_risk_on:
            risk_on_days += 1
        else:
            risk_off_days += 1

        # --- Determine max positions and leverage ---
        if in_protection_mode:
            if protection_stage == 1:
                max_positions = 2
                current_leverage = 0.3
            else:
                max_positions = 3
                current_leverage = 1.0
        elif not is_risk_on:
            max_positions = NUM_POSITIONS_RISK_OFF
            current_leverage = 1.0
        else:
            max_positions = NUM_POSITIONS
            current_leverage = compute_dynamic_leverage(regime_data, date)

        # --- Daily costs ---
        if current_leverage > 1.0:
            borrowed = portfolio_value * (current_leverage - 1) / current_leverage
            daily_margin = MARGIN_RATE / 252 * borrowed
            cash -= daily_margin

        # --- Cash yield ---
        if cash > 0:
            cash += cash * (CASH_YIELD_RATE / 252)

        # --- Close positions ---
        for symbol in list(positions.keys()):
            pos = positions[symbol]
            if symbol not in price_data or date not in price_data[symbol].index:
                continue

            current_price = price_data[symbol].loc[date, 'Close']
            exit_reason = None

            days_held = i - pos['entry_idx']
            if days_held >= HOLD_DAYS:
                exit_reason = 'hold_expired'

            pos_return = (current_price - pos['entry_price']) / pos['entry_price']
            if pos_return <= POSITION_STOP_LOSS:
                exit_reason = 'position_stop'

            if current_price > pos['high_price']:
                pos['high_price'] = current_price
            if pos['high_price'] > pos['entry_price'] * (1 + TRAILING_ACTIVATION):
                trailing_level = pos['high_price'] * (1 - TRAILING_STOP_PCT)
                if current_price <= trailing_level:
                    exit_reason = 'trailing_stop'

            if symbol not in tradeable_symbols:
                exit_reason = 'universe_rotation'

            if exit_reason is None and len(positions) > max_positions:
                pos_returns = {}
                for s, p in positions.items():
                    if s in price_data and date in price_data[s].index:
                        cp = price_data[s].loc[date, 'Close']
                        pos_returns[s] = (cp - p['entry_price']) / p['entry_price']
                worst = min(pos_returns, key=pos_returns.get)
                if symbol == worst:
                    exit_reason = 'regime_reduce'

            if exit_reason:
                shares = pos['shares']
                proceeds = shares * current_price
                commission = shares * COMMISSION_PER_SHARE
                cash += proceeds - commission
                pnl = (current_price - pos['entry_price']) * shares - commission
                trades.append({
                    'symbol': symbol,
                    'entry_date': pos['entry_date'],
                    'exit_date': date,
                    'exit_reason': exit_reason,
                    'pnl': pnl,
                    'return': pnl / (pos['entry_price'] * shares)
                })
                del positions[symbol]

        # --- Open new positions ---
        needed = max_positions - len(positions)

        if needed > 0 and cash > 1000 and len(tradeable_symbols) >= 5:
            scores = compute_momentum_scores(price_data, tradeable_symbols, date, all_dates, i)
            available_scores = {s: sc for s, sc in scores.items() if s not in positions}

            if len(available_scores) >= needed:
                ranked = sorted(available_scores.items(), key=lambda x: x[1], reverse=True)
                selected = [s for s, _ in ranked[:needed]]
                weights = compute_volatility_weights(price_data, selected, date)
                effective_capital = cash * current_leverage * 0.95

                for symbol in selected:
                    if symbol not in price_data or date not in price_data[symbol].index:
                        continue

                    entry_price = price_data[symbol].loc[date, 'Close']
                    if entry_price <= 0:
                        continue

                    weight = weights.get(symbol, 1.0 / len(selected))
                    position_value = effective_capital * weight
                    max_per_position = cash * 0.40
                    position_value = min(position_value, max_per_position)

                    shares = position_value / entry_price
                    cost = shares * entry_price
                    commission = shares * COMMISSION_PER_SHARE

                    if cost + commission <= cash * 0.90:
                        positions[symbol] = {
                            'entry_price': entry_price,
                            'shares': shares,
                            'entry_date': date,
                            'entry_idx': i,
                            'high_price': entry_price,
                        }
                        cash -= cost + commission

        # --- Record daily snapshot ---
        portfolio_values.append({
            'date': date,
            'value': portfolio_value,
            'cash': cash,
            'positions': len(positions),
            'drawdown': drawdown,
            'leverage': current_leverage,
            'in_protection': in_protection_mode,
            'risk_on': is_risk_on,
            'universe_size': len(tradeable_symbols)
        })

        # Annual progress log
        if i % 252 == 0 and i > 0:
            year_num = i // 252
            regime_str = "RISK_ON" if is_risk_on else "RISK_OFF"
            prot_str = f" [PROTECTION S{protection_stage}]" if in_protection_mode else ""
            print(f"  Year {year_num}: ${portfolio_value:,.0f} | DD: {drawdown:.1%} | "
                  f"Lev: {current_leverage:.2f}x | {regime_str}{prot_str} | "
                  f"Pos: {len(positions)}")

    return {
        'portfolio_values': pd.DataFrame(portfolio_values),
        'trades': pd.DataFrame(trades) if trades else pd.DataFrame(),
        'stop_events': pd.DataFrame(stop_events) if stop_events else pd.DataFrame(),
        'final_value': portfolio_values[-1]['value'] if portfolio_values else INITIAL_CAPITAL,
        'annual_universe': annual_universe,
        'risk_on_days': risk_on_days,
        'risk_off_days': risk_off_days,
    }


# ============================================================================
# METRICS (IDENTICAL)
# ============================================================================

def calculate_metrics(results: Dict) -> Dict:
    """Calculate performance metrics. IDENTICAL to COMPASS v8.2."""
    df = results['portfolio_values'].set_index('date')
    trades_df = results['trades']
    stop_df = results['stop_events']

    initial = INITIAL_CAPITAL
    final_value = df['value'].iloc[-1]

    years = len(df) / 252
    cagr = (final_value / initial) ** (1 / years) - 1

    returns = df['value'].pct_change().dropna()
    volatility = returns.std() * np.sqrt(252)

    max_dd = df['drawdown'].min()

    sharpe = cagr / volatility if volatility > 0 else 0
    calmar = cagr / abs(max_dd) if max_dd != 0 else 0

    downside = returns[returns < 0]
    downside_vol = downside.std() * np.sqrt(252) if len(downside) > 0 else volatility
    sortino = cagr / downside_vol if downside_vol > 0 else 0

    win_rate = (trades_df['pnl'] > 0).mean() if len(trades_df) > 0 else 0
    avg_trade = trades_df['pnl'].mean() if len(trades_df) > 0 else 0
    avg_winner = trades_df.loc[trades_df['pnl'] > 0, 'pnl'].mean() if (trades_df['pnl'] > 0).any() else 0
    avg_loser = trades_df.loc[trades_df['pnl'] < 0, 'pnl'].mean() if (trades_df['pnl'] < 0).any() else 0

    exit_reasons = trades_df['exit_reason'].value_counts().to_dict() if 'exit_reason' in trades_df.columns and len(trades_df) > 0 else {}

    protection_days = df['in_protection'].sum()
    protection_pct = protection_days / len(df) * 100

    risk_off_pct = results['risk_off_days'] / (results['risk_on_days'] + results['risk_off_days']) * 100

    df_annual = df['value'].resample('YE').last()
    annual_returns = df_annual.pct_change().dropna()

    return {
        'initial': initial,
        'final_value': final_value,
        'total_return': (final_value - initial) / initial,
        'years': years,
        'cagr': cagr,
        'volatility': volatility,
        'sharpe': sharpe,
        'sortino': sortino,
        'calmar': calmar,
        'max_drawdown': max_dd,
        'win_rate': win_rate,
        'avg_trade': avg_trade,
        'avg_winner': avg_winner,
        'avg_loser': avg_loser,
        'trades': len(trades_df),
        'exit_reasons': exit_reasons,
        'stop_events': len(stop_df),
        'protection_days': protection_days,
        'protection_pct': protection_pct,
        'risk_off_pct': risk_off_pct,
        'annual_returns': annual_returns,
        'best_year': annual_returns.max() if len(annual_returns) > 0 else 0,
        'worst_year': annual_returns.min() if len(annual_returns) > 0 else 0,
    }


# ============================================================================
# MAIN
# ============================================================================

if __name__ == "__main__":
    # 1. Download/load data
    price_data = download_asia_pool()
    print(f"\nAsian symbols available: {len(price_data)}")

    # Show market breakdown
    markets = {'.T': 'Japan', '.HK': 'Hong Kong', '.AX': 'Australia',
               '.KS': 'South Korea', '.TW': 'Taiwan', '.SI': 'Singapore'}
    for suffix, name in markets.items():
        count = sum(1 for s in price_data if s.endswith(suffix))
        print(f"  {name} ({suffix}): {count}")

    regime_data = download_regime_index()
    print(f"Nikkei 225 data: {len(regime_data)} trading days ({regime_data.index[0].strftime('%Y-%m-%d')} to {regime_data.index[-1].strftime('%Y-%m-%d')})")

    # 2. Compute annual top-40
    print("\n--- Computing Annual Top-40 (dollar volume ranking) ---")
    annual_universe = compute_annual_top40(price_data)

    # Show first year top-40 for verification
    first_year = min(annual_universe.keys())
    top40_first = annual_universe[first_year]
    jp_count = sum(1 for s in top40_first if s.endswith('.T'))
    print(f"\n  First year ({first_year}) top-40: {jp_count} Japan, "
          f"{len(top40_first) - jp_count} non-Japan")
    print(f"  Sample top-10: {top40_first[:10]}")

    # 3. Run backtest
    results = run_backtest(price_data, annual_universe, regime_data)

    # 4. Calculate metrics
    metrics = calculate_metrics(results)

    # 5. Print results
    print("\n" + "=" * 80)
    print("RESULTS — COMPASS ASIA v1 (Asian Large-Cap)")
    print("=" * 80)

    print(f"\n--- Performance ---")
    print(f"Initial capital:        ${metrics['initial']:>15,.0f}")
    print(f"Final value:            ${metrics['final_value']:>15,.2f}")
    print(f"Total return:           {metrics['total_return']:>15.2%}")
    print(f"CAGR:                   {metrics['cagr']:>15.2%}")
    print(f"Volatility (annual):    {metrics['volatility']:>15.2%}")

    print(f"\n--- Risk-Adjusted ---")
    print(f"Sharpe ratio:           {metrics['sharpe']:>15.2f}")
    print(f"Sortino ratio:          {metrics['sortino']:>15.2f}")
    print(f"Calmar ratio:           {metrics['calmar']:>15.2f}")
    print(f"Max drawdown:           {metrics['max_drawdown']:>15.2%}")

    print(f"\n--- Trading ---")
    print(f"Trades executed:        {metrics['trades']:>15,}")
    print(f"Win rate:               {metrics['win_rate']:>15.2%}")
    print(f"Avg P&L per trade:      ${metrics['avg_trade']:>15,.2f}")
    print(f"Avg winner:             ${metrics['avg_winner']:>15,.2f}")
    print(f"Avg loser:              ${metrics['avg_loser']:>15,.2f}")

    print(f"\n--- Exit Reasons ---")
    for reason, count in sorted(metrics['exit_reasons'].items(), key=lambda x: -x[1]):
        print(f"  {reason:25s}: {count:>6,} ({count/metrics['trades']*100:.1f}%)")

    print(f"\n--- Risk Management ---")
    print(f"Stop loss events:       {metrics['stop_events']:>15,}")
    print(f"Days in protection:     {metrics['protection_days']:>15,} ({metrics['protection_pct']:.1f}%)")
    print(f"Risk-off days:          {metrics['risk_off_pct']:>14.1f}%")

    print(f"\n--- Annual Returns ---")
    if len(metrics['annual_returns']) > 0:
        print(f"Best year:              {metrics['best_year']:>15.2%}")
        print(f"Worst year:             {metrics['worst_year']:>15.2%}")
        print(f"Positive years:         {(metrics['annual_returns'] > 0).sum()}/{len(metrics['annual_returns'])}")

    # 6. HEAD-TO-HEAD: COMPASS Asia vs COMPASS US
    print("\n" + "=" * 80)
    print("HEAD-TO-HEAD: COMPASS ASIA vs COMPASS v8.2 (US)")
    print("=" * 80)
    us_cagr = 0.1766
    us_sharpe = 0.85
    us_maxdd = -0.275
    us_final = 6_911_873
    us_trades = 5327
    us_win = 0.553
    us_stops = 9
    us_protection = 26.7

    print(f"{'Metric':<25} {'ASIA':>15} {'US (v8.2)':>15} {'Delta':>12}")
    print("-" * 70)
    print(f"{'CAGR':<25} {metrics['cagr']:>14.2%} {us_cagr:>14.2%} {metrics['cagr']-us_cagr:>+11.2%}")
    print(f"{'Sharpe':<25} {metrics['sharpe']:>15.2f} {us_sharpe:>15.2f} {metrics['sharpe']-us_sharpe:>+12.2f}")
    print(f"{'Max Drawdown':<25} {metrics['max_drawdown']:>14.1%} {us_maxdd:>14.1%} {metrics['max_drawdown']-us_maxdd:>+11.1%}")
    print(f"{'Final Value':<25} ${metrics['final_value']:>13,.0f} ${us_final:>13,.0f}")
    print(f"{'Trades':<25} {metrics['trades']:>15,} {us_trades:>15,}")
    print(f"{'Win Rate':<25} {metrics['win_rate']:>14.1%} {us_win:>14.1%}")
    print(f"{'Stop Events':<25} {metrics['stop_events']:>15,} {us_stops:>15,}")
    print(f"{'Protection Days %':<25} {metrics['protection_pct']:>14.1f}% {us_protection:>14.1f}%")
    print(f"{'Volatility':<25} {metrics['volatility']:>14.2%}")

    # Also compare with EU result
    print(f"\n{'':>25} {'ASIA':>15} {'EU (v1)':>15} {'US (v8.2)':>15}")
    print("-" * 75)
    eu_cagr = -0.2087
    eu_maxdd = -0.8828
    eu_final = 507
    print(f"{'CAGR':<25} {metrics['cagr']:>14.2%} {eu_cagr:>14.2%} {us_cagr:>14.2%}")
    print(f"{'Max Drawdown':<25} {metrics['max_drawdown']:>14.1%} {eu_maxdd:>14.1%} {us_maxdd:>14.1%}")
    print(f"{'Final Value':<25} ${metrics['final_value']:>13,.0f} ${eu_final:>13,.0f} ${us_final:>13,.0f}")

    # Verdict
    if metrics['cagr'] >= us_cagr * 0.8:
        verdict = "PROMISING — Asian momentum competitive with US"
    elif metrics['cagr'] >= 0.08:
        verdict = "VIABLE — positive alpha vs Asian buy-and-hold"
    elif metrics['cagr'] >= 0.05:
        verdict = "MARGINAL — positive but not worth the complexity"
    else:
        verdict = "FAILED — Asian momentum too weak with these parameters"
    print(f"\nVERDICT: {verdict}")

    # 7. Save results
    os.makedirs('backtests', exist_ok=True)
    results['portfolio_values'].to_csv('backtests/asia_v1_daily.csv', index=False)
    if len(results['trades']) > 0:
        results['trades'].to_csv('backtests/asia_v1_trades.csv', index=False)

    output_file = 'results_asia_v1.pkl'
    with open(output_file, 'wb') as f:
        pickle.dump({
            'params': {
                'experiment': 'COMPASS Asia v1',
                'universe': 'Asian large-caps (JP/HK/AU/KR/TW/SG)',
                'regime_index': REGIME_INDEX,
                'broad_pool_size': len(BROAD_POOL),
                'symbols_downloaded': len(price_data),
                'momentum_lookback': MOMENTUM_LOOKBACK,
                'momentum_skip': MOMENTUM_SKIP,
                'hold_days': HOLD_DAYS,
                'num_positions': NUM_POSITIONS,
                'target_vol': TARGET_VOL,
                'regime_sma': REGIME_SMA_PERIOD,
                'position_stop': POSITION_STOP_LOSS,
                'portfolio_stop': PORTFOLIO_STOP_LOSS,
                'trailing_activation': TRAILING_ACTIVATION,
                'trailing_stop': TRAILING_STOP_PCT,
            },
            'metrics': metrics,
            'portfolio_values': results['portfolio_values'],
            'trades': results['trades'],
            'stop_events': results['stop_events'],
            'annual_universe': results['annual_universe']
        }, f)

    print(f"\nResults saved: {output_file}")
    print(f"Daily CSV: backtests/asia_v1_daily.csv")
    print(f"Trades CSV: backtests/asia_v1_trades.csv")

    print("\n" + "=" * 80)
    print("COMPASS ASIA v1 BACKTEST COMPLETE")
    print("=" * 80)
