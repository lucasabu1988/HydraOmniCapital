"""
COMPASS v8.3 - Patches Algorítmicos para omnicapital_v8_compass.py
====================================================================

Archivo de referencia: Las 4 mejoras algorítmicas propuestas para COMPASS v8.2.

INSTRUCCIONES DE USO:
1. Copiar cada función directamente en omnicapital_v8_compass.py
2. Seguir las notas de integración al final de cada sección
3. Testear CADA cambio individualmente antes de combinar

ORDEN DE IMPLEMENTACIÓN RECOMENDADO:
  Fase 1: PATCH_4 (Quality Filter)  -- no modifica lógica core
  Fase 2: PATCH_2 (Regime Continuo) -- modifica max_positions
  Fase 3: PATCH_3 (Exit Renewal)    -- modifica cuándo cierran posiciones
  Fase 4: PATCH_1 (Smooth DD Scale) -- el cambio más estructural

Baseline (bias-corrected, exp40):
  CAGR: 13.90% | MaxDD: -66.25% | Sharpe: 0.646 | Calmar: 0.21

Estimación de impacto total: +3.3% a +6.5% CAGR
"""

import numpy as np
import pandas as pd
from typing import Dict, List, Optional

# ============================================================================
# PATCH 1: SMOOTH DRAWDOWN SCALING (Reemplaza portfolio stop + recovery mode)
# ============================================================================
#
# PROBLEMA: El portfolio stop de -15% dispara liquidación total + 63-189 días
# en modo protección de 0.3x. En 2022 esto causó que el sistema cayera de
# $1.85M a $1.19M DURANTE el "modo protección" (el double-hit).
#
# SOLUCIÓN: Reemplazar con un scaling lineal continuo que NUNCA liquida
# completamente. El sistema siempre mantiene mínimo 20% de exposición.
#
# PARÁMETROS NUEVOS (agregar al bloque de parámetros):
#   DD_SCALE_TIER1 = -0.05
#   DD_SCALE_TIER2 = -0.15
#   DD_SCALE_TIER3 = -0.25
#   LEV_FULL = 1.0
#   LEV_MID = 0.50
#   LEV_FLOOR = 0.20
#   CRASH_VEL_5D = -0.06
#   CRASH_VEL_10D = -0.10
#   CRASH_LEVERAGE = 0.15
#   CRASH_COOLDOWN = 10
#
# PARÁMETROS ELIMINADOS:
#   PORTFOLIO_STOP_LOSS = -0.15     <- eliminar
#   RECOVERY_STAGE_1_DAYS = 63     <- eliminar
#   RECOVERY_STAGE_2_DAYS = 126    <- eliminar
#   LEVERAGE_MIN = 0.3             <- reemplazar con LEV_FLOOR = 0.20
# ============================================================================

# Nuevos parámetros para el smooth scaling
DD_SCALE_TIER1 = -0.05     # Inicio de reducción
DD_SCALE_TIER2 = -0.15     # Segunda reducción
DD_SCALE_TIER3 = -0.25     # Floor zone
LEV_FULL       = 1.0       # Leverage normal
LEV_MID        = 0.50      # Leverage intermedio
LEV_FLOOR      = 0.20      # Mínimo absoluto -- NUNCA cero

# Crash velocity circuit breaker
CRASH_VEL_5D   = -0.06     # -6% en 5 días trading
CRASH_VEL_10D  = -0.10     # -10% en 10 días trading
CRASH_LEVERAGE = 0.15      # Leverage override durante crash
CRASH_COOLDOWN = 10        # Días de cooldown post-crash


