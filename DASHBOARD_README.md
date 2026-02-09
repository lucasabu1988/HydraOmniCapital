# AlphaMax OmniCapital v1.0 - Dashboard

## 📊 Dashboard de Seguimiento en Vivo

Este directorio contiene el sistema de dashboard para monitorear la estrategia OmniCapital v1.0 en tiempo real.

---

## 🚀 Opciones de Dashboard

### Opción 1: Dashboard Web (Streamlit) - RECOMENDADO

Dashboard interactivo con gráficos en tiempo real, accesible desde el navegador.

#### Requisitos
```bash
pip install streamlit plotly
```

#### Lanzar Dashboard
```bash
# Opción A: Usar el script launcher
python launch_dashboard.py

# Opción B: Directamente con Streamlit
streamlit run dashboard.py
```

#### Acceder
- **URL Local**: http://localhost:8501
- El dashboard se abrirá automáticamente en tu navegador

#### Características
- 📈 Gráficos interactivos con Plotly
- 🔄 Auto-refresh cada 60 segundos
- 📊 Visualización de portafolio en tiempo real
- 🎯 Señales de compra/venta en vivo
- ⚠️ Alertas de riesgo
- 📋 Historial de trades
- 📱 Responsive (funciona en móvil)

---

### Opción 2: Dashboard Terminal (Simple)

Versión ligera que funciona en la terminal sin dependencias adicionales.

#### Lanzar
```bash
python dashboard_simple.py
```

#### Características
- ⚡ Sin dependencias de navegador
- 🔄 Actualización cada 30 segundos
- 📊 Tablas formateadas en consola
- 💻 Ideal para servidores headless
- 🎯 Bajo consumo de recursos

---

## 📸 Vista Previa del Dashboard

```
====================================================================================================
                          📈 OMNICAPITAL v1.0 - LIVE DASHBOARD 📈
                              Investment Capital Firm
====================================================================================================

⏰ Última Actualización: 2026-02-08 16:30:00
----------------------------------------------------------------------------------------------------

💰 RESUMEN DEL PORTAFOLIO
----------------------------------------------------------------------------------------------------
  Capital Inicial:    $   1,000,000.00
  Valor Total:        $   1,278,034.76  (+27.80%)
  Invertido:          $   1,078,450.00  (84.4%)
  Cash:               $     199,584.76  (15.6%)
  P&L Total:          $     278,034.76
  Posiciones:         8

📊 POSICIONES ACTUALES
----------------------------------------------------------------------------------------------------
#   Symbol   Shares    Entry    Current       Value       P&L% Status  
----------------------------------------------------------------------------------------------------
1   BAC         442 $    54.50 $    56.53 $   24,986.46   +3.72% 🟢      
2   WFC         266 $    91.20 $    93.97 $   24,996.02   +3.04% 🟢      
3   VZ          539 $    44.80 $    46.31 $   24,961.09   +3.37% 🟢      
...

🎯 SEÑALES DE TRADING EN VIVO
----------------------------------------------------------------------------------------------------
#   Symbol      Price    Score      P/E      P/B Sector                  
----------------------------------------------------------------------------------------------------
1   BAC      $   56.53       90     14.8     1.47 Financial Services     
2   WFC      $   93.97       85     15.0     1.77 Financial Services     
...
```

---

## 📁 Archivos

| Archivo | Descripción |
|---------|-------------|
| `dashboard.py` | Dashboard principal con Streamlit (interactivo) |
| `dashboard_simple.py` | Dashboard de terminal (sin dependencias) |
| `launch_dashboard.py` | Script helper para lanzar el dashboard |
| `DASHBOARD_README.md` | Este archivo |

---

## 🔧 Configuración

### Variables de Entorno
```bash
# Opcional: Configurar puerto del dashboard
export STREAMLIT_SERVER_PORT=8501

# Opcional: Configurar tema
export STREAMLIT_THEME_BASE="dark"
```

### Configuración en dashboard.py
```python
# En la función main() puedes modificar:
initial_capital = 1000000  # Tu capital inicial
refresh_interval = 60      # Segundos entre actualizaciones
```

---

## 🐛 Troubleshooting

### Error: "streamlit: command not found"
```bash
# Solución: Instalar Streamlit
pip install streamlit plotly

# O usar el launcher
python launch_dashboard.py
```

### Error: "Address already in use"
```bash
# Cambiar puerto
streamlit run dashboard.py --server.port 8502
```

### Datos no se actualizan
- Verificar conexión a internet
- API de Yahoo Finance puede tener límites
- Esperar 60 segundos para próxima actualización

---

## 📊 Métricas Mostradas

### Portfolio Overview
- Valor total del portafolio
- Capital invertido vs cash
- P&L total y porcentaje
- Número de posiciones

### Posiciones
- Símbolo y cantidad de acciones
- Precio de entrada y actual
- Valor de la posición
- P&L por posición
- Stop loss y take profit sugeridos

### Señales en Vivo
- Score de valoración (0-100)
- Score técnico (0-100)
- P/E y P/B ratios
- Sector de la empresa
- Recomendación de compra

### Análisis de Riesgo
- VaR (Value at Risk)
- Drawdown actual y máximo
- Exposición por sector
- Beta del portafolio
- Alertas de riesgo

### Mercado
- S&P 500 (SPY) en tiempo real
- Nasdaq (QQQ) en tiempo real
- Sentimiento de mercado
- Fear & Greed Index

---

## 🔄 Flujo de Actualización

```
┌─────────────────┐     ┌──────────────┐     ┌─────────────────┐
│  Yahoo Finance  │────▶│  OmniCapital │────▶│   Dashboard     │
│    API          │     │   Engine     │     │  (Streamlit)    │
└─────────────────┘     └──────────────┘     └─────────────────┘
                              │                       │
                              ▼                       ▼
                        ┌──────────────┐     ┌─────────────────┐
                        │  Señales     │     │  Visualización  │
                        │  de Trading  │     │  Interactiva    │
                        └──────────────┘     └─────────────────┘
```

---

## 🎯 Casos de Uso

### 1. Monitoreo Diario
```bash
# Iniciar al comenzar el día
python launch_dashboard.py

# Dejar corriendo en segundo plano
# Revisar periódicamente las señales
```

### 2. Análisis de Oportunidades
```bash
# Ejecutar análisis en vivo
python omnicapital_v1_live.py

# Ver top oportunidades identificadas
# Comparar con dashboard de seguimiento
```

### 3. Trading en Vivo
```bash
# Terminal 1: Dashboard para monitoreo
python dashboard_simple.py

# Terminal 2: Ejecutar estrategia
python omnicapital_v1.py
```

---

## 📱 Acceso Remoto

Para acceder al dashboard desde otro dispositivo en la misma red:

```bash
# Obtener IP local
ipconfig  # Windows
ifconfig  # Linux/Mac

# Lanzar con configuración de red
streamlit run dashboard.py --server.address 0.0.0.0

# Acceder desde otro dispositivo
# http://TU_IP_LOCAL:8501
```

---

## 🔒 Seguridad

- El dashboard es solo para lectura
- No ejecuta trades automáticamente
- No almacena credenciales
- Datos en tiempo real desde Yahoo Finance

---

## 📞 Soporte

Para reportar issues o sugerencias:
- Email: alpha@investmentcapital.com
- Web: www.investmentcapital.com/support

---

**OmniCapital v1.0** - *Deploy Everything, Secure the Upside*

© 2026 Investment Capital Firm. All Rights Reserved.
