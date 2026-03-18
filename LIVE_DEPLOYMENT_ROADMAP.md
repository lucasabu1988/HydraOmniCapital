# OmniCapital HYDRA — Roadmap de Deployment Live
## De Paper Trading a Operacion Real

> *"Un viaje de mil millas comienza con un solo paso."*
> — Lao Tzu

---

## RESUMEN VISUAL

```
COMPLETADO          EN CURSO              PENDIENTE
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Feb 10-Mar 5    Mar 6-Abr 6       Abr 7      Abr 14-May     Jun+
     │              │               │            │            │
     │              │               │            │            └── Operacion Normal
     │              │               │            │                ($100k, sin leverage)
     │              │               │            │
     │              │               │            └── Escalado Gradual
     │              │               │                ($10k → $25k → $50k → $100k)
     │              │               │
     │              │               └── Transicion a Live
     │              │                   (Primer trade real)
     │              │
     │              └── ██████░░░░ Paper Trading (1 mes)
     │                  HYDRA live desde 6 Mar
     │
     └── ████████████ Pre-Deployment
         COMPLETADO: infra, cloud, ML, tests
```

---

## FASE 1: PRE-DEPLOYMENT [COMPLETADO]

### Logros (Feb 10 — Mar 5, 2026)

- [x] Algoritmo HYDRA v8.4 finalizado (40 experimentos, 36 fallidos → parametros locked)
- [x] 4 estrategias integradas: COMPASS momentum + Rattlesnake mean-reversion + Catalyst cross-asset + EFA internacional
- [x] Cash recycling operativo
- [x] Dashboard Flask operativo (local + cloud)
- [x] Deployment en Render.com (gunicorn, auto-sync)
- [x] IBKR broker mock completo (53 unit tests passing)
- [x] Sistema ML de learning (decision logging + progressive learning)
- [x] Alertas y monitoreo configurados
- [x] GitHub Actions CI/CD operativo
- [x] Documentacion completa (Manifesto, Deployment Guide, Implementation Guide)

---

## FASE 2: PAPER TRADING [EN CURSO — Semana 2 de 4]

### Estado Actual (17 Marzo 2026)

| Metrica | Valor |
|---------|-------|
| **Inicio paper trading** | 6 Marzo 2026 |
| **Dias operando** | 11 |
| **Portfolio** | $100,068.76 (+0.07%) |
| **Cash disponible** | $43,220.44 |
| **Posiciones activas** | 6 |
| **Estrategias activas** | COMPASS (JNJ, GEV) + Catalyst (TLT, GLD, DBC) + EFA |
| **Errores criticos** | 0 (post-fixes de aislamiento multi-estrategia) |
| **Cloud dashboard** | Operativo en Render.com |

### Posiciones Actuales

| Ticker | Estrategia | Rol |
|--------|-----------|-----|
| JNJ | COMPASS | Momentum pick |
| GEV | COMPASS | Momentum pick |
| TLT | Catalyst | Bonds (cross-asset trend) |
| GLD | Catalyst | Gold (cross-asset trend) |
| DBC | Catalyst | Commodities (cross-asset trend) |
| EFA | EFA | International diversification |

### Objetivo: 1 Mes de Paper Trading Exitoso (6 Mar → 6 Abr)

#### Checklist Semanal

**Semana 1 (6-12 Mar): [COMPLETADO]**
- [x] Sistema encendido y operando
- [x] Primeras posiciones COMPASS tomadas
- [x] Cloud dashboard desplegado
- [x] Estado sincronizando automaticamente
- [x] Multi-estrategia (COMPASS + Catalyst + EFA) activado

**Semana 2 (13-19 Mar): [EN CURSO]**
- [x] Multi-strategy isolation fix (evitar que COMPASS venda posiciones de Catalyst/EFA)
- [x] Peak value corregido a $100K (estaba stale en $120K)
- [x] SPY benchmark anclado a cierre Mar 16
- [ ] 10+ dias de operacion continua sin errores
- [ ] Verificar que adaptive stops funcionan correctamente
- [ ] Revisar cycle log (rotaciones de 5 dias)

**Semana 3 (20-26 Mar):**
- [ ] 15+ dias de operacion continua
- [ ] Sistema estable sin intervencion manual
- [ ] Rattlesnake mean-reversion: verificar que entra/sale correctamente
- [ ] Costos de operacion estimados (comisiones + slippage)
- [ ] Validar ML learning: decisiones loggeadas correctamente

