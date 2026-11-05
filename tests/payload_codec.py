"""
payload_codec.py — reference implementation, 65535-point framework

Builds directly on bootstrap_block.py. The full store is three parts:

    [ BOOTSTRAP BLOCK  ]  267 bytes, fixed        (tier 0, category 0)
    [ DESCRIPTOR TABLE ]  65536 * 15 bytes, fixed  (one descriptor per address)
    [ HEAP             ]  variable length, append-only

A descriptor is a small fixed record: status, checksum, length, offset.
The actual content — arbitrary length — lives in the heap, pointed to by
offset+length. This is the same two-level indirection every filesystem
uses (inode table + data blocks) and every B-tree-backed database uses
(fixed index + variable heap): it's what lets a fixed 16-bit address space
hold content of any size without either wasting space on padding or
losing O(1) lookup.

Dependency ordering is enforced explicitly, not inferred from tier
numbers: every entry may declare which other addresses it depends on,
and a write is refused until all of them are VALID. Tier numbers are an
organizational convention (advisory), not the correctness mechanism —
the real guarantee comes from the dependency check plus the topological
sort in write_ordered().

Python 3.9+, standard library only.
"""

from __future__ import annotations
import struct
from dataclasses import dataclass
from enum import IntEnum
from typing import Dict, List, Optional, Sequence, Tuple

from bootstrap_block import BootstrapBlock, ChecksumAlgo, BootstrapError


class EntryOutcome(IntEnum):
    VALID = 0
    UNASSIGNED = 1
    DELETED = 2
    CORRUPT = 3          # possible here, unlike the bootstrap's ReadOutcome —
                          # every entry carries its OWN checksum, so a single
                          # damaged entry doesn't take down the whole store.


class PayloadError(ValueError):
    """Raised on any structural, dependency, or integrity violation."""


_STATUS_UNASSIGNED = 0
_STATUS_VALID = 1
_STATUS_DELETED = 2

_DESCRIPTOR_SIZE = 15                     # status(1) + checksum(2) + length(4) + offset(8)
_DESCRIPTOR_FORMAT = ">BHIQ"
_ADDRESS_SPACE = 1 << 16                  # 65536
_DEP_ADDR_FORMAT = ">H"


def _crc16(data: bytes, poly: int = 0x1021, init: int = 0xFFFF) -> int:
    """CRC-16, bit-by-bit. Only needs to agree with itself across languages —
    doesn't need to match a named external standard, just needs the same
    poly/init on both sides, which the Julia mirror uses verbatim."""
    crc = init
    for byte in data:
        crc ^= byte << 8
        for _ in range(8):
            crc = ((crc << 1) ^ poly) & 0xFFFF if (crc & 0x8000) else (crc << 1) & 0xFFFF
    return crc


def compute_checksum(data: bytes, algo: ChecksumAlgo) -> int:
    if algo == ChecksumAlgo.NONE:
        return 0
    if algo == ChecksumAlgo.SUM8:
        return sum(data) % 256
    if algo == ChecksumAlgo.CRC16:
        return _crc16(data)
    if algo == ChecksumAlgo.SHA256_TRUNC:
        # Deliberately unimplemented: Python's hashlib makes this trivial,
        # but the Julia mirror has no SHA in its standard library and this
        # codec has a no-Pkg-dependency rule for Julia. Rather than let the
        # two languages silently diverge on what a given algo ID means,
        # both raise here. Use CRC16 or SUM8.
        raise PayloadError("SHA256_TRUNC is not implemented in this reference build (both languages, on purpose)")
    raise PayloadError(f"unknown checksum algo {algo!r}")


@dataclass
class Descriptor:
    status: int
    checksum: int
    length: int
    offset: int


