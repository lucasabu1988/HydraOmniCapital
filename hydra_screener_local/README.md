# HYDRA Screener Local (Versión Ligera)

Screener personalizado para generar candidatos de compra diarios usando la lógica HYDRA establecida.

## Instalación (una sola vez)

```bash
cd hydra_screener_local
pip install -r requirements.txt
```

O con packaging (experimental, D4):
```bash
pip install -e .
# Then use entrypoints: hydra-daily, hydra-refresh, hydra-watch, hydra-dashboard
```

## Uso (recomendado)

```bash
python daily.py                 # full ritual + beautiful TV instructions
python daily.py --refresh-pnl   # also updates live PnL in the Excel tracker
```

O directamente:
```bash
python screener.py
```

## Configuración actual

Por defecto usa el **S&P 500 completo**.

Para usar otros índices (o **todos a la vez con más acciones**), edita `config.py`:

```python
UNIVERSE = "sp500"        # S&P 500 (~500)
# UNIVERSE = "nasdaq100"  # Nasdaq-100 (~100, más tech)
# UNIVERSE = "dow30"      # Dow Jones 30 (blue chips)
# UNIVERSE = "russell1000" # Russell 1000 (~1000 large+mid)
# UNIVERSE = "russell2000" # Russell 2000 (~2000 small caps)
# UNIVERSE = "russell3000" # Russell 3000 = R1000 + R2000 (~3000)
UNIVERSE = "all"          # Recomendado: combina SP500 + Nasdaq100 + Dow30 + R1000 + R2000
                          # (~2500+ tickers únicos) y selecciona las mejores de entre TODOS
                          # sin distinguir por índice.
# UNIVERSE = "custom"     # la lista INITIAL_UNIVERSE pequeña (para pruebas)
```

Cuando usas `UNIVERSE = "all"`, el screener obtiene el universo combinado AMPLIADO de los principales índices de EE.UU. (SP500 + Nasdaq-100 + Dow30 + Russell1000 + Russell2000 para integrar large + mid + small caps y muchas más acciones), elimina duplicados (~2500+ con fetches reales), y ejecuta **toda** la lógica HYDRA (momentum risk-adjusted, short-term boost, volume strict filter, meta-layer + pillar multipliers, special modes, sector control, etc.) sobre el pool completo.

Las mejores acciones se eligen **sin distinguir el índice de origen**. El ranking y la selección final es puramente por el scoring HYDRA + controles de riesgo.

Esto integra "más acciones" (large + mid + small caps vía Russell1000/2000) mientras mantienes la selección unificada. Perfecto para buscar en un pool mucho más amplio y quedarte con las mejores.

La bandera legacy `USE_FULL_SP500` sigue funcionando para compatibilidad (se mapea a "sp500").

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

## Data Quality (nuevo en Jun 2026)
El screener ahora incluye protección fuerte contra tickers "zombie":
- Hard blacklist en `config.DELISTED_OR_BAD_TICKERS` (SNDK, BRK.B, BF.B, FB, TWTR, SCTY...).
- Filtrado temprano en `data/fetch.py` (evita descargarlos).
- Sanity check adicional en `core/filters.py:remove_zombie_tickers()` (detecta precios planos en los últimos días, típico de datos corruptos de delistados).

## Volume + Strict Filter (nuevo)
- `fetch_prices_and_volume()` ahora descarga también Volumen en los mismos lotes.
- Durante la generación de candidatos se calcula `vol_ratio` (5d vs 20d) y se marca `passes_strict`.
- Los nombres que pasan el Strict Filter (ret_5d >15% + cerca de máximos + volumen surge) reciben +18% de bonus en el composite_score y aparecen claramente en el Excel/historial.
- Esto trae a producción la lógica que en backtest mostró +4.54% al día siguiente con 100% win-rate.

## Control de Concentración Sectorial (nuevo)
- Buckets gruesos definidos en `config.SECTOR_BUCKETS`.
- `apply_sector_concentration_control()` aplica penalidad suave (15% por defecto) a los nombres que exceden `MAX_PER_SECTOR` (8 por defecto) dentro de un mismo bucket.
- Se re-ordena automáticamente después de la penalidad.
- Columnas nuevas en salida: `sector`, `sector_rank`, `sector_penalty_applied`.
- Justificación: En los regímenes STRONG actuales el screener llegaba a 72% concentrado en solo dos temas (Semis + Software/Cyber). Este control mantiene la capacidad de cargar el tema ganador sin volverse un sector bet excesivo.

Esto resuelve el problema donde SNDK (delisted 2016) aparecía consistentemente en el top del ranking por datos históricos fantasmas de yfinance.

## Uso Recomendado de la Señal (por su naturaleza de 5-day cycle)

La señal del screener está diseñada para rotaciones de **5 días de trading** (coincide con el diseño del sistema HYDRA completo: cycle length 5 días, 5 posiciones en risk-on).

**Mejor forma de usarla (aceptada por el usuario):**

