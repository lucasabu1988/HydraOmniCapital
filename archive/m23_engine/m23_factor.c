/*
 * Fast GF(p) polynomial factorization pattern for degree-23 polynomials.
 * Returns the factorization pattern (sorted list of irred factor degrees).
 * Compiled as: gcc -O3 -o m23_factor m23_factor.exe m23_factor.c
 * Usage: reads polynomial coefficients from stdin, outputs patterns.
 */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#define MAXDEG 24

typedef struct {
    int deg;
    long long c[MAXDEG+1]; // coefficients, c[0] = constant term
} Poly;

static long long mod(long long a, long long p) {
    a %= p;
    return a < 0 ? a + p : a;
}

static long long power_mod(long long base, long long exp, long long p) {
    long long result = 1;
    base = mod(base, p);
    while (exp > 0) {
        if (exp & 1) result = result * base % p;
        base = base * base % p;
        exp >>= 1;
    }
    return result;
}

static long long modinv(long long a, long long p) {
    return power_mod(a, p - 2, p);
}

static void poly_copy(Poly *dst, const Poly *src) {
    dst->deg = src->deg;
    memcpy(dst->c, src->c, sizeof(long long) * (src->deg + 1));
}

static void poly_strip(Poly *a, long long p) {
    while (a->deg > 0 && mod(a->c[a->deg], p) == 0) a->deg--;
    if (a->deg == 0 && mod(a->c[0], p) == 0) a->deg = -1; // zero poly
}

static void poly_reduce(Poly *a, long long p) {
    for (int i = 0; i <= a->deg; i++) a->c[i] = mod(a->c[i], p);
    poly_strip(a, p);
}

/* a = a mod m over GF(p) */
static void poly_mod(Poly *a, const Poly *m, long long p) {
    if (m->deg < 0) return;
    long long inv_lc = modinv(m->c[m->deg], p);
    while (a->deg >= m->deg) {
        long long lc = mod(a->c[a->deg], p);
        if (lc != 0) {
            long long c = lc * inv_lc % p;
            int offset = a->deg - m->deg;
            for (int i = 0; i <= m->deg; i++) {
                a->c[offset + i] = mod(a->c[offset + i] - c * m->c[i] % p, p);
            }
        }
        a->deg--;
    }
    poly_strip(a, p);
}

/* r = a * b mod m over GF(p) */
static void poly_mulmod(Poly *r, const Poly *a, const Poly *b, const Poly *m, long long p) {
    Poly tmp;
    tmp.deg = (a->deg < 0 || b->deg < 0) ? -1 : a->deg + b->deg;
    memset(tmp.c, 0, sizeof(long long) * (tmp.deg + 1));
    if (tmp.deg >= 0) {
        for (int i = 0; i <= a->deg; i++) {
            if (a->c[i] == 0) continue;
            for (int j = 0; j <= b->deg; j++) {
                tmp.c[i+j] = mod(tmp.c[i+j] + a->c[i] * b->c[j], p);
            }
        }
    }
    poly_mod(&tmp, m, p);
    poly_copy(r, &tmp);
}

/* r = base^exp mod m over GF(p) */
static void poly_powmod(Poly *r, const Poly *base, long long exp, const Poly *m, long long p) {
    Poly b;
    poly_copy(&b, base);
    poly_mod(&b, m, p);
    r->deg = 0;
    r->c[0] = 1;
    while (exp > 0) {
        if (exp & 1) {
            poly_mulmod(r, r, &b, m, p);
        }
        poly_mulmod(&b, &b, &b, m, p);
        exp >>= 1;
    }
}

/* GCD of a and b over GF(p) */
static void poly_gcd(Poly *g, const Poly *a, const Poly *b, long long p) {
    Poly x, y, tmp;
    poly_copy(&x, a);
    poly_copy(&y, b);
    poly_reduce(&x, p);
    poly_reduce(&y, p);
    while (y.deg >= 0) {
        poly_copy(&tmp, &y);
        poly_mod(&x, &y, p);
        poly_copy(&y, &x);
        poly_copy(&x, &tmp);
    }
    poly_copy(g, &x);
    // Make monic
    if (g->deg > 0) {
        long long inv = modinv(g->c[g->deg], p);
        for (int i = 0; i <= g->deg; i++) g->c[i] = g->c[i] * inv % p;
    }
}

/* Exact division f/g over GF(p). Result in q. */
static void poly_div(Poly *q, const Poly *f, const Poly *g, long long p) {
    Poly rem;
    poly_copy(&rem, f);
    int dq = f->deg - g->deg;
    if (dq < 0) { q->deg = -1; return; }
    q->deg = dq;
    memset(q->c, 0, sizeof(long long) * (dq + 1));
    long long inv_lc = modinv(g->c[g->deg], p);
    for (int i = dq; i >= 0; i--) {
        long long c = mod(rem.c[i + g->deg], p) * inv_lc % p;
        q->c[i] = c;
        for (int j = 0; j <= g->deg; j++) {
            rem.c[i+j] = mod(rem.c[i+j] - c * g->c[j], p);
        }
    }
    poly_strip(q, p);
}

