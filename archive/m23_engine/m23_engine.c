/* M23 polynomial search engine - compiled via tinycc, called via ctypes */
#include <string.h>

#define MAXDEG 24

typedef long long ll;

static ll mod(ll a, ll p) {
    a %= p;
    return a < 0 ? a + p : a;
}

static ll power_mod(ll base, ll exp, ll p) {
    ll result = 1;
    base = mod(base, p);
    while (exp > 0) {
        if (exp & 1) result = result * base % p;
        base = base * base % p;
        exp >>= 1;
    }
    return result;
}

static ll modinv(ll a, ll p) { return power_mod(a, p - 2, p); }

/* Polynomial over GF(p): degree + coefficients c[0..deg] */
typedef struct { int deg; ll c[50]; } Poly;

static void pstrip(Poly *a, ll p) {
    while (a->deg > 0 && mod(a->c[a->deg], p) == 0) a->deg--;
    if (a->deg == 0 && mod(a->c[0], p) == 0) a->deg = -1;
}

static void pcopy(Poly *d, const Poly *s) {
    d->deg = s->deg;
    if (s->deg >= 0) memcpy(d->c, s->c, sizeof(ll)*(s->deg+1));
}

/* a = a mod m */
static void pmod(Poly *a, const Poly *m, ll p) {
    if (m->deg < 0) return;
    ll inv = modinv(m->c[m->deg], p);
    while (a->deg >= m->deg) {
        ll lc = mod(a->c[a->deg], p);
        if (lc) {
            ll c = lc * inv % p;
            int off = a->deg - m->deg;
            for (int i = 0; i <= m->deg; i++)
                a->c[off+i] = mod(a->c[off+i] - c * m->c[i] % p, p);
        }
        a->deg--;
    }
    pstrip(a, p);
}

/* r = a*b mod m */
static void pmulmod(Poly *r, const Poly *a, const Poly *b, const Poly *m, ll p) {
    Poly t;
    t.deg = (a->deg < 0 || b->deg < 0) ? -1 : a->deg + b->deg;
    memset(t.c, 0, sizeof(ll)*(t.deg+1));
    for (int i = 0; i <= a->deg; i++) {
        if (!a->c[i]) continue;
        for (int j = 0; j <= b->deg; j++)
            t.c[i+j] = (t.c[i+j] + a->c[i] * b->c[j]) % p;
    }
    pmod(&t, m, p);
    pcopy(r, &t);
}

/* r = base^exp mod m */
static void ppowmod(Poly *r, const Poly *base, ll exp, const Poly *m, ll p) {
    Poly b; pcopy(&b, base); pmod(&b, m, p);
    r->deg = 0; r->c[0] = 1;
    while (exp > 0) {
        if (exp & 1) pmulmod(r, r, &b, m, p);
        pmulmod(&b, &b, &b, m, p);
        exp >>= 1;
    }
}

/* GCD */
static void pgcd(Poly *g, const Poly *a0, const Poly *b0, ll p) {
    Poly x, y;
    pcopy(&x, a0); pstrip(&x, p);
    pcopy(&y, b0); pstrip(&y, p);
    while (y.deg >= 0) {
        Poly t; pcopy(&t, &y);
        pmod(&x, &y, p);
        pcopy(&y, &x);
        pcopy(&x, &t);
    }
    pcopy(g, &x);
    if (g->deg > 0) {
        ll inv = modinv(g->c[g->deg], p);
        for (int i = 0; i <= g->deg; i++) g->c[i] = g->c[i] * inv % p;
    }
}

/* f / g exact */
static void pdiv(Poly *q, const Poly *f, const Poly *g, ll p) {
    Poly rem; pcopy(&rem, f);
    int dq = f->deg - g->deg;
    if (dq < 0) { q->deg = -1; return; }
    q->deg = dq;
    memset(q->c, 0, sizeof(ll)*(dq+1));
    ll inv = modinv(g->c[g->deg], p);
    for (int i = dq; i >= 0; i--) {
        ll c = mod(rem.c[i+g->deg], p) * inv % p;
        q->c[i] = c;
        for (int j = 0; j <= g->deg; j++)
            rem.c[i+j] = mod(rem.c[i+j] - c * g->c[j], p);
    }
    pstrip(q, p);
}

