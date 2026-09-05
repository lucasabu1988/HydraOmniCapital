"""
OmniCapital v6 - Deployment Checklist (Fast/Non-interactive)
Verifica automaticamente lo que puede sin input del usuario
"""

import os
import sys

print("="*60)
print("OMNICAPITAL v6 - DEPLOYMENT CHECK (FAST)")
print("="*60)
print()

checks = []
passed = 0
failed = 0

def check(name, condition, message=""):
    global passed, failed
    status = "[OK]" if condition else "[FAIL]"
    checks.append((name, condition, message))
    
    if condition:
        passed += 1
        print(f"{status} {name}")
    else:
        failed += 1
        print(f"{status} {name}")
        if message:
            print(f"    -> {message}")
    return condition

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
    check(f"Archivo {f} existe", os.path.exists(f), f"Crear {f}")

# Python y dependencias
check("Python 3.8+", sys.version_info >= (3, 8), f"Version: {sys.version}")

try:
    import pandas, numpy, yfinance
    check("Dependencias instaladas", True)
except ImportError as e:
    check("Dependencias instaladas", False, f"pip install pandas numpy yfinance")

# Verificar configuracion v6
try:
    with open('omnicapital_live.py', 'r') as f:
        content = f.read()
    
    has_hold = "HOLD_MINUTES = 1200" in content
    has_pos = "NUM_POSITIONS = 5" in content
    has_stop = "STOP_LOSS_PCT = -0.20" in content or "STOP_LOSS_PCT = -0.2" in content
    has_lev = "LEVERAGE = 2.0" in content or "LEVERAGE = 2" in content
    
    config_ok = has_hold and has_pos and has_stop and has_lev
    check("Configuracion v6 verificada", config_ok, "Revisar parametros en omnicapital_live.py")
    
    if not config_ok:
        if not has_hold:
            print("    -> HOLD_MINUTES no es 1200")
        if not has_pos:
            print("    -> NUM_POSITIONS no es 5")
        if not has_stop:
            print("    -> STOP_LOSS_PCT no es -0.20")
        if not has_lev:
            print("    -> LEVERAGE no es 2.0")
except Exception as e:
    check("Configuracion v6 verificada", False, f"Error leyendo archivo: {e}")

print()
print("--- CHECKS DE BROKER (MANUALES) ---")
print("[!] Cuenta de broker abierta - VERIFICAR MANUALMENTE")
print("[!] Margin aprobado para 2:1 - VERIFICAR MANUALMENTE")
print("[!] API keys configuradas - VERIFICAR MANUALMENTE")
print("[!] Test de conexion exitoso - VERIFICAR MANUALMENTE")

print()
print("--- CHECKS DE CAPITAL (MANUALES) ---")
print("[!] Capital asignado (solo dinero que no necesitas en 5+ anos)")
print("[!] Capital <= 20% de patrimonio neto")
print("[!] Fondo de emergencia de 6+ meses separado")

print()
print("--- CHECKS DE PAPER TRADING (MANUALES) ---")
print("[!] Paper trading completado (minimo 1 mes)")
print("[!] Mas del 95% de ordenes ejecutadas sin error")
print("[!] Stop loss testeado al menos una vez")

print()
print("--- CHECKS LEGALES/FISCALES (MANUALES) ---")
print("[!] Estructura legal definida")
print("[!] Plan fiscal preparado")

print()
print("--- CHECKS MENTALES (MANUALES) ---")
print("[!] Aceptacion de riesgo (puedes perder todo el capital)")
print("[!] Compromiso de NO intervenir en el sistema")
print("[!] Comfort con drawdown de 38%")

print()
print("="*60)
print("RESUMEN AUTOMATICO")
print("="*60)
print(f"Checks automaticos passed: {passed}")
print(f"Checks automaticos failed: {failed}")
print(f"Checks manuales pendientes: 14")
print()

if failed == 0:
    print("[OK] Todos los checks automaticos pasaron")
    print()
    print("SIGUIENTE PASO:")
    print("1. Completar los 14 checks manuales (arriba)")
    print("2. Ejecutar: python omnicapital_live.py (modo paper)")
    print("3. Monitorear por 1 mes minimo")
else:
    print(f"[FAIL] {failed} checks automaticos fallidos")
    print("Resolver antes de continuar")

print()
print("="*60)
print("LISTA DE VERIFICACION MANUAL")
print("="*60)
print()
print("Copiar y completar:")
print()
print("[ ] Cuenta de broker abierta (IBKR/Alpaca)")
print("[ ] Margin aprobado para 2:1 leverage")
print("[ ] API keys generadas y guardadas")
print("[ ] Test de conexion con broker exitoso")
print("[ ] Capital asignado: $_________")
print("[ ] Capital es <= 20% de patrimonio neto")
print("[ ] Fondo de emergencia 6+ meses intacto")
print("[ ] Paper trading 1+ mes completado")
print("[ ] 95%+ ordenes ejecutadas sin error")
print("[ ] Stop loss testeado")
print("[ ] Estructura legal definida")
print("[ ] Plan fiscal preparado")
print("[ ] Acepto riesgo de perder todo el capital")
print("[ ] Me comprometo a NO intervenir en el sistema")
print("[ ] Estoy comodo con 38% drawdown potencial")
print()
print("Fecha: _______________ Firma: _______________")
print()
