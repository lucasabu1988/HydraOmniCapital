"""
Proveedor de Datos Fundamentales
Maneja la obtención de métricas fundamentales de empresas
"""

import pandas as pd
from typing import Dict, List, Optional, Any
from datetime import datetime
import yfinance as yf

from ..signals.fundamental import FundamentalMetrics


class FundamentalProvider:
    """
    Provee datos fundamentales de empresas
    """
    
    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key
        self._cache: Dict[str, FundamentalMetrics] = {}
    
    def get_fundamental_data(self, symbol: str) -> FundamentalMetrics:
        """
        Obtiene datos fundamentales para un símbolo
        
        Args:
            symbol: Símbolo de la acción
            
        Returns:
            FundamentalMetrics con los datos
        """
        # Verificar cache
        if symbol in self._cache:
            return self._cache[symbol]
        
        try:
            ticker = yf.Ticker(symbol)
            info = ticker.info
            
            # Construir métricas
            metrics = FundamentalMetrics(
                symbol=symbol,
                pe_ratio=info.get('trailingPE'),
                forward_pe=info.get('forwardPE'),
                pb_ratio=info.get('priceToBook'),
                ps_ratio=info.get('priceToSalesTrailing12Months'),
                ev_ebitda=info.get('enterpriseToEbitda'),
                roe=info.get('returnOnEquity'),
                roa=info.get('returnOnAssets'),
                gross_margin=info.get('grossMargins'),
                operating_margin=info.get('operatingMargins'),
                profit_margin=info.get('profitMargins'),
                debt_equity=info.get('debtToEquity'),
                current_ratio=info.get('currentRatio'),
                quick_ratio=info.get('quickRatio'),
                interest_coverage=None,  # No disponible directamente
                revenue_growth=info.get('revenueGrowth'),
                earnings_growth=info.get('earningsGrowth'),
                dividend_yield=info.get('dividendYield'),
                payout_ratio=info.get('payoutRatio'),
                asset_turnover=info.get('revenuePerShare'),
                inventory_turnover=None
            )
            
            self._cache[symbol] = metrics
            return metrics
            
        except Exception as e:
            print(f"Error obteniendo datos fundamentales de {symbol}: {e}")
            return FundamentalMetrics(symbol=symbol)
    
    def get_batch_fundamental_data(
        self,
        symbols: List[str]
    ) -> Dict[str, FundamentalMetrics]:
        """
        Obtiene datos fundamentales para múltiples símbolos
        
        Args:
            symbols: Lista de símbolos
            
        Returns:
            Diccionario {símbolo: FundamentalMetrics}
        """
        result = {}
        for symbol in symbols:
            result[symbol] = self.get_fundamental_data(symbol)
        return result
    
    def get_financials(self, symbol: str) -> Dict[str, Any]:
        """
        Obtiene estados financieros
        
        Args:
            symbol: Símbolo de la acción
            
        Returns:
            Diccionario con estados financieros
        """
        try:
            ticker = yf.Ticker(symbol)
            
            return {
                'income_stmt': ticker.income_stmt,
                'balance_sheet': ticker.balance_sheet,
                'cash_flow': ticker.cashflow,
                'quarterly_income': ticker.quarterly_income_stmt,
                'quarterly_balance': ticker.quarterly_balance_sheet
            }
        except Exception as e:
            print(f"Error obteniendo estados financieros de {symbol}: {e}")
            return {}
    
    def calculate_custom_metrics(
        self,
        symbol: str,
        financials: Dict[str, Any]
    ) -> Dict[str, float]:
        """
        Calcula métricas personalizadas
        
        Args:
            symbol: Símbolo
            financials: Estados financieros
            
        Returns:
            Diccionario de métricas calculadas
        """
        metrics = {}
        
        try:
            income = financials.get('income_stmt')
            balance = financials.get('balance_sheet')
            
            if income is not None and not income.empty:
                # Crecimiento de ingresos YoY
                if 'Total Revenue' in income.index and income.shape[1] >= 2:
                    revenue_current = income.loc['Total Revenue'].iloc[0]
                    revenue_prev = income.loc['Total Revenue'].iloc[1]
                    if revenue_prev != 0:
                        metrics['revenue_growth_yoy'] = (revenue_current - revenue_prev) / abs(revenue_prev)
                
                # Crecimiento de ganancias YoY
                if 'Net Income' in income.index and income.shape[1] >= 2:
                    income_current = income.loc['Net Income'].iloc[0]
                    income_prev = income.loc['Net Income'].iloc[1]
                    if income_prev != 0:
                        metrics['earnings_growth_yoy'] = (income_current - income_prev) / abs(income_prev)
            
            if balance is not None and not balance.empty:
                # Debt/Equity calculado
                if 'Total Debt' in balance.index and 'Stockholders Equity' in balance.index:
                    debt = balance.loc['Total Debt'].iloc[0]
                    equity = balance.loc['Stockholders Equity'].iloc[0]
                    if equity != 0:
                        metrics['debt_equity_calculated'] = debt / equity
            
        except Exception as e:
            print(f"Error calculando métricas personalizadas: {e}")
        
        return metrics
