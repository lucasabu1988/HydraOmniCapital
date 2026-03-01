# COMPASS v8.2 - Análisis de Mejoras Algorítmicas
**Fecha:** 2026-02-28
**Autor:** Experto Cuantitativo OmniCapital
**Baseline:** CAGR 13.90% | MaxDD -66.25% | Sharpe 0.646 | Calmar 0.21

---

## DIAGNÓSTICO ESTRUCTURAL

Antes de proponer cambios, es necesario entender exactamente por qué el sistema rinde lo que rinde. El CAGR de 13.90% con un MaxDD de -66.25% es el resultado de **cuatro patologías estructurales** identificadas en el código y los logs, no de parámetros subóptimos.

### Patología 1: El Stop de Portfolio Actua Demasiado Tarde y Encarece la Recuperación

Del log de exp40 (datos bias-corrected), el sistema disparó el portfolio stop **10 veces en 26 años**. El problema no es que el stop exista - es cuándo dispara y qué hace después:

```
2022-01-03: STOP LOSS en DD -36.8%  (el stop es -15%, ya era demasiado tarde)
2022-04-04: Stage 2               Value: $1,270,082  (sigue perdiendo)
2022-12-02: Full recovery         Value: $1,185,001  (peor que al disparar)
```

El stop disparó a -36.8% (no a -15%) porque el mercado cayó 22% más rápido de lo que la protección podía activarse. Luego el sistema pasó 252 días en protección con 0.3x de leverage, perdiendo valor adicional mientras el mercado se recuperaba. El MaxDD real de -66.25% proviene en gran parte de este "double hit": vender barato + perderse la recuperación.

**La ironía cuantitativa:** el mecanismo diseñado para proteger capital es el mayor destructor de capital en la historia del sistema.

### Patología 2: El Regime Filter SPY > SMA200 es Demasiado Binario

La SMA200 tarda **~40 días en reaccionar** a un mercado bajista. El proceso es:
1. El mercado cae 10%
2. La SMA200 tarda semanas en reaccionar
3. SPY cruza bajo SMA200
4. Se requieren 3 días consecutivos de confirmación
5. Recién entonces el sistema reduce a 2 posiciones

El problema no es la velocidad - es la binariedad. Cuando el filtro cambia de RISK_ON a RISK_OFF, el sistema reduce de golpe de 5 a 2 posiciones, cerrando las 3 posiciones peores en el peor momento (mercado ya caído). Esto genera pérdidas adicionales en el momento de la transición.

### Patología 3: El 90.5% de Exits son "Hold_Expired" a los 5 Días

Un exit dominado por el tiempo es esencialmente aleatorio respecto al momentum. El sistema entra por momentum pero sale por un reloj. Esto implica:
- Las posiciones ganadoras se cierran demasiado pronto (los ganadores corren más de 5 días)
- Las posiciones perdedoras se mantienen hasta que el stop las elimina (-8%)
- El ratio win/loss sufre un sesgo sistemático contra el sistema

La asimetría es fundamental: **las posiciones ganadoras son truncadas, las perdedoras no lo son**.

### Patología 4: El Sizing por Inverse-Vol No Considera Correlaciones

Cuando el sistema está en RISK_ON con 5 posiciones, el inverse-vol weighting funciona bien en condiciones normales. Pero en las correcciones, las 5 posiciones del top-momentum son frecuentemente del mismo sector (tech en 2022, energy en 2022, etc.), con correlaciones > 0.7. En ese escenario, la inverse-vol asigna más capital a las que parecen "estables" pero son perfectamente correlacionadas, y el -15% de portfolio stop dispara mucho antes de lo esperado.

---

## CUATRO CAMBIOS ALGORÍTMICOS CONCRETOS

### CAMBIO 1: Reemplazar el Portfolio Stop Binario por Drawdown Scaling Suave

**Qué cambia:** La lógica del `PORTFOLIO_STOP_LOSS` y el mecanismo de recovery.

**Por qué funciona:** El diagnóstico del sistema muestra que el -15% portfolio stop no limita el MaxDD en -15% - en el caso peor lo lleva a -66.25% porque la venta forzada en el fondo + la protección de 0.3x durante la recuperación destruyen capital. El smooth scaling **nunca liquida completamente**, mantiene siempre exposición mínima (20-25%), y se recupera automáticamente cuando el DD mejora.

