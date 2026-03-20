/* ============================================================
   i18n.js — HYDRA Dashboard Internationalization (ES / EN)
   Loaded before dashboard.js
   ============================================================ */

var currentLang = localStorage.getItem('hydra-lang') || 'es';

var TRANSLATIONS = {
  es: {
    // Header
    'hdr-market-closed':   'MERCADO CERRADO',
    'hdr-waiting-signal':  'ESPERANDO SEÑAL 15:30',
    'hdr-preclose-open':   'VENTANA PRE-CIERRE ABIERTA',
    'hdr-moc-sent':        'ÓRDENES MOC ENVIADAS',
    'offline-banner':      'CONECTANDO AL SERVIDOR...',

    // Tabs
    'tab-dashboard':  'Dashboard',
    'tab-roadmap':    'Roadmap',
    'tab-algorithm':  'Algoritmo',
    'tab-funds':      'Comparativa',
    'tab-analytics':  'Analytics',
    'tab-ml':         'ML',

    // Dashboard Narrative Sections
    'ds-today-label':     'Estado Actual',
    'ds-today-title':     'Rendimiento en Tiempo Real',
    'ds-today-insight':   'HYDRA vs S&P 500 \u2014 d\u00eda a d\u00eda y acumulado desde el inicio del test en vivo',
    'ds-regime-label':    'R\u00e9gimen',
    'ds-regime-title':    'R\u00e9gimen de Mercado',
    'ds-regime-insight':  'El term\u00f3metro del mercado determina cu\u00e1ntas posiciones mantener y el overlay macro ajusta la exposici\u00f3n',
    'ds-strat-label':     'Posiciones',
    'ds-strat-title':     'Estrategias Activas',
    'ds-strat-insight':   '4 estrategias complementarias con reciclaje de capital \u2014 momentum, mean-reversion, tendencia macro y exposici\u00f3n internacional',
    'ds-track-label':     'Evidencia',
    'ds-track-title':     'Track Record',
    'ds-track-insight':   '26 a\u00f1os de backtest con correcci\u00f3n de supervivencia, an\u00e1lisis de riesgo y proyecci\u00f3n Monte Carlo',

    // Fund Comparison
    'fc-hero-sub':        '\u00bfC\u00f3mo se compara HYDRA contra fondos reales?',
    'fc-hero-tagline':    'Backtest 2000\u20132026 \u00b7 Datos de Yahoo Finance (precios ajustados con dividendos) \u00b7 Costos incluidos',
    'fc-metrics-title':   'M\u00e9tricas Principales',
    'fc-equity-title':    'Crecimiento de $100K (Datos Mensuales Reales)',
    'fc-crisis-title':    'Rendimiento en Crisis',
    'fc-annual-title':    'Retornos Anuales (%)',
    'fc-notes-title':     'Notas & Fuentes',
    'fc-th-fund':         'Fondo',
    'fc-th-type':         'Tipo',
    'fc-th-since':        'Desde',
    'fc-th-vol':          'Volatilidad',
    'fc-th-cumulative':   'Acumulado',
    'fc-th-expense':      'Costo',

    // Hero Section
    'hero-tagline':          'Momentum + Mean-Reversion + International · Cash Recycling · S&P 500 + EAFE · Long-Only',
    'hero-cagr-context':     'Survivorship-corrected (882 tickers)',
    'hero-sharpe-context':   'Risk-adjusted',
    'hero-maxdd-context':    'vs −55.2% SPY',
    'hero-posyears-label':   'Positive Years',
    'hero-posyears-context': '81% win rate by year',
    'hero-beats-label':      'Beats S&P',
    'hero-beats-context':    'years with alpha > 0',
    'hero-alpha-label':      'Avg Alpha',
    'hero-alpha-context':    'per year vs S&P 500',
    'hero-strategies-label':   'Strategies',
    'hero-strategies-context': 'Momentum + Rattle + EFA',
    'hero-hold-label':       'Hold Period',
    'hero-hold-value':       '5 days',
    'hero-hold-context':     'Weekly rotation cycle',
    'hero-growth-label':     'Growth',
    'hero-growth-context':   '2000–2026 backtest',
    'hero-avgalpha-label':     'Alpha Promedio',
    'hero-avgalpha-context':   'por año vs S&P 500',
    'hero-medianalpha-label':  'Alpha Mediana',
    'hero-medianalpha-context':'por año vs S&P 500',
    'hero-alphapositive-label':'Alpha Positivo',
    'hero-bestalpha-label':    'Mejor Alpha',
    'hero-worstalpha-label':   'Peor Alpha',
    'hero-feat-experiments':   '68 Experiments',
    'hero-feat-noleverage':    'No Leverage',
    'hero-feat-cashrecycling': 'Cash Recycling',
    'hero-feat-noblackbox':    'No Black Box',
    'hero-disclaimer':       'Past performance does not guarantee future results. This is a live paper trading test, not investment advice.',

    // Preclose
    'preclose-closed': 'MERCADO CERRADO',

    // Perf Banner
    'perf-today':          'Hoy',
    'perf-overall':        'General',
    'perf-beating':        'Superando S&P 500',
    'perf-behind':         'Detrás de S&P 500',
    'perf-vs':             'vs S&P 500',
    'perf-period':         'Test en vivo desde',
    'perf-backtest-label': 'Backtest (2000–2026)',

    // Metric Cards
    'metric-portfolio': 'Valor del Portfolio',
    'metric-cagr':      'CAGR Esperado',
    'metric-cagr-sub':  'HYDRA (Momentum + Rattlesnake + Catalyst + EFA) | No leverage',
    'metric-cash':      'Efectivo',
    'metric-drawdown':  'Drawdown',
    'metric-positions': 'Posiciones',
    'metric-invested':  'Invertido',
    'metric-peak':      'Máximo',

    // Regime Band
    'regime-score':       'Regime Score',
    'regime-consecutive': 'Consecutivos',
    'regime-risk-on':     'RISK ON',
    'regime-risk-off':    'RISK OFF',
    'regime-transition':  'TRANSICIÓN',
    'regime-caution':     'CAUTELA',

    // Overlay
    'overlay-title': 'Macro Overlay',

    // HYDRA header
    'hydra-header-sub': '4 estrategias · Cash Recycling activo · Capital segregado',

    // Strategy labels
    'strategy-1':         'ESTRATEGIA 1',
    'strategy-2':         'ESTRATEGIA 2',
    'strategy-3':         'ESTRATEGIA 3',
    'strat-desc-momentum': 'Compra las acciones con mayor momentum ajustado por riesgo (retorno 90d / volatilidad 63d) del top-40 S&P 500. Rota cada 5 días con stops adaptativos por volatilidad.',
    'strat-desc-rattle':   'Compra acciones del S&P 100 que caen ≥8% en 5 días con RSI(5)<25 y tendencia alcista. Objetivo +4%, stop −5%, máximo 8 días.',
    'strat-desc-catalyst': 'Mantiene ETFs de tendencia macro (TLT, GLD, DBC) que estén sobre su SMA200, más una asignación permanente en oro. Rebalancea cada 5 días.',
    'strat-desc-efa':      'Capital idle después del reciclaje se aparca en EFA (mercados desarrollados internacionales) cuando EFA > SMA200. Se liquida si las estrategias activas necesitan capital.',
    'strat-invested':     'Invertido',
    'strat-return':       'Retorno',
    'strat-positions':    'Posiciones',
    'strat-loading':      'Cargando posiciones...',
    'strat-no-positions': 'SIN POSICIONES',
    'strat-rattle-waiting': 'Esperando caída ≥8% + RSI<25 en S&P 100',

    // Position cards
    'pos-today':  'Hoy',
    'pos-entry':  'Entrada',
    'pos-target': 'Target',
    'pos-stop':   'Stop',

    // P2P Scatter
    'p2p-title':     'Peer-to-Peer — Comparación de Posiciones',
    'p2p-positions': 'posiciones',
    'p2p-best':      'Mejor Posición',
    'p2p-worst':     'Peor Posición',
    'p2p-avg':       'Retorno Promedio',
    'p2p-total-val': 'Valor Total',

    // Annual Returns
    'ar-title':           'Retornos Anuales — HYDRA vs S&P 500',
    'ar-hydra-pos':       'HYDRA positivo',
    'ar-hydra-neg':       'HYDRA negativo',
    'ar-positive-years':  'Años positivos',
    'ar-of-years':        'de',
    'ar-years':           'años',
    'ar-beats-sp':        'Bate al S&P',
    'ar-years-alpha':     'años con alfa > 0',
    'ar-loses-sp':        'Pierde al S&P',
    'ar-years-alpha-neg': 'años con alfa < 0',
    'ar-avg-alpha':       'Alfa promedio',
    'ar-pp-year':         'pp / año vs S&P',

    // Trade Analytics
    'ta-title': 'Análisis de Trades — Backtest',
    'risk-title': 'Monitor de Riesgo',
    'risk-concentration': 'Riesgo de Concentración',
    'risk-sector': 'Concentración Sectorial',
    'risk-correlation': 'Correlación Promedio',
    'risk-var': 'VaR 95% (30d)',
    'risk-maxpos': 'Posición Máxima',
    'risk-beta': 'Beta vs S&P',
    'risk-low-label': 'BAJO',
    'risk-moderate-label': 'MODERADO',
    'risk-high-label': 'ALTO',
    'risk-extreme-label': 'EXTREMO',
    'risk-positions-label': 'posiciones',
    'mc-title': 'Proyección 1 Año',
    'mc-median-return': 'Retorno Mediano',
    'mc-outcome-range': 'Rango 5-95%',
    'mc-prob-gain': 'Prob. Ganancia >10%',
    'mc-prob-dd': 'Prob. DD > -20%',
    'mc-source-live': 'LIVE',
    'mc-source-backtest': 'BACKTEST',
    'mc-day-prefix': 'Día',
    'mc-days-axis': 'Días',
    'mc-start-label': 'Hoy',


    // Dynamic strings
    'near-stop':           '⚠ CERCA DEL STOP',
    'no-rattle-positions': 'SIN POSICIONES RATTLESNAKE',
    'no-catalyst-positions': 'Esperando primer rebalanceo Catalyst',
    'positions-efa-note':  'incl. EFA',
    'live-test-prefix':    'Test en vivo',
    'day-label':           'Día',
    'start-label':         'Inicio',
    'waking-server':       'DESPERTANDO SERVIDOR... INTENTO',
    'paper-trading-live':  'PAPER TRADING EN VIVO',
    'market-closes':       'cierra',
    'market-opens':        'abre',
    'ar-positive-count':   'positivos',
    'ar-of-years-sub':     'años',
    'ml-phase-active':     'activa',
    'ml-phase-label':      'Fase',
    'ml-days-label':       'días',

    // ML phase badges
    'ml-phase1-badge':     'Fase 1',
    'ml-phase1-days':      '0 – 63 días',
    'ml-phase2-badge':     'Fase 2',
    'ml-phase2-days':      '63 – 252 días',
    'ml-phase3-badge':     'Fase 3',
    'ml-phase3-days':      '252+ días',

    // Roadmap
    'rm-heading':        'Camino hacia Lanzamiento',
    'rm-heading-sub':    'HYDRA (Momentum + Rattlesnake + Catalyst + EFA) — Checklist de producción. Cada fase debe completarse antes de operar con capital real.',
    'rm-progress-text':  'completado',
    'rm-summary-title':  'Resumen de Progreso',
    'rm-completed':      'Completado',
    'rm-in-progress':    'En Progreso',
    'rm-pending':        'Pendiente',
    'rm-experiments':    'Experimentos',
    'rm-phase1':         'Fase 1 — Algoritmo',
    'rm-phase2':         'Fase 2 — Datos',
    'rm-phase3':         'Fase 3 — Broker',
    'rm-phase4':         'Fase 4 — Validación',
    'rm-phase5':         'Fase 5 — Fiscalidad',
    'rm-phase6':         'Fase 6 — Lanzamiento',
    'rm-status-done':    'Completado',
    'rm-status-active':  'En Progreso',
    'rm-status-pending': 'Pendiente',
    'rm-decisions-title': 'Decisiones Clave Tomadas',

    // Algorithm page
    'algo-hero-sub':              'Cómo Funciona',
    'algo-hero-tagline':          'Momentum + Rattlesnake (mean-reversion) + Catalyst (trend/gold) + EFA (international) con cash recycling · S&P 500 + EAFE · Sin deuda · Completamente automático',
    'algo-pipe-universe':         'Universo',
    'algo-pipe-universe-detail':  'Las 40 más líquidas',
    'algo-pipe-signals':          'Señales',
    'algo-pipe-signals-detail':   '¿Quién sube más fuerte?',
    'algo-pipe-context':          'Contexto',
    'algo-pipe-context-detail':   '¿El mercado está bien?',
    'algo-pipe-sizing':           'Tamaño',
    'algo-pipe-sizing-detail':    '¿Cuánto en cada una?',
    'algo-pipe-protection':       'Protección',
    'algo-pipe-protection-detail':'¿Cuándo vender?',
    'algo-s1-title':              '¿En qué acciones invertimos?',
    'algo-s2-title':              '¿Cómo elegimos qué comprar?',
    'algo-s3-title':              '¿Cómo sabe si el mercado está bien o mal?',
    'algo-s4-title':              '¿Cómo nos protegemos de pérdidas?',
    'algo-s5-title':              '¿Cuánto invertimos y cuándo?',
    'algo-s6-title':              'Rattlesnake + EFA + Cash Recycling',
    'algo-s7-title':              '¿Cómo anticipa las crisis antes de que lleguen?',
    'algo-s8-title':              '¿Cómo aprende de sus propios resultados?',
    'algo-s9-title':              'Parámetros Técnicos',
    'algo-s9-subtitle':           '(para expertos)',
    'algo-s9-full':               'Parámetros Técnicos <span style="font-size:13px;font-weight:400;color:var(--text-tertiary);">(para expertos)</span>',

    // ML page
    'ml-engine-title':    'Motor de Aprendizaje',
    'ml-overview-desc':   'Sistema progresivo de aprendizaje automático que observa cada decisión del algoritmo HYDRA y construye modelos estadísticos a medida que se acumulan datos.',
    'ml-completed-trades': 'Trades Completados',
    'ml-win-rate':        'Win Rate',
    'ml-avg-return':      'Retorno Medio',
    'ml-total-pnl':       'P&L Total',
    'ml-trading-days':    'Días de Trading',
    'ml-learning-phase':  'Fase ML',
    'ml-kpi-trades':      'Trades Completados',
    'ml-kpi-winrate':     'Win Rate',
    'ml-kpi-avgreturn':   'Retorno Medio',
    'ml-kpi-pnl':         'P&L Total',
    'ml-kpi-days':        'Días de Trading',
    'ml-kpi-phase':       'Fase ML',
    'ml-decisions':       'decisiones',
    'ml-days-to-phase2':  'días para Phase 2',
    'ml-pipe-engine':     'Motor HYDRA',
    'ml-pipe-engine-sub': 'Ejecuta trades',
    'ml-pipe-logger-sub':   'Captura 30+ features por decisión',
    'ml-pipe-outcome-sub':  'Vincula resultados reales',
    'ml-pipe-learning-sub': 'Entrena modelos según fase',
    'ml-pipe-insight-sub':  'Sugiere ajustes (>90% confianza)',
    'ml-phase1-title':    'Observar y Registrar',
    'ml-phase1-desc':     'Mean/median return, win rate, stop rate, breakdowns por régimen, sector, volatilidad. Bootstrap 95% CI.',
    'ml-phase2-title':    'Primeras Señales',
    'ml-phase2-desc':     'Ridge Regression para retorno, Logistic Regression para win/loss. TimeSeriesSplit CV. Feature importance.',
    'ml-phase3-title':    'ML Supervisado Completo',
    'ml-phase3-desc':     'LightGBM o RandomForest con 5-fold TimeSeriesSplit. Feature importance para monitorear signal decay.',
    'ml-interpret-live-title': 'Análisis Paper Trading',
    'ml-interpret-bt-title':   'Análisis Backtest',
    'ml-cycle-title':     'Ciclos de 5 Días — HYDRA vs S&P 500',
    'ml-loading':         'Cargando...',
    'ml-no-cycles':       'No hay ciclos completados aún',
    'ml-bt-analysis':     'Análisis Backtest',
    'ml-bt-waiting':      'Esperando análisis del backtest...',
    'ml-live-analysis':   'Análisis Paper Trading',
    'ml-live-waiting':    'Esperando datos de paper trading...',

    // Footer
    'footer-disclaimer': 'This dashboard is for informational and educational purposes only. Not investment advice. Past performance does not guarantee future results. All trading involves risk of loss. HYDRA is a quantitative research project in paper trading phase.',

    // Misc dynamic
    'no-universe':        'No universe loaded',
    'recycling-active':   'Recycling Active',
    'no-recycling':       'No Recycling',
    'position-singular':  'Posición',
    'position-plural':    'Posiciones',
    'tooltip-last-update': 'Última actualización',
    'tooltip-next-in':     'Próxima en',
    'market-label':        'Mercado',
    'value-label':         'Valor',
    'tt-sector':           'Sector',
    'tt-value':            'Valor',
    'tt-price':            'Precio',
    'tt-shares':           'Acciones',
    'tt-days':             'Días',
    'tt-remaining':        'quedan',
    'ml-waiting-analysis': 'Esperando analisis...',
    'p2p-axis-return':     'RETORNO %',
    'p2p-axis-days':       'DÍAS EN POSICIÓN',

    // Error badges
    'cl-error-text':       'Error al cargar ciclos',
    'mc-error-badge':      'ERROR',
    'risk-error-badge':    'ERROR',
    'ta-error-badge':      'ERROR',
    'eq-error-badge':      'ERROR',
    'ar-error-badge':      'ERROR',
    'fc-error-text':       'Error al cargar comparativa de fondos'
  },

  en: {
    // Header
    'hdr-market-closed':   'MARKET CLOSED',
    'hdr-waiting-signal':  'WAITING FOR SIGNAL 15:30',
    'hdr-preclose-open':   'PRE-CLOSE WINDOW OPEN',
    'hdr-moc-sent':        'MOC ORDERS SENT',
    'offline-banner':      'CONNECTING TO SERVER...',

    // Tabs
    'tab-dashboard':  'Dashboard',
    'tab-roadmap':    'Roadmap',
    'tab-algorithm':  'Algorithm',
    'tab-funds':      'Comparison',
    'tab-analytics':  'Analytics',
    'tab-ml':         'ML',

    // Dashboard Narrative Sections
    'ds-today-label':     'Current Status',
    'ds-today-title':     'Real-Time Performance',
    'ds-today-insight':   'HYDRA vs S&P 500 \u2014 daily and cumulative since live test inception',
    'ds-regime-label':    'Regime',
    'ds-regime-title':    'Market Regime',
    'ds-regime-insight':  'The market thermometer determines how many positions to hold and the macro overlay adjusts exposure',
    'ds-strat-label':     'Positions',
    'ds-strat-title':     'Active Strategies',
    'ds-strat-insight':   '4 complementary strategies with cash recycling \u2014 momentum, mean-reversion, macro trend, and international exposure',
    'ds-track-label':     'Evidence',
    'ds-track-title':     'Track Record',
    'ds-track-insight':   '26 years of survivorship-corrected backtesting, risk analysis, and Monte Carlo projection',

    // Fund Comparison
    'fc-hero-sub':        'How does HYDRA compare to real funds?',
    'fc-hero-tagline':    'Backtest 2000\u20132026 \u00b7 Yahoo Finance adjusted close prices (dividends reinvested) \u00b7 Costs included',
    'fc-metrics-title':   'Key Metrics',
    'fc-equity-title':    'Growth of $100K (Real Monthly Data)',
    'fc-crisis-title':    'Crisis Performance',
    'fc-annual-title':    'Annual Returns (%)',
    'fc-notes-title':     'Notes & Sources',
    'fc-th-fund':         'Fund',
    'fc-th-type':         'Type',
    'fc-th-since':        'Since',
    'fc-th-vol':          'Volatility',
    'fc-th-cumulative':   'Cumulative',
    'fc-th-expense':      'Cost',

    // Hero Section
    'hero-tagline':          'Momentum + Mean-Reversion + International · Cash Recycling · S&P 500 + EAFE · Long-Only',
    'hero-cagr-context':     'Survivorship-corrected (882 tickers)',
    'hero-sharpe-context':   'Risk-adjusted',
    'hero-maxdd-context':    'vs −55.2% SPY',
    'hero-posyears-label':   'Positive Years',
    'hero-posyears-context': '81% win rate by year',
    'hero-beats-label':      'Beats S&P',
    'hero-beats-context':    'years with alpha > 0',
    'hero-alpha-label':      'Avg Alpha',
    'hero-alpha-context':    'per year vs S&P 500',
    'hero-strategies-label':   'Strategies',
    'hero-strategies-context': 'Momentum + Rattle + EFA',
    'hero-hold-label':       'Hold Period',
    'hero-hold-value':       '5 days',
    'hero-hold-context':     'Weekly rotation cycle',
    'hero-growth-label':     'Growth',
    'hero-growth-context':   '2000–2026 backtest',
    'hero-avgalpha-label':     'Avg Alpha',
    'hero-avgalpha-context':   'per year vs S&P 500',
    'hero-medianalpha-label':  'Median Alpha',
    'hero-medianalpha-context':'per year vs S&P 500',
    'hero-alphapositive-label':'Alpha Positive',
    'hero-bestalpha-label':    'Best Alpha',
    'hero-worstalpha-label':   'Worst Alpha',
    'hero-feat-experiments':   '68 Experiments',
    'hero-feat-noleverage':    'No Leverage',
    'hero-feat-cashrecycling': 'Cash Recycling',
    'hero-feat-noblackbox':    'No Black Box',
    'hero-disclaimer':       'Past performance does not guarantee future results. This is a live paper trading test, not investment advice.',

    // Preclose
    'preclose-closed': 'MARKET CLOSED',

    // Perf Banner
    'perf-today':          'Today',
    'perf-overall':        'Overall',
    'perf-beating':        'Beating S&P 500',
    'perf-behind':         'Behind S&P 500',
    'perf-vs':             'vs S&P 500',
    'perf-period':         'Live test since',
    'perf-backtest-label': 'Backtest (2000–2026)',

    // Metric Cards
    'metric-portfolio': 'Portfolio Value',
    'metric-cagr':      'Expected CAGR',
    'metric-cagr-sub':  'HYDRA (Momentum + Rattlesnake + Catalyst + EFA) | No leverage',
    'metric-cash':      'Cash',
    'metric-drawdown':  'Drawdown',
    'metric-positions': 'Positions',
    'metric-invested':  'Invested',
    'metric-peak':      'Peak',

    // Regime Band
    'regime-score':       'Regime Score',
    'regime-consecutive': 'Consecutive',
    'regime-risk-on':     'RISK ON',
    'regime-risk-off':    'RISK OFF',
    'regime-transition':  'TRANSITION',
    'regime-caution':     'CAUTION',

    // Overlay
    'overlay-title': 'Macro Overlay',

    // HYDRA header
    'hydra-header-sub': '4 strategies · Cash Recycling active · Segregated capital',

    // Strategy labels
    'strategy-1':         'STRATEGY 1',
    'strategy-2':         'STRATEGY 2',
    'strategy-3':         'STRATEGY 3',
    'strat-desc-momentum': 'Buys the top risk-adjusted momentum stocks (90d return / 63d volatility) from the S&P 500 top-40. Rotates every 5 days with volatility-scaled adaptive stops.',
    'strat-desc-rattle':   'Buys S&P 100 stocks that drop ≥8% in 5 days with RSI(5)<25 and uptrend filter. Target +4%, stop −5%, max 8-day hold.',
    'strat-desc-catalyst': 'Holds macro trend ETFs (TLT, GLD, DBC) above their SMA200, plus a permanent gold allocation. Rebalances every 5 days.',
    'strat-desc-efa':      'Idle cash after recycling parks in EFA (international developed markets) when EFA > SMA200. Liquidated if active strategies need capital.',
    'strat-invested':     'Invested',
    'strat-return':       'Return',
    'strat-positions':    'Positions',
    'strat-loading':      'Loading positions...',
    'strat-no-positions': 'NO POSITIONS',
    'strat-rattle-waiting': 'Waiting for ≥8% drop + RSI<25 in S&P 100',

    // Position cards
    'pos-today':  'Today',
    'pos-entry':  'Entry',
    'pos-target': 'Target',
    'pos-stop':   'Stop',

    // P2P Scatter
    'p2p-title':     'Peer-to-Peer — Position Comparison',
    'p2p-positions': 'positions',
    'p2p-best':      'Best Position',
    'p2p-worst':     'Worst Position',
    'p2p-avg':       'Avg Return',
    'p2p-total-val': 'Total Value',

    // Annual Returns
    'ar-title':           'Annual Returns — HYDRA vs S&P 500',
    'ar-hydra-pos':       'HYDRA positive',
    'ar-hydra-neg':       'HYDRA negative',
    'ar-positive-years':  'Positive years',
    'ar-of-years':        'of',
    'ar-years':           'years',
    'ar-beats-sp':        'Beats S&P',
    'ar-years-alpha':     'years with alpha > 0',
    'ar-loses-sp':        'Loses to S&P',
    'ar-years-alpha-neg': 'years with alpha < 0',
    'ar-avg-alpha':       'Avg alpha',
    'ar-pp-year':         'pp / year vs S&P',

    // Trade Analytics
    'ta-title': 'Trade Analysis — Backtest',
    'risk-title': 'Risk Monitor',
    'risk-concentration': 'Concentration Risk',
    'risk-sector': 'Sector Concentration',
    'risk-correlation': 'Average Correlation',
    'risk-var': 'VaR 95% (30d)',
    'risk-maxpos': 'Max Position',
    'risk-beta': 'Beta vs S&P',
    'risk-low-label': 'LOW',
    'risk-moderate-label': 'MODERATE',
    'risk-high-label': 'HIGH',
    'risk-extreme-label': 'EXTREME',
    'risk-positions-label': 'positions',
    'mc-title': '1-Year Projection',
    'mc-median-return': 'Median Return',
    'mc-outcome-range': '5-95% Range',
    'mc-prob-gain': 'Prob. Gain >10%',
    'mc-prob-dd': 'Prob. DD > -20%',
    'mc-source-live': 'LIVE',
    'mc-source-backtest': 'BACKTEST',
    'mc-day-prefix': 'Day',
    'mc-days-axis': 'Days',
    'mc-start-label': 'Today',


    // Dynamic strings
    'near-stop':           '⚠ NEAR STOP',
    'no-rattle-positions': 'NO RATTLESNAKE POSITIONS',
    'no-catalyst-positions': 'Waiting for first Catalyst rebalance',
    'positions-efa-note':  'incl. EFA',
    'live-test-prefix':    'Live test',
    'day-label':           'Day',
    'start-label':         'Start',
    'waking-server':       'WAKING SERVER... ATTEMPT',
    'paper-trading-live':  'PAPER TRADING LIVE',
    'market-closes':       'closes',
    'market-opens':        'opens',
    'ar-positive-count':   'positive',
    'ar-of-years-sub':     'years',
    'ml-phase-active':     'active',
    'ml-phase-label':      'Phase',
    'ml-days-label':       'days',

    // ML phase badges
    'ml-phase1-badge':     'Phase 1',
    'ml-phase1-days':      '0 – 63 days',
    'ml-phase2-badge':     'Phase 2',
    'ml-phase2-days':      '63 – 252 days',
    'ml-phase3-badge':     'Phase 3',
    'ml-phase3-days':      '252+ days',

    // Roadmap
    'rm-heading':        'Road to Launch',
    'rm-heading-sub':    'HYDRA (Momentum + Rattlesnake + Catalyst + EFA) — Production checklist. Each phase must be completed before trading with real capital.',
    'rm-progress-text':  'completed',
    'rm-summary-title':  'Progress Summary',
    'rm-completed':      'Completed',
    'rm-in-progress':    'In Progress',
    'rm-pending':        'Pending',
    'rm-experiments':    'Experiments',
    'rm-phase1':         'Phase 1 — Algorithm',
    'rm-phase2':         'Phase 2 — Data',
    'rm-phase3':         'Phase 3 — Broker',
    'rm-phase4':         'Phase 4 — Validation',
    'rm-phase5':         'Phase 5 — Tax Optimization',
    'rm-phase6':         'Phase 6 — Launch',
    'rm-status-done':    'Completed',
    'rm-status-active':  'In Progress',
    'rm-status-pending': 'Pending',
    'rm-decisions-title': 'Key Decisions Made',

    // Algorithm page
    'algo-hero-sub':              'How It Works',
    'algo-hero-tagline':          'Momentum + Rattlesnake (mean-reversion) + Catalyst (trend/gold) + EFA (international) with cash recycling · S&P 500 + EAFE · No debt · Fully automated',
    'algo-pipe-universe':         'Universe',
    'algo-pipe-universe-detail':  'Top 40 most liquid',
    'algo-pipe-signals':          'Signals',
    'algo-pipe-signals-detail':   'Who is rising fastest?',
    'algo-pipe-context':          'Context',
    'algo-pipe-context-detail':   'Is the market healthy?',
    'algo-pipe-sizing':           'Sizing',
    'algo-pipe-sizing-detail':    'How much in each?',
    'algo-pipe-protection':       'Protection',
    'algo-pipe-protection-detail':'When to sell?',
    'algo-s1-title':              'Which stocks do we invest in?',
    'algo-s2-title':              'How do we choose what to buy?',
    'algo-s3-title':              'How does it know if the market is healthy or not?',
    'algo-s4-title':              'How do we protect against losses?',
    'algo-s5-title':              'How much do we invest and when?',
    'algo-s6-title':              'Rattlesnake + EFA + Cash Recycling',
    'algo-s7-title':              'How does it anticipate crises before they arrive?',
    'algo-s8-title':              'How does it learn from its own results?',
    'algo-s9-title':              'Technical Parameters',
    'algo-s9-subtitle':           '(for experts)',
    'algo-s9-full':               'Technical Parameters <span style="font-size:13px;font-weight:400;color:var(--text-tertiary);">(for experts)</span>',

    // ML page
    'ml-engine-title':    'Learning Engine',
    'ml-overview-desc':   'Progressive machine learning system that observes every HYDRA algorithm decision and builds statistical models as data accumulates.',
    'ml-completed-trades': 'Completed Trades',
    'ml-win-rate':        'Win Rate',
    'ml-avg-return':      'Avg Return',
    'ml-total-pnl':       'Total P&L',
    'ml-trading-days':    'Trading Days',
    'ml-learning-phase':  'ML Phase',
    'ml-kpi-trades':      'Completed Trades',
    'ml-kpi-winrate':     'Win Rate',
    'ml-kpi-avgreturn':   'Avg Return',
    'ml-kpi-pnl':         'Total P&L',
    'ml-kpi-days':        'Trading Days',
    'ml-kpi-phase':       'ML Phase',
    'ml-decisions':       'decisions',
    'ml-days-to-phase2':  'days to Phase 2',
    'ml-pipe-engine':     'HYDRA Engine',
    'ml-pipe-engine-sub': 'Executes trades',
    'ml-pipe-logger-sub':   'Captures 30+ features per decision',
    'ml-pipe-outcome-sub':  'Links real outcomes',
    'ml-pipe-learning-sub': 'Trains models by phase',
    'ml-pipe-insight-sub':  'Suggests adjustments (>90% confidence)',
    'ml-phase1-title':    'Observe and Record',
    'ml-phase1-desc':     'Mean/median return, win rate, stop rate, breakdowns by regime, sector, volatility. Bootstrap 95% CI.',
    'ml-phase2-title':    'First Signals',
    'ml-phase2-desc':     'Ridge Regression for return, Logistic Regression for win/loss. TimeSeriesSplit CV. Feature importance.',
    'ml-phase3-title':    'Full Supervised ML',
    'ml-phase3-desc':     'LightGBM or RandomForest with 5-fold TimeSeriesSplit. Feature importance to monitor signal decay.',
    'ml-interpret-live-title': 'Paper Trading Analysis',
    'ml-interpret-bt-title':   'Backtest Analysis',
    'ml-cycle-title':     '5-Day Cycles — HYDRA vs S&P 500',
    'ml-loading':         'Loading...',
    'ml-no-cycles':       'No completed cycles yet',
    'ml-bt-analysis':     'Backtest Analysis',
    'ml-bt-waiting':      'Waiting for backtest analysis...',
    'ml-live-analysis':   'Paper Trading Analysis',
    'ml-live-waiting':    'Waiting for paper trading data...',

    // Footer
    'footer-disclaimer': 'This dashboard is for informational and educational purposes only. Not investment advice. Past performance does not guarantee future results. All trading involves risk of loss. HYDRA is a quantitative research project in paper trading phase.',

    // Misc dynamic
    'no-universe':        'No universe loaded',
    'recycling-active':   'Recycling Active',
    'no-recycling':       'No Recycling',
    'position-singular':  'Position',
    'position-plural':    'Positions',
    'tooltip-last-update': 'Last update',
    'tooltip-next-in':     'Next in',
    'market-label':        'Market',
    'value-label':         'Value',
    'tt-sector':           'Sector',
    'tt-value':            'Value',
    'tt-price':            'Price',
    'tt-shares':           'Shares',
    'tt-days':             'Days',
    'tt-remaining':        'remaining',
    'ml-waiting-analysis': 'Waiting for analysis...',
    'p2p-axis-return':     'RETURN %',
    'p2p-axis-days':       'DAYS IN POSITION',

    // Error badges
    'cl-error-text':       'Failed to load cycles',
    'mc-error-badge':      'ERROR',
    'risk-error-badge':    'ERROR',
    'ta-error-badge':      'ERROR',
    'eq-error-badge':      'ERROR',
    'ar-error-badge':      'ERROR',
    'fc-error-text':       'Failed to load fund comparison'
  }
};

