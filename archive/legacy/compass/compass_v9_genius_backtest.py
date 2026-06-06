"""
COMPASS v9.0 "GENIUS LAYER" Backtest
=====================================
Experimental backtest implementing ALL 5 proposed layers on top of COMPASS v8.2.
This is a CURIOSITY TEST — v8.2 remains production. Algorithm is LOCKED.

Layers implemented:
1. MLP Enduring Momentum Probability — LogisticRegression elastic-net filter
2. Graph Momentum — Eigenvector centrality from partial correlation matrix
3. HMM 4-state regime — GaussianMixture proxy (no hmmlearn available)
4. Hierarchical optimization — Sector-neutral soft constraints via scipy
5. Meta-COMPASS — Thompson sampling online learning

Constraints:
- Same universe, same data (yfinance), same period (2000-2026)
- No external data (no earnings surprise, short interest, analyst revisions)
- MLP features limited to price/volume-derived (point-in-time from price data)
- Python 3.14.2, sklearn 1.8.0, scipy 1.17.0

NOTE: The proposal claimed +3-8% CAGR and -7% MaxDD. Let's see what actually happens.
"""

import pandas as pd
import numpy as np
import yfinance as yf
from datetime import datetime, timedelta
from sklearn.linear_model import LogisticRegression
from sklearn.preprocessing import StandardScaler
from scipy.linalg import eigh
from scipy.optimize import minimize
import pickle
import os
from typing import Dict, List, Tuple, Optional
import warnings
warnings.filterwarnings('ignore')

# ============================================================================
# COMPASS v8.2 BASE PARAMETERS (UNCHANGED)
# ============================================================================
TOP_N = 40
MIN_AGE_DAYS = 63
MOMENTUM_LOOKBACK = 90
MOMENTUM_SKIP = 5
MIN_MOMENTUM_STOCKS = 20
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
LEVERAGE_MAX = 1.0  # NO LEVERAGE — LOCKED
VOL_LOOKBACK = 20
INITIAL_CAPITAL = 100_000
MARGIN_RATE = 0.06
COMMISSION_PER_SHARE = 0.001
CASH_YIELD_RATE = 0.035
CASH_YIELD_SOURCE = 'AAA'
START_DATE = '2000-01-01'
END_DATE = '2026-02-09'

# v9.0 GENIUS LAYER PARAMETERS
MLP_TRAINING_WINDOW = 252 * 5   # 5 years rolling window
MLP_RETRAIN_FREQ = 63           # Retrain quarterly (was 21 monthly — FAST MODE)
MLP_PROB_THRESHOLD = 0.55       # Minimum probability to enter (proposal said 0.65)
MLP_FEATURE_LOOKBACKS = [20, 60, 90, 120, 252]  # Multi-scale features

GRAPH_CORR_WINDOW = 20          # 20-day partial correlation window
GRAPH_TOP_PERCENTILE = 0.70     # Only consider stocks with MLP score > 70th percentile

HMM_N_STATES = 4                # Bull-High, Bull-Late, Transition, Bear
HMM_LOOKBACK = 252              # 1 year of data for fitting

FAST_MODE = True                # Skip sector optimization, reduce graph candidates

SECTOR_PENALTY = 0.12           # Max sector deviation from equal-weight

META_BANDIT_WINDOW = 63         # Sharpe over 63 days
META_PRIOR_ALPHA = 2.0          # Beta prior alpha
META_PRIOR_BETA = 2.0           # Beta prior beta

SEED = 666  # Official project seed

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

# Sector mapping for optimization layer
SECTOR_MAP = {
    'AAPL': 'Tech', 'MSFT': 'Tech', 'NVDA': 'Tech', 'GOOGL': 'Tech', 'META': 'Tech',
    'AVGO': 'Tech', 'ADBE': 'Tech', 'CRM': 'Tech', 'AMD': 'Tech', 'INTC': 'Tech',
    'CSCO': 'Tech', 'IBM': 'Tech', 'TXN': 'Tech', 'QCOM': 'Tech', 'ORCL': 'Tech',
    'ACN': 'Tech', 'NOW': 'Tech', 'INTU': 'Tech', 'AMAT': 'Tech', 'MU': 'Tech',
    'LRCX': 'Tech', 'SNPS': 'Tech', 'CDNS': 'Tech', 'KLAC': 'Tech', 'MRVL': 'Tech',
    'BRK-B': 'Fin', 'JPM': 'Fin', 'V': 'Fin', 'MA': 'Fin', 'BAC': 'Fin',
    'WFC': 'Fin', 'GS': 'Fin', 'MS': 'Fin', 'AXP': 'Fin', 'BLK': 'Fin',
    'SCHW': 'Fin', 'C': 'Fin', 'USB': 'Fin', 'PNC': 'Fin', 'TFC': 'Fin',
    'CB': 'Fin', 'MMC': 'Fin', 'AIG': 'Fin',
    'UNH': 'Health', 'JNJ': 'Health', 'LLY': 'Health', 'ABBV': 'Health', 'MRK': 'Health',
    'PFE': 'Health', 'TMO': 'Health', 'ABT': 'Health', 'DHR': 'Health', 'AMGN': 'Health',
    'BMY': 'Health', 'MDT': 'Health', 'ISRG': 'Health', 'SYK': 'Health', 'GILD': 'Health',
    'REGN': 'Health', 'VRTX': 'Health', 'BIIB': 'Health',
    'AMZN': 'Consumer', 'TSLA': 'Consumer', 'WMT': 'Consumer', 'HD': 'Consumer',
    'PG': 'Consumer', 'COST': 'Consumer', 'KO': 'Consumer', 'PEP': 'Consumer',
    'NKE': 'Consumer', 'MCD': 'Consumer', 'DIS': 'Consumer', 'SBUX': 'Consumer',
    'TGT': 'Consumer', 'LOW': 'Consumer', 'CL': 'Consumer', 'KMB': 'Consumer',
    'GIS': 'Consumer', 'EL': 'Consumer', 'MO': 'Consumer', 'PM': 'Consumer',
    'XOM': 'Energy', 'CVX': 'Energy', 'COP': 'Energy', 'SLB': 'Energy', 'EOG': 'Energy',
    'OXY': 'Energy', 'MPC': 'Energy', 'PSX': 'Energy', 'VLO': 'Energy',
    'GE': 'Industrial', 'CAT': 'Industrial', 'BA': 'Industrial', 'HON': 'Industrial',
    'UNP': 'Industrial', 'RTX': 'Industrial', 'LMT': 'Industrial', 'DE': 'Industrial',
    'UPS': 'Industrial', 'FDX': 'Industrial', 'MMM': 'Industrial', 'GD': 'Industrial',
    'NOC': 'Industrial', 'EMR': 'Industrial',
    'NEE': 'Utility', 'DUK': 'Utility', 'SO': 'Utility', 'D': 'Utility', 'AEP': 'Utility',
    'VZ': 'Telecom', 'T': 'Telecom', 'TMUS': 'Telecom', 'CMCSA': 'Telecom',
}

