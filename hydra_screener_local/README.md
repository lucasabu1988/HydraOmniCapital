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

## Próximos pasos (cuando quieras)

- Integrar la Meta-Layer completa
- Agregar lógica de Catalyst y Rattlesnake
- Mejor ranking combinado
- Filtros adicionales (volatilidad, sector, etc.)

¡Listo para usar!