/* DDF: returns number of factors, fills pattern[] with sorted degrees */
static int ddf(ll coeffs[24], ll p, int pattern[23]) {
    Poly f;
    f.deg = 23;
    for (int i = 0; i <= 23; i++) f.c[i] = mod(coeffs[i], p);
    pstrip(&f, p);
    if (f.deg != 23) return -1;
    ll inv = modinv(f.c[23], p);
    for (int i = 0; i <= 23; i++) f.c[i] = f.c[i] * inv % p;

    Poly rem; pcopy(&rem, &f);
    Poly xpk; xpk.deg = 1; xpk.c[0] = 0; xpk.c[1] = 1;
    int nf = 0;

    for (int k = 1; k <= 23 && rem.deg > 0; k++) {
        ppowmod(&xpk, &xpk, p, &rem, p);
        Poly tmp; pcopy(&tmp, &xpk);
        if (tmp.deg < 1) { tmp.deg = 1; tmp.c[1] = 0; }
        tmp.c[1] = mod(tmp.c[1] - 1, p);
        pstrip(&tmp, p);

        Poly g;
        if (tmp.deg < 0) pcopy(&g, &rem);
        else pgcd(&g, &rem, &tmp, p);

        if (g.deg > 0) {
            int cnt = g.deg / k;
            for (int i = 0; i < cnt; i++) pattern[nf++] = k;
            Poly q; pdiv(&q, &rem, &g, p);
            pcopy(&rem, &q);
            if (rem.deg > 0) pmod(&xpk, &rem, p);
        }
    }
    if (rem.deg > 0) pattern[nf++] = rem.deg;

    /* Sort */
    for (int i = 0; i < nf-1; i++)
        for (int j = i+1; j < nf; j++)
            if (pattern[i] > pattern[j]) { int t=pattern[i]; pattern[i]=pattern[j]; pattern[j]=t; }
    return nf;
}

/* M23 patterns */
static int m23p[12][23] = {
    {1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1},
    {1,1,1,1,1,1,1,2,2,2,2,2,2,2,2},
    {1,1,1,1,1,3,3,3,3,3,3},
    {1,1,1,2,2,4,4,4,4},
    {1,1,1,5,5,5,5},
    {1,1,7,7,7},
    {1,2,2,3,3,6,6},
    {1,2,4,8,8},
    {1,11,11},
    {2,7,14},
    {3,5,15},
    {23}
};
static int m23l[12] = {23,15,11,9,7,5,7,5,3,3,3,1};

static int is_m23(int pat[], int n) {
    for (int i = 0; i < 12; i++) {
        if (m23l[i] != n) continue;
        int ok = 1;
        for (int j = 0; j < n; j++) if (pat[j] != m23p[i][j]) { ok=0; break; }
        if (ok) return 1;
    }
    return 0;
}

static ll PRIMES[] = {2,3,5,7,11,13,17,19,29,31,37,41,43,47,53,59,61,67,71,73,79,83,89,97};

/* Check poly: returns number of primes passed */
__declspec(dllexport) int check_m23(ll coeffs[24], int nprimes) {
    int passed = 0;
    for (int pi = 0; pi < nprimes && pi < 24; pi++) {
        ll p = PRIMES[pi];
        if (mod(coeffs[23], p) == 0) continue;
        int pat[23]; int n = ddf(coeffs, p, pat);
        if (n < 0) continue;
        if (!is_m23(pat, n)) return passed;
        passed++;
    }
    return passed;
}

/* Batch search: trinomials x^23 + ax + b
   Returns best number of primes, fills best_a and best_b */
__declspec(dllexport) int search_trinomials(int a_min, int a_max, int b_min, int b_max,
                                             int nprimes, int *best_a, int *best_b) {
    int best = 0;
    ll coeffs[24];
    for (int a = a_min; a <= a_max; a++) {
        for (int b = b_min; b <= b_max; b++) {
            if (a == 0 && b == 0) continue;
            memset(coeffs, 0, sizeof(coeffs));
            coeffs[0] = b; coeffs[1] = a; coeffs[23] = 1;
            int p = check_m23(coeffs, nprimes);
            if (p > best) {
                best = p;
                *best_a = a;
                *best_b = b;
            }
        }
    }
    return best;
}

/* Search x^23 + a*x^k + b */
__declspec(dllexport) int search_binomial_k(int k, int a_min, int a_max, int b_min, int b_max,
                                             int nprimes, int *best_a, int *best_b) {
    int best = 0;
    ll coeffs[24];
    for (int a = a_min; a <= a_max; a++) {
        if (a == 0) continue;
        for (int b = b_min; b <= b_max; b++) {
            if (b == 0) continue;
            memset(coeffs, 0, sizeof(coeffs));
            coeffs[0] = b; coeffs[k] = a; coeffs[23] = 1;
            int p = check_m23(coeffs, nprimes);
            if (p > best) {
                best = p;
                *best_a = a;
                *best_b = b;
            }
        }
    }
    return best;
}
