<p align="center">
  <img src="../static/img/omnicapital_logo.png" alt="OmniCapital Logo" width="150">
</p>

# OmniCapital — Guia de Deployment en Vivo
## COMPASS v8.2 — De Paper Trading a Capital Real

> *"El momento de la verdad no es en el backtest, es cuando el dinero real esta en juego."*

---

## FASE 0: PRE-DEPLOYMENT (Semanas 1-2)

### 0.1 Checklist de Preparacion Legal y Fiscal

- [ ] **Estructura legal definida**
  - Cuenta personal vs LLC vs Fondo
  - Consultar con abogado fiscalista
  - **Priorizar IRA/401(k)** — ~209 trades/año = short-term gains (hasta 37%+state)

- [ ] **Cuenta IBKR abierta y aprobada**
  - Interactive Brokers (unico broker soportado)
  - Verificar soporte para MOC orders
  - Paper trading port: 7497
  - Live trading port: 7496 (NO usar hasta completar paper trading)

- [ ] **Documentacion fiscal preparada**
  - Formularios W-9 (US) o W-8BEN (internacional)
  - Plan para reporte de ganancias/perdidas
  - Contador familiarizado con trading activo (~209 trades/año)

- [ ] **Capital asignado**
  - Capital inicial: $100,000 (minimo recomendado)
  - Solo dinero que no necesites en 5+ años
  - Maximo 20% de patrimonio neto
  - Fondo de emergencia intacto

### 0.2 Setup Tecnico

```bash
# 1. Verificar Python
python --version  # Requiere 3.11+

# 2. Instalar dependencias
pip install yfinance pandas numpy

# 3. Verificar archivos del proyecto
python omnicapital_v8_compass.py     # Backtest COMPASS v8.2
python -m pytest tests/test_ibkr_broker.py -v  # 53 tests passing

# 4. Verificar dashboard
python compass_dashboard.py          # Flask dashboard en localhost:5000
```

### 0.3 Configuracion IBKR

```python
# En config o compass/broker.py:
IBKR_CONFIG = {
    'host': '127.0.0.1',
    'port': 7497,           # Paper trading SIEMPRE primero
    'client_id': 1,
    'ibkr_mock': True,      # Empezar en mock mode

    # Safety guards (NO MODIFICAR)
    'moc_deadline': '15:50',     # ET - deadline para MOC orders
    'max_order_size': 50000,     # $50K maximo por orden
    'kill_switch': True,
}
```

### 0.4 Configuracion de Seguridad

```python
# config_live.py - NO SUBIR A GIT
IBKR_ACCOUNT = "TU_ACCOUNT_ID"

# Alertas
EMAIL_ALERTS = "tu@email.com"
SLACK_WEBHOOK = "https://hooks.slack.com/services/..."
```

---

## FASE 1: PAPER TRADING RIGUROSO (3-6 MESES MINIMO)

> **Minimo 3 meses** para capturar un ciclo completo de earnings trimestrales.

### 1.1 Activacion de Paper Trading

```bash
# Paso 1: Iniciar TWS (Trader Workstation)
# - Login con cuenta paper
# - Verificar port 7497 activo
# - API Settings > Enable ActiveX and Socket Clients

# Paso 2: Cambiar de mock a paper
# En config: ibkr_mock: false (TWS debe estar corriendo)

# Paso 3: Iniciar sistema
python omnicapital_live.py
```

### 1.2 Protocolo de Ejecucion COMPASS v8.2

| Hora (ET) | Evento | Accion |
|-----------|--------|--------|
| 15:30 | Signal generation | Sistema calcula rankings con Close[T-1] |
| 15:30-15:50 | Order submission | MOC orders enviados a IBKR |
| 15:50 | MOC deadline | Ultimo momento para enviar MOC |
| 16:00 | Market close | Ordenes ejecutadas al precio de cierre |

### 1.3 Protocolo de Monitoreo Diario

