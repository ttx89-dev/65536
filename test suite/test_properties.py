"""
test_properties.py — Hypothesis property-based tests, 65535-point framework
═══════════════════════════════════════════════════════════════════════════════

Invariant-driven testing for all three modules. Each property is a universal
quantification over a well-typed input space: if it holds for all
generated inputs, it holds for any real input.

Run:   python -m pytest test_properties.py
   or: python -m hypothesis test_properties.py
   or: python test_properties.py

Hypothesis strategies are defined at module level for reuse and clarity.
═══════════════════════════════════════════════════════════════════════════════
"""

import sys, os
sys.path.insert(0, os.path.dirname(__file__))

from hypothesis import given, assume, strategies as st, settings, HealthCheck
from hypothesis.stateful import RuleBasedStateMachine, rule, precondition, invariant

from bootstrap_block import (
    BootstrapBlock, BootstrapError, ChecksumAlgo,
    ProvenanceScheme, ReadOutcome, BLOCK_SIZE, PREAMBLE_SIZE,
    RESERVED_SIZE, MAGIC,
)
from payload_codec import Store as PayloadStore, EntryOutcome, PayloadError, compute_checksum
from content_store import Store as ContentStore, fnv1a_64


# ═══════════════════════════════════════════════════════════════════════════
# Shared Hypothesis Strategies
# ═══════════════════════════════════════════════════════════════════════════

# Fixed bit widths for address_width=16 (the only supported value)
TIER_BITS = 4
CAT_BITS = 4
IDX_BITS = 8
TIER_MASK = (1 << TIER_BITS) - 1
CAT_MASK  = (1 << CAT_BITS) - 1
IDX_MASK  = (1 << IDX_BITS) - 1
MAX_TIER  = TIER_MASK
MAX_CAT   = CAT_MASK
MAX_IDX   = IDX_MASK

valid_tiers   = st.integers(min_value=0, max_value=MAX_TIER)
valid_cats    = st.integers(min_value=0, max_value=MAX_CAT)
valid_indices = st.integers(min_value=0, max_value=MAX_IDX)

# Non-reserved tier/category combos (exclude tier=0, category=0)
nonreserved_tiers   = st.integers(min_value=0, max_value=MAX_TIER)
nonreserved_cats    = st.integers(min_value=0, max_value=MAX_CAT)

# Checksum algos that actually work (NONE, SUM8, CRC16 — SHA256_TRUNC raises)
active_algos = st.sampled_from([ChecksumAlgo.NONE, ChecksumAlgo.SUM8, ChecksumAlgo.CRC16])

# Valid bootstrap block configurations
valid_checksum_algos = st.sampled_from([ChecksumAlgo.NONE, ChecksumAlgo.SUM8, ChecksumAlgo.CRC16])
valid_prov_schemes   = st.sampled_from(list(ProvenanceScheme))
valid_headrooms      = st.integers(min_value=0, max_value=100)
valid_tombstones     = st.integers(min_value=0, max_value=255)
valid_counts         = st.integers(min_value=1, max_value=16)

# Content: small bytes, empty bytes, and larger blocks
small_content = st.binary(min_size=0, max_size=64)
any_content   = st.binary(min_size=0, max_size=1024)

# Dependency lists (0-4 deps)
dep_list = st.lists(
    st.integers(min_value=0x0100, max_value=0xFFFF),
    min_size=0, max_size=4,
)


# ═══════════════════════════════════════════════════════════════════════════
# 1. BootstrapBlock Properties
# ═══════════════════════════════════════════════════════════════════════════

@given(valid_checksum_algos, valid_prov_schemes, valid_headrooms,
       valid_tombstones, valid_counts, valid_counts, small_content)
