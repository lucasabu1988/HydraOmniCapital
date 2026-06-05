"""
Configuración ligera del Screener HYDRA Local

Todos los parámetros aquí son los valores por defecto usados en
HYDRA_ALGORITHM_SPEC.md (v1.2). Cualquier cambio aquí debe reflejarse en el spec
y en las implementaciones (Python + Pine).
"""

# ============================================
# UNIVERSE SELECTION
# ============================================
# Choose the main index/universe to screen:
#   "sp500"       -> S&P 500 (~500 stocks)
#   "nasdaq100"   -> Nasdaq-100 (~100 stocks, tech-heavy)
#   "dow30"       -> Dow Jones Industrial Average (30 blue-chip stocks)
#   "russell1000" -> Russell 1000 (~1000 large+mid cap US stocks)
#   "russell2000" -> Russell 2000 (~2000 small caps) - adds many more acciones
#   "russell3000" -> Russell 3000 = R1000 + R2000 (~3000 total)
#   "all"         -> Union of SP500 + Nasdaq100 + Dow30 + R1000 + R2000 (max breadth, ~2500+ unique)
#   "custom"      -> Use the INITIAL_UNIVERSE list below (small/fast for testing)
#
# When UNIVERSE="all", the screener fetches the combined unique tickers from all major US indices
# (including Russell 1000/2000 for broader large/mid/small cap coverage) and selects the best candidates purely by
# HYDRA scoring (no distinction between indices). This integrates "más acciones" (large + mid + small caps).
#
# Legacy: USE_FULL_SP500=True still works and maps to "sp500".
UNIVERSE = "all"

# Legacy flag (kept for backward compatibility with old scripts)
# If UNIVERSE is not explicitly set to something else, this controls sp500 vs custom.
USE_FULL_SP500 = True

# Lista pequeña / custom (usada cuando UNIVERSE="custom" o USE_FULL_SP500=False)
# (comentarios actualizados para soportar multi-universe)
INITIAL_UNIVERSE = [
    'AAPL', 'MSFT', 'NVDA', 'AMZN', 'GOOGL', 'META', 'AVGO', 'TSLA',
    'JPM', 'V', 'MA', 'XOM', 'UNH', 'JNJ', 'PG', 'COST', 'HD', 'MRK',
    'LLY', 'ABBV', 'PEP', 'KO', 'MCD', 'WMT', 'DIS', 'NFLX', 'ADBE',
    'CRM', 'INTC', 'AMD', 'QCOM', 'TXN', 'HON', 'UPS', 'BA', 'CAT',
    'BRK-B', 'CVX', 'ABT', 'TMO', 'DHR', 'NEE', 'LIN', 'MDT', 'BMY',
    'AMGN', 'GILD', 'ISRG', 'SYK', 'BSX', 'ELV', 'CI', 'HUM',
    'SPGI', 'BLK', 'AXP', 'GS', 'MS', 'C', 'BAC', 'WFC',
    'LOW', 'NKE', 'SBUX', 'TGT', 'ORCL', 'IBM', 'CSCO',
]

# ============================================
# PARÁMETROS DE SEÑALES (lógica establecida)
# ============================================
MOMENTUM_LOOKBACK = 90
MOMENTUM_SKIP = 5
REGIME_SMA = 200
MIN_REGIME_SCORE = 0.35          # Por debajo de esto, reducimos agresividad

# ============================================
# NUEVAS REGLAS - Short Term Momentum + Strength Filters (post-análisis 31-may)
# ============================================
SHORT_TERM_LOOKBACK = 10         # Para retorno reciente (5-10 días)
PROXIMITY_HIGH_DAYS = 20         # Ventana para "distancia a máximos"
MAX_DIST_TO_HIGH_PCT = 3.0       # Máximo % lejos del high para dar boost completo
SHORT_TERM_BOOST = 0.35          # Cuánto boostear el meta_score con momentum reciente + cercanía a highs
VOL_SURGE_THRESHOLD = 1.50       # Umbral base de volumen relativo (placeholder hasta extender fetch)