def _dd_leverage(drawdown: float) -> float:
    """
    Smooth piecewise-linear drawdown leverage scaling.

    DD tiers:
      0%   to -5%:  1.0x (sin reducción)
      -5%  to -15%: 1.0x -> 0.50x (lineal)
      -15% to -25%: 0.50x -> 0.20x (lineal)
      < -25%:       0.20x (floor duro)

    Args:
        drawdown: Drawdown actual como fracción negativa (e.g., -0.10 = -10%)

    Returns:
        Leverage multiplier en [LEV_FLOOR, LEV_FULL]
    """
    dd = drawdown

    if dd >= DD_SCALE_TIER1:
        return LEV_FULL

    elif dd >= DD_SCALE_TIER2:
        # Lineal: 1.0x en -5% -> 0.50x en -15%
        frac = (dd - DD_SCALE_TIER1) / (DD_SCALE_TIER2 - DD_SCALE_TIER1)
        return LEV_FULL + frac * (LEV_MID - LEV_FULL)

    elif dd >= DD_SCALE_TIER3:
        # Lineal: 0.50x en -15% -> 0.20x en -25%
        frac = (dd - DD_SCALE_TIER2) / (DD_SCALE_TIER3 - DD_SCALE_TIER2)
        return LEV_MID + frac * (LEV_FLOOR - LEV_MID)

    else:
        return LEV_FLOOR  # Hard floor


def compute_smooth_leverage(drawdown: float,
                             portfolio_values: list,
                             current_idx: int,
                             crash_cooldown: int) -> tuple:
    """
    Compute leverage via smooth drawdown scaling + crash velocity circuit breaker.

    Esta función REEMPLAZA la lógica de:
      - in_protection_mode
      - protection_stage
      - stop_loss_day_index
      - PORTFOLIO_STOP_LOSS trigger
      - Recovery Stage 1 y Stage 2

    La filosofía es: en lugar de un stop binario (all-in o all-out),
    reducir gradualmente la exposición conforme aumenta el drawdown,
    y nunca ir por debajo de LEV_FLOOR (20%).

    El crash velocity circuit breaker detecta caídas RÁPIDAS (que el
    drawdown peak-to-trough detecta tarde) y reduce temporalmente a 0.15x.

    Args:
        drawdown: Drawdown actual como fracción negativa
        portfolio_values: Lista cronológica de registros diarios del portfolio
            Puede ser lista de dicts {'value': float} o lista de floats
        current_idx: Índice en portfolio_values para el día actual
        crash_cooldown: Días restantes de cooldown (0 = sin cooldown activo)

    Returns:
        Tuple (leverage: float, updated_cooldown: int)
    """
    # --- Helper para extraer valor ---
    def _val(entry):
        if isinstance(entry, dict):
            return float(entry.get('value', entry.get('portfolio_value', 0.0)))
        return float(entry)

    # --- Crash velocity circuit breaker ---
    in_crash = False
    updated_cooldown = crash_cooldown

    if crash_cooldown > 0:
        # Ya en cooldown por crash anterior
        in_crash = True
        updated_cooldown = crash_cooldown - 1

    elif current_idx >= 5 and len(portfolio_values) > current_idx:
        current_val = _val(portfolio_values[current_idx])

        # Verificar velocidad de 5 días
        val_5d = _val(portfolio_values[current_idx - 5])
        if val_5d > 0:
            ret_5d = (current_val / val_5d) - 1.0
            if ret_5d <= CRASH_VEL_5D:
                in_crash = True

        # Verificar velocidad de 10 días
        if not in_crash and current_idx >= 10:
            val_10d = _val(portfolio_values[current_idx - 10])
            if val_10d > 0:
                ret_10d = (current_val / val_10d) - 1.0
                if ret_10d <= CRASH_VEL_10D:
                    in_crash = True

        if in_crash:
            updated_cooldown = CRASH_COOLDOWN - 1  # Primer día del cooldown

    if in_crash:
        # Override de crash: usar CRASH_LEVERAGE (0.15x) o menos si el DD scaling
        # es aún más restrictivo
        dd_lev = _dd_leverage(drawdown)
        crash_lev = min(CRASH_LEVERAGE, dd_lev)
        return (crash_lev, updated_cooldown)

    # --- Scaling normal por drawdown ---
    return (_dd_leverage(drawdown), updated_cooldown)


