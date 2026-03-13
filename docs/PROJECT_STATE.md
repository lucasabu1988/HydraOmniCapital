# OmniCapital - Estado del Proyecto
## Checkpoint: 26 Febrero 2026

---

## RESUMEN EJECUTIVO

| Aspecto | Estado |
|---------|--------|
| **Algoritmo** | COMPASS v8.2 (LOCKED — 39 experimentos, 35 fallidos) |
| **Signal CAGR** | 18.61% \| 1.03 Sharpe \| -30.6% MaxDD \| $100K→$8.6M |
| **Net CAGR** | 17.42% \| 0.98 Sharpe \| -31.2% MaxDD \| $100K→$6.6M |
| **Costo de ejecucion** | 1.0% fijo anual (MOC slippage + comisiones + buffer) |
| **Broker** | IBKR mock mode operativo (53 unit tests passing) |
| **Dashboard** | Flask live dashboard operativo |
| **Proximo Paso** | Norgate Data + IBKR Paper Trading (3-6 meses) |

---

## ARCHIVOS CLAVE

### Algoritmo (LOCKED — NO MODIFICAR)

| Archivo | Descripcion | Estado |
|---------|-------------|--------|
| `omnicapital_v8_compass.py` | COMPASS v8.2 produccion | LOCKED |
| `compass_net_backtest.py` | Net backtest (prod engine + pre-close + 2bps) | Completo |

### Infraestructura Live

| Archivo | Descripcion | Estado |
|---------|-------------|--------|
| `omnicapital_live.py` | Sistema live (COMPASSLive) | Listo |
| `compass/broker.py` | IBKRBroker (mock + live) | Listo |
| `compass/data_feed.py` | Modulo de datos | Listo |
| `compass/live.py` | COMPASSLive integrado | Listo |
| `compass_dashboard.py` + `templates/dashboard.html` | Dashboard Flask | Operativo |

### Tests y Validacion

| Archivo | Descripcion | Estado |
|---------|-------------|--------|
| `tests/test_ibkr_broker.py` | 53 unit tests IBKRBroker mock | 53/53 passing |
| `tests/test_live_system.py` | Tests sistema live | Passing |
| `tests/validate_live_system.py` | Validacion componentes | Passing |

### Documentacion

| Archivo | Descripcion | Estado |
|---------|-------------|--------|
| `docs/MANIFESTO.md` / `.docx` | Manifiesto COMPASS v8 | Completo |
| `OMNICAPITAL_PROJECT_REVIEW.py` / `.txt` | Review completa (25 preguntas) | Completo |
| `docs/DEPLOYMENT_GUIDE.md` | Guia de deployment | Actualizado |
| `docs/IMPLEMENTATION_GUIDE.md` | Guia de implementacion | Completo |

---

## PARAMETROS COMPASS v8.2 (NO MODIFICAR — ALGORITHM LOCKED)

```python
# Momentum
LOOKBACK = 90           # 90 dias
SKIP_DAYS = 5           # 5 dias skip
HOLD_DAYS = 5           # 5 dias hold

# Posiciones
NUM_POSITIONS_RISK_ON = 5   # 5 posiciones en risk-on
NUM_POSITIONS_RISK_OFF = 2  # 2 posiciones en risk-off

# Stops
POSITION_STOP = -0.08       # -8% por posicion
TRAILING_STOP_INIT = 0.05   # +5% trailing inicial
TRAILING_STOP_FINAL = 0.03  # +3% trailing final
PORTFOLIO_STOP = -0.15       # -15% portfolio

# Leverage (NO LEVERAGE EN PRODUCCION)
VOL_TARGET = 0.15           # 15% vol targeting
LEVERAGE_MIN = 0.3          # Minimo 0.3x
LEVERAGE_MAX = 1.0          # Maximo 1.0x (NO leverage)

# Regimen
REGIME_FILTER = 'SPY SMA(200)'  # 3-day confirmation
SEED = 666                       # Seed oficial del proyecto

# Cash yield
CASH_YIELD = "Moody's Aaa IG Corporate (FRED variable, avg ~4.8%)"
```

---

## IBKR BROKER INTEGRATION

| Componente | Estado |
|------------|--------|
| IBKRBroker clase | Completo (mock + live mode) |
| ConnectionManager | State machine con auto-reconnect |
| Mock mode | Comisiones IBKR tiered, MOC orders, ~0.5bps slippage |
| Safety guards | Paper port 7497, MOC deadline 15:50 ET, kill switch, $50K order limit |
| Position reconciliation | JSON state vs broker positions on startup |
| Audit trail | `logs/ibkr_audit_YYYYMMDD.json` |
| Unit tests | 53/53 passing |
| **Transicion a live** | Set `ibkr_mock: false` + iniciar TWS en port 7497 |

---

## LAUNCH ROADMAP

### Fase 1: Data Quality (PRIORIDAD MAXIMA)
- [ ] **Norgate Data** — S&P 500 point-in-time membership
  - Cura survivorship bias
  - Cross-valida datos yfinance
  - Dos problemas resueltos con una solucion

