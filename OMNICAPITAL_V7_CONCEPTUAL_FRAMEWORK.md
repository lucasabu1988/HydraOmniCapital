# OmniCapital v7 - Conceptual Framework
## Meta-Sistema Adaptativo

---

## 1. EL PROBLEMA DE LOS SISTEMAS ESTATICOS

Los sistemas de trading estaticos (como v6) funcionan hasta que no. El mundo cambia:
- Regulaciones cambian (Reg NMS, MiFID)
- Estructura de mercado cambia (HFT, dark pools)
- Macroentorno cambia (tasa de interes, inflacion)
- Comportamiento del inversor cambia (Reddit, Robinhood, ETFs)

**Pregunta:** ¿Como construir un sistema que evolucione sin overfitting?

**Respuesta v7:** Un meta-sistema que *selecciona* entre estrategias pre-definidas, no una estrategia que *optimiza* parametros.

---

## 2. ARQUITECTURA v7

```
┌─────────────────────────────────────────────────────────────┐
│                    OMNICAPITAL v7                           │
│                    "ADAPTIVE"                                 │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  ┌──────────────┐    ┌──────────────┐    ┌──────────────┐  │
│  │   SENSOR     │───▶│   BRAIN      │───▶│   ACTUATOR   │  │
│  │              │    │              │    │              │  │
│  │ - VIX        │    │ - Regimen    │    │ - Strategy   │  │
│  │ - SPY trend  │    │   classifier │    │   selector   │  │
│  │ - Breadth    │    │ - Mode       │    │ - Position   │  │
│  │ - Credit     │    │   selector   │    │   sizing     │  │
│  │   spreads    │    │              │    │              │  │
│  └──────────────┘    └──────────────┘    └──────────────┘  │
│                                                             │
│  ┌────────────────────────────────────────────────────────┐│
│  │              STRATEGY ARSENAL                           ││
│  ├────────────────────────────────────────────────────────┤│
│  │                                                         ││
│  │  A. CONSERVADOR (v6 Pure)                               ││
│  │     Hold: 1200min | Lev: 2.0x | Stop: -20%             ││
│  │     Use case: Default, unknown regime                  ││
│  │                                                         ││
│  │  B. AGRESIVO (Momentum)                                 ││
│  │     Hold: 1800min | Lev: 2.5x | Micro: ON              ││
│  │     Use case: Low vol, strong trend                    ││
│  │                                                         ││
│  │  C. DEFENSIVO (Capital Preservation)                    ││
│  │     Hold: 600min  | Lev: 1.0x | Cash: 30%              ││
│  │     Use case: High vol, bear market                    ││
│  │                                                         ││
│  │  D. OPPORTUNISTA (Mean Reversion)                       ││
│  │     Hold: 300min  | Lev: 1.5x | Contrarian: ON         ││
│  │     Use case: Crash, extreme fear                      ││
│  │                                                         ││
│  └────────────────────────────────────────────────────────┘│
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

---

## 3. EL SENSOR: MARKET REGIME DETECTION

### 3.1 Inputs

| Variable | Fuente | Frecuencia | Lag |
|----------|--------|------------|-----|
| VIX | CBOE | Real-time | 15min |
| SPY 20-day return | Yahoo | EOD | 1 day |
| NYSE Advance/Decline | WSJ | EOD | 1 day |
| High Yield Spread | FRED | Daily | 1 day |
| MOVE Index (bond vol) | NYSE | Real-time | 15min |
| DXY (dollar strength) | Yahoo | Real-time | 15min |

### 3.2 Regime Classification

```python
class MarketRegime:
    BULL_CALM = "bull_calm"        # VIX < 15, trend > 0
    BULL_NORMAL = "bull_normal"    # VIX 15-25, trend > 0
    BULL_VOLATILE = "bull_vol"     # VIX > 25, trend > 0
    BEAR_VOLATILE = "bear_vol"     # VIX > 25, trend < 0
    BEAR_CRASH = "bear_crash"      # VIX > 35, trend < -10%
    RECOVERY = "recovery"          # Post-crash, VIX falling
    UNCLEAR = "unclear"            # Mixed signals