/*
 * Distinct-degree factorization: returns sorted list of irreducible factor degrees.
 * pattern[0..22] filled with degrees, returns count of factors.
 */
static int ddf(long long coeffs[24], long long p, int pattern[23]) {
    Poly f;
    f.deg = 23;
    for (int i = 0; i <= 23; i++) f.c[i] = mod(coeffs[i], p);
    poly_strip(&f, p);
    if (f.deg != 23) return -1; // degree dropped

    // Make monic
    long long inv_lc = modinv(f.c[23], p);
    for (int i = 0; i <= 23; i++) f.c[i] = f.c[i] * inv_lc % p;

    Poly remaining;
    poly_copy(&remaining, &f);

    // xpk starts as x
    Poly xpk;
    xpk.deg = 1;
    xpk.c[0] = 0;
    xpk.c[1] = 1;

    int nfactors = 0;

    for (int k = 1; k <= 23; k++) {
        int deg_r = remaining.deg;
        if (deg_r <= 0) break;

        // xpk = xpk^p mod remaining
        poly_powmod(&xpk, &xpk, p, &remaining, p);

        // temp = xpk - x
        Poly temp;
        poly_copy(&temp, &xpk);
        temp.c[1] = mod(temp.c[1] - 1, p);
        if (temp.deg < 1) temp.deg = 1;
        poly_strip(&temp, p);

        // g = gcd(remaining, temp)
        Poly g;
        if (temp.deg < 0) {
            // temp is zero => gcd = remaining
            poly_copy(&g, &remaining);
        } else {
            poly_gcd(&g, &remaining, &temp, p);
        }

        int deg_g = g.deg;
        if (deg_g > 0) {
            int count = deg_g / k;
            for (int i = 0; i < count; i++) {
                pattern[nfactors++] = k;
            }
            // remaining = remaining / g
            Poly quot;
            poly_div(&quot, &remaining, &g, p);
            poly_copy(&remaining, &quot);
            // Reduce xpk mod new remaining
            if (remaining.deg > 0) {
                poly_mod(&xpk, &remaining, p);
            } else {
                break;
            }
        }
        if (remaining.deg <= 0) break;
    }

    // If remaining has degree > 0, it's one more irreducible
    if (remaining.deg > 0) {
        pattern[nfactors++] = remaining.deg;
    }

    // Sort pattern
    for (int i = 0; i < nfactors - 1; i++)
        for (int j = i + 1; j < nfactors; j++)
            if (pattern[i] > pattern[j]) {
                int t = pattern[i]; pattern[i] = pattern[j]; pattern[j] = t;
            }

    return nfactors;
}

/* Check if pattern matches one of the 12 M23 cycle types */
static int m23_patterns[12][23] = {
    {1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1}, // 1^23
    {1,1,1,1,1,1,1,2,2,2,2,2,2,2,2},                   // 1^7 2^8
    {1,1,1,1,1,3,3,3,3,3,3},                             // 1^5 3^6
    {1,1,1,2,2,4,4,4,4},                                 // 1^3 2^2 4^4
    {1,1,1,5,5,5,5},                                     // 1^3 5^4
    {1,1,7,7,7},                                         // 1^2 7^3
    {1,2,2,3,3,6,6},                                     // 1 2^2 3^2 6^2
    {1,2,4,8,8},                                         // 1 2 4 8^2
    {1,11,11},                                           // 1 11^2
    {2,7,14},                                            // 2 7 14
    {3,5,15},                                            // 3 5 15
    {23},                                                // 23
};
static int m23_lens[12] = {23, 15, 11, 9, 7, 5, 7, 5, 3, 3, 3, 1};

static int is_m23_pattern(int pattern[], int n) {
    for (int i = 0; i < 12; i++) {
        if (m23_lens[i] != n) continue;
        int match = 1;
        for (int j = 0; j < n; j++) {
            if (pattern[j] != m23_patterns[i][j]) { match = 0; break; }
        }
        if (match) return 1;
    }
    return 0;
}

static long long PRIMES[] = {2,3,5,7,11,13,17,19,29,31,37,41,43,47,53,59,61,67,71,73,79,83,89,97};
#define NPRIMES 24

/*
 * Check polynomial against M23.
 * Returns number of primes that passed before first failure (or NPRIMES if all pass).
 */
static int check_m23(long long coeffs[24]) {
    int passed = 0;
    for (int pi = 0; pi < NPRIMES; pi++) {
        long long p = PRIMES[pi];
        if (mod(coeffs[23], p) == 0) continue; // skip bad primes
        int pattern[23];
        int n = ddf(coeffs, p, pattern);
        if (n < 0) continue; // degree dropped
        if (!is_m23_pattern(pattern, n)) return passed;
        passed++;
    }
    return passed;
}

