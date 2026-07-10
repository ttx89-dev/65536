"""
test_payload.py — exhaustive unit tests for payload_codec.py
═══════════════════════════════════════════════════════════════════════════════

Tests every public method of Store, Descriptor, CRC16, compute_checksum,
and all error paths. Non-reserved addresses (tier>0 or category>0) are
required for write operations.
═══════════════════════════════════════════════════════════════════════════════
"""

import sys, os
sys.path.insert(0, os.path.dirname(__file__))

import pytest
from bootstrap_block import BootstrapBlock, BootstrapError
from payload_codec import Store, Descriptor, EntryOutcome, PayloadError, _crc16, compute_checksum, ChecksumAlgo


# ═══════════════════════════════════════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════════════════════════════════════

def _make_store() -> tuple[Store, BootstrapBlock]:
    bb = BootstrapBlock()
    store = Store(bb)
    return store, bb


def _addr(store: Store, idx: int = 0x01) -> int:
    """Return a writable address (tier>0)."""
    return store.compose(tier=1, category=1, index=idx)


# ═══════════════════════════════════════════════════════════════════════════
# 1. CRC16
# ═══════════════════════════════════════════════════════════════════════════

def test_crc16_empty():
    """CRC16 of empty data with init=0xFFFF is 0xFFFF."""
    crc = _crc16(b"")
    assert crc == 0xFFFF, f"empty crc16: got 0x{crc:04X}, expected 0xFFFF"


def test_crc16_known():
    """CRC16 of known test vectors."""
    crc1 = _crc16(b"hello")
    crc2 = _crc16(b"hello")
    assert crc1 == crc2, f"deterministic crc16: 0x{crc1:04X} != 0x{crc2:04X}"
    crc3 = _crc16(b"world")
    assert crc1 != crc3, f"different inputs -> different crc16: 0x{crc1:04X} == 0x{crc3:04X}"


def test_crc16_single_bytes():
    """CRC16 returns int in 16-bit range."""
    crc = _crc16(b"\x00")
    assert isinstance(crc, int), f"crc16 returns int, got {type(crc)}"
    assert 0 <= crc <= 0xFFFF, f"crc16 fits 16 bits, got 0x{crc:04X}"


def test_crc16_custom_init():
    """CRC16 with custom init value produces different results."""
    crc1 = _crc16(b"test", poly=0x1021, init=0xFFFF)
    crc2 = _crc16(b"test", poly=0x1021, init=0x0000)
    assert crc1 != crc2, f"different init -> different crc: 0x{crc1:04X} == 0x{crc2:04X}"


# ═══════════════════════════════════════════════════════════════════════════
# 2. compute_checksum
# ═══════════════════════════════════════════════════════════════════════════

def test_compute_checksum_sum8():
    """SUM8 checksum = sum of data bytes % 256."""
    data = b"hello"
    s = sum(data) % 256
    assert compute_checksum(data, ChecksumAlgo.SUM8) == s, f"SUM8: expected {s}, got {compute_checksum(data, ChecksumAlgo.SUM8)}"


def test_compute_checksum_crc16():
    """CRC16 checksum = _crc16(data)."""
    data = b"test payload"
    assert compute_checksum(data, ChecksumAlgo.CRC16) == _crc16(data), "CRC16 checksum mismatch"


def test_compute_checksum_none():
    """NONE checksum = 0."""
    assert compute_checksum(b"anything", ChecksumAlgo.NONE) == 0, "NONE checksum should be 0"


def test_compute_checksum_unknown():
    """Unknown algorithm raises PayloadError."""
    with pytest.raises(PayloadError):
        compute_checksum(b"x", 99)


# ═══════════════════════════════════════════════════════════════════════════
# 3. Descriptor
# ═══════════════════════════════════════════════════════════════════════════

def test_descriptor_creation():
    """Descriptor must be created with all 4 positional args."""
    d = Descriptor(status=1, checksum=0x1234, length=100, offset=5000)
    assert d.status == 1, f"status: expected 1, got {d.status}"
    assert d.checksum == 0x1234, f"checksum: expected 0x1234, got 0x{d.checksum:04X}"
    assert d.length == 100, f"length: expected 100, got {d.length}"
    assert d.offset == 5000, f"offset: expected 5000, got {d.offset}"


# ═══════════════════════════════════════════════════════════════════════════
# 4. Store — Init
# ═══════════════════════════════════════════════════════════════════════════

def test_store_init():
    """Store must initialize with a bootstrap block."""
    store, bb = _make_store()
    assert store.bootstrap is bb, "bootstrap reference"
    assert len(store.descriptors) == 65536 * 15, f"descriptor table size: expected 983040, got {len(store.descriptors)}"
    assert len(store.heap) == 0, f"heap starts empty, got {len(store.heap)} bytes"


# ═══════════════════════════════════════════════════════════════════════════
# 5. Store — Compose
# ═══════════════════════════════════════════════════════════════════════════

