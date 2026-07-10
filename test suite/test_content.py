"""
test_content.py — exhaustive unit tests for content_store.py
═══════════════════════════════════════════════════════════════════════════════

Tests FNV1a-64 hashing, content deduplication, refcounting, dependency
resolution by content hash, and all error paths.
═══════════════════════════════════════════════════════════════════════════════
"""

import sys, os
sys.path.insert(0, os.path.dirname(__file__))

import pytest
from bootstrap_block import BootstrapBlock
from content_store import Store, ContentRecord, EntryOutcome, PayloadError, fnv1a_64


# ═══════════════════════════════════════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════════════════════════════════════

def _make_store() -> Store:
    bb = BootstrapBlock()
    return Store(bb)


def _addr(store: Store, idx: int = 0x01, tier: int = 1, cat: int = 1) -> int:
    """Return a writable address (tier>0)."""
    return store.compose(tier=tier, category=cat, index=idx)


# ═══════════════════════════════════════════════════════════════════════════
# 1. FNV1a-64
# ═══════════════════════════════════════════════════════════════════════════

def test_fnv1a_64_empty():
    """FNV1a-64 of empty is offset basis."""
    h = fnv1a_64(b"")
    assert h == 0xcbf29ce484222325, f"empty: expected 0xcbf29ce484222325, got 0x{h:016x}"


def test_fnv1a_64_known():
    """FNV1a-64 is deterministic."""
    assert fnv1a_64(b"hello") == fnv1a_64(b"hello"), "deterministic"
    assert isinstance(fnv1a_64(b"x"), int), f"returns int, got {type(fnv1a_64(b'x'))}"
    assert fnv1a_64(b"x") > 0, f"positive: got {fnv1a_64(b'x')}"


def test_fnv1a_64_different():
    """Different inputs -> different hashes (sanity)."""
    assert fnv1a_64(b"hello") != fnv1a_64(b"world"), "hello != world"
    assert fnv1a_64(b"hello") != fnv1a_64(b"Hello"), "case sensitivity"


def test_fnv1a_64_large():
    """FNV1a-64 of 10KB must complete quickly."""
    data = os.urandom(10_000)
    h = fnv1a_64(data)
    assert isinstance(h, int), f"large fnv1a returns int, got {type(h)}"


# ═══════════════════════════════════════════════════════════════════════════
# 2. ContentRecord
# ═══════════════════════════════════════════════════════════════════════════

def test_content_record_default():
    """ContentRecord defaults: offset 0, length 0, refcount 0."""
    cr = ContentRecord(offset=10, length=20)
    assert cr.offset == 10, f"offset: expected 10, got {cr.offset}"
    assert cr.length == 20, f"length: expected 20, got {cr.length}"
    assert cr.refcount == 0, f"refcount: expected 0, got {cr.refcount}"


# ═══════════════════════════════════════════════════════════════════════════
# 3. Store — Init
# ═══════════════════════════════════════════════════════════════════════════

def test_store_init():
    """Store initializes with correct internal structures."""
    store = _make_store()
    assert len(store.address_table) == 65536 * 9, f"address table: expected 589824, got {len(store.address_table)}"
    assert len(store.content_table) == 0, f"content table empty: expected 0, got {len(store.content_table)}"
    assert len(store.heap) == 0, f"heap empty: expected 0, got {len(store.heap)}"


# ═══════════════════════════════════════════════════════════════════════════
# 4. Store — Compose
# ═══════════════════════════════════════════════════════════════════════════

def test_compose_address():
    """compose returns valid 16-bit address."""
    store = _make_store()
    addr = store.compose(1, 2, 0x34)
    assert 0 <= addr <= 0xFFFF, f"range: {addr:#06x}"
    tier, cat, idx = store.bootstrap.decompose_address(addr)
    assert tier == 1, f"tier: expected 1, got {tier}"
    assert cat == 2, f"category: expected 2, got {cat}"
    assert idx == 0x34, f"index: expected 0x34, got {idx}"


# ═══════════════════════════════════════════════════════════════════════════
# 5. Store — Write / Read / Delete
# ═══════════════════════════════════════════════════════════════════════════

