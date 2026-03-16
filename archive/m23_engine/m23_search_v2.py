"""
M23 polynomial search - optimized with GF(2) bit-vector arithmetic.
Key insight: ~93% of random polynomials fail the M23 test at p=2.
By making the p=2 check ultra-fast (bit ops), we get massive speedup.
"""
import time
import random
import sys

random.seed(666)

# M23 allowed partitions of 23
ALLOWED = {
    (1,)*23, (1,1,1,1,1,1,1,2,2,2,2,2,2,2,2), (1,1,1,1,1,3,3,3,3,3,3),
    (1,1,1,2,2,4,4,4,4), (1,1,1,5,5,5,5), (1,1,7,7,7),
    (1,2,2,3,3,6,6), (1,2,4,8,8), (1,11,11),
    (2,7,14), (3,5,15), (23,),
}

# --- Ultra-fast GF(2) polynomial arithmetic using integers as bit vectors ---
# Bit i of integer = coefficient of x^i

def gf2_mod(a, m, deg_m):
    """a mod m over GF(2). m has degree deg_m."""
    while a.bit_length() - 1 >= deg_m:
        shift = (a.bit_length() - 1) - deg_m
        a ^= (m << shift)
    return a

def gf2_mulmod(a, b, m, deg_m):
    """a * b mod m over GF(2)."""
    result = 0
    while b:
        if b & 1:
            result ^= a
        a <<= 1
        if a.bit_length() - 1 >= deg_m:
            a ^= (m << ((a.bit_length() - 1) - deg_m))
        b >>= 1
    return result

def gf2_powmod(base, exp, m, deg_m):
    """base^exp mod m over GF(2)."""
    result = 1
    base = gf2_mod(base, m, deg_m)
    while exp > 0:
        if exp & 1:
            result = gf2_mulmod(result, base, m, deg_m)
        base = gf2_mulmod(base, base, m, deg_m)
        exp >>= 1
    return result

def gf2_gcd(a, b):
    """GCD over GF(2)."""
    while b:
        if a.bit_length() < b.bit_length():
            a, b = b, a
        a = gf2_mod(a, b, b.bit_length() - 1)
    return a

def gf2_degree(a):
    return a.bit_length() - 1 if a else -1

def gf2_div(f, g):
    """f / g over GF(2)."""
    dg = gf2_degree(g)
    q = 0
    while gf2_degree(f) >= dg:
        shift = gf2_degree(f) - dg
        q |= (1 << shift)
        f ^= (g << shift)
    return q

def gf2_factorization_pattern(coeffs):
    """Factorization pattern of degree-23 polynomial mod 2 using bit-vector ops."""
    # Convert coefficients to GF(2) bit vector
    f = 0
    for i in range(24):
        if coeffs[i] & 1:
            f |= (1 << i)
    if gf2_degree(f) != 23:
        return None

    remaining = f
    xpk = 2  # x = bit 1 set
    pattern = []

    for k in range(1, 24):
        deg_r = gf2_degree(remaining)
        if deg_r <= 0:
            break

        # xpk = xpk^2 mod remaining (squaring in GF(2) = raising to p=2)
        xpk = gf2_mulmod(xpk, xpk, remaining, deg_r)

        # temp = xpk + x (XOR in GF(2))
        temp = xpk ^ 2  # XOR with x (bit 1)

        if temp == 0:
            # gcd = remaining
            g = remaining
        else:
            g = gf2_gcd(remaining, temp)

        deg_g = gf2_degree(g)
        if deg_g > 0:
            count = deg_g // k
            pattern.extend([k] * count)
            remaining = gf2_div(remaining, g)
            if gf2_degree(remaining) > 0:
                xpk = gf2_mod(xpk, remaining, gf2_degree(remaining))
            else:
                break

        if gf2_degree(remaining) <= 0:
            break

    if gf2_degree(remaining) > 0:
        pattern.append(gf2_degree(remaining))

    result = tuple(sorted(pattern))
    return result if sum(result) == 23 else None

