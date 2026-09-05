# HYDRA — Rediseño del algoritmo: veredicto y diseño candidato

**Autor:** Claude (architect) · **Fecha:** 2026-09-06
**Encargo (Lucas):** "rediseñar el algoritmo para que tenga resultados de por lo menos 10% anualizado".
**Lectura del encargo:** 10 % **neto** de costes (10 bp/lado), sin apalancamiento, sobre el único panel
honesto que tenemos: S&P 500 con membresía point-in-time 2004-2026 (TASK-324/325). Producción hace
ahí 9.6 % bruto / 5.4-5.7 % neto, así que el encargo era casi doblar el neto.
**Laboratorio:** `hydra_screener_local/experiments/redesign_lab.py` (importa el harness validado
`backtest_variant_sweep.py`; misma puntuación que producción salvo la palanca que se cambia).
**Estado de producción:** sin cambios. Nada de lo que sigue se aplicó a `core/` ni al SPEC.

---

## 0. Veredicto en tres líneas

1. **El 10 % neto no se alcanza de forma honesta** en 2004-2026 con ninguna variante robusta. El
   mejor candidato robusto (T20) hace **8.9 % bruto / 7.6 % neto**, Sharpe 0.60, maxDD −28.6 %,
   frente a producción 9.6 % bruto / 5.4 % neto, Sharpe ~0.4, maxDD −39 %.
2. Lo que sí se consigue: **+2.2 pp de neto anualizado con un tercio de la rotación y 10 pp menos
   de drawdown**, y el candidato es el único que sobrevive al período difícil (2004-2015: 7.3 % neto
   frente a 3.3 % de producción). En 2016-2026 producción y T20 empatan (7.5 % vs 7.9 %).
3. Las rutas que quedan hacia el 10 % son externas al scoring: (a) costes reales de 5 bp/lado en
   large caps (F1 y PROD rondan 9.7-9.9 % neto en TEST a 5 bp; T20 8.6 %), (b) medir sobre el
   universo de producción (Russell) — imposible hoy: TASK-326 concluyó que no hay fuente PIT
   gratuita honesta, (c) aceptar el bruto como métrica (PROD 11.9 % / F1 11.0 % en TEST). Ninguna
   de las tres es una decisión mía.

---

## 1. Protocolo (para que el número signifique algo)

- Panel: 1209 tickers (miembros PIT del S&P 500 2004-2026 con precio en Yahoo). Cobertura de
  precios 53 % (2005) → 95 % (2023): la membresía es real, los precios NO son survivorship-free.
  El sesgo restante favorece a cualquier momentum; afecta a todas las variantes por igual.
- Partición fija antes de mirar nada: **DEV < 2016-01-01 ≤ TEST**. DEV se exploró libremente
  (~35 configuraciones). TEST se miró **una sola vez**, para cuatro finalistas pre-registrados
  (PROD, F1, T20, T10). Después de esa mirada solo se corrió en DEV (§4).
- Costes: 10 bp/lado, neto = bruto − 2·bp·rotación. Entrada al cierre de D+1 (lag=1), salida al
  cierre `hold` barras después. Sin apalancamiento (exposición ≤ 1).
- Multiplicidad: con ~35 pruebas en DEV, el Sharpe "esperado del mejor por suerte" es del orden de
  0.6-0.7 (error estándar de un Sharpe a 12 años ≈ 0.3). Por eso el Sharpe DEV de T20 (0.58) NO es
  evidencia por sí solo; la evidencia es que se sostuvo en TEST (0.61) con la misma forma. Aun así,
  la mejora de T20 sobre PROD en TEST es modesta; la mejora grande es en DEV, que es el período que
  contiene 2008-2009 y el crash de momentum de 2009.

## 2. Qué se probó y qué se aprendió (DEV 2004-2015, neto 10 bp/lado)

