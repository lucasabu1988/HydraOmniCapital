# HYDRA v9 — Cartera de mangas: diseño y pre-registro

**Autor:** Claude (architect) · **Fecha:** 2026-09-06
**Decisión de Lucas:** opción A — dejar de optimizar una sola manga y construir una cartera de mangas poco
correlacionadas: **T20** (momentum cross-seccional en acciones, ya medido) + **trend-following multi-activo en
ETFs** + **cash en T-bill**.
**Por qué esto y no otra cosa:** lo único que subió el Sharpe de forma grande en la historia del proyecto fue
combinar mangas (HYDRA v2 legacy: 0.85 → 1.04, DD −32 → −23). La manga ETF se mide honestamente con datos
gratis (los ETFs no tienen sesgo de supervivencia), tiene rotación mínima y correlación baja con acciones US
cuando importa (2008, 2022).

---

## 1. Pre-registro de la manga ETF (escrito ANTES de ver ningún resultado)

**Universo (10 ETFs, fijo, sin selección posterior):** SPY, QQQ, IWM, EFA, EEM, TLT, IEF, GLD, DBC, VNQ.
Cada ETF entra en el universo cuando tiene 252 barras de historia (DBC en 2007, GLD/VNQ en 2005-06, resto
desde 2004). Ampliaciones del universo = nuevo pre-registro.

**Señal (Moskowitz, Ooi & Pedersen 2012; Antonacci 2014):** retorno total 12 meses (252 barras) menos el
T-bill acumulado del mismo período > 0 → largo; si no → T-bill. Sin skip (la literatura TSMOM usa los 12
meses completos). Una sola variante de señal alternativa pre-registrada: precio > SMA(200) (Faber 2007).

**Pesos:** inverse-vol (vol63) normalizado sobre **todo** el universo elegible, de modo que la parte de los
ETFs "apagados" queda en T-bill (exposición ≤ 1, sin apalancamiento). Variante pre-registrada: 1/N.

**Ritmo:** misma maquinaria que T20 — hold 20 barras en 4 tramos, paso 5 barras (invariante a la fase; la
manga se evalúa semanalmente en el mismo calendario que T20).

**Costes:** 5 bp/lado (ETFs líquidos); sensibilidad a 10 bp.

**Combinación con T20 (pre-especificada):** (i) 50/50 fijo rebalanceado cada paso; (ii) paridad de riesgo
inverse-vol sobre los últimos 63 pasos de cada manga. Cash de ambas mangas en T-bill (`cash_yield=True`).
El veredicto anterior se dio a cash 0 %; aquí el cash es una manga real y se contabiliza.

**Criterios de éxito (pre-registrados):**
- Manga ETF sola: Sharpe ≥ 0.5 en DEV y en TEST, maxDD ≤ −25 %.
- Cartera: Sharpe ≥ 0.85 en la muestra completa, maxDD mejor que T20 solo (−28.6 %), neto ≥ 8.5 %.
- Correlación semanal T20–ETF < 0.6.
- **Kill:** si la manga ETF tiene Sharpe < 0.3 en DEV, no se combina y se documenta.

**Multiplicidad:** 2 señales × 2 esquemas de pesos = 4 configuraciones de manga, 2 combinaciones. Se
reportan todas; la primaria es TSMOM-12m + inverse-vol + 50/50. DEV 2004-2015 / TEST 2016-2026 como siempre;
TEST se mira una vez para las 4 + 2.

## 2. Resultados (una mirada; `experiments/sleeve_lab.py`, calendario del panel PIT, lag 1)

### 2.1 Manga ETF sola (neto 5 bp/lado, cash en T-bill)

