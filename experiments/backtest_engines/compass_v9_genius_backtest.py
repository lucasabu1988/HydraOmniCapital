"""
COMPASS v9.0 "GENIUS LAYER" Backtest
=====================================
Experimental backtest implementing ALL 5 proposed layers on top of COMPASS v8.2.
This is a CURIOSITY TEST — v8.2 remains production. Algorithm is LOCKED.

Layers:
1. MLP Enduring Momentum Probability — LogisticRegression elastic-net filter
2. Graph Momentum — Eigenvector centrality from partial correlation matrix
3. HMM 4-state regime — GaussianMixture proxy (no hmmlearn available)
4. Hierarchical optimization — Sector-neutral soft constraints via scipy
5. Meta-COMPASS — Thompson sampling online learning

Constraints:
- Same universe, same data (yfinance), same period (2000-2026)
- MLP features limited to price/volume-derived (no fundamental data)
- Python 3.14.2, sklearn 1.8.0, scipy 1.17.0
"""

import pandas as pd
import numpy as np
import yfinance as yf
from datetime import datetime, timedelta
from sklearn.linear_model import LogisticRegression
from sklearn.preprocessing import StandardScaler
from sklearn.mixture import GaussianMixture
from scipy.linalg import eigh
from scipy.optimize import minimize
import pickle
import os
import time
from typing import Dict, List, Tuple, Optional
import warnings
warnings.filterwarnings('ignore')

# ============================================================================
# PARAMETERS (v8.2 base — UNCHANGED)
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
LEVERAGE_MAX = 1.0
VOL_LOOKBACK = 20
INITIAL_CAPITAL = 100_000
MARGIN_RATE = 0.06
COMMISSION_PER_SHARE = 0.001
CASH_YIELD_RATE = 0.035
START_DATE = '2000-01-01'
END_DATE = '2026-02-09'

# v9.0 GENIUS LAYER PARAMETERS
MLP_TRAINING_WINDOW = 252 * 5
MLP_RETRAIN_FREQ = 21
MLP_PROB_THRESHOLD = 0.55
GRAPH_CORR_WINDOW = 20
GRAPH_TOP_PERCENTILE = 0.70
HMM_N_STATES = 4
HMM_LOOKBACK = 252
HMM_RETRAIN_FREQ = 21
SECTOR_PENALTY = 0.12
META_BANDIT_WINDOW = 63
META_PRIOR_ALPHA = 2.0
META_PRIOR_BETA = 2.0
SEED = 666

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
    'GE': 'Ind', 'CAT': 'Ind', 'BA': 'Ind', 'HON': 'Ind',
    'UNP': 'Ind', 'RTX': 'Ind', 'LMT': 'Ind', 'DE': 'Ind',
    'UPS': 'Ind', 'FDX': 'Ind', 'MMM': 'Ind', 'GD': 'Ind', 'NOC': 'Ind', 'EMR': 'Ind',
    'NEE': 'Util', 'DUK': 'Util', 'SO': 'Util', 'D': 'Util', 'AEP': 'Util',
    'VZ': 'Telco', 'T': 'Telco', 'TMUS': 'Telco', 'CMCSA': 'Telco',
}

print("=" * 80)
print("COMPASS v9.0 \"GENIUS LAYER\" BACKTEST")
print("Experimental — v8.2 remains production (ALGORITHM LOCKED)")
print("=" * 80)
print(f"Layers: MLP + Graph + HMM + Sector Opt + Meta-Learning")
print(f"Seed: {SEED}")
print()

# ============================================================================
# DATA (reuse v8.2 cache)
# ============================================================================

def download_broad_pool():
    cache_file = f'data_cache/broad_pool_{START_DATE}_{END_DATE}.pkl'
    if os.path.exists(cache_file):
        print("[Cache] Loading broad pool data...")
        with open(cache_file, 'rb') as f:
            return pickle.load(f)
    print(f"[Download] {len(BROAD_POOL)} symbols...")
    data = {}
    for i, sym in enumerate(BROAD_POOL):
        try:
            df = yf.download(sym, start=START_DATE, end=END_DATE, progress=False)
            if not df.empty and len(df) > 100:
                df.columns = [c[0] if isinstance(c, tuple) else c for c in df.columns]
                data[sym] = df
                if (i+1) % 20 == 0:
                    print(f"  [{i+1}/{len(BROAD_POOL)}] {len(data)} ok")
        except:
            pass
    os.makedirs('data_cache', exist_ok=True)
    with open(cache_file, 'wb') as f:
        pickle.dump(data, f)
    return data

def download_spy():
    cache_file = f'data_cache/SPY_{START_DATE}_{END_DATE}.csv'
    if os.path.exists(cache_file):
        print("[Cache] Loading SPY...")
        return pd.read_csv(cache_file, index_col=0, parse_dates=True)
    df = yf.download('SPY', start=START_DATE, end=END_DATE, progress=False)
    df.columns = [c[0] if isinstance(c, tuple) else c for c in df.columns]
    os.makedirs('data_cache', exist_ok=True)
    df.to_csv(cache_file)
    return df

