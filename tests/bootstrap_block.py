"""
bootstrap_block.py — reference implementation, 65535-point framework

Layer A: preamble, 12 raw bytes, fixed forever, read before any addressing
         scheme exists at all.
Layer B: bootstrap fields, 255 bytes, slot-addressed within category 0 /
         tier 0 (slot width = 1 byte; multi-byte fields span consecutive
         slot numbers, so address <-> byte-offset stays a simple additive
         relationship).

Total block size: 267 bytes, always — regardless of CHECKSUM_ALGO_ID.
That field describes checksums for *content* elsewhere in the address
space; this block's own integrity byte is fixed at sum8, because a
self-describing header cannot make its own length conditional on a field
that lives inside itself.

Python 3.9+, standard library only.
"""

from __future__ import annotations
import struct
from dataclasses import dataclass, field
from enum import IntEnum
from typing import Optional, Tuple


MAGIC = b"DOTM"
PREAMBLE_SIZE = 12
STRUCTURED_SIZE = 255                          # slots 0x01-0xFF, 1 byte each
BLOCK_SIZE = PREAMBLE_SIZE + STRUCTURED_SIZE   # 267
RESERVED_SIZE = 244                            # 255 - 10 fixed fields - 1 checksum slot


class ChecksumAlgo(IntEnum):
    NONE = 0
    SUM8 = 1
    CRC16 = 2
    SHA256_TRUNC = 3


class ProvenanceScheme(IntEnum):
    NONE = 0
    HUMAN_CURATED = 1
    AGENT_SIGNED = 2
    CONTENT_HASH = 3


class ReadOutcome(IntEnum):
    VALID = 0
    UNASSIGNED = 1
    DELETED = 2
    # CORRUPT is deliberately absent here: the bootstrap block carries ONE
    # checksum for the whole 267 bytes, not one per slot, so a damaged slot
    # invalidates the whole block at parse() time rather than being caught
    # per-read. Per-slot CORRUPT is a payload-codec feature for content
    # entries that carry their own checksum (governed by checksum_algo).


class BootstrapError(ValueError):
    """Raised on any structural or integrity violation."""


