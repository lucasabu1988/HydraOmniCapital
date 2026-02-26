<p align="center">
  <img src="../static/img/omnicapital_logo.png" alt="OmniCapital Logo" width="150">
</p>

# OmniCapital — Guia de Deployment en Vivo
## De Paper Trading a Dinero Real

> *"El momento de la verdad no es en el backtest, es cuando el dinero real esta en juego."*

---

## FASE 0: PRE-DEPLOYMENT (Semanas 1-2)

### 0.1 Checklist de Preparacion Legal y Fiscal

- [ ] **Estructura legal definida**
  - Cuenta personal vs LLC vs Fondo
  - Consultar con abogado fiscalista
  - Considerar offshore si aplica

- [ ] **Cuenta de broker abierta y aprobada**
  - Interactive Brokers (recomendado)
  - Alpaca (alternativa US-only)
  - Verificar soporte para margin 2:1

- [ ] **Documentacion fiscal preparada**
  - Formularios W-9 (US) o W-8BEN (internacional)
  - Plan para reporte de ganancias/pérdidas
  - Contador familiarizado con trading

- [ ] **Capital asignado**
  - Solo dinero que no necesites en 5+ años
  - Maximo 20% de patrimonio neto
  - Fondo de emergencia intacto

### 0.2 Setup Tecnico

```bash
# 1. Crear entorno virtual dedicado
python -m venv omnicapital_live_env
source omnicapital_live_env/bin/activate  # Linux/Mac
omnicapital_live_env\Scripts\activate     # Windows

# 2. Instalar dependencias
pip install yfinance pandas numpy ib_insync alpaca-trade-api

# 3. Crear directorio de produccion
mkdir ~/omnicapital_production
cd ~/omnicapital_production

# 4. Copiar archivos necesarios
cp omnicapital_live.py .
cp omnicapital_broker.py .
cp omnicapital_data_feed.py .
```

### 0.3 Configuracion de Seguridad

```python
# config_live.py - NO SUBIR A GIT
IBKR_ACCOUNT = "TU_ACCOUNT_ID"
IBKR_API_KEY = "TU_API_KEY"
IBKR_SECRET = "TU_SECRET"

# Alertas
EMAIL_ALERTS = "tu@email.com"
SLACK_WEBHOOK = "https://hooks.slack.com/services/..."
SMS_NUMBER = "+1234567890"
```

---

## FASE 1: PAPER TRADING RIGUROSO (Semanas 3-6)

### 1.1 Configuracion Paper Trading

```python
# En omnicapital_live.py, configurar:
CONFIG = {
    'BROKER_TYPE': 'IBKR_PAPER',  # o 'ALPACA_PAPER'
    'INITIAL_CAPITAL': 100000,    # Igual al capital real planeado
    'PAPER_TRADING': True,
    
    # Parametros v6 (NO MODIFICAR)
    'HOLD_MINUTES': 1200,
    'NUM_POSITIONS': 5,
    'STOP_LOSS_PCT': -0.20,
    'LEVERAGE': 2.0,
}
```

### 1.2 Protocolo de Monitoreo Diario

| Hora | Tarea | Check |
|------|-------|-------|
| 09:30 ET | Verificar apertura del sistema | [ ] |
| 12:00 ET | Check de posiciones y P&L | [ ] |
| 16:00 ET | Verificar cierre y estado final | [ ] |
| 20:00 ET | Revisar logs del dia | [ ] |

### 1.3 Checklist Semanal

- [ ] Todas las ordenes se ejecutaron correctamente
- [ ] Stop loss funciono segun lo esperado
- [ ] No hay errores en logs
- [ ] Data feed actualizo correctamente
- [ ] Cash disponible es el esperado
- [ ] Numero de posiciones = 5 (o menos en proteccion)

### 1.4 Criterios de Exit Paper Trading

**MINIMO 1 MES** de paper trading exitoso:

| Criterio | Threshold | Estado |
|----------|-----------|--------|
| Ordenes ejecutadas | > 95% sin error | [ ] |
| Slippage promedio | < 0.2% | [ ] |
| Latencia de datos | < 5 minutos | [ ] |
| Tiempo de uptime | > 99% | [ ] |
| Stop loss testeado | 1+ evento exitoso | [ ] |

---

## FASE 2: TRANSICION A LIVE (Semana 7)

### 2.1 Pre-Launch Checklist