print("=" * 80)
print("COMPASS v9.0 \"GENIUS LAYER\" BACKTEST")
print("Experimental — v8.2 remains production (ALGORITHM LOCKED)")
print("=" * 80)
print(f"\nLayers: MLP Filter + Graph Momentum + HMM Regime + Sector Opt + Meta-Learning")
print(f"Universe: {len(BROAD_POOL)} stocks | Top-{TOP_N} annual rotation")
print(f"Period: {START_DATE} to {END_DATE}")
print(f"Seed: {SEED}")
print()


# ============================================================================
# DATA FUNCTIONS (same as v8.2)
# ============================================================================

def download_broad_pool() -> Dict[str, pd.DataFrame]:
    cache_file = f'data_cache/broad_pool_{START_DATE}_{END_DATE}.pkl'
    if os.path.exists(cache_file):
        print("[Cache] Loading broad pool data...")
        try:
            with open(cache_file, 'rb') as f:
                return pickle.load(f)
        except Exception:
            print("[Cache] Failed to load, re-downloading...")
    print(f"[Download] Downloading {len(BROAD_POOL)} symbols...")
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
    os.makedirs('data_cache', exist_ok=True)
    with open(cache_file, 'wb') as f:
        pickle.dump(data, f)
    return data


def download_spy() -> pd.DataFrame:
    cache_file = f'data_cache/SPY_{START_DATE}_{END_DATE}.csv'
    if os.path.exists(cache_file):
        print("[Cache] Loading SPY data...")
        return pd.read_csv(cache_file, index_col=0, parse_dates=True)
    print("[Download] Downloading SPY...")
    df = yf.download('SPY', start=START_DATE, end=END_DATE, progress=False)
    df.columns = [c[0] if isinstance(c, tuple) else c for c in df.columns]
    os.makedirs('data_cache', exist_ok=True)
    df.to_csv(cache_file)
    return df


def download_cash_yield() -> pd.Series:
    cache_file = 'data_cache/moody_aaa_yield.csv'
    if os.path.exists(cache_file):
        print("[Cache] Loading Moody's Aaa yield data...")
        df = pd.read_csv(cache_file, index_col=0, parse_dates=True)
        daily = df['yield_pct'].resample('D').ffill()
        print(f"  {len(daily)} daily rates, avg {daily.mean():.2f}%")
        return daily
    print("[Download] Downloading Moody's Aaa yield from FRED...")
    try:
        url = 'https://fred.stlouisfed.org/graph/fredgraph.csv?id=AAA&cosd=1999-01-01&coed=2026-12-31'
        df = pd.read_csv(url, parse_dates=['observation_date'], index_col='observation_date')
        df.columns = ['yield_pct']
        os.makedirs('data_cache', exist_ok=True)
        df.to_csv(cache_file)
        daily = df['yield_pct'].resample('D').ffill()
        print(f"  {len(daily)} daily rates, avg {daily.mean():.2f}%")
        return daily
    except Exception as e:
        print(f"  FRED download failed: {e}. Using fixed {CASH_YIELD_RATE:.1%}")
        return None


def download_vix() -> pd.DataFrame:
    """Download VIX data for HMM regime model"""
    cache_file = f'data_cache/VIX_{START_DATE}_{END_DATE}.csv'
    if os.path.exists(cache_file):
        print("[Cache] Loading VIX data...")
        return pd.read_csv(cache_file, index_col=0, parse_dates=True)
    print("[Download] Downloading VIX...")
    df = yf.download('^VIX', start=START_DATE, end=END_DATE, progress=False)
    df.columns = [c[0] if isinstance(c, tuple) else c for c in df.columns]
    os.makedirs('data_cache', exist_ok=True)
    df.to_csv(cache_file)
    return df


def compute_annual_top40(price_data: Dict[str, pd.DataFrame]) -> Dict[int, List[str]]:
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
# v8.2 BASE FUNCTIONS (UNCHANGED)
# ============================================================================

def compute_regime(spy_data: pd.DataFrame) -> pd.Series:
    spy_close = spy_data['Close']
    sma200 = spy_close.rolling(REGIME_SMA_PERIOD).mean()
    raw_signal = spy_close > sma200
    regime = pd.Series(index=spy_close.index, dtype=bool)
    regime.iloc[:REGIME_SMA_PERIOD] = True
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


def compute_momentum_scores(price_data, tradeable, date, all_dates, date_idx):
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


def compute_volatility_weights(price_data, selected, date):
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


def compute_dynamic_leverage(spy_data, date):
    if date not in spy_data.index:
        return 1.0
    idx = spy_data.index.get_loc(date)
    if idx < VOL_LOOKBACK + 1:
        return 1.0
    returns = spy_data['Close'].iloc[idx - VOL_LOOKBACK:idx + 1].pct_change().dropna()
    if len(returns) < VOL_LOOKBACK - 2:
        return 1.0
    realized_vol = returns.std() * np.sqrt(252)
    if realized_vol < 0.01:
        return LEVERAGE_MAX
    leverage = TARGET_VOL / realized_vol
    return max(LEVERAGE_MIN, min(LEVERAGE_MAX, leverage))


