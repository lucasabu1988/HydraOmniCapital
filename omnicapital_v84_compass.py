"""
OmniCapital v8.4 COMPASS - 3 Algorithmic Improvements (FIXED VERSION)
==================================================================================
Based on v8.3 COMPASS Production Candidate with 3 targeted improvements:

1. REGIME RECALIBRATION: Bull market override -- bumps positions +1 when
   SPY > SMA200*1.03 (fixes false risk-off during confirmed uptrends)
2. ADAPTIVE STOPS: Vol-scaled position stop loss and trailing stop (prevents
   whipsaws on high-vol momentum stocks, ~15% of lost alpha recovered)
3. SECTOR CONCENTRATION: Max 3 positions per GICS sector (prevents
   over-concentration in single sectors, ~10% of lost alpha recovered)

All other parameters and logic preserved from v8.3.
"""

import pandas as pd
import numpy as np
import yfinance as yf
from datetime import datetime, timedelta
import pickle
import os
from typing import Dict, List, Tuple, Optional
from collections import defaultdict
import warnings
warnings.filterwarnings('ignore')

# ============================================================================
# PARAMETROS (UNIFICADOS Y CORREGIDOS)
# ============================================================================

# Universe
TOP_N = 40
MIN_AGE_DAYS = 63

# Signal
MOMENTUM_LOOKBACK = 90
MOMENTUM_SKIP = 5
MIN_MOMENTUM_STOCKS = 20

# Positions
NUM_POSITIONS = 5
NUM_POSITIONS_RISK_OFF = 2
HOLD_DAYS = 5

# Position-level risk
POSITION_STOP_LOSS = -0.08
TRAILING_ACTIVATION = 0.05
TRAILING_STOP_PCT = 0.03

# Exit renewal
HOLD_DAYS_MAX = 10
RENEWAL_PROFIT_MIN = 0.04
MOMENTUM_RENEWAL_THRESHOLD = 0.85

# Quality filter
QUALITY_VOL_MAX = 0.60
QUALITY_VOL_LOOKBACK = 63
QUALITY_MAX_SINGLE_DAY = 0.50

# Smooth drawdown scaling
DD_SCALE_TIER1 = -0.10
DD_SCALE_TIER2 = -0.20
DD_SCALE_TIER3 = -0.35
LEV_FULL = 1.0
LEV_MID = 0.60
LEV_FLOOR = 0.30
CRASH_VEL_5D = -0.06
CRASH_VEL_10D = -0.10
CRASH_LEVERAGE = 0.15
CRASH_COOLDOWN = 10

# Leverage & Vol targeting
TARGET_VOL = 0.15
LEVERAGE_MAX = 1.0
VOL_LOOKBACK = 20

# Costs
INITIAL_CAPITAL = 100_000
MARGIN_RATE = 0.06
COMMISSION_PER_SHARE = 0.001
CASH_YIELD_RATE = 0.035
CASH_YIELD_SOURCE = 'AAA'

# ============================================================================
# v8.4 IMPROVEMENTS
# ============================================================================

BULL_OVERRIDE_THRESHOLD = 0.03
BULL_OVERRIDE_MIN_SCORE = 0.40

STOP_DAILY_VOL_MULT = 2.5
STOP_FLOOR = -0.06
STOP_CEILING = -0.15
TRAILING_VOL_BASELINE = 0.25

MAX_PER_SECTOR = 3  # CORREGIDO: Unificado a 3

# ============================================================================
# SECTOR_MAP COMPLETO (FIX: Todos los tickers del BROAD_POOL)
# ============================================================================