#### Tecnico
- [ ] API keys de broker funcionan
- [ ] Margin aprobado y activo
- [ ] Ordenes de prueba ejecutadas correctamente
- [ ] Stop loss testeado en live (con minima cantidad)
- [ ] Backup de conexion (4G/wifi secundario)
- [ ] VPS/cloud server configurado (opcional pero recomendado)

#### Financiero
- [ ] Capital transferido a cuenta de broker
- [ ] Comisiones entendidas y calculadas
- [ ] Costos de margin confirmados
- [ ] Impuestos estimados reservados

#### Personal
- [ ] Horario de trading bloqueado en calendario
- [ ] Plan de contingencia definido
- [ ] Contacto de broker guardado
- [ ] Decisiones pre-comprometidas escritas

### 2.2 Estrategia de Escalado

| Semana | Capital | Leverage | Notas |
|--------|---------|----------|-------|
| 7 | $10,000 | 1:1 | Solo para test de ejecucion |
| 8-9 | $25,000 | 1.5:1 | Validar con algo de riesgo |
| 10-11 | $50,000 | 2:1 | Escala completa sin leverage max |
| 12+ | $100,000+ | 2:1 | Operacion normal |

### 2.3 Configuracion Live

```python
# CONFIGURACION LIVE - REVISAR 3 VECES ANTES DE EJECUTAR
CONFIG = {
    'BROKER_TYPE': 'IBKR_LIVE',  # ⚠️ LIVE - NO PAPER
    'INITIAL_CAPITAL': 100000,   # ⚠️ DINERO REAL
    'PAPER_TRADING': False,      # ⚠️ FALSE PARA LIVE
    
    # Parametros v6 (VERIFICAR QUE SEAN EXACTOS)
    'HOLD_MINUTES': 1200,
    'NUM_POSITIONS': 5,
    'STOP_LOSS_PCT': -0.20,
    'LEVERAGE': 2.0,
    'MIN_AGE_DAYS': 63,
    'RANDOM_SEED': 42,
    
    # Costos reales (actualizar segun broker)
    'COMMISSION_PER_SHARE': 0.001,  # IBKR typical
    'SLIPPAGE_PCT': 0.001,          # Estimado
    'BORROW_RATE_ANNUAL': 0.06,     # Verificar con broker
}
```

---

## FASE 3: OPERACION LIVE (Semana 8+)

### 3.1 Rutina Diaria

#### Pre-Mercado (08:30 ET)
```bash
# 1. Verificar sistema
python check_system.py

# 2. Revisar estado anterior
cat logs/omnicapital_$(date -d "yesterday" +%Y%m%d).log

# 3. Verificar conexion con broker
python test_broker_connection.py

# 4. Confirmar cash disponible
```

#### Durante Mercado (09:30-16:00 ET)
- Monitoreo pasivo (no intervenir)
- Alertas configuradas para:
  - Stop loss proximo (-15%)
  - Error de ejecucion
  - Perdida de conexion
  - Cambio de regimen (si aplica)

#### Post-Mercado (16:30 ET)
```bash
# 1. Verificar estado final
python generate_daily_report.py

# 2. Backup de datos
cp data/* backup/$(date +%Y%m%d)/

# 3. Revisar metricas
python analyze_performance.py --days=7
```

### 3.2 Protocolos de Emergencia

#### Escenario A: Stop Loss Activado
```
1. Sistema cierra automaticamente todas las posiciones
2. Leverage reduce a 1:1
3. Enviar alerta: "STOP LOSS ACTIVADO - MODO PROTECCION"
4. NO agregar capital durante proteccion
5. Esperar recuperacion a 95% del peak
6. Sistema restaura leverage automaticamente
```

#### Escenario B: Perdida de Conexion
```
1. Sistema intenta reconectar (max 3 intentos)
2. Si falla: enviar alerta critica
3. Manual: verificar broker directamente
4. Si hay posiciones abiertas: decidir mantener o cerrar
5. Reiniciar sistema cuando conexion estable
```

#### Escenario C: Error de Ejecucion
```
1. Sistema loguea error y continua
2. Enviar alerta con detalles
3. Manual: verificar en plataforma del broker
4. Si orden no se ejecuto: sistema intentara en siguiente ciclo
5. Si orden parcial: sistema ajustara cantidad
```

