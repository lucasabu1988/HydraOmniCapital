<p align="center">
  <img src="docs/img/omnicapital_logo.png" alt="OmniCapital Logo" width="200">
</p>

<h1 align="center">OmniCapital HYDRA</h1>
<h3 align="center">Local Screener + Meta-Layer para trading cuantitativo</h3>

<p align="center">
  <strong>Lightweight • 100% Local en Windows • Sin dependencias en la nube</strong>
</p>

<p align="center">
  <a href="#-screener-local">📥 Screener Local</a> • 
  <a href="#-meta-layer">🧠 Meta-Layer</a> • 
  <a href="https://github.com/lucasabu1988/HydraOmniCapital/tree/feature/hydra-local-screener">Feature Branch</a>
</p>

---

## 🎯 Enfoque Actual

**HYDRA Screener Local** — Herramienta ligera y 100% local para Windows.

El proyecto ha evolucionado hacia un **screener local ligero** que genera candidatos de compra diarios usando la lógica completa de HYDRA + Meta-Layer, sin depender de servidores en la nube.

### Características principales del Screener Local

- Corre completamente en Windows (sin Render, Flask ni gunicorn)
- Usa el S&P 500 completo (o lista reducida)
- Integra Meta-Layer con Special Modes y Pillar Multipliers
- Número de recomendaciones dinámico según el régimen
- Guarda histórico automático para análisis de rendimiento
- Muy rápido de ejecutar manualmente (antes, durante y después de la apertura)

Ver instrucciones completas más abajo en la sección **Screener Local**.

---

## 🐍 Las 4 estrategias de HYDRA

HYDRA combina cuatro estrategias complementarias con un sistema de reciclaje de capital:

| Estrategia | Asignación | Lógica |
|---|---|---|
| **COMPASS v8.4** | 42.5% | Momentum cross-sectional risk-adjusted (90d return / 63d vol) sobre 40 large-caps US. Ciclos de 5 días, vol-targeting capped 1.0x, regimen SPY SMA200 |
| **Rattlesnake v1.0** | 42.5% | Mean-reversion dip-buying (RSI<25) sobre S&P 100 con filtro de uptrend |
| **Catalyst** | 15% (ring-fenced) | Trend cross-asset sobre TLT/ZROZ/GLD/DBC. Cada activo entra solo si cotiza por encima de su SMA200. GLD participa exclusivamente vía este filtro de tendencia (sin asignación permanente). |
| **EFA** | overflow | Diversificación internacional pasiva con cash residual del recycling |

**Cash recycling**: el cash idle de Rattlesnake fluye a COMPASS hasta un cap del 75%. El cash residual (post-recycling, no Catalyst) se asigna a EFA. Catalyst está aislado y nunca participa del recycling.

**Algorithm LOCKED**: 64 experimentos corridos. El motor está congelado; cualquier cambio paramétrico degrada performance.

---

## 📥 Screener Local (Recomendado)

Versión ligera y moderna que corre 100% local en Windows.

```bash
cd hydra_screener_local
pip install -r requirements.txt
python screener.py
```

**Características:**
- Soporta S&P 500 completo
- Filtros de liquidez y precio configurables
- Meta-Layer con los 4 Special Modes
- Pillar Multipliers que afectan el ranking
- Número de recomendaciones dinámico
- Guarda histórico automáticamente en `history/`

Para analizar el histórico:
```bash
python analyze_history.py
```

Todo el código está en la carpeta `hydra_screener_local/`.

---

## 🧠 Meta-Layer v1 (Presupuesto de Riesgo + Adaptación) / Meta-Layer v1 (Risk Budgeting + Adaptation)

**Nuevo sistema de control de riesgo a nivel de portfolio** que se activa de forma segura mediante variable de entorno.

**Feature flag**: `ENABLE_META_LAYER=0` (por defecto) | `1` (activo) | `shadow` (observabilidad sin impacto en capital)

- **Modo Shadow (recomendado para rollout inicial)**: Calcula decisiones reales cada ciclo y las registra con detalle (multiplicadores por pilar, reciclaje, modos especiales, boost de recuperación), pero **nunca modifica** la asignación de capital. Comportamiento idéntico al baseline.
- **Modo Live**: Aplica multiplicadores conservadores por estrategia (COMPASS / Rattlesnake / Catalyst / EFA) y modula el reciclaje de efectivo según el régimen de mercado.
- **Task 3.2 - Recovery Adaptation Controller**: Boost limitado y muy conservador (rango duro `[0.98, 1.12]`) que solo actúa en fases de recuperación post-crisis. Incluye inercia, decaimiento automático y tags de auditoría (ADAPT / DECAY / MANUAL_OVERRIDE).

**Validación**:
- Prueba A/B exitosa en el año COVID 2020 (2020-01-01 → 2020-12-31).
- Meta ON mostró +2.21 pp de CAGR y mejora en Calmar (2.426 vs 2.393) y Sharpe (1.533 vs 1.512) respecto al baseline sin Meta-Layer.
- Toda la lógica es **fail-safe**: cualquier error devuelve multiplicadores neutros (sin impacto).