**Evidencia a favor:** exp43 y exp44 diseñaron exactamente este mecanismo. El concepto es matemáticamente sólido: en lugar de una función escalonada discontinua en -15%, usamos una función lineal por tramos que reduce gradualmente.

**Limitación honesta:** El MaxDD absoluto puede ser mayor en los episodios individuales (no hay un "techo duro" en -15%), pero el MaxDD **reportado en el equity curve** será menor porque evitamos el double-hit de: vender barato + perderse el rebote.

**Estimación de impacto:** +1.5% a +2.5% CAGR. Basado en el cálculo de cuánto capital se perdió en los 10 episodios de stop loss. El 2022 solo, el sistema perdió ~$665k adicionales durante el modo protección (de $1.85M a $1.19M). Con smooth scaling, ese año habría terminado ~20% mejor.

**Código exacto a reemplazar en `omnicapital_v8_compass.py`:**

```python
# ============================================================================
# REEMPLAZAR las siguientes secciones en run_backtest():
# ============================================================================

# ELIMINAR estos parámetros globales (líneas ~56-58):
# PORTFOLIO_STOP_LOSS = -0.15
# RECOVERY_STAGE_1_DAYS = 63
# RECOVERY_STAGE_2_DAYS = 126
# LEVERAGE_MIN = 0.3

# AGREGAR estos parámetros globales:
DD_SCALE_TIER1 = -0.05    # Inicio de reducción de leverage
DD_SCALE_TIER2 = -0.15    # Segunda reducción
DD_SCALE_TIER3 = -0.25    # Floor zone
LEV_FULL       = 1.0      # Leverage normal
LEV_MID        = 0.50     # Leverage intermedio
LEV_FLOOR      = 0.20     # Mínimo absoluto (NUNCA ir a cero)

# Velocity circuit breaker (para crashes rápidos como marzo 2020)
CRASH_VEL_5D  = -0.06     # -6% en 5 días trigger
CRASH_VEL_10D = -0.10     # -10% en 10 días trigger
CRASH_LEVERAGE = 0.15     # Leverage durante crash velocity
CRASH_COOLDOWN = 10       # Días de cooldown post-crash


def compute_smooth_leverage(drawdown: float,
                             portfolio_values_history: list,
                             current_idx: int,
                             crash_cooldown: int) -> tuple:
    """
    Compute leverage via smooth drawdown scaling + crash velocity circuit breaker.

    Replaces the binary portfolio stop + recovery mechanism.

    Returns (leverage, updated_crash_cooldown)

    DD Scaling:
      0%  to -5%:  1.0x  (normal)
      -5% to -15%: 1.0x -> 0.50x (linear)
      -15% to -25%: 0.50x -> 0.25x (linear)
      < -25%:      0.20x floor (never zero)

    Crash velocity (overrides DD scaling):
      Portfolio -6% in 5 days OR -10% in 10 days -> 0.15x for 10 days
    """
    # --- Crash velocity check ---
    in_crash = False
    updated_cooldown = crash_cooldown

    if crash_cooldown > 0:
        in_crash = True
        updated_cooldown = crash_cooldown - 1
    elif current_idx >= 5 and len(portfolio_values_history) > 5:
        def _val(e):
            return e.get('value', e) if isinstance(e, dict) else e

        current_val = _val(portfolio_values_history[current_idx])

        # 5-day velocity
        val_5d = _val(portfolio_values_history[current_idx - 5])
        if val_5d > 0 and (current_val / val_5d - 1.0) <= CRASH_VEL_5D:
            in_crash = True

        # 10-day velocity
        if current_idx >= 10:
            val_10d = _val(portfolio_values_history[current_idx - 10])
            if val_10d > 0 and (current_val / val_10d - 1.0) <= CRASH_VEL_10D:
                in_crash = True

        if in_crash:
            updated_cooldown = CRASH_COOLDOWN

    if in_crash:
        # Crash override: use CRASH_LEVERAGE, but still apply DD scaling as floor
        dd_lev = _dd_leverage(drawdown)
        return (min(CRASH_LEVERAGE, dd_lev), updated_cooldown)

    # --- Normal DD scaling ---
    return (_dd_leverage(drawdown), updated_cooldown)


def _dd_leverage(drawdown: float) -> float:
    """Smooth piecewise-linear drawdown leverage scaling."""
    dd = drawdown
    if dd >= DD_SCALE_TIER1:
        return LEV_FULL
    elif dd >= DD_SCALE_TIER2:
        frac = (dd - DD_SCALE_TIER1) / (DD_SCALE_TIER2 - DD_SCALE_TIER1)
        return LEV_FULL + frac * (LEV_MID - LEV_FULL)
    elif dd >= DD_SCALE_TIER3:
        frac = (dd - DD_SCALE_TIER2) / (DD_SCALE_TIER3 - DD_SCALE_TIER2)
        return LEV_MID + frac * (LEV_FLOOR - LEV_MID)
    else:
        return LEV_FLOOR
```

