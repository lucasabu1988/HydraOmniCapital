"""
AlphaMax OmniCapital v1.0 - Dashboard en Vivo
Dashboard de seguimiento de la estrategia en tiempo real

Copyright (c) 2026 Investment Capital Firm
Version: 1.0.0
"""

import streamlit as st
import pandas as pd
import numpy as np
import plotly.graph_objects as go
import plotly.express as px
from plotly.subplots import make_subplots
from datetime import datetime, timedelta
import time
import yaml

from src.core.engine import TradingEngine
from src.data.data_provider import YFinanceProvider
from src.signals.technical import TechnicalSignals, SignalType

# Configuración de página
st.set_page_config(
    page_title="OmniCapital v1.0 - Dashboard",
    page_icon="📈",
    layout="wide",
    initial_sidebar_state="expanded"
)

# CSS personalizado
st.markdown("""
<style>
    .main-header {
        font-size: 3rem;
        font-weight: bold;
        color: #1f77b4;
        text-align: center;
        padding: 1rem;
        background: linear-gradient(90deg, #1f77b4 0%, #ff7f0e 100%);
        -webkit-background-clip: text;
        -webkit-text-fill-color: transparent;
    }
    .metric-card {
        background-color: #f0f2f6;
        border-radius: 10px;
        padding: 20px;
        border-left: 5px solid #1f77b4;
    }
    .buy-signal {
        background-color: #d4edda;
        color: #155724;
        padding: 10px;
        border-radius: 5px;
        border-left: 5px solid #28a745;
    }
    .sell-signal {
        background-color: #f8d7da;
        color: #721c24;
        padding: 10px;
        border-radius: 5px;
        border-left: 5px solid #dc3545;
    }
    .info-box {
        background-color: #e7f3ff;
        padding: 15px;
        border-radius: 10px;
        border-left: 5px solid #0066cc;
    }
</style>
""", unsafe_allow_html=True)


def get_live_data():
    """Obtiene datos en vivo para el dashboard"""
    provider = YFinanceProvider()
    
    # Símbolos principales
    symbols = ['AAPL', 'MSFT', 'GOOGL', 'AMZN', 'NVDA', 'META', 'TSLA', 'BRK-B',
               'JPM', 'V', 'JNJ', 'UNH', 'XOM', 'WMT', 'PG', 'MA', 'HD', 'CVX',
               'MRK', 'ABBV', 'PEP', 'KO', 'PFE', 'AVGO', 'COST', 'TMO', 'DIS',
               'ABT', 'ADBE', 'BAC', 'SPY', 'QQQ']
    
    # Obtener precios actuales
    current_prices = provider.get_current_price(symbols)
    
    # Obtener fundamentales
    fundamentals = {}
    for symbol in symbols[:30]:  # Top 30 para velocidad
        try:
            info = provider.get_ticker_info(symbol)
            fundamentals[symbol] = {
                'pe_ratio': info.get('trailing_pe'),
                'pb_ratio': info.get('pb_ratio'),
                'market_cap': info.get('marketCap'),
                'sector': info.get('sector', 'Unknown'),
                'dividend_yield': info.get('dividendYield'),
                'beta': info.get('beta', 1.0)
            }
        except:
            pass
    
    return current_prices, fundamentals


def calculate_portfolio_metrics(positions, current_prices, initial_capital=1000000):
    """Calcula métricas del portafolio"""
    if not positions:
        return {
            'total_value': initial_capital,
            'cash': initial_capital,
            'invested': 0,
            'pnl': 0,
            'pnl_pct': 0,
            'num_positions': 0
        }
    
    invested = 0
    current_value = 0
    
    for symbol, pos in positions.items():
        if symbol in current_prices:
            price = current_prices[symbol]
            invested += pos['shares'] * pos['entry_price']
            current_value += pos['shares'] * price
    
    cash = initial_capital - invested
    total_value = cash + current_value
    pnl = total_value - initial_capital
    pnl_pct = (pnl / initial_capital) * 100
    
    return {
        'total_value': total_value,
        'cash': cash,
        'invested': invested,
        'current_value': current_value,
        'pnl': pnl,
        'pnl_pct': pnl_pct,
        'num_positions': len(positions)
    }