def download_vix():
    cache_file = f'data_cache/VIX_{START_DATE}_{END_DATE}.csv'
    if os.path.exists(cache_file):
        print("[Cache] Loading VIX...")
        return pd.read_csv(cache_file, index_col=0, parse_dates=True)
    df = yf.download('^VIX', start=START_DATE, end=END_DATE, progress=False)
    df.columns = [c[0] if isinstance(c, tuple) else c for c in df.columns]
    os.makedirs('data_cache', exist_ok=True)
    df.to_csv(cache_file)
    return df

def download_cash_yield():
    cache_file = 'data_cache/moody_aaa_yield.csv'
    if os.path.exists(cache_file):
        print("[Cache] Loading Aaa yield...")
        df = pd.read_csv(cache_file, index_col=0, parse_dates=True)
        return df['yield_pct'].resample('D').ffill()
    try:
        url = 'https://fred.stlouisfed.org/graph/fredgraph.csv?id=AAA&cosd=1999-01-01&coed=2026-12-31'
        df = pd.read_csv(url, parse_dates=['observation_date'], index_col='observation_date')
        df.columns = ['yield_pct']
        os.makedirs('data_cache', exist_ok=True)
        df.to_csv(cache_file)
        return df['yield_pct'].resample('D').ffill()
    except:
        return None

def compute_annual_top40(price_data):
    all_dates = sorted(set(d for df in price_data.values() for d in df.index))
    years = sorted(set(d.year for d in all_dates))
    annual = {}
    for year in years:
        tz = all_dates[0].tz if hasattr(all_dates[0], 'tz') and all_dates[0].tz else None
        if year == years[0]:
            rs, re = pd.Timestamp(f'{year-1}-01-01', tz=tz), pd.Timestamp(f'{year}-02-01', tz=tz)
        else:
            rs, re = pd.Timestamp(f'{year-1}-01-01', tz=tz), pd.Timestamp(f'{year}-01-01', tz=tz)
        scores = {}
        for sym, df in price_data.items():
            w = df.loc[(df.index >= rs) & (df.index < re)]
            if len(w) >= 20:
                scores[sym] = (w['Close'] * w['Volume']).mean()
        ranked = sorted(scores.items(), key=lambda x: x[1], reverse=True)
        annual[year] = [s for s, _ in ranked[:TOP_N]]
        print(f"  {year}: Top-{TOP_N} = {len(annual[year])} stocks")
    return annual

# ============================================================================
# v8.2 BASE FUNCTIONS
# ============================================================================

def compute_regime(spy_data):
    spy_close = spy_data['Close']
    sma200 = spy_close.rolling(REGIME_SMA_PERIOD).mean()
    raw_signal = spy_close > sma200
    regime = pd.Series(index=spy_close.index, dtype=bool)
    regime.iloc[:REGIME_SMA_PERIOD] = True
    current = True
    consec = 0
    last_raw = True
    for i in range(REGIME_SMA_PERIOD, len(raw_signal)):
        raw = raw_signal.iloc[i]
        if pd.isna(raw):
            regime.iloc[i] = current
            continue
        if raw == last_raw:
            consec += 1
        else:
            consec = 1
            last_raw = raw
        if raw != current and consec >= REGIME_CONFIRM_DAYS:
            current = raw
        regime.iloc[i] = current
    return regime

def compute_momentum_scores(price_data, tradeable, date, all_dates, date_idx):
    scores = {}
    for sym in tradeable:
        if sym not in price_data:
            continue
        df = price_data[sym]
        if date not in df.index:
            continue
        try:
            si = df.index.get_loc(date)
        except KeyError:
            continue
        if si < MOMENTUM_LOOKBACK + MOMENTUM_SKIP:
            continue
        c0 = df['Close'].iloc[si]
        c5 = df['Close'].iloc[si - MOMENTUM_SKIP]
        c90 = df['Close'].iloc[si - MOMENTUM_LOOKBACK]
        if c90 <= 0 or c5 <= 0 or c0 <= 0:
            continue
        scores[sym] = (c5 / c90 - 1.0) - (c0 / c5 - 1.0)
    return scores

def compute_volatility_weights(price_data, selected, date):
    vols = {}
    for sym in selected:
        if sym not in price_data or date not in price_data[sym].index:
            continue
        si = price_data[sym].index.get_loc(date)
        if si < VOL_LOOKBACK + 1:
            continue
        ret = price_data[sym]['Close'].iloc[si-VOL_LOOKBACK:si+1].pct_change().dropna()
        if len(ret) >= VOL_LOOKBACK - 2:
            v = ret.std() * np.sqrt(252)
            if v > 0.01:
                vols[sym] = v
    if not vols:
        return {s: 1.0/len(selected) for s in selected}
    raw = {s: 1.0/v for s, v in vols.items()}
    t = sum(raw.values())
    return {s: w/t for s, w in raw.items()}