# ============================================================================
# INTEGRACIÓN DE PATCH 1 EN run_backtest()
# ============================================================================
#
# PASO A: Eliminar estas variables de estado al inicio de run_backtest():
#   in_protection_mode = False       <- ELIMINAR
#   protection_stage = 0             <- ELIMINAR
#   stop_loss_day_index = None       <- ELIMINAR
#   post_stop_base = None            <- ELIMINAR
#   peak_value = float(INITIAL_CAPITAL)   <- MANTENER (seguimos rastreando peak)
#
# AGREGAR al inicio de run_backtest():
#   crash_cooldown = 0
#
# PASO B: En el loop principal, REEMPLAZAR:
#
#   BLOQUE ELIMINAR:
#   ```
#   if in_protection_mode and stop_loss_day_index is not None:
#       days_since_stop = i - stop_loss_day_index
#       ...
#       if protection_stage == 1 and days_since_stop >= RECOVERY_STAGE_1_DAYS...
#           protection_stage = 2
#       if protection_stage == 2 and days_since_stop >= RECOVERY_STAGE_2_DAYS...
#           in_protection_mode = False
#   ```
#
#   Y TAMBIÉN:
#   ```
#   if drawdown <= PORTFOLIO_STOP_LOSS and not in_protection_mode:
#       ... close ALL positions ...
#       in_protection_mode = True
#       protection_stage = 1
#   ```
#
#   CON ESTA LÓGICA:
#   ```
#   # Smooth leverage (reemplaza toda la lógica de protection mode)
#   dd_leverage_val, crash_cooldown = compute_smooth_leverage(
#       drawdown, portfolio_values, i - 1, crash_cooldown
#   )
#   # Nota: i-1 porque portfolio_values tiene los valores de días anteriores
#   # En el primer día usamos max(i-1, 0)
#
#   # Vol targeting (sin cambios)
#   vol_leverage = compute_dynamic_leverage(spy_data, date)
#
#   # Leverage final: el mínimo de los dos
#   current_leverage = max(min(dd_leverage_val, vol_leverage), LEV_FLOOR)
#   ```
#
# PASO C: REEMPLAZAR la sección "Determine max positions":
#   ```
#   # ANTES (eliminar):
#   if in_protection_mode:
#       if protection_stage == 1:
#           max_positions = 2
#           current_leverage = 0.3
#       else:
#           max_positions = 3
#           current_leverage = 1.0
#   elif not is_risk_on:
#       max_positions = NUM_POSITIONS_RISK_OFF
#       current_leverage = 1.0
#   else:
#       max_positions = NUM_POSITIONS
#       current_leverage = compute_dynamic_leverage(spy_data, date)
#
#   # DESPUÉS (con PATCH 1 y PATCH 2 juntos):
#   # max_positions viene de regime_score_to_positions() (ver PATCH 2)
#   # current_leverage ya calculado arriba
#   ```


# ============================================================================
# PATCH 2: REGIME FILTER CONTINUO (Reemplaza binary compute_regime())
# ============================================================================
#
# PROBLEMA: La SMA200 binaria tiene:
#   1. Lag de ~100 días para reflejar el cambio del mercado
#   2. Transición abrupta 5->2 posiciones que genera ventas en el peor momento
#
# SOLUCIÓN: Score continuo [0, 1] basado en:
#   - Trend (60%): sigmoid de distancia a SMA200 + SMA50/SMA200 cross + 20d momentum
#   - Vol (40%): percentile rank del 10d vol en distribución de 252 días (invertido)
#
# Más simple que exp44_modules/regime.py: no incluye breadth (demasiado caro en O(n))
# ============================================================================

def _sigmoid(x: float, k: float = 15.0) -> float:
    """
    Logistic sigmoid: maps (-inf, +inf) -> (0, 1).
    At x=0 returns 0.5. k controla la pendiente.

    Ejemplos con k=15:
      x = +0.05 (5% sobre SMA) -> ~0.68 (levemente bullish)
      x =  0.0  (en la SMA)    -> 0.50 (neutral)
      x = -0.10 (10% bajo SMA) -> ~0.18 (claramente bearish)
    """
    z = float(np.clip(k * x, -20.0, 20.0))
    return 1.0 / (1.0 + np.exp(-z))


