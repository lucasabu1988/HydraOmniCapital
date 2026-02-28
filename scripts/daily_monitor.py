"""
OmniCapital v8.2 COMPASS - Daily Monitor
Script de monitoreo diario para trading live
"""

import pandas as pd
import json
import os
from datetime import datetime, timedelta
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart


class DailyMonitor:
    def __init__(self, config_file='state/compass_state_latest.json'):
        self.config_file = config_file
        self.state = None
        self.load_state()
        
    def load_state(self):
        """Carga estado actual del sistema"""
        if os.path.exists(self.config_file):
            with open(self.config_file, 'r') as f:
                self.state = json.load(f)
        else:
            self.state = {}
    
    def generate_daily_report(self):
        """Genera reporte del dia"""
        
        report = []
        report.append("="*60)
        report.append("OMNICAPITAL v8.2 COMPASS - DAILY REPORT")
        report.append("="*60)
        report.append(f"Fecha: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        report.append("")
        
        # Estado del portfolio
        if 'portfolio_value' in self.state:
            report.append("--- ESTADO DEL PORTFOLIO ---")
            report.append(f"Valor actual: ${self.state.get('portfolio_value', 0):,.2f}")
            report.append(f"Cash: ${self.state.get('cash', 0):,.2f}")
            report.append(f"Peak value: ${self.state.get('peak_value', 0):,.2f}")
            
            # Calcular drawdown
            peak = self.state.get('peak_value', 1)
            current = self.state.get('portfolio_value', 0)
            drawdown = (current - peak) / peak if peak > 0 else 0
            report.append(f"Drawdown actual: {drawdown:.2%}")
            report.append("")
        
        # Posiciones
        positions = self.state.get('positions', {})
        report.append("--- POSICIONES ---")
        report.append(f"Numero de posiciones: {len(positions)}")
        
        for symbol, pos in positions.items():
            report.append(f"  {symbol}: {pos.get('shares', 0):.2f} shares @ ${pos.get('entry_price', 0):.2f}")
        report.append("")
        
        # Estado del sistema
        report.append("--- ESTADO DEL SISTEMA ---")
        report.append(f"En proteccion: {self.state.get('in_protection', False)}")
        prot_stage = self.state.get('protection_stage', 0)
        if prot_stage:
            report.append(f"Protection stage: {prot_stage}")
        regime = "RISK_ON" if self.state.get('current_regime', True) else "RISK_OFF"
        report.append(f"Regime: {regime}")
        report.append(f"Trading day: {self.state.get('trading_day_counter', 0)}")
        report.append(f"Stop events historicos: {len(self.state.get('stop_events', []))}")
        report.append("")
        
        # Alertas
        report.append("--- ALERTAS ---")
        alerts = self.check_alerts()
        if alerts:
            for alert in alerts:
                report.append(f"⚠ {alert}")
        else:
            report.append("✓ No hay alertas")
        report.append("")
        
        # Recomendaciones
        report.append("--- RECOMENDACIONES ---")
        if self.state.get('in_protection'):
            stage = self.state.get('protection_stage', 1)
            report.append(f"• Sistema en MODO PROTECCION Stage {stage}")
            report.append("• NO agregar capital")
            if stage == 1:
                report.append("• Leverage: 0.3x | Max 2 posiciones | Esperar 63 dias + RISK_ON")
            else:
                report.append("• Leverage: 1.0x | Max 3 posiciones | Esperar 126 dias + RISK_ON")
        else:
            report.append("• Sistema operando normalmente")
            report.append("• Monitorear pero NO intervenir")

        if drawdown < -0.12:
            report.append("• Drawdown cercano a -15% - Stop loss proximo")
        
        report.append("")
        report.append("="*60)
        
        return "\n".join(report)
    
    def check_alerts(self):
        """Verifica condiciones de alerta"""
        alerts = []
        
        if not self.state:
            alerts.append("No se encontro estado del sistema")
            return alerts
        
        # Alerta: Drawdown cercano a stop loss
        peak = self.state.get('peak_value', 1)
        current = self.state.get('portfolio_value', 0)
        drawdown = (current - peak) / peak if peak > 0 else 0
        
        if drawdown < -0.12:
            alerts.append(f"Drawdown {drawdown:.1%} - Cerca de stop loss (-15%)")
        
        # Alerta: En proteccion
        if self.state.get('in_protection'):
            alerts.append("Sistema en MODO PROTECCION - Leverage reducido a 1:1")
        
        # Alerta: Numero de posiciones bajo
        positions = self.state.get('positions', {})
        if len(positions) < 3 and not self.state.get('in_protection'):
            alerts.append(f"Solo {len(positions)} posiciones (esperado: 5)")
        
        # Alerta: Cash bajo
        portfolio = self.state.get('portfolio_value', 0)
        cash = self.state.get('cash', 0)
        if portfolio > 0 and cash / portfolio < 0.05:
            alerts.append("Cash bajo (< 5% del portfolio)")
        
        return alerts
    
    def send_email(self, subject, body, to_email):
        """Envia reporte por email"""
        # Configurar con tus credenciales
        smtp_server = "smtp.gmail.com"
        smtp_port = 587
        from_email = "tu_email@gmail.com"
        password = "tu_password"
        
        msg = MIMEMultipart()
        msg['From'] = from_email
        msg['To'] = to_email
        msg['Subject'] = subject
        
        msg.attach(MIMEText(body, 'plain'))
        
        try:
            server = smtplib.SMTP(smtp_server, smtp_port)
            server.starttls()
            server.login(from_email, password)
            server.send_message(msg)
            server.quit()
            print(f"Email enviado a {to_email}")
        except Exception as e:
            print(f"Error enviando email: {e}")
    
    def save_report(self, report):
        """Guarda reporte en archivo"""
        date_str = datetime.now().strftime('%Y%m%d')
        filename = f'daily_reports/report_{date_str}.txt'
        
        # Crear directorio si no existe
        os.makedirs('daily_reports', exist_ok=True)
        
        with open(filename, 'w') as f:
            f.write(report)
        
        print(f"Reporte guardado: {filename}")
    
    def run(self):
        """Ejecuta monitoreo diario"""
        print("Generando reporte diario...")
        
        report = self.generate_daily_report()
        print(report)
        
        # Guardar
        self.save_report(report)
        
        # Enviar email (opcional)
        # self.send_email("OmniCapital Daily Report", report, "tu@email.com")
        
        # Verificar si hay alertas criticas
        alerts = self.check_alerts()
        critical = [a for a in alerts if "proteccion" in a.lower() or "stop loss" in a.lower()]
        
        if critical:
            print("\n" + "!"*60)
            print("ALERTAS CRITICAS DETECTADAS")
            print("!"*60)
            for alert in critical:
                print(f"  ⚠ {alert}")
            print("\nRevisar sistema inmediatamente")
            return 1
        
        return 0


def main():
    monitor = DailyMonitor()
    return monitor.run()


if __name__ == "__main__":
    import sys
    sys.exit(main())