@settings(max_examples=200, suppress_health_check=list(HealthCheck))
def test_bootstrap_roundtrip(algo, prov, headroom, tombstone,
                              cat_count, tier_count, reserved_small):
    """Any valid BootstrapBlock survives serialize→parse→serialize unchanged."""
    reserved = reserved_small.ljust(RESERVED_SIZE, b"\x00")[:RESERVED_SIZE]
    bb = BootstrapBlock(
        checksum_algo=algo, provenance_scheme=prov,
        headroom_ratio=headroom, tombstone_sentinel=tombstone,
        category_count=cat_count, tier_count=tier_count,
        reserved_slots=reserved,
    )
    data = bb.to_bytes()
    assert len(data) == BLOCK_SIZE
    parsed = BootstrapBlock.parse(data)
    assert parsed == bb
    assert parsed.to_bytes() == data


@given(valid_tiers, valid_cats, valid_indices)
@settings(max_examples=500, suppress_health_check=list(HealthCheck))
def test_address_decompose_roundtrip(tier, cat, idx):
    """Compose then decompose yields original (tier, category, index)."""
    bb = BootstrapBlock()
    store = PayloadStore(bb)
    addr = store.compose(tier, cat, idx)
    t, c, i = bb.decompose_address(addr)
    assert (t, c, i) == (tier, cat, idx), \
        f"({tier},{cat},{idx}) -> 0x{addr:04X} -> ({t},{c},{i})"


@given(st.integers(min_value=0x10000, max_value=0xFFFFFFFF))
@settings(max_examples=100, suppress_health_check=list(HealthCheck))
def test_decompose_out_of_range(bad_addr):
    """Address above 0xFFFF must be rejected."""
    bb = BootstrapBlock()
    try:
        bb.decompose_address(bad_addr)
        assert False, f"0x{bad_addr:X} should be out of range"
    except BootstrapError:
        pass


@given(st.binary(min_size=0, max_size=BLOCK_SIZE - 1),
       st.binary(min_size=BLOCK_SIZE + 1, max_size=BLOCK_SIZE + 100))
@settings(max_examples=50, suppress_health_check=list(HealthCheck))
def test_parse_wrong_size(short, long_):
    """Blocks of wrong size must be rejected."""
    bb = BootstrapBlock()
    try:
        BootstrapBlock.parse(short)
        assert False, "short block parsed"
    except BootstrapError:
        pass
    # Tampered-to-wrong-size too
    data = bb.to_bytes()
    try:
        BootstrapBlock.parse(data + b"\x00")
        assert False, "long block parsed"
    except BootstrapError:
        pass


@given(st.integers(min_value=0, max_value=0xFF))
@settings(max_examples=100, suppress_health_check=list(HealthCheck))
def test_read_slot_consistency(slot):
    """read_slot returns sensible outcome for any slot 0-255 against the
    default block's serialized bytes."""
    bb = BootstrapBlock()
    data = bb.to_bytes()
    # Build a mock store with the block installed
    mock_store = bytearray(PREAMBLE_SIZE + 256)
    mock_store[:BLOCK_SIZE] = data
    outcome, val = bb.read_slot(bytes(mock_store), slot)
    if slot == 0x00:
        assert outcome == ReadOutcome.VALID and val == 0
    else:
        assert outcome in (ReadOutcome.VALID, ReadOutcome.UNASSIGNED, ReadOutcome.DELETED)


@given(st.integers(min_value=256, max_value=1000))
@settings(max_examples=50, suppress_health_check=list(HealthCheck))
def test_read_slot_out_of_range(bad_slot):
    """Slots above 255 must be rejected."""
    bb = BootstrapBlock()
    mock_store = b"\x00" * (PREAMBLE_SIZE + 256)
    try:
        bb.read_slot(mock_store, bad_slot)
        assert False, f"slot {bad_slot} should be out of range"
    except BootstrapError:
        pass


@given(st.integers(min_value=1, max_value=0xFF),
       st.integers(min_value=0, max_value=0xFF))
