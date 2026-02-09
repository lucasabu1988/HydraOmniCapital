# OmniCapital v1.0 - Guia de Ejecutables

Este documento describe los diferentes ejecutables disponibles para operar el algoritmo de trading en vivo.

## ⚠️ IMPORTANTE - Problemas Comunes

Si los archivos `.bat` no funcionan, usa el **launcher.py** que es más compatible.

---

## 🚀 Metodos de Ejecucion (en orden de recomendacion)

### Metodo 1: Launcher Python (RECOMENDADO - Más Compatible)

**Archivo:** `launcher.py` o `iniciar.bat`

Este es el metodo mas confiable y compatible con todos los sistemas Windows.

**Opcion A - Desde linea de comandos:**
```bash
python launcher.py
```

**Opcion B - Doble clic en iniciar.bat:**
```
iniciar.bat
```

**Ventajas:**
- Funciona en todas las versiones de Windows
- No tiene problemas con caracteres especiales
- Menu interactivo claro
- Manejo de errores robusto

---

### Metodo 2: Menu CMD (Alternativa Simple)

**Archivo:** `menu.cmd`

Version simplificada sin caracteres especiales.

```
menu.cmd
```

---

### Metodo 3: PowerShell (Para usuarios avanzados)

**Archivo:** `LiveMonitor.ps1`

```powershell
.\LiveMonitor.ps1
```

Si da error de ejecucion, primero ejecuta:
```powershell
Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser
```

---

### Metodo 4: Batch Original

**Archivo:** `run_live.bat`

Si no funciona, prueba los metodos anteriores.

---

## 📋 Opciones del Menu

Todas las versiones del menu incluyen estas opciones:

1. **Dashboard Web** - Abre interfaz web en http://localhost:8501
2. **Analisis de Mercado** - Ejecuta analisis completo y genera reporte CSV
3. **Trading Simulado** - Ejecuta el algoritmo sin trades reales
4. **Backtest Historico** - Prueba la estrategia en datos pasados
5. **Monitor Continuo** - Actualizaciones periodicas en tiempo real
6. **Ver Reportes** - Muestra archivos generados
7. **Salir** - Cierra el programa

---

## 📁 Archivos Disponibles

| Archivo | Descripcion | Uso |
|---------|-------------|-----|
| `launcher.py` | Lanzador Python principal | `python launcher.py` |
| `iniciar.bat` | Batch que ejecuta launcher.py | Doble clic |
| `menu.cmd` | Menu simplificado CMD | `menu.cmd` |
| `LiveMonitor.ps1` | Menu PowerShell avanzado | `.\LiveMonitor.ps1` |
| `run_live.bat` | Menu Batch original | `run_live.bat` |
| `ejecutar_analisis.bat` | Ejecuta analisis directo | `ejecutar_analisis.bat` |
| `live_monitor.py` | Monitor continuo Python | `python live_monitor.py` |

---

## 🔧 Solucion de Problemas

### "Windows no puede abrir este archivo"

**Solucion:** Usa el Metodo 1 (launcher.py)

1. Abre CMD o PowerShell en la carpeta del proyecto
2. Ejecuta: `python launcher.py`

### "Python no esta instalado"

1. Descarga Python 3.11+ desde https://python.org
2. Durante la instalacion, marca "Add Python to PATH"
3. Reinicia la terminal

### "No se reconoce el comando python"

Reinstala Python asegurandote de marcar "Add to PATH"

### El archivo .bat se cierra inmediatamente

1. Abre CMD manualmente
2. Navega a la carpeta: `cd C:\Users\caslu\Desktop\NuevoProyecto`
3. Ejecuta: `python launcher.py`

### Error en PowerShell sobre politicas de ejecucion

Ejecuta como Administrador:
```powershell
Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser
```

---

## 📊 Descripcion de Funciones

### Dashboard Web
Interfaz grafica en el navegador que muestra:
- Precios en tiempo real
- Oportunidades de inversion
- Metricas del portafolio
- Graficos interactivos

### Analisis de Mercado
Ejecuta el algoritmo completo:
- Descarga datos actualizados de Yahoo Finance
- Calcula scores de valoracion fundamental
- Genera senales tecnicas
- Muestra top 20 oportunidades
- Guarda reporte CSV en carpeta `reports/`

### Trading Simulado
Ejecuta el algoritmo sin realizar trades reales:
- Analiza oportunidades
- Simula ejecucion de ordenes
- Calcula metricas de rendimiento

### Backtest Historico
Prueba la estrategia en datos pasados:
- Simula trades historicos
- Calcula retornos, drawdown, Sharpe ratio
- Genera reporte detallado

### Monitor Continuo
Mantiene el algoritmo corriendo:
- Actualiza datos cada X segundos
- Detecta cambios significativos
- Genera alertas de compra/venta
- Guarda historial en `logs/`

---

## 📂 Estructura de Carpetas

```
NuevoProyecto/
├── launcher.py          <- USAR ESTE (recomendado)
├── iniciar.bat          <- O este para doble clic
├── menu.cmd             <- Alternativa simple
├── LiveMonitor.ps1      <- PowerShell
├── run_live.bat         <- Batch original
├── ejecutar_analisis.bat
├── live_monitor.py
├── src/                 <- Codigo fuente
├── reports/             <- Reportes generados
├── logs/                <- Logs de ejecucion
├── backtests/           <- Resultados de backtest
└── data/                <- Datos descargados
```

---

## 💡 Ejemplos de Uso

### Ejecutar analisis rapido desde CMD:
```bash
python omnicapital_v1_live.py
```

### Ejecutar solo el dashboard:
```bash
python -m streamlit run dashboard.py
```

### Ejecutar backtest especifico:
```bash
python src/main.py --mode backtest --start-date 2022-01-01 --end-date 2024-01-01
```

### Ejecutar monitor con intervalo personalizado:
```bash
python live_monitor.py --interval 30
```

---

## 🆘 Soporte

Si tienes problemas:

1. **Primer intento:** `python launcher.py`
2. **Segundo intento:** Abre CMD, navega a la carpeta, ejecuta `python launcher.py`
3. **Tercer intento:** Revisa que Python este instalado: `python --version`

Para mas ayuda, revisa:
- `README.md` - Documentacion general
- `OMNICAPITAL_v1.0_README.md` - Documentacion tecnica

---

**Version:** 1.0.0  
**Fecha:** 2026  
**Requisitos:** Python 3.11+
