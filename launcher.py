#!/usr/bin/env python3
"""
OmniCapital v1.0 - Launcher Universal
Lanzador principal para ejecutar el algoritmo de trading
"""

import os
import sys
import subprocess
from pathlib import Path
from datetime import datetime

# Asegurar encoding UTF-8 en Windows
if sys.platform == 'win32':
    os.environ.setdefault('PYTHONIOENCODING', 'utf-8')

# Directorio base del proyecto
BASE_DIR = Path(__file__).parent.resolve()
os.chdir(BASE_DIR)


def clear_screen():
    """Limpia la pantalla"""
    os.system('cls' if os.name == 'nt' else 'clear')


def print_header():
    """Muestra el encabezado"""
    print("")
    print("=" * 70)
    print("  ALPHAMAX OMNICAPITAL v1.0 - Sistema de Trading")
    print("=" * 70)
    print("")


def check_dependencies():
    """Verifica que las dependencias criticas esten instaladas"""
    missing = []
    deps = {
        'pandas': 'pandas',
        'numpy': 'numpy',
        'yfinance': 'yfinance',
        'yaml': 'pyyaml',
    }
    optional_deps = {
        'streamlit': 'streamlit',
        'plotly': 'plotly',
    }

    for module, package in deps.items():
        try:
            __import__(module)
        except ImportError:
            missing.append(package)

    if missing:
        print("[!] Dependencias faltantes: " + ", ".join(missing))
        print("    Instalar con: pip install " + " ".join(missing))
        print("")
        return False

    # Verificar opcionales (solo avisar)
    for module, package in optional_deps.items():
        try:
            __import__(module)
        except ImportError:
            print(f"[!] Opcional no instalado: {package} (necesario para Dashboard Web)")

    return True


def check_config():
    """Verifica que el archivo de configuracion exista"""
    config_path = BASE_DIR / "config" / "strategy.yaml"
    if not config_path.exists():
        print(f"[!] Archivo de configuracion no encontrado: {config_path}")
        return False
    return True


def ensure_directories():
    """Crea directorios necesarios"""
    for d in ['logs', 'reports', 'backtests', 'data']:
        (BASE_DIR / d).mkdir(exist_ok=True)


def print_menu():
    """Muestra el menu principal"""
    print_header()
    print("  Selecciona una opcion:")
    print("")
    print("  [1] Dashboard Web          (http://localhost:8501)")
    print("  [2] Analisis de Mercado    (oportunidades en vivo)")
    print("  [3] Trading Simulado       (iteracion de trading)")
    print("  [4] Backtest Historico     (testear estrategia)")
    print("  [5] Monitor Continuo       (tiempo real)")
    print("  [6] Ver Reportes           (reportes generados)")
    print("  [7] Diagnostico            (verificar sistema)")
    print("  [0] Salir")
    print("")
    print("-" * 70)


def run_dashboard():
    """Ejecuta el dashboard web con Streamlit"""
    clear_screen()
    print_header()

    # Verificar streamlit
    try:
        import streamlit
        print(f"  Streamlit v{streamlit.__version__} detectado")
    except ImportError:
        print("  [ERROR] Streamlit no esta instalado.")
        print("  Instalar con: pip install streamlit plotly")
        input("\n  Presiona Enter para volver al menu...")
        return

    # Verificar plotly
    try:
        import plotly
        print(f"  Plotly v{plotly.__version__} detectado")
    except ImportError:
        print("  [AVISO] Plotly no esta instalado. Algunos graficos no funcionaran.")
        print("  Instalar con: pip install plotly")

    dashboard_file = BASE_DIR / "dashboard.py"
    if not dashboard_file.exists():
        print(f"  [ERROR] No se encuentra: {dashboard_file}")
        input("\n  Presiona Enter para volver al menu...")
        return

    print("")
    print("  Abriendo dashboard...")
    print("  URL: http://localhost:8501")
    print("  Presiona Ctrl+C para detener")
    print("")

    try:
        subprocess.run([
            sys.executable, "-m", "streamlit", "run",
            str(dashboard_file),
            "--server.headless", "true"
        ])
    except KeyboardInterrupt:
        print("\n  Dashboard detenido.")
    except Exception as e:
        print(f"\n  [ERROR] {e}")

    input("\n  Presiona Enter para volver al menu...")


