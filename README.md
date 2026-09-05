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

Python calcula y selecciona. TradingView solo muestra: pegas `pine/hydra_last_summary.json` y `pine/watchlist.txt` en el indicador `pine/HYDRA_Screener.pine`. El flag `Rec?` que manda es el de Python.

**Código activo:** [`hydra_screener_local/`](hydra_screener_local/). El resto del repo (COMPASS, Rattlesnake, dashboard Flask, paper trading) es **legacy congelado**. No se usa, no se revive.

| | Producción |
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

CI (GitHub Actions): job `screener` (esta suite) y job `test` (`pytest tests/` del motor legacy, informativo).

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

Ese código está congelado o borrado (`omnicapital_live.py` ya no existe). Docs viejos: `archive/docs-legacy-2026-09/`. No tomes parámetros de ahí.

---

## Disclaimer

Investigación y uso personal. No es asesoramiento financiero. Trading puede perder el capital entero.

---

## Licencia

Uso privado — OmniCapital. El repositorio es público.