# ============================================
# CONFIGURACIÓN GEOPOLÍTICA (afecta umbrales dinámicos)
# ============================================
# 0.0 = normal / baja tensión
# 0.3-0.5 = tensión media (elecciones, conflictos regionales)
# 0.7-1.0 = alta tensión geopolítica (guerras abiertas, crisis mayores)
GEOPOLITICAL_RISK_LEVEL = 0.0

# Factor con el que el riesgo geopolítico modifica el umbral de volumen
# En alta tensión, exigimos surge más fuerte para considerar "real"
GEO_VOL_THRESHOLD_ADJUST = 0.6   # el umbral puede subir hasta +0.6 en riesgo máximo

# Piso duro: el umbral de volumen NUNCA puede bajar de 1.0
# ni en el backtest ni en el screener en vivo, independientemente del riesgo geopolítico
MIN_VOL_THRESHOLD = 1.0

# ============================================
# CONFIGURACIÓN DE SALIDA
# ============================================
TOP_CANDIDATES = 15              # Cuántos mostrar en la tabla principal
EXPORT_EXCEL = True              # Guardar Excel automáticamente en /output

# Nombre del archivo de salida (se agrega fecha automáticamente)
OUTPUT_FILENAME_PREFIX = "hydra_screener"


# ============================================
# DATA QUALITY - Tickers problemáticos / delistados
# ============================================
# Hard blacklist de tickers que ya no existen o devuelven datos corruptos/zombies
# de yfinance (ej: SNDK delisted 2016, BRK.B mal mapeado a veces, etc.).
# Se filtran lo antes posible para evitar descargas inútiles y contaminación del ranking.
DELISTED_OR_BAD_TICKERS = {
    "SNDK",      # SanDisk - delisted 2016 (adquirida por WDC). Zombie data frecuente.
    "BRK.B",     # A menudo falla o se confunde con BRK-B. Usar BRK-B en listas.
    "BF.B",      # Brown-Forman clase B - problemas de mapeo comunes.
    "FB",        # Viejo ticker de Meta, ahora META.
    "TWTR",      # Delisted 2022 (adquirida por X).
    "SCTY",      # SolarCity - delisted.
}

# ============================================
# SECTOR / THEME CONCENTRATION CONTROL (nuevo Jun 2026)
# ============================================
# Justificación: En regímenes STRONG_BROAD_MOMENTUM el screener se concentra fuertemente
# en 1-2 temas líderes (ej: 72% Semis + Software/Cyber en mayo-jun 2026). Esto reduce
# la diversificación efectiva aunque tengamos 22 nombres recomendados.
#
# Control ligero:
# - Soft penalty en composite_score cuando un bucket excede el límite.
# - Hard cap al seleccionar los recomendados finales.

ENABLE_SECTOR_CONTROL = True
MAX_PER_SECTOR = 8               # Máximo recomendado por bucket grueso
SECTOR_OVERWEIGHT_PENALTY = 0.15 # Penalidad al composite_score (15%) para nombres que exceden