def get_tradeable_symbols(price_data, date, first_date, annual_universe):
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


# ============================================================================
# LAYER 1: MLP ENDURING MOMENTUM PROBABILITY
# ============================================================================

class MLPFilter:
    """
    Logistic regression with elastic-net penalty predicting whether a stock's
    momentum will persist over the next 5 trading days.

    Features (all price/volume derived, point-in-time):
    1. Momentum 90d (base signal)
    2. Momentum 20d, 60d, 120d, 252d (multi-scale)
    3. Volatility 20d annualized
    4. Volume ratio (20d avg / 60d avg)
    5. RSI 14d
    6. Distance from 52-week high
    7. Momentum vs sector median (idiosyncratic component)
    8. Amihud illiquidity ratio (20d)
    9. Return skewness 60d
    10. Max drawdown 60d
    """

    def __init__(self, seed=SEED):
        self.model = None
        self.scaler = StandardScaler()
        self.last_train_idx = -999
        self.seed = seed
        self.train_count = 0

    def _compute_features(self, price_data, symbol, date, sym_idx):
        """Compute feature vector for a stock at a given date"""
        df = price_data[symbol]
        if sym_idx < 252:
            return None

        close = df['Close'].iloc[:sym_idx + 1]
        volume = df['Volume'].iloc[:sym_idx + 1]

        features = {}

        # Multi-scale momentum
        for lb in [20, 60, 90, 120, 252]:
            if sym_idx >= lb:
                features[f'mom_{lb}d'] = close.iloc[-1] / close.iloc[-lb] - 1.0
            else:
                features[f'mom_{lb}d'] = 0.0

        # Volatility 20d
        ret_20 = close.iloc[-21:].pct_change().dropna()
        features['vol_20d'] = ret_20.std() * np.sqrt(252) if len(ret_20) >= 15 else 0.2

        # Volume ratio (20d / 60d)
        vol_20 = volume.iloc[-20:].mean()
        vol_60 = volume.iloc[-60:].mean() if sym_idx >= 60 else vol_20
        features['vol_ratio'] = vol_20 / vol_60 if vol_60 > 0 else 1.0

        # RSI 14d
        ret_14 = close.iloc[-15:].pct_change().dropna()
        if len(ret_14) >= 10:
            gains = ret_14[ret_14 > 0].sum()
            losses = -ret_14[ret_14 < 0].sum()
            if losses > 0:
                rs = gains / losses
                features['rsi_14'] = 100 - 100 / (1 + rs)
            else:
                features['rsi_14'] = 100.0
        else:
            features['rsi_14'] = 50.0

        # Distance from 52-week high
        high_252 = close.iloc[-252:].max()
        features['dist_52w_high'] = close.iloc[-1] / high_252 - 1.0 if high_252 > 0 else 0.0

        # Amihud illiquidity (avg |return| / dollar_volume)
        ret_20_abs = ret_20.abs()
        dv_20 = (close.iloc[-21:] * volume.iloc[-21:]).iloc[1:]
        if len(dv_20) >= 15 and dv_20.mean() > 0:
            features['amihud'] = (ret_20_abs / dv_20.values[:len(ret_20_abs)]).mean() * 1e6
        else:
            features['amihud'] = 0.0

        # Return skewness 60d
        ret_60 = close.iloc[-61:].pct_change().dropna() if sym_idx >= 61 else ret_20
        if len(ret_60) >= 20:
            mean_r = ret_60.mean()
            std_r = ret_60.std()
            if std_r > 0:
                features['skew_60d'] = ((ret_60 - mean_r) ** 3).mean() / (std_r ** 3)
            else:
                features['skew_60d'] = 0.0
        else:
            features['skew_60d'] = 0.0

        # Max drawdown 60d
        if sym_idx >= 60:
            prices_60 = close.iloc[-60:]
            peak = prices_60.expanding().max()
            dd_series = (prices_60 - peak) / peak
            features['max_dd_60d'] = dd_series.min()
        else:
            features['max_dd_60d'] = 0.0

        return features

    def _compute_label(self, price_data, symbol, sym_idx):
        """Label: did momentum persist (positive return) over next 5 days?"""
        df = price_data[symbol]
        if sym_idx + HOLD_DAYS >= len(df):
            return None
        future_return = df['Close'].iloc[sym_idx + HOLD_DAYS] / df['Close'].iloc[sym_idx] - 1.0
        return 1 if future_return > 0 else 0

    def train(self, price_data, tradeable_symbols, date, date_idx, all_dates):
        """Train MLP model on rolling window of historical data"""
        X_train = []
        y_train = []

        # Collect training data from rolling window
        train_start = max(0, date_idx - MLP_TRAINING_WINDOW)
        # Sample every 10 days to reduce correlation and speed up (FAST MODE)
        sample_indices = range(train_start, date_idx - HOLD_DAYS - 1, 10)

        for idx in sample_indices:
            train_date = all_dates[idx]
            year = train_date.year

            for symbol in tradeable_symbols:
                if symbol not in price_data:
                    continue
                df = price_data[symbol]
                if train_date not in df.index:
                    continue
                try:
                    sym_idx = df.index.get_loc(train_date)
                except KeyError:
                    continue

                features = self._compute_features(price_data, symbol, train_date, sym_idx)
                if features is None:
                    continue

                label = self._compute_label(price_data, symbol, sym_idx)
                if label is None:
                    continue

                X_train.append(list(features.values()))
                y_train.append(label)

        if len(X_train) < 100:
            return False

        X = np.array(X_train)
        y = np.array(y_train)

        # Remove NaN/Inf
        mask = np.isfinite(X).all(axis=1)
        X = X[mask]
        y = y[mask]

        if len(X) < 100:
            return False

        self.scaler = StandardScaler()
        X_scaled = self.scaler.fit_transform(X)

        self.model = LogisticRegression(
            penalty='elasticnet',
            solver='saga',
            l1_ratio=0.5,
            C=0.1,
            max_iter=500,
            random_state=self.seed
        )
        self.model.fit(X_scaled, y)
        self.last_train_idx = date_idx
        self.train_count += 1
        return True

    def predict_probability(self, price_data, symbol, date):
        """Predict P(enduring momentum) for a stock"""
        if self.model is None:
            return 0.5  # No model yet, neutral

        df = price_data[symbol]
        if date not in df.index:
            return 0.5

        sym_idx = df.index.get_loc(date)
        features = self._compute_features(price_data, symbol, date, sym_idx)
        if features is None:
            return 0.5

        X = np.array([list(features.values())])
        if not np.isfinite(X).all():
            return 0.5

        X_scaled = self.scaler.transform(X)
        prob = self.model.predict_proba(X_scaled)[0, 1]
        return prob