def run_analysis():
    """Ejecuta el analisis de mercado en vivo"""
    clear_screen()
    print_header()

    script = BASE_DIR / "omnicapital_v1_live.py"
    if not script.exists():
        print(f"  [ERROR] No se encuentra: {script}")
        input("\n  Presiona Enter para volver al menu...")
        return

    print("  Ejecutando analisis de mercado...")
    print("  Esto puede tomar varios minutos (descarga datos de ~50 acciones)")
    print("")

    try:
        result = subprocess.run(
            [sys.executable, str(script)],
            cwd=str(BASE_DIR)
        )
        if result.returncode == 0:
            print("\n  [OK] Analisis completado exitosamente")
        else:
            print(f"\n  [ERROR] El analisis termino con codigo {result.returncode}")
    except KeyboardInterrupt:
        print("\n  Analisis interrumpido.")
    except Exception as e:
        print(f"\n  [ERROR] {e}")

    input("\n  Presiona Enter para volver al menu...")


def run_trading():
    """Ejecuta trading simulado"""
    clear_screen()
    print_header()

    script = BASE_DIR / "src" / "main.py"
    if not script.exists():
        print(f"  [ERROR] No se encuentra: {script}")
        input("\n  Presiona Enter para volver al menu...")
        return

    print("  Ejecutando trading simulado...")
    print("  Modo: Una iteracion completa del algoritmo")
    print("")

    try:
        subprocess.run(
            [sys.executable, str(script), "--mode", "live"],
            cwd=str(BASE_DIR)
        )
    except KeyboardInterrupt:
        print("\n  Trading interrumpido.")
    except Exception as e:
        print(f"\n  [ERROR] {e}")

    input("\n  Presiona Enter para volver al menu...")


def run_backtest():
    """Ejecuta backtest historico"""
    clear_screen()
    print_header()

    script = BASE_DIR / "src" / "main.py"
    if not script.exists():
        print(f"  [ERROR] No se encuentra: {script}")
        input("\n  Presiona Enter para volver al menu...")
        return

    print("  BACKTEST HISTORICO")
    print("  " + "-" * 35)
    print("")

    start_date = input("  Fecha inicio (YYYY-MM-DD) [2024-01-01]: ").strip()
    end_date = input("  Fecha fin    (YYYY-MM-DD) [hoy]:        ").strip()

    if not start_date:
        start_date = "2024-01-01"
    if not end_date:
        end_date = datetime.now().strftime("%Y-%m-%d")

    # Validar formato de fechas
    for label, date_str in [("inicio", start_date), ("fin", end_date)]:
        try:
            datetime.strptime(date_str, "%Y-%m-%d")
        except ValueError:
            print(f"\n  [ERROR] Fecha de {label} invalida: {date_str}")
            print("  Formato esperado: YYYY-MM-DD (ej: 2024-01-01)")
            input("\n  Presiona Enter para volver al menu...")
            return

    print(f"\n  Ejecutando backtest desde {start_date} hasta {end_date}...")
    print("  Esto puede tomar varios minutos...")
    print("")

    try:
        result = subprocess.run(
            [
                sys.executable, str(script),
                "--mode", "backtest",
                "--start-date", start_date,
                "--end-date", end_date
            ],
            cwd=str(BASE_DIR)
        )
        if result.returncode == 0:
            print("\n  [OK] Backtest completado")
        else:
            print(f"\n  [ERROR] Backtest termino con codigo {result.returncode}")
    except KeyboardInterrupt:
        print("\n  Backtest interrumpido.")
    except Exception as e:
        print(f"\n  [ERROR] {e}")

    input("\n  Presiona Enter para volver al menu...")


