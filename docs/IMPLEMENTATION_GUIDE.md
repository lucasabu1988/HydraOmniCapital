<p align="center">
  <img src="../static/img/omnicapital_logo.png" alt="OmniCapital Logo" width="150">
</p>

# OmniCapital — Guia de Implementacion

## Resumen del Sistema

OmniCapital v6 es un sistema de trading sistematico con las siguientes caracteristicas:

| Parametro | Valor |
|-----------|-------|
| **Hold Time** | 1200 minutos (~20 horas, 2 overnights) |
| **Stop Loss** | -20% a nivel de portfolio |
| **Leverage** | 2:1 (dinamico, reduce a 1:1 en stop) |
| **Posiciones** | 5 simultaneas |
| **Universo** | S&P 500 large-caps (65 simbolos) |
| **Rebalanceo** | Cada minuto durante horario de mercado |
| **Seleccion** | Aleatoria entre simbolos disponibles |

## Performance Esperada

- **CAGR**: 16.92%
- **Sharpe Ratio**: 0.82
- **Max Drawdown**: -38.4%
- **Stop Loss Events**: ~5 en 26 anos (2001, 2008, 2010, 2020, 2022)

## Archivos del Sistema

```
omnicapital_live.py              # Sistema principal (listo para usar)
omnicapital_data_feed.py         # Modulo de datos
omnicapital_broker.py            # Integracion con brokers
omnicapital_live_trading.py      # Implementacion alternativa
IMPLEMENTATION_GUIDE.md          # Esta guia
```

## Requisitos

```bash
pip install yfinance pandas numpy
```

Para IBKR:
```bash
pip install ib_insync
```

Para Alpaca:
```bash
pip install alpaca-trade-api
```

## Inicio Rapido (Paper Trading)

```bash
python omnicapital_live.py
```

El sistema:
1. Carga estado previo si existe
2. Conecta con broker de papel
3. Inicia loop de trading
4. Guarda estado cada 5 minutos

## Configuracion

Editar `CONFIG` en `omnicapital_live.py`:

```python
CONFIG = {
    'HOLD_MINUTES': 1200,           # Tiempo de retencion
    'NUM_POSITIONS': 5,              # Max posiciones
    'PORTFOLIO_STOP_LOSS': -0.20,    # Stop loss portfolio
    'LEVERAGE': 2.0,                 # Apalancamiento inicial
    'INITIAL_CAPITAL': 100000,       # Capital inicial
    'BROKER_TYPE': 'PAPER',          # PAPER, IBKR, ALPACA
}
```

## Estados del Sistema

### Normal (Leverage 2:1)
- 5 posiciones aleatorias
- Cada posicion ~40% del capital efectivo
- Hold time 1200 minutos

### Proteccion (Leverage 1:1)
- Activado tras stop loss (-20%)
- Solo se cierran posiciones, no se abren nuevas
- Recuperacion cuando portfolio >= 95% del peak

## Flujo de Trading

```
Cada minuto:
  |
  +-- Verificar horario mercado (9:30-16:00 ET)
  |
  +-- Obtener precios
  |
  +-- Verificar stop loss
  |     +-- Si DD <= -20%: Cerrar todo, leverage = 1:1
  |
  +-- Cerrar posiciones expiradas (>1200 min)
  |
  +-- Abrir nuevas posiciones (si hay slots)
  |     +-- Seleccion aleatoria de simbolos
  |     +-- Calcular tamaño: (cash * leverage * 0.95) / 5
  |
  +-- Log estado
  +-- Guardar estado (cada 5 min)
```

## Conexion con Brokers Reales

### Interactive Brokers (IBKR)

1. Instalar TWS o IB Gateway
2. Habilitar API (Edit > Global Configuration > API)
3. Modificar `omnicapital_live.py`:

```python
from ib_insync import IB, Stock, MarketOrder

class IBKRBroker:
    def __init__(self):
        self.ib = IB()
        self.ib.connect('127.0.0.1', 7497, clientId=1)
    
    def buy(self, symbol, shares, price):
        contract = Stock(symbol, 'SMART', 'USD')
        order = MarketOrder('BUY', shares)
        trade = self.ib.placeOrder(contract, order)
        return trade
```

### Alpaca

```python
from alpaca_trade_api import REST

class AlpacaBroker:
    def __init__(self):
        self.api = REST('API_KEY', 'SECRET_KEY', 
                       'https://paper-api.alpaca.markets')
    
    def buy(self, symbol, shares, price):
        self.api.submit_order(
            symbol=symbol,
            qty=shares,
            side='buy',
            type='market',
            time_in_force='day'
        )
```

## Monitoreo

### Logs
- Archivo: `omnicapital_live_YYYYMMDD.log`
- Consola: output en tiempo real

### Estado
- Archivo: `omnicapital_state_YYYYMMDD.json`
- Contiene: posiciones, cash, peak, proteccion

### Metricas a Monitorear

```bash
# Ver logs en tiempo real
tail -f omnicapital_live_*.log

# Ver estado actual
cat omnicapital_state_*.json | jq

# Contar trades
python -c "import json; d=json.load(open('omnicapital_state_*.json')); print(len(d['positions']))"
```

## Backups y Recuperacion

### Backup Diario
```bash
cp omnicapital_state_$(date +%Y%m%d).json backup/
cp omnicapital_live_$(date +%Y%m%d).log backup/
```

### Recuperacion
```python
# Cargar estado especifico
trader.load_state('omnicapital_state_20250209.json')
```

## Troubleshooting

### No se obtienen precios
- Verificar conexion a internet
- Yahoo Finance puede tener delays
- Considerar feed de pago (IBKR, Polygon)

### Ordenes no se ejecutan
- Verificar horario de mercado
- Verificar cash disponible
- Revisar logs de error

### Stop loss no activa
- Verificar calculo de portfolio value
- Revisar si peak_value se actualiza correctamente
- Verificar condicion de drawdown

### Muchas posiciones pequenas
- Ajustar MIN_CASH_BUFFER
- Verificar calculo de position_size
- Revisar redondeo de shares

## Seguridad

### Antes de Live Trading

1. **Test en paper trading** (minimo 1 mes)
2. **Verificar calculos** de position sizing
3. **Testear stop loss** manualmente
4. **Revisar comisiones** y slippage
5. **Backup de estado** antes de iniciar

### Checklist Live Trading

- [ ] Cuenta de broker verificada
- [ ] Margin aprobado (para 2:1 leverage)
- [ ] API keys configuradas
- [ ] Paper trading exitoso (1+ mes)
- [ ] Stop loss testeado
- [ ] Capital asignado correctamente
- [ ] Monitoreo configurado
- [ ] Plan de contingencia

## Soporte

Para issues o preguntas:
1. Revisar logs en `omnicapital_live_*.log`
2. Verificar estado en `omnicapital_state_*.json`
3. Consultar `OMNICAPITAL_V6_FINAL_SPEC.md`

## Proximos Pasos

1. Ejecutar paper trading 1-2 semanas
2. Validar comportamiento del stop loss
3. Verificar costos de comisiones
4. Planificar migracion a live trading
5. Establecer procedimientos de monitoreo
