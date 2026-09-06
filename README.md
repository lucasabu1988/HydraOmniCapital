<p align="center">
  <img src="docs/img/omnicapital_logo.png" alt="OmniCapital Logo" width="200">
</p>

<h1 align="center">HYDRA</h1>
<h3 align="center">Cartera 50/50 momentum de acciones + trend-following en ETFs, operada a mano desde una hoja semanal</h3>

<p align="center">
  <strong>100% local · Windows · sin nube · sin broker · Python</strong>
</p>

---

## Qué es esto

**HYDRA v9** (producción desde 2026-09-07) es una cartera de dos mangas con capital 50/50 que se opera manualmente a partir de una **hoja de instrucciones semanal**. Python decide; tú ejecutas en tu bróker.

| | Manga A — T20 (acciones) | Manga B — ETF trend |
|---|---|---|
| Capital | 50 %, en 4 tramos de 12.5 % | 50 %, en 4 tramos de 12.5 % |
| Universo | `"all"`: S&P 500 ∪ Nasdaq-100 ∪ Dow ∪ Russell 1000 ∪ Russell 2000 (~3 000 nombres), filtros de liquidez/precio, filtro de calidad de datos, cap duro de **5 por sector**, veto de caída reciente | SPY QQQ IWM EFA EEM TLT IEF GLD DBC VNQ (fijo) |
| Señal | momentum **12-7** (`close[t−126]/close[t−252] − 1`) / vol 63d; régimen rico sobre SPY y Meta-Layer deciden cuántos nombres (6–28) | retorno 12 meses − T-bill > 0 → largo, si no T-bill |
| Pesos | iguales × exposición `min(1, 15 % / vol de la cesta)`; el resto en T-bill | inverse-vol sobre todo el universo; los apagados dejan su parte en T-bill |
| Ritmo | cada **5 barras de bolsa** se renueva **un** tramo (vive 20 barras); un nombre en cartera se conserva si sigue en el top 2n | igual |
| Reset 50/50 | el tramo renovado se dimensiona a 1/8 del libro; la diferencia se transfiere entre mangas (registrado) | |
| Cash | T-bill / fondo monetario | |
| Costes modelados | 10 bp por lado | 5 bp por lado |

**Convención temporal:** la corrida se hace tras el cierre del día *t* (viernes); la hoja instruye ejecutar **al cierre de *t+1*** (lunes, MOC). La siguiente corrida asume esos fills como *presumidos* hasta que los confirmes con los reales.

**Objetivo declarado:** retorno por unidad de riesgo, no retorno absoluto. Evidencia (simulación con contabilidad ejecutable, S&P 500 point-in-time 2004-2026, costes incluidos): cartera 50/50 **6.9 % neto, Sharpe 0.74, maxDD −19.5 %** frente al screener v8.4 solo (5.5 % / 0.42 / −37.8 %) y SPY comprar-y-mantener (11.0 % / 0.68 / −54.7 %). El 10 % neto **no se demuestra**; el universo Russell de producción **no está medido** (solo S&P 500). No hay track record: el único registro vivo es el ledger de `state/`.

Documentos: [diseño de producción](.comms/claude-v9-production-design-2026-09-06.md) · [auditoría y métricas](.comms/claude-audit-2026-09-06.md) · [veredicto del rediseño](.comms/claude-redesign-verdict-2026-09-06.md) · [mangas](.comms/claude-sleeves-design-2026-09-06.md) · spec: [`HYDRA_ALGORITHM_SPEC.md`](hydra_screener_local/HYDRA_ALGORITHM_SPEC.md) (§9 = v9). Parámetros: [`config.py`](hydra_screener_local/config.py) (`ALGO_VERSION`, bloque `V9`). El scoring está **cerrado** salvo aprobación explícita de Lucas.

---

## Cómo operar

```bash
git clone https://github.com/lucasabu1988/HydraOmniCapital.git
cd HydraOmniCapital/hydra_screener_local
pip install -r requirements.txt
python warm_sectors.py                 # una vez: caché de sectores completa (sin ella el cap sectorial no actúa)
python daily.py                        # viernes tras el cierre: screener + portfolio_v9 -> hoja de instrucciones
```

Ritmo semanal:

1. **Viernes tras el cierre** (o fin de semana): `python daily.py`. Genera `state/instructions_<fecha>.md` con las órdenes (compras, ventas, transferencia 50/50, `park` en T-bill) y unidades estimadas al cierre del viernes. Si más del 30 % de los candidatos no tiene sector, la hoja lleva cabecera **DEGRADED**: corre `warm_sectors.py` y repite.
2. **Lunes al cierre:** ejecuta los importes en $ de la hoja (MOC). El efectivo no invertido de cada manga va a T-bill/fondo monetario.
3. **Lunes tras el cierre (o martes):** `python daily.py` liquida los fills presumidos al cierre del lunes y valora. Los días sin renovación imprimen "No trades today".
4. **Fills reales:** `python confirm_fills.py --from-csv fills.csv` (`exec_date,sleeve,tranche,ticker,side,units,price,fee`); `--report` solo muestra diferencias. Compras no planificadas quedan como `confirmed_unplanned`.
5. **Dashboard local:** `python dashboard_v9.py` → `http://127.0.0.1:8765/` (rendimiento, P/L realizado y no realizado, log de operaciones, curva de equity, comparación con SPY). Solo lectura del estado; cotizaciones cada 5 min.
6. **Respaldo fuera del disco:** define `HYDRA_BACKUP_DIR`; cada corrida copia `state/` y las hojas a `<dir>/state_v9/<fecha>/`.

Primera corrida: `python portfolio_v9.py --capital 100000` (o `daily.py --v9-capital`). El primer estado se creó el **2026-09-04** (ancla viernes; primeras órdenes lunes 2026-09-07 al cierre).

Datos: **yfinance** (precios ajustados a 2 años, ETFs, `^IRX`). No hay deploy, ni Render, ni IBKR, ni webhooks.

---

## Qué hay dentro

```
hydra_screener_local/
  daily.py                   ritual: screener + portfolio_v9 (ALGO_VERSION = "v9")
  portfolio_v9.py            CLI v9: estado, motor, hoja de instrucciones, respaldo
  confirm_fills.py           fills reales sobre los presumidos (core/fills.py)
  dashboard_v9.py            dashboard local en vivo (dashboard/index.html)
  warm_sectors.py            caché GICS completa (guardado incremental)
  screener.py                ranking diario (también escribe los artefactos v8.4 para Pine)
  config.py                  parámetros; ALGO_VERSION; bloque V9
  HYDRA_ALGORITHM_SPEC.md    fuente de verdad del algoritmo (§9 = cartera v9)
  core/portfolio_engine.py   motor puro: plan / settle / mark, selección con buffer y cap, reset 50/50
  core/tranche_book.py       contabilidad ejecutable por tramo (unidades, efectivo, operaciones, write-offs)
  core/signals.py            momentum (ret90 | mom12_7), features, filtro estricto, dynamic count, veto
  core/regime.py, meta_layer.py, filters.py, tracking.py, history.py
  sleeves/etf_trend.py       señales y pesos de la manga ETF
  data/                      universo, precios (2y), ETFs, T-bill, sectores
  state/                     (gitignored) portfolio_v9.json, instructions_<fecha>.*, backup/, equity_curve.csv
  experiments/               harness PIT, redesign_lab, sleeve_lab, engine_backtest (simulador ejecutable)
  run_all_tests.py           runner
```

`pine/` (indicador TradingView) sigue en el repo pero está **aparcado**: los artefactos v8.4 se generan, nadie los mantiene.

---

## Tests

```bash
cd hydra_screener_local
python run_all_tests.py            # debe salir 0
```

Estado al 2026-09-07: **29 archivos PASS, 2 SKIP, 0 FAIL**. Los dos skips necesitan artefactos locales (`history/`, `pine/hydra_last_summary.json`); un skip no es un pass. Cubren, entre otros: cero recomendaciones sin fallback, lista completa en todas las exportaciones, tracking con estados pendiente/medido, contabilidad por tramo (caso 100→200→100 = 0 %), causalidad de la mezcla, paridad del motor de producción con el simulador (1e-9), CLI idempotente, fills confirmados, dashboard.

CI (GitHub Actions, `.github/workflows/test.yml`): un solo job, `screener`, Python 3.12. CI verde demuestra regresión de código, no validez financiera.

Agentes: [`CLAUDE.md`](CLAUDE.md), [`AGENTS.md`](AGENTS.md), tablero [`GROKBOARD.md`](GROKBOARD.md), notas en [`.comms/`](.comms/).

---

## Lo que este repo ya no es

El motor COMPASS (cuatro estrategias con recycling, dashboard Flask en Render, paper trading IBKR, parámetros "5 posiciones / máx 3 por sector / skip 5d / 40 large-caps") está en [`archive/root-legacy-2026-09/`](archive/root-legacy-2026-09/) o borrado. No se usa, no se revive, no se toman parámetros de ahí. El screener v8.4 (momentum 90d, ciclo de 5 días) sigue existiendo como ranking, pero la producción es la cartera v9.

---

## Disclaimer

Investigación y uso personal. No es asesoramiento financiero. Trading puede perder el capital entero.

---

## Licencia

Uso privado — OmniCapital. El repositorio es público.