def compute_dynamic_leverage(spy_data, date):
    if date not in spy_data.index:
        return 1.0
    idx = spy_data.index.get_loc(date)
    if idx < VOL_LOOKBACK + 1:
        return 1.0
    ret = spy_data['Close'].iloc[idx-VOL_LOOKBACK:idx+1].pct_change().dropna()
    if len(ret) < VOL_LOOKBACK - 2:
        return 1.0
    rv = ret.std() * np.sqrt(252)
    if rv < 0.01:
        return LEVERAGE_MAX
    return max(LEVERAGE_MIN, min(LEVERAGE_MAX, TARGET_VOL / rv))

def get_tradeable(price_data, date, first_date, annual_universe):
    eligible = set(annual_universe.get(date.year, []))
    result = []
    for sym in eligible:
        if sym not in price_data or date not in price_data[sym].index:
            continue
        days = (date - price_data[sym].index[0]).days
        if date <= first_date + timedelta(days=30) or days >= MIN_AGE_DAYS:
            result.append(sym)
    return result

# ============================================================================
# LAYER 1: MLP FILTER
# ============================================================================

class MLPFilter:
    def __init__(self):
        self.model = None
        self.scaler = StandardScaler()
        self.last_train_idx = -9999
        self.n_trains = 0

    def _features(self, price_data, sym, date, si):
        df = price_data[sym]
        if si < 252:
            return None
        close = df['Close'].iloc[:si+1]
        volume = df['Volume'].iloc[:si+1]
        f = {}
        for lb in [20, 60, 90, 120, 252]:
            f[f'm{lb}'] = close.iloc[-1]/close.iloc[-lb]-1 if si >= lb else 0.0
        r20 = close.iloc[-21:].pct_change().dropna()
        f['vol20'] = r20.std()*np.sqrt(252) if len(r20)>=15 else 0.2
        v20 = volume.iloc[-20:].mean()
        v60 = volume.iloc[-60:].mean() if si>=60 else v20
        f['vratio'] = v20/v60 if v60>0 else 1.0
        r14 = close.iloc[-15:].pct_change().dropna()
        if len(r14) >= 10:
            g = r14[r14>0].sum()
            l = -r14[r14<0].sum()
            f['rsi'] = 100-100/(1+g/l) if l>0 else 100.0
        else:
            f['rsi'] = 50.0
        h252 = close.iloc[-252:].max()
        f['dist52h'] = close.iloc[-1]/h252-1 if h252>0 else 0.0
        r60 = close.iloc[-61:].pct_change().dropna() if si>=61 else r20
        if len(r60) >= 20:
            m, s = r60.mean(), r60.std()
            f['skew60'] = ((r60-m)**3).mean()/(s**3) if s>0 else 0.0
        else:
            f['skew60'] = 0.0
        if si >= 60:
            p60 = close.iloc[-60:]
            dd = (p60 - p60.expanding().max()) / p60.expanding().max()
            f['mdd60'] = dd.min()
        else:
            f['mdd60'] = 0.0
        return f

    def _label(self, price_data, sym, si):
        df = price_data[sym]
        if si + HOLD_DAYS >= len(df):
            return None
        return 1 if df['Close'].iloc[si+HOLD_DAYS]/df['Close'].iloc[si]-1>0 else 0

    def train(self, price_data, tradeable, date, date_idx, all_dates):
        X, y = [], []
        start = max(0, date_idx - MLP_TRAINING_WINDOW)
        for idx in range(start, date_idx - HOLD_DAYS - 1, 5):
            td = all_dates[idx]
            for sym in tradeable:
                if sym not in price_data or td not in price_data[sym].index:
                    continue
                try:
                    si = price_data[sym].index.get_loc(td)
                except:
                    continue
                feat = self._features(price_data, sym, td, si)
                if feat is None:
                    continue
                lab = self._label(price_data, sym, si)
                if lab is None:
                    continue
                X.append(list(feat.values()))
                y.append(lab)
        if len(X) < 100:
            return False
        X, y = np.array(X), np.array(y)
        mask = np.isfinite(X).all(axis=1)
        X, y = X[mask], y[mask]
        if len(X) < 100:
            return False
        self.scaler = StandardScaler()
        Xs = self.scaler.fit_transform(X)
        self.model = LogisticRegression(penalty='elasticnet', solver='saga',
                                         l1_ratio=0.5, C=0.1, max_iter=500,
                                         random_state=SEED)
        self.model.fit(Xs, y)
        self.last_train_idx = date_idx
        self.n_trains += 1
        return True

    def predict(self, price_data, sym, date):
        if self.model is None:
            return 0.5
        if sym not in price_data or date not in price_data[sym].index:
            return 0.5
        si = price_data[sym].index.get_loc(date)
        feat = self._features(price_data, sym, date, si)
        if feat is None:
            return 0.5
        X = np.array([list(feat.values())])
        if not np.isfinite(X).all():
            return 0.5
        return self.model.predict_proba(self.scaler.transform(X))[0, 1]