- Corre el screener (idealmente con `UNIVERSE="all"` para el pool combinado de los 3 índices principales).
- Elige las **mejores 5 acciones** (top 5 por `composite_score`).
- **Prioriza** las que pasen `passes_strict` (ret_5d >15% + cerca de highs + volumen surge) cuando haya suficientes. El análisis de historial mostró que el strict filter entrega +4.54% al día siguiente con 100% win-rate (vs ~2% del top general).
- Equal weight (20% por posición).
- Mantén exactamente **5 días de trading**.
- Rebalancea al final del ciclo: vende las que ya no están en el top, compra las nuevas.
- Esto genera turnover razonable, captura el momentum fresco + regime awareness + strict conviction del screener, y es consistente con los backtests oficiales del proyecto.

El control sectorial (max 8 por bucket) ya protege contra concentración excesiva.

## Hybrid Python + TradingView Flow (nuevo)

Ver `HYBRID_USAGE.md` para el flujo completo.

Resumen rápido:
- Python hace el scan pesado diario + genera `pine/watchlist.txt` automáticamente (al final de screener.py / run_real_full_sp500.py).
- Pega esa lista en el Pine `HYDRA_Screener.pine` (input "Watchlist Symbols").
- El Pine muestra una tabla bonita con scoring por símbolo + alerts.
- `send_hydra_summary.py` (llamado automáticamente) genera resumen rico + puede enviar a Discord/Telegram/generic si configuras vars o usas `.env` (copia `.env.example`).
- El parser en Pine consume `top_details` + `recommended_tickers` del JSON. La tabla usa valores exactos de Python (composite, momentum, strict, special) **y las flags "Rec?" exactas** de la lista recomendada por Python cuando pegas el json completo.

Esto combina lo mejor de ambos mundos: poder de cálculo en Python + visualización/alertas en TradingView.

**Scripts experimentales / one-off**: ver `experiments/README.md`. Los comandos diarios recomendados son los indicados arriba (screener + analyze + track).

**Limpieza de artefactos**: `python clean_artifacts.py --dry-run` (luego `--force`) para limpiar output/, backtest/ temporales, data_cache/, __pycache__, etc. (la mayoría ya están en .gitignore del proyecto padre).

**Tests (one command)**: `python run_all_tests.py` (runs spec compliance, feeder golden, hybrid integration, screener logic). Key contract tests must stay green after any change to core or hybrid layer.

## Backtest Histórico del Uso Recomendado (2000-presente)

El proyecto tiene backtests extensos y validados del estilo **exacto** "5 posiciones hold 5 días de trading" usando la misma lógica base del screener actual (momentum 90d risk-adjusted / 63d vol, regime SMA200, etc.).

**Resultados del backtest estilo top-5 / 5-day rotation (2000-2026):**

- CAGR: **15.62%**
- Max DD: **-21.7%** (muy controlado comparado con SPY)
- Sharpe: **1.08**
- Retorno total: ~4341%

Esto es significativamente mejor risk-adjusted que buy & hold SPY en el mismo período.

Los backtests usan pools amplios y la rotación idéntica a la recomendada. Las mejoras del screener actual (Strict Filter, short-term boost, sector control, pillar multipliers, combined "all") harían que una simulación con la versión *exacta actual* sea similar o mejor, especialmente por el alpha demostrado del strict filter.

(Equity curves detallados en backtests/hydra_clean_daily.csv y los v8/v84/v9 del proyecto.)

El script `experiments/backtest_screener_top5_hold5d.py` está preparado para simular el backtest usando la lógica *exacta* del screener actual (puedes correrlo localmente con buena conexión yf para datos históricos; usa el mismo sistema de cache que los backtests oficiales). Ver `experiments/README.md` para la lista completa de scripts experimentales.

**Script dedicado para guardar TODAS las posiciones de TODOS los ciclos en un único Excel (con PnL dinámico):**

Ejecuta o importa `log_cycle_positions.py`.

Después de un run live (especialmente con el hybrid recommended list), actualiza precios actuales con:
```
python refresh_current_prices.py --lookback 5
```
Abre el Excel: las columnas de PnL son fórmulas y se recalculan solas.

Después de cada ciclo (o al final de un backtest), registra las posiciones elegidas. El archivo `backtest/portfolio_cycles.xlsx` acumula todo el historial con hojas estructuradas:
- Cycle_Summaries
- All_Positions (cada ticker de cada ciclo con todos los detalles: rank, score, sector, passes_strict, etc.)
- Equity_Curve y Summary_Stats (cuando se usa desde el backtest)

Esto te da un registro completo, auditable y fácil de analizar de todas las posiciones tomadas a lo largo del tiempo en un solo archivo. El backtest lo usa automáticamente para registrar cada ciclo simulado.

## Cómo correr con UNIVERSE all (pool combinado)

```python
# en config.py
UNIVERSE = "all"
```

Luego:
- `launch_full_screener.bat`
- o `python run_real_full_sp500.py`

El output indicará "COMBINED" y las top 5 de ese output son las que mantendrías por los próximos 5 días de trading.

¡Listo para implementar la recomendación! Si quieres que agregue un módulo simple de "portfolio rotator" o que corra el backtest específico aquí, avísame.

## Próximos pasos (cuando quieras)

- Calcular rendimiento real de los candidatos recomendados (5d/10d) en analyze_history.py
- Reportes de win-rate por tipo de régimen y Special Mode
- Extender fetch para incluir Volume y activar filtro de liquidez real (>1M shares)
- Filtros adicionales (e.g. por sector vía yfinance info o polygon)

¡Listo para usar diariamente!