# Buckets gruesos (coarse buckets). Mantener pocos y estables.
# Los tickers no listados caen en "Other".
SECTOR_BUCKETS = {
    # Semis, Storage, Hardware
    "DELL": "Semis_Storage_HW", "SNDK": "Semis_Storage_HW", "STX": "Semis_Storage_HW",
    "HPE": "Semis_Storage_HW", "MU": "Semis_Storage_HW", "WDC": "Semis_Storage_HW",
    "AMD": "Semis_Storage_HW", "INTC": "Semis_Storage_HW", "NVDA": "Semis_Storage_HW",
    "AVGO": "Semis_Storage_HW", "QCOM": "Semis_Storage_HW", "TXN": "Semis_Storage_HW",
    "ON": "Semis_Storage_HW", "MRVL": "Semis_Storage_HW", "NXPI": "Semis_Storage_HW",
    "LRCX": "Semis_Storage_HW", "AMAT": "Semis_Storage_HW", "KLAC": "Semis_Storage_HW",

    # Software, SaaS, Cybersecurity
    "CRWD": "Software_SaaS_Cyber", "PANW": "Software_SaaS_Cyber", "DDOG": "Software_SaaS_Cyber",
    "FTNT": "Software_SaaS_Cyber", "SNOW": "Software_SaaS_Cyber", "PLTR": "Software_SaaS_Cyber",
    "ZS": "Software_SaaS_Cyber", "NET": "Software_SaaS_Cyber", "OKTA": "Software_SaaS_Cyber",
    "NOW": "Software_SaaS_Cyber", "TEAM": "Software_SaaS_Cyber", "ADBE": "Software_SaaS_Cyber",
    "CRM": "Software_SaaS_Cyber", "ORCL": "Software_SaaS_Cyber", "IBM": "Software_SaaS_Cyber",

    # Networking / Telecom equipment
    "CIEN": "Networking_Telecom", "CSCO": "Networking_Telecom", "NTAP": "Networking_Telecom",
    "FFIV": "Networking_Telecom", "ANET": "Networking_Telecom", "KEYS": "Networking_Telecom",

    # Materials + Industrials + Energy
    "NUE": "Materials_Industrials", "STLD": "Materials_Industrials", "TRGP": "Materials_Industrials",
    "CAT": "Materials_Industrials", "HON": "Materials_Industrials", "UPS": "Materials_Industrials",
    "BA": "Materials_Industrials", "XOM": "Materials_Industrials", "CVX": "Materials_Industrials",

    # Healthcare
    "DVA": "Healthcare", "UNH": "Healthcare", "JNJ": "Healthcare", "LLY": "Healthcare",
    "ABBV": "Healthcare", "MRK": "Healthcare", "TMO": "Healthcare", "ISRG": "Healthcare",

    # Consumer / Retail
    "COST": "Consumer", "WMT": "Consumer", "TGT": "Consumer", "HD": "Consumer",
    "LOW": "Consumer", "NKE": "Consumer", "SBUX": "Consumer", "MCD": "Consumer",

    # Financials
    "BRK-B": "Financials", "JPM": "Financials", "V": "Financials", "MA": "Financials",
    "AXP": "Financials", "GS": "Financials", "MS": "Financials", "BLK": "Financials",

    # Otros grandes
    "AAPL": "Tech_Hardware", "MSFT": "Software_SaaS_Cyber", "GOOGL": "Software_SaaS_Cyber",
    "META": "Software_SaaS_Cyber", "TSLA": "Consumer_EV", "AMZN": "Consumer",
    "NFLX": "Consumer", "DIS": "Consumer",
}

# ============================================
# FILTROS PRÁCTICOS (para S&P 500)
# ============================================
FILTERS = {
    # Liquidez: actualmente deshabilitado (0) porque el fetch solo trae precios (Close).
    # El filtro de "volumen" compara contra precios y eliminaría todo.
    # TODO: extender fetch para incluir Volume y activar (e.g. 1_000_000).
    "min_avg_volume": 0,

    # Precio mínimo actual (activo y útil)
    "min_price": 5.0,

    # Precio máximo (opcional, None = sin límite)
    "max_price": None,

    # Sectores a excluir (requiere metadata de sectores - por ahora no implementado)
    "exclude_sectors": [],           # Ejemplo: ["Financials", "Energy"]
}

# ============================================
# TICKERS PROBLEMATICOS / ZOMBIES
# ============================================
# Hard blacklist de tickers que ya no existen o devuelven datos corruptos/zombies
# de yfinance (ej: SNDK delisted 2016, BRK.B mal mapeado a veces, etc.).
# Se filtran lo antes posible para evitar descargas inutiles y contaminacion del ranking.
DELISTED_OR_BAD_TICKERS = {
    # "SNDK",    # Dejamos activo para que aparezca en el analisis general
    "BRK.B",     # A menudo falla o se confunde con BRK-B. Usar BRK-B en listas.
    "BF.B",      # Brown-Forman clase B - problemas de mapeo comunes.
    "FB",        # Viejo ticker de Meta, ahora META.
    "TWTR",      # Delisted 2022 (adquirida por X).
    "SCTY",      # SolarCity - delisted.
}
