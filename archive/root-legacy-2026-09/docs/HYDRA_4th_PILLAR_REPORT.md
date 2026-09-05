# HYDRA 4th Pillar — Informe Consolidado

## Contexto

5 agentes analizaron durante 30 minutos en paralelo:
1. **Analista de drawdowns** — estudió cuándo y por qué HYDRA falla
2. **Investigador de factores** — buscó premiums descorrelacionados
3. **Analista de correlaciones** — corrió backtests reales de 16 ETFs contra HYDRA
4. **Estratega de hedge funds** — investigó qué usan AQR, Renaissance, Man AHL
5. **Analista de experimentos** — extrajo lecciones de los 7 experimentos fallidos (EXP65-67)

---

## Diagnóstico: ¿Cuándo falla HYDRA?

| Período | Drawdown | Duración | Contexto |
|---------|----------|----------|----------|
| 2001-2002 | -19.5% | 24 meses | Dot-com bust |
| 2008-2009 | -21.7% | 20 meses | GFC |
| 2011 | -19.3% | 22 meses | Eurozone crisis, **peor año relativo vs SPY (-18.8%)** |
| 2018 Q4 | -21.4% | 5 meses | Fed tightening, crash Dec 24 |
| 2020 | -18.3% | 3 meses | COVID |
| 2022 | -16.5% | 10 meses | Inflación + tasas |

**Patrón**: Bear markets largos y grinding son peores que crashes cortos. HYDRA se recupera rápido de V-shapes (2020: 3 meses) pero sufre en bears prolongados (2011: 22 meses).

**Meses más débiles**: Febrero-Marzo y Agosto-Septiembre.

---

## Por qué fallaron los 7 experimentos anteriores

Los agentes identificaron 3 fallas estructurales comunes:

1. **Costo de oportunidad**: Reemplazar HYDRA (que tiene retorno positivo esperado de +5-9% por período) con un activo alternativo requiere que el alternativo supere ese benchmark, no cero.

2. **Señal imprecisa**: Bombings y desastres no predicen dirección del instrumento alternativo. El petróleo baja después de bombardeos el 58% de las veces.

3. **Contaminación de correlación**: Defense stocks, construction stocks y petróleo están correlacionados con equities. Reemplazar HYDRA con otro equity-correlated es redundante.

**Principio clave**: El 4to pilar debe ser ADITIVO (usar cash disponible), no SUSTITUTIVO (liquidar HYDRA).

---

## Análisis de Correlaciones (datos reales 2004-2026)

Blend: 85% HYDRA + 15% Alternativo

| Rank | Ticker | Nombre | Corr | Corr en DD | Sharpe Blend | Delta Sharpe | Reducción DD |
|------|--------|--------|------|-----------|-------------|-------------|-------------|
| 1 | **GLD** | Oro | +0.09 | +0.09 | 0.997 | **+0.101** | -12.9% |
| 2 | **CTA** | Managed Futures | -0.01 | -0.05 | 1.355 | **+0.094** | -12.7% |
| 3 | **TLT** | Bonos 30Y | -0.18 | -0.20 | 0.964 | **+0.065** | **-20.1%** |
| 4 | **IEF** | Bonos 10Y | -0.18 | -0.20 | 0.948 | +0.049 | -18.0% |
| 5 | **DBMF** | Managed Futures iM | +0.30 | +0.29 | 1.300 | +0.043 | -10.1% |
| 6 | **TIP** | TIPS Inflación | -0.05 | -0.05 | 0.941 | +0.041 | -10.6% |
| 7 | **KMLM** | KFA Mt Lucas MF | +0.03 | -0.03 | 1.248 | +0.041 | -12.4% |
| 8 | **BTAL** | Anti-Beta L/S | -0.27 | -0.27 | 1.101 | +0.037 | **-14.8%** |
| 9 | **BIL** | T-Bills | -0.06 | -0.09 | 0.887 | +0.014 | -14.0% |
| 10 | **HYG** | High Yield Bonds | +0.38 | +0.40 | 0.914 | +0.013 | -1.2% |
| 11 | VNQ | REITs | +0.39 | +0.42 | 0.901 | -0.017 | +20.6% peor |
| 12 | DBC | Commodities | +0.30 | +0.33 | 0.842 | -0.034 | +21.6% peor |
| 13 | GSG | iShares Comm | +0.28 | +0.31 | 0.825 | -0.087 | +31.5% peor |