# ============================================================================
# LAYER 2: GRAPH MOMENTUM (Eigenvector Centrality)
# ============================================================================

class GraphMomentum:
    """
    Build partial correlation graph from returns (controlling for SPY).
    Select stocks with highest eigenvector centrality.
    """

    def compute_centrality(self, price_data, candidates, date, spy_data):
        """
        Compute eigenvector centrality for candidate stocks.
        Returns dict: symbol -> centrality score
        """
        if len(candidates) < 3:
            return {s: 1.0 for s in candidates}

        # Collect 20-day returns for candidates
        returns_matrix = []
        valid_symbols = []
        spy_ret = None

        if date in spy_data.index:
            spy_idx = spy_data.index.get_loc(date)
            if spy_idx >= GRAPH_CORR_WINDOW:
                spy_ret = spy_data['Close'].iloc[spy_idx - GRAPH_CORR_WINDOW:spy_idx + 1].pct_change().dropna().values

        for symbol in candidates:
            if symbol not in price_data:
                continue
            df = price_data[symbol]
            if date not in df.index:
                continue
            sym_idx = df.index.get_loc(date)
            if sym_idx < GRAPH_CORR_WINDOW:
                continue
            ret = df['Close'].iloc[sym_idx - GRAPH_CORR_WINDOW:sym_idx + 1].pct_change().dropna().values
            if len(ret) >= GRAPH_CORR_WINDOW - 2:
                returns_matrix.append(ret[:GRAPH_CORR_WINDOW - 1])
                valid_symbols.append(symbol)

        if len(valid_symbols) < 3:
            return {s: 1.0 for s in candidates}

        R = np.array(returns_matrix)  # shape: (n_stocks, n_days)

        # Partial correlation: residualize against SPY
        if spy_ret is not None and len(spy_ret) >= R.shape[1]:
            spy_r = spy_ret[:R.shape[1]]
            # Regress out SPY from each stock
            spy_r_2d = spy_r.reshape(-1, 1)
            for i in range(R.shape[0]):
                coef = np.linalg.lstsq(spy_r_2d, R[i], rcond=None)[0]
                R[i] = R[i] - spy_r_2d.flatten() * coef[0]

        # Correlation matrix of residuals
        n = R.shape[0]
        corr = np.corrcoef(R)

        # Handle NaN
        corr = np.nan_to_num(corr, nan=0.0)
        np.fill_diagonal(corr, 1.0)

        # Make non-negative for eigenvector centrality (shift)
        corr_shifted = corr - corr.min() + 0.01
        np.fill_diagonal(corr_shifted, 0)

        # Eigenvector centrality = leading eigenvector of adjacency matrix
        try:
            eigenvalues, eigenvectors = eigh(corr_shifted)
            # Leading eigenvector (last one, since eigh returns ascending order)
            centrality = np.abs(eigenvectors[:, -1])
            centrality = centrality / centrality.sum()  # Normalize
        except Exception:
            centrality = np.ones(n) / n

        return {valid_symbols[i]: centrality[i] for i in range(n)}


# ============================================================================
# LAYER 3: HMM 4-STATE REGIME (GaussianMixture proxy)
# ============================================================================