@dataclass(frozen=True)
class BootstrapBlock:
    fw_ver_major: int = 1
    fw_ver_minor: int = 0
    address_width: int = 16
    tier_bits: int = 4
    category_bits: int = 4
    index_bits: int = 8
    reserved_preamble: int = 0

    schema_version: Tuple[int, int] = (1, 0)
    key_version: Tuple[int, int] = (1, 0)
    checksum_algo: ChecksumAlgo = ChecksumAlgo.SUM8
    category_count: int = 1
    tier_count: int = 1
    headroom_ratio: int = 10
    tombstone_sentinel: int = 0xFF
    provenance_scheme: ProvenanceScheme = ProvenanceScheme.NONE
    reserved_slots: bytes = field(default_factory=lambda: b"\x00" * RESERVED_SIZE)

    def __post_init__(self):
        if self.tier_bits + self.category_bits + self.index_bits != self.address_width:
            raise BootstrapError(
                f"tier_bits({self.tier_bits}) + category_bits({self.category_bits}) + "
                f"index_bits({self.index_bits}) != address_width({self.address_width})"
            )
        if self.address_width != 16:
            raise BootstrapError("only address_width=16 is supported in this version")
        if len(self.reserved_slots) != RESERVED_SIZE:
            raise BootstrapError(
                f"reserved_slots must be {RESERVED_SIZE} bytes, got {len(self.reserved_slots)}"
            )
        if not (0 <= self.headroom_ratio <= 100):
            raise BootstrapError(f"headroom_ratio={self.headroom_ratio} out of range 0..100")

    # ---- internal byte builders -----------------------------------------

    def _preamble_body(self) -> bytes:
        """Bytes 0-10 (11 bytes): everything before the preamble checksum."""
        return struct.pack(
            ">4sBBBBBBB",
            MAGIC, self.fw_ver_major, self.fw_ver_minor,
            self.address_width, self.tier_bits, self.category_bits,
            self.index_bits, self.reserved_preamble,
        )

    def _preamble_checksum(self) -> int:
        return sum(self._preamble_body()) % 256

    def _structured_body(self) -> bytes:
        """Bytes 12-265 (254 bytes): 10 fixed fields + 244 reserved.
        Excludes the block checksum byte (266)."""
        schema = (self.schema_version[0] << 8) | self.schema_version[1]
        key = (self.key_version[0] << 8) | self.key_version[1]
        fixed = struct.pack(
            ">HHBBBBBB",
            schema, key, int(self.checksum_algo),
            self.category_count, self.tier_count, self.headroom_ratio,
            self.tombstone_sentinel, int(self.provenance_scheme),
        )
        return fixed + self.reserved_slots

    def _block_checksum(self) -> int:
        body = self._preamble_body() + bytes([self._preamble_checksum()]) + self._structured_body()
        return sum(body) % 256

    # ---- public API --------------------------------------------------------

    def to_bytes(self) -> bytes:
        block = (
            self._preamble_body()
            + bytes([self._preamble_checksum()])
            + self._structured_body()
            + bytes([self._block_checksum()])
        )
        assert len(block) == BLOCK_SIZE, f"internal error: built {len(block)}, expected {BLOCK_SIZE}"
        return block

    @classmethod
    def parse(cls, data: bytes) -> "BootstrapBlock":
        if len(data) != BLOCK_SIZE:
            raise BootstrapError(f"expected {BLOCK_SIZE} bytes, got {len(data)}")
        if data[0:4] != MAGIC:
            raise BootstrapError(f"bad magic: expected {MAGIC!r}, got {data[0:4]!r}")

        computed_preamble_cs = sum(data[0:11]) % 256
        if data[11] != computed_preamble_cs:
            raise BootstrapError(
                f"preamble checksum mismatch: stored=0x{data[11]:02x} computed=0x{computed_preamble_cs:02x}"
            )

        computed_block_cs = sum(data[0:266]) % 256
        if data[266] != computed_block_cs:
            raise BootstrapError(
                f"block checksum mismatch: stored=0x{data[266]:02x} computed=0x{computed_block_cs:02x}"
            )

        schema, key, algo, cat_c, tier_c, headroom, tomb, prov = struct.unpack(">HHBBBBBB", data[12:22])

        return cls(
            fw_ver_major=data[4], fw_ver_minor=data[5], address_width=data[6],
            tier_bits=data[7], category_bits=data[8], index_bits=data[9],
            reserved_preamble=data[10],
            schema_version=(schema >> 8, schema & 0xFF),
            key_version=(key >> 8, key & 0xFF),
            checksum_algo=ChecksumAlgo(algo),
            category_count=cat_c, tier_count=tier_c, headroom_ratio=headroom,
            tombstone_sentinel=tomb, provenance_scheme=ProvenanceScheme(prov),
            reserved_slots=data[22:266],
        )

    def decompose_address(self, address: int) -> Tuple[int, int, int]:
        """Split a full address into (tier, category, index) using THIS
        block's own declared bit widths — never hardcoded, always read from
        the preamble that was actually parsed."""
        if not (0 <= address <= (1 << self.address_width) - 1):
            raise BootstrapError(f"address {address} out of range for {self.address_width}-bit space")
        index = address & ((1 << self.index_bits) - 1)
        category = (address >> self.index_bits) & ((1 << self.category_bits) - 1)
        tier = (address >> (self.index_bits + self.category_bits)) & ((1 << self.tier_bits) - 1)
        return tier, category, index

    def read_slot(self, store: bytes, slot: int) -> Tuple[ReadOutcome, Optional[int]]:
        """Three-way read for one byte within category 0 / tier 0 (the
        bootstrap's own slot table)."""
        if not (0 <= slot <= 0xFF):
            raise BootstrapError(f"slot {slot} out of range 0..255")
        if slot == 0x00:
            return ReadOutcome.VALID, 0  # slot 0 is the preamble's own address, always present
        offset = PREAMBLE_SIZE + (slot - 1)
        if offset >= len(store):
            return ReadOutcome.UNASSIGNED, None
        value = store[offset]
        if slot != 0xFF and value == self.tombstone_sentinel:
            return ReadOutcome.DELETED, None
        if slot != 0xFF and value == 0x00:
            return ReadOutcome.UNASSIGNED, None
        return ReadOutcome.VALID, value


# ──────────────────────────────────────────────────────────────
# Self-test / demo
# ──────────────────────────────────────────────────────────────

def _demo() -> None:
    block = BootstrapBlock()
    data = block.to_bytes()
    assert len(data) == BLOCK_SIZE

    parsed = BootstrapBlock.parse(data)
    assert parsed.to_bytes() == data, "round-trip failed"
    assert parsed == block, "field-for-field equality failed"

    print("round-trip OK —", len(data), "bytes")
    print("preamble checksum: 0x%02x" % block._preamble_checksum())
    print("block checksum:    0x%02x" % block._block_checksum())
    print("hex:", data.hex())

    # tamper detection — flip a byte inside the "reserved" region and
    # confirm reserved does NOT mean unprotected
    tampered = bytearray(data)
    tampered[50] ^= 0xFF
    try:
        BootstrapBlock.parse(bytes(tampered))
        print("TAMPER TEST FAILED: corrupted block parsed without error")
    except BootstrapError as e:
        print("tamper correctly rejected:", e)

    # address decomposition, using widths read from the block itself
    for addr in (0x0000, 0x0001, 0x1234, 0xFFFF):
        t, c, i = block.decompose_address(addr)
        print(f"address 0x{addr:04x} -> tier={t} category={c} index={i}")

    # three-way read demo against a mock store
    store = bytearray(PREAMBLE_SIZE + 256)
    store[0:BLOCK_SIZE] = data
    store[PREAMBLE_SIZE + 0x10 - 1] = 0xFF  # slot 0x10 tombstoned
    for slot in (0x01, 0x10, 0x50):
        outcome, val = block.read_slot(bytes(store), slot)
        print(f"slot 0x{slot:02x}: {outcome.name}" + (f" = 0x{val:02x}" if val is not None else ""))


if __name__ == "__main__":
    _demo()