| Palanca (una a la vez sobre PROD) | bruto | neto | Sharpe | maxDD | rotación/paso | Lección |
|---|---|---|---|---|---|---|
| PROD (hold 5, mom90/vol63, gate binario) | 7.44 | 3.33 | 0.28 | −38.2 | 38.7 | el coste se come el 55 % del bruto |
| hold 10 | 8.92 | 6.21 | 0.46 | −36.6 | 50.1 | la barrera principal es la rotación semanal |
| hold 20 (una sola fase) | 5.94 | 4.31 | 0.35 | −48.5 | 61.8 | hold largo sin tramos = ruleta de fase (§3) |
| buffer 2 (mantener si rank ≤ 2n) | 6.13 | 3.41 | 0.29 | −40.7 | 25.8 | baja rotación pero baja bruto igual |
| sin gate de régimen | 6.24 | 1.83 | 0.19 | −60.2 | 42.1 | el gate vale ~+1.5 pp y −22 pp de DD en DEV |
| vol-targeting (15 %) sobre mom90 | 5.10 | 1.38 | 0.17 | −48.8 | 35.8 | con señal rápida, el vol-target hace daño |
| inverse-vol weights | 6.98 | 2.80 | 0.26 | −33.3 | 39.5 | menos DD, menos retorno; neutral |
| sin boost/strict | 8.27 | 4.50 | 0.36 | −34.9 | 35.2 | el boost corto NO paga en 2004-2015 |
| mom 12-1 | 7.71 | 4.13 | 0.34 | −42.3 | 33.5 | |
| mom 6-1 | 9.17 | 5.11 | 0.39 | −38.7 | 37.6 | |
| mom 12-7 (Novy-Marx 2012) | 8.15 | 4.18 | 0.33 | −52.0 | 37.2 | solo, no; con hold largo + vol-target, sí (abajo) |

Finalistas pre-registrados y sus ajustes (un botón por finalista, como se anunció en el board):

| Config | bruto | neto | Sharpe | maxDD | rotación | Nota |
|---|---|---|---|---|---|---|
| F1 = buffer 2 + hold 10 | 7.64 | 5.64 | 0.43 | −35.3 | 37.3 | |
| F2 = F1 + vol-target | 5.60 | 3.73 | 0.33 | −44.4 | 35.5 | vol-target daña con mom90 |
| F3 = F2 + mom 12-1 | 7.53 | 6.03 | 0.47 | −40.8 | 27.9 | |
| F3 con 12-7, hold 20, vol de la cesta (basket63) | 9.54 | 8.35 | 0.68 | −23.4 | 43.8 | **pero** fase+5: 3.86, fase+10: 3.58 |
| **T20** = 12-7, hold 20 en 4 tramos, buffer 2, vol-target basket63 | 8.53 | 7.31 | 0.58 | −28.6 | 11.2 | fase+0/+5/+10: 7.31/7.30/7.22 |
| T20 con gate en vez de vol-target | 7.59 | 6.29 | 0.49 | −33.0 | 12.1 | el vol-target aporta +1 pp y −4 pp DD |
| T20 con mom90 en vez de 12-7 | 6.52 | 5.25 | 0.44 | −38.1 | 11.9 | la señal 12-7 es la que trabaja |
| T10 = 12-7, hold 10 en 2 tramos | 9.39 | 7.60 | 0.60 | −37.6 | 16.4 | |

Descomposición del candidato (DEV): sin tramos, hold 20 con gate binario 4.7 %, quitando el boost
3.8 %, cambiando gate por vol-target 7.2 %. El vol-targeting **con señal lenta** es lo que convierte
el hold largo en algo utilizable; sobre la señal semanal de producción lo empeora.

## 3. Por qué tramos (y por qué el resultado de hold 20 "a secas" era falso)

Un hold de 20 barras rebalanceado de una vez depende del día de arranque: la misma configuración dio
8.19 % o 3.58 % neto según se empezara en la barra 280 o en la 290. Eso no es una estrategia, es
una fase. Jegadeesh & Titman (1993) resuelven exactamente esto con **carteras superpuestas**: K
tramos de capital, cada uno mantenido `hold` barras y renovado en rotación cada `hold/K` barras.
Con K=4 y hold=20 el paso vuelve a ser **5 barras — el ciclo semanal actual** — y el resultado es
invariante a la fase por construcción (7.31 / 7.30 / 7.22). La rotación anual es la de un hold de
20 barras (≈ 11 % del libro por semana frente a 39 % hoy).

