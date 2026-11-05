"""
test_bootstrap.py — exhaustive unit tests for bootstrap_block.py
═══════════════════════════════════════════════════════════════════════════════

Tests every public method of BootstrapBlock, every edge case of read_slot(),
and all validation in __post_init__ and parse().
═══════════════════════════════════════════════════════════════════════════════
"""

import sys, os
sys.path.insert(0, os.path.dirname(__file__))

import pytest
from bootstrap_block import (
    BootstrapBlock, BootstrapError, ChecksumAlgo, ProvenanceScheme, ReadOutcome,
    BLOCK_SIZE, PREAMBLE_SIZE, RESERVED_SIZE, MAGIC,
)


# ═══════════════════════════════════════════════════════════════════════════
# 1. Block Creation & Validation
# ═══════════════════════════════════════════════════════════════════════════

def test_default_block_creation():
    """Default BootstrapBlock should have expected field values."""
    b = BootstrapBlock()
    assert b.fw_ver_major == 1, f"fw_ver_major: expected 1, got {b.fw_ver_major}"
    assert b.fw_ver_minor == 0, f"fw_ver_minor: expected 0, got {b.fw_ver_minor}"
    assert b.address_width == 16, f"address_width: expected 16, got {b.address_width}"
    assert b.tier_bits == 4, f"tier_bits: expected 4, got {b.tier_bits}"
    assert b.category_bits == 4, f"category_bits: expected 4, got {b.category_bits}"
    assert b.index_bits == 8, f"index_bits: expected 8, got {b.index_bits}"
    assert b.checksum_algo == ChecksumAlgo.SUM8, f"checksum_algo: expected SUM8, got {b.checksum_algo}"
    assert len(b.reserved_slots) == RESERVED_SIZE, f"reserved_slots length: expected {RESERVED_SIZE}, got {len(b.reserved_slots)}"


def test_validation_address_width():
    """Only address_width=16 is supported."""
    with pytest.raises(BootstrapError):
        BootstrapBlock(address_width=8)
    with pytest.raises(BootstrapError):
        BootstrapBlock(address_width=32)


def test_validation_bit_sum():
    """tier_bits + category_bits + index_bits must equal address_width."""
    with pytest.raises(BootstrapError):
        BootstrapBlock(tier_bits=8, category_bits=8, index_bits=8)
    with pytest.raises(BootstrapError):
        BootstrapBlock(tier_bits=2, category_bits=2, index_bits=8)


def test_validation_reserved_slots_len():
    """reserved_slots must be exactly RESERVED_SIZE (244) bytes."""
    with pytest.raises(BootstrapError):
        BootstrapBlock(reserved_slots=b"\x00" * 100)
    with pytest.raises(BootstrapError):
        BootstrapBlock(reserved_slots=b"\x00" * 300)


def test_validation_headroom_ratio():
    """headroom_ratio must be 0..100."""
    with pytest.raises(BootstrapError):
        BootstrapBlock(headroom_ratio=-1)
    with pytest.raises(BootstrapError):
        BootstrapBlock(headroom_ratio=101)
    # Edge: 0 and 100 are valid
    b0 = BootstrapBlock(headroom_ratio=0)
    b100 = BootstrapBlock(headroom_ratio=100)
    assert b0.headroom_ratio == 0, f"headroom_ratio=0: expected 0, got {b0.headroom_ratio}"
    assert b100.headroom_ratio == 100, f"headroom_ratio=100: expected 100, got {b100.headroom_ratio}"


# ═══════════════════════════════════════════════════════════════════════════
# 2. Serialization Round-Trips
# ═══════════════════════════════════════════════════════════════════════════

def test_serialization_roundtrip():
    """to_bytes() -> parse() should recover the original block."""
    b1 = BootstrapBlock()
    data = b1.to_bytes()
    assert len(data) == BLOCK_SIZE, f"block size should be {BLOCK_SIZE}, got {len(data)}"
    b2 = BootstrapBlock.parse(data)
    assert b1 == b2, "field-for-field equality after round-trip"
    assert b1.to_bytes() == b2.to_bytes(), "byte identity after round-trip"