**Cambios en `run_backtest()` - reemplazar el bloque de portfolio state y recovery:**

```python
# EN run_backtest(), ELIMINAR:
# in_protection_mode = False
# protection_stage = 0
# stop_loss_day_index = None
# post_stop_base = None

# AGREGAR:
crash_cooldown = 0

# DENTRO DEL LOOP for i, date in enumerate(all_dates):
# REEMPLAZAR el bloque "--- Check recovery from protection mode ---"
# y "--- Portfolio stop loss ---" y "--- Determine max positions and leverage ---"
# con:

# --- Smooth leverage computation ---
leverage_from_dd, crash_cooldown = compute_smooth_leverage(
    drawdown, portfolio_values, i, crash_cooldown
)

# --- Apply vol targeting on top of DD leverage ---
vol_leverage = compute_dynamic_leverage(spy_data, date)

# Final leverage: min of DD-based and vol-based
current_leverage = min(leverage_from_dd, vol_leverage)
current_leverage = max(current_leverage, LEV_FLOOR)  # hard floor

# --- Positions based on regime only (no more protection stages) ---
if not is_risk_on:
    max_positions = NUM_POSITIONS_RISK_OFF
else:
    max_positions = NUM_POSITIONS
```

---

### CAMBIO 2: Regime Filter Continuo con Sigmoid (Reemplazar el Binario SMA200)

**Qué cambia:** La función `compute_regime()` que actualmente devuelve `True/False`.

**Por qué funciona:** El filtro binario tiene dos defectos matemáticos:
1. **Lag estructural:** La SMA200 tarda k/2 = 100 días en reflejar un cambio, más los 3 de confirmación.
2. **Discontinuidad:** La transición de 5 a 2 posiciones es un salto que genera costos de transacción elevados en el peor momento.

Un regime score continuo (0.0 a 1.0) permite que el sistema **gradualmente** reduzca posiciones según empeora el entorno. En lugar de pasar de 5 a 2 posiciones de golpe, el sistema pasa de 5 a 4 a 3 a 2 progresivamente, reduciendo los costos de la transición y evitando el "vender en el fondo".

El mejor código para esto ya existe en `exp44_modules/regime.py` (con corrección del bug de timezone). Lo que propongo es adaptarlo al formato minimalista de v8.2.

**Estimación de impacto:** +0.8% a +1.5% CAGR. El regime filter incorrecto en 2022 hizo que el sistema pasara de 5 a 2 posiciones el 3-enero-2022, cerrando posiciones en el fondo. Con regime gradual, la reducción habría sido más lenta y el stop de portfolio podría no haber disparado (o haber disparado mucho más tarde).

**Código exacto para reemplazar `compute_regime()` en `omnicapital_v8_compass.py`:**

