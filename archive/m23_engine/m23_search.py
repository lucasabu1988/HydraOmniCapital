"""
Search for degree-23 polynomial in Z[x] with Galois group M23.

Strategy:
- Factor f(x) mod p for many small primes
- Check if ALL factorization patterns match M23 cycle types (12 allowed partitions)
- This is an EXTREMELY strong filter (~7% pass rate per prime, ~0.07^k after k primes)
- Any polynomial passing 20+ primes is a serious candidate

WARNING: This is an open problem. M23 is the ONLY sporadic simple group not yet realized
over Q. The search is almost certainly futile, but we try anyway.
"""
import json
import time
import math
import random
from sympy.polys.galoistools import gf_factor
from sympy import ZZ

random.seed(666)

# Load M23 cycle types
with open("m23_data.json") as f:
    m23_data = json.load(f)

# The 12 allowed partitions (cycle types) of M23
ALLOWED = set()
for ct in m23_data["cycle_types"]:
    ALLOWED.add(tuple(ct))
# Add identity (might have been missed in random sampling)
ALLOWED.add(tuple([1]*23))

print(f"M23 has {len(ALLOWED)} allowed cycle types (partitions of 23)")
for p in sorted(ALLOWED):
    print(f"  {p}")

# Small primes for testing
PRIMES = [2, 3, 5, 7, 11, 13, 17, 19, 23, 29, 31, 37, 41, 43, 47, 53, 59, 61, 67, 71,
          73, 79, 83, 89, 97, 101, 103, 107, 109, 113]

def get_factorization_pattern(coeffs, p):
    """Get degree pattern of f(x) mod p using sympy's GF factoring.
    coeffs: [a_0, a_1, ..., a_23] (little-endian, a_23 is leading coeff)
    Returns sorted tuple of degrees of irreducible factors, or None if degenerate.
    """
    # Convert to sympy format (big-endian: [a_n, ..., a_1, a_0])
    f_sym = [int(c) % p for c in reversed(coeffs)]
    # Strip leading zeros
    while len(f_sym) > 1 and f_sym[0] == 0:
        f_sym.pop(0)
    if len(f_sym) <= 1:
        return None  # Degenerate mod p
    if len(f_sym) - 1 != 23:
        return None  # Degree dropped mod p (p divides leading coeff)

    try:
        lc, factors = gf_factor(f_sym, p, ZZ)
        degrees = []
        for factor, mult in factors:
            deg = len(factor) - 1
            for _ in range(mult):
                degrees.append(deg)
        return tuple(sorted(degrees))
    except Exception:
        return None

def check_polynomial(coeffs, num_primes=20):
    """Check if polynomial has M23-compatible factorizations mod many primes.
    Returns (num_passed, first_fail_prime) or (num_primes, None) if all pass.
    """
    passed = 0
    for p in PRIMES[:num_primes]:
        if coeffs[-1] % p == 0:
            continue  # Skip primes dividing leading coefficient
        pattern = get_factorization_pattern(coeffs, p)
        if pattern is None:
            continue
        if pattern not in ALLOWED:
            return passed, p
        passed += 1
    return passed, None

def is_perfect_square(n):
    """Check if n is a perfect square (n >= 0)."""
    if n < 0:
        return False
    if n == 0:
        return True
    root = math.isqrt(n)
    return root * root == n

# --- Search strategies ---

def make_monic_poly(lower_coeffs):
    """Create monic degree-23 polynomial coefficients [a0, a1, ..., a22, 1]."""
    coeffs = list(lower_coeffs)
    while len(coeffs) < 23:
        coeffs.append(0)
    coeffs.append(1)  # leading coefficient
    return coeffs

def search_trinomials(max_ab=500, report_interval=10000):
    """Search x^23 + a*x + b for small a, b."""
    print(f"\n{'='*60}")
    print(f"STRATEGY 1: Trinomials x^23 + a*x + b, |a|,|b| <= {max_ab}")
    print(f"{'='*60}")
    tested = 0
    best_pass = 0
    t0 = time.time()

    for a in range(-max_ab, max_ab + 1):
        for b in range(-max_ab, max_ab + 1):
            if a == 0 and b == 0:
                continue
            # coeffs: [b, a, 0, 0, ..., 0, 1] (little-endian)
            coeffs = [b, a] + [0]*21 + [1]
            passed, fail_p = check_polynomial(coeffs, num_primes=25)
            tested += 1

            if passed > best_pass:
                best_pass = passed
                elapsed = time.time() - t0
                print(f"  New best: x^23 + {a}x + {b} passed {passed} primes "
                      f"(failed at p={fail_p}) [{tested} tested, {elapsed:.1f}s]")

            if passed >= 25:
                print(f"\n  *** CANDIDATE FOUND: x^23 + {a}x + {b} ***")
                print(f"  Passed all {passed} prime tests!")
                return (a, b)

            if tested % report_interval == 0:
                elapsed = time.time() - t0
                rate = tested / elapsed if elapsed > 0 else 0
                print(f"  Progress: {tested} tested, best={best_pass} primes, "
                      f"{rate:.0f}/sec, {elapsed:.1f}s")

    elapsed = time.time() - t0
    print(f"  Done: {tested} trinomials tested in {elapsed:.1f}s, best={best_pass}")
    return None