| Config | Período | bruto | neto | Sharpe | maxDD | rotación/sem | exposición | posiciones |
|---|---|---|---|---|---|---|---|---|
| **ETF (TSMOM-12m, inverse-vol)** primaria | DEV | 6.67 | 6.57 | **0.94** | **−7.2** | 1.9 | 72 | 6.9 |
| | TEST | 5.66 | 5.56 | 0.88 | −12.4 | 2.0 | 60 | 6.2 |
| | ALL | 6.17 | 6.07 | 0.91 | −12.4 | 2.0 | 66 | 6.5 |
| ETF 1/N | ALL | 6.77 | 6.69 | 0.83 | −14.6 | 1.4 | 67 | |
| ETF SMA200, inverse-vol | ALL | 6.24 | 6.11 | 0.92 | −11.1 | 2.5 | 70 | |
| ETF SMA200, 1/N | ALL | 6.79 | 6.69 | 0.85 | −12.8 | 1.9 | 69 | |
| ETF primaria a 10 bp | ALL | 6.17 | 5.96 | 0.89 | −12.4 | | | |

Las cuatro variantes dan lo mismo (6.1-6.7 % neto, Sharpe 0.83-0.92, DD −11 a −15): la manga es robusta a la
señal y a los pesos, y a los costes (2 % de rotación semanal, 10 bp casi no se notan). **Criterios de la manga:
cumplidos** (Sharpe ≥ 0.5 en DEV y TEST, DD ≤ −25 %). Referencia T20 con cash en T-bill: 7.80 neto, Sharpe
0.61, DD −28.0.

### 2.2 Correlación y cartera

Correlación semanal T20–ETF: **0.71** (DEV 0.66, TEST 0.76). Criterio < 0.6: **no cumplido**. Seis de los diez
ETFs son renta variable y T20 es 86 % largo acciones; la diversificación real viene de TLT/IEF/GLD/DBC y del
34 % medio en T-bill de la manga.

| Cartera | Período | neto | Sharpe | maxDD |
|---|---|---|---|---|
| T20 solo (referencia) | ALL | 7.80 | 0.61 | −28.0 |
| **50/50** | DEV | 7.14 | 0.77 | −13.9 |
| | TEST | 7.01 | 0.74 | −19.6 |
| | ALL | 7.08 | 0.76 | −19.6 |
| Paridad de riesgo (peso T20 medio 0.33, 0.20-0.50) | DEV | 6.98 | 0.84 | −9.6 |
| | TEST | 6.44 | 0.80 | −16.7 |
| | ALL | 6.71 | 0.82 | −16.7 |

Criterios de cartera: DD mejor que T20 ✓ (−19.6 / −16.7 vs −28.0); Sharpe ≥ 0.85 ✗ (0.76 / 0.82); neto ≥ 8.5 ✗
(7.1 / 6.7). **Cumple uno de tres.**

Por años (neto %): 2008 T20 −18.5 / ETF +5.2 / 50-50 −6.9; 2018 −10.4 / −4.7 / −7.4; 2020 −6.8 / +1.1 / −2.6;
2022 +2.5 / −4.6 / −0.9. La manga ETF hace exactamente lo que se le pidió en los años malos de acciones; el
precio es 2013 (26.6 → 17.0) y 2024 (28.4 → 18.8).

### 2.3 Lectura honesta

- **La tesis de mangas se confirma en dirección**: Sharpe 0.61 → 0.76-0.82, DD casi a la mitad. Es la mayor
  mejora de calidad de retorno medida en el proyecto sin tocar la señal de acciones.
- **No fabrica retorno.** La cartera es una recta entre T20 (7.8 %, vol ~13 %) y ETF (6.1 %, vol ~7 %); cualquier
  peso queda entre 6 y 8 % neto. Con Sharpe ~0.8 y sin apalancamiento, el retorno máximo sin apalancar es el de
  la manga más rentable. **El 10 % neto sólo aparece apalancando la cartera ~1.3× con financiación barata**
  (el legacy midió box spreads a SOFR+20 pb: +1.25 pp sobre margen bróker). Lucas fijó `LEVERAGE_MAX = 1.0`;
  lo dejo escrito y no lo propongo.
- La correlación 0.71 dice que el siguiente candidato a manga no debería ser otra cosa larga en acciones US.
  Las mangas con correlación realmente baja y datos honestos gratis son: bonos/oro/materias primas ya están;
  faltaría **mean-reversion de corto plazo** (el Rattlesnake legacy: correlación 0.38 con COMPASS, Sharpe 0.93
  solo, 51 % del tiempo en cash) — es la única manga adicional con precedente medido dentro del proyecto.