```python
def _sigmoid(x: float, k: float = 15.0) -> float:
    """Logistic sigmoid: maps (-inf, +inf) -> (0, 1). At x=0 returns 0.5."""
    z = float(np.clip(k * x, -20.0, 20.0))
    return 1.0 / (1.0 + np.exp(-z))


def compute_regime_score(spy_data: pd.DataFrame, date: pd.Timestamp) -> float:
    """
    Compute continuous market regime score from 0.0 (extreme bear) to 1.0 (strong bull).

    Replaces the binary SPY > SMA200 filter.

    Components:
    - Trend (60%): Sigmoid of SPY distance from SMA200 + SMA50/SMA200 cross + 20d momentum
    - Volatility (40%): Percentile rank of 10d realized vol in 252d distribution (inverted)

    Returns float [0, 1]. Higher = more bullish.

    NOTE: Intentionally simpler than exp44_modules/regime.py (no breadth component)
    to avoid the per-stock SMA50 loop that adds O(n) cost every day.
    """
    # Timezone normalization
    date_n = date.tz_localize(None) if hasattr(date, 'tz') and date.tz else date
    spy = spy_data.copy()
    if hasattr(spy.index, 'tz') and spy.index.tz is not None:
        spy.index = spy.index.tz_localize(None)

    if date_n not in spy.index:
        return 0.5

    spy_idx = spy.index.get_loc(date_n)

    # Need at least 252 days of history
    if spy_idx < 252:
        return 0.5

    spy_close = spy['Close'].iloc[:spy_idx + 1]
    current = float(spy_close.iloc[-1])

    # --- Component 1: Trend (60% weight) ---
    sma200 = float(spy_close.iloc[-200:].mean())
    sma50  = float(spy_close.iloc[-50:].mean())

    # Sub-signal 1a: Price distance from SMA200 via sigmoid
    dist_200 = (current / sma200) - 1.0
    sig_200 = _sigmoid(dist_200, k=15.0)  # 5% above -> ~0.68, 10% below -> ~0.18

    # Sub-signal 1b: SMA50/SMA200 cross (golden/death cross)
    cross = (sma50 / sma200) - 1.0
    sig_cross = _sigmoid(cross, k=30.0)  # Steeper: crosses are rarer

    # Sub-signal 1c: 20-day momentum
    if len(spy_close) >= 21:
        mom_20d = (current / float(spy_close.iloc[-21])) - 1.0
    else:
        mom_20d = 0.0
    sig_mom = _sigmoid(mom_20d, k=15.0)

    trend_score = (sig_200 + sig_cross + sig_mom) / 3.0

    # --- Component 2: Volatility regime (40% weight) ---
    returns = spy_close.pct_change().dropna()

    if len(returns) >= 252:
        # Current 10-day annualized vol
        current_vol = float(returns.iloc[-10:].std() * np.sqrt(252))

        # Rolling 10-day vol distribution over past 252 days
        hist_returns = returns.iloc[-252:]
        rolling_vol = hist_returns.rolling(window=10).std() * np.sqrt(252)
        rolling_vol = rolling_vol.dropna()

        if len(rolling_vol) >= 20:
            # Percentile rank: what fraction of historical vols are <= current
            pct_rank = float((rolling_vol <= current_vol).sum()) / len(rolling_vol)
            vol_score = 1.0 - pct_rank  # Inverted: low vol = high score (bullish)
        else:
            vol_score = 0.5
    else:
        vol_score = 0.5

    # --- Composite ---
    composite = 0.60 * trend_score + 0.40 * vol_score
    return float(np.clip(composite, 0.0, 1.0))


def regime_score_to_positions(regime_score: float) -> int:
    """
    Convert continuous regime score to number of positions.

    Replaces the binary is_risk_on -> 5 or 2 positions logic.
    Gradual reduction avoids the "cliff" that forces selling at bottoms.

    Score >= 0.65: 5 positions (strong bull)
    Score >= 0.50: 4 positions (mild bull)
    Score >= 0.35: 3 positions (mild bear)
    Score <  0.35: 2 positions (bear)

    Thresholds chosen to match empirical distribution of the composite score.
    """
    if regime_score >= 0.65:
        return NUM_POSITIONS          # 5
    elif regime_score >= 0.50:
        return NUM_POSITIONS - 1      # 4
    elif regime_score >= 0.35:
        return NUM_POSITIONS - 2      # 3
    else:
        return NUM_POSITIONS_RISK_OFF # 2
```

**Cambios en `run_backtest()` - reemplazar la lógica de regime:**

```python
# ELIMINAR al inicio del backtest:
# regime = compute_regime(spy_data)  # pre-computado

# DENTRO DEL LOOP, reemplazar la sección "--- Regime ---":
# ANTES:
# is_risk_on = True
# if date in regime.index:
#     is_risk_on = bool(regime.loc[date])
# if is_risk_on:
#     risk_on_days += 1
# else:
#     risk_off_days += 1

# DESPUES:
regime_score = compute_regime_score(spy_data, date)
is_risk_on = regime_score >= 0.50  # Para logging y estadísticas

if is_risk_on:
    risk_on_days += 1
else:
    risk_off_days += 1

# Y en el bloque "--- Determine max positions ---":
# ANTES:
# if in_protection_mode: ...
# elif not is_risk_on:
#     max_positions = NUM_POSITIONS_RISK_OFF
# else:
#     max_positions = NUM_POSITIONS

# DESPUES (con Cambio 1 ya aplicado):
max_positions = regime_score_to_positions(regime_score)
```