| Hora (ET) | Tarea | Check |
|-----------|-------|-------|
| 09:30 | Verificar sistema activo, conexion IBKR | [ ] |
| 15:25 | Verificar signal generation inminente | [ ] |
| 15:55 | Confirmar MOC orders enviados | [ ] |
| 16:15 | Verificar ejecucion, reconciliar posiciones | [ ] |
| 20:00 | Revisar logs + audit trail del dia | [ ] |

### 1.4 Checklist Semanal

- [ ] Todas las MOC orders se ejecutaron correctamente
- [ ] Stop losses funcionaron segun lo esperado (-8% pos, -15% portfolio)
- [ ] Slippage dentro de rango esperado (~2bps)
- [ ] Position reconciliation sin discrepancias
- [ ] Audit trail completo en `logs/ibkr_audit_*.json`
- [ ] Cash yield acreditado correctamente
- [ ] Numero de posiciones = 5 (risk-on) o 2 (risk-off)

### 1.5 Criterios de Exit Paper Trading

**MINIMO 3 MESES** de paper trading exitoso:

| Criterio | Threshold | Estado |
|----------|-----------|--------|
| MOC orders ejecutados | > 95% sin error | [ ] |
| Slippage promedio | < 5bps (0.05%) | [ ] |
| Position reconciliation | 100% match | [ ] |
| Signal generation | 100% a las 15:30 ET | [ ] |
| Stop loss testeado | 1+ evento exitoso | [ ] |
| Regime switch observado | 1+ transicion risk-on/off | [ ] |
| Uptime del sistema | > 99% | [ ] |
| Ciclo earnings capturado | Minimo 1 trimestre completo | [ ] |

---

## FASE 2: TRANSICION A LIVE (Despues de 3-6 meses paper)

### 2.1 Pre-Launch Checklist

#### Tecnico
- [ ] Paper trading exitoso por 3+ meses
- [ ] Cambiar port de 7497 (paper) a 7496 (live) en config
- [ ] API keys de IBKR live funcionan
- [ ] MOC orders testeados en live (con minima cantidad)
- [ ] Kill switch verificado
- [ ] Backup de conexion (4G/wifi secundario)

#### Financiero
- [ ] Capital transferido a cuenta IBKR live
- [ ] Comisiones IBKR tiered entendidas (~0.15% anual)
- [ ] **NO usar margin** (LEVERAGE_MAX = 1.0)
- [ ] Impuestos estimados reservados (preferir IRA/401(k))

#### Personal
- [ ] Horario 15:25-16:15 ET bloqueado en calendario (critico)
- [ ] Plan de contingencia definido
- [ ] Contacto IBKR guardado
- [ ] Decisiones pre-comprometidas escritas

### 2.2 Estrategia de Escalado

| Semana | Capital | Leverage | Notas |
|--------|---------|----------|-------|
| 1-2 | $10,000 | 1:1 (no leverage) | Test de ejecucion MOC |
| 3-4 | $25,000 | 1:1 (no leverage) | Validar slippage real |
| 5-8 | $50,000 | 1:1 (no leverage) | Escala intermedia |
| 9+ | $100,000 | 1:1 (no leverage) | Operacion normal |

> **IMPORTANTE**: NO usar leverage. LEVERAGE_MAX = 1.0. Broker margin a 6% destruye -1.10% CAGR.

### 2.3 Configuracion Live

```python
# CONFIGURACION LIVE - REVISAR 3 VECES ANTES DE EJECUTAR
IBKR_CONFIG = {
    'host': '127.0.0.1',
    'port': 7496,           # !! LIVE - NO PAPER !!
    'client_id': 1,
    'ibkr_mock': False,     # !! LIVE MODE !!
}

# Parametros COMPASS v8.2 (VERIFICAR QUE SEAN EXACTOS - NO MODIFICAR)
COMPASS_PARAMS = {
    'LOOKBACK': 90,
    'SKIP_DAYS': 5,
    'HOLD_DAYS': 5,
    'NUM_POSITIONS_RISK_ON': 5,
    'NUM_POSITIONS_RISK_OFF': 2,
    'POSITION_STOP': -0.08,
    'TRAILING_STOP_INIT': 0.05,
    'TRAILING_STOP_FINAL': 0.03,
    'PORTFOLIO_STOP': -0.15,
    'VOL_TARGET': 0.15,
    'LEVERAGE_MIN': 0.3,
    'LEVERAGE_MAX': 1.0,         # NO LEVERAGE
    'SEED': 666,
}
```

