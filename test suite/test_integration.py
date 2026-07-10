"""
test_integration.py — cross-module integration tests, 65535-point framework
═══════════════════════════════════════════════════════════════════════════════

Tests the full bootstrap → payload → content pipeline, consistent address
decomposition, cross-store invariants, and end-to-end correctness.

All three modules share a common foundation: BootstrapBlock defines the
address space, payload_codec.Store owns descriptor+heap storage, and
content_store.Store replaces the descriptor table with content-addressed
indirection. This file tests their interactions.

Run with: python -m pytest test_integration.py
═══════════════════════════════════════════════════════════════════════════════
"""

import sys, os
sys.path.insert(0, os.path.dirname(__file__))

import pytest
from bootstrap_block import BootstrapBlock, BootstrapError, ChecksumAlgo, ReadOutcome
from payload_codec import Store as PayloadStore, EntryOutcome, PayloadError
from content_store import Store as ContentStore, fnv1a_64


# ═══════════════════════════════════════════════════════════════════════════
# 1. Shared Bootstrap Block
# ═══════════════════════════════════════════════════════════════════════════

def test_shared_default_bootstrap():
    """Both stores must accept the same default BootstrapBlock."""
    bb = BootstrapBlock()
    # Both stores init from it
    ps = PayloadStore(bb)
    cs = ContentStore(bb)
    assert ps.bootstrap is bb, "payload store bootstrap ref"
    assert cs.bootstrap is bb, "content store bootstrap ref"
    assert ps.bootstrap is cs.bootstrap, "same bootstrap object"


def test_shared_custom_bootstrap():
    """Both stores must work with non-default BootstrapBlock."""
    bb = BootstrapBlock(
        fw_ver_major=2, fw_ver_minor=3,
        checksum_algo=ChecksumAlgo.CRC16,
        category_count=4, tier_count=2,
        headroom_ratio=25, tombstone_sentinel=0xAA,
    )
    ps = PayloadStore(bb)
    cs = ContentStore(bb)
    # Both must decompose addresses the same way
    examples = [(0x0000, (0, 0, 0)), (0x0001, (0, 0, 1)),
                (0x0100, (0, 1, 0)), (0x1000, (1, 0, 0)),
                (0x1234, (1, 2, 0x34)), (0xFFFF, (0xF, 0xF, 0xFF))]
    for addr, expected in examples:
        r1 = ps.bootstrap.decompose_address(addr)
        r2 = cs.bootstrap.decompose_address(addr)
        assert r1 == expected, f"payload decompose 0x{addr:04X}: expected {expected}, got {r1}"
        assert r2 == expected, f"content decompose 0x{addr:04X}: expected {expected}, got {r2}"


# ═══════════════════════════════════════════════════════════════════════════
# 2. Consistent Address Composition & Decomposition
# ═══════════════════════════════════════════════════════════════════════════

def test_compose_decompose_consistency():
    """compose then decompose yields original components for both stores."""
    bb = BootstrapBlock()
    ps = PayloadStore(bb)
    cs = ContentStore(bb)
    test_cases = [
        (1, 1, 1, 0x1101),
        (2, 3, 0xFF, 0x23FF),
        (0xF, 0xF, 0xFF, 0xFFFF),
        (0, 1, 0, 0x0100),
        (1, 0, 0, 0x1000),
        (5, 5, 0x55, 0x5555),
    ]
    for tier, cat, idx, expected_addr in test_cases:
        pa = ps.compose(tier, cat, idx)
        ca = cs.compose(tier, cat, idx)
        assert pa == expected_addr, f"payload compose({tier},{cat},{idx}) = 0x{pa:04X}, expected 0x{expected_addr:04X}"
        assert ca == expected_addr, f"content compose({tier},{cat},{idx}) = 0x{ca:04X}, expected 0x{expected_addr:04X}"
        # Decompose back
        t, c, i = bb.decompose_address(pa)
        assert (t, c, i) == (tier, cat, idx), f"decompose 0x{pa:04X}: expected ({tier},{cat},{idx}), got ({t},{c},{i})"


