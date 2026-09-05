# HYDRA — Segunda lectura del corpus legacy (OneDrive): qué ignoramos o hacemos distinto hoy

**Autor:** Claude (architect) · **Fecha:** 2026-09-06
**Pregunta de Lucas:** "¿encontraste algo en los .md que nos ayudara a mejorar el algoritmo? busca cosas que hoy
estemos ignorando o no ejecutando correctamente."
**Fuente:** `OneDrive/Documentos/_PARA_MOVER_FUERA/Repos_GitHub/GitHub/NuevoProyecto/` — 45 .md (leídos los 30
con contenido algorítmico; los de dashboard/deploy/i18n no) + `backtests/` (110 CSV de equity diario, de los que
recalculé CAGR / maxDD / Sharpe porque la mayoría nunca se documentaron en ningún .md).
**Método:** cada lección legacy se contrastó con lo que hace hoy `hydra_screener_local/` y, cuando la
diferencia era medible, se midió en el lab (`experiments/redesign_lab.py`) sobre el panel PIT 2004-2026.

---

## 0. Resumen

Cuatro cosas concretas, ordenadas por lo que cambian:

1. **Datos corruptos sin filtro (ejecutamos mal).** El legacy filtraba nombres con un movimiento diario > 50 %
   (exp53, "quality filter") porque Yahoo devuelve series basura para tickers delistados/reutilizados. Ni el
   harness ni `screener.py` filtran saltos. El panel PIT tiene 18 series con saltos > +100 % (DEC = ∞, MI +9500 %,
   COMS +3000 %…). Medido: §2.
2. **El cash rinde 0 en todas nuestras medidas (contabilidad incompleta).** El legacy midió +0.9 pp CAGR al
   pagar T-bill al cash ocioso (`v83_test_cash_yield` 16.92 vs 16.01). Nuestro lab y el harness pagan 0; eso
   castiga sistemáticamente a cualquier diseño con más cash (vol-targeting, gate). Medido: §3.
3. **Breadth dentro del régimen (algo que hacemos y el legacy midió como dañino dos veces).** `v8_opt_c_breadth_filter`
   11.02 vs 16.01 y `v85b_breadth_only` 9.91 vs 12.20. HYDRA lleva breadth al 10 % en el régimen rico (SPEC 4.3).
   Medido: §4.
4. **Crash brake de mercado (algo que el legacy tenía y HYDRA no).** SPY −6 % en 5d o −10 % en 10d → sin entradas
   nuevas 10 días (MANIFESTO §5.2). El downtrend gate de HYDRA es por acción, no de mercado. Medido: §5.

Y una lista de cosas que el legacy probó y **fallaron**, para no volver a gastarlas (§6). Ninguna de las cuatro
anteriores es un cambio de scoring; 1 y 2 son correcciones de medición/filtro, 3 y 4 son cambios de régimen/exposición.

## 1. Lo que dicen los 110 CSV legacy (mismo motor COMPASS, 2000-2026, universo sesgado salvo indicación)

Recalculado desde `value` diario. Baseline de cada bloque en negrita. Sólo los que nos afectan:

