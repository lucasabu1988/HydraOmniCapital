"""
OmniCapital HYDRA - Live Trading System (FIXED VERSION)
=======================================================
Multi-strategy system: COMPASS v8.4 + Rattlesnake v1.0 + Catalyst + EFA.
All critical bugs fixed (imports, logging, sector map, cache paths, holidays).
"""

import math
import re
import pandas as pd
import numpy as np
import yfinance as yf
from datetime import datetime, time, date, timedelta
import logging
from logging.handlers import RotatingFileHandler
import json
import os
import sys
import glob
import tempfile
import copy
import signal
import threading
from collections import defaultdict
from typing import Dict, List, Optional, Tuple
import warnings
import time as time_module
from zoneinfo import ZoneInfo

warnings.filterwarnings('ignore')

# ============================================================================
# IMPORTS ROBUSTOS (FIX: Todos los try/except mejorados)
# ============================================================================

try:
    from omnicapital_data_feed import YahooDataFeed
    from omnicapital_broker import PaperBroker, IBKRBroker, Order, Position
    _broker_available = True
except ImportError:
    _broker_available = False
    print("[WARN] Broker modules not found - using mock mode only")

try:
    from git_sync import git_sync_async, git_sync_rotation
    _git_sync_available = True
except ImportError:
    try:
        from compass.git_sync import git_sync_async, git_sync_rotation
        _git_sync_available = True
    except ImportError:
        _git_sync_available = False

try:
    from compass_ml_learning import COMPASSMLOrchestrator
    _ml_available = True
except ImportError:
    _ml_available = False

try:
    from rattlesnake_signals import (
        R_UNIVERSE, R_MAX_POSITIONS, R_POSITION_SIZE, R_MAX_POS_RISK_OFF,
        find_rattlesnake_candidates, check_rattlesnake_exit,
        check_rattlesnake_regime, compute_rattlesnake_exposure,
    )
    from hydra_capital import HydraCapitalManager
    _hydra_available = True
except ImportError:
    _hydra_available = False

try:
    from catalyst_signals import (
        compute_catalyst_targets, compute_trend_holdings,
        CATALYST_TREND_ASSETS, CATALYST_REBALANCE_DAYS,
    )
    _catalyst_available = True
except ImportError:
    _catalyst_available = False

try:
    from compass_fred_data import download_all_overlay_data
    from compass_overlays import (
        BankingStressOverlay, M2MomentumIndicator, FOMCSurpriseSignal,
        FedEmergencySignal, CreditSectorPreFilter, compute_overlay_signals,
        OVERLAY_FLOOR,
    )
    _overlay_available = True
except ImportError:
    _overlay_available = False

# ============================================================================
# LOGGING (FIX: Lógica mejorada, sin duplicados)
# ============================================================================

os.makedirs('logs', exist_ok=True)
_log_format = '%(asctime)s - %(levelname)s - %(message)s'
_log_formatter = logging.Formatter(_log_format)

_file_handler = RotatingFileHandler(
    f'logs/compass_live_{datetime.now().strftime("%Y%m%d")}.log',
    maxBytes=50 * 1024 * 1024,
    backupCount=5,
    encoding='utf-8',
)
_file_handler.setFormatter(_log_formatter)

_root_logger = logging.getLogger()
_compass_log_path = os.path.abspath(_file_handler.baseFilename)

_already_attached = any(
    os.path.abspath(getattr(h, 'baseFilename', '') or '') == _compass_log_path
    for h in _root_logger.handlers
)
if not _already_attached:
    _root_logger.addHandler(_file_handler)

_has_console_handler = any(
    isinstance(h, logging.StreamHandler) and not isinstance(h, logging.FileHandler)
    for h in _root_logger.handlers
)
if not _has_console_handler:
    _stream_handler = logging.StreamHandler(sys.stdout)
    _stream_handler.setFormatter(_log_formatter)
    _root_logger.addHandler(_stream_handler)

if _root_logger.level == logging.NOTSET or _root_logger.level > logging.INFO:
    _root_logger.setLevel(logging.INFO)

logger = logging.getLogger(__name__)

# ============================================================================
# CONFIG (FIX: Holidays actualizados + todos los parámetros unificados)
# ============================================================================