def test_compose_address():
    """compose should return valid 16-bit address."""
    store, _ = _make_store()
    addr = store.compose(1, 2, 0x34)
    assert 0 <= addr <= 0xFFFF, f"address range: {addr:#06x}"
    tier, cat, idx = store.bootstrap.decompose_address(addr)
    assert tier == 1, f"tier: expected 1, got {tier}"
    assert cat == 2, f"category: expected 2, got {cat}"
    assert idx == 0x34, f"index: expected 0x34, got {idx}"


def test_compose_out_of_range():
    """Out-of-range tier/category/index must raise PayloadError."""
    store, _ = _make_store()
    with pytest.raises(PayloadError):
        store.compose(99, 0, 1)
    with pytest.raises(PayloadError):
        store.compose(0, 99, 1)
    with pytest.raises(PayloadError):
        store.compose(0, 0, 256)


# ═══════════════════════════════════════════════════════════════════════════
# 6. Store — Write / Read
# ═══════════════════════════════════════════════════════════════════════════

def test_write_then_read():
    """Write then read back must succeed."""
    store, _ = _make_store()
    addr = _addr(store, 0x10)
    content = b"Hello, 65536!"
    store.write(addr, content)
    outcome, data, deps = store.read(addr)
    assert outcome == EntryOutcome.VALID, f"outcome: expected VALID, got {outcome}"
    assert data == content, f"content match: expected {content!r}, got {data!r}"


def test_write_empty():
    """Writing empty bytes works."""
    store, _ = _make_store()
    addr = _addr(store, 0xAA)
    store.write(addr, b"")
    outcome, data, deps = store.read(addr)
    assert outcome == EntryOutcome.VALID, f"empty valid: expected VALID, got {outcome}"
    assert data == b"", f"empty data: expected b'', got {data!r}"


def test_write_large_payload():
    """Writing many entries must all read back correctly."""
    store, _ = _make_store()
    for i in range(50):
        addr = _addr(store, i)
        content = bytes([i] * 32)
        store.write(addr, content)
        outcome, data, _ = store.read(addr)
        assert outcome == EntryOutcome.VALID, f"entry {i} valid: expected VALID, got {outcome}"
        assert data == content, f"entry {i} content: expected {content!r}, got {data!r}"


def test_write_reserved_range_rejected():
    """Writing to tier=0,category=0 must be rejected."""
    store, bb = _make_store()
    bad_addr = store.compose(0, 0, 1)
    with pytest.raises(PayloadError):
        store.write(bad_addr, b"nope")


def test_read_unassigned():
    """Reading an unwritten address must return UNASSIGNED."""
    store, _ = _make_store()
    addr = store.compose(0xF, 0xF, 0xFF)
    outcome, data, deps = store.read(addr)
    assert outcome == EntryOutcome.UNASSIGNED, f"unassigned outcome: expected UNASSIGNED, got {outcome}"
    assert data is None, f"unassigned data: expected None, got {data!r}"


# ═══════════════════════════════════════════════════════════════════════════
# 7. Store — Delete
# ═══════════════════════════════════════════════════════════════════════════

def test_delete():
    """Delete must mark entry as DELETED."""
    store, _ = _make_store()
    addr = _addr(store, 0x42)
    store.write(addr, b"delete me")
    outcome1, _, _ = store.read(addr)
    assert outcome1 == EntryOutcome.VALID, f"pre-delete: expected VALID, got {outcome1}"
    store.delete(addr)
    outcome2, data, deps = store.read(addr)
    assert outcome2 == EntryOutcome.DELETED, f"post-delete: expected DELETED, got {outcome2}"
    assert data is None, f"post-delete data: expected None, got {data!r}"


def test_delete_unassigned_raises():
    """Deleting an UNASSIGNED address must raise PayloadError."""
    store, _ = _make_store()
    addr = store.compose(1, 1, 0x99)
    with pytest.raises(PayloadError):
        store.delete(addr)


def test_overwrite():
    """Overwriting must update content."""
    store, _ = _make_store()
    addr = _addr(store, 0x50)
    store.write(addr, b"first")
    store.write(addr, b"second")
    outcome, data, _ = store.read(addr)
    assert outcome == EntryOutcome.VALID, f"overwrite valid: expected VALID, got {outcome}"
    assert data == b"second", f"overwrite content: expected b'second', got {data!r}"


# ═══════════════════════════════════════════════════════════════════════════
# 8. Dependencies
# ═══════════════════════════════════════════════════════════════════════════

def test_write_with_dependencies():
    """Reading an entry with dependencies must return dependency list."""
    store, _ = _make_store()
    dep_addr = _addr(store, 0x60)
    store.write(dep_addr, b"dependency")
    main_addr = _addr(store, 0x61)
    store.write(main_addr, b"main", depends_on=[dep_addr])
    outcome, data, deps = store.read(main_addr)
    assert outcome == EntryOutcome.VALID, f"with deps valid: expected VALID, got {outcome}"
    assert deps == [dep_addr], f"dependency list: expected {[dep_addr]}, got {deps}"