### Fase 2: Paper Trading (3-6 MESES MINIMO)
- [ ] Iniciar TWS, set `ibkr_mock: false`
- [ ] Correr minimo 3-6 meses (capturar ciclo completo de earnings)
- [ ] Verificar ejecucion MOC, slippage real, reconciliacion
- [ ] Monitorear via dashboard Flask

### Fase 3: Ejecucion Avanzada
- [ ] Passive limits dentro de ventana MOC (mejor que MOC directo)
- [ ] TWAP como alternativa
- [ ] MOC imbalance data (noisy/complejo, baja prioridad)

### Fase 4: Optimizacion Fiscal
- [ ] Operar en IRA/401(k) — ~209 trades/año = short-term capital gains
- [ ] En cuenta taxable: ~10-11% after-tax (vs 17.42% pre-tax)

### Fase 5: Escalado ($500K+)
- [ ] RATTLESNAKE dual-engine
- [ ] IBKR portfolio margin para Box Spread access
- [ ] Box Spread financing (SOFR+20bps) = unica via viable de leverage

---

## HISTORIAL DE EXPERIMENTOS (39 total, 35 fallidos)

| # | Experimento | Resultado | CAGR |
|---|------------|-----------|------|
| - | v6 original | FAILED (survivorship bias) | 16.92% (biased) |
| - | v6 corrected | annual top-40 rotation | 5.40% |
| - | v7 | Cancelado | - |
| - | **v8 COMPASS** | **SUCCESS** | **18.61%** |
| - | v8.1 short-selling | FAILED | - |
| - | v8.3 rank-hysteresis | FAILED | -4.56% delta |
| - | v8.3 cash yield → Exp#34 | APPROVED | +1.15% |
| - | VORTEX v1/v2/v3 | FAILED | - |
| - | Optimization suite (5) | Baseline won | - |
| - | Behavioral overlays | FAILED | -7% to -10% |
| - | Dynamic recovery | FAILED | worse DD |
| - | Protection shorts (ETF) | FAILED | -$145-235K |
| - | Protection shorts (mom) | FAILED | -0.16% |
| - | ChatGPT ensemble | FAILED | -7.43% |
| - | ChatGPT hold ext | FAILED | -3.93% |
| - | ChatGPT preemptive stop | FAILED | -6.56% |
| - | VIPER v1 (ETF rotation) | FAILED | 5.84% |
| - | VIPER v2 (Sector ETF) | FAILED | 3.59% |
| - | RATTLESNAKE v1 | SUCCESS (standalone) | 10.51% |
| - | COMPASS+RATTLESNAKE | REVERTED | - |
| - | ECLIPSE v1 (pairs) | FAILED | -3.37% |
| - | QUANTUM v1 (RSI+IBS) | PARTIAL | 9.42% |
| - | COMPASS Internacional | FAILED | -20.87% |
| - | COMPASS Asia | FAILED | -19.71% |
| 33 | Profit Target | FAILED | 13.23% (-54.9% DD) |
| 34 | IG Cash Yield | APPROVED | +1.15% |
| 35 | MWF Trading | FAILED (3 variants) | ~13% (-49-53% DD) |
| 36 | Gold Protection | FAILED | noise vs cash |
| 37 | v9 Genius Layer (5 ML) | FAILED | 10.53% (-55.9% DD) |
| 38 | Cash Deploy | FAILED | 15.20% (-31.3% DD) |
| 39 | Conviction+Crowding | FAILED (3 variants) | 17.21-17.95% |

**Conclusion**: Motor LOCKED. Algoritmo ha alcanzado maximo teorico. Enfocarse en chassis.

---

## DECISIONES CLAVE

| Fecha | Decision | Razon |
|-------|----------|-------|
| Feb 2026 | v8.2 LOCKED | 39 experimentos, inelastico |
| Feb 2026 | No leverage | Broker 6% margin destruye -1.10% CAGR |
| Feb 2026 | Pre-close execution | Signal T-1 + MOC same-day = +0.79% CAGR |
| Feb 2026 | Cash yield Aaa IG | +1.15% CAGR vs T-bill fijo |
| Feb 2026 | IBKR mock mode | Scaffolding listo, switch a live cuando ready |
| Feb 2026 | Seed 666 | Seed oficial del proyecto |
| Feb 2026 | Geographic expansion rejected | EU -20.87%, Asia -19.71% |
| Feb 2026 | ML rejected | v9 Genius lost -8.03% CAGR |
| Feb 2026 | 25 review questions answered | No open questions |

---

## COMANDOS RAPIDOS

```bash
# Backtest COMPASS v8.2
python omnicapital_v8_compass.py

# Dashboard live
python compass_dashboard.py

# Paper trading (mock)
python omnicapital_live.py

# Tests IBKR broker
python -m pytest tests/test_ibkr_broker.py -v

# Ver estado actual
type state\compass_state_latest.json

# Ver logs
type logs\compass_live_*.log
```

---

**Ultima actualizacion**: 26 Febrero 2026
**Proxima revision**: Al iniciar IBKR Paper Trading
**Estado**: IBKR Mock Operativo — Esperando Norgate Data + Paper Trading

*"In Simplicity We Trust. The Motor is Locked. Focus on the Chassis."*