# --- Generic GF(p) factorization for p > 2 ---
def generic_factorization_pattern(coeffs, p):
    """Factorization pattern of degree-23 poly mod p, for p > 2."""
    n = 23
    f = [c % p for c in coeffs[:24]]
    # Check degree
    while len(f) > 1 and f[-1] == 0:
        f.pop()
    if len(f) - 1 != n:
        return None

    # Make monic
    inv_lc = pow(f[-1], -1, p)
    f = [(c * inv_lc) % p for c in f]

    # Working arrays - preallocate
    remaining = list(f)
    rem_deg = n

    # xpk = x initially
    xpk = [0] * (n + 1)
    xpk[1] = 1
    xpk_deg = 1

    pattern = []

    for k in range(1, n + 1):
        if rem_deg <= 0:
            break

        # xpk = xpk^p mod remaining
        # Square-and-multiply
        base = xpk[:rem_deg + 1]  # truncate to remaining's degree
        result = [0] * (rem_deg + 1)
        result[0] = 1
        result_deg = 0

        exp = p
        # Inline powmod for speed
        while exp > 0:
            if exp & 1:
                # result = result * base mod remaining
                new = [0] * (rem_deg * 2 + 1)
                for i in range(result_deg + 1):
                    if result[i] == 0: continue
                    ri = result[i]
                    for j in range(min(len(base), rem_deg + 1)):
                        if base[j] == 0: continue
                        new[i+j] = (new[i+j] + ri * base[j]) % p
                # Reduce mod remaining
                inv_r = pow(remaining[rem_deg], -1, p)
                nd = len(new) - 1
                while nd > len(new) - 1 or (nd >= 0 and new[nd] == 0):
                    nd -= 1
                    if nd < 0: break
                nd = min(2 * rem_deg, len(new) - 1)
                while nd >= rem_deg:
                    if new[nd] != 0:
                        c = (new[nd] * inv_r) % p
                        off = nd - rem_deg
                        for ii in range(rem_deg + 1):
                            new[off + ii] = (new[off + ii] - c * remaining[ii]) % p
                    nd -= 1
                result = new[:rem_deg + 1]
                result_deg = rem_deg
                while result_deg > 0 and result[result_deg] == 0:
                    result_deg -= 1

            # base = base * base mod remaining
            new = [0] * (rem_deg * 2 + 1)
            bd = min(len(base) - 1, rem_deg)
            for i in range(bd + 1):
                if base[i] == 0: continue
                bi = base[i]
                for j in range(bd + 1):
                    if base[j] == 0: continue
                    new[i+j] = (new[i+j] + bi * base[j]) % p
            inv_r = pow(remaining[rem_deg], -1, p)
            nd = min(2 * rem_deg, len(new) - 1)
            while nd >= rem_deg:
                if new[nd] != 0:
                    c = (new[nd] * inv_r) % p
                    off = nd - rem_deg
                    for ii in range(rem_deg + 1):
                        new[off + ii] = (new[off + ii] - c * remaining[ii]) % p
                nd -= 1
            base = new[:rem_deg + 1]

            exp >>= 1

        xpk = result[:rem_deg + 1]
        while len(xpk) <= rem_deg:
            xpk.append(0)

        # temp = xpk - x
        temp = list(xpk)
        temp[1] = (temp[1] - 1) % p
        temp_deg = rem_deg
        while temp_deg > 0 and temp[temp_deg] == 0:
            temp_deg -= 1

        # GCD
        if temp_deg < 0 or (temp_deg == 0 and temp[0] == 0):
            g = remaining[:rem_deg + 1]
            g_deg = rem_deg
        else:
            # Euclidean GCD
            a = remaining[:rem_deg + 1]
            a_deg = rem_deg
            b = temp[:temp_deg + 1]
            b_deg = temp_deg
            while b_deg >= 0 and not (b_deg == 0 and b[0] == 0):
                if a_deg < b_deg:
                    a, b = b, a
                    a_deg, b_deg = b_deg, a_deg
                # a = a mod b
                inv_b = pow(b[b_deg], -1, p)
                while a_deg >= b_deg:
                    if a[a_deg] != 0:
                        c = (a[a_deg] * inv_b) % p
                        off = a_deg - b_deg
                        for ii in range(b_deg + 1):
                            a[off + ii] = (a[off + ii] - c * b[ii]) % p
                    a_deg -= 1
                while a_deg > 0 and a[a_deg] == 0:
                    a_deg -= 1
                if a_deg == 0 and a[0] == 0:
                    a_deg = -1
            g = a[:a_deg + 1] if a_deg >= 0 else [0]
            g_deg = a_deg

        if g_deg > 0:
            count = g_deg // k
            pattern.extend([k] * count)
            # remaining = remaining / g
            inv_g = pow(g[g_deg], -1, p)
            new_deg = rem_deg - g_deg
            quot = [0] * (new_deg + 1)
            temp_r = remaining[:rem_deg + 1]
            for i in range(new_deg, -1, -1):
                c = (temp_r[i + g_deg] * inv_g) % p
                quot[i] = c
                for ii in range(g_deg + 1):
                    temp_r[i + ii] = (temp_r[i + ii] - c * g[ii]) % p
            remaining = quot
            rem_deg = new_deg
            while rem_deg > 0 and remaining[rem_deg] == 0:
                rem_deg -= 1
            # Reduce xpk
            if rem_deg > 0:
                while len(xpk) > rem_deg + 1:
                    xpk.pop()
                inv_r = pow(remaining[rem_deg], -1, p)
                xd = len(xpk) - 1
                while xd >= rem_deg:
                    if xpk[xd] != 0:
                        c = (xpk[xd] * inv_r) % p
                        off = xd - rem_deg
                        for ii in range(rem_deg + 1):
                            xpk[off + ii] = (xpk[off + ii] - c * remaining[ii]) % p
                    xd -= 1

        if rem_deg <= 0:
            break

    if rem_deg > 0:
        pattern.append(rem_deg)

    result = tuple(sorted(pattern))
    return result if sum(result) == 23 else None