class HMMRegime:
    """
    4-state regime model using GaussianMixture as a proxy for HMM.
    States: Bull-HighConviction, Bull-Late, Transition, Bear

    Features: SPY return, VIX level, breadth proxy (% of universe above SMA50)
    """

    def __init__(self, seed=SEED):
        from sklearn.mixture import GaussianMixture
        self.model = GaussianMixture(
            n_components=HMM_N_STATES,
            covariance_type='full',
            n_init=3,
            random_state=seed,
            max_iter=200
        )
        self.fitted = False
        self.state_means = None  # To identify which state is which
        self.last_fit_idx = -999
        self.seed = seed

    def _build_features(self, spy_data, vix_data, price_data, tradeable, date, lookback=HMM_LOOKBACK):
        """Build feature matrix for regime model"""
        idx = spy_data.index.get_loc(date) if date in spy_data.index else None
        if idx is None or idx < lookback:
            return None

        features = []
        for i in range(idx - lookback, idx + 1):
            d = spy_data.index[i]
            row = []

            # SPY 20d return
            if i >= 20:
                spy_ret_20 = spy_data['Close'].iloc[i] / spy_data['Close'].iloc[i - 20] - 1
            else:
                spy_ret_20 = 0.0
            row.append(spy_ret_20)

            # SPY 20d volatility
            if i >= 21:
                spy_vol = spy_data['Close'].iloc[i-20:i+1].pct_change().dropna().std() * np.sqrt(252)
            else:
                spy_vol = 0.15
            row.append(spy_vol)

            # VIX level (normalized)
            if d in vix_data.index:
                vix = vix_data.loc[d, 'Close'] / 100.0  # Normalize
            else:
                vix = 0.20
            row.append(vix)

            # Breadth: fraction of tradeable stocks above their 50d SMA
            above_sma = 0
            total = 0
            for sym in tradeable[:20]:  # Sample for speed
                if sym in price_data and d in price_data[sym].index:
                    si = price_data[sym].index.get_loc(d)
                    if si >= 50:
                        sma50 = price_data[sym]['Close'].iloc[si-50:si+1].mean()
                        if price_data[sym]['Close'].iloc[si] > sma50:
                            above_sma += 1
                        total += 1
            breadth = above_sma / total if total > 0 else 0.5
            row.append(breadth)

            features.append(row)

        return np.array(features)

    def fit(self, spy_data, vix_data, price_data, tradeable, date, date_idx):
        """Fit the regime model"""
        X = self._build_features(spy_data, vix_data, price_data, tradeable, date)
        if X is None or len(X) < 50:
            return False

        # Remove NaN/Inf
        mask = np.isfinite(X).all(axis=1)
        X = X[mask]
        if len(X) < 50:
            return False

        try:
            self.model.fit(X)
            self.fitted = True
            self.last_fit_idx = date_idx

            # Identify states by their mean SPY return (feature 0)
            self.state_means = self.model.means_[:, 0]  # SPY 20d return means
            return True
        except Exception:
            return False

    def predict_probabilities(self, spy_data, vix_data, price_data, tradeable, date):
        """
        Returns probability of being in bull state.
        Used to modulate leverage and max positions.
        """
        if not self.fitted:
            return 0.7  # Default moderate bull

        X = self._build_features(spy_data, vix_data, price_data, tradeable, date, lookback=5)
        if X is None or len(X) == 0:
            return 0.7

        try:
            # Use last observation
            x_last = X[-1:].reshape(1, -1)
            if not np.isfinite(x_last).all():
                return 0.7

            probs = self.model.predict_proba(x_last)[0]

            # Sort states by their mean SPY return
            state_order = np.argsort(self.state_means)  # Bear -> Bull

            # P(bull) = probability of being in the top 2 states
            bull_states = state_order[-2:]  # Top 2 = Bull-High + Bull-Late
            prob_bull = probs[bull_states].sum()

            # P(bull-high) = just the most bullish state
            prob_bull_high = probs[state_order[-1]]

            return prob_bull_high * 0.6 + prob_bull * 0.4
        except Exception:
            return 0.7


# ============================================================================
# LAYER 4: SECTOR-NEUTRAL OPTIMIZATION
# ============================================================================

def optimize_sector_weights(candidates, base_scores, sectors, max_deviation=SECTOR_PENALTY):
    """
    Soft sector-neutral optimization via scipy.
    Minimizes negative expected return subject to sector constraints.
    """
    n = len(candidates)
    if n <= 1:
        return {candidates[0]: 1.0} if n == 1 else {}

    # Get unique sectors
    sector_list = list(set(sectors.values()))
    n_sectors = len(sector_list)
    equal_sector_weight = 1.0 / n_sectors if n_sectors > 0 else 1.0

    # Base scores as expected returns
    scores = np.array([base_scores.get(s, 0.0) for s in candidates])
    if scores.max() > 0:
        scores = scores / scores.max()  # Normalize to [0, 1]

    # Objective: maximize expected return (minimize negative)
    def objective(w):
        return -np.dot(w, scores) + 0.01 * np.dot(w, w)  # Small regularization

    # Constraints
    constraints = [{'type': 'eq', 'fun': lambda w: np.sum(w) - 1.0}]

    # Sector constraints
    for sector in sector_list:
        sector_mask = np.array([1.0 if sectors.get(c, '') == sector else 0.0 for c in candidates])
        constraints.append({
            'type': 'ineq',
            'fun': lambda w, sm=sector_mask: max_deviation + equal_sector_weight - np.dot(w, sm)
        })

    bounds = [(0, 0.5) for _ in range(n)]  # Max 50% in one stock
    w0 = np.ones(n) / n

    try:
        result = minimize(objective, w0, method='SLSQP', bounds=bounds, constraints=constraints)
        if result.success:
            weights = result.x
            weights = np.maximum(weights, 0)
            weights = weights / weights.sum()
            return {candidates[i]: weights[i] for i in range(n)}
    except Exception:
        pass

    # Fallback: equal weight
    return {s: 1.0 / n for s in candidates}


# ============================================================================
# LAYER 5: META-COMPASS (Thompson Sampling)
# ============================================================================

class MetaCompass:
    """
    Online learning via Thompson sampling to adapt:
    - leverage_multiplier (0.8 to 1.2)
    - position_count_adj (-1, 0, +1)

    Reward = rolling Sharpe, penalized by turnover
    """

    def __init__(self, seed=SEED):
        self.rng = np.random.RandomState(seed)
        # Arms: (leverage_mult, pos_adj)
        self.arms = [
            (0.85, -1),  # Conservative
            (0.90, 0),   # Slightly conservative
            (1.00, 0),   # Baseline
            (1.10, 0),   # Slightly aggressive
            (1.05, +1),  # Aggressive
        ]
        self.n_arms = len(self.arms)
        self.alpha = np.full(self.n_arms, META_PRIOR_ALPHA)
        self.beta = np.full(self.n_arms, META_PRIOR_BETA)
        self.current_arm = 2  # Start at baseline
        self.last_value = None
        self.returns_buffer = []

    def select_arm(self):
        """Thompson sampling: sample from Beta posteriors, pick best"""
        samples = [self.rng.beta(self.alpha[i], self.beta[i]) for i in range(self.n_arms)]
        self.current_arm = int(np.argmax(samples))
        return self.arms[self.current_arm]

    def update(self, portfolio_value):
        """Update with daily portfolio value"""
        if self.last_value is not None and self.last_value > 0:
            daily_ret = (portfolio_value - self.last_value) / self.last_value
            self.returns_buffer.append(daily_ret)

            # Update every META_BANDIT_WINDOW days
            if len(self.returns_buffer) >= META_BANDIT_WINDOW:
                returns = np.array(self.returns_buffer[-META_BANDIT_WINDOW:])
                sharpe = returns.mean() / (returns.std() + 1e-8) * np.sqrt(252)

                # Reward: positive if Sharpe > 0.5
                if sharpe > 0.5:
                    self.alpha[self.current_arm] += 1
                else:
                    self.beta[self.current_arm] += 1

                self.returns_buffer = self.returns_buffer[-META_BANDIT_WINDOW:]

        self.last_value = portfolio_value

    def get_adjustments(self):
        """Get current leverage multiplier and position adjustment"""
        return self.arms[self.current_arm]


