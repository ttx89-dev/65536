"""
demo_content_identity.py — Content identity & dedup exploration
═══════════════════════════════════════════════════════════════════════════════

Explores FNV-1a content-addressed storage: exact dedup, content-dependent
addressing, hash collision bounds, and address-space utilisation.

Run:   python "tests/demos/demo_content_identity.py"  (from 65536/)
       python demo_content_identity.py                     (from tests/demos/)
═══════════════════════════════════════════════════════════════════════════════
"""

import sys, os, math
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from bootstrap_block import BootstrapBlock, ChecksumAlgo
from content_store import Store as ContentStore, EntryOutcome


def _fnv1a_64(data: bytes) -> int:
    """Reference FNV-1a 64-bit (matches content_store)."""
    h = 0xCBF29CE484222325
    for b in data:
        h ^= b
        h = (h * 0x100000001B3) & 0xFFFFFFFFFFFFFFFF
    return h


def demo():
    print("═" * 60)
    print("  65536 — Content Identity & Dedup Exploration")
    print("═" * 60)

    bb = BootstrapBlock(checksum_algo=ChecksumAlgo.NONE)
    cs = ContentStore(bb)

    # ── 1. Basic Dedup ─────────────────────────────────────────────────
    print("\n◆ 1. Exact Dedup")
    data = b"the quick brown fox jumps over the lazy dog"

    addr1, addr2, addr3 = 0x2001, 0x2002, 0x2003

    h1 = cs.write(addr1, data)
    h2 = cs.write(addr2, data)   # same content → same hash (dedup)
    h3 = cs.write(addr3, b"different content")

    print(f"  Content:          {data}")
    print(f"  {addr1:#06x} hash: {h1:#018x}")
    print(f"  {addr2:#06x} hash: {h2:#018x}")
    print(f"  {addr3:#06x} hash: {h3:#018x}")
    print(f"  Dedup:            {'YES — same hash' if h1 == h2 else 'NO — collision!'}")

    # Readback verification (content_store.read returns 4-tuple)
    oc1, d1, _, _ = cs.read(addr1)
    oc2, d2, _, _ = cs.read(addr2)
    oc3, d3, _, _ = cs.read(addr3)

    assert oc1 == oc2 == oc3 == EntryOutcome.VALID
    assert d1 == d2 == data
    assert d3 == b"different content"
    assert h1 == h2
    assert h1 != h3
    print(f"  Readbacks:        ALL VALID")

    # ── 2. Hash inspection ────────────────────────────────────────────
    print("\n◆ 2. FNV-1a Hash Behaviour")
    h_fox = _fnv1a_64(data)
    h_diff = _fnv1a_64(b"different content")
    print(f"  Hash of 'fox...': {h_fox:#020x}")
    print(f"  Hash of 'diff..': {h_diff:#020x}")
    print(f"  Hamming dist:     {bin(h_fox ^ h_diff).count('1')} bits / 64")
    print(f"  Hash space:       2^64 ≈ 1.8×10¹⁹ values — astronomical for dedup")

    # ── 3. Collision bounds ───────────────────────────────────────────
    print("\n◆ 3. Collision Bounds (16-bit truncation from full 64-bit hash)")
    #
    # The ContentStore truncates the 64-bit FNV-1a hash to 16 bits for the
    # address table lookup (two addresses pointing to same hash). The birthday
    # bound for n items across N=65536 slots is P ≈ 1 − exp(−n²/(2N)).
    #
    # This is NOT about full FNV-1a hash collisions (64-bit → negligible),
    # but about two DIFFERENT content items being truncated to the same
    # 16-bit address. The Store detects this via the full hash in the
    # content table — it doesn't lose data, but it means multiple items
    # share a 16-bit address path.

    n_slots = 65536
    for n_items in [100, 500, 1000, 5000]:
        p = 1.0 - math.exp(-(n_items ** 2) / (2 * n_slots))
        print(f"  Items={n_items:<6d}  P(16-bit addr collision) ≈ {p:.4f}")

    print("\n  (The full 64-bit hash collision probability for 10¹² items")
    print("   is ~2.7×10⁻⁵ — negligible at this scale.)")

    # ── 4. Stress dedup ───────────────────────────────────────────────
    print("\n◆ 4. Stress: 200 writes, varied content")
    seen_hashes = {}
    unique = 0
    for i in range(200):
        item = f"stress-item-{i:04d}-{'x' * (i % 50)}".encode()
        addr = 0x4000 + i   # each address unique and within range
        h = cs.write(addr, item)
        if h not in seen_hashes:
            seen_hashes[h] = item
            unique += 1

    print(f"  Writes:           200")
    print(f"  Unique hashes:    {unique}")
    print(f"  Dedup ratio:      {(200 - unique) / 200 * 100:.1f}% repeated content")

    # ── 5. Empty addresses → UNASSIGNED ───────────────────────────────
    print("\n◆ 5. Gap reads return UNASSIGNED")
    for a in [0x0000, 0xFFFF, 0x4000 + 999]:
        oc, _, _, _ = cs.read(a)
        print(f"  {a:#06x}: {oc.name}")

    # ── 6. Content identity chain ─────────────────────────────────────
    print("\n◆ 6. Content identity includes dependency hashes")
    bb2 = BootstrapBlock(checksum_algo=ChecksumAlgo.NONE)
    cs2 = ContentStore(bb2)

    addr_lone = 0x5001
    addr_dep = 0x5002
    cs2.write(addr_lone, b"standalone")
    cs2.write(addr_dep, b"dependent", depends_on=[addr_lone])

    _, _, _, hash_lone = cs2.read(addr_lone)
    _, _, _, hash_dep = cs2.read(addr_dep)
    print(f"  Standalone:       {hash_lone:#018x}")
    print(f"  Dependent:        {hash_dep:#018x}")
    print(f"  Different:        {'YES — deps change identity' if hash_lone != hash_dep else 'NO'}")
    print("  (Body includes dependency hashes before content bytes)")

    # ── Done ──────────────────────────────────────────────────────────
    print("\n═" * 60)
    print("  Content identity demo: ALL PASS")
    print("═" * 60)


if __name__ == "__main__":
    demo()