def test_compose_out_of_range_both_stores():
    """Both stores must reject the same out-of-range addresses."""
    bb = BootstrapBlock()
    ps = PayloadStore(bb)
    cs = ContentStore(bb)
    bad_cases = [(99, 0, 1), (0, 99, 1), (0, 0, 256)]
    for tier, cat, idx in bad_cases:
        with pytest.raises(PayloadError):
            ps.compose(tier, cat, idx)
        with pytest.raises(PayloadError):
            cs.compose(tier, cat, idx)


# ═══════════════════════════════════════════════════════════════════════════
# 3. Cross-Store Read — Unwritten
# ═══════════════════════════════════════════════════════════════════════════

def test_unwritten_address_both_stores():
    """Both stores must agree that an unwritten address is UNASSIGNED."""
    bb = BootstrapBlock()
    ps = PayloadStore(bb)
    cs = ContentStore(bb)
    addr = ps.compose(1, 1, 0x55)
    p_outcome, p_data, p_deps = ps.read(addr)
    c_outcome, c_data, c_deps, c_hash = cs.read(addr)
    assert p_outcome == EntryOutcome.UNASSIGNED, f"payload unassigned: expected UNASSIGNED, got {p_outcome}"
    assert c_outcome == EntryOutcome.UNASSIGNED, f"content unassigned: expected UNASSIGNED, got {c_outcome}"
    assert p_data is None, f"payload data None: expected None, got {p_data!r}"
    assert c_data is None, f"content data None: expected None, got {c_data!r}"


# ═══════════════════════════════════════════════════════════════════════════
# 4. Reserved range rejection
# ═══════════════════════════════════════════════════════════════════════════

def test_reserved_range_both_stores():
    """Both stores must reject writes to tier=0,category=0."""
    bb = BootstrapBlock()
    ps = PayloadStore(bb)
    cs = ContentStore(bb)
    bad_addr = ps.compose(0, 0, 1)  # 0x0001
    with pytest.raises(PayloadError):
        ps.write(bad_addr, b"x")
    with pytest.raises(PayloadError):
        cs.write(bad_addr, b"x")


# ═══════════════════════════════════════════════════════════════════════════
# 5. Delete unassigned — both stores
# ═══════════════════════════════════════════════════════════════════════════

def test_delete_unassigned_both_stores():
    """Both stores must reject deleting an UNASSIGNED address."""
    bb = BootstrapBlock()
    ps = PayloadStore(bb)
    cs = ContentStore(bb)
    addr = ps.compose(1, 1, 0x77)
    with pytest.raises(PayloadError):
        ps.delete(addr)
    with pytest.raises(PayloadError):
        cs.delete(addr)


# ═══════════════════════════════════════════════════════════════════════════
# 6. Full Pipeline: Write → Read → Delete → Verify
# ═══════════════════════════════════════════════════════════════════════════

def test_full_pipeline_payload():
    """End-to-end payload Store cycle: write, read, delete, verify."""
    bb = BootstrapBlock()
    store = PayloadStore(bb)
    addr = store.compose(1, 2, 0x44)
    content = b"integration test payload"
    # Write
    store.write(addr, content)
    # Read
    o1, d1, deps1 = store.read(addr)
    assert o1 == EntryOutcome.VALID, f"write valid: expected VALID, got {o1}"
    assert d1 == content, f"content match: expected {content!r}, got {d1!r}"
    assert deps1 == [], f"no deps: expected [], got {deps1}"
    # Delete
    store.delete(addr)
    o2, d2, _ = store.read(addr)
    assert o2 == EntryOutcome.DELETED, f"post-delete: expected DELETED, got {o2}"
    # Reuse: delete + write should work
    store.write(addr, b"reused")
    o3, d3, _ = store.read(addr)
    assert o3 == EntryOutcome.VALID, f"reuse valid: expected VALID, got {o3}"
    assert d3 == b"reused", f"reuse content: expected b'reused', got {d3!r}"


