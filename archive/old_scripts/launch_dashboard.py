"""
Script para lanzar el Dashboard de OmniCapital v1.0
"""

import subprocess
import sys
import os

def check_streamlit():
    """Verifica si Streamlit está instalado"""
    try:
        import streamlit
        return True
    except ImportError:
        return False

def install_requirements():
    """Instala dependencias necesarias"""
    print("📦 Instalando dependencias del dashboard...")
    subprocess.check_call([sys.executable, "-m", "pip", "install", "-q", "streamlit", "plotly"])
    print("✅ Dependencias instaladas")

def launch_dashboard():
    """Lanza el dashboard"""
    print("\n" + "="*80)
    print("🚀 LANZANDO OMNICAPITAL v1.0 DASHBOARD")
    print("="*80)
    print("\n📊 El dashboard se abrirá en tu navegador")
    print("🌐 URL: http://localhost:8501")
    print("\n⚠️  Para detener el dashboard, presiona Ctrl+C")
    print("="*80 + "\n")
    
    # Lanzar Streamlit
    subprocess.call([sys.executable, "-m", "streamlit", "run", "dashboard.py"])

if __name__ == '__main__':
    # Verificar/installar dependencias
    if not check_streamlit():
        print("⚠️  Streamlit no encontrado. Instalando...")
        install_requirements()
    
    # Lanzar dashboard
    launch_dashboard()