**Semana 4 (27 Mar - 6 Abr):**
- [ ] 20+ dias de operacion continua
- [ ] Todos los checks de deployment pasados
- [ ] Stop loss testeado en al menos 1 posicion
- [ ] Documento de go/no-go para live trading
- [ ] Plan fiscal definido
- [ ] Decision: continuar a live o extender paper

---

## FASE 3: TRANSICION A LIVE [PENDIENTE — Abr 7, 2026]

### Prerrequisitos (deben estar completos antes)

- [ ] Paper trading exitoso por 1 mes completo
- [ ] Documento go/no-go aprobado
- [ ] Cuenta IBKR live abierta y fondeada
- [ ] API keys de produccion generadas
- [ ] Plan fiscal definido

### Dia D-3: Preparacion Final

- [ ] Transferir capital inicial ($10K) a cuenta broker
- [ ] Verificar que API keys de produccion funcionan
- [ ] Revisar comisiones reales de IBKR
- [ ] Configurar alertas de alto nivel (email/SMS)
- [ ] Notificar a personas clave

### Dia D-2: Test Final

- [ ] Ejecutar orden de prueba con $100
- [ ] Verificar ejecucion en plataforma broker
- [ ] Confirmar que logs funcionan con broker real
- [ ] Testear stop loss con cantidad minima

### Dia D-1: Descanso

- [ ] No hacer nada relacionado con trading
- [ ] Dormir bien
- [ ] Recordar: "Es solo dinero, no mi identidad"

### Dia D: PRIMER TRADE EN VIVO

```
HORARIO TIPO (ET)
=================
08:30 - Pre-market check
        - Sistema encendido (IBKRBroker live mode)
        - Conexion OK
        - Cash disponible confirmado

09:30 - Mercado abre
        - HYDRA engine entra en loop
        - 4 estrategias operando simultaneamente
        - Respirar. No intervenir.

12:00 - Check medio dia
        - Dashboard cloud: verificar posiciones
        - Revisar P&L por estrategia

16:00 - Cierre
        - Sistema procesa rotaciones
        - State sync automatico
        - Backup de estado

20:00 - Post-market
        - Revisar cycle log
        - Analizar trades por estrategia
        - Verificar ML learning log
```

---

## FASE 4: ESCALADO GRADUAL [PENDIENTE — Abr 14 - May, 2026]

### Estrategia de Escalado

| Semana | Capital | Leverage | Objetivo |
|--------|---------|----------|----------|
| 1 (Abr 14) | $10,000 | 1:1 (sin leverage) | Validar ejecucion real con IBKR |
| 2 (Abr 21) | $25,000 | 1:1 | Escalar si semana 1 sin errores |
| 3 (Abr 28) | $50,000 | 1:1 | Probar 4 estrategias a escala media |
| 4 (May 5) | $100,000 | 1:1 | Capital objetivo completo |

> **IMPORTANTE**: LEVERAGE_MAX = 1.0 — broker margin al 6% destruye valor.
> Nunca habilitar leverage. Este es un parametro LOCKED.

### Criterios de Escalado

**Subir al siguiente nivel solo si:**
- Semana anterior sin errores criticos
- Slippage dentro de parametros (< 0.2%)
- Sistema estable (99%+ uptime en Render)
- Comfort emocional con nivel actual
- Todas las estrategias ejecutando correctamente

**Si algo falla:**
- Detener escalado
- Volver a nivel anterior
- Extender 1 semana adicional
- Diagnosticar y corregir antes de avanzar

---

## FASE 5: OPERACION NORMAL [PENDIENTE — Jun 2026+]

### Estado Estacionario

- Capital: $100,000 (o tu maximo planeado)
- Leverage: 1:1 (nunca mas — LOCKED)
- Estrategias: COMPASS + Rattlesnake + Catalyst + EFA + cash recycling
- Cloud: Render.com dashboard con auto-sync
- ML: Progressive learning activo
- Monitoreo: Diario pero pasivo
- Intervencion: Solo en emergencias

### Rutina Semanal

**Lunes:**
- Revisar fin de semana (si hubo noticias)
- Confirmar sistema listo
- Semana de trading comienza

**Viernes:**
- Generar reporte semanal
- Analizar performance
- Backup de datos
- Planificar proxima semana

**Domingo:**
- Revisar trades de la semana
- Leer documentacion (recordar por que no intervenir)
- Preparar mentalmente para semana
- NO cambiar parametros

### Metricas de Salud Mensual

