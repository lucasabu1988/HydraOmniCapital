"""
AlphaMax OmniCapital v1.0 - LIVE Market Analysis
Analisis de oportunidades en tiempo real

Copyright (c) 2026 Investment Capital Firm
Version: 1.0.0
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))

import pandas as pd
import numpy as np
from datetime import datetime, timedelta

from src.data.data_provider import YFinanceProvider
from src.signals.technical import TechnicalSignals, SignalType


def get_universe_50():
    """50 principales acciones para analisis"""
    return [
        'AAPL', 'MSFT', 'GOOGL', 'AMZN', 'NVDA', 'META', 'TSLA', 'BRK-B',
        'JPM', 'V', 'JNJ', 'UNH', 'XOM', 'WMT', 'PG', 'MA', 'HD', 'CVX',
        'MRK', 'ABBV', 'PEP', 'KO', 'PFE', 'AVGO', 'COST', 'TMO', 'DIS',
        'ABT', 'ADBE', 'BAC', 'ACN', 'WFC', 'CRM', 'VZ', 'DHR', 'NKE',
        'TXN', 'PM', 'NEE', 'AMD', 'CMCSA', 'RTX', 'HON', 'INTC', 'IBM',
        'QCOM', 'AMGN', 'SPY', 'QQQ'
    ]


def calculate_value_score(pe_ratio, pb_ratio, ps_ratio, ev_ebitda, roe, peg_ratio):
    """Score de valoracion mejorado"""
    score = 50
    
    # P/E Score
    if pe_ratio and pe_ratio > 0:
        if pe_ratio < 12:
            score += 20
        elif pe_ratio < 18:
            score += 15
        elif pe_ratio < 25:
            score += 8
        elif pe_ratio > 40:
            score -= 15
    
    # P/B Score
    if pb_ratio and pb_ratio > 0:
        if pb_ratio < 1.5:
            score += 18
        elif pb_ratio < 2.5:
            score += 10
        elif pb_ratio > 5:
            score -= 12
    
    # PEG Ratio (mejor metrica de valor)
    if peg_ratio and peg_ratio > 0:
        if peg_ratio < 1.0:
            score += 15
        elif peg_ratio < 1.5:
            score += 8
        elif peg_ratio > 2.5:
            score -= 10
    
    # EV/EBITDA
    if ev_ebitda and ev_ebitda > 0:
        if ev_ebitda < 10:
            score += 12
        elif ev_ebitda < 15:
            score += 6
        elif ev_ebitda > 25:
            score -= 8
    
    # ROE Bonus
    if roe and roe > 0.20:
        score += 10
    elif roe and roe > 0.15:
        score += 5
    
    return max(0, min(100, score))


def analyze_market_live():
    """Analisis de mercado en tiempo real"""
    
    print("=" * 100)
    print("ALPHAMAX OMNICAPITAL v1.0 - LIVE MARKET ANALYSIS")
    print("=" * 100)
    print(f"Fecha: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("Modo: Analisis de Oportunidades de Compra")
    print("=" * 100)
    
    symbols = get_universe_50()
    provider = YFinanceProvider()
    
    # Descargar datos
    print("\n[1/4] Descargando datos de mercado...")
    end_date = datetime.now()
    start_date = end_date - timedelta(days=180)  # 6 meses de historial
    
    prices = provider.get_historical_prices(symbols, start_date=start_date, end_date=end_date)
    current_prices = provider.get_current_price(symbols)
    
    print(f"      Datos descargados: {len(prices)} dias x {len(prices.columns)} simbolos")
    
    # Obtener fundamentales
    print("\n[2/4] Analizando datos fundamentales...")
    fundamentals = {}
    for symbol in symbols:
        try:
            info = provider.get_ticker_info(symbol)
            fundamentals[symbol] = {
                'pe_ratio': info.get('trailing_pe'),
                'forward_pe': info.get('forward_pe'),
                'pb_ratio': info.get('pb_ratio'),
                'ps_ratio': info.get('priceToSalesTrailing12Months'),
                'ev_ebitda': info.get('enterpriseToEbitda'),
                'peg_ratio': info.get('pegRatio'),
                'roe': info.get('returnOnEquity'),
                'debt_equity': info.get('debtToEquity'),
                'current_ratio': info.get('currentRatio'),
                'dividend_yield': info.get('dividendYield'),
                'sector': info.get('sector', 'Unknown'),
                'market_cap': info.get('marketCap', 0),
                'beta': info.get('beta', 1.0),
                'revenue_growth': info.get('revenueGrowth'),
                'earnings_growth': info.get('earningsGrowth')
            }
        except:
            fundamentals[symbol] = {'sector': 'Unknown'}
    
    # Calcular scores
    print("\n[3/4] Calculando scores de valoracion...")
    analysis_results = []
    
    tech_config = {
        'entry': [
            {'name': 'momentum', 'weight': 0.30, 'lookback': 60, 'min_momentum': 0.02},
            {'name': 'trend', 'weight': 0.20, 'short_ma': 10, 'long_ma': 25}
        ]
    }
    tech_signals = TechnicalSignals(tech_config)
    
    for symbol in symbols:
        if symbol not in prices.columns or symbol not in current_prices:
            continue
        
        current_price = current_prices.get(symbol)
        if not current_price or current_price <= 0:
            continue
        
        # Datos fundamentales
        f = fundamentals.get(symbol, {})
        
        # Score de valoracion
        value_score = calculate_value_score(
            f.get('pe_ratio'),
            f.get('pb_ratio'),
            f.get('ps_ratio'),
            f.get('ev_ebitda'),
            f.get('roe'),
            f.get('peg_ratio')
        )
        
        # Analisis tecnico
        symbol_prices = prices[symbol].dropna()
        if len(symbol_prices) >= 30:
            tech_analysis = tech_signals.analyze_all_signals(symbol, symbol_prices)
            tech_score = tech_analysis['final_strength'] * 100 if tech_analysis['final_signal'] == SignalType.BUY else 0
            trend = "ALCISTA" if tech_analysis['final_signal'] == SignalType.BUY else "NEUTRAL/BAJISTA"
        else:
            tech_score = 0
            trend = "N/A"
        
        # Score combinado
        combined_score = value_score * 0.6 + tech_score * 0.4
        
        # Calcular stop loss y take profit sugeridos
        if len(symbol_prices) >= 14:
            atr = symbol_prices.rolling(14).std().iloc[-1]
            suggested_sl = current_price - (atr * 1.5)
            suggested_tp = current_price + (atr * 4)  # Ratio 1:2.5
        else:
            suggested_sl = current_price * 0.95
            suggested_tp = current_price * 1.15
        
        analysis_results.append({
            'symbol': symbol,
            'current_price': current_price,
            'value_score': value_score,
            'tech_score': tech_score,
            'combined_score': combined_score,
            'sector': f.get('sector', 'Unknown'),
            'pe_ratio': f.get('pe_ratio'),
            'pb_ratio': f.get('pb_ratio'),
            'peg_ratio': f.get('peg_ratio'),
            'roe': f.get('roe'),
            'debt_equity': f.get('debt_equity'),
            'dividend_yield': f.get('dividend_yield'),
            'market_cap': f.get('market_cap'),
            'beta': f.get('beta'),
            'trend': trend,
            'suggested_sl': suggested_sl,
            'suggested_tp': suggested_tp,
            'revenue_growth': f.get('revenue_growth'),
            'earnings_growth': f.get('earnings_growth')
        })
    
    # Ordenar por score combinado
    df_results = pd.DataFrame(analysis_results)
    df_results = df_results.sort_values('combined_score', ascending=False)
    
    # === MOSTRAR RESULTADOS ===
    print("\n" + "=" * 100)
    print("TOP 20 OPORTUNIDADES DE COMPRA - OMNICAPITAL v1.0")
    print("=" * 100)
    print(f"{'#':<3} {'Symbol':<6} {'Price':>10} {'Val':>5} {'Tec':>5} {'Total':>6} {'P/E':>7} {'P/B':>6} {'PEG':>6} {'Sector':<20}")
    print("-" * 100)
    
    top_20 = df_results.head(20)
    for i, (_, row) in enumerate(top_20.iterrows(), 1):
        pe_str = f"{row['pe_ratio']:.1f}" if pd.notna(row['pe_ratio']) else "N/A"
        pb_str = f"{row['pb_ratio']:.1f}" if pd.notna(row['pb_ratio']) else "N/A"
        peg_str = f"{row['peg_ratio']:.2f}" if pd.notna(row['peg_ratio']) else "N/A"
        
        print(f"{i:<3} {row['symbol']:<6} ${row['current_price']:>8.2f} "
              f"{row['value_score']:>5.0f} {row['tech_score']:>5.0f} {row['combined_score']:>6.0f} "
              f"{pe_str:>7} {pb_str:>6} {peg_str:>6} {row['sector'][:19]:<20}")
    
    # === OPORTUNIDADES RECOMENDADAS ===
    print("\n" + "=" * 100)
    print("RECOMENDACIONES OFICIALES OMNICAPITAL v1.0")
    print("=" * 100)
    
    # Filtrar oportunidades fuertes
    strong_opportunities = df_results[
        (df_results['combined_score'] >= 60) & 
        (df_results['value_score'] >= 55) &
        (df_results['current_price'] > 0)
    ].head(10)
    
    if len(strong_opportunities) == 0:
        print("\nNo se encontraron oportunidades que cumplan todos los criterios.")
        print("Recomendacion: Esperar a mejor entrada o revisar condiciones de mercado.")
    else:
        print(f"\nEncontradas {len(strong_opportunities)} oportunidades FUERTES:")
        print("-" * 100)
        
        for i, (_, row) in enumerate(strong_opportunities.iterrows(), 1):
            print(f"\n>>> OPCION {i}: {row['symbol']} ({row['sector']})")
            print(f"    Precio Actual:     ${row['current_price']:.2f}")
            print(f"    Score Valoracion:  {row['value_score']:.0f}/100")
            print(f"    Score Tecnico:     {row['tech_score']:.0f}/100")
            print(f"    Score TOTAL:       {row['combined_score']:.0f}/100")
            print(f"    Tendencia:         {row['trend']}")
            
            # Metricas clave
            print(f"\n    -- Metricas Fundamentales --")
            if pd.notna(row['pe_ratio']):
                print(f"    P/E Ratio:         {row['pe_ratio']:.2f}")
            if pd.notna(row['pb_ratio']):
                print(f"    P/B Ratio:         {row['pb_ratio']:.2f}")
            if pd.notna(row['peg_ratio']):
                print(f"    PEG Ratio:         {row['peg_ratio']:.2f}")
            if pd.notna(row['roe']):
                print(f"    ROE:               {row['roe']:.1%}")
            if pd.notna(row['dividend_yield']):
                print(f"    Dividend Yield:    {row['dividend_yield']:.2%}")
            if pd.notna(row['revenue_growth']):
                print(f"    Revenue Growth:    {row['revenue_growth']:.1%}")
            
            print(f"\n    -- Sugerencias de Trading --")
            print(f"    Stop Loss (5%):    ${row['suggested_sl']:.2f}")
            print(f"    Take Profit:       ${row['suggested_tp']:.2f}")
            print(f"    Potencial Upside:  {((row['suggested_tp']/row['current_price'])-1)*100:.1f}%")
            
            # Tamaño de posicion sugerido
            position_value = 25000  # $25k por posicion para portfolio de $1M
            shares = int(position_value / row['current_price'])
            print(f"    Posicion Sugerida: {shares} acciones (~${shares*row['current_price']:,.0f})")
    
    # === RESUMEN POR SECTOR ===
    print("\n" + "=" * 100)
    print("DISTRIBUCION POR SECTOR - Top Oportunidades")
    print("=" * 100)
    
    sector_analysis = df_results[df_results['combined_score'] >= 55].groupby('sector').agg({
        'symbol': 'count',
        'combined_score': 'mean',
        'value_score': 'mean'
    }).sort_values('symbol', ascending=False)
    
    print(f"{'Sector':<25} {'Cantidad':>10} {'Score Prom':>12} {'Val Prom':>12}")
    print("-" * 100)
    for sector, row in sector_analysis.iterrows():
        print(f"{sector:<25} {int(row['symbol']):>10} {row['combined_score']:>12.1f} {row['value_score']:>12.1f}")
    
    # === MERCADO EN GENERAL ===
    print("\n" + "=" * 100)
    print("CONDICIONES DE MERCADO")
    print("=" * 100)
    
    if 'SPY' in current_prices and 'QQQ' in current_prices:
        spy_price = current_prices['SPY']
        qqq_price = current_prices['QQQ']
        
        # Calcular rendimiento ultimos 20 dias
        if 'SPY' in prices.columns and len(prices['SPY']) >= 20:
            spy_20d = (spy_price / prices['SPY'].iloc[-20] - 1) * 100
            qqq_20d = (qqq_price / prices['QQQ'].iloc[-20] - 1) * 100 if 'QQQ' in prices.columns else 0
            
            print(f"\n    S&P 500 (SPY):     ${spy_price:.2f} (20d: {spy_20d:+.2f}%)")
            print(f"    Nasdaq (QQQ):      ${qqq_price:.2f} (20d: {qqq_20d:+.2f}%)")
            
            if spy_20d > 5:
                regime = "ALCISTA FUERTE"
            elif spy_20d > 0:
                regime = "ALCISTA MODERADO"
            elif spy_20d > -5:
                regime = "CORRECCION"
            else:
                regime = "BAJISTA"
            
            print(f"\n    Regimen de Mercado: {regime}")
            
            if regime == "ALCISTA FUERTE":
                print("    Recomendacion: Aumentar exposicion, aprovechar momentum")
            elif regime == "CORRECCION":
                print("    Recomendacion: Oportunidad de compra en valoracion")
            elif regime == "BAJISTA":
                print("    Recomendacion: Cautela, mantener stops estrictos")
    
    # === OUTPUT CSV ===
    output_file = f"reports/omnicapital_live_analysis_{datetime.now().strftime('%Y%m%d_%H%M')}.csv"
    df_results.to_csv(output_file, index=False)
    print(f"\n>> Resultados completos guardados en: {output_file}")
    
    print("\n" + "=" * 100)
    print("FIN DEL ANALISIS - OMNICAPITAL v1.0")
    print("=" * 100)
    print("\nDISCLAIMER: Este analisis es para fines informativos.")
    print("No constituye asesoramiento financiero. Invertir conlleva riesgos.")
    print("=" * 100)
    
    return df_results


if __name__ == '__main__':
    results = analyze_market_live()