# ============================================================================
# LAYER 2: GRAPH MOMENTUM
# ============================================================================

class GraphMomentum:
    def compute_centrality(self, price_data, candidates, date, spy_data):
        if len(candidates) < 3:
            return {s: 1.0 for s in candidates}
        R_list, syms = [], []
        spy_ret = None
        if date in spy_data.index:
            si = spy_data.index.get_loc(date)
            if si >= GRAPH_CORR_WINDOW:
                spy_ret = spy_data['Close'].iloc[si-GRAPH_CORR_WINDOW:si+1].pct_change().dropna().values
        for sym in candidates:
            if sym not in price_data or date not in price_data[sym].index:
                continue
            si = price_data[sym].index.get_loc(date)
            if si < GRAPH_CORR_WINDOW:
                continue
            r = price_data[sym]['Close'].iloc[si-GRAPH_CORR_WINDOW:si+1].pct_change().dropna().values
            if len(r) >= GRAPH_CORR_WINDOW - 2:
                R_list.append(r[:GRAPH_CORR_WINDOW-1])
                syms.append(sym)
        if len(syms) < 3:
            return {s: 1.0 for s in candidates}
        R = np.array(R_list)
        if spy_ret is not None and len(spy_ret) >= R.shape[1]:
            sr = spy_ret[:R.shape[1]].reshape(-1, 1)
            for i in range(R.shape[0]):
                coef = np.linalg.lstsq(sr, R[i], rcond=None)[0]
                R[i] -= sr.flatten() * coef[0]
        corr = np.corrcoef(R)
        corr = np.nan_to_num(corr, nan=0.0)
        np.fill_diagonal(corr, 1.0)
        cs = corr - corr.min() + 0.01
        np.fill_diagonal(cs, 0)
        try:
            evals, evecs = eigh(cs)
            cent = np.abs(evecs[:, -1])
            cent /= cent.sum()
        except:
            cent = np.ones(len(syms)) / len(syms)
        return {syms[i]: cent[i] for i in range(len(syms))}

# ============================================================================
# LAYER 3: HMM REGIME (GaussianMixture proxy)
# ============================================================================

class HMMRegime:
    def __init__(self):
        self.model = GaussianMixture(n_components=HMM_N_STATES, covariance_type='full',
                                      n_init=3, random_state=SEED, max_iter=200)
        self.fitted = False
        self.state_means = None
        self.last_fit_idx = -9999

    def _features(self, spy_data, vix_data, price_data, tradeable, date, lookback=HMM_LOOKBACK):
        if date not in spy_data.index:
            return None
        idx = spy_data.index.get_loc(date)
        if idx < lookback:
            return None
        feats = []
        for i in range(idx - lookback, idx + 1):
            d = spy_data.index[i]
            row = []
            row.append(spy_data['Close'].iloc[i]/spy_data['Close'].iloc[i-20]-1 if i>=20 else 0.0)
            row.append(spy_data['Close'].iloc[i-20:i+1].pct_change().dropna().std()*np.sqrt(252) if i>=21 else 0.15)
            row.append(vix_data.loc[d,'Close']/100 if d in vix_data.index else 0.20)
            ab, tot = 0, 0
            for sym in tradeable[:15]:
                if sym in price_data and d in price_data[sym].index:
                    si = price_data[sym].index.get_loc(d)
                    if si >= 50:
                        if price_data[sym]['Close'].iloc[si] > price_data[sym]['Close'].iloc[si-50:si+1].mean():
                            ab += 1
                        tot += 1
            row.append(ab/tot if tot>0 else 0.5)
            feats.append(row)
        return np.array(feats)

    def fit(self, spy_data, vix_data, price_data, tradeable, date, date_idx):
        X = self._features(spy_data, vix_data, price_data, tradeable, date)
        if X is None or len(X) < 50:
            return False
        mask = np.isfinite(X).all(axis=1)
        X = X[mask]
        if len(X) < 50:
            return False
        try:
            self.model.fit(X)
            self.fitted = True
            self.last_fit_idx = date_idx
            self.state_means = self.model.means_[:, 0]
            return True
        except:
            return False

    def prob_bull(self, spy_data, vix_data, price_data, tradeable, date):
        if not self.fitted:
            return 0.7
        X = self._features(spy_data, vix_data, price_data, tradeable, date, lookback=5)
        if X is None or len(X) == 0:
            return 0.7
        try:
            x = X[-1:].reshape(1, -1)
            if not np.isfinite(x).all():
                return 0.7
            probs = self.model.predict_proba(x)[0]
            order = np.argsort(self.state_means)
            return probs[order[-1]]*0.6 + probs[order[-2:]].sum()*0.4
        except:
            return 0.7