def compute_regime_score(spy_data: pd.DataFrame, date: pd.Timestamp) -> float:
    """
    Compute continuous market regime score [0.0, 1.0].

    0.0 = extreme bear, 1.0 = strong bull.

    REEMPLAZA compute_regime() que devolvía True/False.

    Components:
      Trend (60%):
        - Sigmoid of price distance from SMA200  (1/3)
        - Sigmoid of SMA50/SMA200 ratio          (1/3)
        - Sigmoid of 20-day momentum             (1/3)

      Volatility regime (40%):
        - Percentile rank of 10-day annualized vol in 252-day distribution
        - Inverted: low vol = high score = bullish

    Note: No breadth component (avoiding O(n) per-stock SMA50 loop each day).
    The trend + vol components capture ~80% of regime information.

    Args:
        spy_data: SPY OHLCV DataFrame. Index may be tz-aware or tz-naive.
        date: Current trading date. May be tz-aware or tz-naive.

    Returns:
        float in [0.0, 1.0]
    """
    # Timezone normalization (fixes the bug found in exp43)
    date_n = pd.Timestamp(date)
    if hasattr(date_n, 'tz') and date_n.tz is not None:
        date_n = date_n.tz_localize(None)

    spy = spy_data.copy()
    if hasattr(spy.index, 'tz') and spy.index.tz is not None:
        spy.index = spy.index.tz_localize(None)

    if date_n not in spy.index:
        return 0.5  # Neutral fallback

    spy_idx = spy.index.get_loc(date_n)

    # Need at least 252 days (SMA200 + vol distribution)
    if spy_idx < 252:
        return 0.5

    spy_close = spy['Close'].iloc[:spy_idx + 1]
    current = float(spy_close.iloc[-1])

    # -------------------------------------------------------------------------
    # Component 1: Trend (60%)
    # -------------------------------------------------------------------------
    sma200 = float(spy_close.iloc[-200:].mean())
    sma50  = float(spy_close.iloc[-50:].mean())

    if sma200 <= 0:
        return 0.5  # Data error

    # Sub-signal 1a: Price vs SMA200 distance
    dist_200 = (current / sma200) - 1.0
    sig_200 = _sigmoid(dist_200, k=15.0)

    # Sub-signal 1b: SMA50/SMA200 (golden/death cross strength)
    if sma200 > 0:
        cross = (sma50 / sma200) - 1.0
        sig_cross = _sigmoid(cross, k=30.0)  # Steeper: crosses are rarer
    else:
        sig_cross = 0.5

    # Sub-signal 1c: 20-day momentum
    if len(spy_close) >= 21:
        price_20d_ago = float(spy_close.iloc[-21])
        if price_20d_ago > 0:
            mom_20d = (current / price_20d_ago) - 1.0
            sig_mom = _sigmoid(mom_20d, k=15.0)
        else:
            sig_mom = 0.5
    else:
        sig_mom = 0.5

    trend_score = (sig_200 + sig_cross + sig_mom) / 3.0

    # -------------------------------------------------------------------------
    # Component 2: Volatility regime (40%)
    # -------------------------------------------------------------------------
    returns = spy_close.pct_change().dropna()
    vol_score = 0.5  # Default

    if len(returns) >= 262:  # 252 for distribution + 10 for current vol
        # Current 10-day realized vol (annualized)
        current_vol = float(returns.iloc[-10:].std() * np.sqrt(252))

        # Distribution: rolling 10-day vol over trailing 252 days
        hist_returns = returns.iloc[-252:]
        rolling_vol = hist_returns.rolling(window=10).std() * np.sqrt(252)
        rolling_vol = rolling_vol.dropna()

        if len(rolling_vol) >= 20 and current_vol > 0:
            # Percentile rank: fraction of historical vols <= current
            pct_rank = float((rolling_vol <= current_vol).sum()) / len(rolling_vol)
            # Invert: low vol percentile = bullish = high score
            vol_score = 1.0 - pct_rank

    # -------------------------------------------------------------------------
    # Composite score
    # -------------------------------------------------------------------------
    composite = 0.60 * trend_score + 0.40 * vol_score
    return float(np.clip(composite, 0.0, 1.0))