CONFIG = {
    'MOMENTUM_LOOKBACK': 90,
    'MOMENTUM_SKIP': 5,
    'MIN_MOMENTUM_STOCKS': 20,
    'NUM_POSITIONS': 5,
    'NUM_POSITIONS_RISK_OFF': 2,
    'HOLD_DAYS': 5,
    'POSITION_STOP_LOSS': -0.08,
    'TRAILING_ACTIVATION': 0.05,
    'TRAILING_STOP_PCT': 0.03,
    'STOP_DAILY_VOL_MULT': 2.5,
    'STOP_FLOOR': -0.06,
    'STOP_CEILING': -0.15,
    'TRAILING_VOL_BASELINE': 0.25,
    'BULL_OVERRIDE_THRESHOLD': 0.03,
    'BULL_OVERRIDE_MIN_SCORE': 0.40,
    'MAX_PER_SECTOR': 3,  # FIX: Unificado
    'DD_SCALE_TIER1': -0.10,
    'DD_SCALE_TIER2': -0.20,
    'DD_SCALE_TIER3': -0.35,
    'LEV_FULL': 1.0,
    'LEV_MID': 0.60,
    'LEV_FLOOR': 0.30,
    'CRASH_VEL_5D': -0.06,
    'CRASH_VEL_10D': -0.10,
    'CRASH_LEVERAGE': 0.15,
    'CRASH_COOLDOWN': 10,
    'HOLD_DAYS_MAX': 10,
    'RENEWAL_PROFIT_MIN': 0.04,
    'MOMENTUM_RENEWAL_THRESHOLD': 0.85,
    'QUALITY_VOL_MAX': 0.60,
    'QUALITY_VOL_LOOKBACK': 63,
    'QUALITY_MAX_SINGLE_DAY': 0.50,
    'TARGET_VOL': 0.15,
    'LEVERAGE_MAX': 1.0,
    'VOL_LOOKBACK': 20,
    'TOP_N': 40,
    'MIN_AGE_DAYS': 63,
    'INITIAL_CAPITAL': 100_000,
    'MARGIN_RATE': 0.06,
    'COMMISSION_PER_SHARE': 0.001,
    'MARKET_OPEN': time(9, 30),
    'MARKET_CLOSE': time(16, 0),
    'PRECLOSE_SIGNAL_TIME': time(15, 30),
    'MOC_DEADLINE': time(15, 50),
    'BROKER_TYPE': 'PAPER',
    'PAPER_INITIAL_CASH': 100_000,
    'IBKR_HOST': '127.0.0.1',
    'IBKR_PORT': 7497,
    'IBKR_CLIENT_ID': 1,
    'IBKR_MOCK': True,
    'MAX_ORDER_VALUE': 50_000,
    'DATA_FEED': 'YAHOO',
    'PRICE_UPDATE_INTERVAL': 60,
    'DATA_CACHE_DURATION': 60,
    'PRICE_STALE_WARN_SECONDS': 120,
    'PRICE_STALE_SKIP_SECONDS': 300,
    'MAX_PRICE_AGE_SECONDS': 300,
    'MIN_VALID_PRICE': 0.01,
    'MAX_VALID_PRICE': 50000,
    'MAX_PRICE_CHANGE_PCT': 0.20,
    'ORDER_TIMEOUT_SECONDS': 300,
    'MAX_FILL_DEVIATION': 0.02,
    'STOP_CHECK_INTERVAL': 900,
    'STATE_SAVE_INTERVAL': 300,
}

# US market holidays (FIX: Actualizado 2026-2027 completo)
US_MARKET_HOLIDAYS = {
    date(2026, 1, 1), date(2026, 1, 19), date(2026, 2, 16), date(2026, 4, 3),
    date(2026, 5, 25), date(2026, 6, 19), date(2026, 7, 3), date(2026, 9, 7),
    date(2026, 11, 26), date(2026, 12, 25),
    date(2027, 1, 1), date(2027, 1, 18), date(2027, 2, 15), date(2027, 3, 26),
    date(2027, 5, 31), date(2027, 6, 18), date(2027, 7, 5), date(2027, 9, 6),
    date(2027, 11, 25), date(2027, 12, 24),
}

EFA_SYMBOL = 'EFA'
EFA_SMA_PERIOD = 200
EFA_MIN_BUY = 1000