def search_quadrinomials(max_c=100, report_interval=50000):
    """Search x^23 + a*x^k + b*x + c for various k and small coefficients."""
    print(f"\n{'='*60}")
    print(f"STRATEGY 2: Sparse polynomials x^23 + a*x^k + b*x + c")
    print(f"{'='*60}")
    tested = 0
    best_pass = 0
    t0 = time.time()

    for k in [2, 3, 5, 7, 11, 13, 17, 19, 22]:
        print(f"\n  Trying k={k}...")
        for a in range(-max_c, max_c + 1):
            if a == 0:
                continue
            for b in range(-max_c, max_c + 1):
                for c in range(-max_c, max_c + 1):
                    if b == 0 and c == 0:
                        continue
                    coeffs = [0] * 24
                    coeffs[0] = c
                    coeffs[1] = b
                    coeffs[k] = a
                    coeffs[23] = 1
                    passed, fail_p = check_polynomial(coeffs, num_primes=25)
                    tested += 1

                    if passed > best_pass:
                        best_pass = passed
                        elapsed = time.time() - t0
                        print(f"    New best: x^23+{a}x^{k}+{b}x+{c} passed {passed} primes "
                              f"[{tested} tested, {elapsed:.1f}s]")

                    if passed >= 25:
                        print(f"\n    *** CANDIDATE: x^23+{a}x^{k}+{b}x+{c} ***")
                        return coeffs

                    if tested % report_interval == 0:
                        elapsed = time.time() - t0
                        rate = tested / elapsed if elapsed > 0 else 0
                        print(f"    Progress: {tested} tested, best={best_pass}, "
                              f"{rate:.0f}/sec, {elapsed:.1f}s")

    elapsed = time.time() - t0
    print(f"  Done: {tested} tested in {elapsed:.1f}s, best={best_pass}")
    return None

def search_random_sparse(num_trials=5000000, max_coeff=1000, report_interval=100000):
    """Random sparse polynomials with 3-5 nonzero coefficients."""
    print(f"\n{'='*60}")
    print(f"STRATEGY 3: Random sparse polynomials ({num_trials} trials)")
    print(f"{'='*60}")
    best_pass = 0
    t0 = time.time()

    for trial in range(1, num_trials + 1):
        # Random sparse polynomial: x^23 + sum of 2-4 random terms
        coeffs = [0] * 24
        coeffs[23] = 1
        num_terms = random.randint(2, 4)
        for _ in range(num_terms):
            k = random.randint(0, 22)
            coeffs[k] = random.randint(-max_coeff, max_coeff)
        if all(c == 0 for c in coeffs[:23]):
            continue

        passed, fail_p = check_polynomial(coeffs, num_primes=25)

        if passed > best_pass:
            best_pass = passed
            elapsed = time.time() - t0
            nonzero = [(i, coeffs[i]) for i in range(24) if coeffs[i] != 0]
            print(f"  New best: {nonzero} passed {passed} primes [{trial} trials, {elapsed:.1f}s]")

        if passed >= 25:
            print(f"\n  *** CANDIDATE FOUND ***")
            return coeffs

        if trial % report_interval == 0:
            elapsed = time.time() - t0
            rate = trial / elapsed if elapsed > 0 else 0
            print(f"  Progress: {trial}/{num_trials}, best={best_pass}, "
                  f"{rate:.0f}/sec, {elapsed:.1f}s")

    elapsed = time.time() - t0
    print(f"  Done: {num_trials} trials in {elapsed:.1f}s, best={best_pass}")
    return None

# --- Main ---
if __name__ == "__main__":
    print("="*60)
    print("M23 POLYNOMIAL SEARCH ENGINE")
    print("Searching for f(x) in Z[x], deg 23, Gal(f/Q) = M23")
    print("This is an OPEN PROBLEM (only unsolved sporadic group)")
    print("="*60)

    # Strategy 1: Trinomials (fastest to scan)
    result = search_trinomials(max_ab=200)

    if result is None:
        # Strategy 2: Quadrinomials (moderate parameter space)
        result = search_quadrinomials(max_c=30)

    if result is None:
        # Strategy 3: Random sparse (shotgun approach)
        result = search_random_sparse(num_trials=2000000, max_coeff=500)

    if result is not None:
        print("\n" + "!"*60)
        print("POTENTIAL M23 POLYNOMIAL FOUND!")
        print("!"*60)
    else:
        print("\n" + "-"*60)
        print("No candidate found. (Expected - this is an open problem.)")
        print("The inverse Galois problem for M23 over Q remains unsolved.")
        print("-"*60)