#### Escenario D: Bug en el Sistema
```
1. Detener sistema inmediatamente
2. Cerrar posiciones manualmente si es necesario
3. Revisar logs para identificar problema
4. NO reiniciar hasta fix confirmado
5. Considerar volver a paper trading
```

### 3.3 Reglas de Oro (Lectura Diaria)

1. **NO MODIFICAR PARAMETROS** durante drawdowns
2. **NO AGREGAR CAPITAL** durante proteccion (1:1 leverage)
3. **NO INTERRUMPIR** el sistema por "intuicion"
4. **NO OPERAR** tamanos que causen ansiedad
5. **NO COMPARAR** resultados mensuales con otros

---

## FASE 4: MONITOREO Y MANTENIMIENTO

### 4.1 Metricas de Salud

| Metrica | Frecuencia | Herramienta |
|---------|------------|-------------|
| P&L diario | Diaria | Dashboard |
| Drawdown actual | Tiempo real | Alerta si > -15% |
| Sharpe ratio | Mensual | Reporte |
| Uptime del sistema | Continuo | Pingdom/UptimeRobot |
| Slippage promedio | Semanal | Analisis de trades |
| Costos de margin | Mensual | Extracto broker |

### 4.2 Revisiones Periodicas

#### Semanal (Domingos)
- [ ] Revisar todos los trades de la semana
- [ ] Verificar que stop loss esta funcionando
- [ ] Analizar slippage y costos
- [ ] Backup de logs y estado

#### Mensual
- [ ] Calcular performance vs benchmark (SPY)
- [ ] Revisar metricas de riesgo (Sharpe, Sortino)
- [ ] Analisis de regimen (tiempo en proteccion)
- [ ] Ajustar reservas fiscales si es necesario

#### Trimestral
- [ ] Revision profunda de performance
- [ ] Considerar ajuste de capital (solo al alza)
- [ ] Evaluar si seguir en live o pausar
- [ ] Reunion con asesor fiscal

### 4.3 Cuando DETENER el Sistema

**Detener inmediatamente si:**
- Drawdown > 30% (por encima del stop loss esperado)
- 3+ errores de ejecucion en una semana
- Cambio en situacion personal (necesitas la liquidez)
- Problemas de salud que impidan monitoreo
- Duda razonable sobre validez del sistema

**Detener y reconsiderar si:**
- Underperformance vs SPY por 6+ meses
- Cambio estructural en mercado (ej: prohibicion de short selling)
- Nuevos costos regulatorios significativos

---

## APENDICE: CHECKLIST FINAL PRE-LIVE

### Tecnico
- [ ] Codigo revisado y testeado en paper
- [ ] API keys configuradas y funcionando
- [ ] Logs rotativos configurados
- [ ] Alertas configuradas y testeadas
- [ ] Backup automatico de estado
- [ ] Documentacion de recuperacion de desastres

### Financiero
- [ ] Capital disponible en cuenta
- [ ] Margin aprobado y activado
- [ ] Comisiones entendidas
- [ ] Reserva fiscal calculada
- [ ] Presupuesto de costos de operacion

### Legal/Fiscal
- [ ] Estructura legal definida
- [ ] Impuestos entendidos
- [ ] Regulaciones compliance verificadas
- [ ] Documentacion de trades preparada

### Personal
- [ ] Horario comprometido
- [ ] Plan de contingencia escrito
- [ ] Decisiones pre-comprometidas
- [ ] Support system (familia/amigos al tanto)
- [ ] Ego chequeado

### Mental
- [ ] Acepto que puedo perder todo el capital
- [ ] No necesito este dinero para 5+ años
- [ ] No voy a intervenir en el sistema
- [ ] Entiendo que habra meses/perdidas negativos
- [ ] Estoy comodo con 38% drawdown potencial

---

## FIRMA DE COMPROMISO

Yo, ________________, declaro que:

1. He leido y entendido completamente este documento
2. He testeado el sistema en paper trading por minimo 1 mes
3. Entiendo los riesgos y acepto las posibles perdidas
4. No intervenire en el sistema una vez en operacion
5. Seguire los protocolos de emergencia establecidos

Firma: ________________ Fecha: ________________

---

**Version:** 1.0  
**Fecha:** 10 Febrero 2026  
**Sistema:** OmniCapital v6 FINAL  
**Estado:** Listo para deployment

*"In Simplicity We Trust. In Discipline We Execute."*