**Hallazgo clave**: GLD, CTA y TLT son los únicos que mejoran TANTO el Sharpe como reducen el drawdown.

---

## Las 10 Opciones

### TIER 1 — Los más prometedores

#### Opción 1: Cross-Asset Trend Following (estilo Man AHL / Winton)
- **Qué es**: Aplicar señal de tendencia (precio > SMA 200d) a 5 ETFs: SPY, EFA, TLT, GLD, DBC
- **Instrumentos**: SPY, EFA, TLT, GLD, DBC
- **Regla**: Cada 5 días, comprar los que estén arriba de su SMA200. Si ninguno, cash (SHY).
- **CAGR esperado**: 7-10% standalone, Sharpe 0.60-0.90
- **Correlación con momentum**: +0.2
- **En crashes de momentum**: Bonds y gold suben → el pilar rota hacia ellos automáticamente
- **Por qué #1**: Crisis alpha real. Multi-asset. Mismo ciclo de 5 días que HYDRA. Simple.

#### Opción 2: Low Volatility / Minimum Variance
- **Qué es**: Comprar acciones de baja beta que académicamente superan en riesgo-ajustado
- **Instrumentos**: USMV o SPLV
- **Regla**: Asignación permanente. Si SPY vol 21d > 20% → 100% USMV. Si < 12% → SPLV. Stop -6%.
- **CAGR esperado**: 8-10%, Sharpe 0.65-0.85
- **Correlación con momentum**: -0.3 a -0.4 (la más negativa entre factores equity)
- **En crashes de momentum**: Cae 5-8% vs momentum -40%. El mejor colchón dentro de equities.

#### Opción 3: Quality / Profitabilidad (factor AQR)
- **Qué es**: Acciones con alto ROE, bajo endeudamiento, earnings estables
- **Instrumentos**: QUAL (iShares Quality Factor)
- **Regla**: Asignación permanente. Stop si QUAL cae >8% del high de 63d → rotar a SHY.
- **CAGR esperado**: 8-11%, Sharpe 0.55-0.75
- **Correlación con momentum**: +0.1 a +0.2 (casi ortogonal)
- **En crashes de momentum**: Flat o ligeramente negativo. Quality es "seguro de crash de momentum."

### TIER 2 — Fuertes candidatos

#### Opción 4: Oro (asignación permanente con trend filter)
- **Instrumentos**: GLD
- **Regla**: Si GLD > SMA200 → 80% GLD / 20% GDX. Si < SMA200 → 50% GLD / 50% SHY. Nunca 0%.
- **CAGR esperado**: 6-9%, Sharpe 0.35-0.55
- **Dato empírico**: **Mejor Sharpe delta en blend real (+0.101)**. Correlación +0.09.
- **En crashes**: 2008 positivo, 2011 +10%, 2020 +25%.

#### Opción 5: Bonos 30Y con trend filter
- **Instrumentos**: TLT, IEF, SHY
- **Regla**: Si TLT > SMA200 → TLT. Si solo IEF > SMA200 → IEF. Si ninguno → SHY.
- **CAGR esperado**: 4-6%, Sharpe 0.40-0.60
- **Dato empírico**: **Mayor reducción de drawdown (-20.1%)**. Correlación -0.18.
- **Problema**: Post-2021 los bonos se correlacionaron positivamente con equities (inflación).

#### Opción 6: Equity Carry / Shareholder Yield
- **Instrumentos**: SYLD (Cambria Shareholder Yield), DVY, VIG
- **Regla**: Cada 21d, rankear por retorno ajustado por riesgo 63d. Top 2. Si todos < SMA200 → SHY.
- **CAGR esperado**: 9-12%, Sharpe 0.50-0.70
- **Correlación con momentum**: +0.05 (casi cero, validado por AQR)
- **En crashes**: Moderadamente negativo pero con floor por income.