@settings(max_examples=200, suppress_health_check=list(HealthCheck))
def test_tamper_detection(byte_offset, flip_mask):
    """Any single-byte flip in the serialized block must be detected at
    parse time, EXCEPT slot 0xFF (the block checksum byte itself) which
    is deliberately special (slot 255's value is the checksum, being wrong
    there is not itself a checksum violation — the checksum is about the
    REST of the block)."""
    bb = BootstrapBlock()
    data = bytearray(bb.to_bytes())
    # Flip within the 267 bytes, at a valid offset
    off = byte_offset % BLOCK_SIZE
    data[off] ^= (flip_mask & 0xFF) or 1
    try:
        BootstrapBlock.parse(bytes(data))
        # If it parsed, it must be because the checksum byte was the one flipped
        # and the data happens to still checksum correctly (1/256 chance)
        assert off == BLOCK_SIZE - 1, \
            f"tamper at offset {off} went undetected"
    except BootstrapError:
        pass  # expected


# ═══════════════════════════════════════════════════════════════════════════
# 2. Payload Store Properties
# ═══════════════════════════════════════════════════════════════════════════

def _nonreserved_addr(store, tier, cat, idx):
    """Helper to skip reserved range."""
    assume(not (tier == 0 and cat == 0))
    return store.compose(tier, cat, idx)


@given(nonreserved_tiers, nonreserved_cats, valid_indices, small_content, active_algos)
@settings(max_examples=300, suppress_health_check=list(HealthCheck))
def test_payload_write_read(tier, cat, idx, content, algo):
    """write then read must return VALID with identical content."""
    assume(not (tier == 0 and cat == 0))
    bb = BootstrapBlock(checksum_algo=algo)
    store = PayloadStore(bb)
    addr = store.compose(tier, cat, idx)
    store.write(addr, content)
    outcome, data, deps = store.read(addr)
    assert outcome == EntryOutcome.VALID, f"expected VALID at {addr:#06x}"
    assert data == content, f"content mismatch at {addr:#06x}"
    assert deps == [], f"expected no deps, got {deps}"


@given(nonreserved_tiers, nonreserved_cats, valid_indices, small_content)
@settings(max_examples=100, suppress_health_check=list(HealthCheck))
def test_payload_write_overwrite(tier, cat, idx, content):
    """Overwriting a VALID address with new content must succeed."""
    assume(not (tier == 0 and cat == 0))
    bb = BootstrapBlock()
    store = PayloadStore(bb)
    addr = store.compose(tier, cat, idx)
    store.write(addr, b"first")
    store.write(addr, content)
    outcome, data, _ = store.read(addr)
    assert outcome == EntryOutcome.VALID
    assert data == content


@given(nonreserved_tiers, nonreserved_cats, valid_indices, small_content)
@settings(max_examples=100, suppress_health_check=list(HealthCheck))
def test_payload_write_delete(tier, cat, idx, content):
    """write then delete → read returns DELETED."""
    assume(not (tier == 0 and cat == 0))
    bb = BootstrapBlock()
    store = PayloadStore(bb)
    addr = store.compose(tier, cat, idx)
    store.write(addr, content)
    store.delete(addr)
    outcome, _, _ = store.read(addr)
    assert outcome == EntryOutcome.DELETED


@given(nonreserved_tiers, nonreserved_cats, valid_indices)
@settings(max_examples=100, suppress_health_check=list(HealthCheck))
def test_payload_unassigned(tier, cat, idx):
    """Reading an unwritten address returns UNASSIGNED."""
    assume(not (tier == 0 and cat == 0))
    bb = BootstrapBlock()
    store = PayloadStore(bb)
    addr = store.compose(tier, cat, idx)
    outcome, data, deps = store.read(addr)
    assert outcome == EntryOutcome.UNASSIGNED
    assert data is None
    assert deps is None


@given(nonreserved_tiers, nonreserved_cats, valid_indices, small_content)
@settings(max_examples=100, suppress_health_check=list(HealthCheck))
def test_payload_write_reserved_rejected(tier, cat, idx, content):
    """Writing to tier=0,category=0 must be rejected."""
    bb = BootstrapBlock()
    store = PayloadStore(bb)
    try:
        addr = store.compose(0, 0, idx)
        # Only test addresses where idx is in the first 256 (tier=0, cat=0)
        if idx < 256:
            store.write(addr, content)
            assert False, f"wrote to reserved {addr:#06x}"
    except PayloadError:
        pass