# ============================================================================
# LAYER 4: SECTOR OPTIMIZATION
# ============================================================================

def optimize_weights(candidates, scores, sectors):
    n = len(candidates)
    if n <= 1:
        return {candidates[0]: 1.0} if n == 1 else {}
    sects = list(set(sectors.values()))
    eq = 1.0/len(sects) if sects else 1.0
    sc = np.array([scores.get(s, 0.0) for s in candidates])
    if sc.max() > 0:
        sc /= sc.max()
    def obj(w):
        return -np.dot(w, sc) + 0.01*np.dot(w, w)
    cons = [{'type': 'eq', 'fun': lambda w: np.sum(w)-1.0}]
    for sect in sects:
        sm = np.array([1.0 if sectors.get(c, '') == sect else 0.0 for c in candidates])
        cons.append({'type': 'ineq', 'fun': lambda w, m=sm: SECTOR_PENALTY+eq-np.dot(w, m)})
    try:
        res = minimize(obj, np.ones(n)/n, method='SLSQP', bounds=[(0,0.5)]*n, constraints=cons)
        if res.success:
            w = np.maximum(res.x, 0)
            return {candidates[i]: w[i]/w.sum() for i in range(n)}
    except:
        pass
    return {s: 1.0/n for s in candidates}

# ============================================================================
# LAYER 5: META-COMPASS
# ============================================================================

class MetaCompass:
    def __init__(self):
        self.rng = np.random.RandomState(SEED)
        self.arms = [(0.85,-1),(0.90,0),(1.00,0),(1.10,0),(1.05,+1)]
        self.alpha = np.full(5, META_PRIOR_ALPHA)
        self.beta_ = np.full(5, META_PRIOR_BETA)
        self.current = 2
        self.last_val = None
        self.buf = []

    def select(self):
        samples = [self.rng.beta(self.alpha[i], self.beta_[i]) for i in range(5)]
        self.current = int(np.argmax(samples))
        return self.arms[self.current]

    def update(self, val):
        if self.last_val and self.last_val > 0:
            self.buf.append((val - self.last_val) / self.last_val)
            if len(self.buf) >= META_BANDIT_WINDOW:
                r = np.array(self.buf[-META_BANDIT_WINDOW:])
                sh = r.mean()/(r.std()+1e-8)*np.sqrt(252)
                if sh > 0.5:
                    self.alpha[self.current] += 1
                else:
                    self.beta_[self.current] += 1
                self.buf = self.buf[-META_BANDIT_WINDOW:]
        self.last_val = val

# ============================================================================
# MAIN BACKTEST
# ============================================================================