def test_serialization_non_default():
    """Non-default fields should survive serialization."""
    b = BootstrapBlock(
        fw_ver_major=2, fw_ver_minor=3,
        checksum_algo=ChecksumAlgo.CRC16,
        category_count=4, tier_count=2,
        headroom_ratio=25, tombstone_sentinel=0xAA,
        provenance_scheme=ProvenanceScheme.AGENT_SIGNED,
    )
    data = b.to_bytes()
    parsed = BootstrapBlock.parse(data)
    assert parsed.fw_ver_major == 2, f"fw_ver_major: expected 2, got {parsed.fw_ver_major}"
    assert parsed.fw_ver_minor == 3, f"fw_ver_minor: expected 3, got {parsed.fw_ver_minor}"
    assert parsed.checksum_algo == ChecksumAlgo.CRC16, f"checksum_algo: expected CRC16, got {parsed.checksum_algo}"
    assert parsed.category_count == 4, f"category_count: expected 4, got {parsed.category_count}"
    assert parsed.tier_count == 2, f"tier_count: expected 2, got {parsed.tier_count}"
    assert parsed.headroom_ratio == 25, f"headroom_ratio: expected 25, got {parsed.headroom_ratio}"
    assert parsed.tombstone_sentinel == 0xAA, f"tombstone_sentinel: expected 0xAA, got {parsed.tombstone_sentinel}"
    assert parsed.provenance_scheme == ProvenanceScheme.AGENT_SIGNED, f"provenance: expected AGENT_SIGNED, got {parsed.provenance_scheme}"
    assert b == parsed, "full field equality"


def test_magic_bytes():
    """The first 4 bytes must always be 'DOTM'."""
    b = BootstrapBlock()
    data = b.to_bytes()
    assert data[:4] == MAGIC, f"magic bytes: expected {MAGIC!r}, got {data[:4]!r}"


def test_preamble_checksum_field():
    """Byte 11 must be the preamble checksum (sum of bytes 0-10 % 256)."""
    b = BootstrapBlock()
    data = b.to_bytes()
    computed = sum(data[0:11]) % 256
    assert data[11] == computed, f"preamble checksum at byte 11: expected {computed}, got {data[11]}"


def test_block_checksum_field():
    """Byte 266 must be the block checksum (sum of bytes 0-265 % 256)."""
    b = BootstrapBlock()
    data = b.to_bytes()
    computed = sum(data[0:266]) % 256
    assert data[266] == computed, f"block checksum at byte 266: expected {computed}, got {data[266]}"


# ═══════════════════════════════════════════════════════════════════════════
# 3. Parse Validation (error detection)
# ═══════════════════════════════════════════════════════════════════════════

def test_parse_wrong_size():
    """Parsing a block of wrong size should raise."""
    with pytest.raises(BootstrapError):
        BootstrapBlock.parse(b"")
    with pytest.raises(BootstrapError):
        BootstrapBlock.parse(b"\x00" * 100)
    with pytest.raises(BootstrapError):
        BootstrapBlock.parse(b"\x00" * 400)


def test_parse_bad_magic():
    """Parsing a block with wrong magic should raise."""
    data = bytearray(BLOCK_SIZE)
    data[:4] = b"BOGUS"
    with pytest.raises(BootstrapError):
        BootstrapBlock.parse(bytes(data))


def test_parse_bad_preamble_checksum():
    """Parsing a block with a corrupted preamble checksum should raise."""
    b = BootstrapBlock()
    data = bytearray(b.to_bytes())
    data[11] ^= 0xFF  # corrupt preamble checksum
    with pytest.raises(BootstrapError):
        BootstrapBlock.parse(bytes(data))


def test_parse_bad_block_checksum():
    """Parsing a block with a corrupted block checksum should raise."""
    b = BootstrapBlock()
    data = bytearray(b.to_bytes())
    data[266] ^= 0xFF  # corrupt block checksum
    with pytest.raises(BootstrapError):
        BootstrapBlock.parse(bytes(data))


# ═══════════════════════════════════════════════════════════════════════════
# 4. Slot Read Three-Way Semantics
# ═══════════════════════════════════════════════════════════════════════════