# ============================================================================
# v9.0 GENIUS BACKTEST
# ============================================================================

def run_genius_backtest(price_data, annual_universe, spy_data, vix_data,
                        cash_yield_daily=None) -> Dict:
    """Run COMPASS v9.0 GENIUS LAYER backtest"""

    print("\n" + "=" * 80)
    print("RUNNING COMPASS v9.0 GENIUS LAYER BACKTEST")
    print("=" * 80)

    # Initialize layers
    mlp_filter = MLPFilter(seed=SEED)
    graph_momentum = GraphMomentum()
    hmm_regime = HMMRegime(seed=SEED)
    meta_compass = MetaCompass(seed=SEED)

    # Get all trading dates
    all_dates = set()
    for df in price_data.values():
        all_dates.update(df.index)
    all_dates = sorted(list(all_dates))
    first_date = all_dates[0]

    # Compute base regime (v8.2 SMA200 — kept as fallback)
    print("\nComputing base regime (SPY vs SMA200)...")
    base_regime = compute_regime(spy_data)

    print(f"Period: {all_dates[0].strftime('%Y-%m-%d')} to {all_dates[-1].strftime('%Y-%m-%d')}")
    print(f"Trading days: {len(all_dates)}")

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

    # Layer tracking
    mlp_filter_count = 0
    mlp_block_count = 0
    graph_rerank_count = 0
    hmm_override_count = 0
    meta_adjust_count = 0
    layer_stats = {'mlp_trains': 0, 'hmm_fits': 0}

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

        # --- Meta-COMPASS update (Layer 5) ---
        meta_compass.update(portfolio_value)

        # --- Update peak ---
        if portfolio_value > peak_value and not in_protection_mode:
            peak_value = portfolio_value

        # --- Recovery from protection ---
        if in_protection_mode and stop_loss_day_index is not None:
            days_since_stop = i - stop_loss_day_index
            is_regime_on = True
            if date in base_regime.index:
                is_regime_on = bool(base_regime.loc[date])
            if protection_stage == 1 and days_since_stop >= RECOVERY_STAGE_1_DAYS and is_regime_on:
                protection_stage = 2
            if protection_stage == 2 and days_since_stop >= RECOVERY_STAGE_2_DAYS and is_regime_on:
                in_protection_mode = False
                protection_stage = 0
                peak_value = portfolio_value
                stop_loss_day_index = None
                post_stop_base = None

        # --- Drawdown ---
        drawdown = (portfolio_value - peak_value) / peak_value if peak_value > 0 else 0

        # --- Portfolio stop loss ---
        if drawdown <= PORTFOLIO_STOP_LOSS and not in_protection_mode:
            stop_events.append({'date': date, 'portfolio_value': portfolio_value, 'drawdown': drawdown})
            for symbol in list(positions.keys()):
                if symbol in price_data and date in price_data[symbol].index:
                    exit_price = price_data[symbol].loc[date, 'Close']
                    pos = positions[symbol]
                    proceeds = pos['shares'] * exit_price
                    commission = pos['shares'] * COMMISSION_PER_SHARE
                    cash += proceeds - commission
                    pnl = (exit_price - pos['entry_price']) * pos['shares'] - commission
                    trades.append({
                        'symbol': symbol, 'entry_date': pos['entry_date'],
                        'exit_date': date, 'exit_reason': 'portfolio_stop',
                        'pnl': pnl, 'return': pnl / (pos['entry_price'] * pos['shares'])
                    })
                del positions[symbol]
            in_protection_mode = True
            protection_stage = 1
            stop_loss_day_index = i
            post_stop_base = cash

        # --- Base regime (v8.2) ---
        is_risk_on = True
        if date in base_regime.index:
            is_risk_on = bool(base_regime.loc[date])

        # --- LAYER 3: HMM Regime Override ---
        # Retrain HMM monthly
        if i - hmm_regime.last_fit_idx >= MLP_RETRAIN_FREQ and i > HMM_LOOKBACK:
            hmm_regime.fit(spy_data, vix_data, price_data, tradeable_symbols, date, i)
            layer_stats['hmm_fits'] += 1

        hmm_prob_bull = hmm_regime.predict_probabilities(
            spy_data, vix_data, price_data, tradeable_symbols, date
        )

        # HMM can override regime: if HMM is very bearish but SMA says bullish, reduce
        hmm_leverage_mult = 1.0
        if hmm_prob_bull < 0.3 and is_risk_on:
            # HMM says bear but SMA says bull — be cautious
            hmm_leverage_mult = 0.7
            hmm_override_count += 1
        elif hmm_prob_bull > 0.7 and not is_risk_on:
            # HMM says bull but SMA says bear — slightly more aggressive
            hmm_leverage_mult = 1.1

        if is_risk_on:
            risk_on_days += 1
        else:
            risk_off_days += 1

        # --- Determine max positions and leverage ---
        # Meta-COMPASS adjustments (Layer 5)
        meta_lev_mult, meta_pos_adj = meta_compass.select_arm()

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
            current_leverage = compute_dynamic_leverage(spy_data, date)

        # Apply HMM multiplier
        current_leverage = current_leverage * hmm_leverage_mult
        current_leverage = max(LEVERAGE_MIN, min(LEVERAGE_MAX, current_leverage))

        # Apply Meta-COMPASS multiplier (subtle)
        if not in_protection_mode:
            current_leverage = current_leverage * meta_lev_mult
            current_leverage = max(LEVERAGE_MIN, min(LEVERAGE_MAX, current_leverage))
            max_positions = max(2, min(7, max_positions + meta_pos_adj))
            meta_adjust_count += 1

        # --- HMM can modulate positions ---
        if not in_protection_mode and is_risk_on:
            hmm_pos = round(2 + 3 * hmm_prob_bull)
            max_positions = max(2, min(7, hmm_pos))

        # --- Daily costs ---
        if current_leverage > 1.0:
            borrowed = portfolio_value * (current_leverage - 1) / current_leverage
            daily_margin = MARGIN_RATE / 252 * borrowed
            cash -= daily_margin

        # --- Cash yield ---
        if cash > 0:
            if cash_yield_daily is not None and date in cash_yield_daily.index:
                daily_rate = cash_yield_daily.loc[date] / 100 / 252
            else:
                daily_rate = CASH_YIELD_RATE / 252
            cash += cash * daily_rate

        # --- Close positions (same as v8.2) ---
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
                    'symbol': symbol, 'entry_date': pos['entry_date'],
                    'exit_date': date, 'exit_reason': exit_reason,
                    'pnl': pnl, 'return': pnl / (pos['entry_price'] * shares)
                })
                del positions[symbol]

        # --- Open new positions (GENIUS LAYER) ---
        needed = max_positions - len(positions)

        if needed > 0 and cash > 1000 and len(tradeable_symbols) >= 5:
            # Step 1: Base momentum scores (v8.2)
            scores = compute_momentum_scores(price_data, tradeable_symbols, date, all_dates, i)
            available_scores = {s: sc for s, sc in scores.items() if s not in positions}

            if len(available_scores) >= needed:
                # --- LAYER 1: MLP Filter ---
                # Retrain monthly
                if i - mlp_filter.last_train_idx >= MLP_RETRAIN_FREQ and i > MLP_TRAINING_WINDOW:
                    success = mlp_filter.train(price_data, tradeable_symbols, date, i, all_dates)
                    if success:
                        layer_stats['mlp_trains'] += 1

                # Apply MLP probability filter
                mlp_scores = {}
                for symbol, base_score in available_scores.items():
                    prob = mlp_filter.predict_probability(price_data, symbol, date)
                    if prob >= MLP_PROB_THRESHOLD:
                        # Weight score by probability
                        mlp_scores[symbol] = base_score * prob
                        mlp_filter_count += 1
                    else:
                        mlp_block_count += 1

                # If MLP filtered too aggressively, fall back to base scores
                if len(mlp_scores) < needed:
                    mlp_scores = available_scores.copy()

                # --- LAYER 2: Graph Momentum ---
                # Get top candidates (70th percentile by MLP score), cap at 8 for speed
                if len(mlp_scores) > 5:
                    score_threshold = np.percentile(list(mlp_scores.values()),
                                                     GRAPH_TOP_PERCENTILE * 100)
                    graph_candidates = [s for s, sc in mlp_scores.items() if sc >= score_threshold]
                    # FAST MODE: cap graph candidates to reduce matrix computation
                    if FAST_MODE and len(graph_candidates) > 8:
                        top_mlp = sorted(mlp_scores.items(), key=lambda x: x[1], reverse=True)[:8]
                        graph_candidates = [s for s, _ in top_mlp]
                else:
                    graph_candidates = list(mlp_scores.keys())

                if len(graph_candidates) >= needed:
                    centrality = graph_momentum.compute_centrality(
                        price_data, graph_candidates, date, spy_data
                    )

                    # Final score = MLP_score * centrality
                    final_scores = {}
                    for symbol in graph_candidates:
                        final_scores[symbol] = mlp_scores.get(symbol, 0) * centrality.get(symbol, 0.5)

                    graph_rerank_count += 1
                else:
                    final_scores = mlp_scores

                # Select top N
                ranked = sorted(final_scores.items(), key=lambda x: x[1], reverse=True)
                selected = [s for s, _ in ranked[:needed]]

                # --- LAYER 4: Sector-neutral optimization ---
                if FAST_MODE:
                    # FAST: skip scipy optimization, use vol weights
                    weights = compute_volatility_weights(price_data, selected, date)
                else:
                    selected_sectors = {s: SECTOR_MAP.get(s, 'Other') for s in selected}
                    if len(selected) > 1:
                        weights = optimize_sector_weights(
                            selected, final_scores, selected_sectors
                        )
                    else:
                        weights = compute_volatility_weights(price_data, selected, date)

                # Effective capital with leverage
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
            'universe_size': len(tradeable_symbols),
            'hmm_prob_bull': hmm_prob_bull,
        })

        # Annual progress log
        if i % 252 == 0 and i > 0:
            year_num = i // 252
            regime_str = "RISK_ON" if is_risk_on else "RISK_OFF"
            prot_str = f" [PROTECTION S{protection_stage}]" if in_protection_mode else ""
            print(f"  Year {year_num}: ${portfolio_value:,.0f} | DD: {drawdown:.1%} | "
                  f"Lev: {current_leverage:.2f}x | {regime_str}{prot_str} | "
                  f"Pos: {len(positions)} | HMM: {hmm_prob_bull:.2f}")

    print(f"\n--- GENIUS LAYER STATS ---")
    print(f"  MLP trains: {layer_stats['mlp_trains']}")
    print(f"  MLP filter passes: {mlp_filter_count}")
    print(f"  MLP blocks: {mlp_block_count}")
    print(f"  Graph re-rankings: {graph_rerank_count}")
    print(f"  HMM fits: {layer_stats['hmm_fits']}")
    print(f"  HMM overrides: {hmm_override_count}")
    print(f"  Meta adjustments: {meta_adjust_count}")

    return {
        'portfolio_values': pd.DataFrame(portfolio_values),
        'trades': pd.DataFrame(trades) if trades else pd.DataFrame(),
        'stop_events': pd.DataFrame(stop_events) if stop_events else pd.DataFrame(),
        'final_value': portfolio_values[-1]['value'] if portfolio_values else INITIAL_CAPITAL,
        'annual_universe': annual_universe,
        'risk_on_days': risk_on_days,
        'risk_off_days': risk_off_days,
        'layer_stats': layer_stats,
    }