/* ---- Helper functions ---- */

function t(key) {
  return (TRANSLATIONS[currentLang] && TRANSLATIONS[currentLang][key]) || key;
}

function setLang(lang) {
  currentLang = lang;
  localStorage.setItem('hydra-lang', lang);

  // Update all elements with data-i18n (textContent)
  document.querySelectorAll('[data-i18n]').forEach(function(el) {
    var key = el.getAttribute('data-i18n');
    el.textContent = t(key);
  });

  // Update all elements with data-i18n-html (innerHTML)
  // Safe: all content is developer-controlled static strings, never user input
  document.querySelectorAll('[data-i18n-html]').forEach(function(el) {
    var key = el.getAttribute('data-i18n-html');
    el.innerHTML = t(key);
  });

  // Toggle lang-specific content blocks
  document.querySelectorAll('.lang-es').forEach(function(el) {
      el.style.display = lang === 'es' ? '' : 'none';
  });
  document.querySelectorAll('.lang-en').forEach(function(el) {
      el.style.display = lang === 'en' ? '' : 'none';
  });

  updateLangToggle();

  if (typeof refreshDashboard === 'function') {
    refreshDashboard();
  }
}

function toggleLang() {
  setLang(currentLang === 'es' ? 'en' : 'es');
}

function updateLangToggle() {
  var btn = document.getElementById('lang-toggle');
  if (!btn) return;

  var esSpan = btn.querySelector('[data-lang="es"]');
  var enSpan = btn.querySelector('[data-lang="en"]');

  if (esSpan) {
    esSpan.classList.toggle('lang-active', currentLang === 'es');
    esSpan.classList.toggle('lang-inactive', currentLang !== 'es');
  }
  if (enSpan) {
    enSpan.classList.toggle('lang-active', currentLang === 'en');
    enSpan.classList.toggle('lang-inactive', currentLang !== 'en');
  }
}

/* ---- Initialize on DOM ready ---- */
document.addEventListener('DOMContentLoaded', function() {
  setLang(currentLang);
});
