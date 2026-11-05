"""
demo_full_pipeline.py — Bootstrap → Payload → ContentStore lifecycle
═══════════════════════════════════════════════════════════════════════════════

Writes content through all three storage layers and reads it back.
Demonstrates the complete write→read→verify lifecycle across the 65536
addressing framework.

Run:   python "tests/demos/demo_full_pipeline.py"       (from 65536/)
       python demo_full_pipeline.py                          (from tests/demos/)
═══════════════════════════════════════════════════════════════════════════════
"""

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from bootstrap_block import BootstrapBlock, ChecksumAlgo, ProvenanceScheme, ReadOutcome, BLOCK_SIZE, MAGIC
from payload_codec import Store as PayloadStore, EntryOutcome
from content_store import Store as ContentStore


def demo():
    print("═" * 60)
    print("  65536 — Full Pipeline Demo")
    print("═" * 60)

    # ── Layer 1: Bootstrap Block (267B fixed header) ──────────────────
    print("\n◆ LAYER 1: Bootstrap Block (267B fixed header)")
    bb = BootstrapBlock(
        checksum_algo=ChecksumAlgo.CRC16,
        provenance_scheme=ProvenanceScheme.AGENT_SIGNED,
        schema_version=(2, 0),
        tier_count=5,
        category_count=4,
    )

    data = bb.to_bytes()
    assert len(data) == BLOCK_SIZE
    print(f"  Block size:       {len(data)} B")
    print(f"  Magic:            {data[:4]!r}")

    # Round-trip: parse the serialised form back
    bb2 = BootstrapBlock.parse(data)
    assert bb2 == bb, "serialise/parse round-trip equality"
    print(f"  Round-trip:       PASS (field-for-field)")

    # Inspect parsed fields
    print(f"  Checksum algo:    {bb2.checksum_algo.name}")
    print(f"  Provenance:       {bb2.provenance_scheme.name}")
    print(f"  Schema version:   {bb2.schema_version}")
    print(f"  Tiers / cats:     {bb2.tier_count} / {bb2.category_count}")

    # Address decomposition
    t, c, i = bb2.decompose_address(0x1234)
    print(f"  Decompose 0x1234: tier={t} category={c} index={i}")

    # Read slots from serialised data (read-only inspection)
    outcome0, val0 = bb2.read_slot(data, 0x00)
    outcome1, val1 = bb2.read_slot(data, 0x01)
    outcomeFe, valFe = bb2.read_slot(data, 0xFE)
    outcomeFF, valFF = bb2.read_slot(data, 0xFF)
    print(f"  Slot 0x00:        {outcome0.name} ({'always present' if outcome0 == ReadOutcome.VALID else '?'})")
    print(f"  Slot 0x01:        {outcome1.name}" + (f"  val={val1}" if val1 is not None else ""))
    print(f"  Slot 0xFE:        {outcomeFe.name}" + (f"  val={valFe}" if valFe is not None else ""))
    print(f"  Slot 0xFF:        {outcomeFF.name}" + (f"  val={valFF}" if valFF is not None else ""))
    print("  BootstrapBlock:  PASS")

    # ── Layer 2: Payload Codec ────────────────────────────────────────
    print("\n◆ LAYER 2: Payload Store (address-indexed, dependency-checked)")
    ps = PayloadStore(BootstrapBlock(checksum_algo=ChecksumAlgo.NONE))

    addr_a = 0x1101   # tier=1, category=1, index=1
    addr_b = 0x1102   # tier=1, category=1, index=2
    addr_c = 0x1201   # tier=1, category=2, index=1

    ps.write(addr_a, b"Hello, payload A!")
    ps.write(addr_b, b"Hello, payload B!", depends_on=[addr_a])
    ps.write(addr_c, b"Payload C with deps A and B", depends_on=[addr_a, addr_b])

    # Readback verification (payload_codec.read returns 3-tuple)
    outcome_a, content_a, dep_hashes_a = ps.read(addr_a)
    assert outcome_a == EntryOutcome.VALID
    assert content_a == b"Hello, payload A!"
    print(f"  A ({addr_a:#06x}): {outcome_a.name} → {content_a}")

    outcome_b, content_b, dep_hashes_b = ps.read(addr_b)
    assert outcome_b == EntryOutcome.VALID
    assert content_b == b"Hello, payload B!"
    print(f"  B ({addr_b:#06x}): {outcome_b.name} → {content_b}, deps={dep_hashes_b}")

    outcome_c, content_c, _ = ps.read(addr_c)
    assert outcome_c == EntryOutcome.VALID
    print(f"  C ({addr_c:#06x}): {outcome_c.name} → {content_c}")

    print("  PayloadStore:  PASS")

    # ── Layer 3: Content Store ────────────────────────────────────────
    print("\n◆ LAYER 3: Content Store (content-addressed, FNV-1a dedup)")
    cs = ContentStore(BootstrapBlock(checksum_algo=ChecksumAlgo.NONE))

    addr_x = 0x2101  # tier=2, category=1, index=1
    addr_y = 0x2102  # tier=2, category=1, index=2
    addr_z = 0x2103  # tier=2, category=1, index=3

    dup_data = b"deduplicatable content string"

    hash_x = cs.write(addr_x, b"unique alpha")
    hash_y = cs.write(addr_y, dup_data)
    hash_z = cs.write(addr_z, dup_data)   # same content → same hash

    # content_store.read returns 4-tuple: (EntryOutcome, bytes, deps, hash)
    oc_x, data_x, _, h_x = cs.read(addr_x)
    oc_y, data_y, _, h_y = cs.read(addr_y)
    oc_z, data_z, _, h_z = cs.read(addr_z)

    print(f"  X ({addr_x:#06x}): hash={h_x:#018x} → {data_x}")
    print(f"  Y ({addr_y:#06x}): hash={h_y:#018x} → {data_y}")
    print(f"  Z ({addr_z:#06x}): hash={h_z:#018x} → {data_z}")
    print(f"  Dedup:        {'YES — hashes match' if h_y == h_z else 'NO — collision!'}")

    assert h_y == h_z, "Content store should dedup identical content"
    assert h_x != h_y, "Different content should have different hashes"
    assert oc_x == oc_y == oc_z == EntryOutcome.VALID

    print("  ContentStore:  PASS")

    # ── Done ──────────────────────────────────────────────────────────
    print("\n═" * 60)
    print("  Full pipeline: ALL PASS")
    print("═" * 60)


if __name__ == "__main__":
    demo()