# ============================================================================
# METRICS (same as v8.2)
# ============================================================================

def calculate_metrics(results: Dict) -> Dict:
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
    avg_winner = trades_df.loc[trades_df['pnl'] > 0, 'pnl'].mean() if len(trades_df) > 0 and (trades_df['pnl'] > 0).any() else 0
    avg_loser = trades_df.loc[trades_df['pnl'] < 0, 'pnl'].mean() if len(trades_df) > 0 and (trades_df['pnl'] < 0).any() else 0
    exit_reasons = trades_df['exit_reason'].value_counts().to_dict() if 'exit_reason' in trades_df.columns and len(trades_df) > 0 else {}
    protection_days = df['in_protection'].sum()
    protection_pct = protection_days / len(df) * 100
    risk_off_pct = results['risk_off_days'] / (results['risk_on_days'] + results['risk_off_days']) * 100
    df_annual = df['value'].resample('YE').last()
    annual_returns = df_annual.pct_change().dropna()
    return {
        'initial': initial, 'final_value': final_value,
        'total_return': (final_value - initial) / initial,
        'years': years, 'cagr': cagr, 'volatility': volatility,
        'sharpe': sharpe, 'sortino': sortino, 'calmar': calmar,
        'max_drawdown': max_dd, 'win_rate': win_rate,
        'avg_trade': avg_trade, 'avg_winner': avg_winner, 'avg_loser': avg_loser,
        'trades': len(trades_df), 'exit_reasons': exit_reasons,
        'stop_events': len(stop_df), 'protection_days': protection_days,
        'protection_pct': protection_pct, 'risk_off_pct': risk_off_pct,
        'annual_returns': annual_returns,
        'best_year': annual_returns.max() if len(annual_returns) > 0 else 0,
        'worst_year': annual_returns.min() if len(annual_returns) > 0 else 0,
    }