### 2.4 Recomendación

1. **Operar la cartera 50/50 (o paridad de riesgo) en lugar de T20 solo.** Mismo retorno esperado ±1 pp,
   con la mitad de drawdown: para una cuenta real es la diferencia entre aguantar 2008/2020 y abandonar.
   La manga ETF son 7 posiciones, 2 % de rotación semanal, y sus datos no tienen ninguno de los problemas
   de las acciones.
2. **Siguiente manga a pre-registrar: mean-reversion de corto plazo en large caps** (regla Rattlesnake legacy
   tal cual: caída ≥ 8 % en 5 días, RSI(5) < 25, por encima de SMA200; salida +4 % / −5 % / 8 días), medida
   sobre el mismo panel PIT. Si su correlación con T20+ETF es < 0.4 como en el legacy, la cartera de tres
   puede acercar el Sharpe a 1.0 — y ahí sí, la conversación sobre 1.2-1.3× con financiación barata deja
   de ser académica. Sin ella, 10 % neto sin apalancar no está en esta familia de mangas.
3. Producción: `sleeves/etf_trend.py` (Grok, tras 330-335), tramos vía `portfolio_state`, tracking v2 mide
   las dos mangas por separado y la cartera.

## 4. Manga 3 — mean-reversion de corto plazo: pre-registro (escrito antes de ver ningún resultado)

**Decisión de Lucas (2026-09-06):** "proceder" con la manga 3 tras los resultados de §2.

**Regla:** la del Rattlesnake v1.0 legacy, sin retocar (MANIFESTO §3.2, `hydra_soul.md`):
- Universo: el legacy usaba el S&P 100 actual (sesgado). Aquí: **los 100 miembros PIT del S&P 500 con mayor
  dollar-ADV a 20 días cada día** — el proxy honesto del OEX.
- Entrada (señal al cierre de D, ejecución al cierre de D+1): retorno 5 días ≤ −8 %, RSI(5) Wilder < 25, cierre >
  SMA200 de la acción; régimen: SPY > SMA200 → hasta 5 posiciones, SPY < SMA200 → hasta 2; **VIX > 35 bloquea
  entradas**. Si hay más candidatos que huecos, entran los de menor RSI.
- Tamaño: 20 % del capital de la manga por posición; lo no invertido, en T-bill.
- Salida (evaluada y ejecutada al cierre): beneficio ≥ +4 %, pérdida ≤ −5 %, o 8 días de tenencia. Sin
  intradía: los stops se ven al cierre, así que la pérdida real puede ser algo mayor que −5 %.
- Costes: 10 bp/lado (acciones, como T20).

**Variantes pre-registradas (2):** sin filtro VIX; universo top-200 por ADV. Se reportan las tres.

**Agregación:** la manga es diaria; para correlaciones y cartera se compone su curva diaria en la misma
rejilla de 5 barras y con la misma convención de entrada (cierre t+1 → cierre t+6) que T20 y ETF.

**Criterios de éxito:** manga sola Sharpe ≥ 0.5 en DEV y TEST, maxDD ≤ −20 %; correlación semanal con la
cartera 50/50 (T20+ETF) < 0.4; cartera de tres (1/3 cada una, y paridad de riesgo) Sharpe ≥ 0.85, neto ≥ 7 %,
DD mejor que −19.6 %. **Kill:** Sharpe < 0.3 en DEV → no se combina.

**Multiplicidad acumulada en esta línea:** 4 mangas ETF + 3 MR + 4 combinaciones. TEST se mira una vez por manga.

### 4.1 Resultados

PENDIENTE.

## 3. Camino a producción (si pasa)

`hydra_screener_local/sleeves/etf_trend.py` (señales mensuales, salida JSON junto a la lista de acciones),
`daily.py` imprime las dos mangas, `core/portfolio_state.py` (TASK-329) lleva los tramos, tracking v2 mide
ambas. Paper en `history/` desde el día siguiente a la aprobación.