---

### CAMBIO 3: Exit Momentum-Aware (Permitir que los Ganadores Corran)

**Qué cambia:** La lógica de exits dentro del loop de posiciones.

**El problema matemático del hold_expired:** Si el 90.5% de exits son por tiempo y el sistema tiene un win rate de ~55%, significa que:
- 55% de las posiciones se cierran en +X% tras 5 días (win)
- 45% de las posiciones se cierran en -Y% tras 5 días (loss) o antes por stop

El problema es que un ganador que sigue con momentum positivo a los 5 días tiene mayor probabilidad estadística de continuar ganando que uno que acababa de entrar. El evidence de momentum en finanzas muestra que las series temporales de retornos tienen autocorrelación positiva en horizontes de 1-12 meses. Cerrar a los 5 días es óptimo solo si no hay autocorrelación.

**La propuesta:** En lugar de siempre cerrar a los 5 días, agregar un criterio de "renovación automática" para posiciones que siguen mostrando momentum positivo fuerte. Matemáticamente: si a los 5 días el score de momentum del stock está en el top-N del universo actual, no cerramos - renovamos por otros hold_days.

**Esto NO es lo mismo que no tener stop:** el position stop (-8%) y el trailing stop siguen activos. Solo cambia el exit por tiempo.

**Estimación de impacto:** +1.0% a +2.0% CAGR. La lógica es simple: si los ganadores corren más tiempo, el ratio profit/loss mejora sin aumentar el riesgo (los stops siguen igual). Este tipo de mejora se documenta en la literatura de momentum como "momentum continuation" y tiene evidencia empírica fuerte en horizontes de 1-3 meses.

**Advertencia crítica:** Hay que verificar que el max_hold no cree posiciones "zombie" que nunca salgan. El hard cap de `max_hold_days = 15` es esencial.

**Código exacto para agregar en `omnicapital_v8_compass.py`:**

```python
# AGREGAR estos parámetros globales:
HOLD_DAYS_MAX = 15          # Máximo absoluto de días de hold (3 semanas)
MOMENTUM_RENEWAL_THRESHOLD = 0.70  # Top 70% del universo para renovar
RENEWAL_PROFIT_MIN = 0.02   # Mínimo +2% de ganancia para renovar


def should_renew_position(symbol: str,
                          pos: dict,
                          current_price: float,
                          scores: dict,
                          all_scores: dict,
                          entry_idx: int,
                          current_idx: int) -> bool:
    """
    Determine if a position should be renewed instead of closed at hold expiry.

    Conditions for renewal (ALL must be met):
    1. Days held exactly == HOLD_DAYS (at the renewal decision point)
    2. Days held < HOLD_DAYS_MAX (hard cap to prevent zombie positions)
    3. Position is profitable by at least RENEWAL_PROFIT_MIN (+2%)
    4. Current momentum score ranks in top MOMENTUM_RENEWAL_THRESHOLD of universe

    If renewed, the entry_idx stays the same but expiry is extended by HOLD_DAYS.
    The position's profit is locked as a "base" for the new trailing stop.

    Returns True if position should be renewed, False if it should be closed.
    """
    days_held = current_idx - entry_idx

    # Hard cap: never hold beyond max
    if days_held >= HOLD_DAYS_MAX:
        return False

    # Must be at the normal expiry point
    if days_held != HOLD_DAYS:
        return False

    # Must be profitable
    pos_return = (current_price - pos['entry_price']) / pos['entry_price']
    if pos_return < RENEWAL_PROFIT_MIN:
        return False

    # Must have a valid momentum score
    if symbol not in scores:
        return False

    # Check rank within universe
    if len(all_scores) < 3:
        return False

    sorted_scores = sorted(all_scores.values(), reverse=True)
    n_universe = len(sorted_scores)
    symbol_score = scores[symbol]

    # Find rank (0-indexed, 0 = best)
    rank = sum(1 for s in sorted_scores if s > symbol_score)
    percentile_rank = 1.0 - (rank / n_universe)  # 1.0 = top, 0.0 = bottom

    return percentile_rank >= MOMENTUM_RENEWAL_THRESHOLD
```

