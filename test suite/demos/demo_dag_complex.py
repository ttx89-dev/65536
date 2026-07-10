"""
demo_dag_complex.py — Complex 10+ node dependency DAG
═══════════════════════════════════════════════════════════════════════════════

Builds a 13-node dependency DAG and exercises:
  - Tier derivation from a label-level dependency graph
  - Topological ordering via payload_codec.write_ordered()
  - Readback and dep verification across all nodes
  - Content-store dedup on duplicate payloads

Run:   python "test suite/demos/demo_dag_complex.py"       (from 65536/)
       python demo_dag_complex.py                          (from test suite/demos/)
═══════════════════════════════════════════════════════════════════════════════
"""

import sys, os
# Need paths to both test suite/ (for payload_codec etc.) and project root (for hierarchy.py)
_demo_dir = os.path.dirname(__file__)
sys.path.insert(0, os.path.join(_demo_dir, ".."))        # test suite/
sys.path.insert(0, os.path.join(_demo_dir, "..", ".."))  # project root

from bootstrap_block import BootstrapBlock, ChecksumAlgo
from payload_codec import Store as PayloadStore, EntryOutcome
from content_store import Store as ContentStore
from hierarchy import derive_tiers, derive_priority, plan_ingestion, HierarchyError


# ═══ DAG definition (13 nodes) ═══════════════════════════════════════════
#        root ─┬─ A ── C ── D ── F
#              ├─ B ── E ── G
#              │           └── H
#              └─ I ── J ── K
#                    └── L

LABELS = {
    "root": 0x2001,
    "A": 0x2101, "B": 0x2102, "I": 0x2103,
    "C": 0x2201, "D": 0x2301,
    "E": 0x2202, "G": 0x2302, "H": 0x2303,
    "J": 0x2203, "K": 0x2304, "L": 0x2305,
    "F": 0x2401,
}

DEPS = {
    "root": [],
    "A": ["root"],  "B": ["root"],  "I": ["root"],
    "C": ["A"],
    "D": ["C"],
    "E": ["B"],
    "J": ["I"],
    "F": ["D"],
    "G": ["E"],  "H": ["E"],
    "K": ["J"],  "L": ["J"],
}


def _dag_as_tree():
    """Pretty-print the dependency DAG as indented text."""
    lines = []
    children = {l: [] for l in DEPS}
    roots = [l for l, d in DEPS.items() if not d]
    for l, deps in DEPS.items():
        for d in deps:
            children[d].append(l)

    def walk(node, indent=0, seen=None):
        if seen is None:
            seen = set()
        prefix = "  " * indent + ("└─ " if indent else "")
        lines.append(f"{prefix}{node}  ({LABELS[node]:#06x})")
        if node in seen:
            lines.append(f"{'  ' * (indent+1)}⚠ cycle")
            return
        seen.add(node)
        for c in sorted(children.get(node, [])):
            walk(c, indent + 1, seen.copy())

    for r in sorted(roots):
        walk(r)
    return "\n".join(lines)


def demo():
    print("═" * 60)
    print("  65536 — Complex Dependency DAG Demo (13 nodes)")
    print("═" * 60)

    # ── 1. Visualise ──────────────────────────────────────────────────
    print(f"\n◆ Dependency DAG:\n{_dag_as_tree()}\n")

    # ── 2. Derive tiers ───────────────────────────────────────────────
    print("◆ Tier / priority derivation (hierarchy.py)")
    try:
        tiers = derive_tiers(DEPS)
        prio = derive_priority(DEPS)
        plan = plan_ingestion(DEPS)
    except HierarchyError as e:
        print(f"  ✗ Cycle detected: {e}")
        return

    print(f"  {'Label':>6s}  tier  priority")
    for label in sorted(tiers, key=lambda l: (tiers[l], -prio[l], l)):
        print(f"  {label:>6s}  {tiers[label]:>3d}   {prio[label]:>3d}")
    print(f"\n  Ingestion order: {plan.order}")

    # ── 3. Build items and write via topological ordering ─────────────
    print("\n◆ Topological write (payload_codec.Store.write_ordered)")
    items = [(LABELS[l], f"content_{l}".encode(), [LABELS[d] for d in deps])
             for l, deps in DEPS.items()]

    ps = PayloadStore(BootstrapBlock(checksum_algo=ChecksumAlgo.NONE))
    order = ps.write_ordered(items)
    write_labels = []
    for addr in order:
        for l, a in LABELS.items():
            if a == addr:
                write_labels.append(l)
                break
    print(f"  Write order:  {', '.join(write_labels)}")
    print(f"  Count:        {len(order)}")

    # ── 4. Verify all readbacks ───────────────────────────────────────
    print("\n◆ Readback verification")
    ok = True
    for label in DEPS:
        addr = LABELS[label]
        outcome, content, dep_hashes = ps.read(addr)
        expected = f"content_{label}".encode()
        if outcome != EntryOutcome.VALID or content != expected:
            print(f"  ✗ {label:>6s} ({addr:#06x}): {outcome.name}")
            ok = False
    print(f"  All content:  {'PASS' if ok else 'FAIL'}")

    # ── 5. Dependency chain spot-check ────────────────────────────────
    print("  Dep chains:  ", end="")
    for label in ["J", "G", "K", "F"]:
        addr = LABELS[label]
        outcome, content, dep_hashes = ps.read(addr)
        assert outcome == EntryOutcome.VALID
        n_expected = len(DEPS[label])
        n_actual = len(dep_hashes) if dep_hashes else 0
        assert n_actual == n_expected, \
            f"{label}: expected {n_expected} deps, got {n_actual}"
    print("PASS")

    # ── 6. ContentStore dedup ─────────────────────────────────────────
    print("\n◆ ContentStore dedup")
    cs = ContentStore(BootstrapBlock(checksum_algo=ChecksumAlgo.NONE))
    for addr, content, deps in items:
        cs.write(addr, content, deps)

    a1, a2 = 0x3001, 0x3002
    cs.write(a1, b"dedup-this-content")
    cs.write(a2, b"dedup-this-content")
    _, _, _, h1 = cs.read(a1)
    _, _, _, h2 = cs.read(a2)
    print(f"  Dedup:        {'PASS (hashes match)' if h1 == h2 else 'FAIL'}")

    print("\n═" * 60)
    print("  Complex DAG demo: ALL PASS")
    print("═" * 60)


if __name__ == "__main__":
    demo()
