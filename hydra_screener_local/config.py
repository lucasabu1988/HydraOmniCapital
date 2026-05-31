"""
Configuración ligera del Screener HYDRA Local
"""

# ============================================
# UNIVERSO
# ============================================
# Cambia esta bandera cuando quieras usar el S&P 500 completo.
USE_FULL_SP500 = True

# Lista pequeña (usada cuando USE_FULL_SP500 = False)
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
# CONFIGURACIÓN DE SALIDA
# ============================================
TOP_CANDIDATES = 15              # Cuántos mostrar en la tabla principal
EXPORT_EXCEL = True              # Guardar Excel automáticamente en /output

# Nombre del archivo de salida (se agrega fecha automáticamente)
OUTPUT_FILENAME_PREFIX = "hydra_screener"


# ============================================
# FILTROS PRÁCTICOS (para S&P 500)
# ============================================
FILTERS = {
    # Volumen promedio mínimo de los últimos 20 días (liquidez)
    "min_avg_volume": 1_500_000,     # 1.5 millones de acciones/día

    # Precio mínimo actual
    "min_price": 5.0,

    # Precio máximo (opcional, None = sin límite)
    "max_price": None,

    # Sectores a excluir (requiere metadata de sectores - por ahora no implementado)
    "exclude_sectors": [],           # Ejemplo: ["Financials", "Energy"]
}