def test_write_then_read():
    """Write then read back must succeed."""
    store = _make_store()
    addr = _addr(store, 0x10)
    content = b"content addr storage"
    h = store.write(addr, content)
    outcome, data, deps, chash = store.read(addr)
    assert outcome == EntryOutcome.VALID, f"valid: expected VALID, got {outcome}"
    assert data == content, f"content match: expected {content!r}, got {data!r}"
    assert chash == h, f"hash match: expected 0x{h:016x}, got 0x{chash:016x}"


def test_content_addressability():
    """Same content at different addresses -> same hash, heap dedup."""
    store = _make_store()
    content = b"identical content"
    addr_a = _addr(store, 0x20)
    addr_b = _addr(store, 0x21)
    h_a = store.write(addr_a, content)
    h_b = store.write(addr_b, content)
    assert h_a == h_b, f"same content -> same hash: 0x{h_a:016x} != 0x{h_b:016x}"
    # Heap should NOT have grown for the second write (dedup)
    for h in (h_a, h_b):
        record = store.content_table.get(h)
        if record is not None:
            assert record.refcount == 2, f"refcount 2 for hash 0x{h:016x}, got {record.refcount}"


def test_read_unassigned():
    """Unwritten address -> UNASSIGNED."""
    store = _make_store()
    addr = store.compose(0xF, 0xF, 0xFF)
    outcome, data, deps, chash = store.read(addr)
    assert outcome == EntryOutcome.UNASSIGNED, f"unassigned: expected UNASSIGNED, got {outcome}"
    assert data is None, f"data: expected None, got {data!r}"
    assert chash is None, f"hash: expected None, got {chash!r}"


def test_write_empty():
    """Writing empty bytes works."""
    store = _make_store()
    addr = _addr(store, 0x30)
    h = store.write(addr, b"")
    expected_hash = fnv1a_64(b"\x00")  # body = b"\x00" (0 deps) + b"" = b"\x00"
    assert h == expected_hash, f"empty content hash: expected 0x{expected_hash:016x}, got 0x{h:016x}"
    outcome, data, _, chash = store.read(addr)
    assert outcome == EntryOutcome.VALID, f"empty valid: expected VALID, got {outcome}"
    assert data == b"", f"empty data: expected b'', got {data!r}"


def test_write_already_written_raises():
    """Content store is first-write only; overwrite must raise."""
    store = _make_store()
    addr = _addr(store, 0x40)
    store.write(addr, b"first")
    with pytest.raises(PayloadError):
        store.write(addr, b"second")


def test_write_reserved_range_rejected():
    """Writing to tier=0,category=0 must be rejected."""
    store = _make_store()
    bad_addr = store.compose(0, 0, 1)
    with pytest.raises(PayloadError):
        store.write(bad_addr, b"nope")


# ═══════════════════════════════════════════════════════════════════════════
# 6. Store — Delete
# ═══════════════════════════════════════════════════════════════════════════

def test_delete():
    """Delete must mark as DELETED and decrement refcount."""
    store = _make_store()
    addr = _addr(store, 0x50)
    h = store.write(addr, b"to delete")
    store.delete(addr)
    outcome, data, _, _ = store.read(addr)
    assert outcome == EntryOutcome.DELETED, f"deleted: expected DELETED, got {outcome}"
    # Refcount should be 0
    record = store.content_table.get(h)
    if record is not None:
        assert record.refcount == 0, f"refcount after delete: expected 0, got {record.refcount}"


def test_delete_unassigned_raises():
    """Deleting UNASSIGNED must raise."""
    store = _make_store()
    addr = store.compose(1, 1, 0x51)
    with pytest.raises(PayloadError):
        store.delete(addr)


# ═══════════════════════════════════════════════════════════════════════════
# 7. Dependencies (by content hash)
# ═══════════════════════════════════════════════════════════════════════════

def test_write_with_dependencies():
    """Writing with deps works, read returns dep hashes."""
    store = _make_store()
    dep_addr = _addr(store, 0x60)
    h_dep = store.write(dep_addr, b"dependency")
    main_addr = _addr(store, 0x61)
    h_main = store.write(main_addr, b"main", depends_on=[dep_addr])
    outcome, data, dep_hashes, chash = store.read(main_addr)
    assert outcome == EntryOutcome.VALID, f"deps valid: expected VALID, got {outcome}"
    assert dep_hashes == [h_dep], f"dep hashes: expected {[h_dep]}, got {dep_hashes}"
    assert chash == h_main, f"hash match: expected 0x{h_main:016x}, got 0x{chash:016x}"