def test_full_pipeline_content():
    """End-to-end content Store cycle: write, read, delete, verify."""
    bb = BootstrapBlock()
    store = ContentStore(bb)
    addr = store.compose(1, 2, 0x44)
    content = b"integration content store"
    # Write
    h = store.write(addr, content)
    # Read
    o1, d1, deps1, h1 = store.read(addr)
    assert o1 == EntryOutcome.VALID, f"write valid: expected VALID, got {o1}"
    assert d1 == content, f"content match: expected {content!r}, got {d1!r}"
    assert h1 == h, f"hash match: expected 0x{h:016x}, got 0x{h1:016x}"
    # Delete
    store.delete(addr)
    o2, d2, _, _ = store.read(addr)
    assert o2 == EntryOutcome.DELETED, f"post-delete: expected DELETED, got {o2}"
    # Note: content store is first-write-only, can't reuse


# ═══════════════════════════════════════════════════════════════════════════
# 7. Dependency chain across same bootstrap
# ═══════════════════════════════════════════════════════════════════════════

def test_dependency_chain_payload():
    """Chain of dependencies in payload Store; topological integrity."""
    bb = BootstrapBlock()
    store = PayloadStore(bb)
    # root → mid → leaf
    root = store.compose(1, 1, 0x10)
    mid = store.compose(1, 1, 0x11)
    leaf = store.compose(1, 1, 0x12)
    store.write(root, b"root")
    store.write(mid, b"mid", depends_on=[root])
    store.write(leaf, b"leaf", depends_on=[mid])
    # Verify all readable with correct deps
    o1, _, d1 = store.read(root)
    assert o1 == EntryOutcome.VALID, f"root valid: expected VALID, got {o1}"
    assert d1 == [], f"root deps empty: expected [], got {d1}"
    o2, _, d2 = store.read(mid)
    assert o2 == EntryOutcome.VALID, f"mid valid: expected VALID, got {o2}"
    assert d2 == [root], f"mid deps = [root]: expected {[root]}, got {d2}"
    o3, d3, _ = store.read(leaf)
    assert o3 == EntryOutcome.VALID, f"leaf valid: expected VALID, got {o3}"
    assert d3 == b"leaf", f"leaf content: expected b'leaf', got {d3!r}"
    # Deleting mid should not affect leaf readability
    store.delete(mid)
    o4, _, _ = store.read(mid)
    assert o4 == EntryOutcome.DELETED, f"mid deleted: expected DELETED, got {o4}"
    # leaf still readable (payload store doesn't cascade)
    o5, _, _ = store.read(leaf)
    assert o5 == EntryOutcome.VALID, f"leaf still valid after mid deleted: expected VALID, got {o5}"


def test_dependency_chain_content():
    """Chain of dependencies in content Store; hash-based integrity."""
    bb = BootstrapBlock()
    store = ContentStore(bb)
    root = store.compose(1, 1, 0x10)
    mid = store.compose(1, 1, 0x11)
    leaf = store.compose(1, 1, 0x12)
    h_root = store.write(root, b"root")
    h_mid = store.write(mid, b"mid", depends_on=[root])
    h_leaf = store.write(leaf, b"leaf", depends_on=[mid])
    # Verify hashes chain
    _, _, d_root, _ = store.read(root)
    _, _, d_mid, _ = store.read(mid)
    _, _, d_leaf, _ = store.read(leaf)
    assert d_root == [], f"root dep hashes empty: expected [], got {d_root}"
    assert d_mid == [h_root], f"mid dep hashes = [h_root]: expected {[h_root]}, got {d_mid}"
    assert d_leaf == [h_mid], f"leaf dep hashes = [h_mid]: expected {[h_mid]}, got {d_leaf}"
    # Deleting mid, leaf still readable
    store.delete(mid)
    o1, _, _, _ = store.read(mid)
    assert o1 == EntryOutcome.DELETED, f"mid deleted: expected DELETED, got {o1}"
    o2, _, _, _ = store.read(leaf)
    assert o2 == EntryOutcome.VALID, f"leaf still valid: expected VALID, got {o2}"


# ═══════════════════════════════════════════════════════════════════════════
# 8. write_ordered in payload Store (batch with deps)
# ═══════════════════════════════════════════════════════════════════════════