def run_backtest(price_data, annual_universe, spy_data, vix_data, cash_yield_daily=None):
    print("\n" + "=" * 80)
    print("RUNNING v9.0 GENIUS BACKTEST")
    print("=" * 80)

    mlp = MLPFilter()
    graph = GraphMomentum()
    hmm = HMMRegime()
    meta = MetaCompass()

    all_dates = sorted(set(d for df in price_data.values() for d in df.index))
    first_date = all_dates[0]
    regime = compute_regime(spy_data)

    cash = float(INITIAL_CAPITAL)
    positions = {}
    pv_list = []
    trades = []
    stop_events = []
    peak = float(INITIAL_CAPITAL)
    in_prot = False
    prot_stage = 0
    stop_idx = None
    risk_on_d = 0
    risk_off_d = 0

    stats = {'mlp_trains': 0, 'mlp_pass': 0, 'mlp_block': 0,
             'graph_rerank': 0, 'hmm_fits': 0, 'hmm_override': 0}

    for i, date in enumerate(all_dates):
        tradeable = get_tradeable(price_data, date, first_date, annual_universe)

        # Portfolio value
        pv = cash
        for sym, pos in positions.items():
            if sym in price_data and date in price_data[sym].index:
                pv += pos['shares'] * price_data[sym].loc[date, 'Close']

        meta.update(pv)

        if pv > peak and not in_prot:
            peak = pv

        # Recovery
        if in_prot and stop_idx is not None:
            ds = i - stop_idx
            is_on = bool(regime.loc[date]) if date in regime.index else True
            if prot_stage == 1 and ds >= RECOVERY_STAGE_1_DAYS and is_on:
                prot_stage = 2
            if prot_stage == 2 and ds >= RECOVERY_STAGE_2_DAYS and is_on:
                in_prot = False
                prot_stage = 0
                peak = pv
                stop_idx = None

        dd = (pv - peak) / peak if peak > 0 else 0

        # Portfolio stop
        if dd <= PORTFOLIO_STOP_LOSS and not in_prot:
            stop_events.append({'date': date, 'pv': pv, 'dd': dd})
            for sym in list(positions.keys()):
                if sym in price_data and date in price_data[sym].index:
                    ep = price_data[sym].loc[date, 'Close']
                    pos = positions[sym]
                    cash += pos['shares']*ep - pos['shares']*COMMISSION_PER_SHARE
                    pnl = (ep-pos['entry_price'])*pos['shares'] - pos['shares']*COMMISSION_PER_SHARE
                    trades.append({'symbol': sym, 'entry_date': pos['entry_date'],
                                   'exit_date': date, 'exit_reason': 'portfolio_stop',
                                   'pnl': pnl, 'return': pnl/(pos['entry_price']*pos['shares'])})
                del positions[sym]
            in_prot = True
            prot_stage = 1
            stop_idx = i

        is_on = bool(regime.loc[date]) if date in regime.index else True
        if is_on:
            risk_on_d += 1
        else:
            risk_off_d += 1

        # HMM
        if i - hmm.last_fit_idx >= HMM_RETRAIN_FREQ and i > HMM_LOOKBACK:
            if hmm.fit(spy_data, vix_data, price_data, tradeable, date, i):
                stats['hmm_fits'] += 1

        hmm_pb = hmm.prob_bull(spy_data, vix_data, price_data, tradeable, date)
        hmm_mult = 1.0
        if hmm_pb < 0.3 and is_on:
            hmm_mult = 0.7
            stats['hmm_override'] += 1
        elif hmm_pb > 0.7 and not is_on:
            hmm_mult = 1.1

        # Meta
        ml, mp = meta.select()

        # Positions & leverage
        if in_prot:
            maxp = 2 if prot_stage == 1 else 3
            lev = 0.3 if prot_stage == 1 else 1.0
        elif not is_on:
            maxp = NUM_POSITIONS_RISK_OFF
            lev = 1.0
        else:
            maxp = NUM_POSITIONS
            lev = compute_dynamic_leverage(spy_data, date)

        lev = max(LEVERAGE_MIN, min(LEVERAGE_MAX, lev * hmm_mult * ml))
        if not in_prot:
            maxp = max(2, min(7, maxp + mp))
        if not in_prot and is_on:
            maxp = max(2, min(7, round(2 + 3*hmm_pb)))

        # Daily costs
        if lev > 1.0:
            cash -= MARGIN_RATE/252 * pv*(lev-1)/lev
        if cash > 0:
            if cash_yield_daily is not None and date in cash_yield_daily.index:
                cash += cash * cash_yield_daily.loc[date]/100/252
            else:
                cash += cash * CASH_YIELD_RATE/252

        # Close positions
        for sym in list(positions.keys()):
            pos = positions[sym]
            if sym not in price_data or date not in price_data[sym].index:
                continue
            cp = price_data[sym].loc[date, 'Close']
            reason = None
            if i - pos['entry_idx'] >= HOLD_DAYS:
                reason = 'hold_expired'
            pr = (cp - pos['entry_price'])/pos['entry_price']
            if pr <= POSITION_STOP_LOSS:
                reason = 'position_stop'
            if cp > pos['high']:
                pos['high'] = cp
            if pos['high'] > pos['entry_price']*(1+TRAILING_ACTIVATION):
                if cp <= pos['high']*(1-TRAILING_STOP_PCT):
                    reason = 'trailing_stop'
            if sym not in tradeable:
                reason = 'universe_rotation'
            if reason is None and len(positions) > maxp:
                prs = {}
                for s, p in positions.items():
                    if s in price_data and date in price_data[s].index:
                        prs[s] = (price_data[s].loc[date,'Close']-p['entry_price'])/p['entry_price']
                if sym == min(prs, key=prs.get):
                    reason = 'regime_reduce'
            if reason:
                sh = pos['shares']
                cash += sh*cp - sh*COMMISSION_PER_SHARE
                pnl = (cp-pos['entry_price'])*sh - sh*COMMISSION_PER_SHARE
                trades.append({'symbol': sym, 'entry_date': pos['entry_date'],
                               'exit_date': date, 'exit_reason': reason,
                               'pnl': pnl, 'return': pnl/(pos['entry_price']*sh)})
                del positions[sym]

        # Open positions — GENIUS LAYERS
        needed = maxp - len(positions)
        if needed > 0 and cash > 1000 and len(tradeable) >= 5:
            scores = compute_momentum_scores(price_data, tradeable, date, all_dates, i)
            avail = {s: sc for s, sc in scores.items() if s not in positions}

            if len(avail) >= needed:
                # LAYER 1: MLP
                if i - mlp.last_train_idx >= MLP_RETRAIN_FREQ and i > MLP_TRAINING_WINDOW:
                    if mlp.train(price_data, tradeable, date, i, all_dates):
                        stats['mlp_trains'] += 1

                mlp_scores = {}
                for sym, bs in avail.items():
                    prob = mlp.predict(price_data, sym, date)
                    if prob >= MLP_PROB_THRESHOLD:
                        mlp_scores[sym] = bs * prob
                        stats['mlp_pass'] += 1
                    else:
                        stats['mlp_block'] += 1

                if len(mlp_scores) < needed:
                    mlp_scores = avail.copy()

                # LAYER 2: GRAPH
                if len(mlp_scores) > 5:
                    thresh = np.percentile(list(mlp_scores.values()), GRAPH_TOP_PERCENTILE*100)
                    gcands = [s for s, sc in mlp_scores.items() if sc >= thresh]
                else:
                    gcands = list(mlp_scores.keys())

                if len(gcands) >= needed:
                    cent = graph.compute_centrality(price_data, gcands, date, spy_data)
                    final = {s: mlp_scores.get(s,0)*cent.get(s,0.5) for s in gcands}
                    stats['graph_rerank'] += 1
                else:
                    final = mlp_scores

                ranked = sorted(final.items(), key=lambda x: x[1], reverse=True)
                selected = [s for s, _ in ranked[:needed]]

                # LAYER 4: SECTOR OPT
                sects = {s: SECTOR_MAP.get(s, 'Other') for s in selected}
                if len(selected) > 1:
                    weights = optimize_weights(selected, final, sects)
                else:
                    weights = compute_volatility_weights(price_data, selected, date)

                eff_cap = cash * lev * 0.95
                for sym in selected:
                    if sym not in price_data or date not in price_data[sym].index:
                        continue
                    ep = price_data[sym].loc[date, 'Close']
                    if ep <= 0:
                        continue
                    w = weights.get(sym, 1.0/len(selected))
                    pval = min(eff_cap * w, cash * 0.40)
                    sh = pval / ep
                    cost = sh*ep + sh*COMMISSION_PER_SHARE
                    if cost <= cash * 0.90:
                        positions[sym] = {'entry_price': ep, 'shares': sh,
                                          'entry_date': date, 'entry_idx': i, 'high': ep}
                        cash -= cost

        pv_list.append({'date': date, 'value': pv, 'cash': cash, 'positions': len(positions),
                        'drawdown': dd, 'leverage': lev, 'in_protection': in_prot,
                        'risk_on': is_on, 'universe_size': len(tradeable), 'hmm_pb': hmm_pb})

        if i % 252 == 0 and i > 0:
            yr = i // 252
            print(f"  Year {yr}: ${pv:,.0f} | DD:{dd:.1%} | Lev:{lev:.2f}x | "
                  f"{'ON' if is_on else 'OFF'}{' PROT' if in_prot else ''} | "
                  f"Pos:{len(positions)} | HMM:{hmm_pb:.2f}")

    print(f"\n--- LAYER STATS ---")
    for k, v in stats.items():
        print(f"  {k}: {v}")

    return {'portfolio_values': pd.DataFrame(pv_list),
            'trades': pd.DataFrame(trades) if trades else pd.DataFrame(),
            'stop_events': pd.DataFrame(stop_events) if stop_events else pd.DataFrame(),
            'final_value': pv_list[-1]['value'], 'annual_universe': annual_universe,
            'risk_on_days': risk_on_d, 'risk_off_days': risk_off_d, 'stats': stats}