PRIMES_GT2 = [3, 5, 7, 11, 13, 17, 19, 29, 31, 37, 41, 43, 47, 53, 59, 61, 67, 71, 73]

def check_m23(coeffs, max_extra_primes=18):
    """Check polynomial: first GF(2) (fast), then other primes."""
    # Fast GF(2) check
    pat = gf2_factorization_pattern(coeffs)
    if pat is not None and pat not in ALLOWED:
        return 0
    passed = 1 if pat is not None else 0

    # Check more primes
    for p in PRIMES_GT2[:max_extra_primes]:
        if coeffs[23] % p == 0:
            continue
        pat = generic_factorization_pattern(coeffs, p)
        if pat is None:
            continue
        if pat not in ALLOWED:
            return passed
        passed += 1
    return passed

# --- Quick test ---
print("Testing GF(2) engine...", flush=True)
test = [-1] + [0]*22 + [1]  # x^23 - 1
print(f"  x^23-1 mod 2: {gf2_factorization_pattern(test)}", flush=True)
test2 = [1, 1] + [0]*21 + [1]  # x^23 + x + 1
print(f"  x^23+x+1 mod 2: {gf2_factorization_pattern(test2)}", flush=True)

# Benchmark GF(2)
t0 = time.time()
count = 0
for a in range(-200, 201):
    for b in range(-200, 201):
        coeffs = [b, a] + [0]*21 + [1]
        gf2_factorization_pattern(coeffs)
        count += 1
elapsed = time.time() - t0
print(f"  GF(2) benchmark: {count} polys in {elapsed:.2f}s = {count/elapsed:.0f}/s", flush=True)

