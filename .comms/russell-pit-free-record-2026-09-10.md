# Russell 3000 point-in-time desde el registro público gratuito — qué da, qué no, medido

**From:** Claude
**Date:** 2026-09-10
**Branch:** `feat/russell-free-membership` — `experiments/russell_free_membership.py` + `experiments/test_russell_free_membership.py`
**Contexto:** TASK-403 (panel PIT de Russell) lleva bloqueada en "Norgate Platinum, 630 USD/año". Lucas encontró material
público nuevo (constituent reports 2010–2023, PDF oficiales de altas y bajas 2023–2026, altas de IPO trimestrales,
holdings actuales de VTHR e IWV) y propuso construir la membresía PIT con él. Esta nota mide qué se obtiene de verdad.

## Lo que se verificó y se construyó

| fuente | qué es | verificado hoy |
|---|---|---|
| `kact998/Russell3000Components` | 13 CSV anuales (Company, Ticker) de los PDF de constituyentes de junio, 2010–2023 sin 2013 | descargados; 2.975–3.124 nombres por año |
| FTSE Russell, PDF oficiales de reconstitución | altas y bajas del Russell 3000, junio 2023, 2024, 2025 y 2026 (dos layouts distintos, ambos parseados) | +278/−169, +211/−143, +228/−152, +219/−116 |
| FTSE Russell, IPO additions | altas del trimestre en curso, efectivas 2026-09-21 | 33 nombres |
| iShares IWV / IWB | holdings del ETF a 2026-09-09 | 2.571 y 1.018 acciones (IWV replica ~2.575 de ~3.000) |
| Vanguard VTHR | 2.971 acciones en cartera, benchmark 2.998 | la página es una app JS: el "Export full holdings" hay que hacerlo desde el navegador; no se pudo descargar aquí |

La herramienta descarga todo, parsea, encadena una tabla datada `date, ticker, member, source` (17 fechas, 6.578 tickers
distintos, 52.418 filas) y contrasta contra IWV. Nada se escribe en `_sweep_cache_russell/`; la salida va a
`experiments/_lab_scratch/russell_free/` (gitignored).

## Tres mediciones que deciden

**1. La membresía de junio 2010–2023 es buena y el roll-forward oficial la reproduce.** Rotación de ~300 altas y ~300
bajas por año (10 %). El único junio presente en las dos fuentes (2023) sirve de control: aplicar las altas y bajas
oficiales de 2023 a la lista de 2022 reproduce la lista de 2023 con **7 nombres de diferencia sobre 3.124**.

**2. Pero las listas no quitan a los que se van entre reconstituciones.** La lista arrastrada crece 3.124 → 3.196 → 3.275
→ 3.384 (2026-06) frente a los 2.998 del índice. De los 1.053 nombres de la lista de 2026 que IWV no tiene, **619 no
imprimen en Yahoo desde junio** (muertos, absorbidos o renombrados), y **582 de esos 619 ya venían en el archivo "2023"
del repositorio**: ese archivo es una lista proyectada que conserva a los que salieron intra-año (AAWW, absorbida en
marzo de 2023, sigue en ella). Los PDF oficiales de junio listan bajas de reconstitución, no las bajas por fusión o
quiebra del año. Para la lista de HOY eso se resuelve podando lo que no imprime; para un panel PIT esos nombres deben
quedarse como muertos con sus precios, y ahí está el problema siguiente.

**3. Los precios de los que salieron no existen en Yahoo.** Sobre 6.214 tickers que alguna vez fueron miembros (2010–
2023), 3.983 (64 %) no están en el Russell 3000 de hoy. Dos muestras aleatorias de 150 de esos nombres, en corridas
independientes y sin throttling: Yahoo tiene algún cierre para **17 % y 27 %**, cubre más de la mitad de su época de
membresía para **14 % y 21 %**, y **todos los que tienen precio siguen cotizando hoy**: son empresas que salieron del
índice pero no del mercado, o tickers reutilizados por otra empresa (AVB, DFS, RE, BLD aparecen en la muestra). Los
verdaderamente deslistados: **~0 %**. Es la misma pared que TASK-324 midió en el panel S&P (53 % de miembros con precio en
2005), pero en el universo donde vive el churn.

## Lectura

- El hallazgo de Lucas **resuelve la mitad de la membresía**: junio 2010–2023 con validación cruzada, roll-forward oficial
  2023–2026 y una lista actual defendible tras podar los muertos. TASK-326 había descartado el repositorio por faltar
  2004–2009 y 2013 y por la reutilización de tickers; ambas objeciones siguen en pie, pero ahora hay 16 años de
  membresía datada y no una nota al pie.
- **No resuelve la mitad de los precios**, que es la que TASK-326/334 identificaron como el bloqueo real. Un panel Russell
  construido con estas listas más Yahoo tendría entre el 40 % (2010) y el 70 % (2023) de sus miembros con precio, y los
  que faltan serían exactamente los deslistados: el sesgo de supervivencia entraría por la puerta de atrás, en el
  universo donde el momentum de small caps debería funcionar mejor. `build_russell_pit.py` sigue exigiendo un cliente que
  entregue precios de deslistados; Norgate Platinum sigue siendo el único producto listado que los da junto con la
  membresía. La membresía gratuita pasa a ser el **conjunto de validación** de esa compra, no su sustituto.
- **Efecto colateral sobre producción:** el universo `all` de producción no es membresía Russell sino un proxy por
  capitalización de NASDAQ (así lo etiqueta `data/universe.py`). Hoy coincide con IWV en 2.150 nombres: el 72 % del
  universo de producción y el 84 % de IWV; 852 nombres de producción no están en el Russell 3000 (ADR como ABEV,
  preferentes como ACGLN/ACGLO) y 422 miembros no están en producción. Cambiar el universo vivo es regla 6 y decisión de
  Lucas; el dato queda medido.
- Anécdota útil: ANRO, en las órdenes pendientes del libro, fue alta en 2024, baja en 2025 y alta otra vez en 2026;
  IMMX fue alta en 2026. Los dos son miembros hoy.

## Robustez que costó aprender hoy

Una segunda corrida en la misma hora devolvió 979 "vivos" de 3.417 y 3 de 150 en la sonda: throttling de Yahoo, no
datos. La herramienta descarga ahora por lotes con tres tickers de control (SPY, AAPL, MSFT) en cada lote y **se niega
a publicar** la poda o la sonda si un control vuelve vacío (`reliable=False`, test incluido).

## Reproducir

```
python experiments/russell_free_membership.py --fetch      # descarga todo, construye, contrasta con IWV, sonda Yahoo
python experiments/russell_free_membership.py              # reconstruye desde disco
```