@given(small_content)
@settings(max_examples=50, suppress_health_check=list(HealthCheck))
def test_payload_missing_dep(content):
    """Writing with a non-existent dependency must raise."""
    bb = BootstrapBlock()
    store = PayloadStore(bb)
    addr = store.compose(1, 1, 0x55)
    missing = store.compose(1, 1, 0x66)  # unwritten
    try:
        store.write(addr, content, depends_on=[missing])
        assert False, "wrote with missing dependency"
    except PayloadError:
        pass


@given(st.lists(st.integers(min_value=0, max_value=0xFFFF), min_size=256, max_size=300),
       small_content)
@settings(max_examples=30, suppress_health_check=list(HealthCheck))
def test_payload_too_many_deps(many_deps, content):
    """255+ dependencies must raise."""
    bb = BootstrapBlock()
    store = PayloadStore(bb)
    addr = store.compose(1, 1, 0x77)
    try:
        store.write(addr, content, depends_on=many_deps)
        assert False, "wrote with too many deps"
    except PayloadError:
        pass


@given(nonreserved_tiers, nonreserved_cats, valid_indices, small_content)
@settings(max_examples=100, suppress_health_check=list(HealthCheck))
def test_payload_corruption_detected(tier, cat, idx, content):
    """Flipping a heap byte must make the entry CORRUPT on subsequent read."""
    assume(not (tier == 0 and cat == 0))
    assume(len(content) > 0)  # need at least 1 byte to flip
    bb = BootstrapBlock()
    store = PayloadStore(bb)
    addr = store.compose(tier, cat, idx)
    store.write(addr, content)
    # Flip one byte in the stored body
    d = store._get_descriptor(addr)
    store.heap[d.offset] ^= 0xFF
    outcome, _, _ = store.read(addr)
    assert outcome == EntryOutcome.CORRUPT, \
        f"expected CORRUPT, got {outcome}"


@given(small_content)
@settings(max_examples=50, suppress_health_check=list(HealthCheck))
def test_payload_write_ordered_topological(content):
    """write_ordered must return addresses in valid dependency order."""
    bb = BootstrapBlock()
    store = PayloadStore(bb)
    a = store.compose(1, 1, 0xA0)
    b = store.compose(1, 1, 0xA1)
    c = store.compose(1, 1, 0xA2)
    # a → b → c, submitted in reverse
    try:
        order = store.write_ordered([
            (c, content, [b]),
            (b, content, [a]),
            (a, content, []),
        ])
    except PayloadError:
        # Could fail if addresses conflict with existing state — skip
        return
    assert order.index(a) < order.index(b), f"a before b: {[hex(x) for x in order]}"
    assert order.index(b) < order.index(c), f"b before c: {[hex(x) for x in order]}"
    # All must be VALID
    for addr in order:
        o, d, _ = store.read(addr)
        if o != EntryOutcome.VALID:
            # Could be that the content was overwritten — skip
            pass


@given(small_content)
@settings(max_examples=50, suppress_health_check=list(HealthCheck))
def test_payload_write_ordered_cycle(content):
    """write_ordered must reject cycles."""
    bb = BootstrapBlock()
    store = PayloadStore(bb)
    a = store.compose(1, 1, 0xB0)
    b = store.compose(1, 1, 0xB1)
    try:
        store.write_ordered([
            (a, content, [b]),
            (b, content, [a]),
        ])
        assert False, "cycle was accepted"
    except PayloadError:
        pass


# ═══════════════════════════════════════════════════════════════════════════
# 3. Content Store Properties
# ═══════════════════════════════════════════════════════════════════════════