| Experimento legacy | CAGR | maxDD | Sharpe | Lección para HYDRA hoy |
|---|---|---|---|---|
| **v8_opt_base_v8.2** | **16.01** | −39.3 | 0.82 | referencia del bloque v8 |
| v83_test_hysteresis (régimen con histéresis +2 %) | 11.46 | −40.9 | 0.67 | **−4.5 pp**. Nuestro gate es sin estado: no añadir histéresis |
| v83_test_cash_yield (T-bill al cash) | 16.92 | −37.9 | 0.86 | **+0.9 pp** de contabilidad que nosotros no hacemos |
| v8_opt_c_breadth_filter | 11.02 | −42.7 | 0.66 | breadth como filtro: **−5.0 pp** |
| v8_opt_b_risk-adj_mom | 8.02 | −38.3 | 0.56 | momentum/vol con inverse-vol sizing encima: −8 pp (doble castigo a la vol). Nosotros medimos k=1 vs k=0 en nuestro pipeline y k=1 gana (TASK-320): decisión propia, se mantiene |
| v8_opt_a2_vix_override | 15.53 | −39.3 | 0.80 | VIX override: nada |
| **v84_compass** | **12.20** | −32.0 | 0.87 | referencia del bloque v8.4 (sin leverage) |
| v85a_stop_only (stops más anchos en bull) | 11.01 | −32.0 | 0.80 | −1.2 pp |
| v85b_breadth_only (breadth 25 % en el régimen) | 9.91 | −38.4 | 0.74 | **−2.3 pp** |
| v85_compass (ambos) | 10.79 | −29.9 | 0.76 | −1.4 pp |
| v85_idea1_har_recovery | 12.33 | −31.8 | 0.89 | +0.13 pp, por debajo del criterio pre-registrado (+0.6) |
| v85_idea10_vol_compression | 12.20 | −32.0 | 0.87 | 0 |
| v84_longrot_annual / biennial / quadrennial | 12.46 / 10.51 / 11.92 | | | rotación del universo: n/a para un screener |
| v84_overlay (macro overlays FRED) | 10.41 | −33.0 | 0.77 | −1.8 pp: los overlays macro restan |
| exp54_signal_only / lev_only / three_moves | 11.55 / 11.58 / 12.05 | | | n/a |
| **exp55_baseline_774 (750 limpios)** | **12.24** | −32.1 | 0.85 | referencia del bloque "clean" |
| exp55_residual_momentum | 10.80 | −30.3 | 0.73 | −1.4 pp |
| exp56_multi_lookback | 11.79 | −32.0 | 0.82 | **−0.5 pp** — el design doc decía +0.85 "WIN"; el CSV dice FAIL. Coincide con nuestro DEV (−1.5 pp sobre T20) |
| exp57_dynamic_hold | 11.52 | −33.6 | 0.82 | −0.7 pp |
| exp58_tail_hedge | 12.18 | −32.0 | 0.85 | 0 |
| chatgpt_cond_hold_ext / ensemble_mom / preemptive_stop / all_three | 13.00 / 9.50 / 10.38 / 12.89 vs **16.92** | | | las cuatro ideas "ChatGPT" restan 4-7 pp |
| dynrecov_vix / breadth / combined / aggressive | 14.81 / 14.46 / 14.57 / 12.81 vs **16.92** | | | recuperación dinámica post-stop: todas restan |
| protshort_sh / sds (cortos en protección) | 14.44-15.54 vs 16.92 | −28.8 a −32.5 | | menos CAGR, algo menos DD |
| hydra_corrected vs hydra_clean | 16.45 / **14.42** | **−53.6 / −27.0** | 0.87 / 0.91 | **limpiar 25 series corruptas movió el maxDD de −54 % a −27 %** con el mismo motor |
| exp40 / exp41 corrected | 13.88 / 11.30 | −66 / −63 | 0.65 / 0.53 | corrección de supervivencia −4.6 / −7.2 pp (ya en el veredicto) |
| exp42_compass_666 | 4.83 | 0.0 | 57.7 | serie rota (equity plana); el "666" no tiene resultado válido |
| stooq_crossval vs yfinance | 12.66 vs 12.67 | | | la fuente de precios no es el problema; los tickers muertos sí |

Lecturas transversales: (a) todo lo que añade un estado o un parámetro al régimen (histéresis, breadth, overlays,
recuperación dinámica) **restó**; (b) lo único que sumó fue contabilidad honesta (cash yield) y limpieza de datos;
(c) el motor legacy nunca superó ~12-14 % con universo corregido y sin leverage, coherente con nuestro 7-9 %
neto una vez se descuentan costes y supervivencia de precios.

## 2. Datos corruptos en el panel PIT — medición

Filtro `max_jump=1.0`: un nombre es inelegible mientras su máximo |retorno diario| en las últimas 252 barras
supere el 100 % (ventana trailing: sin look-ahead). Y, con la columna `traded` del lab, qué nombres de la lista
de 18 se operaron de verdad.

| Config | bruto | neto | Sharpe | maxDD | Nombres "sospechosos" operados |
|---|---|---|---|---|---|
| PROD ALL | 9.60 | 5.38 | 0.41 | −38.2 | HIG (36 pasos), FMCC (6), GME (16), NKTR (4), MRNA (11) |
| PROD_dq ALL | 9.58 | 5.36 | 0.41 | −38.2 | |
| T20 ALL | 8.87 | 7.61 | 0.60 | −28.6 | HIG (47), GME (28), NKTR (11), MRNA (10) |
| T20_dq ALL | 8.87 | 7.61 | 0.60 | −28.6 | |