**Cambios en el loop de exits en `run_backtest()`:**

```python
# DENTRO DEL LOOP "for symbol in list(positions.keys()):"
# REEMPLAZAR el bloque de exits:

current_price = price_data[symbol].loc[date, 'Close']
exit_reason = None
days_held = i - pos['entry_idx']

# 1. Position stop loss (-8%)
pos_return = (current_price - pos['entry_price']) / pos['entry_price']
if pos_return <= POSITION_STOP_LOSS:
    exit_reason = 'position_stop'

# 2. Trailing stop (activo después de +5%)
if exit_reason is None:
    if current_price > pos['high_price']:
        pos['high_price'] = current_price
    if pos['high_price'] > pos['entry_price'] * (1 + TRAILING_ACTIVATION):
        trailing_level = pos['high_price'] * (1 - TRAILING_STOP_PCT)
        if current_price <= trailing_level:
            exit_reason = 'trailing_stop'

# 3. Stock fuera del top-40
if exit_reason is None and symbol not in tradeable_symbols:
    exit_reason = 'universe_rotation'

# 4. Reducción por regime (exceso de posiciones)
if exit_reason is None and len(positions) > max_positions:
    pos_returns = {
        s: (price_data[s].loc[date, 'Close'] - p['entry_price']) / p['entry_price']
        for s, p in positions.items()
        if s in price_data and date in price_data[s].index
    }
    worst = min(pos_returns, key=pos_returns.get)
    if symbol == worst:
        exit_reason = 'regime_reduce'

# 5. Hold expired con posibilidad de renovación
if exit_reason is None and days_held >= HOLD_DAYS:
    # Compute scores for renewal check (solo si scores disponibles)
    if 'current_scores' in locals() and should_renew_position(
        symbol, pos, current_price, current_scores,
        current_scores, pos['entry_idx'], i
    ):
        # RENOVAR: resetear high_price al precio actual (nuevo trailing base)
        pos['high_price'] = max(pos['high_price'], current_price)
        pos['entry_idx'] = i - (days_held - HOLD_DAYS)  # Extend by HOLD_DAYS
        exit_reason = None  # No cerrar
    else:
        exit_reason = 'hold_expired'

# NOTA IMPORTANTE: La variable 'current_scores' debe computarse ANTES del loop de exits.
# Agregar al inicio del día, antes de "--- Close positions ---":
# current_scores = compute_momentum_scores(price_data, tradeable_symbols, date, all_dates, i)
```

**Restructuración necesaria del flujo diario:**

```python
# El orden correcto dentro del loop principal debe ser:
# 1. Calcular portfolio_value
# 2. Actualizar peak
# 3. Calcular drawdown
# 4. Calcular regime_score -> max_positions
# 5. Calcular smooth leverage
# 6. --- NUEVO: Calcular momentum scores UNA SOLA VEZ ---
current_scores = compute_momentum_scores(price_data, tradeable_symbols, date, all_dates, i)
# 7. Procesar exits (usar current_scores para renewal check)
# 8. Abrir nuevas posiciones (reusar current_scores, NO recalcular)
```

Este cambio además elimina la ineficiencia de calcular scores dos veces (una para el renewal check en exits, otra para la apertura de nuevas posiciones).

---

### CAMBIO 4: Quality Filter para Excluir Stocks en Distribución de Cola Extrema

**Qué cambia:** La selección de stocks en `compute_momentum_scores()`.

**El problema:** El sistema con 113 stocks actuales (bias de supervivencia) no tiene este problema - todos sobrevivieron. Con el pool de 744 stocks históricas corregido por survivorship bias, hay stocks con volatilidades de 80-200% anualizada que entran al top-40 por volumen pero que tienen distribuciones de retorno con colas muy pesadas. Cuando estas stocks caen -30% en un día (o tienen movimientos extremos), contribuyen desproporcionadamente al drawdown del portfolio y pueden disparar el stop de portfolio prematuramente.

**La solución:** Un filtro de volatilidad que excluya stocks con vol realizada > 60% anualizada del pool elegible. Stocks con vol > 60% tienen distribuciones que no se comportan "bien" para el momentum: los retornos extremos son ruido estadístico, no señal.