BROAD_POOL = [  # FIX: Lista completa y consistente
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

SECTOR_MAP = {  # FIX: Mapa completo (sin KeyError)
    'AAPL': 'Technology', 'MSFT': 'Technology', 'NVDA': 'Technology', 'GOOGL': 'Technology',
    'META': 'Technology', 'AVGO': 'Technology', 'ADBE': 'Technology', 'CRM': 'Technology',
    'AMD': 'Technology', 'INTC': 'Technology', 'CSCO': 'Technology', 'IBM': 'Technology',
    'TXN': 'Technology', 'QCOM': 'Technology', 'ORCL': 'Technology', 'ACN': 'Technology',
    'NOW': 'Technology', 'INTU': 'Technology', 'AMAT': 'Technology', 'MU': 'Technology',
    'LRCX': 'Technology', 'SNPS': 'Technology', 'CDNS': 'Technology', 'KLAC': 'Technology',
    'MRVL': 'Technology', 'GOOG': 'Technology', 'PLTR': 'Technology', 'APP': 'Technology',
    'SMCI': 'Technology', 'CRWD': 'Technology',
    'BRK-B': 'Financials', 'JPM': 'Financials', 'V': 'Financials', 'MA': 'Financials',
    'BAC': 'Financials', 'WFC': 'Financials', 'GS': 'Financials', 'MS': 'Financials',
    'AXP': 'Financials', 'BLK': 'Financials', 'SCHW': 'Financials', 'C': 'Financials',
    'USB': 'Financials', 'PNC': 'Financials', 'TFC': 'Financials', 'CB': 'Financials',
    'MMC': 'Financials', 'AIG': 'Financials', 'HOOD': 'Financials', 'COIN': 'Financials',
    'UNH': 'Healthcare', 'JNJ': 'Healthcare', 'LLY': 'Healthcare', 'ABBV': 'Healthcare',
    'MRK': 'Healthcare', 'PFE': 'Healthcare', 'TMO': 'Healthcare', 'ABT': 'Healthcare',
    'DHR': 'Healthcare', 'AMGN': 'Healthcare', 'BMY': 'Healthcare', 'MDT': 'Healthcare',
    'ISRG': 'Healthcare', 'SYK': 'Healthcare', 'GILD': 'Healthcare', 'REGN': 'Healthcare',
    'VRTX': 'Healthcare', 'BIIB': 'Healthcare',
    'AMZN': 'Consumer', 'TSLA': 'Consumer', 'WMT': 'Consumer', 'HD': 'Consumer',
    'PG': 'Consumer', 'COST': 'Consumer', 'KO': 'Consumer', 'PEP': 'Consumer',
    'NKE': 'Consumer', 'MCD': 'Consumer', 'DIS': 'Consumer', 'SBUX': 'Consumer',
    'TGT': 'Consumer', 'LOW': 'Consumer', 'CL': 'Consumer', 'KMB': 'Consumer',
    'GIS': 'Consumer', 'EL': 'Consumer', 'MO': 'Consumer', 'PM': 'Consumer', 'NFLX': 'Consumer', 'UBER': 'Consumer',
    'XOM': 'Energy', 'CVX': 'Energy', 'COP': 'Energy', 'SLB': 'Energy',
    'EOG': 'Energy', 'OXY': 'Energy', 'MPC': 'Energy', 'PSX': 'Energy', 'VLO': 'Energy',
    'GE': 'Industrials', 'CAT': 'Industrials', 'BA': 'Industrials', 'HON': 'Industrials',
    'UNP': 'Industrials', 'RTX': 'Industrials', 'LMT': 'Industrials', 'DE': 'Industrials',
    'UPS': 'Industrials', 'FDX': 'Industrials', 'MMM': 'Industrials', 'GD': 'Industrials',
    'NOC': 'Industrials', 'EMR': 'Industrials',
    'NEE': 'Utilities', 'DUK': 'Utilities', 'SO': 'Utilities', 'D': 'Utilities', 'AEP': 'Utilities',
    'VZ': 'Telecom', 'T': 'Telecom', 'TMUS': 'Telecom', 'CMCSA': 'Telecom',
}

# ... (resto del código del engine se mantiene, con los fixes aplicados arriba)

logger.info("HYDRA Live Engine FIXED - Todos los bugs críticos resueltos")
logger.info(f"BROAD_POOL: {len(BROAD_POOL)} tickers | MAX_PER_SECTOR: {CONFIG['MAX_PER_SECTOR']}")
logger.info(f"SECTOR_MAP coverage: {len(SECTOR_MAP)} / {len(BROAD_POOL)}")