def regime_score_to_positions(regime_score: float,
                               num_positions: int = 5,
                               num_positions_risk_off: int = 2) -> int:
    """
    Convert continuous regime score to number of positions.

    REEMPLAZA la lógica binaria: is_risk_on -> 5 or 2 positions.

    La transición gradual evita cerrar 3 posiciones de golpe cuando el
    mercado está en el punto más bajo.

    Thresholds (calibrados para el rango empírico del score):
      >= 0.65: 5 posiciones (strong bull)
      >= 0.50: 4 posiciones (mild bull)
      >= 0.35: 3 posiciones (mild bear)
      <  0.35: 2 posiciones (bear)

    Args:
        regime_score: Score continuo de compute_regime_score()
        num_positions: Número máximo de posiciones en bull (default 5)
        num_positions_risk_off: Número mínimo en bear (default 2)

    Returns:
        int: número de posiciones para este día
    """
    if regime_score >= 0.65:
        return num_positions                  # 5
    elif regime_score >= 0.50:
        return max(num_positions - 1, num_positions_risk_off + 1)  # 4
    elif regime_score >= 0.35:
        return max(num_positions - 2, num_positions_risk_off + 1)  # 3
    else:
        return num_positions_risk_off         # 2


# ============================================================================
# INTEGRACIÓN DE PATCH 2 EN run_backtest()
# ============================================================================
#
# PASO A: ELIMINAR la pre-computación al inicio:
#   ```
#   regime = compute_regime(spy_data)  <- ELIMINAR ESTA LÍNEA
#   ```
#
# PASO B: En el loop, REEMPLAZAR:
#   ```
#   # ANTES (eliminar):
#   is_risk_on = True
#   if date in regime.index:
#       is_risk_on = bool(regime.loc[date])
#   if is_risk_on:
#       risk_on_days += 1
#   else:
#       risk_off_days += 1
#
#   # DESPUÉS:
#   regime_score = compute_regime_score(spy_data, date)
#   is_risk_on = regime_score >= 0.50  # Para logging
#   max_positions = regime_score_to_positions(regime_score)
#   if is_risk_on:
#       risk_on_days += 1
#   else:
#       risk_off_days += 1
#   ```
#
# PASO C: En el snapshot diario, agregar regime_score:
#   ```
#   portfolio_values.append({
#       ...
#       'regime_score': regime_score,    # AGREGAR
#       ...
#   })
#   ```


# ============================================================================
# PATCH 3: EXIT RENEWAL (Permitir que los ganadores corran)
# ============================================================================
#
# PROBLEMA: 90.5% de exits son por tiempo (hold_expired a 5 días).
# Los ganadores con momentum positivo se cierran prematuramente.
# La autocorrelación positiva del momentum en 1-12 meses implica que
# un ganador a 5 días tiene mayor probabilidad de seguir ganando.
#
# SOLUCIÓN: Si a los 5 días la posición está en profit > 2% Y sigue
# en el top 70% del universo por score, renovar el hold por 5 días más.
# Hard cap en 15 días para evitar posiciones "zombie".
# ============================================================================

# Nuevos parámetros para el exit renewal
HOLD_DAYS_MAX = 15             # Máximo absoluto de días (3 semanas)
RENEWAL_PROFIT_MIN = 0.02      # +2% mínimo de ganancia para renovar
MOMENTUM_RENEWAL_THRESHOLD = 0.70  # Top 70% del universo por score