```

### 3.3 Regime → Strategy Mapping

| Regime | Primary | Secondary | Max Frequency |
|--------|---------|-----------|---------------|
| bull_calm | AGRESIVO | CONSERVADOR | 1 change/week |
| bull_normal | CONSERVADOR | AGRESIVO | 1 change/week |
| bull_vol | CONSERVADOR | DEFENSIVO | 1 change/week |
| bear_vol | DEFENSIVO | OPPORTUNISTA | 1 change/week |
| bear_crash | DEFENSIVO | Cash | 1 change/week |
| recovery | OPPORTUNISTA | CONSERVADOR | 1 change/week |
| unclear | CONSERVADOR | - | - |

---

## 4. EL BRAIN: DECISION ENGINE

### 4.1 State Machine

```
                    ┌─────────────┐
         ┌─────────▶│ CONSERVADOR │◀────────┐
         │          │   (default) │         │
         │          └──────┬──────┘         │
    VIX▲ │                 │                │ VIX▼
    trend▼ │                 │                │ trend▲
         │          ┌────────▼────────┐      │
         │    ┌─────│                 │─────┐│
         │    │     │   UNCLEAR       │     ││
         │    │     │   (hold current)│     ││
         │    │     └─────────────────┘     ││
         │    │                              ││
    ┌────┘    └──────┐                ┌──────┘└────┐
    │                 │                │             │
    ▼                 ▼                ▼             ▼
┌────────┐      ┌────────┐      ┌────────┐    ┌────────┐
│AGRESIVO│      │DEFENSIV│      │OPPORTUN│    │  CASH  │
│        │      │        │      │  ISTA  │    │        │
└────────┘      └────────┘      └────────┘    └────────┘
```

### 4.2 Transition Rules

```python
def evaluate_transition(current_mode, regime, portfolio_dd):
    """
    Returns: (new_mode, reason) or (None, None) if no change
    """
    
    # Hard rules (always apply)
    if portfolio_dd > -15% and current_mode != "DEFENSIVO":
        return "DEFENSIVO", "Portfolio drawdown protection"
    
    if portfolio_dd > -20%:
        return "DEFENSIVO", "CRITICAL: Stop loss approaching"
    
    # Regime-based rules
    regime_map = {
        "bull_calm": "AGRESIVO",
        "bull_normal": "CONSERVADOR",
        "bull_vol": "CONSERVADOR",
        "bear_vol": "DEFENSIVO",
        "bear_crash": "DEFENSIVO",
        "recovery": "OPPORTUNISTA",
        "unclear": "CONSERVADOR"
    }
    
    recommended = regime_map.get(regime, "CONSERVADOR")
    
    # Hysteresis: don't flip-flop
    if recommended == current_mode:
        return None, None
    
    # Minimum time in mode: 5 trading days
    if days_in_current_mode < 5:
        return None, None
    
    return recommended, f"Regime change: {regime}"
```

---

## 5. EL ACTUATOR: STRATEGY IMPLEMENTATION

### 5.1 Strategy A: CONSERVADOR (v6 Pure)

```python
class ConservativeStrategy:
    hold_minutes = 1200
    leverage = 2.0
    stop_loss = -0.20
    num_positions = 5
    selection = "random"
    micro_management = False
```

### 5.2 Strategy B: AGRESIVO (Momentum)

```python
class AggressiveStrategy:
    hold_minutes = 1800  # 3 overnights
    leverage = 2.5
    stop_loss = -0.15    # Tighter, faster exit
    num_positions = 5
    selection = "momentum_biased"  # Slight tilt to recent winners
    micro_management = True
    
    def micro_rules(self, position):
        if position.return_4h > 0.05:
            return "TAKE_PARTIAL_PROFIT", 0.25
        if position.return_4h < -0.03:
            return "CUT_LOSS", 1.0
        return "HOLD", 0