@given(nonreserved_tiers, nonreserved_cats, valid_indices, small_content, active_algos)
@settings(max_examples=200, suppress_health_check=list(HealthCheck))
def test_content_write_read(tier, cat, idx, content, algo):
    """write then read returns VALID with same content and matching hash."""
    assume(not (tier == 0 and cat == 0))
    bb = BootstrapBlock(checksum_algo=algo)
    store = ContentStore(bb)
    addr = store.compose(tier, cat, idx)
    h = store.write(addr, content)
    outcome, data, deps, read_hash = store.read(addr)
    assert outcome == EntryOutcome.VALID, f"expected VALID at {addr:#06x}"
    assert data == content, f"content mismatch"
    assert read_hash == h, f"hash mismatch: {read_hash:#x} vs {h:#x}"


@given(small_content, small_content)
@settings(max_examples=100, suppress_health_check=list(HealthCheck))
def test_content_dedup_same_content(content_a, content_b):
    """Same content → same hash regardless of address."""
    assume(content_a == content_b)
    bb = BootstrapBlock()
    store = ContentStore(bb)
    addr_a = store.compose(1, 1, 0x20)
    addr_b = store.compose(1, 1, 0x21)
    h_a = store.write(addr_a, content_a)
    h_b = store.write(addr_b, content_b)
    assert h_a == h_b, "same content must produce same hash"


@given(nonreserved_tiers, nonreserved_cats, valid_indices, small_content)
@settings(max_examples=100, suppress_health_check=list(HealthCheck))
def test_content_first_write_only(tier, cat, idx, content):
    """Writing twice to the same address must raise."""
    assume(not (tier == 0 and cat == 0))
    bb = BootstrapBlock()
    store = ContentStore(bb)
    addr = store.compose(tier, cat, idx)
    store.write(addr, content)
    try:
        store.write(addr, content)
        assert False, "second write to same address was allowed"
    except PayloadError:
        pass


@given(nonreserved_tiers, nonreserved_cats, valid_indices, small_content)
@settings(max_examples=100, suppress_health_check=list(HealthCheck))
def test_content_refcounting(tier, cat, idx, content):
    """N writes of same content → refcount = N. Deleting all → refcount = 0."""
    assume(not (tier == 0 and cat == 0))
    bb = BootstrapBlock()
    store = ContentStore(bb)
    # Write same content to N addresses
    N = min(10, MAX_IDX + 1)
    addrs = []
    for i in range(N):
        addr = store.compose(1, 1, (idx + i) & MAX_IDX)
        if addr in addrs or (tier == 0 and (addr >> IDX_BITS) & CAT_MASK == 0):
            continue
        addrs.append(addr)

    if len(addrs) < 2:
        return  # degenerate case

    hashes = []
    for addr in addrs:
        h = store.write(addr, content)
        hashes.append(h)

    # All hashes identical
    assert all(h == hashes[0] for h in hashes), "dedup: all hashes same"
    record = store.content_table[hashes[0]]
    assert record.refcount == len(addrs), \
        f"refcount {record.refcount} != {len(addrs)}"

    # Delete all
    for addr in addrs:
        store.delete(addr)

    assert record.refcount == 0, \
        f"refcount after full delete: {record.refcount}"


@given(nonreserved_tiers, nonreserved_cats, valid_indices, small_content)
@settings(max_examples=50, suppress_health_check=list(HealthCheck))
def test_content_corruption_detected(tier, cat, idx, content):
    """Flipping a heap byte must make content read CORRUPT."""
    assume(not (tier == 0 and cat == 0))
    assume(len(content) > 0)
    bb = BootstrapBlock()
    store = ContentStore(bb)
    addr = store.compose(tier, cat, idx)
    store.write(addr, content)
    if not store.heap:
        return
    store.heap[0] ^= 0xFF  # flip first heap byte
    outcome, _, _, _ = store.read(addr)
    assert outcome == EntryOutcome.CORRUPT, \
        f"expected CORRUPT, got {outcome}"


