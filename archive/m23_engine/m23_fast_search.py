"""
Fast M23 polynomial search - pure Python GF(p) arithmetic, no sympy.
"""
import time
import math
import random
import sys

random.seed(666)

# M23 allowed cycle types (partitions of 23) - computed from Golay code construction
ALLOWED = {
    (1,)*23,                                    # identity
    (1,1,1,1,1,1,1,2,2,2,2,2,2,2,2),          # 1^7 2^8
    (1,1,1,1,1,3,3,3,3,3,3),                   # 1^5 3^6
    (1,1,1,2,2,4,4,4,4),                        # 1^3 2^2 4^4
    (1,1,1,5,5,5,5),                             # 1^3 5^4
    (1,1,7,7,7),                                 # 1^2 7^3
    (1,2,2,3,3,6,6),                             # 1^1 2^2 3^2 6^2
    (1,2,4,8,8),                                 # 1^1 2^1 4^1 8^2
    (1,11,11),                                   # 1^1 11^2
    (2,7,14),                                    # 2^1 7^1 14^1
    (3,5,15),                                    # 3^1 5^1 15^1
    (23,),                                       # 23-cycle
}

print(f"M23: {len(ALLOWED)} allowed partitions of 23", flush=True)

# --- Fast GF(p) polynomial arithmetic ---
# Polynomials as lists, little-endian: [a0, a1, ..., an]

def poly_strip(a):
    while a and a[-1] == 0: a.pop()
    return a if a else []

def poly_mod_p(a, m, p):
    """a mod m over GF(p)."""
    a = [x % p for x in a]
    a = poly_strip(a)
    m = poly_strip([x % p for x in m])
    if not m:
        return a
    dm = len(m) - 1
    inv_lc = pow(m[-1], -1, p)
    while len(a) > dm:
        if a[-1] != 0:
            c = (a[-1] * inv_lc) % p
            offset = len(a) - len(m)
            for i in range(len(m)):
                a[offset + i] = (a[offset + i] - c * m[i]) % p
        a.pop()
    return poly_strip(a)

def poly_mulmod(a, b, m, p):
    """a * b mod m over GF(p)."""
    la, lb = len(a), len(b)
    if la == 0 or lb == 0: return []
    r = [0] * (la + lb - 1)
    for i in range(la):
        if a[i]:
            ai = a[i]
            for j in range(lb):
                if b[j]:
                    r[i+j] = (r[i+j] + ai * b[j]) % p
    return poly_mod_p(r, m, p)

def poly_powmod(base, exp, m, p):
    """base^exp mod m over GF(p)."""
    result = [1]
    base = poly_mod_p(list(base), m, p)
    while exp > 0:
        if exp & 1:
            result = poly_mulmod(result, base, m, p)
        base = poly_mulmod(base, base, m, p)
        exp >>= 1
    return result

def poly_gcd(a, b, p):
    """GCD over GF(p)."""
    a = poly_strip([x % p for x in a])
    b = poly_strip([x % p for x in b])
    while b:
        a, b = b, poly_mod_p(list(a), b, p)
    if a:
        inv = pow(a[-1], -1, p)
        a = [(c * inv) % p for c in a]
    return a if a else []

def poly_div(f, g, p):
    """f / g over GF(p), assuming g divides f."""
    f = list(f)
    dg = len(g) - 1
    if dg == 0:
        inv = pow(g[0], -1, p)
        return [(c * inv) % p for c in f]
    inv_lc = pow(g[-1], -1, p)
    q = [0] * (len(f) - dg)
    for i in range(len(q) - 1, -1, -1):
        if f[i + dg] != 0:
            c = (f[i + dg] * inv_lc) % p
            q[i] = c
            for j in range(len(g)):
                f[i + j] = (f[i + j] - c * g[j]) % p
    while q and q[-1] == 0: q.pop()
    return q if q else [0]

def factorization_pattern(coeffs, p):
    """Distinct-degree factorization: returns sorted tuple of irred factor degrees."""
    f = [c % p for c in coeffs]
    while f and f[-1] == 0: f.pop()
    if not f: return None
    n = len(f) - 1
    if n != 23: return None  # degree dropped

    # Make monic
    inv_lc = pow(f[-1], -1, p)
    f = [(c * inv_lc) % p for c in f]

    pattern = []
    remaining = list(f)

    # x^(p^k) mod remaining, starting from x
    xpk = [0, 1]  # x
    for k in range(1, 24):
        deg_r = len(remaining) - 1
        if deg_r <= 0:
            break

        # xpk = xpk^p mod remaining
        xpk = poly_powmod(xpk, p, remaining, p)

        # g = gcd(remaining, xpk - x)
        temp = list(xpk)
        while len(temp) < 2: temp.append(0)
        temp[1] = (temp[1] - 1) % p
        # Remove trailing zeros
        while temp and temp[-1] == 0: temp.pop()
        if not temp: temp = [0]

        g = poly_gcd(list(remaining), temp, p)
        deg_g = (len(g) - 1) if g else 0

        if deg_g > 0:
            count = deg_g // k
            pattern.extend([k] * count)
            # Divide remaining by g
            remaining = poly_div(remaining, g, p)
            remaining = poly_strip(remaining)
            if not remaining:
                remaining = [1]
            # Reduce xpk mod new remaining
            if len(remaining) > 1:
                xpk = poly_mod_p(list(xpk), remaining, p)
            else:
                break

        if len(remaining) <= 1:
            break

    # If remaining has degree > 0, it's one more irreducible factor
    deg_rem = len(remaining) - 1 if remaining else 0
    if deg_rem > 0:
        pattern.append(deg_rem)

    result = tuple(sorted(pattern))
    # Verify partition sums to 23
    if sum(result) != 23:
        return None
    return result