| Metrica | Target | Accion si fuera de rango |
|---------|--------|--------------------------|
| CAGR (rolling 12m) | > 10% | Revisar, NO cambiar algoritmo |
| Max DD | < -40% | Esperar recuperacion (crash brake activa) |
| Sharpe | > 0.6 | Revisar costos de ejecucion |
| Uptime (Render) | > 99% | Revisar gunicorn workers |
| Trades exitosos | > 95% | Revisar conexion IBKR |
| ML decisions logged | 100% | Verificar compass_ml_learning.py |

---

## ML LEARNING SYSTEM — Roadmap de Aprendizaje Progresivo

El sistema ML (`compass_ml_learning.py`) opera como observador pasivo: registra cada decision del algoritmo y progresivamente construye modelos estadisticos y de ML a medida que se acumulan datos.

### Estado Actual del ML (17 Mar 2026)

| Componente | Estado |
|-----------|--------|
| **DecisionLogger** | Activo — loggeando entries, exits, holds, skips |
| **Archivos JSONL** | `decisions.jsonl`, `outcomes.jsonl`, `daily_snapshots.jsonl` |
| **Open entries tracking** | `open_entries.json` mantiene link entry→exit |
| **Fase actual** | Fase 1 (estadisticas descriptivas) |
| **Dias de trading** | ~11 |
| **CLI** | `python compass_ml_learning.py status/report/backfill` |

### Fases del ML Learning

```
FASE 1 (Ahora)         FASE 2               FASE 3
Dias 0-62               Dias 63-251          Dias 252+
Mar 2026 - Jun 2026     Jun 2026 - Mar 2027  Mar 2027+
━━━━━━█░░░░░░░░░░░░     ░░░░░░░░░░░░░░░░░    ░░░░░░░░░░░░░
Estadisticas            Ridge + LogReg       LightGBM/RF
descriptivas            (regularizado)       (full ML)
```

### Fase 1: Estadisticas Descriptivas [EN CURSO — ~11 de 62 dias]

**Que hace:**
- Mean/median return con bootstrap 95% CI (2000 resamples, seed 666)
- Win rate, stop rate, avg days held
- Breakdowns por: regime bucket, sector, exit reason, vol bucket
- Stop analysis: stop rate por vol bucket, avg return when stopped

**Checklist Fase 1:**
- [x] DecisionLogger integrado en omnicapital_live.py
- [x] JSONL files creados y recibiendo datos
- [x] Fail-safe wrappers (try/except en todos los hooks)
- [x] Backfill desde state files historicos
- [ ] Acumular 20+ trades completados (minimo para stats por grupo)
- [ ] Acumular 62 dias de trading (~3 meses) para pasar a Fase 2
- [ ] Primer insights.json generado con stats significativas

**Fecha estimada de completar Fase 1:** ~Jun 2026

### Fase 2: ML Ligero [PENDIENTE — ~Jun 2026]

**Prerequisitos:**
- 63+ dias de trading
- 20+ trades completados
- scikit-learn instalado

**Que hace:**
- Ridge Regression (alpha=10.0) para prediccion de retorno
- Logistic Regression (C=0.1) para clasificacion win/loss
- TimeSeriesSplit cross-validation (sin data leakage temporal)
- Top 10 features por magnitud de coeficiente
- StopParameterOptimizer: sugerencias de ajuste de stops (solo si >90% bootstrap confidence)

**Features utilizados:**

| Categoria | Features |
|-----------|----------|
| Momentum signal | score, rank, score² |
| Volatility regime | daily vol, annual vol, vol buckets, adaptive stop |
| Market regime | regime score, SPY vs SMA200, regime buckets, SPY 10d vol |
| Portfolio state | drawdown, dd_severe flag, leverage |
| Sector | One-hot encoding (8 sectores) |

**Targets:** return (regression), label 5-class (classification), beat_spy (binary)

**Checklist Fase 2:**
- [ ] 63 dias de trading acumulados
- [ ] 20+ trades completados con outcomes
- [ ] Primer modelo Ridge entrenado
- [ ] R² y AUC CV scores publicados en insights.json
- [ ] Feature importance ranking disponible
- [ ] Stop parameter suggestions generadas (si hay suficiente confianza)

**Fecha estimada:** Jun-Jul 2026

### Fase 3: ML Completo [PENDIENTE — ~Mar 2027]

**Prerequisitos:**
- 252+ dias de trading (~12 meses)
- 100+ trades completados

