# AlphaMax Investment Algorithm

Algoritmo financiero profesional para gestión de portafolios de equities con enfoque en **maximización de retornos** mediante gestión de riesgo dinámica.

## Características Principales

### Estrategia de Inversión
- **Enfoque**: Maximización de retornos con control de riesgo
- **Universo**: Acciones de gran capitalización (S&P 500 y similares)
- **Horizonte**: Medio-largo plazo con rebalanceo activo

### Gestión de Riesgo
- **Stop Loss Automático**: Basado en ATR o porcentaje fijo
- **Take Profit Parcial**: Tres niveles de salida (50%, 75%, 100%)
- **Trailing Stop**: Protección dinámica de ganancias
- **Sizing de Posiciones**: Criterio de Kelly con fracción conservadora

### Señales de Trading
- **Análisis Técnico**: Momentum, tendencia (MA crossover), RSI, MACD
- **Análisis Fundamental**: Valor, calidad, crecimiento, dividendos
- **Señal Compuesta**: Combinación ponderada de factores técnicos y fundamentales

### Rebalanceo de Portafolio
- **Frecuencia**: Mensual o por umbral de drift
- **Optimización Fiscal**: Consideración de ganancias/pérdidas
- **Control de Turnover**: Límite anual del 50%

## Estructura del Proyecto

```
NuevoProyecto/
├── config/
│   └── strategy.yaml          # Configuración de la estrategia
├── src/
│   ├── core/
│   │   ├── engine.py          # Motor principal del algoritmo
│   │   └── portfolio.py       # Gestión de portafolio y rebalanceo
│   ├── data/
│   │   ├── data_provider.py   # Proveedor de datos de mercado
│   │   └── fundamental_provider.py  # Proveedor de datos fundamentales
│   ├── risk/
│   │   ├── position_risk.py   # Gestión de riesgo por posición
│   │   └── portfolio_risk.py  # Gestión de riesgo de portafolio
│   ├── signals/
│   │   ├── technical.py       # Señales técnicas
│   │   ├── fundamental.py     # Señales fundamentales
│   │   └── composite.py       # Generador de señales compuestas
│   ├── execution/
│   │   └── executor.py        # Ejecutor de órdenes
│   └── main.py                # Punto de entrada
├── tests/                     # Tests unitarios
├── data/                      # Datos históricos
├── logs/                      # Logs de ejecución
├── reports/                   # Reportes generados
├── backtests/                 # Resultados de backtests
├── requirements.txt           # Dependencias
└── README.md                  # Este archivo
```

## Instalación

### Requisitos
- Python 3.11+
- pip o uv

### Instalación de Dependencias

```bash
# Usando pip
pip install -r requirements.txt

# Usando uv (recomendado)
uv pip install -r requirements.txt
```

### Configuración

El archivo `config/strategy.yaml` contiene todos los parámetros configurables:

- **Objetivos**: Retorno objetivo (25%), máximo drawdown (15%)
- **Capital**: Capital inicial, tamaños de posición, buffers
- **Riesgo**: Configuración de stop loss, take profit, trailing stops
- **Señales**: Pesos de indicadores técnicos y fundamentales
- **Rebalanceo**: Frecuencia y umbrales

## Uso

### Ejecutables Disponibles

El proyecto incluye varios ejecutables para facilitar el uso:

#### 1. Menú Interactivo (Recomendado)

Ejecuta el menú principal con todas las opciones:

```bash
# Windows (Batch)
run_live.bat

# Windows (PowerShell)
.\LiveMonitor.ps1

# O con modo específico
.\LiveMonitor.ps1 -Mode Dashboard
.\LiveMonitor.ps1 -Mode Analysis
.\LiveMonitor.ps1 -Mode Monitor -Interval 60
```

#### 2. Análisis Rápido

Ejecuta el análisis de mercado directamente:

```bash
ejecutar_analisis.bat
```

#### 3. Monitor en Tiempo Real

Monitoreo continuo con actualizaciones periódicas:

```bash
python live_monitor.py
python live_monitor.py --interval 30
python live_monitor.py --symbols AAPL MSFT GOOGL
```

### Uso Manual (Python)

#### Análisis de Mercado

Analiza las mejores oportunidades actuales sin ejecutar trades:

```bash
python src/main.py --mode analyze
```

