import os
import glob
import re

def audit_coverage():
    # 1. List root .py files (excluding specific dirs/files)
    exclude_dirs = {'archive', 'docs', 'scripts', 'tests', 'data', 'logs', 'state', 'backtests'}
    root_files = []
    
    for item in os.listdir('.'):
        if item.endswith('.py') and os.path.isfile(item):
            root_files.append(item)
            
    # 2. Find test files in root
    test_files = [f for f in root_files if f.startswith('test_') or f.endswith('_test.py')]
    production_files = [f for f in root_files if f not in test_files and f != 'conftest.py']

    print(f"Found {len(production_files)} production files and {len(test_files)} test files.")

    results = []

    for prod_file in production_files:
        module_name = prod_file.replace('.py', '')
        # Count references in test files
        ref_count = 0
        for test_file in test_files:
            try:
                with open(test_file, 'r', encoding='utf-8') as f:
                    content = f.read()
                    if module_name in content:
                        ref_count += 1
            except Exception:
                pass
        
        # Count LOC
        try:
            with open(prod_file, 'r', encoding='utf-8') as f:
                loc = sum(1 for line in f if line.strip() and not line.strip().startswith('#'))
        except:
            loc = 0
            
        # Score: Ref Count / LOC (lower is worse coverage)
        # Prevent div by zero
        score = ref_count / max(1, loc)
        
        results.append({
            'file': prod_file,
            'refs': ref_count,
            'loc': loc,
            'score': score
        })

    # Sort by score (ascending) -> gaps
    results.sort(key=lambda x: x['score'])
    
    print("\nTop 10 Files with Lowest Coverage Score (Refs / LOC):")
    print(f"{'File':<40} {'Refs':<5} {'LOC':<6} {'Score':<10}")
    print("-" * 65)
    for r in results[:10]:
        print(f"{r['file']:<40} {r['refs']:<5} {r['loc']:<6} {r['score']:.6f}")

    # Specific check for edge cases
    targets = ['compass_portfolio_risk.py', 'compass_montecarlo.py', 'compass_trade_analytics.py']
    print("\nEdge Case Check:")
    for t in targets:
        found = False
        for tf in test_files:
            try:
                with open(tf, 'r', encoding='utf-8') as f:
                    content = f.read()
                    if t.replace('.py', '') in content:
                        if 'empty' in content or 'ZeroDivisionError' in content or 'single' in content:
                            print(f"[OK] {t} checked in {tf} for edge cases")
                            found = True
            except:
                pass
        if not found:
            print(f"[WARN] {t} needs edge case tests")

if __name__ == "__main__":
    audit_coverage()