## 4. La única mirada a TEST (2016-2026) y la muestra completa

| Config | ciclos | bruto | neto | Sharpe | maxDD | rotación | exposición |
|---|---|---|---|---|---|---|---|
| PROD | 535 | 11.87 | 7.52 | 0.55 | −27.3 | 39.4 | 91 |
| F1 (buffer 2, hold 10) | 267 | 10.95 | **8.78** | 0.68 | −20.7 | 39.5 | 91 |
| T20 | 535 | 9.22 | 7.92 | 0.61 | −26.7 | 11.9 | 86 |
| T10 | 535 | 8.19 | 6.22 | 0.50 | −22.7 | 18.2 | 86 |

Muestra completa 2004-2026 (1084 pasos semanales):

| Config | bruto | neto | Sharpe | maxDD | rotación |
|---|---|---|---|---|---|
| PROD (harness `--oos`, referencia) | 9.68 | 5.72 | ~0.41 | −39.3 | 36.5 |
| PROD (lab, misma lógica) | 9.60 | 5.38 | | | |
| **T20** | 8.87 | **7.61** | 0.60 | −28.6 | 11.6 |
| T10 | 8.80 | 6.92 | 0.55 | −37.6 | 17.3 |

Lectura honesta:
- 2016-2026 fue fácil para momentum: todo mejora respecto a DEV. PROD es la que más mejora
  (3.3 → 7.5), lo que dice que el problema de producción es el período difícil, no el fácil.
- **F1 gana TEST en neto** (8.78) y en DD (−20.7) con un cambio mínimo (ciclo de 10 barras en vez
  de 5, buffer 2). Pero en DEV hizo 5.64 y no se probó su robustez a la fase (es un hold 10 de una
  sola fase; el análogo con 12-7 osciló 6.93 / 5.10 entre fases). Es el candidato "barato".
- **T20 es el candidato robusto**: es el único con neto ≥ 7 % en DEV, TEST y ALL, con la rotación
  más baja y el mejor DD de la muestra completa. Su mejora sobre PROD en TEST es pequeña (+0.4 pp);
  su mejora en la muestra completa es de +2.2 pp de neto y +0.2 de Sharpe.

Sensibilidad a costes (aproximada, neto ≈ bruto − 2·bp·rotación anual; producción opera un universo
Russell donde 10 bp/lado es optimista — TASK-327 lo está cuantificando):

| Config (ALL salvo indicado) | 5 bp | 10 bp | 20 bp |
|---|---|---|---|
| PROD | 7.7 | 5.7 | 1.8 |
| T20 | 8.2 | 7.6 | 6.4 |
| F1 (solo TEST) | 9.9 | 8.8 | 6.6 |
| PROD (solo TEST) | 9.7 | 7.5 | 3.2 |

A 20 bp/lado producción gana 1.8 %/año y T20 6.4 %: la rotación es la variable de supervivencia
en el universo real, no un detalle.

In-sample 2020-2026 (503 miembros actuales, sesgo de supervivencia total; solo como cotejo):
PROD 20.1 / 15.3 neto, Sharpe 0.91, DD −21.9; **T20 17.7 / 16.4 neto, Sharpe 1.16, DD −12.3**;
T10 15.9 / 13.9. T20 también domina en neto, Sharpe y DD en el panel que Lucas ve todos los días.

## 5. Lo que aportó el corpus legacy de OneDrive

Leído: `COMPASS_IMPROVEMENTS_v82.md`, manifiestos V7/V8, `EXP40/41_SUMMARY.md`,
`cost_decomposition.csv`, `conditional_hold_sweep.csv`, `docs/plans/2026-03-01-compass-v84-
improvement-decisions.md`, `2026-03-05-multi-lookback-ensemble-design.md`,
`COMPASS_RUSSELL2000_EXPANSION_PLAN.md`. `exp42_comparison_v82_v83.txt` está truncado a la
cabecera (7 líneas), el resultado del "framework 666" no sobrevivió.

