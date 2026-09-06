<p align="center">
  <img src="docs/img/omnicapital_logo.png" alt="OmniCapital Logo" width="200">
</p>

<h1 align="center">HYDRA</h1>
<h3 align="center">Screener local de momentum + régimen (Python + TradingView)</h3>

<p align="center">
  <strong>100% local · Windows · sin nube · sin broker</strong>
</p>

---

## Qué es esto

Un **screener de acciones US** que corre en tu máquina, rankea el universo cada día y marca un número dinámico de nombres como `recommended`. Está pensado para **ciclos de 5 días de bolsa**.

**Producción desde 2026-09-07: HYDRA v9** (`ALGO_VERSION = "v9"`, autorizado por Lucas) — una cartera **50/50** de dos mangas
operada a mano con una hoja de instrucciones semanal: **T20** (acciones del universo, momentum 12-7, 4 tramos de 20 barras,
vol-target 15 %) y **ETF trend** (10 ETFs, momentum 12 meses sobre T-bill, inverse-vol). `python daily.py` corre el screener
y después `portfolio_v9.py`, que persiste `state/portfolio_v9.json` y escribe `state/instructions_<fecha>.md` ("ejecutar al
cierre del t+1"). Objetivo: retorno por unidad de riesgo (simulado 6.9 % neto, Sharpe 0.74, maxDD −19.5 % en S&P 500 PIT
2004-2026; sin track record). Diseño: [`.comms/claude-v9-production-design-2026-09-06.md`](.comms/claude-v9-production-design-2026-09-06.md);
SPEC §9. El ranking v8.4 (momentum 90d) sigue generándose para los artefactos de Pine, que están **aparcados**.

Python calcula y selecciona. TradingView solo muestra: pegas `pine/hydra_last_summary.json` y `pine/watchlist.txt` en el indicador `pine/HYDRA_Screener.pine`. El flag `Rec?` que manda es el de Python.

**Código activo:** [`hydra_screener_local/`](hydra_screener_local/). COMPASS, Rattlesnake, Flask, paper trading y el resto de la raíz vieja están en [`archive/root-legacy-2026-09/`](archive/root-legacy-2026-09/). No se usa, no se revive.

| | Ranking v8.4 (screener, artefactos Pine) |
|---|---|
| Universo | `"all"` — S&P 500 ∪ Nasdaq-100 ∪ Dow ∪ Russell 1000 ∪ Russell 2000 (~3000 nombres) |
| Score | momentum 90d / vol 63d, sin skip de 5d |
| Selección | N dinámico 6–28 según régimen; cap duro **5 por sector GICS** (`"Other"` exento) |
| Filtros | precio ≥ $5, 100k acciones/día, **$5M** de volumen en dólares |
| Coste modelado | 10 bp por lado (sweep y tracking) |

La Meta-Layer **no cambia el ranking** (el mismo escalar para todos los tickers ese día; Spearman 1.000). Solo mueve cuántos nombres salen recomendados. Rattlesnake / Catalyst / EFA no tocan el score.

Spec: [`hydra_screener_local/HYDRA_ALGORITHM_SPEC.md`](hydra_screener_local/HYDRA_ALGORITHM_SPEC.md). Parámetros: [`hydra_screener_local/config.py`](hydra_screener_local/config.py). El scoring está **cerrado** salvo aprobación explícita.

---

## Cómo correrlo

```bash
git clone https://github.com/lucasabu1988/HydraOmniCapital.git
cd HydraOmniCapital/hydra_screener_local
pip install -r requirements.txt
python daily.py
```

`daily.py` ejecuta el screener y deja las instrucciones de copy-paste para TradingView. Alternativas:

```bash
python screener.py                 # solo el screener
python daily.py --universe sp500   # universo más chico / más rápido
python analyze_history.py          # reportes sobre history/ (gitignored; aparece al correr)
python track_performance.py        # win-rate bruto y neto (coste modelado)
```

Datos: **yfinance**. No hay deploy, ni Render, ni IBKR.

---

## Tests

```bash
cd hydra_screener_local
python run_all_tests.py            # suite del producto; debe salir 0
```

CI (GitHub Actions, `.github/workflows/test.yml`): un solo job, `screener`, que corre esta suite en Python 3.12. Los tests del motor legacy están archivados y no se ejecutan. La suite omite (`SKIP`, no `PASS`) los archivos que necesitan artefactos locales: `history/` y `pine/hydra_last_summary.json`.

---

## Layout

```
hydra_screener_local/
  screener.py / daily.py     entrada diaria
  config.py                  parámetros
  HYDRA_ALGORITHM_SPEC.md    fuente de verdad del algoritmo
  core/                      signals, régimen, filtros, history, tracking
  data/                      universo, precios, sectores GICS
  pine/                      indicador TradingView + contrato JSON
  experiments/               harness point-in-time (backtest_variant_sweep.py)
  run_all_tests.py
```

Agentes: [`CLAUDE.md`](CLAUDE.md), [`AGENTS.md`](AGENTS.md), tablero [`GROKBOARD.md`](GROKBOARD.md).

---

## Lo que este repo ya no es

El README anterior describía un sistema **que no corre**:

- cuatro estrategias (COMPASS 42.5% / Rattlesnake 42.5% / Catalyst / EFA) con recycling
- dashboard Flask en [omnicapital.onrender.com](https://omnicapital.onrender.com/) — **servicio suspendido**; Render se retiró
- Meta-Layer con `ENABLE_META_LAYER` y paper trading IBKR
- parámetros v8.4 (5 posiciones, máx 3/sector, skip 5d, 40 large-caps)

Ese código está en [`archive/root-legacy-2026-09/`](archive/root-legacy-2026-09/) o borrado (`omnicapital_live.py` no existe). Docs de agentes viejos: `archive/docs-legacy-2026-09/`. No tomes parámetros de ahí.

---

## Disclaimer

Investigación y uso personal. No es asesoramiento financiero. Trading puede perder el capital entero.

---

## Licencia

Uso privado — OmniCapital. El repositorio es público.