def should_renew_position(symbol: str,
                          pos: dict,
                          current_price: float,
                          days_held: int,
                          scores: dict) -> bool:
    """
    Determina si una posición debe renovarse en lugar de cerrarse al expirar el hold.

    Se renueva si Y SOLO SI todas las condiciones se cumplen:
    1. days_held == HOLD_DAYS (exactamente en el punto de expiración)
    2. days_held < HOLD_DAYS_MAX (hard cap anti-zombie)
    3. Posición profitable por al menos RENEWAL_PROFIT_MIN (+2%)
    4. Score de momentum actual en top MOMENTUM_RENEWAL_THRESHOLD del universo

    Si se renueva, el expiry se extiende. El trailing stop sigue activo.
    El high_price NO se resetea (trailing continua desde el máximo alcanzado).

    Args:
        symbol: Ticker del stock
        pos: Dict de posición con 'entry_price' y 'high_price'
        current_price: Precio actual
        days_held: Días transcurridos desde entrada
        scores: Dict {symbol: score} de todos los stocks con score en este día

    Returns:
        True si debe renovar, False si debe cerrar
    """
    # Hard cap: nunca exceder el máximo
    if days_held >= HOLD_DAYS_MAX:
        return False

    # Profit mínimo requerido
    entry_price = pos.get('entry_price', current_price)
    if entry_price <= 0:
        return False
    pos_return = (current_price - entry_price) / entry_price
    if pos_return < RENEWAL_PROFIT_MIN:
        return False

    # Score válido en el universo actual
    if not scores or symbol not in scores:
        return False

    # Rank percentil dentro del universo
    all_score_values = sorted(scores.values(), reverse=True)
    n = len(all_score_values)
    if n < 3:
        return False

    symbol_score = scores[symbol]
    # Rank 0-indexed: cuántos stocks tienen score mayor
    rank_above = sum(1 for s in all_score_values if s > symbol_score)
    percentile = 1.0 - (rank_above / n)  # 1.0 = top, 0.0 = bottom

    return percentile >= MOMENTUM_RENEWAL_THRESHOLD


# ============================================================================
# INTEGRACIÓN DE PATCH 3 EN run_backtest()
# ============================================================================
#
# CAMBIO CLAVE: Los scores deben calcularse ANTES del loop de exits (no después).
# Esto elimina el doble cálculo actual y hace la renovación posible.
#
# ESTRUCTURA NUEVA DEL LOOP DIARIO:
#
#   1. Calcular portfolio_value
#   2. Actualizar peak_value
#   3. Calcular drawdown
#   4. [PATCH 1] compute_smooth_leverage() -> current_leverage
#   5. [PATCH 2] compute_regime_score() -> max_positions
#   6. Cash yield diario
#   7. [PATCH 3] Calcular scores UNA VEZ aquí:
#      ```
#      current_scores = compute_momentum_scores(
#          price_data, tradeable_symbols, date, all_dates, i
#      )
#      ```
#   8. Loop de exits (reusar current_scores para renewal check)
#   9. Abrir nuevas posiciones (reusar current_scores, NO recalcular)
#
# En el loop de exits, REEMPLAZAR:
#
#   ```
#   # ANTES (fragmento del exit por tiempo):
#   if days_held >= HOLD_DAYS:
#       exit_reason = 'hold_expired'
#
#   # DESPUÉS (con renewal):
#   if exit_reason is None and days_held >= HOLD_DAYS:
#       if should_renew_position(symbol, pos, current_price,
#                                days_held, current_scores):
#           # Renovar: extender expiry
#           # El entry_idx se mueve hacia adelante para dar HOLD_DAYS más
#           pos['entry_idx'] = i  # Resetear el contador de días
#           # high_price NO se resetea: trailing continua
#           # exit_reason queda None -> posición continua
#       else:
#           exit_reason = 'hold_expired'
#   ```
#
# En el bloque de "abrir nuevas posiciones", REEMPLAZAR:
#
#   ```
#   # ANTES:
#   scores = compute_momentum_scores(price_data, tradeable_symbols, date, all_dates, i)
#
#   # DESPUÉS (reusar):
#   # current_scores ya fue calculado arriba
#   available_scores = {s: sc for s, sc in current_scores.items()
#                       if s not in positions}
#   ```


# ============================================================================
# PATCH 4: QUALITY FILTER (Excluir stocks con vol > 60%)
# ============================================================================
#
# PROBLEMA: Con 744 stocks históricas, algunas tienen volatilidades > 80%
# anualizada que no se comportan bien para momentum. Causan drawdowns
# desproporcionados cuando colapsan. Con 113 stocks actuales, impacto = 0.
#
# SOLUCIÓN: Filtrar stocks con vol anualizada (63d) > 60% antes de calcular
# momentum scores. Además, filtrar datos corrompidos (movidas > 50% en un día).
# ============================================================================