Lo que confirma el diagnóstico:
- La patología del v8.2 ya estaba escrita: 90.5 % de las salidas eran `Hold_Expired` a 5 días, el
  régimen era binario y el stop de cartera llegaba tarde. Es exactamente lo que el lab mide como
  "la rotación semanal se come el 55 % del bruto" y "el gate binario cuesta retorno".
- **Corrección de supervivencia legacy: −4.56 pp** (18.46 → 13.90 % CAGR en 2000-2026) y la
  descomposición de costes (señal pura 16.94 % → MOC 14.02 → +slippage 12.22 → +comisiones
  11.54 %). Aplicando ambas al mismo motor se llega a ~7 % neto — el mismo orden que mide el lab
  hoy sobre un panel PIT. Los 13.90 % del legacy no eran netos de costes; el 11.31 % de 1996-2026
  llevaba −63 % de DD. No hay un "10 % neto" escondido en el pasado del proyecto.
- El documento v8.4 (2026-03-01) ya imponía pre-registro, criterios de kill y deflación del Sharpe
  por 75 experimentos; este lab siguió la misma disciplina (DEV/TEST, una mirada).

Lo que sí quedó fuera y se probó (§6): el **ensemble multi-lookback** (EXP56: 21/63/126/252 con
skip 5, rank-average, +0.85 pp CAGR y −3 pp DD sobre 750 acciones 2000-2026). Es la única idea del
corpus con resultado positivo medido que no estaba en mis palancas.

Lo que quedó fuera y NO merece prueba: crowding con AUM de MTUM (el propio legacy lo difirió a
2028 por intestable), VIX-compression flag (falsa alarma > 60 % estimada), HAR-RV para la
recuperación tras stop (no hay stop de cartera en HYDRA local).

## 6. Ensemble multi-lookback (DEV solamente — corrió después de mirar TEST)

Especificación tomada tal cual del legacy (EXP56): momentum a 21/63/126/252 barras con skip de 5,
cada uno dividido por vol63, percentil dentro del universo elegible del día, promedio de los cuatro
(un nombre necesita los cuatro). Sin ajustar nada. DEV 2004-2015, neto 10 bp/lado:

| Config | bruto | neto | Sharpe | maxDD | rotación | vs. su base |
|---|---|---|---|---|---|---|
| PROD + ensemble | 8.01 | 3.62 | 0.31 | −35.9 | 41.2 | PROD 3.33 → +0.3 pp |
| F1 + ensemble (buffer 2, hold 10) | 8.64 | 6.47 | 0.52 | −24.4 | 40.3 | F1 5.64 → +0.8 pp, DD −35 → −24 |
| T20 + ensemble (en vez de 12-7) | 7.24 | 5.83 | 0.48 | −31.9 | 13.1 | T20 7.31 → −1.5 pp |

Lectura: el ensemble ayuda algo a los diseños de ciclo corto (es una señal más lenta que mom90, y
eso es lo que les falta) y **empeora T20**, que ya tiene la señal lenta correcta (12-7) y pierde al
mezclarla con 21 y 63 barras. Es evidencia DEV-only y no cambia el finalista. Si algún día se
optara por la vía B (F1), el ensemble sería lo primero a verificar en TEST — con la advertencia
de que sería una segunda mirada.

## 7. Diseño candidato: HYDRA v9 "T20" (sin aplicar)

Cambios respecto al SPEC v1.2, y solo estos:

1. **Señal:** `mom_12_7 = close[t−126] / close[t−252] − 1`, dividido por vol63 anualizada (igual
   que hoy). Boost corto y filtro estricto se mantienen como están (en DEV su aporte es negativo
   en 2004-2015 y positivo en el compuesto con vol-target: 7.2 → 7.3; no se toca por
   principio de mínimo cambio).
