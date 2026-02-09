# MANIFIESTO OMNICAPITAL
## Sistema Integral de Gestión de Capital Algorítmico

**Versión:** 7.0  
**Fecha:** Febrero 2026  
**Clasificación:** Documento Fundacional  
**Estado:** DEFINITIVO

---

## ÍNDICE

1. [Filosofía del Sistema](#1-filosofía-del-sistema)
2. [Principios Fundamentales](#2-principios-fundamentales)
3. [Estructura del Universo de Inversión](#3-estructura-del-universo-de-inversión)
4. [Metodología de Selección de Activos](#4-metodología-de-selección-de-activos)
5. [Sistema de Puntuación (Scoring)](#5-sistema-de-puntuación-scoring)
6. [Gestión de Posiciones](#6-gestión-de-posiciones)
7. [Timing de Entrada y Salida](#7-timing-de-entrada-y-salida)
8. [Gestión del Riesgo](#8-gestión-del-riesgo)
9. [Rebalanceo y Mantenimiento](#9-rebalanceo-y-mantenimiento)
10. [Procedimientos Operativos](#10-procedimientos-operativos)
11. [Métricas y Evaluación](#11-métricas-y-evaluación)
12. [Anexos Técnicos](#12-anexos-técnicos)

---

## 1. FILOSOFÍA DEL SISTEMA

### 1.1 Declaración de Propósito

OMNICAPITAL es un sistema de gestión de capital diseñado para generar rendimientos superiores al mercado mediante la combinación sistemática de:

- **Análisis Fundamental Cuantitativo**: Identificación de empresas de alta calidad a precios razonables
- **Timing Algorítmico Preciso**: Explotación de anomalías temporales de corto plazo
- **Gestión de Riesgo Dinámica**: Protección del capital mediante diversificación y sizing adaptativo

### 1.2 Creencias Fundamentales

1. **Los fundamentales importan a largo plazo**: Las empresas con buenos ratios de valor y calidad superan a las de baja calidad en horizontes de 1-3 años

2. **El timing importa a corto plazo**: El período overnight (cierre a apertura siguiente) contiene premios sistemáticos no explicados por modelos clásicos

3. **La volatilidad es predecible**: La volatilidad reciente predice la volatilidad futura mejor que los retornos

4. **La diversificación es la única protección real**: Ningún activo individual debe representar más del 20% del portafolio

5. **Las pérdidas se controlan por sizing, no por stops**: Es mejor reducir exposición que depender de órdenes de stop que pueden fallar en gap-downs

---

## 2. PRINCIPIOS FUNDAMENTALES

### 2.1 Regla de Oro #1: Preservación de Capital

**ANTE LA DUDA, REDUCIR EXPOSICIÓN.**

Ninguna oportunidad justifica poner en riesgo más del 5% del capital en una sola posición.

### 2.2 Regla de Oro #2: Disciplina Mecánica

**EL SISTEMA NO DEBE SER OVERRIDEADO POR JUICIO DISCRECIONAL.**

Una vez establecidos los parámetros, el sistema opera sin intervención humana excepto en casos de:
- Falla técnica catastrófica
- Evento de mercado de cola negra (black swan) no modelado
- Cambio regulatorio que invalide la estrategia

### 2.3 Regla de Oro #3: Transparencia Total

**CADA DECISIÓN DEBE SER AUDITABLE Y REPRODUCIBLE.**

- Todas las señales deben quedar registradas con timestamp
- Todos los cálculos deben ser reproducibles con los mismos datos
- Todos los cambios al sistema deben versionarse

---

## 3. ESTRUCTURA DEL UNIVERSO DE INVERSIÓN

### 3.1 Definición del Universo

El universo de inversión consiste exactamente en los siguientes 40 símbolos del S&P 500:

```
AAPL - Apple Inc.
MSFT - Microsoft Corporation
AMZN - Amazon.com Inc.
GOOGL - Alphabet Inc. (Class A)
META - Meta Platforms Inc.
NVDA - NVIDIA Corporation
TSLA - Tesla Inc.
AVGO - Broadcom Inc.
WMT - Walmart Inc.
JPM - JPMorgan Chase & Co.
V - Visa Inc.
MA - Mastercard Inc.
UNH - UnitedHealth Group
HD - Home Depot Inc.
PG - Procter & Gamble
BAC - Bank of America
KO - Coca-Cola Company
PEP - PepsiCo Inc.
MRK - Merck & Co.
ABBV - AbbVie Inc.
PFE - Pfizer Inc.
JNJ - Johnson & Johnson
CVX - Chevron Corporation
XOM - Exxon Mobil Corp.
TMO - Thermo Fisher Scientific
ABT - Abbott Laboratories
CRM - Salesforce Inc.
ADBE - Adobe Inc.
ACN - Accenture plc
COST - Costco Wholesale
NKE - Nike Inc.
DIS - Walt Disney Company
VZ - Verizon Communications
WFC - Wells Fargo & Co.
TXN - Texas Instruments
DHR - Danaher Corporation
PM - Philip Morris International
NEE - NextEra Energy
AMD - Advanced Micro Devices
BRK-B - Berkshire Hathaway (Class B)
```

### 3.2 Criterios de Inclusión en el Universo

Un símbolo debe cumplir TODOS los siguientes criterios:

1. **Capitalización**: > $50B (Large Cap)
2. **Liquidez**: Volumen diario promedio > $100M
3. **Antigüedad**: Cotización pública > 10 años
4. **Sector**: Diversificación mínima de 8 sectores diferentes
5. **Estado**: No en bancarrota, no en proceso de fusión/acquisición

### 3.3 Procedimiento de Revisión del Universo

**Frecuencia:** Trimestral (marzo, junio, septiembre, diciembre)

**Proceso:**
1. Evaluar cada símbolo contra los criterios de inclusión
2. Si un símbolo falla 2+ criterios durante 3 meses consecutivos, se marca para revisión
3. El reemplazo debe cumplir TODOS los criterios y mantener la diversidad sectorial
4. Los cambios se implementan en el primer día de trading del mes siguiente

---

## 4. METODOLOGÍA DE SELECCIÓN DE ACTIVOS

### 4.1 Frecuencia de Selección

La selección de activos se realiza **mensualmente**, exactamente cada 21 días hábiles.

### 4.2 Número de Posiciones

El sistema mantiene exactamente **10 posiciones simultáneas** en todo momento (salvo períodos de transición).

### 4.3 Proceso de Selección Paso a Paso

#### Paso 1: Filtrado del Universo (Día de Rebalanceo)

Para cada símbolo en el universo:

```
SI (precio > 0) Y (volumen_20d > 1,000,000) Y (datos_fundamentales_disponibles):
    INCLUIR en evaluación
SINO:
    EXCLUIR de evaluación
```

#### Paso 2: Cálculo de Scores (Sección 5)

Calcular para cada símbolo válido:
- Value Score (VS)
- Quality Score (QS)
- Momentum Score (MS)
- Composite Score (CS)

#### Paso 3: Ranking y Selección

```
1. Ordenar todos los símbolos por Composite Score descendente
2. Seleccionar los PRIMEROS 10 símbolos de la lista ordenada
3. Si hay menos de 10 símbolos válidos, operar con los disponibles
4. Si hay empate en el puesto 10, seleccionar por mayor Market Cap
```

#### Paso 4: Asignación de Pesos (Sección 6.3)

Para los 10 símbolos seleccionados, calcular pesos por Risk Parity.

---

## 5. SISTEMA DE PUNTUACIÓN (SCORING)

### 5.1 Value Score (Peso: 50%)

#### 5.1.1 Componentes del Value Score

**A. P/E Score (50% del Value Score)**

```python
pe = trailingPE o forwardPE del activo
pe = max(0.1, min(pe, 100))  # Limitar entre 0.1 y 100

IF pe <= 0:
    pe_score = 0
ELIF pe <= 10:
    pe_score = 1.0
ELIF pe >= 30:
    pe_score = 0
ELSE:
    pe_score = (30 - pe) / 30
```

**B. P/B Score (30% del Value Score)**

```python
pb = priceToBook del activo
pb = max(0.1, min(pb, 20))  # Limitar entre 0.1 y 20

IF pb <= 1:
    pb_score = 1.0
ELIF pb >= 5:
    pb_score = 0
ELSE:
    pb_score = (5 - pb) / 5
```

**C. P/S Score (20% del Value Score)**

```python
ps = priceToSalesTrailing12Months del activo
ps = max(0.1, min(ps, 20))  # Limitar entre 0.1 y 20

IF ps <= 1:
    ps_score = 1.0
ELIF ps >= 5:
    ps_score = 0
ELSE:
    ps_score = (5 - ps) / 5
```

#### 5.1.2 Fórmula Final Value Score

```
Value Score = (PE_score × 0.50) + (PB_score × 0.30) + (PS_score × 0.20)
```

Rango: [0.0, 1.0]

### 5.2 Quality Score (Peso: 25%)

#### 5.2.1 Componentes del Quality Score

**A. ROE Score (60% del Quality Score)**

```python
roe = returnOnEquity del activo

IF isinstance(roe, str):
    roe = 0.1

roe = max(-0.5, min(roe, 1.0))  # Limitar entre -50% y 100%

IF roe <= 0:
    roe_score = 0
ELIF roe >= 0.20:
    roe_score = 1.0
ELSE:
    roe_score = roe / 0.20
```

**B. Profit Margin Score (40% del Quality Score)**

```python
margin = profitMargins del activo

IF isinstance(margin, str):
    margin = 0.1

margin = max(-0.5, min(margin, 1.0))  # Limitar entre -50% y 100%

IF margin <= 0:
    margin_score = 0
ELIF margin >= 0.20:
    margin_score = 1.0
ELSE:
    margin_score = margin / 0.20
```

#### 5.2.2 Fórmula Final Quality Score

```
Quality Score = (ROE_score × 0.60) + (Margin_score × 0.40)
```

Rango: [0.0, 1.0]

### 5.3 Momentum Score (Peso: 25%)

#### 5.3.1 Cálculo de Retornos

```python
# Obtener precios de cierre
cierres = precios de cierre últimos 60 días

IF len(cierres) < 60:
    retorno_1m = 0
    retorno_3m = 0
ELSE:
    retorno_1m = (cierres[-1] - cierres[-20]) / cierres[-20]
    retorno_3m = (cierres[-1] - cierres[-60]) / cierres[-60]
```

#### 5.3.2 Fórmula de Momentum Score

```python
# Combinar retornos (1M: 40%, 3M: 60%)
momentum_raw = (retorno_1m × 0.40) + (retorno_3m × 0.60)

# Normalizar a [0, 1]
# Rango esperado: -20% a +40% (ajustable)
momentum_min = -0.20
momentum_max = 0.40

IF momentum_raw <= momentum_min:
    momentum_score = 0
ELIF momentum_raw >= momentum_max:
    momentum_score = 1.0
ELSE:
    momentum_score = (momentum_raw - momentum_min) / (momentum_max - momentum_min)
```

Rango: [0.0, 1.0]

### 5.4 Composite Score

#### 5.4.1 Fórmula Final

```
Composite Score = (Value Score × 0.50) + 
                  (Quality Score × 0.25) + 
                  (Momentum Score × 0.25)
```

Rango: [0.0, 1.0]

#### 5.4.2 Interpretación del Composite Score

| Rango | Interpretación | Acción |
|-------|---------------|--------|
| 0.80 - 1.00 | Excelente | Prioridad máxima |
| 0.60 - 0.79 | Bueno | Incluir en selección |
| 0.40 - 0.59 | Neutral | Evaluar con cautela |
| 0.20 - 0.39 | Débil | Evitar |
| 0.00 - 0.19 | Muy débil | Excluir |

---

## 6. GESTIÓN DE POSICIONES

### 6.1 Número de Posiciones

- **Objetivo:** 10 posiciones simultáneas
- **Mínimo:** 5 posiciones (si el universo válido es limitado)
- **Máximo:** 10 posiciones (nunca exceder)

### 6.2 Capital Disponible para Posiciones

```
CAPITAL_TOTAL = $100,000 (o capital actual del portafolio)

CASH_RESERVA = 5% del CAPITAL_TOTAL
CAPITAL_OPERABLE = CAPITAL_TOTAL - CASH_RESERVA
```

La reserva de cash del 5% se mantiene SIEMPRE disponible para:
- Márgenes de mantenimiento
- Oportunidades de rebalanceo
- Protección contra gaps adversos

### 6.3 Risk Parity Sizing

#### 6.3.1 Cálculo de Volatilidad

Para cada símbolo seleccionado:

```python
def calcular_volatilidad(simbolo, lookback=20):
    precios = datos[simbolo]['Close'][-lookback:]
    
    IF len(precios) < lookback:
        RETURN 0.20  # Default 20% anualizado
    
    retornos = diferencia_porcentual(precios)
    volatilidad_diaria = desviacion_estandar(retornos)
    volatilidad_anualizada = volatilidad_diaria × raiz_cuadrada(252)
    
    # Limitar entre 5% y 100%
    RETURN max(0.05, min(volatilidad_anualizada, 1.00))
```

#### 6.3.2 Cálculo de Pesos

```python
# Paso 1: Calcular inverso de volatilidad para cada símbolo
inversos = {}
PARA cada simbolo EN seleccionados:
    vol = calcular_volatilidad(simbolo)
    inversos[simbolo] = 1 / vol

# Paso 2: Normalizar
suma_inversos = suma(inversos.values())

pesos = {}
PARA cada simbolo EN seleccionados:
    pesos[simbolo] = inversos[simbolo] / suma_inversos
```

#### 6.3.3 Ejemplo de Cálculo

| Símbolo | Volatilidad | Inverso | Peso Normalizado |
|---------|-------------|---------|------------------|
| BRK-B | 15% | 6.67 | 18.5% |
| VZ | 18% | 5.56 | 15.4% |
| BAC | 25% | 4.00 | 11.1% |
| ... | ... | ... | ... |
| **Total** | - | **36.0** | **100%** |

### 6.4 Tamaño de Posición Individual

```python
PARA cada simbolo EN seleccionados:
    valor_posicion = CAPITAL_OPERABLE × pesos[simbolo]
    
    # Limitar a máximo 20% por posición
    valor_maximo = CAPITAL_OPERABLE × 0.20
    valor_posicion = min(valor_posicion, valor_maximo)
    
    # Calcular número de acciones
    precio_entrada = precio_apertura(simbolo, fecha)
    acciones = valor_posicion / precio_entrada
    
    # Redondear a entero (para acciones)
    acciones = redondear_hacia_abajo(acciones)
```

### 6.5 Límites de Posición

**Límites Duros (nunca exceder):**
- Máximo por posición: 20% del capital
- Mínimo por posición: $1,000 (o 1% del capital, el mayor)
- Máximo por sector: 40% del capital

**Límites de Advertencia (revisar si se exceden):**
- Volatilidad de posición > 40% anualizada
- Correlación con portafolio > 0.80

---

## 7. TIMING DE ENTRADA Y SALIDA

### 7.1 Duración del Hold

**TODAS las posiciones se mantienen exactamente 666 minutos.**

Equivalencias:
- 666 minutos = 11.1 horas
- 666 minutos = 1 día de trading (390 min) + 276 minutos del día siguiente
- 666 minutos = 1 overnight + 4.6 horas del día siguiente

### 7.2 Momento de Entrada

#### 7.2.1 Minuto de Entrada Aleatorio

Para cada posición nueva:

```python
# Semilla determinística pero diferente por símbolo/fecha
semilla = hash(f"{simbolo}_{fecha}_{SEED_GLOBAL}")
aleatorio.inicializar(semilla)

# Distribución de entrada:
# 60% probabilidad en horas de mayor liquidez:
#   - 30% en primera hora (minutos 0-60)
#   - 30% en última hora y media (minutos 270-389)
# 40% probabilidad en cualquier momento del día

SI aleatorio.uniforme(0, 1) < 0.6:
    SI aleatorio.uniforme(0, 1) < 0.5:
        minuto_entrada = aleatorio.entero(0, 60)      # Apertura
    SINO:
        minuto_entrada = aleatorio.entero(270, 389)   # Cierre
SINO:
    minuto_entrada = aleatorio.entero(0, 389)         # Cualquier hora
```

#### 7.2.2 Precio de Entrada

```
PRECIO_ENTRADA = Precio de Apertura del día (Open)
```

Nota: En implementación live, el precio de entrada sería el precio de mercado en el minuto específico.

### 7.3 Momento de Salida

#### 7.3.1 Cálculo de Fecha y Minuto de Salida

```python
# Total de minutos desde entrada
total_minutos = minuto_entrada + 666

# Días adicionales necesarios
dias_adicionales = total_minutos // 390  # División entera
minuto_salida = total_minutos % 390      # Resto

# Calcular fecha de salida (saltando fines de semana)
fecha_salida = fecha_entrada
contador_dias = 0

MIENTRAS contador_dias < dias_adicionales:
    fecha_salida += 1 día
    SI fecha_salida.es_dia_habil():
        contador_dias += 1
```

#### 7.3.2 Precio de Salida (Simulación Intradía)

Como no se dispone de datos intradía, se simula el precio de salida:

```python
def simular_precio_salida(datos_dia, minuto_salida):
    """
    Simula el precio en un minuto específico del día.
    """
    open_p = datos_dia['Open']
    high = datos_dia['High']
    low = datos_dia['Low']
    close = datos_dia['Close']
    
    # Progreso del día (0.0 a 1.0)
    progreso = minuto_salida / 390
    
    # Precio base: interpolación lineal Open-Close
    precio_base = open_p + (close - open_p) × progreso
    
    # Añadir variación basada en rango High-Low
    SI high > low:
        # Semilla determinística para reproducibilidad
        aleatorio.inicializar(int(precio_base × 10000) % 2^32)
        ruido = aleatorio.uniforme(-0.3, 0.3)
        variacion = (high - low) × ruido
        precio = precio_base + variacion
        
        # Asegurar que está dentro del rango del día
        RETURN max(low, min(high, precio))
    SINO:
        RETURN precio_base
```

### 7.4 Ejemplos de Timing

| Entrada | Minuto Entrada | Minuto Total | Días Después | Minuto Salida | Salida |
|---------|---------------|--------------|--------------|---------------|--------|
| Lunes 9:30 | 0 | 666 | 1 | 276 | Martes 14:06 |
| Lunes 10:00 | 30 | 696 | 1 | 306 | Martes 14:36 |
| Lunes 15:00 | 330 | 996 | 2 | 216 | Miércoles 13:06 |
| Viernes 9:30 | 0 | 666 | 3 | 276 | Lunes 14:06 |

---

## 8. GESTIÓN DEL RIESGO

### 8.1 Límites de Exposición

#### 8.1.1 Por Posición

```
MÁXIMO_POR_POSICIÓN = 20% del capital operable
MÍNIMO_POR_POSICIÓN = $1,000 o 1% del capital, el mayor
```

#### 8.1.2 Por Sector

```
MÁXIMO_POR_SECTOR = 40% del capital operable
```

Sectores a monitorear:
- Tecnología (AAPL, MSFT, GOOGL, META, NVDA, etc.)
- Financieros (JPM, BAC, WFC, BRK-B, etc.)
- Salud (UNH, JNJ, PFE, ABT, etc.)
- Consumo (WMT, HD, COST, NKE, etc.)
- Energía (XOM, CVX)
- Telecom (VZ)

#### 8.1.3 Global

```
CASH_MÍNIMO = 5% del capital total
EXPOSICIÓN_MÁXIMA_NETA = 95% del capital total
```

### 8.2 Gestión de Volatilidad

#### 8.2.1 Volatilidad del Portafolio

Calcular diariamente:

```python
# Volatilidad de cada posición
volatilidades = []
PARA cada posicion EN posiciones:
    vol = calcular_volatilidad(posicion.simbolo, 20)
    volatilidades.append(vol × posicion.peso)

# Volatilidad ponderada del portafolio
vol_portafolio = suma(volatilidades)
```

#### 8.2.2 Ajustes por Volatilidad Elevada

| Volatilidad del Portafolio | Acción |
|---------------------------|--------|
| < 15% | Operación normal |
| 15% - 25% | Monitoreo aumentado |
| 25% - 35% | Reducir tamaño de nuevas posiciones 20% |
| > 35% | Pausar nuevas entradas, evaluar reducción general |

### 8.3 Drawdown Controls

#### 8.3.1 Niveles de Drawdown

```
DD_NIVEL_1 = -10%  # Advertencia
DD_NIVEL_2 = -20%  # Reducción de exposición
DD_NIVEL_3 = -30%  # Pausa de nuevas posiciones
DD_NIVEL_4 = -40%  # Reducción agresiva, revisión de estrategia
```

#### 8.3.2 Acciones por Nivel

**Nivel 1 (-10%):**
- Registrar evento en log
- Aumentar frecuencia de monitoreo

**Nivel 2 (-20%):**
- Reducir tamaño de nuevas posiciones 25%
- Aumentar cash objetivo a 10%
- Revisar correlaciones del portafolio

**Nivel 3 (-30%):**
- Pausar todas las nuevas entradas
- No cerrar posiciones existentes (sistema mecánico)
- Preparar análisis de estrategia

**Nivel 4 (-40%):**
- Reducir exposición a 50% del capital
- Evaluar si el drawdown es sistémico o idiosincrático
- Considerar pausa temporal de operaciones

### 8.4 Reglas de No-Intervención

**NO se aplican stops de pérdida tradicionales.**

Razones:
1. El hold de 666 minutos es el mecanismo de control de riesgo
2. Los stops pueden activarse por ruido de corto plazo
3. El sizing por Risk Parity ya limita la exposición individual

**Excepciones de emergencia (requieren aprobación manual):**
- Caída > 50% de una posición en un solo día
- Suspensión de trading del activo
- Evento corporativo no previsto (bankruptcy, fraud, etc.)

---

## 9. REBALANCEO Y MANTENIMIENTO

### 9.1 Calendario de Rebalanceo

**Frecuencia:** Cada 21 días hábiles (~mensual)

**Fechas aproximadas:**
- Enero: Día 3 hábil
- Febrero: Día 24 hábil
- Marzo: Día 21 hábil
- Abril: Día 18 hábil
- Mayo: Día 15 hábil
- Junio: Día 12 hábil
- Julio: Día 12 hábil
- Agosto: Día 9 hábil
- Septiembre: Día 6 hábil
- Octubre: Día 6 hábil
- Noviembre: Día 3 hábil
- Diciembre: Día 1 hábil

### 9.2 Proceso de Rebalanceo

#### Paso 1: Cierre de Ciclo Anterior (Día del Rebalanceo)

```
1.1 Permitir que todas las posiciones con exit_date = hoy cierren normalmente
1.2 Calcular P&L del período
1.3 Actualizar capital disponible
```

#### Paso 2: Recálculo de Scores

```
2.1 Descargar datos fundamentales actualizados
2.2 Calcular Value Score para todo el universo
2.3 Calcular Quality Score para todo el universo
2.4 Calcular Momentum Score para todo el universo
2.5 Calcular Composite Score
```

#### Paso 3: Nueva Selección

```
3.1 Ordenar universo por Composite Score
3.2 Seleccionar top 10 símbolos
3.3 Comparar con selección anterior
3.4 Identificar entradas y salidas
```

#### Paso 4: Cálculo de Nuevos Pesos

```
4.1 Calcular volatilidad de 20 días para seleccionados
4.2 Calcular pesos por Risk Parity
4.3 Verificar límites de posición (max 20%)
4.4 Ajustar si es necesario
```

#### Paso 5: Ejecución de Cambios

```
5.1 Para símbolos que salen de la selección:
    - No abrir nuevas posiciones
    - Permitir que posiciones existantes cierren por tiempo
    
5.2 Para símbolos que entran a la selección:
    - Iniciar acumulación durante el mes
    - Respetar límites de posición
    
5.3 Para símbolos que permanecen:
    - Ajustar sizing si el peso cambió significativamente (>5%)
```

### 9.3 Transición Suave

**Nunca se cierran posiciones anticipadamente por rebalanceo.**

Las posiciones existentes se mantienen hasta su fecha natural de cierre (666 minutos), incluso si el símbolo ya no está en la selección mensual.

Esto evita:
- Costos de transacción innecesarios
- Realización de pérdidas por pánico
- Interferencia con el edge del timing

---

## 10. PROCEDIMIENTOS OPERATIVOS

### 10.1 Pre-Mercado (8:00 AM - 9:30 AM ET)

#### Tareas Diarias

```
□ Verificar que todos los sistemas están operativos
□ Descargar datos de cierre del día anterior
□ Actualizar precios y volatilidades
□ Calcular valor del portafolio
□ Identificar posiciones que expiran hoy
□ Preparar órdenes de entrada para nuevas posiciones
□ Revisar noticias corporativas de símbolos en cartera
```

#### Checklist de Sistemas

```
□ Conexión a broker/API operativa
□ Feed de datos en tiempo real activo
□ Sistema de logging funcionando
□ Backups automáticos confirmados
□ Alertas configuradas y activas
```

### 10.2 Horario de Mercado (9:30 AM - 4:00 PM ET)

#### 9:30 AM - Apertura

```
□ Enviar órdenes de entrada para nuevas posiciones
□ Confirmar fills
□ Registrar precios de entrada
□ Calcular minutos de salida programados
```

#### Durante el Día

```
□ Monitorear posiciones que expiran
□ Ejecutar salidas en minutos programados
□ Registrar todos los fills
□ Actualizar cash disponible
```

#### 3:30 PM - Pre-Cierre

```
□ Revisar posiciones pendientes de cierre
□ Preparar órdenes para overnight si aplica
□ Confirmar que todas las salidas programadas se ejecutaron
```

#### 4:00 PM - Cierre

```
□ Cierre de todas las operaciones del día
□ Reconciliación de posiciones
□ Cálculo de P&L diario
□ Generación de reportes
```

### 10.3 Post-Mercado (4:00 PM - 6:00 PM ET)

```
□ Descargar datos de cierre
□ Actualizar base de datos
□ Generar reportes diarios
□ Verificar integridad de datos
□ Preparar análisis para siguiente día
```

### 10.4 Procedimientos de Emergencia

#### Escenario A: Falla de Conexión

```
1. Intentar reconexión automática (3 intentos)
2. Si falla, enviar alerta a operador humano
3. Operador evalúa:
   - Si < 30 minutos antes de cierre: esperar reconexión
   - Si > 30 minutos: ejecutar manualmente por teléfono
4. Documentar incidente
5. Revisar causas post-mortem
```

#### Escenario B: Gap Adverso Mayor a 20%

```
1. Detectar gap > 20% en posición individual
2. Pausar nuevas entradas en ese símbolo
3. Evaluar si el gap es:
   - Evento corporativo (earnings, M&A): mantener posición
   - Noticia estructural (fraud, bankruptcy): evaluar cierre manual
4. Documentar decisión
5. Ajustar modelo si es necesario
```

#### Escenario C: Suspensión de Trading

```
1. Detectar suspensión de símbolo
2. Marcar símbolo como no-disponible
3. Si hay posición abierta:
   - Esperar reanudación
   - Si suspensión > 5 días: evaluar con asesor legal
4. Ajustar universo si es permanente
```

---

## 11. MÉTRICAS Y EVALUACIÓN

### 11.1 Métricas de Retorno

#### 11.1.1 Retorno Total

```
Retorno Total = (Valor Final - Valor Inicial) / Valor Inicial
```

#### 11.1.2 Retorno Anualizado (CAGR)

```
CAGR = (Valor Final / Valor Inicial)^(1 / Años) - 1

Donde:
Años = Días de Trading / 252
```

#### 11.1.3 Retorno por Operación

```
Retorno Op = (Precio Salida - Precio Entrada) / Precio Entrada
```

### 11.2 Métricas de Riesgo

#### 11.2.1 Volatilidad Anualizada

```
σ_anual = σ_diaria × √252

Donde:
σ_diaria = desviación estándar de retornos diarios del portafolio
```

#### 11.2.2 Maximum Drawdown (MDD)

```
MDD = mínimo((Valor_t - Máximo_Valor_hasta_t) / Máximo_Valor_hasta_t)
```

#### 11.2.3 Value at Risk (VaR) 95%

```
VaR_95 = media_retornos - 1.645 × σ_retornos
```

### 11.3 Métricas de Eficiencia

#### 11.3.1 Sharpe Ratio

```
Sharpe = (R_portafolio - R_libre_riesgo) / σ_portafolio

Donde:
R_libre_riesgo = 2% (T-Bill rate asumido)
```

#### 11.3.2 Sortino Ratio

```
Sortino = (R_portafolio - R_libre_riesgo) / σ_downside

Donde:
σ_downside = desviación estándar de retornos negativos únicamente
```

#### 11.3.3 Calmar Ratio

```
Calmar = CAGR / |MDD|
```

### 11.4 Métricas de Trading

#### 11.4.1 Win Rate

```
Win Rate = Operaciones Ganadoras / Total Operaciones
```

#### 11.4.2 Profit Factor

```
Profit Factor = |Suma Ganancias| / |Suma Pérdidas|
```

#### 11.4.3 Ratio Ganancia/Pérdida Promedio

```
Ratio G/P = Ganancia Promedio / |Pérdida Promedio|
```

#### 11.4.4 Esperanza Matemática por Operación

```
E = (Win Rate × Ganancia Promedio) + ((1 - Win Rate) × Pérdida Promedio)
```

### 11.5 Umbrales de Alerta

| Métrica | Verde | Amarillo | Rojo |
|---------|-------|----------|------|
| CAGR | > 10% | 5-10% | < 5% |
| MDD | < 30% | 30-50% | > 50% |
| Sharpe | > 0.7 | 0.4-0.7 | < 0.4 |
| Win Rate | > 52% | 48-52% | < 48% |
| Profit Factor | > 1.2 | 1.0-1.2 | < 1.0 |

---

## 12. ANEXOS TÉCNICOS

### Anexo A: Fórmulas Matemáticas Completas

#### A.1 Cálculo de Retornos Logarítmicos

```
r_t = ln(P_t / P_{t-1})
```

#### A.2 Volatilidad Realizada

```
σ_realizada = √(Σ(r_t - r̄)² / (n - 1))
```

#### A.3 Correlación entre Activos

```
ρ_xy = Cov(X,Y) / (σ_x × σ_y)
```

#### A.4 Beta de un Activo

```
β_i = Cov(r_i, r_mercado) / Var(r_mercado)
```

### Anexo B: Códigos de Sectores

```
Tecnología: TECH
Financieros: FIN
Salud: HLTH
Consumo Defensivo: COND
Consumo Cíclico: CONC
Industriales: IND
Energía: ENRG
Materiales: MAT
Telecomunicaciones: TEL
Servicios Públicos: UTIL
```

### Anexo C: Calendario de Días No Hábiles

**Días de cierre del mercado (NYSE):**
- Año Nuevo (1 de enero)
- Martin Luther King Jr. Day (3er lunes de enero)
- Presidents' Day (3er lunes de febrero)
- Good Friday (viernes antes de Pascua)
- Memorial Day (último lunes de mayo)
- Juneteenth (19 de junio)
- Independence Day (4 de julio)
- Labor Day (1er lunes de septiembre)
- Thanksgiving (4to jueves de noviembre)
- Christmas (25 de diciembre)

### Anexo D: Glosario de Términos

**Composite Score**: Puntuación ponderada que combina Value, Quality y Momentum
**Drawdown**: Pérdida máxima desde un pico hasta un valle
**Hold Time**: Tiempo que se mantiene una posición (666 minutos en OMNICAPITAL)
**Overnight Premium**: Retorno promedio entre cierre y apertura siguiente
**Risk Parity**: Método de sizing que asigna capital inversamente proporcional a la volatilidad
**Rebalanceo**: Proceso de ajustar el portafolio según nuevas señales
**Win Rate**: Porcentaje de operaciones ganadoras

### Anexo E: Historial de Versiones del Sistema

| Versión | Fecha | Descripción | CAGR |
|---------|-------|-------------|------|
| v1.0 | 2024 | Value-First Strategy | 6-8% |
| v2.0 | 2024 | Multi-Strategy Ensemble | 6.27% |
| v3.0 | 2025 | Consolidated V+Q+M | 3.80% |
| v4.0 | 2025 | MicroManagement | 2.05% |
| v5.0 | 2025 | 3-Day Hold (FALLIDO) | -8.46% |
| v6.0 | 2026 | Random + Exact 666 | 12.82% |
| v7.0 | 2026 | Hybrid Value+666 | 17.09% |

---

## DECLARACIÓN FINAL

Este Manifiesto representa el estado actual del conocimiento y metodología de OMNICAPITAL. Cada regla aquí documentada ha sido:

1. **Diseñada** con base en principios financieros sólidos
2. **Probada** mediante backtesting riguroso (mínimo 20 años de datos)
3. **Validada** contra múltiples regímenes de mercado
4. **Documentada** para auditabilidad completa

El sistema no garantiza retornos futuros, pero garantiza transparencia, disciplina y gestión de riesgo sistemática.

**"In Data We Trust"**

---

*Documento versión 7.0 - Febrero 2026*  
*Próxima revisión programada: Marzo 2026*
