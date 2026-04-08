<p align="center">
  <img src="static/img/omnicapital_logo.png" alt="OmniCapital Logo" width="200">
</p>

<h1 align="center">OmniCapital HYDRA</h1>
<h3 align="center">Sistema multi-estrategia de trading cuantitativo</h3>

<p align="center">
  <strong>14.45% CAGR</strong> | <strong>0.91 Sharpe</strong> | <strong>-27.0% Max DD</strong> | <strong>$100k → $3.3M</strong> (2000-2026, survivorship-corrected)
</p>

<p align="center">
  <a href="https://omnicapital.onrender.com">🌐 Dashboard en vivo</a>
</p>

---

## 🎯 Estado actual

**Paper trading en vivo desde el 16 de marzo de 2026.** 18 días de trading completados al 8 de abril de 2026.

| Métrica | Backtest (2000-2026) | Live (Mar 16 - Apr 8 2026) |
|---|---|---|
| CAGR esperado | 14.45% | en curso |
| Sharpe | 0.91 | en curso |
| Max Drawdown | -27.0% | -1.49% |
| Final value | $3.3M (de $100k) | $100,400 (de $100k) |

Backtest corrido sobre **882 tickers point-in-time** del S&P 500 (multi-source pipeline: yfinance + Tiingo + Stooq + Wayback Machine), recuperando incluso bancarrotas históricas (Lehman, Bear Stearns, Merrill, Wachovia, Eastman Kodak, Nortel, Countrywide).

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

**Algorithm LOCKED**: 64 experimentos corridos. El motor está congelado; cualquier cambio paramétrico degrada performance. La inelasticidad fue confirmada empíricamente.

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
| `compass_dashboard_cloud.py` | Flask app cloud (Render) — entrypoint deployado |
| `compass_dashboard.py` | Flask app local + engine runner |
| `omnicapital_live.py` | Core engine (`COMPASSLive`) — orquesta las 4 estrategias |
| `omnicapital_v84_compass.py` | Algoritmo COMPASS v8.4 (LOCKED) |
| `rattlesnake_signals.py` | Señales Rattlesnake (RSI dip-buying) |
| `catalyst_signals.py` | Señales Catalyst (trend cross-asset + gold) |
| `hydra_capital.py` | `HydraCapitalManager` — cash recycling |
| `compass_ml_learning.py` | Sistema ML de aprendizaje progresivo |
| `omnicapital_broker.py` | `PaperBroker` + `IBKRBroker` (mock + live) |
| `templates/dashboard.html` + `static/` | Frontend dashboard |

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
python compass_dashboard.py    # Flask en localhost:5000
```

Para deploy cloud-style:
```bash
gunicorn compass_dashboard_cloud:app --bind 0.0.0.0:5000 --workers 1 --threads 4 --preload
```

---

## 🧪 Tests

```bash
pytest tests/ -v                           # Suite completa
pytest tests/ -v --cov-fail-under=50       # Con coverage threshold (CI default)
python tests/validate_live_system.py       # Validación end-to-end
```

CI corre en GitHub Actions con coverage mínimo del 50% en módulos críticos: `compass_api_models`, `compass_dashboard`, `compass_dashboard_cloud`, `compass_ml_learning`, `omnicapital_broker`, `omnicapital_live`.

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

### Completado
- [x] Algoritmo HYDRA v8.4 LOCKED (64 experimentos)
- [x] Sistema multi-estrategia (COMPASS + Rattlesnake + Catalyst + EFA + cash recycling)
- [x] Backtest con corrección de survivorship bias (882 tickers PIT)
- [x] Integración IBKR con mock mode (53 unit tests passing)
- [x] Dashboard web tiempo real (Flask + cloud deploy en Render)
- [x] Sistema ML de logging y aprendizaje (Phase 1)
- [x] Pre-close execution (signal 15:30 ET + MOC same-day)
- [x] Cash yield Moody's Aaa IG (FRED variable, ~4.8% avg)
- [x] Safety guards: paper port verification, MOC deadline, kill switch, order limits
- [x] Position reconciliation + audit trail
- [x] Live paper trading desde 2026-03-16

### En progreso
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