**Que hace:**
- LightGBM (200 estimators, lr=0.05, depth=3, 8 leaves, subsample=0.8, seed 666)
- RandomForest como fallback (200 estimators, depth=4, min_samples_leaf=5)
- 5-fold TimeSeriesSplit cross-validation
- Feature importance ranking para monitorear signal decay
- Retraining mensual

**Checklist Fase 3:**
- [ ] 252 dias de trading acumulados
- [ ] 100+ trades completados
- [ ] LightGBM o RF entrenado exitosamente
- [ ] Feature importance estable (sin signal decay)
- [ ] Retrain mensual automatizado
- [ ] Parameter suggestions con alta confianza estadistica

**Fecha estimada:** Mar 2027+

### Principios Inmutables del ML

1. **Zero look-ahead bias** — features solo de datos disponibles al momento de la decision
2. **Hipotesis, no hechos** — outputs del ML son sugerencias, nunca directivas
3. **Fail-safe** — el ML nunca puede crashear el engine de trading
4. **Regime-conditional** — todo analisis segmentado por regimen y volatilidad
5. **No auto-apply** — las sugerencias de parametros requieren aprobacion manual

---

## PROTOCOLOS DE EMERGENCIA

### Si el Sistema Falla

```
1. NO PANICO
2. Detener sistema automatico
3. Evaluar situacion:
   
   a) Si hay posiciones abiertas:
      - Mantener si mercado estable
      - Cerrar manualmente si necesario
   
   b) Si no hay posiciones:
      - Diagnosticar problema
      - Corregir
      - Reiniciar cuando seguro

4. Documentar incidente
5. Aprender y mejorar
6. Volver a operacion
```

### Si el Mercado Colapsa

```
1. HYDRA ACTIVARA adaptive stops automaticamente (-6% a -15% vol-scaled)
2. Crash brake: 5d=-6% o 10d=-10% → 15% leverage
3. DD tiers activan: T1=-10%, T2=-20%, T3=-35%
4. NO agregar capital
5. NO intervenir — el sistema maneja drawdowns
6. Esperar recuperacion a 95% del peak
7. El sistema restaurara posiciones automaticamente
```

### Si Yo Quiero Intervenir

```
1. DETENERSE
2. Leer: "Por que no intervenir"
3. Preguntar: "¿Tengo informacion que el sistema no tiene?"
4. Si la respuesta es NO → NO intervenir
5. Si la respuesta es SI → Documentar y reconsiderar
6. 99% de las veces, NO intervenir
```

---

## RECURSOS Y CONTACTOS

### Documentacion
- `docs/MANIFESTO.md` - Manifiesto COMPASS/HYDRA
- `docs/DEPLOYMENT_GUIDE.md` - Guia de deployment
- `docs/IMPLEMENTATION_GUIDE.md` - Guia de implementacion
- `docs/PROJECT_STATE.md` - Estado del proyecto
- `docs/ML_ARCHITECTURE.md` - Arquitectura ML learning
- `docs/HYDRA_4th_PILLAR_REPORT.md` - Report EFA (4to pilar)

### Scripts Clave
- `compass_dashboard.py` - Dashboard Flask + engine (entry point)
- `omnicapital_live.py` - COMPASSLive class (broker, signals, execution)
- `compass_ml_learning.py` - ML orchestrator
- `tests/validate_live_system.py` - Validacion de sistema

### Infraestructura
- **Broker**: Interactive Brokers (mock ahora, live en Fase 3)
- **Data**: Yahoo Finance (con cache en `data_cache/`)
- **Cloud**: Render.com (gunicorn, auto-deploy desde GitHub)
- **CI/CD**: GitHub Actions
- **Repo**: github.com/lucasabu1988/NuevoProyecto

---

## FIRMA DE COMPROMISO

Yo, Lucas, me comprometo a:

1. Seguir este roadmap paso a paso
2. NO saltear etapas (completar 1 mes de paper trading)
3. NO intervenir en el sistema una vez en live
4. NO activar leverage (LEVERAGE_MAX = 1.0 LOCKED)
5. Mantener disciplina durante drawdowns
6. Documentar y aprender de errores

**Fecha de inicio paper:** 6 Marzo 2026
**Fecha objetivo live:** 7 Abril 2026
**Capital a asignar:** $100,000 (escalado gradual desde $10K)

---

**Version:** 2.0
**Fecha:** 17 Marzo 2026
**Sistema:** OmniCapital HYDRA v8.4 (COMPASS + Rattlesnake + Catalyst + EFA)
**Estado:** Paper trading activo — Semana 2 de 4

*"El mejor momento para empezar fue hace 20 anos. El segundo mejor momento es ahora."*
