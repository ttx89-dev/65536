"""
hierarchy.py — tier derivation, 65535-point framework

The piece that was missing: everything built so far assumes tier is
already known when an address is composed. This is the step BEFORE
that — turning a raw dependency graph of symbolic labels (not yet
addresses, not yet categorized) into a mechanically correct tier
assignment.

What this does NOT do, on purpose: assign categories. Category is a
domain/grouping judgment ("this is phonology, that's syntax") that no
dependency graph can derive — it's not a fact about the data, it's a
choice about how someone wants to browse it. Tier is different: once
dependencies are honestly declared, tier stops being a guess.

    tier(x) = 0                                  if x has no dependencies
    tier(x) = 1 + max(tier(d) for d in deps(x))  otherwise

This is deliberately standalone — no dependency on bootstrap_block.py or
payload_codec.py. It operates purely on labels, before any address exists.
Once tiers come out of this, the caller picks a category (judgment) and
the next free index (bookkeeping), calls Store.compose(tier, category,
index), and hands the batch to write_ordered/write as already built.

Python 3.9+, standard library only.
"""

from __future__ import annotations
from dataclasses import dataclass
from typing import Dict, List


class HierarchyError(ValueError):
    """Raised on a cycle or a reference to an undefined label."""


def derive_priority(items: Dict[str, List[str]]) -> Dict[str, int]:
    """label -> count of items that transitively depend on it (directly
    or via a chain). Higher = more foundational = should get a LOWER
    index within its (tier, category) — not because fixed-width addresses
    save any bits from this (they don't; every address is 16 bits
    regardless), but because it clusters what matters most at the low end
    of each range, makes address value a legible foundationality signal,
    and gives two independent ingestions of the same material a reason to
    converge on the same layout rather than diverging by accident of
    arrival order."""
    direct_dependents: Dict[str, List[str]] = {label: [] for label in items}
    for label, deps in items.items():
        for d in deps:
            if d not in items:
                raise HierarchyError(f"{label!r} depends on undefined {d!r}")
            direct_dependents[d].append(label)

    def transitive(label: str, seen: set) -> set:
        for dependent in direct_dependents[label]:
            if dependent not in seen:
                seen.add(dependent)
                transitive(dependent, seen)
        return seen

    return {label: len(transitive(label, set())) for label in items}


@dataclass
class IngestionPlan:
    tier: Dict[str, int]
    priority: Dict[str, int]
    order: List[str]   # suggested index-assignment order: tier ascending, then priority descending


def plan_ingestion(items: Dict[str, List[str]]) -> IngestionPlan:
    """The combined step: derive tier (mechanical), derive priority
    (mechanical), and produce the order in which labels should receive
    indices within their category. What this deliberately does NOT
    decide: category itself. See hierarchy.md for why."""
    tiers = derive_tiers(items)
    priority = derive_priority(items)
    order = sorted(items.keys(), key=lambda l: (tiers[l], -priority[l], l))
    return IngestionPlan(tier=tiers, priority=priority, order=order)


def derive_tiers(items: Dict[str, List[str]]) -> Dict[str, int]:
    """items: label -> list of dependency labels (also just strings).
    Returns label -> tier. Raises on a cycle or an undefined reference."""
    for label, deps in items.items():
        for d in deps:
            if d not in items:
                raise HierarchyError(f"{label!r} depends on undefined {d!r}")

    tier: Dict[str, int] = {}
    remaining = dict(items)
    while remaining:
        ready = [label for label, deps in remaining.items() if all(d in tier for d in deps)]
        if not ready:
            raise HierarchyError(f"dependency cycle among: {sorted(remaining)}")
        for label in ready:
            deps = remaining.pop(label)
            tier[label] = 1 + max((tier[d] for d in deps), default=-1)
    return tier


# ──────────────────────────────────────────────────────────────
# Self-test / demo
# ──────────────────────────────────────────────────────────────

def _demo() -> None:
    # A close relative of the earlier English example — close enough to
    # check this tool against a hand-picked tier assignment made without it.
    subject = {
        "prime":         [],
        "function_word": [],                      # no deps either — same tier as prime, honestly
        "root":          ["prime"],
        "affix":         ["prime"],
        "derivation_rule": ["root", "affix"],
        "syntax_template": ["root", "affix", "function_word"],
    }

    tiers = derive_tiers(subject)
    for label in sorted(tiers, key=lambda l: (tiers[l], l)):
        print(f"tier {tiers[label]}: {label}")

    print()
    print("earlier, by hand, 'roots' and 'affixes' were placed at DIFFERENT tiers")
    print("(tier 1 and tier 2) purely by narrative feel, with no declared dependency")
    print("between them to justify it. Here, both genuinely depend only on 'prime',")
    print(f"so both land at tier {tiers['root']} — the hand-picked version was never wrong")
    print("exactly, just uncorroborated. this is what 'derived, not chosen' catches.")

    print()
    priority = derive_priority(subject)
    for label in sorted(priority, key=lambda l: -priority[l]):
        print(f"priority {priority[label]}: {label} (transitively relied on by {priority[label]} other entries)")

    print()
    plan = plan_ingestion(subject)
    print("suggested index-assignment order (tier ascending, then priority descending):")
    print(" ", plan.order)

    print()
    cyclic = {"a": ["b"], "b": ["a"]}
    try:
        derive_tiers(cyclic)
        print("FAILED: a real cycle was accepted")
    except HierarchyError as e:
        print("cycle correctly rejected:", e)

    print()
    dangling = {"a": ["ghost"]}
    try:
        derive_tiers(dangling)
        print("FAILED: an undefined dependency was accepted")
    except HierarchyError as e:
        print("undefined reference correctly rejected:", e)


if __name__ == "__main__":
    _demo()
