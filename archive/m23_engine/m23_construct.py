"""
Construct M23 from the binary Golay code using backtracking automorphism search.
"""
import random
import json
from itertools import combinations
random.seed(666)

# --- Step 1: Build Golay code and Steiner system (same as before) ---
GENPOLY = [1,0,1,0,1,1,1,0,0,0,1,1]

def poly_mul_gf2(a, b):
    if not a or not b:
        return []
    result = [0] * (len(a) + len(b) - 1)
    for i, ai in enumerate(a):
        if ai:
            for j, bj in enumerate(b):
                if bj:
                    result[i+j] ^= 1
    return result

print("Building Golay code...")
codewords_23 = set()
for msg_int in range(2**12):
    msg = [(msg_int >> i) & 1 for i in range(12)]
    cw = poly_mul_gf2(msg, GENPOLY)
    while len(cw) < 23:
        cw.append(0)
    codewords_23.add(tuple(cw))

codewords_24 = set()
for cw in codewords_23:
    parity = sum(cw) % 2
    codewords_24.add(cw + (parity,))

octad_sets = [frozenset(i for i in range(24) if c[i]) for c in codewords_24 if sum(c) == 8]

blocks = []
for os in octad_sets:
    if 23 in os:
        blocks.append(frozenset(i for i in os if i != 23))
block_set = frozenset(blocks)

print(f"S(4,7,23): {len(blocks)} blocks of size 7 on {{0..22}}")

# Build point-to-blocks index
pt_to_blocks = {i: [] for i in range(23)}
for idx, b in enumerate(blocks):
    for p in b:
        pt_to_blocks[p].append(idx)

# For quick lookup: given a set of >=4 points, find the unique block containing them
# We'll index blocks by sorted 4-subsets
block_by_4subset = {}
for idx, b in enumerate(blocks):
    for quad in combinations(sorted(b), 4):
        block_by_4subset[quad] = idx

def find_block_containing(point_set):
    """Find block containing these 4+ points. Returns block index or None."""
    pts = sorted(point_set)
    if len(pts) >= 4:
        quad = tuple(pts[:4])
        idx = block_by_4subset.get(quad)
        if idx is not None and point_set <= blocks[idx]:
            return idx
    return None

# --- Step 2: Backtracking automorphism search ---
def find_automorphism(initial_map):
    """Find automorphism of S(4,7,23) extending initial_map, using constraint propagation + backtracking."""
    perm = dict(initial_map)
    used = set(perm.values())

    def propagate():
        changed = True
        while changed:
            changed = False
            for bi, block in enumerate(blocks):
                mapped = [p for p in block if p in perm]
                if len(mapped) < 4:
                    continue
                unmapped = [p for p in block if p not in perm]
                image_set = frozenset(perm[p] for p in mapped)
                # Find target block
                target_idx = None
                for candidate_idx in pt_to_blocks[perm[mapped[0]]]:
                    if image_set <= blocks[candidate_idx]:
                        target_idx = candidate_idx
                        break
                if target_idx is None:
                    return False
                target = blocks[target_idx]
                target_remaining = sorted(p for p in target if p not in used)
                if len(unmapped) != len(target_remaining):
                    return False
                if len(unmapped) == 1:
                    perm[unmapped[0]] = target_remaining[0]
                    used.add(target_remaining[0])
                    changed = True
                elif len(unmapped) == 2:
                    # Try to resolve using another block
                    pass
                elif len(unmapped) == 0:
                    if frozenset(perm[p] for p in block) not in block_set:
                        return False
        return True

    def solve():
        if not propagate():
            return None
        if len(perm) == 23:
            # Verify
            for b in blocks:
                if frozenset(perm[p] for p in b) not in block_set:
                    return None
            return tuple(perm[i] for i in range(23))

        # Branch on the unmapped point that's most constrained
        unmapped = [i for i in range(23) if i not in perm]
        # Pick point involved in most blocks with many mapped points
        best_p = unmapped[0]
        available = sorted(i for i in range(23) if i not in used)

        for target in available:
            saved_perm = dict(perm)
            saved_used = set(used)
            perm[best_p] = target
            used.add(target)
            result = solve()
            if result is not None:
                return result
            perm.clear()
            perm.update(saved_perm)
            used.clear()
            used.update(saved_used)
        return None

    return solve()

