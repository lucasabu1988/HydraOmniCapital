"""
M23 search: compile C engine with tinycc, run via ctypes.
"""
import tinycc
import ctypes
import time
import os

print("Compiling C engine with tinycc...", flush=True)
dll_path = tinycc.compile("m23_engine.c")
print(f"  Compiled: {dll_path}", flush=True)

dll_full = os.path.abspath(dll_path)
print(f"  Full path: {dll_full}", flush=True)
lib = ctypes.CDLL(dll_full)

# Bind functions
lib.check_m23.argtypes = [ctypes.POINTER(ctypes.c_longlong), ctypes.c_int]
lib.check_m23.restype = ctypes.c_int

lib.search_trinomials.argtypes = [
    ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
    ctypes.c_int, ctypes.POINTER(ctypes.c_int), ctypes.POINTER(ctypes.c_int)
]
lib.search_trinomials.restype = ctypes.c_int

lib.search_binomial_k.argtypes = [
    ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
    ctypes.c_int, ctypes.POINTER(ctypes.c_int), ctypes.POINTER(ctypes.c_int)
]
lib.search_binomial_k.restype = ctypes.c_int

# Quick test
print("\nTesting...", flush=True)
CoeffsType = ctypes.c_longlong * 24
coeffs = CoeffsType()
for i in range(24): coeffs[i] = 0
coeffs[0] = -1; coeffs[23] = 1  # x^23 - 1
result = lib.check_m23(coeffs, 24)
print(f"  x^23-1: passed {result} primes", flush=True)

coeffs[0] = 1; coeffs[1] = 1  # x^23 + x + 1
for i in range(2, 23): coeffs[i] = 0
coeffs[23] = 1
result = lib.check_m23(coeffs, 24)
print(f"  x^23+x+1: passed {result} primes", flush=True)

# Benchmark
print("\nBenchmarking trinomials...", flush=True)
best_a = ctypes.c_int(0)
best_b = ctypes.c_int(0)
t0 = time.time()
best = lib.search_trinomials(-500, 500, -500, 500, 20, ctypes.byref(best_a), ctypes.byref(best_b))
elapsed = time.time() - t0
count = 1001 * 1001 - 1
print(f"  {count} trinomials in {elapsed:.2f}s = {count/elapsed:.0f}/s", flush=True)
print(f"  Best: {best} primes, a={best_a.value}, b={best_b.value}", flush=True)

# --- MAIN SEARCH ---
print(f"\n{'='*60}", flush=True)
print("M23 POLYNOMIAL SEARCH (C engine via tinycc)", flush=True)
print(f"{'='*60}", flush=True)

overall_best = 0

# Strategy 1: Trinomials x^23 + ax + b
NPRIMES = 24
RANGE = 5000

print(f"\nStrategy 1: Trinomials x^23+ax+b, |a|,|b| <= {RANGE}", flush=True)
chunk = 200  # small chunks for live progress
for a_start in range(-RANGE, RANGE+1, chunk):
    a_end = min(a_start + chunk - 1, RANGE)
    t0 = time.time()
    best = lib.search_trinomials(a_start, a_end, -RANGE, RANGE, NPRIMES,
                                  ctypes.byref(best_a), ctypes.byref(best_b))
    elapsed = time.time() - t0
    if best > overall_best:
        overall_best = best
        print(f"  NEW BEST={best}: x^23+{best_a.value}x+{best_b.value} "
              f"[a in [{a_start},{a_end}], {elapsed:.1f}s]", flush=True)
        if best >= 15:
            print(f"  *** STRONG CANDIDATE! ***", flush=True)
    else:
        if a_start % 4000 == 0:
            n = chunk * (2*RANGE+1)
            print(f"  a=[{a_start},{a_end}]: {n} tested, {n/elapsed:.0f}/s, best_chunk={best}, "
                  f"overall_best={overall_best}", flush=True)

total_tri = (2*RANGE+1)**2
print(f"  Trinomials done: ~{total_tri} tested, overall best={overall_best}", flush=True)

# Strategy 2: x^23 + ax^k + b for various k
print(f"\nStrategy 2: x^23 + a*x^k + b, |a|,|b| <= 5000", flush=True)
R2 = 3000
for k in [2, 3, 5, 7, 11, 13, 17, 19, 22]:
    t0 = time.time()
    best = lib.search_binomial_k(k, -R2, R2, -R2, R2, NPRIMES,
                                  ctypes.byref(best_a), ctypes.byref(best_b))
    elapsed = time.time() - t0
    if best > overall_best:
        overall_best = best
        print(f"  NEW BEST={best}: x^23+{best_a.value}x^{k}+{best_b.value} [{elapsed:.1f}s]",
              flush=True)
    else:
        n = (2*R2)*(2*R2+1)
        print(f"  k={k}: {n} tested, {n/elapsed:.0f}/s, best_k={best}, overall={overall_best}",
              flush=True)

print(f"\n{'='*60}", flush=True)
print(f"Search complete. Overall best: {overall_best} primes passed.", flush=True)
if overall_best >= 15:
    print("A strong candidate was found! Further verification needed.", flush=True)
else:
    print("No M23 polynomial found (expected - this is an open problem).", flush=True)
    print("The inverse Galois problem for M23 over Q remains unsolved.", flush=True)

# Cleanup
try: os.remove(dll_path)
except: pass
