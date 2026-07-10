"""
content_store.py — content-addressed variant, 65535-point framework

The architectural change from payload_codec.py: addresses stop OWNING
bytes and start POINTING at them. Two layers:

    ADDRESS TABLE   65536 entries, one per structured (tier,category,index)
                    address. Each holds: status + a content hash. Small,
                    fixed, dense — same O(1) lookup as before.

    CONTENT TABLE   hash -> (offset, length, refcount) into a shared heap.
                    Keyed by a 64-bit FNV-1a hash, using a native dict/Dict
                    as the hash table (no need to hand-roll one — that's
                    exactly what dicts already are).

Two different structured addresses can point at the same content hash. If
they do, the heap holds ONE copy, refcounted.

The subtle part: what gets hashed is NOT "dep_count + dependency ADDRESSES
+ content" — it's "dep_count + dependency HASHES + content". If addresses
were hashed directly, two semantically-identical entries whose deps happen
to sit at different structured slots would hash differently, breaking
deduplication for exactly the cases that matter most. Hashing the
dependencies' own content hashes instead makes an entry's identity a pure
function of what it MEANS, not where its prerequisites happen to live —
the same principle behind why a git commit object references its parent's
hash, never a branch name.

One consequence: an address can only be written once in this reference
build. Repointing an already-VALID address to different content is a real
feature (versioning, edits) but a distinct one from what's built here —
deferred on purpose, same as compaction was deferred last round.

Depends on bootstrap_block.py (BootstrapBlock, BootstrapError) and
payload_codec.py (EntryOutcome, PayloadError) — reused as-is; this file
only replaces the Store internals, not the outcome vocabulary.

Python 3.9+, standard library only.
"""

from __future__ import annotations
import struct
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence, Set, Tuple

from bootstrap_block import BootstrapBlock
from payload_codec import EntryOutcome, PayloadError


_FNV_OFFSET = 0xcbf29ce484222325
_FNV_PRIME = 0x100000001b3
_MASK64 = 0xFFFFFFFFFFFFFFFF

_ADDR_DESC_SIZE = 9              # status(1) + hash(8)
_ADDR_DESC_FORMAT = ">BQ"
_ADDRESS_SPACE = 1 << 16

_STATUS_UNASSIGNED = 0
_STATUS_VALID = 1
_STATUS_DELETED = 2


def fnv1a_64(data: bytes) -> int:
    """Fixed, non-negotiable identity hash — not governed by checksum_algo.
    Two stores can only recognize shared content if they agree on identity;
    that agreement has to be a framework-level constant, not a per-schema
    choice."""
    h = _FNV_OFFSET
    for byte in data:
        h ^= byte
        h = (h * _FNV_PRIME) & _MASK64
    return h


@dataclass
class ContentRecord:
    offset: int
    length: int
    refcount: int = 0