```

### 5.3 Strategy C: DEFENSIVO (Capital Preservation)

```python
class DefensiveStrategy:
    hold_minutes = 600   # 1 overnight only
    leverage = 1.0       # No margin
    stop_loss = -0.10    # Very tight
    num_positions = 3    # Less exposure
    cash_target = 0.30   # 30% cash
    selection = "quality_biased"  # Slight tilt to low vol stocks
```

### 5.4 Strategy D: OPPORTUNISTA (Mean Reversion)

```python
class OpportunisticStrategy:
    hold_minutes = 300   # Quick in-and-out
    leverage = 1.5
    stop_loss = -0.05    # Very tight
    num_positions = 5
    selection = "oversold"  # Stocks down >10% in 5 days
    
    def entry_filter(self, stock):
        # Only enter if oversold
        return stock.return_5d < -0.10
```

---

## 6. RIESGOS Y MITIGACIONES

### 6.1 Riesgo: Overfitting del Classificador

**Mitigacion:**
- Usar solo variables ampliamente aceptadas (VIX, trend)
- No optimizar thresholds (usar valores estandar: VIX 15, 25, 35)
- Default a CONSERVADOR cuando unclear

### 6.2 Riesgo: Whipsaw en Cambios de Modo

**Mitigacion:**
- Minimo 5 dias en cada modo
- Hysteresis: requerir confirmacion de 2 dias para cambio
- Costos de transicion incluidos en backtest

### 6.3 Riesgo: Estrategia "OPPORTUNISTA" es Trampa de Value

**Mitigacion:**
- Limitar uso de OPPORTUNISTA a post-crash confirmado
- Max 20% del tiempo en OPPORTUNISTA
- Fallback a DEFENSIVO si OPPORTUNISTA pierde >5% en 1 semana

### 6.4 Riesgo: Complejidad Operativa

**Mitigacion:**
- v7 es opcional. v6 siempre disponible como fallback.
- Monitoreo automatico de "regime disagreement"
- Alertas cuando sistema cambia de modo

---

## 7. IMPLEMENTATION CHECKLIST

### Phase 1: Infrastructure (Week 1-2)
- [ ] Build regime classifier
- [ ] Implement strategy switcher
- [ ] Add logging for mode transitions
- [ ] Create monitoring dashboard

### Phase 2: Strategy Implementation (Week 3-4)
- [ ] Code CONSERVADOR (v6 clone)
- [ ] Code AGRESIVO
- [ ] Code DEFENSIVO
- [ ] Code OPPORTUNISTA

### Phase 3: Backtest (Week 5-8)
- [ ] 1990-2026 backtest with regime switching
- [ ] Walk-forward analysis
- [ ] Stress test: 2008, 2020, 2022
- [ ] Sensitivity analysis on thresholds

### Phase 4: Validation (Week 9-10)
- [ ] Paper trading 1 month
- [ ] Compare vs v6 benchmark
- [ ] Document all mode transitions
- [ ] Decision: deploy v7 or stay with v6

---

## 8. SUCCESS CRITERIA

v7 sera considerado exitoso si:

1. **CAGR > 17%** (mejora sobre v6: 16.92%)
2. **Max DD < 40%** (similar a v6: -38.4%)
3. **Sharpe > 0.85** (mejora sobre v6: 0.82)
4. **Time in AGRESIVO > 20%** (el sistema usa la ventaja)
5. **No more than 10 mode switches per year** (evitar whipsaw)

Si cualquiera falla, v6 sigue siendo el sistema de produccion.

---

## 9. FILOSOFIA v7

v7 no reemplaza la simplicidad de v6. **v7 es un experimento controlado** para responder:

> "¿Podemos mejorar v6 sin destruirlo?"

La respuesta puede ser "no". Y eso esta bien. v6 es excelente. Pero debemos preguntar.

*"In Simplicity We Trust... But We Verify"*

---

**Document Version:** 1.0  
**Date:** February 2026  
**Status:** Conceptual Framework  
**Next:** Phase 1 Implementation