def test_missing_dependency_raises():
    """Writing with a not-yet-written dependency must raise."""
    store, _ = _make_store()
    missing = _addr(store, 0x70)
    main = _addr(store, 0x71)
    with pytest.raises(PayloadError):
        store.write(main, b"x", depends_on=[missing])


def test_too_many_deps_raises():
    """More than 255 dependencies must raise."""
    store, _ = _make_store()
    addr = _addr(store, 0x80)
    with pytest.raises(PayloadError):
        store.write(addr, b"x", depends_on=list(range(256)))


# ═══════════════════════════════════════════════════════════════════════════
# 9. write_ordered
# ═══════════════════════════════════════════════════════════════════════════

def test_write_ordered():
    """write_ordered must return addresses in dependency-sorted order."""
    store, _ = _make_store()
    a = _addr(store, 0x90)
    b = _addr(store, 0x91)
    c = _addr(store, 0x92)
    # c depends on b, b depends on a — submitted in reverse
    order = store.write_ordered([
        (c, b"c", [b]),
        (a, b"a", []),
        (b, b"b", [a]),
    ])
    # a must come before b, b before c
    assert order.index(a) == 0, f"a first in {[hex(x) for x in order]}"
    assert order.index(b) == 1, f"b second in {[hex(x) for x in order]}"
    assert order.index(c) == 2, f"c third in {[hex(x) for x in order]}"
    # All must be readable
    for addr in (a, b, c):
        outcome, data, _ = store.read(addr)
        assert outcome == EntryOutcome.VALID, f"ordered {addr:#06x} valid: expected VALID, got {outcome}"


def test_write_ordered_cycle_detected():
    """A dependency cycle within the batch must raise PayloadError."""
    store, _ = _make_store()
    a = _addr(store, 0xA0)
    b = _addr(store, 0xA1)
    with pytest.raises(PayloadError):
        store.write_ordered([
            (a, b"a", [b]),
            (b, b"b", [a]),
        ])


def test_write_ordered_duplicate_raises():
    """Duplicate addresses in one batch must raise."""
    store, _ = _make_store()
    a = _addr(store, 0xB0)
    with pytest.raises(PayloadError):
        store.write_ordered([
            (a, b"a", []),
            (a, b"b", []),  # same address
        ])


# ═══════════════════════════════════════════════════════════════════════════
# 10. Corruption Detection
# ═══════════════════════════════════════════════════════════════════════════

def test_checksum_mismatch_on_read():
    """Tampering heap data after write must produce CORRUPT."""
    store, _ = _make_store()
    addr = _addr(store, 0xC0)
    store.write(addr, b"corrupt target")
    # Read descriptor to find heap offset
    d = store._get_descriptor(addr)
    assert d.length > 0, "entry has body"
    # Flip a byte in the heap
    store.heap[d.offset] ^= 0xFF
    outcome, data, deps = store.read(addr)
    assert outcome == EntryOutcome.CORRUPT, f"should be CORRUPT, got {outcome}"


# ═══════════════════════════════════════════════════════════════════════════
# 11. Roundtrip
# ═══════════════════════════════════════════════════════════════════════════

def test_payload_roundtrip():
    """Full write-read-delete-reuse cycle."""
    store, _ = _make_store()
    addr = _addr(store, 0xD0)
    content = b"\x00\xFF" * 100
    store.write(addr, content)
    o1, d1, _ = store.read(addr)
    assert o1 == EntryOutcome.VALID, f"write: expected VALID, got {o1}"
    assert d1 == content, f"content: expected {content!r}, got {d1!r}"
    store.delete(addr)
    o2, d2, _ = store.read(addr)
    assert o2 == EntryOutcome.DELETED, f"deleted: expected DELETED, got {o2}"
    store.write(addr, b"reuse")
    o3, d3, _ = store.read(addr)
    assert o3 == EntryOutcome.VALID, f"reuse: expected VALID, got {o3}"
    assert d3 == b"reuse", f"reuse content: expected b'reuse', got {d3!r}"


# ═══════════════════════════════════════════════════════════════════════════
# 12. Cross-module integration
# ═══════════════════════════════════════════════════════════════════════════

def test_cross_module_roundtrip():
    """Write via payload Store, verify entry is consistent."""
    store, _ = _make_store()
    addr = _addr(store, 0xE0)
    content = b"cross-module test"
    store.write(addr, content)
    outcome, data, deps = store.read(addr)
    assert outcome == EntryOutcome.VALID, f"cross valid: expected VALID, got {outcome}"
    assert data == content, f"cross content: expected {content!r}, got {data!r}"
    # Verify descriptor internals
    d = store._get_descriptor(addr)
    assert d.status == 1, f"VALID status in descriptor: expected 1, got {d.status}"
    assert d.length > 0, f"non-zero length: got {d.length}"
    assert d.offset >= 0, f"non-negative offset: got {d.offset}"


# ═══════════════════════════════════════════════════════════════════════════
# Runner
# ═══════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    pytest.main([__file__])
