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

## Próximos pasos (cuando quieras)

- Calcular rendimiento real de los candidatos recomendados (5d/10d)
- Reportes de win-rate por tipo de régimen y Special Mode
- Mejor uso de los Pillar Multipliers en el ranking
- Filtros adicionales

¡Listo para usar!