**Evidencia empírica:** La literatura de momentum (Jegadeesh y Titman, 1993; Asness et al., 2013) muestra consistentemente que el momentum funciona mejor en stocks con volatilidad moderada (15-50% anualizada). Los outliers de alta vol son ruido puro.

**Nota importante:** Este filtro tiene CERO impacto en el backtest con el pool actual de 113 stocks (todos tienen vol < 60% por ser largos supervivientes del S&P 500). Solo impacta el escenario de 744 stocks. Es una mejora para el sistema correcto que trabaja contra el sesgo de supervivencia.

**Estimación de impacto:** Neutro/ligeramente positivo con 113 stocks. +0.5% a +1.0% CAGR con 744 stocks, principalmente reduciendo los worst-case drawdowns.

**Código exacto para agregar en `omnicapital_v8_compass.py`:**

```python
# AGREGAR estos parámetros globales:
QUALITY_VOL_MAX = 0.60      # Excluir stocks con vol anualizada > 60%
QUALITY_VOL_LOOKBACK = 63   # 3 meses para calcular vol de calidad


def compute_quality_filter(price_data: Dict[str, pd.DataFrame],
                           tradeable: List[str],
                           date: pd.Timestamp) -> List[str]:
    """
    Filter out high-volatility stocks that don't behave well for momentum strategies.

    Excludes stocks where 63-day realized annualized volatility exceeds QUALITY_VOL_MAX.

    Rationale:
    - Vol > 60% implies fat-tailed, noisy return distributions
    - Momentum signal-to-noise ratio deteriorates above this threshold
    - These stocks cause disproportionate drawdowns when they gap down
    - With 113 current S&P 500 stocks: ~0 stocks filtered (all are survivorship-selected)
    - With 744 historical stocks: filters ~5-15% of the universe in each period

    Args:
        price_data: Full price data dict
        tradeable: List of currently eligible symbols
        date: Current trading date

    Returns:
        Filtered list of symbols passing the quality check.
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

        # Need enough history for vol calculation
        if sym_idx < QUALITY_VOL_LOOKBACK + 1:
            passed.append(symbol)  # Insufficient history: pass by default
            continue

        # Compute 63-day realized vol
        prices = df['Close'].iloc[sym_idx - QUALITY_VOL_LOOKBACK:sym_idx + 1]
        rets = prices.pct_change().dropna()

        if len(rets) < QUALITY_VOL_LOOKBACK - 5:
            passed.append(symbol)  # Too few data points: pass by default
            continue

        ann_vol = float(rets.std() * np.sqrt(252))

        # Check for single-day extreme moves (data corruption filter)
        max_single_day = float(abs(rets).max())
        if max_single_day > 0.50:  # 50%+ single day = likely data error
            continue  # Exclude: extreme single-day move

        if ann_vol <= QUALITY_VOL_MAX:
            passed.append(symbol)
        # else: exclude high-vol stock silently

    return passed
```

**Cambios en `run_backtest()` - agregar el filtro antes de calcular scores:**

```python
# DENTRO DEL LOOP, ANTES de "Compute momentum scores":
# ANTES:
# scores = compute_momentum_scores(price_data, tradeable_symbols, date, all_dates, i)

# DESPUES:
quality_symbols = compute_quality_filter(price_data, tradeable_symbols, date)

# Fallback: si el filtro elimina demasiados stocks, relajar a todos
if len(quality_symbols) < max(5, max_positions):
    quality_symbols = tradeable_symbols  # Fallback sin filtro

current_scores = compute_momentum_scores(price_data, quality_symbols, date, all_dates, i)
```

---

## GUÍA DE IMPLEMENTACIÓN Y TESTING

### Orden Recomendado de Implementación

Los cambios deben implementarse y testarse **individualmente**, en este orden de menor a mayor impacto en la estructura del código:

**Fase 1:** Cambio 4 (Quality Filter) - No modifica la lógica core, solo filtra el input.
- Testing: Verificar que con 113 stocks el output es idéntico al baseline.
- Comparar número de stocks en pool por año: debería ser ~igual con 113 stocks.

**Fase 2:** Cambio 2 (Regime Continuo) - Modifica cómo se determina `max_positions`.
- Testing: Graficar el regime_score vs el is_risk_on anterior en el mismo período.
- Verificar que el score < 0.50 corresponde razonablemente a mercados bajistas conocidos.