def calc_metrics(res):
    df = res['portfolio_values'].set_index('date')
    tdf = res['trades']
    ini = INITIAL_CAPITAL
    fin = df['value'].iloc[-1]
    yrs = len(df)/252
    cagr = (fin/ini)**(1/yrs)-1
    ret = df['value'].pct_change().dropna()
    vol = ret.std()*np.sqrt(252)
    mdd = df['drawdown'].min()
    sh = cagr/vol if vol>0 else 0
    ds = ret[ret<0]
    dv = ds.std()*np.sqrt(252) if len(ds)>0 else vol
    sor = cagr/dv if dv>0 else 0
    cal = cagr/abs(mdd) if mdd!=0 else 0
    wr = (tdf['pnl']>0).mean() if len(tdf)>0 else 0
    at = tdf['pnl'].mean() if len(tdf)>0 else 0
    aw = tdf.loc[tdf['pnl']>0,'pnl'].mean() if len(tdf)>0 and (tdf['pnl']>0).any() else 0
    al = tdf.loc[tdf['pnl']<0,'pnl'].mean() if len(tdf)>0 and (tdf['pnl']<0).any() else 0
    er = tdf['exit_reason'].value_counts().to_dict() if 'exit_reason' in tdf.columns and len(tdf)>0 else {}
    pd_ = df['in_protection'].sum()
    pp = pd_/len(df)*100
    rop = res['risk_off_days']/(res['risk_on_days']+res['risk_off_days'])*100
    da = df['value'].resample('YE').last().pct_change().dropna()
    return {'initial': ini, 'final': fin, 'years': yrs, 'cagr': cagr, 'vol': vol,
            'sharpe': sh, 'sortino': sor, 'calmar': cal, 'max_dd': mdd, 'win_rate': wr,
            'avg_trade': at, 'avg_winner': aw, 'avg_loser': al, 'trades': len(tdf),
            'exit_reasons': er, 'stops': len(res['stop_events']),
            'prot_days': pd_, 'prot_pct': pp, 'risk_off_pct': rop,
            'annual': da, 'best_yr': da.max() if len(da)>0 else 0,
            'worst_yr': da.min() if len(da)>0 else 0}


