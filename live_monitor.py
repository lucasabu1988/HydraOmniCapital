"""
AlphaMax OmniCapital v1.0 - Live Monitor
Sistema de monitoreo en tiempo real del algoritmo

Copyright (c) 2026 Investment Capital Firm
Version: 1.0.0
"""

import sys
import time
import json
import signal
import threading
from pathlib import Path
from datetime import datetime, timedelta
from typing import Optional, Dict, List
import argparse

# Añadir src al path
sys.path.insert(0, str(Path(__file__).parent))

import pandas as pd
import numpy as np

from src.data.data_provider import YFinanceProvider
from src.signals.technical import TechnicalSignals, SignalType
from src.core.engine import TradingEngine


class LiveMonitor:
    """Monitor en tiempo real del algoritmo de trading"""
    
    def __init__(self, config_path: str = 'config/strategy.yaml', 
                 update_interval: int = 60,
                 symbols: Optional[List[str]] = None):
        """
        Inicializa el monitor en vivo
        
        Args:
            config_path: Ruta al archivo de configuración
            update_interval: Intervalo de actualización en segundos
            symbols: Lista opcional de símbolos a monitorear
        """
        self.config_path = config_path
        self.update_interval = update_interval
        self.symbols = symbols
        self.running = False
        self.provider = YFinanceProvider()
        self.engine: Optional[TradingEngine] = None
        self.last_update: Optional[datetime] = None
        self.watchlist: Dict[str, dict] = {}
        self.alerts: List[dict] = []
        
        # Configurar señales de interrupción
        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)
        
    def _signal_handler(self, signum, frame):
        """Maneja señales de interrupción"""
        print("\n\n[MONITOR] Señal de interrupción recibida. Deteniendo...")
        self.stop()
        
    def initialize(self):
        """Inicializa el motor de trading"""
        print("[MONITOR] Inicializando motor de trading...")
        self.engine = TradingEngine(self.config_path)
        
        if self.symbols:
            self.engine.initialize_universe(self.symbols)
        else:
            self.engine.initialize_universe()
            
        print(f"[MONITOR] Motor inicializado. Universo: {len(self.engine.universe)} símbolos")
        
    def start(self):
        """Inicia el monitoreo en tiempo real"""
        self.running = True
        self.initialize()
        
        print("\n" + "="*80)
        print("OMNICAPITAL v1.0 - MONITOR EN TIEMPO REAL")
        print("="*80)
        print(f"Inicio: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"Intervalo de actualización: {self.update_interval} segundos")
        print("="*80)
        print("\nComandos disponibles:")
        print("  [Ctrl+C] - Detener monitoreo")
        print("  [Enter]  - Forzar actualización")
        print("\n")
        
        # Iniciar thread de input para comandos
        input_thread = threading.Thread(target=self._input_handler, daemon=True)
        input_thread.start()
        
        # Bucle principal de monitoreo
        while self.running:
            try:
                self._update_cycle()
                
                # Esperar hasta la próxima actualización
                for _ in range(self.update_interval):
                    if not self.running:
                        break
                    time.sleep(1)
                    
            except Exception as e:
                print(f"\n[ERROR] Error en ciclo de actualización: {e}")
                time.sleep(5)
                
    def stop(self):
        """Detiene el monitoreo"""
        self.running = False
        print("\n[MONITOR] Deteniendo monitoreo...")
        self._save_final_report()
        print("[MONITOR] Monitoreo detenido.")
        
    def _input_handler(self):
        """Maneja input del usuario en segundo plano"""
        while self.running:
            try:
                input()
                if self.running:
                    print("\n[MONITOR] Actualización forzada...")
                    self._update_cycle()
            except:
                pass
                
    def _update_cycle(self):
        """Ejecuta un ciclo de actualización"""
        now = datetime.now()
        self.last_update = now
        
        print(f"\n[{now.strftime('%H:%M:%S')}] Actualizando datos...", end=' ')
        
        try:
            # Actualizar datos de mercado
            self.engine.load_data(lookback_days=30)
            
            # Escanear oportunidades
            opportunities = self.engine.scan_opportunities()
            
            # Actualizar watchlist
            self._update_watchlist(opportunities)
            
            # Verificar alertas
            self._check_alerts()
            
            # Mostrar resumen
            self._display_summary(opportunities)
            
            # Guardar snapshot
            self._save_snapshot()
            
            print("[OK]")

        except Exception as e:
            print(f"[ERROR] {e}")
            
    def _update_watchlist(self, opportunities: List[dict]):
        """Actualiza la lista de seguimiento"""
        for opp in opportunities[:20]:  # Top 20
            symbol = opp['signal'].symbol
            
            if symbol not in self.watchlist:
                self.watchlist[symbol] = {
                    'first_seen': datetime.now(),
                    'signals_history': [],
                    'highest_score': 0,
                    'lowest_score': 100
                }
            
            watch = self.watchlist[symbol]
            watch['last_update'] = datetime.now()
            watch['current_signal'] = opp['signal']
            watch['current_price'] = opp['current_price']
            watch['signals_history'].append({
                'timestamp': datetime.now(),
                'score': opp['signal'].confidence,
                'price': opp['current_price']
            })
            # Limit history to prevent unbounded memory growth
            if len(watch['signals_history']) > 500:
                watch['signals_history'] = watch['signals_history'][-500:]
            watch['highest_score'] = max(watch['highest_score'], opp['signal'].confidence)
            watch['lowest_score'] = min(watch['lowest_score'], opp['signal'].confidence)
            
    def _check_alerts(self):
        """Verifica condiciones de alerta"""
        alerts_triggered = []
        
        for symbol, watch in self.watchlist.items():
            signal = watch.get('current_signal')
            if not signal:
                continue
                
            # Alerta: Señal fuerte de compra
            if signal.action == 'BUY' and signal.confidence >= 0.75:
                if not any(a['symbol'] == symbol and a['type'] == 'STRONG_BUY' 
                          for a in self.alerts[-10:]):
                    alerts_triggered.append({
                        'timestamp': datetime.now(),
                        'type': 'STRONG_BUY',
                        'symbol': symbol,
                        'message': f'Señal FUERTE de COMPRA: {symbol} (confianza: {signal.confidence:.1%})',
                        'price': watch.get('current_price', 0)
                    })
                    
            # Alerta: Cambio significativo en score
            if len(watch['signals_history']) >= 2:
                last_scores = [s['score'] for s in watch['signals_history'][-5:]]
                if len(last_scores) >= 2:
                    score_change = last_scores[-1] - last_scores[0]
                    if abs(score_change) >= 0.20:  # Cambio de 20%
                        direction = "+" if score_change > 0 else "-"
                        alerts_triggered.append({
                            'timestamp': datetime.now(),
                            'type': 'SCORE_CHANGE',
                            'symbol': symbol,
                            'message': f'Cambio significativo en {symbol}: {direction} {abs(score_change):.1%}',
                            'price': watch.get('current_price', 0)
                        })
                        
        self.alerts.extend(alerts_triggered)
        # Prune old alerts to prevent unbounded memory growth
        if len(self.alerts) > 500:
            self.alerts = self.alerts[-500:]

        # Mostrar alertas nuevas
        for alert in alerts_triggered:
            print(f"\n  [ALERTA] {alert['message']}")
            
    def _display_summary(self, opportunities: List[dict]):
        """Muestra resumen del estado actual"""
        
        # Obtener estado del portafolio
        snapshot = self.engine.get_portfolio_snapshot()
        
        print(f"\n  [PORTAFOLIO]")
        print(f"     Valor Total: ${snapshot['total_value']:,.2f}")
        print(f"     Efectivo: ${snapshot['cash']:,.2f}")
        print(f"     Posiciones: {len(snapshot['positions'])}")

        if snapshot['positions']:
            total_pnl = sum(p.get('unrealized_pnl', 0) for p in snapshot['positions'].values())
            print(f"     P&L No Realizado: ${total_pnl:,.2f}")

        # Top 5 oportunidades
        print(f"\n  [TOP 5 OPORTUNIDADES]")
        if opportunities:
            for i, opp in enumerate(opportunities[:5], 1):
                signal = opp['signal']
                trend_icon = "[+]" if signal.action == 'BUY' else "[-]" if signal.action == 'SELL' else "[ ]"
                print(f"     {i}. {trend_icon} {signal.symbol:<6} | "
                      f"Score: {signal.confidence:.1%} | "
                      f"${opp['current_price']:.2f} | "
                      f"T:{signal.technical_score:.2f} F:{signal.fundamental_score:.2f}")
        else:
            print("     Sin oportunidades en este ciclo")

        # Mercado general
        try:
            spy_price = self.provider.get_current_price(['SPY']).get('SPY', 0)
            qqq_price = self.provider.get_current_price(['QQQ']).get('QQQ', 0)
            if spy_price and qqq_price:
                print(f"\n  [MERCADO]")
                print(f"     SPY: ${spy_price:.2f}  |  QQQ: ${qqq_price:.2f}")
        except:
            pass
            
    def _save_snapshot(self):
        """Guarda snapshot del estado actual"""
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        
        snapshot = {
            'timestamp': datetime.now().isoformat(),
            'portfolio': self.engine.get_portfolio_snapshot(),
            'watchlist': {
                symbol: {
                    'current_price': data.get('current_price'),
                    'confidence': data.get('current_signal', {}).confidence if data.get('current_signal') else None,
                    'highest_score': data.get('highest_score'),
                    'lowest_score': data.get('lowest_score')
                }
                for symbol, data in self.watchlist.items()
            },
            'alerts_count': len(self.alerts)
        }
        
        # Guardar en archivo
        snapshot_file = f'logs/monitor_snapshot_{timestamp}.json'
        with open(snapshot_file, 'w') as f:
            json.dump(snapshot, f, indent=2, default=str)
            
    def _save_final_report(self):
        """Guarda reporte final del monitoreo"""
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        
        report = {
            'monitor_start': self.last_update.isoformat() if self.last_update else None,
            'monitor_end': datetime.now().isoformat(),
            'total_alerts': len(self.alerts),
            'alerts': self.alerts[-50:],  # Últimas 50 alertas
            'watchlist_summary': {
                symbol: {
                    'signals_count': len(data.get('signals_history', [])),
                    'highest_score': data.get('highest_score'),
                    'lowest_score': data.get('lowest_score')
                }
                for symbol, data in self.watchlist.items()
            }
        }
        
        report_file = f'reports/monitor_report_{timestamp}.json'
        with open(report_file, 'w') as f:
            json.dump(report, f, indent=2, default=str)
            
        print(f"[MONITOR] Reporte guardado: {report_file}")


def main():
    parser = argparse.ArgumentParser(
        description='OmniCapital v1.0 - Monitor en Tiempo Real',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Ejemplos:
  # Monitoreo básico
  python live_monitor.py
  
  # Monitoreo con actualización cada 30 segundos
  python live_monitor.py --interval 30
  
  # Monitorear símbolos específicos
  python live_monitor.py --symbols AAPL MSFT GOOGL AMZN
        """
    )
    
    parser.add_argument(
        '--config',
        default='config/strategy.yaml',
        help='Ruta al archivo de configuración'
    )
    
    parser.add_argument(
        '--interval',
        type=int,
        default=60,
        help='Intervalo de actualización en segundos (default: 60)'
    )
    
    parser.add_argument(
        '--symbols',
        nargs='+',
        help='Lista de símbolos a monitorear'
    )
    
    args = parser.parse_args()
    
    # Crear directorios necesarios
    Path('logs').mkdir(exist_ok=True)
    Path('reports').mkdir(exist_ok=True)
    
    # Iniciar monitor
    monitor = LiveMonitor(
        config_path=args.config,
        update_interval=args.interval,
        symbols=args.symbols
    )
    
    try:
        monitor.start()
    except KeyboardInterrupt:
        monitor.stop()
    except Exception as e:
        print(f"\n[ERROR] Error fatal: {e}")
        monitor.stop()
        raise


if __name__ == '__main__':
    main()