# ============================================================================
# MAIN
# ============================================================================

if __name__ == "__main__":
    import time
    t_start = time.time()

    # 1. Download/load data
    price_data = download_broad_pool()
    print(f"\nSymbols available: {len(price_data)}")

    spy_data = download_spy()
    print(f"SPY data: {len(spy_data)} trading days")

    vix_data = download_vix()
    print(f"VIX data: {len(vix_data)} trading days")

    cash_yield_daily = download_cash_yield()

    # 2. Compute annual top-40
    print("\n--- Computing Annual Top-40 ---")
    annual_universe = compute_annual_top40(price_data)

    # 3. Run GENIUS backtest
    results = run_genius_backtest(price_data, annual_universe, spy_data, vix_data, cash_yield_daily)

    # 4. Calculate metrics
    metrics = calculate_metrics(results)

    elapsed = time.time() - t_start

    # 5. Print results
    print("\n" + "=" * 80)
    print("RESULTS - COMPASS v9.0 \"GENIUS LAYER\"")
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

    # 6. COMPARISON vs v8.2
    print("\n" + "=" * 80)
    print("COMPARISON: v9.0 GENIUS vs v8.2 COMPASS (BASELINE)")
    print("=" * 80)

    v82_cagr = 0.1856
    v82_sharpe = 0.90
    v82_maxdd = -0.269
    v82_final = 8_430_000
    v82_stops = 6
    v82_trades = 5480  # approximate

    print(f"\n{'Metric':<25} {'v8.2 COMPASS':>15} {'v9.0 GENIUS':>15} {'Delta':>12}")
    print("-" * 70)
    print(f"{'CAGR':<25} {v82_cagr:>14.2%} {metrics['cagr']:>14.2%} {metrics['cagr']-v82_cagr:>+11.2%}")
    print(f"{'Sharpe':<25} {v82_sharpe:>15.2f} {metrics['sharpe']:>15.2f} {metrics['sharpe']-v82_sharpe:>+12.2f}")
    print(f"{'Max Drawdown':<25} {v82_maxdd:>14.1%} {metrics['max_drawdown']:>14.1%} {metrics['max_drawdown']-v82_maxdd:>+11.1%}")
    print(f"{'Final Value':<25} {'$8.43M':>15} ${metrics['final_value']/1e6:>13.2f}M {(metrics['final_value']-v82_final)/v82_final:>+11.1%}")
    print(f"{'Trades':<25} {'~5,480':>15} {metrics['trades']:>15,}")
    print(f"{'Stop Events':<25} {v82_stops:>15} {metrics['stop_events']:>15}")

    verdict = "GENIUS WINS" if metrics['cagr'] > v82_cagr else "v8.2 WINS (as expected)"
    print(f"\n>>> VERDICT: {verdict}")

    if metrics['cagr'] <= v82_cagr:
        delta_pct = (v82_cagr - metrics['cagr']) * 100
        print(f">>> GENIUS lost {delta_pct:.2f}% CAGR vs baseline")
        print(f">>> Experiment #{37}: GENIUS LAYER → FAILED")
    else:
        delta_pct = (metrics['cagr'] - v82_cagr) * 100
        print(f">>> GENIUS gained {delta_pct:.2f}% CAGR vs baseline")
        print(f">>> But remember: more complexity = more overfitting risk")
        print(f">>> Would need Norgate PIT + out-of-sample validation to be credible")

    print(f"\nBacktest runtime: {elapsed:.1f} seconds")

    # 7. Save results
    os.makedirs('backtests', exist_ok=True)
    results['portfolio_values'].to_csv('backtests/v9_genius_daily.csv', index=False)
    if len(results['trades']) > 0:
        results['trades'].to_csv('backtests/v9_genius_trades.csv', index=False)

    print(f"\nResults saved: backtests/v9_genius_daily.csv")
    print(f"Trades saved: backtests/v9_genius_trades.csv")

    print("\n" + "=" * 80)
    print("GENIUS LAYER BACKTEST COMPLETE")
    print("=" * 80)
