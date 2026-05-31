# HYDRA Screener Local (Versión Ligera)

Screener personalizado para generar candidatos de compra diarios usando la lógica HYDRA establecida.

## Instalación (una sola vez)

```bash
cd hydra_screener_local
pip install -r requirements.txt
```

## Uso

```bash
python screener.py
```

## Configuración actual

Por defecto usa el **S&P 500 completo**.

Si quieres volver a una lista más pequeña y rápida para pruebas, edita `config.py` y pon:

```python
USE_FULL_SP500 = False
```

## Qué genera

- Tabla bonita en terminal con `rich`
- Archivo Excel automático en `output/hydra_screener_YYYYMMDD.xlsx`

## Filosofía

- Todo **100% local** en Windows
- Sin servidores ni dependencias pesadas
- Empezamos con el S&P 500 completo (puedes reducirlo fácilmente)
- Rápido de ejecutar manualmente antes / durante / después de la apertura

## Histórico y Análisis

El screener guarda automáticamente cada corrida en `history/`.

Para revisar el histórico:

```bash
python analyze_history.py
```

Esto es la base para medir win-rate y éxito de la estrategia a lo largo del tiempo.

## Estado Actual (May 2026)

El screener está **funcional y estable**:

- ✅ Lógica Meta-Layer + 4 Special Modes + Pillar Multipliers integrada y probada
- ✅ Número dinámico de recomendaciones (6-28) según régimen y multipliers
- ✅ Special Modes y recovery_boost ahora se propagan correctamente al historial
- ✅ Filtros de precio activos (min 5 USD); filtro de volumen placeholder (0 por defecto, requiere Volume data)
- ✅ Persistencia completa en `history/YYMMDD.json` (incluye special_modes reales)
- ✅ Smoke tests con datos sintéticos pasan (core + extracción)

**Nota sobre rich/terminal**: Las tablas bonitas con ✅ usan unicode. En Windows Terminal, VSCode o PowerShell moderno renderizan perfecto. Consolas legacy (cp1252) pueden tener issues de encoding con emojis/flechas.

## Próximos pasos (cuando quieras)

- Calcular rendimiento real de los candidatos recomendados (5d/10d) en analyze_history.py
- Reportes de win-rate por tipo de régimen y Special Mode
- Extender fetch para incluir Volume y activar filtro de liquidez real (>1M shares)
- Filtros adicionales (e.g. por sector vía yfinance info o polygon)

¡Listo para usar diariamente!