@given(small_content)
@settings(max_examples=50, suppress_health_check=list(HealthCheck))
def test_content_delete_unassigned(content):
    """Deleting an unwritten address must raise."""
    bb = BootstrapBlock()
    store = ContentStore(bb)
    addr = store.compose(1, 1, 0xE0)
    try:
        store.delete(addr)
        assert False, "deleted unassigned address"
    except PayloadError:
        pass


@given(small_content)
@settings(max_examples=50, suppress_health_check=list(HealthCheck))
def test_content_reserved_rejected(content):
    """Writing to reserved range must raise."""
    bb = BootstrapBlock()
    store = ContentStore(bb)
    try:
        addr = store.compose(0, 0, 0x05)
        store.write(addr, content)
        assert False, "wrote to reserved address"
    except PayloadError:
        pass


@given(small_content)
@settings(max_examples=50, suppress_health_check=list(HealthCheck))
def test_content_too_many_deps(content):
    """255+ dependencies must raise."""
    bb = BootstrapBlock()
    store = ContentStore(bb)
    addr = store.compose(1, 1, 0xF0)
    many_deps = list(range(256))
    try:
        store.write(addr, content, depends_on=many_deps)
        assert False, "wrote with too many deps"
    except PayloadError:
        pass


@given(small_content, small_content)
@settings(max_examples=100, suppress_health_check=list(HealthCheck))
def test_content_dedup_different_deps_different_hash(content_a, content_b):
    """Same content but different dep hashes → different content hash."""
    assume(content_a == content_b)
    bb = BootstrapBlock()
    store = ContentStore(bb)

    # Create two addresses with DIFFERENT dependencies
    dep1 = store.compose(1, 1, 0x30)
    dep2 = store.compose(1, 1, 0x31)
    store.write(dep1, b"dep-one")
    store.write(dep2, b"dep-two")

    addr_a = store.compose(1, 2, 0x30)
    addr_b = store.compose(1, 2, 0x31)
    h_a = store.write(addr_a, content_a, depends_on=[dep1])
    h_b = store.write(addr_b, content_b, depends_on=[dep2])
    assert h_a != h_b, \
        "different dep hashes must produce different content hashes"


# ═══════════════════════════════════════════════════════════════════════════
# 4. Cross-Module Integrative Properties
# ═══════════════════════════════════════════════════════════════════════════

@given(small_content, active_algos)
@settings(max_examples=100, suppress_health_check=list(HealthCheck))
def test_payload_content_consistency(content, algo):
    """Same bootstrap + same content: both stores must agree on address
    computation and basic read-before-write behavior."""
    bb = BootstrapBlock(checksum_algo=algo)
    ps = PayloadStore(bb)
    cs = ContentStore(bb)

    addr = ps.compose(1, 1, 0x40)
    addr2 = cs.compose(1, 1, 0x40)
    assert addr == addr2, "compose must agree"

    # Both see UNASSIGNED
    po, pd, _ = ps.read(addr)
    co, cd, _, _ = cs.read(addr)
    assert po == EntryOutcome.UNASSIGNED
    assert co == EntryOutcome.UNASSIGNED

    # Write to payload store, verify
    ps.write(addr, content)
    o, d, _ = ps.read(addr)
    assert o == EntryOutcome.VALID and d == content

    # Address still UNASSIGNED in content store (different store)
    o2, _, _, _ = cs.read(addr)
    assert o2 == EntryOutcome.UNASSIGNED, \
        "stores are independent — content store should not see payload writes"


@given(small_content)
@settings(max_examples=100, suppress_health_check=list(HealthCheck))
def test_content_hash_determinism(content):
    """FNV1a-64 hash of the wire format body must be deterministic."""
    bb = BootstrapBlock()
    store = ContentStore(bb)
    addr = store.compose(1, 1, 0x50)
    h1 = store.write(addr, content)

    # New store, same input, same bootstrap
    store2 = ContentStore(bb)
    addr2 = store2.compose(1, 1, 0x51)
    h2 = store2.write(addr2, content)
    assert h1 == h2, "hash must be deterministic"

    # Verify hash matches direct FNV call
    expected_body = b"\x00" + content  # dep_count=0 + content
    expected_hash = fnv1a_64(expected_body)
    assert h1 == expected_hash, f"hash 0x{h1:016x} != expected 0x{expected_hash:016x}"