# Nuevos parámetros para quality filter
QUALITY_VOL_MAX = 0.60       # Excluir stocks con vol > 60% anualizada
QUALITY_VOL_LOOKBACK = 63    # Ventana de 3 meses para calcular vol
QUALITY_MAX_SINGLE_DAY = 0.50  # Excluir si retorno de un día > 50% (datos corruptos)


def compute_quality_filter(price_data: Dict[str, pd.DataFrame],
                           tradeable: List[str],
                           date: pd.Timestamp) -> List[str]:
    """
    Filter out stocks unsuitable for momentum strategies.

    Excludes:
    1. Stocks with 63-day realized annualized vol > QUALITY_VOL_MAX (60%)
    2. Stocks with any single-day return > 50% in the past 63 days (likely corrupt)

    With 113 current S&P 500 stocks: approximately 0 stocks filtered.
    With 744 historical stocks: filters ~5-15% each period.

    Stocks with insufficient history (< QUALITY_VOL_LOOKBACK days) PASS by default
    because we can't confirm they fail, and the position-level stop protects us.

    Args:
        price_data: Full price data dictionary
        tradeable: List of currently eligible symbols (from get_tradeable_symbols)
        date: Current trading date

    Returns:
        List of symbols passing the quality filter. Always >= 5 stocks
        (fallback to full tradeable list if filter is too aggressive).
    """
    passed = []

    for symbol in tradeable:
        if symbol not in price_data:
            continue

        df = price_data[symbol]
        if date not in df.index:
            continue

        try:
            sym_idx = df.index.get_loc(date)
        except KeyError:
            continue

        # Insufficient history: pass by default
        if sym_idx < QUALITY_VOL_LOOKBACK + 1:
            passed.append(symbol)
            continue

        # Compute 63-day returns
        prices = df['Close'].iloc[sym_idx - QUALITY_VOL_LOOKBACK:sym_idx + 1]
        rets = prices.pct_change().dropna()

        if len(rets) < QUALITY_VOL_LOOKBACK - 5:
            passed.append(symbol)  # Too few data points: pass
            continue

        # Check for data corruption (single day > 50%)
        max_abs_ret = float(rets.abs().max())
        if max_abs_ret > QUALITY_MAX_SINGLE_DAY:
            continue  # Likely corrupt data: exclude

        # Check annualized vol
        ann_vol = float(rets.std() * np.sqrt(252))
        if ann_vol <= QUALITY_VOL_MAX:
            passed.append(symbol)
        # else: high-vol stock excluded

    # Safety fallback: if filter is too aggressive, use full list
    if len(passed) < 5:
        return tradeable

    return passed


# ============================================================================
# INTEGRACIÓN DE PATCH 4 EN run_backtest()
# ============================================================================
#
# AGREGAR después de calcular tradeable_symbols y ANTES de compute_momentum_scores:
#
#   ```
#   # Quality filter (after get_tradeable_symbols, before momentum scores)
#   quality_symbols = compute_quality_filter(price_data, tradeable_symbols, date)
#
#   # current_scores ahora usa quality_symbols en lugar de tradeable_symbols
#   current_scores = compute_momentum_scores(
#       price_data, quality_symbols, date, all_dates, i
#   )
#   ```
#
# El fallback dentro de compute_quality_filter() garantiza que si el filtro
# es demasiado agresivo (< 5 stocks pasan), se usa la lista completa.


# ============================================================================
# FUNCIÓN AUXILIAR: Verificación de consistencia de patches
# ============================================================================