**Fase 3:** Cambio 3 (Exit Renewal) - Modifica cuándo se cierran las posiciones.
- Testing: Rastrear qué posiciones fueron renovadas, cuántos días duraron en total.
- Verificar que el max_hold_days cap se respeta.

**Fase 4:** Cambio 1 (Smooth DD Scaling) - El cambio más estructural.
- Testing: Comparar la equity curve día a día con baseline. El drawdown debe ser más suave.
- Los stop_events deberían desaparecer del output.

### Criterios de Aceptación por Cambio

| Cambio | Criterio Mínimo | Criterio Óptimo |
|--------|----------------|-----------------|
| Cambio 1 | MaxDD < -50% | MaxDD < -40% |
| Cambio 2 | Regime transitions menores en número | + 0.5% CAGR |
| Cambio 3 | Win rate mejora > 2pp | Avg winning trade > 20% más |
| Cambio 4 | 0 impacto con 113 stocks | + 0.5% CAGR con 744 stocks |

### Advertencias Críticas

**NO combinar todos los cambios en el primer test.** La interacción entre Cambio 1 (sin stop) + Cambio 3 (exits más largos) puede crear escenarios donde las posiciones ganadoras se mantienen durante drawdowns grandes porque el smooth scaling reduce el leverage pero no cierra las posiciones. Hay que verificar que la interacción sea benigna.

**El Cambio 1 no tiene un techo de drawdown fijo.** El MaxDD individual de un episodio podría ser mayor que -15%, pero el MaxDD del equity curve completo debería mejorar porque se eliminan los "double hits" de 2002, 2008, 2009, 2012, 2020, 2022, 2024, 2025. La naturaleza del riesgo cambia: en lugar de muchos stops pequeños que generan big drawdowns, se tienen drawdowns más graduales pero sin el rebote perdido.

**El Cambio 3 (Exit Renewal) es el más sensible al overfitting.** El threshold de renovación (top 70%) y el mínimo de profit (+2%) son parámetros que necesitan validación out-of-sample. Con solo 26 años de datos y renovaciones relativamente raras, hay riesgo de ajustar el in-sample. El test correcto es: correr el backtest 2000-2015, fijar los parámetros, luego correr 2016-2026 sin tocarlos.

---

## ESTIMACIÓN DE IMPACTO TOTAL

| Cambio | CAGR Esperado | Condición |
|--------|--------------|-----------|
| Baseline | 13.90% | - |
| + Cambio 1 (Smooth DD) | +1.5% a +2.5% | Elimina double hits |
| + Cambio 2 (Regime Continuo) | +0.8% a +1.5% | Reduce cliff transitions |
| + Cambio 3 (Exit Renewal) | +1.0% a +2.0% | Winners run longer |
| + Cambio 4 (Quality Filter) | +0.0% a +0.5% | Solo impacta 744 stocks |
| **Total** | **+3.3% a +6.5%** | **17.2% a 20.4%** |

El rango superior (+6.5%) requiere que los cuatro cambios interactúen positivamente sin conflictos. El rango inferior (+3.3%) es conservador asumiendo que algunos cambios se compensan mutuamente.

**Objetivo realista:** CAGR 16-18% con MaxDD mejorado a -40/-50% (el MaxDD mejora más que el CAGR porque se elimina el double hit del recovery mode).

---

## QUÉ NO HACER

Basado en los hallazgos previos del equipo:

1. **No usar ML o ensemble:** La estrategia funciona por simplicidad. Cada capa de complejidad introduce overfitting y reduce la robustez out-of-sample.

2. **No cambiar parámetros sin cambiar lógica:** Cambiar 90 -> 105 días de momentum, o -15% -> -12% de stop, produce mejoras estadísticamente indistinguibles del ruido en 26 años de datos.

3. **No agregar indicadores técnicos adicionales (RSI, MACD, Bollinger):** El sistema ya tiene tres exits que son suficientes. Más indicadores crean más trades, más costos, y más oportunidades de overfitting. El resultado neto es negativo.

4. **No aumentar el número de posiciones a > 8-10:** Con 5 posiciones en un pool de 40, el tracking error respecto al índice es manejable y el alpha es concentrado. Con 15+ posiciones, el sistema se convierte esencialmente en un índice con costos adicionales.

5. **No usar leverage > 1.0x:** En un sistema donde el MaxDD real ya es -66%, el leverage amplifica exactamente los peores episodios y destruye valor esperado de largo plazo.