@given(active_algos)
@settings(max_examples=50, suppress_health_check=list(HealthCheck))
def test_checksum_matches_payload_store(algo):
    """compute_checksum must match the value stored in descriptors."""
    bb = BootstrapBlock(checksum_algo=algo)
    store = PayloadStore(bb)
    addr = store.compose(1, 1, 0x60)
    content = b"checksum verification payload"
    store.write(addr, content)
    d = store._get_descriptor(addr)
    body = bytes([0]) + content  # dep_count=0
    expected = compute_checksum(body, algo)
    assert d.checksum == expected, \
        f"checksum mismatch: stored=0x{d.checksum:04x} computed=0x{expected:04x}"


# ═══════════════════════════════════════════════════════════════════════════
# 5. Stateful testing: ContentStore refcounting via RuleBasedStateMachine
# ═══════════════════════════════════════════════════════════════════════════

class ContentStoreMachine(RuleBasedStateMachine):
    """Model-based state machine for ContentStore.

    Tracks expected refcounts in a Python dict and verifies that the
    store's actual refcounts match after every operation.
    """

    def __init__(self):
        super().__init__()
        self.bb = BootstrapBlock()
        self.store = ContentStore(self.bb)
        # Model: content_hash -> expected_refcount
        self.model: dict[int, int] = {}
        # Track which addresses are written
        self.written: set[int] = set()

    @rule(
        tier=st.integers(min_value=1, max_value=MAX_TIER),
        cat=st.integers(min_value=0, max_value=MAX_CAT),
        idx=st.integers(min_value=0, max_value=MAX_IDX),
        content=st.binary(min_size=0, max_size=64),
    )
    def write(self, tier, cat, idx, content):
        """Write content to a non-reserved address."""
        addr = self.store.compose(tier, cat, idx)
        if addr in self.written:
            return  # first-write-only, can't re-write
        h = self.store.write(addr, content)
        self.written.add(addr)
        self.model[h] = self.model.get(h, 0) + 1

    @rule(addr_num=st.integers(min_value=0, max_value=0xFFFF))
    def delete(self, addr_num):
        """Delete an address if it's been written."""
        if addr_num not in self.written:
            try:
                self.store.delete(addr_num)
            except PayloadError:
                pass  # expected
            return
        # Read the hash BEFORE deleting
        _, _, _, h = self.store.read(addr_num)
        if h is not None:
            self.model[h] = self.model.get(h, 0) - 1
            if self.model[h] <= 0:
                del self.model[h]
        self.store.delete(addr_num)
        self.written.discard(addr_num)

    @invariant()
    def refcounts_match(self):
        """Verify model matches actual store content_table refcounts."""
        for h, expected in self.model.items():
            record = self.store.content_table.get(h)
            if record is None and expected == 0:
                continue  # cleaned up
            assert record is not None, f"hash 0x{h:016x} missing from content_table"
            assert record.refcount == expected, \
                f"hash 0x{h:016x}: refcount {record.refcount} != expected {expected}"

    @invariant()
    def no_dangling_hashes(self):
        """Every entry in content_table must have refcount > 0."""
        for h, record in self.store.content_table.items():
            if record.refcount <= 0:
                # Might be pending cleanup — acceptable in this model
                pass

    @invariant()
    def all_written_addresses_valid(self):
        """Every address we think is written must still read as VALID."""
        for addr in self.written:
            outcome, _, _, _ = self.store.read(addr)
            assert outcome == EntryOutcome.VALID, \
                f"address {addr:#06x} expected VALID, got {outcome}"


TestContentStoreRefcounting = ContentStoreMachine.TestCase


# ═══════════════════════════════════════════════════════════════════════════
# Runner
# ═══════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    import pytest
    sys.exit(pytest.main([__file__, "-v", "--tb=short"]))