class Store:
    def __init__(self, bootstrap: BootstrapBlock):
        self.bootstrap = bootstrap
        self.address_table = bytearray(_ADDRESS_SPACE * _ADDR_DESC_SIZE)
        self.content_table: Dict[int, ContentRecord] = {}
        self.hash_to_addresses: Dict[int, Set[int]] = {}
        self.heap = bytearray()

    # ---- addressing ---------------------------------------------------------

    def compose(self, tier: int, category: int, index: int) -> int:
        b = self.bootstrap
        if not (0 <= tier < (1 << b.tier_bits)):
            raise PayloadError(f"tier {tier} out of range for {b.tier_bits} tier bits")
        if not (0 <= category < (1 << b.category_bits)):
            raise PayloadError(f"category {category} out of range for {b.category_bits} category bits")
        if not (0 <= index < (1 << b.index_bits)):
            raise PayloadError(f"index {index} out of range for {b.index_bits} index bits")
        return (tier << (b.category_bits + b.index_bits)) | (category << b.index_bits) | index

    # ---- address table i/o ---------------------------------------------------

    def _get_address_descriptor(self, address: int) -> Tuple[int, int]:
        off = address * _ADDR_DESC_SIZE
        status, h = struct.unpack_from(_ADDR_DESC_FORMAT, self.address_table, off)
        return status, h

    def _set_address_descriptor(self, address: int, status: int, h: int) -> None:
        off = address * _ADDR_DESC_SIZE
        struct.pack_into(_ADDR_DESC_FORMAT, self.address_table, off, status, h)

    # ---- core operations --------------------------------------------------------

    def write(self, address: int, content: bytes, depends_on: Sequence[int] = ()) -> int:
        """Returns the content hash this address now points to."""
        tier, category, _ = self.bootstrap.decompose_address(address)
        if tier == 0 and category == 0:
            raise PayloadError(f"address {address:#06x} is in the reserved bootstrap range (tier 0, category 0)")

        status, _ = self._get_address_descriptor(address)
        if status != _STATUS_UNASSIGNED:
            raise PayloadError(
                f"address {address:#06x} already written (status={status}); "
                f"this reference build supports first-write only, not repointing"
            )
        if len(depends_on) > 255:
            raise PayloadError("at most 255 dependencies per entry")

        dep_hashes: List[int] = []
        for dep_addr in depends_on:
            outcome, _, _, dep_hash = self.read(dep_addr)
            if outcome != EntryOutcome.VALID:
                raise PayloadError(
                    f"cannot write {address:#06x}: dependency {dep_addr:#06x} is not VALID (outcome={outcome.name})"
                )
            dep_hashes.append(dep_hash)

        body = bytes([len(dep_hashes)]) + b"".join(struct.pack(">Q", h) for h in dep_hashes) + content
        h = fnv1a_64(body)

        record = self.content_table.get(h)
        if record is None:
            offset = len(self.heap)
            self.heap.extend(body)
            record = ContentRecord(offset=offset, length=len(body), refcount=0)
            self.content_table[h] = record

        record.refcount += 1
        self._set_address_descriptor(address, _STATUS_VALID, h)
        self.hash_to_addresses.setdefault(h, set()).add(address)
        return h

    def read(self, address: int) -> Tuple[EntryOutcome, Optional[bytes], Optional[List[int]], Optional[int]]:
        """Returns (outcome, content, dependency_hashes, this_entry's_own_hash)."""
        status, h = self._get_address_descriptor(address)
        if status == _STATUS_UNASSIGNED:
            return EntryOutcome.UNASSIGNED, None, None, None
        if status == _STATUS_DELETED:
            return EntryOutcome.DELETED, None, None, None

        record = self.content_table.get(h)
        if record is None:
            return EntryOutcome.CORRUPT, None, None, None  # dangling pointer

        body = bytes(self.heap[record.offset: record.offset + record.length])
        if fnv1a_64(body) != h:
            return EntryOutcome.CORRUPT, None, None, None  # heap bytes damaged

        dep_count = body[0]
        dep_hashes = []
        pos = 1
        for _ in range(dep_count):
            (dh,) = struct.unpack_from(">Q", body, pos)
            dep_hashes.append(dh)
            pos += 8
        content = body[pos:]
        return EntryOutcome.VALID, content, dep_hashes, h

    def delete(self, address: int) -> None:
        status, h = self._get_address_descriptor(address)
        if status == _STATUS_UNASSIGNED:
            raise PayloadError(f"cannot delete {address:#06x}: unassigned")
        if status == _STATUS_VALID:
            record = self.content_table.get(h)
            if record is not None:
                record.refcount -= 1
            self.hash_to_addresses.get(h, set()).discard(address)
        self._set_address_descriptor(address, _STATUS_DELETED, h)


# ──────────────────────────────────────────────────────────────
# Self-test / demo
# ──────────────────────────────────────────────────────────────

def _demo() -> None:
    bootstrap = BootstrapBlock()
    store = Store(bootstrap)

    # two DIFFERENT structured addresses, IDENTICAL content, no deps
    addr_a = store.compose(tier=1, category=1, index=1)
    addr_b = store.compose(tier=1, category=6, index=1)  # deliberately a different category

    h1 = store.write(addr_a, b"walk")
    size_after_first = len(store.heap)
    h2 = store.write(addr_b, b"walk")
    size_after_second = len(store.heap)

    print(f"addr_a={addr_a:#06x} hash={h1:016x}")
    print(f"addr_b={addr_b:#06x} hash={h2:016x}  same hash: {h1 == h2}")
    print(f"heap grew by {size_after_second - size_after_first} bytes on the duplicate write (expect 0)")
    print(f"refcount for shared content: {store.content_table[h1].refcount} (expect 2)")
    print(f"addresses currently pointing at it: {sorted(hex(a) for a in store.hash_to_addresses[h1])}")

    # a composite depending on addr_a, and a SEPARATE one depending on addr_b —
    # otherwise identical — proving identity is content-derived, not slot-derived
    rule_ed = store.compose(tier=1, category=2, index=1)
    store.write(rule_ed, b"-ed")

    walked_via_a = store.compose(tier=2, category=1, index=1)
    h_walked_a = store.write(walked_via_a, b"walked", depends_on=[addr_a, rule_ed])

    walked_via_b = store.compose(tier=2, category=6, index=1)
    h_walked_b = store.write(walked_via_b, b"walked", depends_on=[addr_b, rule_ed])

    print(f"\nwalked-via-a hash={h_walked_a:016x}")
    print(f"walked-via-b hash={h_walked_b:016x}")
    print(f"same, despite different dependency SLOTS: {h_walked_a == h_walked_b}")

    # refcounting through delete
    store.delete(addr_a)
    print(f"\nrefcount after deleting addr_a: {store.content_table[h1].refcount} (expect 1)")
    outcome, content, _, _ = store.read(addr_b)
    print(f"addr_b still readable after addr_a deleted: {outcome.name} {content!r}")

    store.delete(addr_b)
    print(f"refcount after deleting addr_b too: {store.content_table[h1].refcount} (expect 0, eligible for future compaction)")

    # attempting to rewrite an already-written address
    try:
        store.write(walked_via_a, b"something else")
        print("FAILED: repointing an already-VALID address was silently allowed")
    except PayloadError as e:
        print(f"\ncorrectly refused repoint: {e}")


if __name__ == "__main__":
    _demo()