Con símbolos específicos:

```bash
python src/main.py --mode analyze --symbols AAPL MSFT GOOGL NVDA
```

#### Trading Simulado/En Vivo

Ejecuta el algoritmo de trading:

```bash
python src/main.py --mode live
```

#### Backtest

Prueba la estrategia en datos históricos:

```bash
python src/main.py --mode backtest --start-date 2022-01-01 --end-date 2024-01-01
```

#### Dashboard Web

Lanza el dashboard de monitoreo en tiempo real:

```bash
python launch_dashboard.py
# o
python -m streamlit run dashboard.py
```

## Configuración de la Estrategia

### Parámetros Clave

```yaml
# Objetivos de retorno
objectives:
  target_annual_return: 0.25      # 25% anual objetivo
  max_drawdown: 0.15              # Máximo 15% drawdown
  sharpe_ratio_min: 1.5           # Sharpe mínimo 1.5

# Gestión de capital
capital:
  initial_capital: 1000000        # $1M inicial
  max_portfolio_positions: 20     # Máximo 20 posiciones
  min_position_size: 0.02         # Mínimo 2% por posición
  max_position_size: 0.10         # Máximo 10% por posición
  max_sector_exposure: 0.30       # Máximo 30% por sector

# Gestión de riesgo
risk_management:
  stop_loss:
    method: "atr"                 # Basado en ATR
    atr_multiplier: 2.0           # 2x ATR para stop
    trailing: true                # Trailing stop activado
  
  take_profit:
    method: "risk_reward"         # Ratio riesgo/beneficio
    risk_reward_ratio: 3.0        # 1:3 ratio
    partial_exit:
      enabled: true               # Salidas parciales
```

## Reglas del Algoritmo

### Entrada a Posiciones

1. **Screening Fundamental**: Filtrar empresas con score fundamental > 0.60
2. **Señal Técnica**: Confirmar señal de compra técnica
3. **Gestión de Riesgo**: Calcular stop loss y tamaño de posición
4. **Verificación de Portafolio**: Confirmar espacio y exposición permitida

### Salida de Posiciones

#### Stop Loss
- Ejecución automática cuando el precio toca el nivel de stop
- Stop loss inicial basado en 2x ATR
- Trailing stop que sube con el precio

#### Take Profit Parcial
- **Nivel 1 (50%)**: Cerrar 30% de la posición
- **Nivel 2 (75%)**: Cerrar 30% adicional
- **Nivel 3 (100%)**: Cerrar 40% restante

#### Señales de Salida Adicionales
- Reversión de momentum técnico
- Deterioro fundamental de la empresa

### Rebalanceo

El portafolio se rebalancea cuando:
1. Drift de pesos excede 5% del objetivo
2. Fecha de rebalanceo mensual alcanzada
3. Violación de límites de riesgo

## Métricas de Rendimiento

El algoritmo rastrea:

- **Total Return**: Retorno total del portafolio
- **Sharpe Ratio**: Rendimiento ajustado por riesgo
- **Max Drawdown**: Máxima caída desde peak
- **Win Rate**: Porcentaje de trades ganadores
- **Profit Factor**: Ratio ganancias/pérdidas
- **Calmar Ratio**: Retorno / Max Drawdown
- **Sector Exposure**: Exposición por sector
- **Beta del Portafolio**: Sensibilidad al mercado

## Consideraciones de Riesgo

⚠️ **Aviso Importante**: Este algoritmo es para fines educativos e investigación. Antes de usar con capital real:

1. Realizar backtests extensivos en diferentes condiciones de mercado
2. Validar con paper trading
3. Ajustar parámetros según tolerancia al riesgo personal
4. Considerar costos de transacción, slippage y taxes
5. Monitorear constantemente el comportamiento

## Desarrollo

### Ejecutar Tests

```bash
pytest tests/ -v
```

### Linting

```bash
black src/
mypy src/
```

## Roadmap

- [ ] Integración con brokers (Alpaca, Interactive Brokers)
- [ ] Machine Learning para selección de activos
- [ ] Optimización de parámetros con walk-forward analysis
- [ ] Dashboard web para monitoreo en tiempo real
- [ ] Alertas por email/SMS

## Licencia

Proyecto privado - Investment Capital Firm

## Contacto

Para soporte o consultas, contactar al equipo de desarrollo.