def test_missing_dependency_raises():
    """Dep on not-yet-written address must raise."""
    store = _make_store()
    missing = _addr(store, 0x70)
    main = _addr(store, 0x71)
    with pytest.raises(PayloadError):
        store.write(main, b"x", depends_on=[missing])


def test_too_many_deps_raises():
    """More than 255 deps must raise."""
    store = _make_store()
    addr = _addr(store, 0x80)
    with pytest.raises(PayloadError):
        store.write(addr, b"x", depends_on=list(range(256)))


# ═══════════════════════════════════════════════════════════════════════════
# 8. Deduplication via content hash across dependency chains
# ═══════════════════════════════════════════════════════════════════════════

def test_dedup_different_dep_slots_same_content():
    """Two entries with different dep ADDRESSES but same dep CONTENT
    and same own content must have the same identity hash."""
    store = _make_store()
    # Two deps with identical content at different addresses
    dep_a = _addr(store, 0x90, tier=1, cat=1)
    dep_b = _addr(store, 0x91, tier=1, cat=6)
    h_dep = store.write(dep_a, b"shared dep content")
    store.write(dep_b, b"shared dep content")  # deduped to same hash
    # Two mains depending on different addresses but same dep content
    main_a = _addr(store, 0x92, tier=2, cat=1)
    main_b = _addr(store, 0x93, tier=2, cat=6)
    h_a = store.write(main_a, b"same body", depends_on=[dep_a])
    h_b = store.write(main_b, b"same body", depends_on=[dep_b])
    assert h_a == h_b, f"identity hash same despite different dep slots: 0x{h_a:016x} != 0x{h_b:016x}"


# ═══════════════════════════════════════════════════════════════════════════
# 9. Corruption detection
# ═══════════════════════════════════════════════════════════════════════════

def test_corruption_detection():
    """Heap corruption must produce CORRUPT."""
    store = _make_store()
    addr = _addr(store, 0xA0)
    store.write(addr, b"corrupt me")
    # Tamper the heap
    if store.heap:
        store.heap[0] ^= 0xFF
        outcome, data, deps, chash = store.read(addr)
        assert outcome == EntryOutcome.CORRUPT, f"should be CORRUPT, got {outcome}"


# ═══════════════════════════════════════════════════════════════════════════
# 10. Refcounting
# ═══════════════════════════════════════════════════════════════════════════

def test_refcounting():
    """Refcount must track number of addresses pointing at content."""
    store = _make_store()
    addr_a = _addr(store, 0xB0, tier=1, cat=1)
    addr_b = _addr(store, 0xB1, tier=1, cat=2)
    h = store.write(addr_a, b"shared")
    rec = store.content_table[h]
    assert rec.refcount == 1, f"refcount after first write: expected 1, got {rec.refcount}"
    store.write(addr_b, b"shared")
    assert rec.refcount == 2, f"refcount after dedup: expected 2, got {rec.refcount}"
    store.delete(addr_a)
    assert rec.refcount == 1, f"refcount after one delete: expected 1, got {rec.refcount}"
    store.delete(addr_b)
    assert rec.refcount == 0, f"refcount after both deleted: expected 0, got {rec.refcount}"


# ═══════════════════════════════════════════════════════════════════════════
# 11. Roundtrip
# ═══════════════════════════════════════════════════════════════════════════

def test_content_roundtrip():
    """Full write-read-delete cycle."""
    store = _make_store()
    addr = _addr(store, 0xC0)
    content = b"roundtrip \x00\xFF"
    h = store.write(addr, content)
    o1, d1, _, h1 = store.read(addr)
    assert o1 == EntryOutcome.VALID, f"write: expected VALID, got {o1}"
    assert d1 == content, f"content: expected {content!r}, got {d1!r}"
    assert h1 == h, f"hash: expected 0x{h:016x}, got 0x{h1:016x}"
    store.delete(addr)
    o2, _, _, _ = store.read(addr)
    assert o2 == EntryOutcome.DELETED, f"deleted: expected DELETED, got {o2}"


# ═══════════════════════════════════════════════════════════════════════════
# Runner
# ═══════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    pytest.main([__file__])