---

## FASE 3: OPERACION LIVE

### 3.1 Rutina Diaria

#### Pre-Mercado (09:00 ET)
```bash
# 1. Verificar TWS activo y conectado
# 2. Verificar estado del sistema
type state\compass_state_latest.json

# 3. Revisar logs de ayer
type logs\compass_live_*.log
```

#### Signal Window (15:25-16:00 ET) — CRITICO
- 15:25: Verificar sistema preparado para signal
- 15:30: Signal generation automatica (Close[T-1] rankings)
- 15:30-15:50: MOC orders enviados automaticamente
- 16:00: Verificar ejecucion al cierre
- 16:15: Position reconciliation

#### Post-Mercado (16:30 ET)
```bash
# 1. Verificar estado final
python compass_dashboard.py

# 2. Revisar audit trail
type logs\ibkr_audit_*.json

# 3. Verificar reconciliacion de posiciones
```

### 3.2 Protocolos de Emergencia

#### Escenario A: Portfolio Stop Loss Activado (-15%)
```
1. Sistema cierra TODAS las posiciones automaticamente
2. Entra en PROTECTION MODE (reduce a 2 posiciones)
3. Recovery: 63d → Stage2 (1.0x), 126d → Normal (vol targeting)
4. NO agregar capital durante proteccion
5. NO intervenir — protection mode es un FEATURE (26.7% del backtest)
6. Cash gana Moody's Aaa yield (~4.8%) durante proteccion
```

#### Escenario B: Perdida de Conexion IBKR
```
1. ConnectionManager intenta auto-reconnect (state machine)
2. Si falla: enviar alerta critica
3. Manual: verificar TWS directamente
4. Si hay MOC orders pendientes antes de 15:50: reconectar urgente
5. Si posiciones abiertas sin stop: mantener (COMPASS es long-only, sin leverage)
```

#### Escenario C: Error de Ejecucion MOC
```
1. Audit trail registra el error automaticamente
2. Circuit breaker puede activarse
3. Verificar en TWS si orden ejecuto parcialmente
4. Sistema reintenta en siguiente dia si aplicable
5. Revisar logs/ibkr_audit_*.json para diagnostico
```

#### Escenario D: Bug en el Sistema
```
1. Kill switch: detener sistema inmediatamente
2. Posiciones existentes estan SAFE (long-only, no leverage, stops en broker)
3. Revisar logs para identificar problema
4. NO reiniciar hasta fix confirmado y testeado
5. Si duda: volver a mock mode y testear
```

### 3.3 Reglas de Oro (Lectura Diaria)

1. **NO MODIFICAR PARAMETROS** — El motor esta LOCKED (39 experimentos lo prueban)
2. **NO USAR LEVERAGE** — Margin a 6% destruye valor
3. **NO INTERVENIR** en protection mode — es un feature, no un bug
4. **NO INTERRUMPIR** el sistema por "intuicion"
5. **NO OPERAR** tamanos que causen ansiedad
6. **NO COMPARAR** resultados mensuales con SPY

---

## FASE 4: MONITOREO Y MANTENIMIENTO

### 4.1 Metricas de Salud

| Metrica | Frecuencia | Target |
|---------|------------|--------|
| P&L diario | Diaria | Dashboard Flask |
| Drawdown actual | Tiempo real | Alerta si > -15% |
| Slippage MOC | Semanal | < 5bps promedio |
| Position count | Diaria | 5 (risk-on) o 2 (risk-off) |
| Reconciliation match | Diaria | 100% |
| Audit trail completo | Diaria | Sin gaps |
| Cash yield acumulado | Mensual | ~4.8% anualizado |

