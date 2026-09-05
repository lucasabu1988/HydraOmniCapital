"""
COMPASS v8.2 - Deployment Setup Script
=======================================
Run on the deployment PC to set up the trading environment.
"""

import subprocess
import sys
import os


def check_python():
    """Verify Python version"""
    version = sys.version_info
    print(f"Python version: {version.major}.{version.minor}.{version.micro}")
    if version.major < 3 or (version.major == 3 and version.minor < 10):
        print("WARNING: Python 3.10+ recommended")
        return False
    print("  OK")
    return True


def install_dependencies():
    """Install required packages"""
    print("\nInstalling dependencies...")
    result = subprocess.run(
        [sys.executable, '-m', 'pip', 'install', '-r', 'requirements.txt'],
        capture_output=True, text=True
    )
    if result.returncode != 0:
        print(f"  ERROR: {result.stderr}")
        return False
    print("  OK")
    return True


def create_directories():
    """Create required directories"""
    print("\nCreating directories...")
    dirs = ['logs', 'state', 'data_cache', 'backtests']
    for d in dirs:
        os.makedirs(d, exist_ok=True)
        print(f"  {d}/ OK")
    return True


def check_data_feed():
    """Verify data feed connectivity"""
    print("\nChecking data feed...")
    try:
        import yfinance as yf
        spy = yf.download('SPY', period='5d', progress=False)
        if len(spy) > 0:
            price = spy['Close'].iloc[-1]
            if hasattr(price, 'item'):
                price = price.item()
            print(f"  SPY price: ${price:.2f}")
            print("  OK")
            return True
        else:
            print("  ERROR: No data received")
            return False
    except Exception as e:
        print(f"  ERROR: {e}")
        return False


def check_config():
    """Check configuration file"""
    print("\nChecking configuration...")
    config_file = 'omnicapital_config.json'
    if os.path.exists(config_file):
        import json
        with open(config_file) as f:
            config = json.load(f)
        env = config.get('environment', 'unknown')
        email = config.get('email', {})
        has_email = bool(email.get('sender') and email.get('password'))
        print(f"  Environment: {env}")
        print(f"  Email configured: {'Yes' if has_email else 'No (configure in omnicapital_config.json)'}")
        print("  OK")
        return True
    else:
        print(f"  WARNING: {config_file} not found")
        return False


def run_tests():
    """Run unit tests"""
    print("\nRunning tests...")
    result = subprocess.run(
        [sys.executable, '-m', 'pytest', 'test_live_system.py', '-v', '--tb=short'],
        capture_output=True, text=True
    )
    print(result.stdout[-500:] if len(result.stdout) > 500 else result.stdout)
    if result.returncode != 0:
        print(f"  WARNING: Some tests failed")
        return False
    print("  OK")
    return True


def run_signal_validation():
    """Run signal validation"""
    print("\nRunning signal validation...")
    result = subprocess.run(
        [sys.executable, 'validate_v8_signals.py'],
        capture_output=True, text=True, timeout=300
    )
    # Show last portion of output
    output = result.stdout[-1000:] if len(result.stdout) > 1000 else result.stdout
    print(output)
    if result.returncode != 0:
        print("  WARNING: Signal validation had issues")
        return False
    return True


def main():
    print("=" * 60)
    print("COMPASS v8.2 - DEPLOYMENT SETUP")
    print("=" * 60)

    results = {}
    results['python'] = check_python()
    results['deps'] = install_dependencies()
    results['dirs'] = create_directories()
    results['data'] = check_data_feed()
    results['config'] = check_config()
    results['tests'] = run_tests()

    # Signal validation is optional (takes time)
    print("\nRun signal validation? (downloads real market data, ~2 min)")
    try:
        answer = input("y/n: ").strip().lower()
        if answer == 'y':
            results['signals'] = run_signal_validation()
    except EOFError:
        pass

    print("\n" + "=" * 60)
    print("SETUP SUMMARY")
    print("=" * 60)

    all_ok = True
    for check, passed in results.items():
        status = "OK" if passed else "ISSUE"
        print(f"  [{status:5s}] {check}")
        if not passed:
            all_ok = False

    if all_ok:
        print("\nSetup complete! Start trading with:")
        print("  python omnicapital_live.py")
        print("  or double-click start_omnicapital.bat")
    else:
        print("\nSome checks failed. Fix issues before starting live trading.")

    return all_ok


if __name__ == '__main__':
    success = main()
    sys.exit(0 if success else 1)