def test_write_ordered_multi_tier():
    """write_ordered across multiple tiers must respect topological order."""
    bb = BootstrapBlock()
    store = PayloadStore(bb)
    # Addresses across different tiers
    a = store.compose(1, 1, 0x20)  # tier 1
    b = store.compose(2, 1, 0x21)  # tier 2
    c = store.compose(3, 1, 0x22)  # tier 3
    # a → b → c dependency chain, submitted in reverse
    order = store.write_ordered([
        (c, b"c", [b]),
        (b, b"b", [a]),
        (a, b"a", []),
    ])
    assert order.index(a) == 0, f"a first in {[hex(x) for x in order]}"
    assert order.index(b) > order.index(a), f"b after a in {[hex(x) for x in order]}"
    assert order.index(c) > order.index(b), f"c after b in {[hex(x) for x in order]}"
    # All valid
    for addr, expected in [(a, b"a"), (b, b"b"), (c, b"c")]:
        o, d, _ = store.read(addr)
        assert o == EntryOutcome.VALID, f"{hex(addr)} valid: expected VALID, got {o}"
        assert d == expected, f"{hex(addr)} content: expected {expected!r}, got {d!r}"


# ═══════════════════════════════════════════════════════════════════════════
# 9. Corruption detection — both stores
# ═══════════════════════════════════════════════════════════════════════════

def test_corruption_both_stores():
    """Both stores must detect heap corruption on read."""
    bb = BootstrapBlock()
    ps = PayloadStore(bb)
    cs = ContentStore(bb)

    p_addr = ps.compose(1, 1, 0xE0)
    ps.write(p_addr, b"payload corrupt target")
    # Flip a byte in the payload heap
    d = ps._get_descriptor(p_addr)
    ps.heap[d.offset] ^= 0xFF
    p_outcome, _, _ = ps.read(p_addr)
    assert p_outcome == EntryOutcome.CORRUPT, f"payload corrupt: expected CORRUPT, got {p_outcome}"

    c_addr = cs.compose(1, 1, 0xE1)
    cs.write(c_addr, b"content corrupt target")
    if cs.heap:
        cs.heap[0] ^= 0xFF
        c_outcome, _, _, _ = cs.read(c_addr)
        assert c_outcome == EntryOutcome.CORRUPT, f"content corrupt: expected CORRUPT, got {c_outcome}"


# ═══════════════════════════════════════════════════════════════════════════
# 10. Cross-store content hash parity
# ═══════════════════════════════════════════════════════════════════════════

def test_content_hash_stability():
    """Content hashes in content_store must be stable FNV1a-64 of the wire format body.

    body = [dep_count(1)] + [dep_hashes(8 each)] + [content]
    """
    bb = BootstrapBlock()
    store = ContentStore(bb)
    addr = store.compose(1, 1, 0xF0)
    content = b"hash verification"
    h = store.write(addr, content)
    # body: dep_count=0 → b"\x00" + content
    expected_body = b"\x00" + content
    expected_hash = fnv1a_64(expected_body)
    assert h == expected_hash, f"hash match: got 0x{h:016x}, expected 0x{expected_hash:016x}"


# ═══════════════════════════════════════════════════════════════════════════
# 11. Deterministic checksums across stores
# ═══════════════════════════════════════════════════════════════════════════

def test_checksum_determinism():
    """Same input to both stores' checksum logic must give same result.

    Both stores use the same ChecksumAlgo and compute_checksum via payload_codec.
    """
    from payload_codec import compute_checksum, ChecksumAlgo
    test_data = [b"", b"x", b"hello", bytes(range(256))]
    for data in test_data:
        for algo in [ChecksumAlgo.NONE, ChecksumAlgo.SUM8, ChecksumAlgo.CRC16]:
            c = compute_checksum(data, algo)
            assert isinstance(c, int), f"checksum is int: {type(c)}"
            assert 0 <= c <= 0xFFFF, f"checksum in range: {c}"


# ═══════════════════════════════════════════════════════════════════════════
# 12. Large payload stress test
# ═══════════════════════════════════════════════════════════════════════════