def _make_store_with_slot(block_bytes: bytes, slot_num: int, value: int) -> bytes:
    """Create a mock store with a specific slot value set."""
    size = PREAMBLE_SIZE + 256  # enough for all slots
    store = bytearray(size)
    store[:BLOCK_SIZE] = block_bytes
    store[PREAMBLE_SIZE + slot_num - 1] = value
    return bytes(store)


def test_read_slot_zero():
    """Slot 0 should always return VALID with value 0."""
    b = BootstrapBlock()
    data = b.to_bytes()
    store = data + b"\x00" * 256  # extend to cover slot reads
    outcome, val = b.read_slot(store, 0)
    assert outcome == ReadOutcome.VALID, f"slot 0 outcome: expected VALID, got {outcome}"
    assert val == 0, f"slot 0 value: expected 0, got {val}"


def test_read_slot_valid():
    """A slot with a non-zero, non-tombstone value should be VALID."""
    b = BootstrapBlock(tombstone_sentinel=0xFF)
    data = b.to_bytes()
    store = _make_store_with_slot(data, 0x42, 0x7F)
    outcome, val = b.read_slot(store, 0x42)
    assert outcome == ReadOutcome.VALID, f"slot 0x42 outcome: expected VALID, got {outcome}"
    assert val == 0x7F, f"slot 0x42 value: expected 0x7F, got {val}"


def test_read_slot_unassigned_zero():
    """A slot with value 0x00 should be UNASSIGNED (unless slot 255)."""
    b = BootstrapBlock()
    data = b.to_bytes()
    store = _make_store_with_slot(data, 0x30, 0x00)
    outcome, val = b.read_slot(store, 0x30)
    assert outcome == ReadOutcome.UNASSIGNED, f"zero slot outcome: expected UNASSIGNED, got {outcome}"
    assert val is None, f"zero slot value should be None, got {val!r}"


def test_read_slot_tombstone():
    """A slot with value == tombstone_sentinel should be DELETED."""
    b = BootstrapBlock(tombstone_sentinel=0xFF)
    data = b.to_bytes()
    # tombstone value 0xFF
    store = _make_store_with_slot(data, 0x50, 0xFF)
    outcome, val = b.read_slot(store, 0x50)
    assert outcome == ReadOutcome.DELETED, f"tombstone outcome: expected DELETED, got {outcome}"
    assert val is None, f"tombstone value should be None, got {val!r}"


def test_read_slot_out_of_range():
    """Slot >= 256 should raise BootstrapError."""
    b = BootstrapBlock()
    store = b.to_bytes() + b"\x00" * 256
    with pytest.raises(BootstrapError):
        b.read_slot(store, 256)
    with pytest.raises(BootstrapError):
        b.read_slot(store, -1)


def test_read_slot_past_store_end():
    """A slot index past the store's end should be UNASSIGNED."""
    b = BootstrapBlock()
    truncated = b.to_bytes()[:20]  # only 20 bytes
    outcome, val = b.read_slot(truncated, 0x10)
    # offset for slot 0x10 = 12 + 15 = 27, which is >= 20 -> UNASSIGNED
    assert outcome == ReadOutcome.UNASSIGNED, f"truncated store outcome: expected UNASSIGNED, got {outcome}"


def test_read_slot_255_special():
    """Slot 255 (0xFF) is the checksum slot — 0x00 is valid there."""
    b = BootstrapBlock()
    data = b.to_bytes()
    store = _make_store_with_slot(data, 0xFF, 0x00)
    outcome, val = b.read_slot(store, 0xFF)
    assert outcome == ReadOutcome.VALID, f"slot 255 should be valid even with 0x00, got {outcome}"


# ═══════════════════════════════════════════════════════════════════════════
# 5. Address Decomposition
# ═══════════════════════════════════════════════════════════════════════════