int main(int argc, char *argv[]) {
    long long coeffs[24];
    long long best = 0;
    long long tested = 0;
    long long total_searched = 0;

    fprintf(stderr, "M23 Fast Search Engine (C)\n");
    fprintf(stderr, "Strategy 1: Trinomials x^23 + a*x + b\n");
    fflush(stderr);

    /* Strategy 1: Trinomials x^23 + ax + b, |a|,|b| <= 5000 */
    int MAX_AB = 5000;
    for (int a = -MAX_AB; a <= MAX_AB; a++) {
        for (int b = -MAX_AB; b <= MAX_AB; b++) {
            if (a == 0 && b == 0) continue;
            memset(coeffs, 0, sizeof(coeffs));
            coeffs[0] = b;
            coeffs[1] = a;
            coeffs[23] = 1;

            int passed = check_m23(coeffs);
            tested++;

            if (passed > best) {
                best = passed;
                fprintf(stderr, "BEST=%d: x^23 + %d*x + %d [%lld tested]\n",
                        (int)best, a, b, tested);
                fflush(stderr);
                if (passed >= 20) {
                    printf("CANDIDATE: x^23 + %d*x + %d (passed %d primes)\n", a, b, (int)passed);
                    fflush(stdout);
                }
            }
        }
        if (a % 500 == 0) {
            fprintf(stderr, "  a=%d, tested=%lld, best=%lld\n", a, tested, best);
            fflush(stderr);
        }
    }
    total_searched += tested;
    fprintf(stderr, "Trinomials done: %lld tested, best=%lld\n\n", tested, best);

    /* Strategy 2: x^23 + a*x^k + b, various k */
    fprintf(stderr, "Strategy 2: x^23 + a*x^k + b\n");
    fflush(stderr);
    int K_VALUES[] = {2,3,5,7,11,13,17,19,22};
    tested = 0;
    for (int ki = 0; ki < 9; ki++) {
        int k = K_VALUES[ki];
        for (int a = -2000; a <= 2000; a++) {
            if (a == 0) continue;
            for (int b = -2000; b <= 2000; b++) {
                if (b == 0) continue;
                memset(coeffs, 0, sizeof(coeffs));
                coeffs[0] = b;
                coeffs[k] = a;
                coeffs[23] = 1;

                int passed = check_m23(coeffs);
                tested++;

                if (passed > best) {
                    best = passed;
                    fprintf(stderr, "BEST=%d: x^23 + %d*x^%d + %d [%lld tested]\n",
                            (int)best, a, k, b, tested);
                    fflush(stderr);
                    if (passed >= 20) {
                        printf("CANDIDATE: x^23 + %d*x^%d + %d (passed %d primes)\n",
                               a, k, b, (int)passed);
                        fflush(stdout);
                    }
                }
            }
        }
        fprintf(stderr, "  k=%d done, tested=%lld, best=%lld\n", k, tested, best);
        fflush(stderr);
    }
    total_searched += tested;

    /* Strategy 3: Random sparse with 3-5 terms */
    fprintf(stderr, "\nStrategy 3: Random sparse polynomials\n");
    fflush(stderr);
    srand(666);
    tested = 0;
    for (long long trial = 0; trial < 50000000LL; trial++) {
        memset(coeffs, 0, sizeof(coeffs));
        coeffs[23] = 1;
        int nterms = 2 + rand() % 4;
        for (int t = 0; t < nterms; t++) {
            int k = rand() % 23;
            coeffs[k] = (rand() % 2001) - 1000;
        }
        int allzero = 1;
        for (int i = 0; i < 23; i++) if (coeffs[i]) { allzero = 0; break; }
        if (allzero) continue;

        int passed = check_m23(coeffs);
        tested++;

        if (passed > best) {
            best = passed;
            fprintf(stderr, "BEST=%d: [", (int)best);
            for (int i = 0; i <= 23; i++) if (coeffs[i]) fprintf(stderr, "%d:%lld ", i, coeffs[i]);
            fprintf(stderr, "] trial=%lld\n", trial);
            fflush(stderr);
            if (passed >= 20) {
                printf("CANDIDATE: ");
                for (int i = 23; i >= 0; i--) {
                    if (coeffs[i]) printf("%+lld*x^%d ", coeffs[i], i);
                }
                printf("(passed %d primes)\n", (int)passed);
                fflush(stdout);
            }
        }
        if (trial % 5000000 == 0 && trial > 0) {
            fprintf(stderr, "  %lld trials, best=%lld\n", trial, best);
            fflush(stderr);
        }
    }
    total_searched += tested;

    fprintf(stderr, "\nTotal searched: %lld, overall best: %lld primes\n",
            total_searched, best);
    fprintf(stderr, "If best < 10: no M23 polynomial found (expected - open problem)\n");
    return 0;
}