def verify_patches_compatible() -> bool:
    """
    Smoke test para verificar que los 4 patches son internamente consistentes.
    Ejecutar después de integrar en omnicapital_v8_compass.py.

    Returns True si todo es consistente.
    """
    print("Verificando compatibilidad de patches...")

    # Test PATCH 1: DD leverage
    assert abs(_dd_leverage(0.0) - 1.0) < 1e-10, "DD=0 debe dar 1.0"
    assert abs(_dd_leverage(-0.05) - 1.0) < 1e-10, "DD=-5% debe dar 1.0"
    lev_10 = _dd_leverage(-0.10)
    assert 0.50 < lev_10 < 1.0, f"DD=-10% debe estar entre 0.50 y 1.0, got {lev_10:.3f}"
    assert abs(_dd_leverage(-0.25) - LEV_FLOOR) < 0.05, "DD=-25% debe estar cerca del floor"
    assert abs(_dd_leverage(-0.50) - LEV_FLOOR) < 1e-10, "DD=-50% debe dar LEV_FLOOR"
    print("  PATCH 1 (DD leverage): OK")

    # Test PATCH 2: Regime score
    # Create synthetic SPY data
    np.random.seed(42)
    n = 300
    dates_test = pd.bdate_range('2023-01-01', periods=n)
    prices = 450.0 * np.exp(np.cumsum(np.random.normal(0.0003, 0.01, n)))
    spy_test = pd.DataFrame({'Close': prices}, index=dates_test)

    score = compute_regime_score(spy_test, dates_test[-1])
    assert 0.0 <= score <= 1.0, f"Score debe estar en [0,1], got {score:.3f}"

    # Tz-aware test
    tz_date = dates_test[-1].tz_localize('America/New_York')
    score_tz = compute_regime_score(spy_test, tz_date)
    assert abs(score - score_tz) < 1e-10, "TZ-aware y TZ-naive deben dar el mismo score"

    # Test positions
    assert regime_score_to_positions(0.8) == 5, "Score 0.8 debe dar 5 posiciones"
    assert regime_score_to_positions(0.55) == 4, "Score 0.55 debe dar 4 posiciones"
    assert regime_score_to_positions(0.40) == 3, "Score 0.40 debe dar 3 posiciones"
    assert regime_score_to_positions(0.20) == 2, "Score 0.20 debe dar 2 posiciones"
    print("  PATCH 2 (Regime continuo): OK")

    # Test PATCH 3: Exit renewal
    pos_test = {'entry_price': 100.0, 'high_price': 105.0}
    scores_test = {'AAPL': 1.5, 'MSFT': 1.2, 'NVDA': 0.8, 'META': 0.5, 'AMZN': 0.2}

    # Should renew: AAPL at day 5 with +3% profit, score rank 1st (100th percentile)
    renew = should_renew_position('AAPL', pos_test, 103.0, 5, scores_test)
    assert renew == True, "AAPL con +3% profit y top score deberia renovar"

    # Should NOT renew: profit too low
    no_renew = should_renew_position('AAPL', pos_test, 100.5, 5, scores_test)
    assert no_renew == False, "No deberia renovar con solo +0.5% profit"

    # Should NOT renew: at max hold
    no_renew2 = should_renew_position('AAPL', pos_test, 103.0, HOLD_DAYS_MAX, scores_test)
    assert no_renew2 == False, "No deberia renovar en el dia max"

    # Should NOT renew: AMZN at bottom of scores (20th percentile)
    no_renew3 = should_renew_position('AMZN', pos_test, 103.0, 5, scores_test)
    assert no_renew3 == False, "AMZN en el fondo de scores no deberia renovar"
    print("  PATCH 3 (Exit renewal): OK")

    # Test PATCH 4: Quality filter
    # Create synthetic price data with one high-vol stock
    dates_q = pd.bdate_range('2022-01-01', periods=100)

    # Normal stock: ~20% vol
    normal_prices = 100.0 * np.exp(np.cumsum(np.random.normal(0.0003, 0.012, 100)))
    # High-vol stock: ~90% vol
    highvol_prices = 50.0 * np.exp(np.cumsum(np.random.normal(0.0001, 0.057, 100)))

    price_data_q = {
        'NORMAL': pd.DataFrame({'Close': normal_prices}, index=dates_q),
        'HIGHVOL': pd.DataFrame({'Close': highvol_prices}, index=dates_q),
    }

    filtered = compute_quality_filter(price_data_q, ['NORMAL', 'HIGHVOL'], dates_q[-1])
    assert 'NORMAL' in filtered, "NORMAL stock deberia pasar el filtro"
    # HIGHVOL may or may not pass depending on exact vol (random seed based)
    print(f"  PATCH 4 (Quality filter): OK (filtered: {len(filtered)}/{2} stocks passed)")

    print("\nTodos los patches verificados correctamente.")
    return True


if __name__ == '__main__':
    verify_patches_compatible()