def run_monitor():
    """Ejecuta monitor continuo"""
    clear_screen()
    print_header()

    script = BASE_DIR / "live_monitor.py"
    if not script.exists():
        print(f"  [ERROR] No se encuentra: {script}")
        input("\n  Presiona Enter para volver al menu...")
        return

    print("  MONITOR CONTINUO EN TIEMPO REAL")
    print("  " + "-" * 35)
    print("")

    interval = input("  Intervalo de actualizacion en segundos [60]: ").strip()
    if not interval:
        interval = "60"

    # Validar intervalo
    try:
        interval_int = int(interval)
        if interval_int < 10:
            print("  [AVISO] Intervalo minimo: 10 segundos")
            interval = "10"
    except ValueError:
        print("  [ERROR] Intervalo invalido, usando 60 segundos")
        interval = "60"

    print(f"\n  Iniciando monitor (intervalo: {interval}s)...")
    print("  Presiona Ctrl+C para detener")
    print("")

    try:
        subprocess.run(
            [sys.executable, str(script), "--interval", interval],
            cwd=str(BASE_DIR)
        )
    except KeyboardInterrupt:
        print("\n  Monitor detenido.")
    except Exception as e:
        print(f"\n  [ERROR] {e}")

    input("\n  Presiona Enter para volver al menu...")


def show_reports():
    """Muestra los reportes generados"""
    clear_screen()
    print_header()

    reports_dir = BASE_DIR / "reports"
    backtests_dir = BASE_DIR / "backtests"

    print("  REPORTES GENERADOS")
    print("  " + "-" * 35)
    print("")

    # Reportes
    if reports_dir.exists():
        files = sorted(
            [f for f in reports_dir.iterdir() if f.is_file()],
            key=lambda x: x.stat().st_mtime,
            reverse=True
        )
        if files:
            print(f"  Reportes ({len(files)}):")
            for i, f in enumerate(files[:15], 1):
                size_kb = f.stat().st_size / 1024
                mod_time = datetime.fromtimestamp(f.stat().st_mtime).strftime('%Y-%m-%d %H:%M')
                print(f"    {i:2}. {f.name:<50} {size_kb:6.1f} KB  ({mod_time})")
        else:
            print("  No hay reportes generados.")
    else:
        print("  Directorio de reportes no existe.")

    print("")

    # Backtests
    if backtests_dir.exists():
        bt_files = sorted(
            [f for f in backtests_dir.iterdir() if f.is_file()],
            key=lambda x: x.stat().st_mtime,
            reverse=True
        )
        if bt_files:
            print(f"  Backtests ({len(bt_files)}):")
            for i, f in enumerate(bt_files[:10], 1):
                size_kb = f.stat().st_size / 1024
                mod_time = datetime.fromtimestamp(f.stat().st_mtime).strftime('%Y-%m-%d %H:%M')
                print(f"    {i:2}. {f.name:<50} {size_kb:6.1f} KB  ({mod_time})")
        else:
            print("  No hay backtests generados.")

    input("\n  Presiona Enter para volver al menu...")