# --- Step 3: Find generators ---
def cycle_type(perm):
    n = len(perm)
    visited = [False]*n
    cycles = []
    for i in range(n):
        if not visited[i]:
            length = 0
            j = i
            while not visited[j]:
                visited[j] = True
                j = perm[j]
                length += 1
            cycles.append(length)
    return tuple(sorted(cycles))

def compose(p, q):
    return tuple(p[q[i]] for i in range(len(p)))

def inverse(p):
    inv = [0]*len(p)
    for i in range(len(p)):
        inv[p[i]] = i
    return tuple(inv)

def power(p, k):
    n = len(p)
    result = tuple(range(n))
    base = p
    while k > 0:
        if k % 2: result = compose(result, base)
        base = compose(base, base)
        k //= 2
    return result

# Generator 1: cyclic shift
gen1 = tuple((i+1) % 23 for i in range(23))
# Generator 2: x -> 2x mod 23
gen2 = tuple((2*i) % 23 for i in range(23))

print(f"gen1 (shift): cycle type {cycle_type(gen1)}")
print(f"gen2 (2x):   cycle type {cycle_type(gen2)}")

# Find a non-affine automorphism by trying to map 0->0, 1->1, 2->2, 3->some other value
print("\nSearching for non-affine automorphism via backtracking...")
# The block containing {0,1,2,3}:
b0123 = None
for b in blocks:
    if {0,1,2,3} <= b:
        b0123 = b
        break
print(f"Block containing {{0,1,2,3}}: {sorted(b0123)}")

# M23 is 4-transitive. Map (0,1,2,3) -> (0,1,2,x) for each x not in {0,1,2}
# This gives automorphisms in the stabilizer of {0,1,2}
found_gens = [gen1, gen2]
found_types = set()
for _ in range(100000):
    p = gen1
    for __ in range(30):
        g = random.choice(found_gens)
        if random.random() < 0.5: g = inverse(g)
        p = compose(p, g)
    found_types.add(cycle_type(p))

print(f"Current cycle types: {len(found_types)}")

# Try mapping (0,1,2,3) -> (0,1,2,x) for each x in 3..22
for x in range(3, 23):
    # Check if {0,1,2,x} is in some block
    target_block = None
    for b in blocks:
        if {0,1,2,x} <= b:
            target_block = b
            break
    if target_block is None:
        continue

    print(f"  Trying (0,1,2,3) -> (0,1,2,{x})...")
    result = find_automorphism({0:0, 1:1, 2:2, 3:x})
    if result is not None:
        ct = cycle_type(result)
        print(f"    Found automorphism! cycle type = {ct}")
        found_gens.append(result)
        if ct not in found_types:
            print(f"    NEW cycle type!")
        break

# Now try more: map (0,1,2,3) -> (a,b,c,d) for various targets
print("\nTrying more initial maps...")
for a, b_val, c, d in [(0,1,3,2), (0,2,1,3), (1,0,2,3), (0,1,4,3), (0,3,1,2)]:
    target_block = None
    for b in blocks:
        if {a, b_val, c, d} <= b:
            target_block = b
            break
    if target_block is None:
        continue
    result = find_automorphism({0:a, 1:b_val, 2:c, 3:d})
    if result is not None:
        ct = cycle_type(result)
        is_new = ct not in found_types
        print(f"  (0,1,2,3)->({a},{b_val},{c},{d}): {ct} {'NEW!' if is_new else ''}")
        found_gens.append(result)

# Resample cycle types with all generators
print("\nResampling with all generators...")
found_types = set()
for _ in range(500000):
    p = tuple(range(23))
    for __ in range(50):
        g = random.choice(found_gens)
        if random.random() < 0.5: g = inverse(g)
        p = compose(p, g)
    found_types.add(cycle_type(p))

print(f"Total cycle types found: {len(found_types)}")
for ct in sorted(found_types):
    print(f"  {ct}")

# Convert cycle types to partitions (for polynomial factorization checking)
allowed_partitions = set(found_types)

results = {
    "num_cycle_types": len(found_types),
    "cycle_types": [list(ct) for ct in sorted(found_types)],
    "generators": [list(g) for g in found_gens],
    "allowed_partitions": [list(ct) for ct in sorted(allowed_partitions)]
}
with open("m23_data.json", "w") as f:
    json.dump(results, f, indent=2)

print(f"\nSaved to m23_data.json")
print(f"Expected: 12 cycle types for M23 (order 10,200,960)")