class Store:
    """The descriptor table + heap for everything outside the bootstrap's
    own reserved range (tier 0, category 0 — addresses 0x0000-0x00FF)."""

    def __init__(self, bootstrap: BootstrapBlock):
        self.bootstrap = bootstrap
        self.descriptors = bytearray(_ADDRESS_SPACE * _DESCRIPTOR_SIZE)
        self.heap = bytearray()

    # ---- addressing, delegated to the bootstrap's own declared widths ----

    def compose(self, tier: int, category: int, index: int) -> int:
        b = self.bootstrap
        if not (0 <= tier < (1 << b.tier_bits)):
            raise PayloadError(f"tier {tier} out of range for {b.tier_bits} tier bits")
        if not (0 <= category < (1 << b.category_bits)):
            raise PayloadError(f"category {category} out of range for {b.category_bits} category bits")
        if not (0 <= index < (1 << b.index_bits)):
            raise PayloadError(f"index {index} out of range for {b.index_bits} index bits")
        return (tier << (b.category_bits + b.index_bits)) | (category << b.index_bits) | index

    # ---- descriptor table i/o ---------------------------------------------

    def _get_descriptor(self, address: int) -> Descriptor:
        off = address * _DESCRIPTOR_SIZE
        status, checksum, length, offset = struct.unpack_from(_DESCRIPTOR_FORMAT, self.descriptors, off)
        return Descriptor(status, checksum, length, offset)

    def _set_descriptor(self, address: int, d: Descriptor) -> None:
        off = address * _DESCRIPTOR_SIZE
        struct.pack_into(_DESCRIPTOR_FORMAT, self.descriptors, off, d.status, d.checksum, d.length, d.offset)

    # ---- single-entry operations -------------------------------------------

    def write(self, address: int, content: bytes, depends_on: Sequence[int] = ()) -> None:
        tier, category, _ = self.bootstrap.decompose_address(address)
        if tier == 0 and category == 0:
            raise PayloadError(f"address {address:#06x} is in the reserved bootstrap range (tier 0, category 0)")
        if len(depends_on) > 255:
            raise PayloadError("at most 255 dependencies per entry")

        for dep in depends_on:
            outcome, _, _ = self.read(dep)
            if outcome != EntryOutcome.VALID:
                raise PayloadError(
                    f"cannot write {address:#06x}: dependency {dep:#06x} is not VALID (outcome={outcome.name})"
                )

        body = bytes([len(depends_on)]) + b"".join(struct.pack(_DEP_ADDR_FORMAT, d) for d in depends_on) + content
        checksum = compute_checksum(body, self.bootstrap.checksum_algo)
        offset = len(self.heap)
        self.heap.extend(body)
        self._set_descriptor(address, Descriptor(_STATUS_VALID, checksum, len(body), offset))

    def read(self, address: int) -> Tuple[EntryOutcome, Optional[bytes], Optional[List[int]]]:
        d = self._get_descriptor(address)
        if d.status == _STATUS_UNASSIGNED:
            return EntryOutcome.UNASSIGNED, None, None
        if d.status == _STATUS_DELETED:
            return EntryOutcome.DELETED, None, None

        body = bytes(self.heap[d.offset: d.offset + d.length])
        if compute_checksum(body, self.bootstrap.checksum_algo) != d.checksum:
            return EntryOutcome.CORRUPT, None, None

        dep_count = body[0]
        deps = []
        pos = 1
        for _ in range(dep_count):
            (dep,) = struct.unpack_from(_DEP_ADDR_FORMAT, body, pos)
            deps.append(dep)
            pos += 2
        content = body[pos:]
        return EntryOutcome.VALID, content, deps

    def delete(self, address: int) -> None:
        d = self._get_descriptor(address)
        if d.status == _STATUS_UNASSIGNED:
            raise PayloadError(f"cannot delete {address:#06x}: unassigned")
        d.status = _STATUS_DELETED
        self._set_descriptor(address, d)

    # ---- batch write, dependency-ordered ------------------------------------

    def write_ordered(self, items: Sequence[Tuple[int, bytes, Sequence[int]]]) -> List[int]:
        """items: (address, content, depends_on) tuples, in ANY order.
        Writes them in dependency order via Kahn's algorithm. Dependencies
        outside this batch must already be VALID in the store. Raises on
        a cycle within the batch. Returns the order actually written in."""
        by_addr: Dict[int, Tuple[bytes, Sequence[int]]] = {}
        for addr, content, deps in items:
            if addr in by_addr:
                raise PayloadError(f"address {addr:#06x} appears twice in one batch")
            by_addr[addr] = (content, deps)

        in_degree: Dict[int, int] = {}
        dependents: Dict[int, List[int]] = {a: [] for a in by_addr}
        for addr, (_, deps) in by_addr.items():
            pending = [d for d in deps if d in by_addr]
            in_degree[addr] = len(pending)
            for d in pending:
                dependents[d].append(addr)
            for d in deps:
                if d not in by_addr:
                    outcome, _, _ = self.read(d)
                    if outcome != EntryOutcome.VALID:
                        raise PayloadError(
                            f"batch item {addr:#06x} depends on {d:#06x}, outside this batch "
                            f"and not VALID in the store (outcome={outcome.name})"
                        )

        ready = [a for a, deg in in_degree.items() if deg == 0]
        order: List[int] = []
        while ready:
            a = ready.pop()
            order.append(a)
            for dep_addr in dependents[a]:
                in_degree[dep_addr] -= 1
                if in_degree[dep_addr] == 0:
                    ready.append(dep_addr)

        if len(order) != len(by_addr):
            remaining = sorted(set(by_addr) - set(order))
            raise PayloadError(f"dependency cycle among: {[hex(a) for a in remaining]}")

        for addr in order:
            content, deps = by_addr[addr]
            self.write(addr, content, deps)
        return order


