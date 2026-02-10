"""
OmniCapital v6 - Deployment Checklist Automation
Verifica que todo este listo para trading live
"""

import os
import sys
import json
from datetime import datetime, timedelta

class DeploymentChecker:
    def __init__(self):
        self.checks = []
        self.passed = 0
        self.failed = 0
        
    def check(self, name, condition, message=""):
        """Ejecuta un check y registra resultado"""
        status = "✓ PASS" if condition else "✗ FAIL"
        self.checks.append({
            'name': name,
            'status': status,
            'condition': condition,
            'message': message
        })
        
        if condition:
            self.passed += 1
        else:
            self.failed += 1
            
        print(f"{status}: {name}")
        if message and not condition:
            print(f"  → {message}")
        
        return condition
    
    def run_all_checks(self):
        """Ejecuta todos los checks de deployment"""
        
        print("="*60)
        print("OMNICAPITAL v6 - DEPLOYMENT CHECKLIST")
        print("="*60)
        print(f"Fecha: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print()
        
        # === CHECKS TECNICOS ===
        print("--- CHECKS TECNICOS ---")
        
        # Archivos necesarios
        required_files = [
            'omnicapital_live.py',
            'omnicapital_broker.py', 
            'omnicapital_data_feed.py',
            'OMNICAPITAL_V6_FINAL_SPEC.md',
            'IMPLEMENTATION_GUIDE.md',
        ]
        
        for f in required_files:
            self.check(
                f"Archivo {f} existe",
                os.path.exists(f),
                f"Crear {f} antes de continuar"
            )
        
        # Python y dependencias
        self.check(
            "Python 3.8+",
            sys.version_info >= (3, 8),
            f"Version actual: {sys.version}"
        )
        
        try:
            import pandas
            import numpy
            import yfinance
            self.check("Dependencias instaladas", True)
        except ImportError as e:
            self.check(
                "Dependencias instaladas",
                False,
                f"Ejecutar: pip install pandas numpy yfinance"
            )
        
        # Configuracion
        self.check(
            "Configuracion v6 verificada",
            self._verify_config(),
            "Revisar parametros en omnicapital_live.py"
        )
        
        # === CHECKS DE BROKER ===
        print("\n--- CHECKS DE BROKER ---")
        
        self.check(
            "Cuenta de broker abierta",
            self._confirm("¿Tienes cuenta de broker (IBKR/Alpaca) abierta?"),
            "Abrir cuenta antes de continuar"
        )
        
        self.check(
            "Margin aprobado",
            self._confirm("¿Tienes margin aprobado para 2:1 leverage?"),
            "Solicitar margin al broker"
        )
        
        self.check(
            "API keys configuradas",
            self._confirm("¿Tienes API keys del broker?"),
            "Generar API keys en plataforma del broker"
        )
        
        self.check(
            "Test de conexion exitoso",
            self._confirm("¿Has testeado conexion con broker (paper)?"),
            "Ejecutar test_broker_connection.py"
        )
        
        # === CHECKS DE CAPITAL ===
        print("\n--- CHECKS DE CAPITAL ---")
        
        self.check(
            "Capital asignado",
            self._confirm("¿Has asignado capital (solo dinero que no necesitas en 5+ años)?"),
            "Definir capital de trading"
        )
        
        self.check(
            "Capital <= 20% patrimonio",
            self._confirm("¿El capital es maximo 20% de tu patrimonio neto?"),
            "Reducir capital o aumentar patrimonio"
        )
        
        self.check(
            "Fondo de emergencia intacto",
            self._confirm("¿Tienes fondo de emergencia de 6+ meses separado?"),
            "Establecer fondo de emergencia primero"
        )
        
        # === CHECKS DE PAPER TRADING ===
        print("\n--- CHECKS DE PAPER TRADING ---")
        
        self.check(
            "Paper trading completado",
            self._confirm("¿Has ejecutado paper trading por minimo 1 mes?"),
            "Ejecutar omnicapital_live.py en modo paper"
        )
        
        self.check(
            "Ordenes ejecutadas correctamente",
            self._confirm("¿Mas del 95% de ordenes se ejecutaron sin error?"),
            "Revisar logs y corregir errores"
        )
        
        self.check(
            "Stop loss testeado",
            self._confirm("¿Has visto el stop loss activarse al menos una vez (incluso manualmente)?"),
            "Testear stop loss con minima cantidad"
        )
        
        # === CHECKS LEGALES/FISCALES ===
        print("\n--- CHECKS LEGALES/FISCALES ---")
        
        self.check(
            "Estructura legal definida",
            self._confirm("¿Has definido estructura legal (personal/LLC/fondo)?"),
            "Consultar con abogado fiscalista"
        )
        
        self.check(
            "Plan fiscal preparado",
            self._confirm("¿Tienes plan para reportar ganancias/pérdidas?"),
            "Consultar con contador"
        )
        
        # === CHECKS MENTALES ===
        print("\n--- CHECKS MENTALES ---")
        
        self.check(
            "Aceptacion de riesgo",
            self._confirm("¿Aceptas que puedes perder todo el capital asignado?"),
            "NO continuar si no aceptas el riesgo"
        )
        
        self.check(
            "Compromiso de no intervenir",
            self._confirm("¿Te comprometes a NO intervenir en el sistema una vez en operacion?"),
            "El sistema es automatico, no tocar"
        )
        
        self.check(
            "Comfort con drawdown",
            self._confirm("¿Estas comodo con potencial drawdown de 38%?"),
            "Revisar historia de drawdowns de v6"
        )
        
        # === RESUMEN ===
        print("\n" + "="*60)
        print("RESUMEN")
        print("="*60)
        print(f"Checks passed: {self.passed}")
        print(f"Checks failed: {self.failed}")
        print(f"Total: {self.passed + self.failed}")
        
        if self.failed == 0:
            print("\n✓ TODOS LOS CHECKS PASADOS")
            print("Estas listo para deployment live (Fase 2)")
            print("\nProximo paso: Ejecutar Fase 2 - Escalado gradual")
        else:
            print(f"\n✗ {self.failed} CHECKS FALLIDOS")
            print("Resolver issues antes de continuar")
            print("\nIssues pendientes:")
            for check in self.checks:
                if not check['condition']:
                    print(f"  - {check['name']}")
        
        # Guardar reporte
        report = {
            'date': datetime.now().isoformat(),
            'passed': self.passed,
            'failed': self.failed,
            'checks': self.checks,
            'ready_for_live': self.failed == 0
        }
        
        with open('deployment_check_report.json', 'w') as f:
            json.dump(report, f, indent=2)
        
        print(f"\nReporte guardado: deployment_check_report.json")
        
        return self.failed == 0
    
    def _verify_config(self):
        """Verifica que configuracion v6 sea correcta"""
        try:
            # Leer archivo y buscar parametros
            with open('omnicapital_live.py', 'r') as f:
                content = f.read()
            
            checks = [
                "HOLD_MINUTES = 1200" in content,
                "NUM_POSITIONS = 5" in content,
                "STOP_LOSS_PCT = -0.20" in content or "STOP_LOSS_PCT = -0.2" in content,
                "LEVERAGE = 2.0" in content or "LEVERAGE = 2" in content,
            ]
            
            return all(checks)
        except:
            return False
    
    def _confirm(self, question):
        """Pide confirmacion al usuario"""
        while True:
            response = input(f"{question} [s/n]: ").lower().strip()
            if response in ['s', 'si', 'yes', 'y']:
                return True
            elif response in ['n', 'no']:
                return False
            else:
                print("  Por favor responde 's' o 'n'")


def main():
    checker = DeploymentChecker()
    ready = checker.run_all_checks()
    
    if ready:
        print("\n" + "="*60)
        print("RECUERDA:")
        print("="*60)
        print("1. Iniciar con capital pequeño ($10k)")
        print("2. Escalar gradualmente (semanas 8-12)")
        print("3. NO intervenir en el sistema")
        print("4. Monitorear diariamente pero no tocar")
        print("5. Mantener logs y reportes")
        print("\nBuena suerte. In Simplicity We Trust.")
    
    return 0 if ready else 1


if __name__ == "__main__":
    sys.exit(main())