2. **Horizonte:** cada nombre recomendado se mantiene **20 barras**. La cartera son **4 tramos de
   25 % del capital**; cada semana (paso de 5 barras, el ciclo actual) se cierra el tramo abierto
   hace 20 barras y se abre uno nuevo con la lista del día.
3. **Buffer de mantenimiento (Novy-Marx & Velikov 2016):** un nombre del tramo que se renueva se
   conserva si sigue en el top `2·n` del ranking del día; solo se sustituyen los que caen fuera.
4. **Exposición:** el gate binario de régimen se sustituye por **vol-targeting**: exposición del
   tramo = `min(1, 0.15 / vol63_anualizada_de_la_cesta_equiponderada)`; el resto en cash. Sin
   apalancamiento. El régimen rico sigue calculándose y sigue moviendo `dynamic_count`.
5. Todo lo demás igual: filtros prácticos, `dynamic_count` 6-28, sector cap 5 GICS, downtrend gate.

Impacto operativo (lo que cambia para Lucas): cada semana la lista recomendada es la del tramo que
se renueva (≈ 16 nombres, como hoy), pero las posiciones abiertas son las de 4 semanas superpuestas
— **≈ 30 nombres distintos en cartera de media (29.6 en DEV) frente a ≈ 16 hoy**, cada uno con la
mitad del peso que tiene ahora. Es el coste operativo real del diseño: más líneas en el broker,
menos operaciones (≈ 2-3 cambios por semana en vez de ≈ 6). `core/portfolio_state.py` (TASK-329,
Grok) es la pieza que hace posible saber qué tramo vence.

Piezas de producción que tocaría (estimación, todas con test):
`core/signals.py` (nueva ventana), `config.py` (HOLD_BARS=20, TRANCHES=4, BUFFER=2.0,
TARGET_VOL=0.15), `screener.py` (estado de tramos + exposición), `core/tracking.py` (horizonte 20),
`log_cycle_positions.py`, `pine/HYDRA_Screener.pine` (paridad de la ventana), SPEC §4.1/§4.6/§6,
`test_spec_compliance.py`. Sugerencia: detrás de un interruptor `ALGO_VERSION = "v8.4" | "v9"` y
correr ambos en paralelo en `history/` durante un trimestre antes de retirar v8.4.

## 8. Literatura usada

Jegadeesh & Titman (1993) carteras superpuestas · Novy-Marx (2012) horizonte intermedio 12-7 ·
Moreira & Muir (2017) volatility-managed portfolios · Barroso & Santa-Clara (2015) momentum
risk-managed · Daniel & Moskowitz (2016) momentum crashes · Novy-Marx & Velikov (2016) costes y
buffers · Frazzini, Israel & Moskowitz (2012) costes reales de momentum · Israel & Moskowitz (2013)
momentum por tamaño · Bailey & López de Prado (2014) deflated Sharpe.

## 9. Decisión que queda en manos de Lucas

El encargo pedía ≥ 10 % anualizado y el resultado honesto es 7.6 % neto / 8.9 % bruto en 2004-2026
(16.4 % neto en 2020-2026). Opciones, por orden de mi recomendación:

- **A. Implementar T20 como v9 detrás de interruptor** y correrlo en paralelo con v8.4 durante un
  trimestre. Es la mejora robusta y la que sobrevive a costes reales. No llega al 10 % neto en el
  panel honesto y lo digo tal cual.
- **B. Cambio mínimo F1** (ciclo de 10 barras + buffer 2, todo lo demás igual): gana TEST
  (8.8 % neto) pero es más débil en DEV y no se probó su robustez a la fase. Menos trabajo, menos
  confianza.
- **C. No cambiar scoring** hasta tener costes por tamaño (TASK-327) y, si Lucas compra un
  histórico Russell (Norgate), medir sobre el universo real. El 10 % sobre S&P 500 PIT a 10 bp no
  existe con esta familia de señales; sobre Russell no se puede medir hoy.

Yo ejecuto A si Lucas lo confirma; el lab, este documento y la cola de tareas ya están listos para
ello.