### TIER 3 — Viables con caveats

#### Opción 7: Managed Futures directo (DBMF o CTA)
- **Instrumentos**: DBMF (replica SocGen CTA Index) o CTA (Simplify)
- **Regla**: Asignación permanente del 15%.
- **CAGR esperado**: 5-10%, Sharpe 0.50-0.80
- **Dato empírico**: CTA tiene Sharpe blend de 1.355 (el más alto), pero track record corto (desde 2022).
- **En crashes**: 2008 CTAs +13%, 2022 +20%+. La definición de "crisis alpha."
- **Caveat**: DBMF tiene correlación +0.30 (más alta de lo ideal). KMLM tiene +0.03 (mejor).

#### Opción 8: Deep Value (anti-momentum puro)
- **Instrumentos**: RPV (S&P 500 Pure Value), QVAL, VTV
- **Regla**: Si RPV/SPY relative strength positiva 21d y 63d → RPV. Si no → VTV. Stop -10% → SHY.
- **CAGR esperado**: 8-12%, Sharpe 0.40-0.60
- **Correlación con momentum**: -0.5 a -0.7 (la más negativa de todos — el "yin y yang" de AQR)
- **En crashes de momentum**: Value sube. Pero tuvo una "década perdida" 2010-2020.

#### Opción 9: Sector Rotation Defensivo
- **Instrumentos**: XLV (Healthcare), XLP (Staples), XLU (Utilities) + sectores cíclicos
- **Regla**: Top 3 sectores por momentum 63d ajustado por vol. Si SPY < SMA200 → solo defensivos.
- **CAGR esperado**: 10-14%, Sharpe 0.60-0.90
- **Correlación con momentum**: +0.3 a +0.4 (overlap con pilar existente)
- **Caveat**: Más overlap con Momentum de lo ideal.

#### Opción 10: Volatility Risk Premium (vender premium)
- **Instrumentos**: SVXY (inverse VIX 0.5x) + SHY
- **Regla**: Si VIX < 20 y contango → 80% SVXY. Si VIX 20-30 → SHY. Si > 30 → SHY. Stop -12%.
- **CAGR esperado**: 8-15%, Sharpe 0.50-0.80
- **Correlación con momentum**: +0.1
- **Caveat**: Tail risk real aunque mitigado por reglas. Volmageddon 2018 destruyó XIV.

---

## Recomendación del Consenso de Agentes

Los 5 agentes convergieron en la misma conclusión:

> **Managed Futures / Cross-Asset Trend Following es el 4to pilar óptimo.**

Razones:
1. Es el único asset class con **crisis alpha comprobado** (gana cuando todo cae)
2. Correlación cercana a cero con equity momentum
3. AQR, Man AHL, Winton, Bridgewater todos lo usan como diversificador core
4. Implementable con ETFs (DBMF, KMLM, CTA) o con la regla simple de SMA200 sobre 5 ETFs
5. Funciona en el ciclo de 5 días de HYDRA
6. 15% de asignación ($15-25K) es suficiente para impacto significativo

**Runner-up**: Oro (GLD) tiene el mejor delta de Sharpe empírico (+0.101) y es el más simple de implementar.

**Combo ideal**: 10% Cross-Asset Trend + 5% Gold = replica el modelo AQR de 4 factores dentro de las restricciones de HYDRA.

---

## Principios de Diseño (de los experimentos fallidos)

1. **ADITIVO, no sustitutivo** — usar cash libre, no liquidar HYDRA
2. **Solo instrumentos de beta cero o negativo** — no más equities correlacionados
3. **Activación rara** (max 3-5 veces/año) o asignación permanente pequeña
4. **Hold corto** (5-10 días) si es táctico
5. **El trigger debe predecir debilidad de HYDRA, no eventos mundiales**
6. **Máximo 15-25% del portafolio**
7. **Regime-aware**: monitorear hit rate rolling 3 años

---

*Informe generado el 2026-03-15 por 5 agentes en paralelo analizando 26 años de data, 16 ETFs, 7 experimentos previos, y la literatura de AQR/Man AHL/Bridgewater/Renaissance.*
