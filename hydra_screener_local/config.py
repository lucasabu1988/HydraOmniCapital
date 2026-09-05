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
# No MOMENTUM_SKIP, deliberately (TASK-319, 2026-09-06). The legacy v8.4 "5d skip" was really
# "skip minus last-5d return" - a short-term reversal bet that contradicts the strict filter and
# the short-term boost. Measured in-sample and out-of-sample: no skip variant beats production.
# Evidence in HYDRA_ALGORITHM_SPEC.md 4.1.
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

# TASK-202: threshold for warning when too many tickers have NaN vol_ratio (missing volume data)
VOL_NAN_WARN_THRESHOLD = 0.20      # max acceptable share of tickers with NaN vol_ratio before warning

# Data-quality guards added by the 2026-09-06 audit (D1, D2). Warnings, never blocks: a wrong
# list is worse than a late one, but a silent one is worst.
FETCH_MISSING_WARN_SHARE = 0.05         # warn when >5% of requested tickers came back without prices
STALE_DATA_WARN_BUSINESS_DAYS = 1       # warn when the last bar is older than the previous session

# Secondary regime (audit R1, 2026-09-06). The gate is computed on SPY; the universe is ~2/3
# mid/small caps. 2020-2026: SPY above its SMA200 while IWM was below on 12.5% of days (longest
# streak 54 sessions), and IWM's 5d return in those days averaged -15.8 bp vs +31.6 bp otherwise.
# Changing the gate is a scoring change that needs out-of-sample data on the real universe; until
# then the screener computes the same rich regime on this symbol, prints the disagreement, and
# persists it in history so the decision can eventually be made on evidence. Observability only.
SECONDARY_REGIME_SYMBOL = "IWM"

# ============================================
# DOWNTREND VETO GATE (nuevo Jun 2026)
# ============================================
# Justificación: el momentum de 90 días tiene tanta inercia que una acción puede
# caer fuerte en los últimos días y seguir rankeando arriba ("fue la que más subió
# en el trimestre"). El veto excluye de 'recommended' a las acciones en caída
# reciente, sin importar su rank. Filosofía: ranking relativo para elegir,
# filtro absoluto para vetar (igual que Catalyst exige precio > SMA200).
# Regla "solo en negativo" (2026-06-12): ret_10d < 0 es condición necesaria —
# una acción con retorno reciente positivo nunca se veta aunque esté lejos de
# su high (dip en uptrend ≠ caída). Ver experiments/backtest_gate_variants.py.
ENABLE_DOWNTREND_GATE = True
GATE_MAX_DIST_TO_HIGH_PCT = -8.0   # Veto si está más de X% debajo de su máximo de 20d (solo si ret 10d < 0)
GATE_MIN_RET_SHORT_PCT = -5.0      # Veto si el retorno de 10d es peor que X%

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

# Modelled round-trip cost (TASK-322). Not fills. 10 bp per side; a name that
# enters or exits pays two sides. Used by the variant sweep and tracking reports.
COST_BP_PER_SIDE = 10

# ============================================
# CONFIGURACIÓN DE SALIDA
# ============================================
TOP_CANDIDATES = 15              # Cuántos mostrar en la tabla principal
EXPORT_EXCEL = True              # Guardar Excel automáticamente en /output

# Nombre del archivo de salida (se agrega fecha automáticamente)
OUTPUT_FILENAME_PREFIX = "hydra_screener"


# ============================================
# SECTOR / THEME CONCENTRATION CONTROL (nuevo Jun 2026)
# ============================================
# Justificación: En regímenes STRONG_BROAD_MOMENTUM el screener se concentra fuertemente
# en 1-2 temas líderes (ej: 72% Semis + Software/Cyber en mayo-jun 2026). Esto reduce
# la diversificación efectiva aunque tengamos 22 nombres recomendados.
#
# TASK-320: el control es un LÍMITE DURO al seleccionar la lista recomendada. No toca
# composite_score (el scoring queda separado de la construcción de cartera, SPEC 1).
# La penalidad blanda anterior se quitó: se aplicaba sobre el universo entero (penalizaba
# al 87% de los nombres por no estar en un mapa de 80 tickers) y, por ser blanda, nunca
# vinculaba — el 100% de los ciclos simulados terminaba por encima del límite.
#
# MAX_PER_SECTOR = 5 sobre sectores GICS. GICS es más grueso que los buckets hechos a mano:
# Semis, Software/Cyber y Networking caen todos en "Technology". Así que 5 bajo GICS es más
# estricto sobre concentración tech que el 3 de los buckets viejos (permitía 3+3+3 = 9
# nombres tech). Sobre una lista de 14-28, 5 es como mucho un 36% en un sector — lejos del
# 72% que motivó este control. Coste medido: -2.8 bp/ciclo (p=0.628), Sharpe 1.07 -> 1.16,
# maxDD -18.8% -> -18.3%, y 0% de ciclos por encima del límite. Los caps 3 y 4 vinculan
# igual pero cuestan más (-9.9 y -7.3 bp) y empeoran el drawdown.
# Aviso: el valor se eligió sobre la misma muestra 2020-2026 que lo mide.
ENABLE_SECTOR_CONTROL = True
MAX_PER_SECTOR = 5               # Máximo por sector GICS en la lista recomendada

# Presupuesto para resolver sectores al arrancar (screener.py, aguas arriba del scoring).
# yfinance solo expone `sector` vía el endpoint `.info`, ~0.4s por nombre desconocido: la
# caché es lo que lo saca del camino crítico diario. Lo que no dé tiempo cae a buckets/Other
# en ese run y se resuelve en el siguiente.
SECTOR_FETCH_BUDGET_SECONDS = 120

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
    # Liquidity filter (Volume is fetched by data/fetch and used here when > 0).
    # 100k is a conservative default for quality; raise for stricter (e.g. 500k+ for large caps).
    "min_avg_volume": 100000,

    # Dollar liquidity: 20-day mean of close x volume, USD. Shares alone let a $5 stock with
    # $500k/day into a list that rotates ~39% a week (audit 2026-09-06, D3). $5M/day excludes
    # the genuinely untradeable end of the Russell 2000 without gutting small caps. Selection
    # rule, not scoring (SPEC 1). Measured on S&P 500: no effect (every name passes); the
    # effect on the production universe is unmeasured until TASK-324's panel exists.
    "min_dollar_volume": 5_000_000,

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