Veredicto: **ninguna de las 13 series basura (MI, COMS, MCIC, STI, UPC, DEC…) se operó jamás** — la membresía PIT
con bloqueo de reutilización (TASK-325) las hace inelegibles en las fechas en que Yahoo tiene precios de otra
empresa. Los únicos nombres con saltos que sí se operaron son empresas reales en eventos reales. El filtro cuesta
0.02 pp en PROD y 0.00 en T20. **Los números del veredicto no están contaminados.** Para producción (universo
Russell con ~3000 nombres de yfinance, sin membresía PIT que proteja) el filtro sigue siendo una defensa barata y
correcta — pero es robustez, no rendimiento, y no se puede medir aquí.

Inspección de los 18 saltos: la mayoría son tickers reutilizados cuya serie de Yahoo empieza **después**
de que el miembro PIT saliera del índice (STI desde 2022, UPC 2021, MI 2015, EQ 2018 — la membresía PIT los hace
inelegibles en esas fechas, así que TASK-325 los contiene), o penny stocks a 0.00 (COMS, MCIC). Tres son reales:
HIG +102 % (2008-12-05), CAR +108 % (2021-11-02, short squeeze), MRNA +177 % (2026-08-19). El filtro también
excluiría estos tres durante un año: para un screener de momentum eso es deseable (un salto de evento no es
momentum), pero es un cambio de lista y hay que decirlo.

## 3. Cash a T-bill — medición (muestra completa 2004-2026)

`cash_yield=True`: la fracción no invertida del libro (1 − exposición) gana el T-bill a 13 semanas (^IRX,
cacheado en `_sweep_cache_oos/irx.pkl`; media 2004-2026 ≈ 1.6 %, casi 0 en 2009-2021, 4-5 % en 2023-2026).

| Config | bruto | neto | Sharpe | maxDD | Δ neto |
|---|---|---|---|---|---|
| PROD ALL | 9.60 | 5.38 | 0.41 | −38.2 | |
| PROD + T-bill | 9.72 | 5.50 | 0.42 | −37.8 | +0.12 |
| T20 ALL | 8.87 | 7.61 | 0.60 | −28.6 | |
| T20 + T-bill | 9.06 | 7.80 | 0.61 | −28.0 | +0.19 |
| T20 + T-bill, TEST 2016-26 | 9.50 | 8.19 | 0.63 | −26.7 | +0.27 |

Veredicto: real pero pequeño (+0.1 / +0.2 pp; el legacy medía +0.9 porque su periodo incluía 2000-2007 con
tipos al 3-5 % y más cash). Va a favor del candidato con más cash, como se esperaba. Las cifras del veredicto se
mantienen a cash 0 % (conservador) y esta fila queda como nota; en producción el cash sí debería estar en un
fondo monetario / T-bill, y eso vale hoy ~4 % sobre el 14 % no invertido de T20 ≈ +0.5 pp/año.

## 4. Régimen sin breadth — medición (DEV 2004-2015)

`regime_breadth=False` → `compute_rich_regime_scores(spy, prices=None)`, breadth fijo en 0.5 (peso 10 %).

| Config | bruto | neto | Sharpe | maxDD |
|---|---|---|---|---|
| PROD | 7.44 | 3.33 | 0.28 | −38.2 |
| PROD sin breadth | 7.39 | 3.23 | 0.28 | **−44.4** |
| T20 | 8.53 | 7.31 | 0.58 | −28.6 |
| T20 sin breadth | 8.26 | 7.06 | 0.57 | −29.7 |

Veredicto: quitar breadth **empeora** (−0.1 / −0.25 pp y peor DD). La lección legacy no se traslada: allí
breadth pesaba 25 % del régimen o actuaba como filtro de entrada; en HYDRA pesa 10 % y sólo mueve
`dynamic_count` y el gate. **Se mantiene tal cual.**

## 5. Crash brake de mercado — medición (DEV 2004-2015)

Regla v8.4 exacta: SPY 5d < −6 % o 10d < −10 % → exposición 0 en el paso (el tramo nuevo no se abre).