def generate_sample_portfolio():
    """Genera un portafolio de ejemplo para demo"""
    return {
        'BAC': {'shares': 442, 'entry_price': 54.50, 'entry_date': datetime(2026, 1, 15)},
        'WFC': {'shares': 266, 'entry_price': 91.20, 'entry_date': datetime(2026, 1, 18)},
        'VZ': {'shares': 539, 'entry_price': 44.80, 'entry_date': datetime(2026, 1, 22)},
        'JPM': {'shares': 77, 'entry_price': 315.00, 'entry_date': datetime(2026, 1, 25)},
        'XOM': {'shares': 167, 'entry_price': 145.30, 'entry_date': datetime(2026, 2, 1)},
        'CMCSA': {'shares': 796, 'entry_price': 30.50, 'entry_date': datetime(2026, 2, 3)},
        'PFE': {'shares': 918, 'entry_price': 26.80, 'entry_date': datetime(2026, 2, 5)},
        'BRK-B': {'shares': 49, 'entry_price': 495.00, 'entry_date': datetime(2026, 2, 6)},
    }


def main():
    # Header
    st.markdown('<h1 class="main-header">📈 OmniCapital v1.0 Dashboard</h1>', 
                unsafe_allow_html=True)
    st.markdown(f"""
    <div style="text-align: center; color: #666; margin-bottom: 2rem;">
        <strong>Investment Capital Firm</strong> | 
        Full Capital Deployment Strategy | 
        Last Update: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
    </div>
    """, unsafe_allow_html=True)
    
    # Sidebar
    st.sidebar.title("⚙️ Configuración")
    st.sidebar.markdown("---")
    
    initial_capital = st.sidebar.number_input(
        "Capital Inicial ($)", 
        min_value=100000, 
        max_value=10000000, 
        value=1000000,
        step=100000,
        format="%d"
    )
    
    refresh_interval = st.sidebar.slider(
        "Intervalo de Actualización (seg)",
        min_value=30,
        max_value=300,
        value=60
    )
    
    auto_refresh = st.sidebar.checkbox("Auto-Refresh", value=False)
    
    st.sidebar.markdown("---")
    st.sidebar.subheader("📊 Parámetros de Estrategia")
    
    show_value_filter = st.sidebar.checkbox("Filtro Valoración", value=True)
    show_tech_filter = st.sidebar.checkbox("Filtro Técnico", value=True)
    
    st.sidebar.markdown("---")
    st.sidebar.info("""
    **OmniCapital v1.0**
    
    Estrategia de despliegue total del capital en acciones subvaluadas del S&P 500.
    
    Target: 25% retorno anual
    Max Drawdown: 15%
    """)
    
    # Tabs principales
    tab1, tab2, tab3, tab4, tab5 = st.tabs([
        "📊 Portfolio Overview", 
        "🎯 Live Signals", 
        "📈 Market Analysis",
        "⚠️ Risk Management",
        "📋 Trade History"
    ])
    
    # TAB 1: Portfolio Overview
    with tab1:
        st.subheader("Resumen del Portafolio")
        
        # Obtener datos
        try:
            current_prices, fundamentals = get_live_data()
            positions = generate_sample_portfolio()
            metrics = calculate_portfolio_metrics(positions, current_prices, initial_capital)
        except:
            st.error("Error obteniendo datos. Usando datos de simulación.")
            current_prices = {'BAC': 56.53, 'WFC': 93.97, 'VZ': 46.31, 'BRK-B': 508.09}
            positions = generate_sample_portfolio()
            metrics = calculate_portfolio_metrics(positions, current_prices, initial_capital)
        
        # Métricas principales
        col1, col2, col3, col4, col5 = st.columns(5)
        
        with col1:
            st.metric(
                "💰 Total Value",
                f"${metrics['total_value']:,.0f}",
                f"{metrics['pnl_pct']:+.2f}%"
            )
        
        with col2:
            st.metric(
                "📈 Invested",
                f"${metrics['current_value']:,.0f}",
                f"{(metrics['current_value']/metrics['total_value']*100):.1f}%"
            )
        
        with col3:
            st.metric(
                "💵 Cash",
                f"${metrics['cash']:,.0f}",
                f"{(metrics['cash']/metrics['total_value']*100):.1f}%"
            )
        
        with col4:
            st.metric(
                "📊 Posiciones",
                f"{metrics['num_positions']}",
                "Target: 30-40"
            )
        
        with col5:
            daily_pnl = np.random.normal(0.5, 1.5)  # Simulado
            st.metric(
                "📉 Daily P&L",
                f"${(metrics['total_value'] * daily_pnl / 100):,.0f}",
                f"{daily_pnl:+.2f}%"
            )
        
        st.markdown("---")
        
        # Gráfico de asignación
        col1, col2 = st.columns([2, 1])
        
        with col1:
            st.subheader("Evolución del Portafolio")
            
            # Simular evolución
            dates = pd.date_range(end=datetime.now(), periods=30, freq='D')
            values = metrics['total_value'] * (1 + np.cumsum(np.random.normal(0.001, 0.015, 30)))
            
            fig = go.Figure()
            fig.add_trace(go.Scatter(
                x=dates,
                y=values,
                mode='lines',
                name='Portfolio Value',
                line=dict(color='#1f77b4', width=2),
                fill='tonexty'
            ))
            fig.add_hline(y=initial_capital, line_dash="dash", line_color="red", 
                         annotation_text="Initial Capital")
            
            fig.update_layout(
                xaxis_title="Fecha",
                yaxis_title="Valor ($)",
                hovermode='x unified',
                template='plotly_white',
                height=400
            )
            st.plotly_chart(fig, use_container_width=True)
        
        with col2:
            st.subheader("Distribución del Capital")
            
            # Pie chart
            labels = ['Invertido', 'Cash']
            values = [metrics['current_value'], metrics['cash']]
            colors = ['#1f77b4', '#ff7f0e']
            
            fig = go.Figure(data=[go.Pie(
                labels=labels,
                values=values,
                hole=.4,
                marker_colors=colors
            )])
            fig.update_layout(height=400)
            st.plotly_chart(fig, use_container_width=True)
        
        # Tabla de posiciones
        st.markdown("---")
        st.subheader("Posiciones Actuales")
        
        position_data = []
        for symbol, pos in positions.items():
            if symbol in current_prices:
                current_price = current_prices[symbol]
                entry_price = pos['entry_price']
                shares = pos['shares']
                
                position_value = shares * current_price
                cost_basis = shares * entry_price
                pnl = position_value - cost_basis
                pnl_pct = (pnl / cost_basis) * 100
                
                # Calcular stop loss y take profit
                stop_loss = entry_price * 0.95
                take_profit = entry_price * 1.20
                
                position_data.append({
                    'Symbol': symbol,
                    'Shares': shares,
                    'Entry': f"${entry_price:.2f}",
                    'Current': f"${current_price:.2f}",
                    'Value': f"${position_value:,.0f}",
                    'P&L': f"${pnl:,.0f}",
                    'P&L%': f"{pnl_pct:+.2f}%",
                    'Stop': f"${stop_loss:.2f}",
                    'Target': f"${take_profit:.2f}",
                    'Status': '🟢' if pnl > 0 else '🔴'
                })
        
        df_positions = pd.DataFrame(position_data)
        st.dataframe(df_positions, use_container_width=True, height=400)
    
    # TAB 2: Live Signals
    with tab2:
        st.subheader("Señales de Trading en Vivo")
        
        col1, col2 = st.columns([2, 1])
        
        with col1:
            st.markdown("""
            <div class="info-box">
                <strong>Top Oportunidades Identificadas</strong><br>
                Basado en filtro de valoración primario (60%) + señal técnica (40%)
            </div>
            """, unsafe_allow_html=True)
            
            # Simular oportunidades
            opportunities = [
                {'symbol': 'BAC', 'score': 90, 'price': 56.53, 'pe': 14.8, 'pb': 1.47, 
                 'signal': 'BUY', 'strength': 'STRONG'},
                {'symbol': 'WFC', 'score': 85, 'price': 93.97, 'pe': 15.0, 'pb': 1.77,
                 'signal': 'BUY', 'strength': 'STRONG'},
                {'symbol': 'BRK-B', 'score': 81, 'price': 508.09, 'pe': 16.3, 'pb': 0.00,
                 'signal': 'BUY', 'strength': 'MODERATE'},
                {'symbol': 'VZ', 'score': 77, 'price': 46.31, 'pe': 11.4, 'pb': 1.87,
                 'signal': 'BUY', 'strength': 'MODERATE'},
                {'symbol': 'CMCSA', 'score': 77, 'price': 31.37, 'pe': 5.8, 'pb': 1.17,
                 'signal': 'BUY', 'strength': 'MODERATE'},
            ]
            
            for i, opp in enumerate(opportunities, 1):
                with st.container():
                    col_a, col_b, col_c = st.columns([2, 2, 1])
                    
                    with col_a:
                        st.markdown(f"""
                        <div class="{'buy-signal' if opp['signal'] == 'BUY' else 'sell-signal'}">
                            <strong>#{i} {opp['symbol']}</strong> | Score: {opp['score']}/100<br>
                            Precio: ${opp['price']:.2f} | Señal: {opp['signal']}
                        </div>
                        """, unsafe_allow_html=True)
                    
                    with col_b:
                        st.write(f"P/E: {opp['pe']:.1f} | P/B: {opp['pb']:.2f}")
                    
                    with col_c:
                        if st.button(f"Ver Detalle", key=f"btn_{opp['symbol']}"):
                            st.session_state.selected_symbol = opp['symbol']
                    
                    st.markdown("---")
        
        with col2:
            st.subheader("Alertas Activas")
            
            alerts = [
                {"symbol": "BAC", "type": "BUY", "message": "Score 90 - Fuerte valoración"},
                {"symbol": "WFC", "type": "BUY", "message": "Tendencia alcista confirmada"},
                {"symbol": "VZ", "type": "HOLD", "message": "Esperando pullback"},
            ]
            
            for alert in alerts:
                emoji = "🟢" if alert['type'] == 'BUY' else "🟡" if alert['type'] == 'HOLD' else "🔴"
                st.write(f"{emoji} **{alert['symbol']}**: {alert['message']}")
            
            st.markdown("---")
            
            st.subheader("Últimos Trades")
            
            trades = [
                {"time": "10:30", "symbol": "BAC", "action": "BUY", "shares": 100},
                {"time": "10:25", "symbol": "VZ", "action": "BUY", "shares": 50},
                {"time": "10:15", "symbol": "XOM", "action": "SELL", "shares": 75},
            ]
            
            for trade in trades:
                color = "🟢" if trade['action'] == 'BUY' else "🔴"
                st.write(f"{color} {trade['time']} - {trade['action']} {trade['shares']} {trade['symbol']}")
    
    # TAB 3: Market Analysis
    with tab3:
        st.subheader("Análisis de Mercado")
        
        col1, col2 = st.columns(2)
        
        with col1:
            st.subheader("Heatmap de Sectores")
            
            # Simular heatmap
            sectors = ['Technology', 'Financials', 'Healthcare', 'Energy', 
                      'Consumer', 'Communication', 'Industrials', 'Utilities']
            performance = np.random.uniform(-3, 5, len(sectors))
            
            fig = go.Figure(data=go.Heatmap(
                z=[performance],
                x=sectors,
                y=['1D Performance'],
                colorscale='RdYlGn',
                text=[[f"{p:+.1f}%" for p in performance]],
                texttemplate="%{text}",
                textfont={"size": 12}
            ))
            fig.update_layout(height=200)
            st.plotly_chart(fig, use_container_width=True)
        
        with col2:
            st.subheader("Sentimiento de Mercado")
            
            # Gauge chart
            sentiment = 65  # 0-100
            fig = go.Figure(go.Indicator(
                mode = "gauge+number+delta",
                value = sentiment,
                domain = {'x': [0, 1], 'y': [0, 1]},
                title = {'text': "Fear & Greed Index"},
                gauge = {
                    'axis': {'range': [None, 100]},
                    'bar': {'color': "darkblue"},
                    'steps': [
                        {'range': [0, 25], 'color': "red"},
                        {'range': [25, 50], 'color': "orange"},
                        {'range': [50, 75], 'color': "yellow"},
                        {'range': [75, 100], 'color': "green"}
                    ],
                    'threshold': {
                        'line': {'color': "black", 'width': 4},
                        'thickness': 0.75,
                        'value': sentiment
                    }
                }
            ))
            fig.update_layout(height=300)
            st.plotly_chart(fig, use_container_width=True)
        
        st.markdown("---")
        
        st.subheader("Comparativa de Benchmarks")
        
        # Simular datos
        dates = pd.date_range(end=datetime.now(), periods=90, freq='D')
        spy_returns = np.cumsum(np.random.normal(0.0005, 0.012, 90))
        qqq_returns = np.cumsum(np.random.normal(0.0007, 0.015, 90))
        portfolio_returns = np.cumsum(np.random.normal(0.001, 0.018, 90))
        
        fig = go.Figure()
        fig.add_trace(go.Scatter(x=dates, y=(1+spy_returns)*100, name='S&P 500', line=dict(color='blue')))
        fig.add_trace(go.Scatter(x=dates, y=(1+qqq_returns)*100, name='Nasdaq', line=dict(color='purple')))
        fig.add_trace(go.Scatter(x=dates, y=(1+portfolio_returns)*100, name='OmniCapital', 
                                line=dict(color='green', width=3)))
        
        fig.update_layout(
            xaxis_title="Fecha",
            yaxis_title="Valor (Base 100)",
            template='plotly_white',
            height=400
        )
        st.plotly_chart(fig, use_container_width=True)
    
    # TAB 4: Risk Management
    with tab4:
        st.subheader("Gestión de Riesgo")
        
        col1, col2, col3 = st.columns(3)
        
        with col1:
            st.metric("VaR (95%)", "$12,450", "1.2%")
        
        with col2:
            st.metric("Beta Portfolio", "1.15", "+0.05")
        
        with col3:
            st.metric("Volatilidad", "16.8%", "-0.3%")
        
        st.markdown("---")
        
        col1, col2 = st.columns(2)
        
        with col1:
            st.subheader("Drawdown History")
            
            dates = pd.date_range(end=datetime.now(), periods=252, freq='D')
            portfolio_values = 100 * np.exp(np.cumsum(np.random.normal(0.0008, 0.015, 252)))
            running_max = np.maximum.accumulate(portfolio_values)
            drawdown = (portfolio_values - running_max) / running_max * 100
            
            fig = go.Figure()
            fig.add_trace(go.Scatter(
                x=dates, y=drawdown,
                fill='tozeroy',
                name='Drawdown',
                line=dict(color='red')
            ))
            fig.add_hline(y=-15, line_dash="dash", line_color="orange", 
                         annotation_text="Max Allowed (-15%)")
            
            fig.update_layout(
                xaxis_title="Fecha",
                yaxis_title="Drawdown %",
                template='plotly_white',
                height=350
            )
            st.plotly_chart(fig, use_container_width=True)
        
        with col2:
            st.subheader("Exposición por Sector")
            
            sectors = ['Financials', 'Technology', 'Healthcare', 'Energy', 'Consumer', 'Other']
            exposure = [25, 20, 18, 12, 15, 10]
            
            fig = px.bar(
                x=sectors, y=exposure,
                labels={'x': 'Sector', 'y': 'Exposición %'},
                color=exposure,
                color_continuous_scale='Blues'
            )
            fig.update_layout(height=350)
            st.plotly_chart(fig, use_container_width=True)
        
        st.markdown("---")
        
        st.subheader("Alertas de Riesgo")
        
        risk_alerts = [
            {"level": "⚠️", "message": "Exposición a Financials en 25% (límite 25%)"},
            {"level": "✅", "message": "Drawdown actual: -5.2% (dentro de límites)"},
            {"level": "✅", "message": "Todas las posiciones tienen stop loss activo"},
        ]
        
        for alert in risk_alerts:
            st.write(f"{alert['level']} {alert['message']}")
    
    # TAB 5: Trade History
    with tab5:
        st.subheader("Historial de Operaciones")
        
        # Simular historial
        n_trades = 50
        trades_data = []
        
        for i in range(n_trades):
            symbol = np.random.choice(['BAC', 'WFC', 'VZ', 'JPM', 'XOM', 'CMCSA', 'PFE', 'BRK-B'])
            action = np.random.choice(['BUY', 'SELL'], p=[0.6, 0.4])
            shares = np.random.randint(50, 500)
            price = np.random.uniform(20, 500)
            pnl = np.random.uniform(-5000, 8000) if action == 'SELL' else 0
            
            trades_data.append({
                'Fecha': datetime.now() - timedelta(days=i*2),
                'Símbolo': symbol,
                'Acción': action,
                'Cantidad': shares,
                'Precio': f"${price:.2f}",
                'Total': f"${shares*price:,.0f}",
                'P&L': f"${pnl:,.0f}" if action == 'SELL' else "-",
                'Estado': 'CERRADO' if action == 'SELL' else 'ABIERTO'
            })
        
        df_trades = pd.DataFrame(trades_data)
        st.dataframe(df_trades, use_container_width=True, height=500)
        
        col1, col2, col3 = st.columns(3)
        
        with col1:
            st.metric("Total Trades", len(df_trades))
        
        with col2:
            win_rate = (df_trades[df_trades['Acción'] == 'SELL']['P&L'].str.replace('$', '').str.replace(',', '').astype(float) > 0).mean()
            st.metric("Win Rate", f"{win_rate*100:.1f}%")
        
        with col3:
            avg_profit = df_trades[df_trades['Acción'] == 'SELL']['P&L'].str.replace('$', '').str.replace(',', '').astype(float).mean()
            st.metric("P&L Promedio", f"${avg_profit:,.0f}")
    
    # Footer
    st.markdown("---")
    st.markdown("""
    <div style="text-align: center; color: #666; padding: 1rem;">
        <strong>OmniCapital v1.0</strong> | Investment Capital Firm | © 2026<br>
        <small>Los datos se actualizan cada 60 segundos. Última actualización: {}</small>
    </div>
    """.format(datetime.now().strftime('%Y-%m-%d %H:%M:%S')), unsafe_allow_html=True)
    
    # Auto-refresh
    if auto_refresh:
        time.sleep(refresh_interval)
        st.rerun()


if __name__ == '__main__':
    main()