# ──────────────────────────────────────────────────────────────
# Self-test / demo
# ──────────────────────────────────────────────────────────────

def _demo() -> None:
    bootstrap = BootstrapBlock()
    store = Store(bootstrap)

    rule_ed = store.compose(tier=1, category=2, index=1)
    root_walk = store.compose(tier=1, category=1, index=1)
    walked = store.compose(tier=2, category=1, index=1)

    print("addresses:", f"rule_ed={rule_ed:#06x}", f"root_walk={root_walk:#06x}", f"walked={walked:#06x}")

    # writing "walked" before its dependencies exist must fail
    try:
        store.write(walked, b"walked", depends_on=[root_walk, rule_ed])
        print("FAILED: wrote an entry whose dependencies don't exist yet")
    except PayloadError as e:
        print("correctly refused premature write:", e)

    store.write(rule_ed, b"-ed")
    store.write(root_walk, b"walk")
    store.write(walked, b"walked", depends_on=[root_walk, rule_ed])
    print("wrote all three in dependency order")

    outcome, content, deps = store.read(walked)
    print(f"read walked: {outcome.name} content={content!r} deps={[hex(d) for d in deps]}")

    store.delete(root_walk)
    outcome, _, _ = store.read(root_walk)
    print(f"read root_walk after delete: {outcome.name}")

    d = store._get_descriptor(walked)
    store.heap[d.offset] ^= 0xFF  # simulate bit rot in "walked"'s own entry
    outcome, content, _ = store.read(walked)
    print(f"read walked after corruption: {outcome.name} content={content}")

    untouched = store.compose(tier=5, category=5, index=5)
    outcome, _, _ = store.read(untouched)
    print(f"read never-written address: {outcome.name}")

    # topological batch write: submitted deliberately out of order, proving
    # the SORT determines write order, not submission order
    prefix_re = store.compose(tier=1, category=3, index=1)
    prefix_un = store.compose(tier=1, category=3, index=2)
    root_do = store.compose(tier=1, category=1, index=3)
    redo = store.compose(tier=2, category=1, index=3)
    undo = store.compose(tier=2, category=1, index=4)
    order = store.write_ordered([
        (redo, b"redo", [prefix_re, root_do]),
        (undo, b"undo", [prefix_un, root_do]),
        (root_do, b"do", []),
        (prefix_un, b"un-", []),
        (prefix_re, b"re-", []),
    ])
    print("batch submitted unordered, written in dependency order:")
    print(" ", [hex(a) for a in order])

    # cycle detection: two entries that depend on each other, submitted together
    cyc_a = store.compose(tier=3, category=3, index=1)
    cyc_b = store.compose(tier=3, category=3, index=2)
    try:
        store.write_ordered([
            (cyc_a, b"a", [cyc_b]),
            (cyc_b, b"b", [cyc_a]),
        ])
        print("FAILED: a real dependency cycle was accepted")
    except PayloadError as e:
        print("cycle correctly rejected:", e)


if __name__ == "__main__":
    _demo()