**Archivos clave**:
- `omnicapital_live.py` — orquestación y flag
- `hydra_capital.py` — aplicación de decisiones en asignación
- `hydra_meta/meta_layer.py` — `RiskBudgetMetaLayer` + `_RecoveryAdaptationController`
- `regime_os.py` — `BasicRegimeOS`

Actualmente en despliegue en **shadow mode** en [omnicapital.onrender.com](https://omnicapital.onrender.com) para observación en mercado real antes de activación controlada.

---

## 🧠 Meta-Layer v1 (Risk Budgeting + Adaptation)

**New portfolio-level risk control system** that can be safely activated via environment variable.

**Feature flag**: `ENABLE_META_LAYER=0` (default) | `1` (live) | `shadow` (observability with zero risk)

- **Shadow Mode (recommended for initial rollout)**: Computes real decisions every cycle and logs them in rich detail (pillar multipliers, recycling, special modes, recovery boost), but **never changes** capital allocation. Behavior is identical to baseline.
- **Live Mode**: Applies conservative per-strategy multipliers (COMPASS / Rattlesnake / Catalyst / EFA) and modulates cash recycling according to market regime.
- **Task 3.2 - Recovery Adaptation Controller**: Very conservative limited boost (hard bounds `[0.98, 1.12]`) that only activates during post-crisis recovery phases. Includes inertia, automatic decay, and full audit tags (ADAPT / DECAY / MANUAL_OVERRIDE).

**Validation**:
- Successful A/B test during the 2020 COVID year.
- Meta ON delivered +2.21 pp higher CAGR and better risk-adjusted metrics (Calmar 2.426 vs 2.393, Sharpe 1.533 vs 1.512).
- All paths are **fail-safe**: any error returns neutral multipliers (no capital impact).

**Key files**:
- `omnicapital_live.py`
- `hydra_capital.py`
- `hydra_meta/meta_layer.py`
- `regime_os.py`

Currently being rolled out in **shadow mode** on [omnicapital.onrender.com](https://omnicapital.onrender.com) for real-market observation before controlled activation.

---

## 🏗️ Arquitectura

```
┌──────────────────────┐         ┌──────────────────────────┐
│   Local Machine      │         │   Render Cloud           │
│ ┌──────────────────┐ │         │ ┌──────────────────────┐ │
│ │compass_dashboard │ │         │ │compass_dashboard_    │ │
│ │   .py + engine   │ │         │ │   cloud.py           │ │
│ └──────────────────┘ │         │ │ gunicorn --workers 1 │ │
│ ┌──────────────────┐ │         │ │ PaperBroker +        │ │
│ │compass_watchdog  │ │         │ │ YahooDataFeed        │ │
│ └──────────────────┘ │         │ └──────────────────────┘ │
└──────────────────────┘         └──────────────────────────┘
            │                                ▲
            │                                │
            └────── git push → GitHub ───────┘
                                  (auto-deploy webhook)
```

### Componentes clave

| Archivo | Rol |
|---|---|
| `omnicapital_live.py` | Core engine (`COMPASSLive`) — orquesta las 4 estrategias |
| `omnicapital_v84_compass.py` | Algoritmo COMPASS v8.4 (LOCKED) |
| `rattlesnake_signals.py` | Señales Rattlesnake (RSI dip-buying) |
| `catalyst_signals.py` | Señales Catalyst (trend cross-asset + gold) |
| `hydra_capital.py` | `HydraCapitalManager` — cash recycling |
| `omnicapital_broker.py` | `PaperBroker` + `IBKRBroker` (mock + live) |

### Stack técnico

- **Lenguaje**: Python 3.11 (cloud) / 3.14 (local Windows)
- **Web**: Flask + gunicorn (cloud) — health check `/api/health`
- **Datos**: yfinance (primary), FRED (cash yield Moody's Aaa IG), Tiingo (opcional)
- **Broker**: IBKR API (mock + live paper trading on port 7497)
- **Deploy**: GitHub → Render auto-deploy via webhook

---

## 📊 Sistema ML de aprendizaje (3 fases)

El engine loguea cada decisión y construye gradualmente un sistema de inteligencia:

| Fase | Decisiones | Componentes |
|---|---|---|
| **Phase 1** | < 100 | `DecisionLogger` — loguea entries, exits, skips, signals |
| **Phase 2** | 100–500 | `FeatureStore` + `OutcomeTracker` — feature vectors + resolución de P&L |
| **Phase 3** | > 500 | `LearningEngine` + `InsightReporter` — entrena modelos, sugiere parámetros |

Toda la capa ML está envuelta en `try/except` — **nunca puede crashear el live engine**.

---

## 🚀 Instalación local

```bash
git clone https://github.com/lucasabu1988/HydraOmniCapital.git
cd HydraOmniCapital
pip install -r requirements.txt
```

Para deploy cloud-style:
```bash
```

---

## 🧪 Tests

```bash
pytest tests/ -v                           # Suite completa
pytest tests/ -v --cov-fail-under=50       # Con coverage threshold (CI default)
python tests/validate_live_system.py       # Validación end-to-end
```

CI corre en GitHub Actions con dos jobs: `test` (motor legacy congelado, `pytest tests/`, cobertura informativa) y `screener` (`hydra_screener_local/run_all_tests.py`). El despliegue en Render se retiro el 2026-09-06; el dashboard, si se usa, corre en local.

53 tests unitarios para `IBKRBroker` mock mode, todos passing.

---

## 📈 Parámetros del algoritmo (v8.4)

| Categoría | Valor |
|---|---|
| Momentum lookback | 90 días |
| Skip period | 5 días |
| Hold period | 5 días (ciclos) |
| Posiciones (risk-on) | 5 (ajustable por regimen) |
| Stops adaptativos | -6% a -15% (vol-scaled) |
| Trailing | +5% / -3% (vol-scaled) |
| Bull override | SPY > SMA200·103% & score>40% → +1 posición |
| Sector limit | máx 3 por sector |
| Crash brake | 5d=-6% o 10d=-10% → 15% leverage |
| Drawdown tiers | T1=-10%, T2=-20%, T3=-35% |
| Leverage máx | **1.0** (sin leverage en producción) |
| Universo | 40 large-caps S&P 500 más líquidas |

---

## 🔬 Lecciones del backtest (64 experimentos)

- **Algorithm inelasticity**: cualquier cambio paramétrico degrada performance. El motor está en un máximo local fuerte sobre este universo y timeframe.
- **Geographic expansion FAILED**: COMPASS aplicado a EU (-20.87% CAGR) y Asia (-19.71% CAGR) catastrófico. El alpha es US-market-specific.
- **Leverage destruye valor**: con margin broker al 6%, perdés -1.10% CAGR. Box Spread (SOFR+20bps) sería el único path viable (+0.15%).
- **Survivorship bias absorbido por diversificación**: HYDRA pierde solo +0.50% CAGR vs +5.24% que perdería COMPASS standalone. El portafolio multi-estrategia neutraliza el sesgo.
- **ML overlays destruyen alpha**: 5 capas de ML (MLP filter, HMM regime, graph centrality, sector optimization, Thompson sampling) = -8.08% CAGR vs baseline. La complejidad mata el momentum concentrado.
- **Cash buffer es vol cushion, no capital idle**: deployear el 20% en picks de segundo orden diluye alpha. Cash + Aaa yield es óptimo.
- **Crisis correlation risk**: en flash crashes las correlaciones → 1.0, gaps overnight pueden bypasear el -15% stop. Es inherente al long-only concentrado.

---

## 🛣️ Roadmap

### Completado / Completed
- [x] Algoritmo HYDRA v8.4 LOCKED (64 experimentos)
- [x] Sistema multi-estrategia (COMPASS + Rattlesnake + Catalyst + EFA + cash recycling)
- [x] Meta-Layer v1 (RiskBudgetMetaLayer + BasicRegimeOS + Recovery Adaptation Controller) — ENABLE_META_LAYER flag + shadow deployment
- [x] Backtest con corrección de survivorship bias (882 tickers PIT)
- [x] Integración IBKR con mock mode (53 unit tests passing)
- [x] Dashboard web tiempo real (Flask + cloud deploy en Render)
- [x] Sistema ML de logging y aprendizaje (Phase 1)
- [x] Pre-close execution (signal 15:30 ET + MOC same-day)
- [x] Cash yield Moody's Aaa IG (FRED variable, ~4.8% avg)
- [x] Safety guards: paper port verification, MOC deadline, kill switch, order limits
- [x] Position reconciliation + audit trail
- [x] Live paper trading desde 2026-03-16

### En progreso / In Progress
- [ ] Live paper trading 3-6 meses mínimo (capturar ciclo earnings completo)
- [ ] Sistema ML Phase 2 (~18 días para 500 decisiones)

### Pendiente
- [ ] Norgate Data — S&P 500 point-in-time membership
- [ ] IBKR live paper trading (set `ibkr_mock: false` + TWS port 7497)
- [ ] Optimización fiscal — operar en IRA/401(k) para evitar short-term gains
- [ ] Escalado $500K+ — IBKR portfolio margin + Box Spread financing

---

## ⚠️ Disclaimer

Este sistema es de uso privado para investigación y trading personal. No constituye asesoramiento financiero. Trading conlleva riesgo de pérdida total del capital. Antes de operar con capital real:

1. Backtests extensivos en distintas condiciones de mercado
2. Paper trading mínimo 3-6 meses
3. Validación de costos reales (slippage, commissions, taxes)
4. Monitoreo continuo del comportamiento
5. Ajuste de parámetros a tolerancia personal de riesgo

---

## 📄 Licencia

Proyecto privado — OmniCapital.