# Test generic
print("Testing generic engine (p=3)...", flush=True)
print(f"  x^23-1 mod 3: {generic_factorization_pattern([-1]+[0]*22+[1], 3)}", flush=True)
print(f"  x^23+x+1 mod 3: {generic_factorization_pattern([1,1]+[0]*21+[1], 3)}", flush=True)

# Benchmark with full check (GF(2) + 2 more primes)
t0 = time.time()
count = 0
best = 0
for a in range(-100, 101):
    for b in range(-100, 101):
        coeffs = [b, a] + [0]*21 + [1]
        p = check_m23(coeffs, max_extra_primes=3)
        if p > best:
            best = p
        count += 1
elapsed = time.time() - t0
print(f"  Full check (4 primes): {count} in {elapsed:.2f}s = {count/elapsed:.0f}/s, best={best}",
      flush=True)

# --- Main Search ---
print(f"\n{'='*60}", flush=True)
print("M23 POLYNOMIAL SEARCH", flush=True)
print(f"{'='*60}", flush=True)

best_overall = 0

# Strategy 1: Trinomials
print("\nStrategy 1: Trinomials x^23 + ax + b, |a|,|b| <= 3000", flush=True)
t0 = time.time()
tested = 0
for a in range(-3000, 3001):
    for b in range(-3000, 3001):
        if a == 0 and b == 0: continue
        coeffs = [b, a] + [0]*21 + [1]
        passed = check_m23(coeffs)
        tested += 1
        if passed > best_overall:
            best_overall = passed
            print(f"  BEST={passed}: x^23+{a}x+{b} [{tested} tested, {time.time()-t0:.1f}s]",
                  flush=True)
    if a % 500 == 0 and a >= 0:
        elapsed = time.time() - t0
        if elapsed > 0:
            print(f"  a={a}, {tested} tested, {tested/elapsed:.0f}/s, best={best_overall}",
                  flush=True)

print(f"  Done: {tested} in {time.time()-t0:.1f}s, best={best_overall}", flush=True)

# Strategy 2: x^23 + ax^k + b for various k
print("\nStrategy 2: x^23 + ax^k + b", flush=True)
t0 = time.time()
tested = 0
for k in [2, 3, 5, 7, 11, 13, 17, 19, 22]:
    for a in range(-1000, 1001):
        if a == 0: continue
        for b in range(-1000, 1001):
            if b == 0: continue
            coeffs = [0]*24
            coeffs[0] = b
            coeffs[k] = a
            coeffs[23] = 1
            passed = check_m23(coeffs)
            tested += 1
            if passed > best_overall:
                best_overall = passed
                print(f"  BEST={passed}: x^23+{a}x^{k}+{b} [{tested}, {time.time()-t0:.1f}s]",
                      flush=True)
    print(f"  k={k} done, {tested} tested, best={best_overall}", flush=True)

# Strategy 3: Random sparse
print("\nStrategy 3: Random sparse (50M trials)", flush=True)
t0 = time.time()
tested = 0
for trial in range(50000000):
    coeffs = [0]*24
    coeffs[23] = 1
    nt = random.randint(2, 5)
    for _ in range(nt):
        k = random.randint(0, 22)
        coeffs[k] = random.randint(-1000, 1000)
    if all(c == 0 for c in coeffs[:23]): continue
    passed = check_m23(coeffs)
    tested += 1
    if passed > best_overall:
        best_overall = passed
        nz = [(i, coeffs[i]) for i in range(24) if coeffs[i]]
        print(f"  BEST={passed}: {nz} [trial {trial}, {time.time()-t0:.1f}s]", flush=True)
    if trial % 5000000 == 0 and trial > 0:
        elapsed = time.time() - t0
        print(f"  {trial}M trials, {tested/elapsed:.0f}/s, best={best_overall}", flush=True)

print(f"\n{'='*60}", flush=True)
print(f"Search complete. Best: {best_overall} primes passed.", flush=True)
print("If best < 8: no M23 polynomial in search space (expected).", flush=True)