def run_diagnostics():
    """Verifica el estado del sistema"""
    clear_screen()
    print_header()
    print("  DIAGNOSTICO DEL SISTEMA")
    print("  " + "-" * 35)
    print("")

    # Python
    print(f"  Python:        {sys.version.split()[0]}")
    print(f"  Ejecutable:    {sys.executable}")
    print(f"  Plataforma:    {sys.platform}")
    print(f"  Directorio:    {BASE_DIR}")
    print("")

    # Dependencias
    print("  Dependencias:")
    deps = [
        ('pandas', 'pandas'),
        ('numpy', 'numpy'),
        ('yfinance', 'yfinance'),
        ('yaml', 'pyyaml'),
        ('scipy', 'scipy'),
        ('sklearn', 'scikit-learn'),
        ('streamlit', 'streamlit'),
        ('plotly', 'plotly'),
        ('matplotlib', 'matplotlib'),
    ]

    for module, package in deps:
        try:
            mod = __import__(module)
            version = getattr(mod, '__version__', 'OK')
            print(f"    [OK] {package:<20} v{version}")
        except ImportError:
            print(f"    [--] {package:<20} No instalado")

    print("")

    # Modulos del proyecto
    print("  Modulos del proyecto:")
    modules = [
        ('src.data.data_provider', 'Data Provider'),
        ('src.data.fundamental_provider', 'Fundamental Provider'),
        ('src.signals.technical', 'Technical Signals'),
        ('src.signals.fundamental', 'Fundamental Signals'),
        ('src.signals.composite', 'Composite Signals'),
        ('src.core.portfolio', 'Portfolio'),
        ('src.core.engine', 'Trading Engine'),
        ('src.risk.position_risk', 'Position Risk'),
        ('src.risk.portfolio_risk', 'Portfolio Risk'),
        ('src.execution.executor', 'Trade Executor'),
    ]

    sys.path.insert(0, str(BASE_DIR))
    for module, name in modules:
        try:
            __import__(module)
            print(f"    [OK] {name}")
        except Exception as e:
            print(f"    [!!] {name}: {e}")

    print("")

    # Archivos criticos
    print("  Archivos criticos:")
    files = [
        'config/strategy.yaml',
        'src/main.py',
        'omnicapital_v1_live.py',
        'live_monitor.py',
        'dashboard.py',
    ]
    for f in files:
        path = BASE_DIR / f
        status = "[OK]" if path.exists() else "[!!]"
        print(f"    {status} {f}")

    print("")

    # Directorios
    print("  Directorios:")
    for d in ['logs', 'reports', 'backtests', 'config', 'src']:
        path = BASE_DIR / d
        status = "[OK]" if path.exists() else "[--]"
        print(f"    {status} {d}/")

    print("")

    # Test rapido de conexion a datos
    print("  Test de conexion a datos:")
    try:
        sys.path.insert(0, str(BASE_DIR))
        from src.data.data_provider import YFinanceProvider
        provider = YFinanceProvider()
        price = provider.get_current_price(['AAPL'])
        if price.get('AAPL', 0) > 0:
            print(f"    [OK] Yahoo Finance - AAPL: ${price['AAPL']:.2f}")
        else:
            print("    [!!] Yahoo Finance - No se obtuvo precio")
    except Exception as e:
        print(f"    [!!] Yahoo Finance - Error: {e}")

    input("\n  Presiona Enter para volver al menu...")


def main():
    """Funcion principal"""
    # Verificaciones iniciales
    ensure_directories()

    if not check_config():
        print("  [ERROR] Configuracion no encontrada. Verifica la instalacion.")
        sys.exit(1)

    if not check_dependencies():
        print("")
        resp = input("  Continuar de todos modos? (s/n): ").strip().lower()
        if resp != 's':
            sys.exit(1)

    while True:
        clear_screen()
        print_menu()

        choice = input("  Opcion: ").strip()

        if choice == "1":
            run_dashboard()
        elif choice == "2":
            run_analysis()
        elif choice == "3":
            run_trading()
        elif choice == "4":
            run_backtest()
        elif choice == "5":
            run_monitor()
        elif choice == "6":
            show_reports()
        elif choice == "7":
            run_diagnostics()
        elif choice == "0":
            clear_screen()
            print_header()
            print("  Gracias por usar OmniCapital v1.0!")
            print("")
            break
        else:
            input("\n  Opcion invalida. Presiona Enter...")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        clear_screen()
        print_header()
        print("  Gracias por usar OmniCapital v1.0!")
        print("")
        sys.exit(0)