# Test with known polynomials
print("Testing factorization engine...", flush=True)
# x^23 - 1 mod 2: factors as (x+1)(x^11+x^9+x^7+x^6+x^5+x+1)(x^11+x^10+x^6+x^5+x^4+x^2+1)
test = [-1] + [0]*22 + [1]  # x^23 - 1
pat = factorization_pattern(test, 2)
print(f"  x^23-1 mod 2: {pat}", flush=True)  # Should be (1, 11, 11)

pat = factorization_pattern(test, 47)
print(f"  x^23-1 mod 47: {pat}", flush=True)  # 47 = 2*23+1, so x^23-1 splits completely

# x^23 + x + 1
test2 = [1, 1] + [0]*21 + [1]
for p in [2, 3, 5, 7, 11]:
    pat = factorization_pattern(test2, p)
    print(f"  x^23+x+1 mod {p}: {pat}", flush=True)

# --- Benchmark ---
print("\nBenchmarking...", flush=True)
PRIMES = [2,3,5,7,11,13,17,19,29,31,37,41,43,47,53,59,61,67,71,73,79,83,89,97]
t0 = time.time()
count = 0
for a in range(-50, 51):
    for b in range(-50, 51):
        coeffs = [b, a] + [0]*21 + [1]
        for p in PRIMES[:5]:
            factorization_pattern(coeffs, p)
        count += 1
elapsed = time.time() - t0
print(f"  {count} polys x 5 primes in {elapsed:.2f}s = {count/elapsed:.0f} poly/sec", flush=True)

# --- Main search ---
print(f"\n{'='*60}", flush=True)
print("M23 POLYNOMIAL SEARCH", flush=True)
print(f"{'='*60}", flush=True)

def check_poly(coeffs, max_primes=24):
    """Check factorization patterns against M23. Returns number of primes passed."""
    passed = 0
    for p in PRIMES[:max_primes]:
        if coeffs[-1] % p == 0:
            continue
        pat = factorization_pattern(coeffs, p)
        if pat is None:
            continue
        if pat not in ALLOWED:
            return passed
        passed += 1
    return passed

# Strategy 1: Trinomials x^23 + ax + b
print(f"\nSTRATEGY 1: Trinomials x^23 + ax + b", flush=True)
best = 0
tested = 0
t0 = time.time()
for a in range(-1000, 1001):
    for b in range(-1000, 1001):
        if a == 0 and b == 0: continue
        coeffs = [b, a] + [0]*21 + [1]
        passed = check_poly(coeffs)
        tested += 1
        if passed > best:
            best = passed
            print(f"  BEST={passed}: x^23 + {a}x + {b} [{tested} tested, {time.time()-t0:.1f}s]",
                  flush=True)
            if passed >= 20:
                print(f"  *** STRONG CANDIDATE! ***", flush=True)
    if a % 200 == 0 and a != 0:
        elapsed = time.time() - t0
        print(f"  a={a}, {tested} tested, best={best}, {tested/elapsed:.0f}/s, {elapsed:.0f}s",
              flush=True)

elapsed = time.time() - t0
print(f"  Trinomials done: {tested} in {elapsed:.1f}s, best={best}", flush=True)

# Strategy 2: Random sparse
print(f"\nSTRATEGY 2: Random sparse polynomials", flush=True)
best = 0
t0 = time.time()
for trial in range(1, 5000001):
    coeffs = [0]*24
    coeffs[23] = 1
    nt = random.randint(2, 5)
    for _ in range(nt):
        k = random.randint(0, 22)
        coeffs[k] = random.randint(-500, 500)
    if all(c == 0 for c in coeffs[:23]): continue

    passed = check_poly(coeffs)
    if passed > best:
        best = passed
        nz = {i: coeffs[i] for i in range(24) if coeffs[i]}
        print(f"  BEST={passed}: {nz} [{trial} trials, {time.time()-t0:.1f}s]", flush=True)
        if passed >= 20:
            print(f"  *** STRONG CANDIDATE! ***", flush=True)
    if trial % 500000 == 0:
        elapsed = time.time() - t0
        print(f"  {trial} trials, best={best}, {trial/elapsed:.0f}/s, {elapsed:.0f}s", flush=True)

elapsed = time.time() - t0
print(f"  Random done: 5M trials in {elapsed:.1f}s, best={best}", flush=True)

print(f"\n{'='*60}", flush=True)
print("Search complete.", flush=True)
print("If best < 10: almost certainly no M23 polynomial in search space.", flush=True)
print("(Expected - this is an OPEN PROBLEM in mathematics.)", flush=True)