def test_decompose_address():
    """decompose_address should split addresses correctly with default widths."""
    b = BootstrapBlock()  # tier_bits=4, category_bits=4, index_bits=8
    # Address 0x0000: tier=0, category=0, index=0
    assert b.decompose_address(0x0000) == (0, 0, 0), "addr 0x0000"
    # Address 0x0001: tier=0, category=0, index=1
    assert b.decompose_address(0x0001) == (0, 0, 1), "addr 0x0001"
    # Address 0x0100: tier=0, category=1, index=0  (category at bits 8-11)
    assert b.decompose_address(0x0100) == (0, 1, 0), "addr 0x0100"
    # Address 0x1000: tier=1, category=0, index=0  (tier at bits 12-15)
    assert b.decompose_address(0x1000) == (1, 0, 0), "addr 0x1000"
    # Address 0x1234: tier=1, category=2, index=0x34
    assert b.decompose_address(0x1234) == (1, 2, 0x34), "addr 0x1234"
    # Address 0xFFFF: all bits set
    assert b.decompose_address(0xFFFF) == (0xF, 0xF, 0xFF), "addr 0xFFFF"


def test_decompose_address_out_of_range():
    """Addresses >= 1<<address_width should raise."""
    b = BootstrapBlock()
    with pytest.raises(BootstrapError):
        b.decompose_address(0x10000)
    with pytest.raises(BootstrapError):
        b.decompose_address(-1)


def test_decompose_address_custom_widths():
    """decompose_address must use the block's own bit widths."""
    b = BootstrapBlock(tier_bits=2, category_bits=6, index_bits=8)
    # address_width still must be 16, so 2+6+8 = 16 ✓
    assert b.tier_bits == 2, f"custom tier_bits: expected 2, got {b.tier_bits}"
    assert b.category_bits == 6, f"custom category_bits: expected 6, got {b.category_bits}"
    assert b.index_bits == 8, f"custom index_bits: expected 8, got {b.index_bits}"
    # Address 0x0001: tier=0, category=0, index=1
    assert b.decompose_address(0x0001) == (0, 0, 1), "custom addr 0x0001"
    # Address 0x0100: tier=0, category=1, index=0
    assert b.decompose_address(0x0100) == (0, 1, 0), "custom addr 0x0100"
    # Address 0x4000: with tier_bits=2, tier at bits 14-15
    assert b.decompose_address(0x4000) == (1, 0, 0), "custom addr 0x4000"


# ═══════════════════════════════════════════════════════════════════════════
# 6. Tamper / Integrity
# ═══════════════════════════════════════════════════════════════════════════

def test_tamper_detection_reserved_region():
    """Flipping a bit in the reserved region must fail parse()."""
    b = BootstrapBlock()
    data = bytearray(b.to_bytes())
    data[50] ^= 0xFF  # flip byte in reserved region
    with pytest.raises(BootstrapError):
        BootstrapBlock.parse(bytes(data))


def test_tamper_detection_preamble():
    """Flipping a bit in the preamble must fail parse()."""
    b = BootstrapBlock()
    data = bytearray(b.to_bytes())
    data[4] ^= 0x01  # flip fw_ver_major
    with pytest.raises(BootstrapError):
        BootstrapBlock.parse(bytes(data))


# ═══════════════════════════════════════════════════════════════════════════
# 7. Determinism
# ═══════════════════════════════════════════════════════════════════════════

def test_determinism():
    """Calling to_bytes() twice on the same block must produce identical bytes."""
    b = BootstrapBlock()
    data1 = b.to_bytes()
    data2 = b.to_bytes()
    assert data1 == data2, "deterministic output"


# ═══════════════════════════════════════════════════════════════════════════
# 8. Known Hex Vector (Golden)
# ═══════════════════════════════════════════════════════════════════════════

def test_known_golden_hex():
    """The default block must produce a known hex prefix.

    This locks in the format: if this test ever fails, the binary layout
    has changed — intentionally or not.
    """
    b = BootstrapBlock()
    data = b.to_bytes()
    # Expected prefix from the reference implementation:
    # MAGIC='DOTM'=444F544D, fw_ver_major=1, fw_ver_minor=0, addr_width=16,
    # tier_bits=4, category_bits=4, index_bits=8, reserved_preamble=0
    # → 444F544D 01 00 10 04 04 08 00
    # Then preamble checksum: sum(444F544D01001004040800) % 256
    expected_prefix = "444F544D01001004040800"
    hex_str = data[:11].hex().upper()
    assert hex_str == expected_prefix, f"golden prefix: expected {expected_prefix}, got {hex_str}"


# ═══════════════════════════════════════════════════════════════════════════
# Runner
# ═══════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    pytest.main([__file__])