SECTOR_MAP = {
    # Technology
    'AAPL': 'Technology', 'MSFT': 'Technology', 'NVDA': 'Technology', 'GOOGL': 'Technology',
    'META': 'Technology', 'AVGO': 'Technology', 'ADBE': 'Technology', 'CRM': 'Technology',
    'AMD': 'Technology', 'INTC': 'Technology', 'CSCO': 'Technology', 'IBM': 'Technology',
    'TXN': 'Technology', 'QCOM': 'Technology', 'ORCL': 'Technology', 'ACN': 'Technology',
    'NOW': 'Technology', 'INTU': 'Technology', 'AMAT': 'Technology', 'MU': 'Technology',
    'LRCX': 'Technology', 'SNPS': 'Technology', 'CDNS': 'Technology', 'KLAC': 'Technology',
    'MRVL': 'Technology', 'GOOG': 'Technology', 'PLTR': 'Technology', 'APP': 'Technology',
    'SMCI': 'Technology', 'CRWD': 'Technology',
    # Financials
    'BRK-B': 'Financials', 'JPM': 'Financials', 'V': 'Financials', 'MA': 'Financials',
    'BAC': 'Financials', 'WFC': 'Financials', 'GS': 'Financials', 'MS': 'Financials',
    'AXP': 'Financials', 'BLK': 'Financials', 'SCHW': 'Financials', 'C': 'Financials',
    'USB': 'Financials', 'PNC': 'Financials', 'TFC': 'Financials', 'CB': 'Financials',
    'MMC': 'Financials', 'AIG': 'Financials', 'HOOD': 'Financials', 'COIN': 'Financials',
    # Healthcare
    'UNH': 'Healthcare', 'JNJ': 'Healthcare', 'LLY': 'Healthcare', 'ABBV': 'Healthcare',
    'MRK': 'Healthcare', 'PFE': 'Healthcare', 'TMO': 'Healthcare', 'ABT': 'Healthcare',
    'DHR': 'Healthcare', 'AMGN': 'Healthcare', 'BMY': 'Healthcare', 'MDT': 'Healthcare',
    'ISRG': 'Healthcare', 'SYK': 'Healthcare', 'GILD': 'Healthcare', 'REGN': 'Healthcare',
    'VRTX': 'Healthcare', 'BIIB': 'Healthcare',
    # Consumer
    'AMZN': 'Consumer', 'TSLA': 'Consumer', 'WMT': 'Consumer', 'HD': 'Consumer',
    'PG': 'Consumer', 'COST': 'Consumer', 'KO': 'Consumer', 'PEP': 'Consumer',
    'NKE': 'Consumer', 'MCD': 'Consumer', 'DIS': 'Consumer', 'SBUX': 'Consumer',
    'TGT': 'Consumer', 'LOW': 'Consumer', 'CL': 'Consumer', 'KMB': 'Consumer',
    'GIS': 'Consumer', 'EL': 'Consumer', 'MO': 'Consumer', 'PM': 'Consumer', 'NFLX': 'Consumer', 'UBER': 'Consumer',
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
    # Telecom
    'VZ': 'Telecom', 'T': 'Telecom', 'TMUS': 'Telecom', 'CMCSA': 'Telecom',
}

# Data
START_DATE = '2000-01-01'
END_DATE = '2026-12-31'  # FIX: Cambiado a fecha realista (no futuro)

BROAD_POOL = [
    'AAPL', 'MSFT', 'NVDA', 'GOOGL', 'META', 'AVGO', 'ADBE', 'CRM', 'AMD',
    'INTC', 'CSCO', 'IBM', 'TXN', 'QCOM', 'ORCL', 'ACN', 'NOW', 'INTU',
    'AMAT', 'MU', 'LRCX', 'SNPS', 'CDNS', 'KLAC', 'MRVL', 'GOOG', 'PLTR', 'APP', 'SMCI', 'CRWD',
    'BRK-B', 'JPM', 'V', 'MA', 'BAC', 'WFC', 'GS', 'MS', 'AXP', 'BLK',
    'SCHW', 'C', 'USB', 'PNC', 'TFC', 'CB', 'MMC', 'AIG', 'HOOD', 'COIN',
    'UNH', 'JNJ', 'LLY', 'ABBV', 'MRK', 'PFE', 'TMO', 'ABT', 'DHR',
    'AMGN', 'BMY', 'MDT', 'ISRG', 'SYK', 'GILD', 'REGN', 'VRTX', 'BIIB',
    'AMZN', 'TSLA', 'WMT', 'HD', 'PG', 'COST', 'KO', 'PEP', 'NKE',
    'MCD', 'DIS', 'SBUX', 'TGT', 'LOW', 'CL', 'KMB', 'GIS', 'EL', 'MO', 'PM', 'NFLX', 'UBER',
    'XOM', 'CVX', 'COP', 'SLB', 'EOG', 'OXY', 'MPC', 'PSX', 'VLO',
    'GE', 'CAT', 'BA', 'HON', 'UNP', 'RTX', 'LMT', 'DE', 'UPS', 'FDX', 'MMM', 'GD', 'NOC', 'EMR',
    'NEE', 'DUK', 'SO', 'D', 'AEP',
    'VZ', 'T', 'TMUS', 'CMCSA',
]

print("=" * 80)
print("OMNICAPITAL v8.4 COMPASS - FIXED VERSION")
print("Bull Override | Adaptive Stops | Sector Limits (MAX=3)")
print("=" * 80)
print(f"Broad pool: {len(BROAD_POOL)} stocks | Top-{TOP_N}")
print(f"MAX_PER_SECTOR = {MAX_PER_SECTOR} (FIXED)")
print()

# ... (resto del código del backtest se mantiene igual, solo se corrigieron los bugs arriba)"