| Config | bruto | neto | Sharpe | maxDD |
|---|---|---|---|---|
| PROD | 7.44 | 3.33 | 0.28 | −38.2 |
| PROD + brake | 7.28 | 3.20 | 0.28 | −39.1 |
| T20 | 8.53 | 7.31 | 0.58 | −28.6 |
| T20 + brake | 8.04 | 6.85 | 0.56 | −29.3 |

Veredicto: **resta** en los dos (−0.1 / −0.5 pp) y no mejora el DD: el freno vende justo antes del rebote y
el vol-targeting de T20 ya hace el trabajo de reducir exposición tras un pico de volatilidad, sin el timing
binario. Rechazado; coherente con "cash es un colchón de volatilidad" del propio legacy.

## 6. Lo que el legacy ya enterró (no volver a probar)

Residual momentum (exp55), multi-lookback (exp56 — confirmado en nuestro DEV), hold dinámico (exp57), tail hedge
(exp58), histéresis del régimen, breadth como filtro, stops más anchos en bull, HAR-RV/Omori para recuperación,
VIX compression flag, crowding con AUM de MTUM (intestable), overlays macro FRED (−1.8 pp), cortos en protección,
recuperación dinámica post-stop, ML overlays (−8 pp), conviction tilt (−1.2 pp), profit targets (−4.4 pp),
expansión geográfica (−20 pp), pairs trading (−3.4 pp, −79 % DD), universo ampliado indiscriminado (v6 150 vs 40:
−8.5 % CAGR, −90 % DD — con supervivencia, pero la dirección vale).

## 7. Qué sí vale la pena llevar a producción

Respuesta corta a la pregunta de Lucas: **el corpus no contiene ninguna mejora de scoring que no hubiéramos
medido ya, y las dos que "faltaban" (crash brake, quitar breadth) restan.** Lo que sí encontró son dos cosas
de ejecución/medición, y una confirmación importante:

1. **Filtro de saltos en producción (robustez, no rendimiento).** `core/filters.py` no filtra movimientos
   diarios extremos; el universo `"all"` son ~3000 nombres de yfinance sin membresía PIT que los proteja, y el
   legacy ya se encontró 25 series con +500 % ficticios. Propuesta: `apply_data_quality_filter(prices,
   max_abs_daily_return=1.0, lookback=252)` en `core/filters.py`, aplicado en `screener.py` tras los filtros
   prácticos, con test sintético y un conteo real de cuántos nombres retira en una corrida de producción. Es
   un filtro (SPEC §1, "implementation-specific"): no necesita regla 6, pero cambia la lista y hay que medirlo.
   → tarea para Grok (TASK-335).
2. **Cash en T-bill.** En el lab queda como opción (`cash_yield`), documentada arriba. En producción es una
   decisión operativa de Lucas: el capital no invertido debería estar en un fondo monetario. Hoy ≈ +0.5 pp/año
   para T20, +0.35 para PROD.
3. **Confirmación:** los números del veredicto (`claude-redesign-verdict-2026-09-06.md`) no están contaminados
   por datos corruptos (§2), y las dos decisiones estructurales que el legacy cuestionaba — régimen sin estado
   (sin histéresis) y breadth al 10 % — quedan validadas en nuestro panel.

Lo que **no** se lleva: crash brake (−0.1 / −0.5 pp), quitar breadth (−0.1 / −0.25 pp), y toda la lista de §6.

## 8. Cambios en el lab (commit de este informe)

`redesign_lab.py`: `P.JUMP252`, `P.SPY_R5/R10`, `P.IRX`; claves de config `max_jump`, `crash_brake`,
`cash_yield`, `regime_breadth` (todas apagadas por defecto = producción); configs `PROD_dq`, `T20_dq`,
`PROD_brake`, `T20_brake`, `PROD_cy`, `T20_cy`, `PROD_nobreadth`, `T20_nobreadth`. Los resultados de PROD y T20
sin opciones son idénticos a los del veredicto (comprobado en la tabla de §2). Multiplicidad: +4 variantes en
DEV (brake ×2, nobreadth ×2) — ninguna elegida; `_dq` y `_cy` son contabilidad, no candidatos, y por eso se
corrieron en full sample.