def test_large_payload_stress():
    """Write 100 entries to payload Store, verify all."""
    bb = BootstrapBlock()
    store = PayloadStore(bb)
    entries = {}
    for i in range(100):
        addr = store.compose(1, 1, i)
        content = bytes([i % 256] * (100 + i * 10))
        store.write(addr, content)
        entries[addr] = content
    # Verify all
    for addr, expected in entries.items():
        o, d, _ = store.read(addr)
        assert o == EntryOutcome.VALID, f"stress entry {addr:#06x} valid: expected VALID, got {o}"
        assert d == expected, f"stress entry {addr:#06x} content mismatch"


def test_large_content_stress():
    """Write 100 entries to content Store, verify all."""
    bb = BootstrapBlock()
    store = ContentStore(bb)
    entries = {}
    for i in range(100):
        addr = store.compose(1, 1, i)
        content = bytes([i % 256] * (100 + i * 10))
        h = store.write(addr, content)
        entries[addr] = (content, h)
    # Verify all
    for addr, (expected, h_expected) in entries.items():
        o, d, _, h = store.read(addr)
        assert o == EntryOutcome.VALID, f"stress entry {addr:#06x} valid: expected VALID, got {o}"
        assert d == expected, f"stress entry {addr:#06x} content mismatch"
        assert h == h_expected, f"stress entry {addr:#06x} hash mismatch"


# ═══════════════════════════════════════════════════════════════════════════
# 13. Content store deduplication with stress
# ═══════════════════════════════════════════════════════════════════════════

def test_dedup_repeated_content():
    """Writing identical content to many addresses must share heap space."""
    bb = BootstrapBlock()
    store = ContentStore(bb)
    content = b"repeated dedup content"
    addrs = []
    for i in range(50):
        addr = store.compose(1, 1, i)
        h = store.write(addr, content)
        addrs.append((addr, h))
    # All should return same hash
    hashes = [h for _, h in addrs]
    assert all(h == hashes[0] for h in hashes), "all hashes identical"
    # Refcount should be 50
    record = store.content_table[hashes[0]]
    assert record.refcount == 50, f"refcount 50, got {record.refcount}"
    # Heap should be very small (one entry)
    assert len(store.heap) >= record.offset + record.length, "heap has one entry"
    assert len(store.heap) < 100, f"heap small ({len(store.heap)} bytes) for 50 writes"


# ═══════════════════════════════════════════════════════════════════════════
# 14. Error message consistency
# ═══════════════════════════════════════════════════════════════════════════

def test_error_message_patterns():
    """Both stores' error messages must contain expected terms."""
    bb = BootstrapBlock()
    ps = PayloadStore(bb)
    cs = ContentStore(bb)

    # Reserved range
    bad = ps.compose(0, 0, 1)
    with pytest.raises(PayloadError) as excinfo_p:
        ps.write(bad, b"x")
    assert "reserved" in str(excinfo_p.value).lower(), f"payload reserved msg: {excinfo_p.value}"

    with pytest.raises(PayloadError) as excinfo_c:
        cs.write(bad, b"x")
    assert "reserved" in str(excinfo_c.value).lower(), f"content reserved msg: {excinfo_c.value}"

    # Missing dependency
    missing_ps = ps.compose(1, 1, 0xFA)
    main_ps = ps.compose(1, 1, 0xFB)
    with pytest.raises(PayloadError) as excinfo_dep:
        ps.write(main_ps, b"x", depends_on=[missing_ps])
    assert "valid" in str(excinfo_dep.value).lower(), f"payload dep msg: {excinfo_dep.value}"


# ═══════════════════════════════════════════════════════════════════════════
# 15. Integration suite summary
# ═══════════════════════════════════════════════════════════════════════════

def test_integration_summary():
    """Count all integration test functions."""
    count = len([name for name in dir(sys.modules[__name__])
                 if name.startswith("test_") and name != "test_integration_summary"])
    assert count > 0, f"integration suite: {count} test functions (expected > 0)"


# ═══════════════════════════════════════════════════════════════════════════
# Runner
# ═══════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    pytest.main([__file__])