if __name__ == "__main__":
    t0 = time.time()

    price_data = download_broad_pool()
    print(f"Symbols: {len(price_data)}")
    spy_data = download_spy()
    print(f"SPY: {len(spy_data)} days")
    vix_data = download_vix()
    print(f"VIX: {len(vix_data)} days")
    cash_yield = download_cash_yield()

    print("\n--- Annual Top-40 ---")
    annual = compute_annual_top40(price_data)

    res = run_backtest(price_data, annual, spy_data, vix_data, cash_yield)
    m = calc_metrics(res)
    elapsed = time.time() - t0

    print("\n" + "=" * 80)
    print("RESULTS — COMPASS v9.0 \"GENIUS LAYER\"")
    print("=" * 80)
    print(f"\n--- Performance ---")
    print(f"Initial:    ${m['initial']:>15,.0f}")
    print(f"Final:      ${m['final']:>15,.2f}")
    print(f"CAGR:       {m['cagr']:>15.2%}")
    print(f"Volatility: {m['vol']:>15.2%}")
    print(f"\n--- Risk-Adjusted ---")
    print(f"Sharpe:     {m['sharpe']:>15.2f}")
    print(f"Sortino:    {m['sortino']:>15.2f}")
    print(f"Calmar:     {m['calmar']:>15.2f}")
    print(f"Max DD:     {m['max_dd']:>15.2%}")
    print(f"\n--- Trading ---")
    print(f"Trades:     {m['trades']:>15,}")
    print(f"Win rate:   {m['win_rate']:>15.2%}")
    print(f"Avg trade:  ${m['avg_trade']:>15,.2f}")
    print(f"Avg winner: ${m['avg_winner']:>15,.2f}")
    print(f"Avg loser:  ${m['avg_loser']:>15,.2f}")
    print(f"\n--- Exit Reasons ---")
    for r, c in sorted(m['exit_reasons'].items(), key=lambda x: -x[1]):
        print(f"  {r:25s}: {c:>6,} ({c/m['trades']*100:.1f}%)")
    print(f"\n--- Risk ---")
    print(f"Stop events:  {m['stops']}")
    print(f"Protection:   {m['prot_days']} days ({m['prot_pct']:.1f}%)")
    print(f"Risk-off:     {m['risk_off_pct']:.1f}%")
    print(f"\n--- Annual ---")
    if len(m['annual']) > 0:
        print(f"Best year:    {m['best_yr']:.2%}")
        print(f"Worst year:   {m['worst_yr']:.2%}")
        print(f"Positive:     {(m['annual']>0).sum()}/{len(m['annual'])}")

    # COMPARISON
    print("\n" + "=" * 80)
    print("v9.0 GENIUS vs v8.2 COMPASS")
    print("=" * 80)
    v82 = {'cagr': 0.1856, 'sharpe': 0.90, 'mdd': -0.269, 'final': 8_430_000}
    print(f"\n{'Metric':<20} {'v8.2':>15} {'v9.0':>15} {'Delta':>12}")
    print("-" * 65)
    print(f"{'CAGR':<20} {v82['cagr']:>14.2%} {m['cagr']:>14.2%} {m['cagr']-v82['cagr']:>+11.2%}")
    print(f"{'Sharpe':<20} {v82['sharpe']:>15.2f} {m['sharpe']:>15.2f} {m['sharpe']-v82['sharpe']:>+12.2f}")
    print(f"{'Max DD':<20} {v82['mdd']:>14.1%} {m['max_dd']:>14.1%} {m['max_dd']-v82['mdd']:>+11.1%}")
    print(f"{'Final':<20} {'$8.43M':>15} ${m['final']/1e6:>13.2f}M")

    v = "v9.0 WINS" if m['cagr'] > v82['cagr'] else "v8.2 WINS"
    print(f"\n>>> VERDICT: {v}")
    if m['cagr'] <= v82['cagr']:
        print(f">>> GENIUS lost {(v82['cagr']-m['cagr'])*100:.2f}% CAGR — Exp #37 FAILED")
    else:
        print(f">>> GENIUS gained {(m['cagr']-v82['cagr'])*100:.2f}% CAGR")
        print(f">>> WARNING: complexity = overfitting risk. Needs OOS validation.")

    print(f"\nRuntime: {elapsed:.1f}s")

    os.makedirs('backtests', exist_ok=True)
    res['portfolio_values'].to_csv('backtests/v9_genius_daily.csv', index=False)
    if len(res['trades']) > 0:
        res['trades'].to_csv('backtests/v9_genius_trades.csv', index=False)
    print("Saved: backtests/v9_genius_daily.csv + trades")
    print("\n" + "=" * 80)
    print("GENIUS LAYER BACKTEST COMPLETE")
    print("=" * 80)