### 4.2 Revisiones Periodicas

#### Semanal (Domingos)
- [ ] Revisar todos los trades de la semana
- [ ] Verificar stop losses y trailing stops
- [ ] Analizar slippage real vs esperado (~2bps)
- [ ] Backup de logs, state, y audit trail
- [ ] Verificar regime status (risk-on vs risk-off)

#### Mensual
- [ ] Calcular performance vs backtest esperado
- [ ] Revisar metricas de riesgo (Sharpe rolling, DD)
- [ ] Analisis de regimen (tiempo en protection)
- [ ] Ajustar reservas fiscales si es necesario

#### Trimestral
- [ ] Revision profunda de performance
- [ ] Considerar ajuste de capital (solo al alza)
- [ ] Evaluar cross-validation con Norgate Data (si disponible)
- [ ] Reunion con asesor fiscal

### 4.3 Cuando DETENER el Sistema

**Detener inmediatamente si:**
- Drawdown > 30% (significativamente peor que backtest -26.9%)
- 3+ errores de ejecucion MOC en una semana
- Position reconciliation falla repetidamente
- Cambio en situacion personal (necesitas la liquidez)

**Detener y reconsiderar si:**
- Underperformance sostenida vs backtest por 12+ meses
- Cambio estructural en mercado (prohibicion de momentum trading)
- IBKR cambia estructura de comisiones significativamente
- Regulacion nueva que afecte S&P 500 trading

---

## APENDICE: CHECKLIST FINAL PRE-LIVE

### Tecnico
- [ ] 3+ meses de paper trading exitoso
- [ ] 53 unit tests passing
- [ ] IBKR live port 7496 configurado
- [ ] Kill switch testeado
- [ ] MOC deadline (15:50 ET) verificado
- [ ] Auto-reconnect testeado
- [ ] Position reconciliation funcionando
- [ ] Audit trail completo
- [ ] Dashboard Flask operativo

### Financiero
- [ ] Capital disponible en cuenta IBKR
- [ ] **NO margin activado** (LEVERAGE_MAX = 1.0)
- [ ] Comisiones IBKR tiered entendidas
- [ ] Reserva fiscal calculada (preferir IRA/401(k))

### Legal/Fiscal
- [ ] Estructura legal definida
- [ ] ~209 trades/año = short-term capital gains entendido
- [ ] IRA/401(k) evaluado como opcion principal
- [ ] Contador informado

### Personal
- [ ] Horario 15:25-16:15 ET comprometido
- [ ] Plan de contingencia escrito
- [ ] Decisiones pre-comprometidas
- [ ] Entiendo que protection mode es normal (26.7% del tiempo)

### Mental
- [ ] Acepto que puedo perder hasta 30% del capital
- [ ] No necesito este dinero para 5+ años
- [ ] No voy a modificar parametros durante drawdowns
- [ ] Entiendo que 39 experimentos confirman que el motor es optimo
- [ ] Confio en el sistema y no intervendre

---

## FIRMA DE COMPROMISO

Yo, ________________, declaro que:

1. He leido y entendido completamente este documento
2. He testeado el sistema en paper trading por minimo 3 meses
3. COMPASS v8.2 esta LOCKED — no modificare parametros
4. No usare leverage (LEVERAGE_MAX = 1.0)
5. No intervenire en protection mode
6. Seguire los protocolos de emergencia establecidos

Firma: ________________ Fecha: ________________

---

**Version:** 2.0
**Fecha:** 26 Febrero 2026
**Sistema:** OmniCapital COMPASS v8.2 (LOCKED)
**Estado:** IBKR Mock Operativo — Esperando Paper Trading

*"In Simplicity We Trust. The Motor is Locked. In Discipline We Execute."*
