# Ordering, Prioritizing, Categorizing — the ingestion methodology

What this document is: the connective process between "an arbitrary piece
of information, new or old" and "a correctly-addressed, regeneratable
entry" in the 65535-point framework. Every mechanism referenced here was
built and tested earlier this session — this document is what tells you
*when* to use which one, in what order, and why.

## What tier, category, and index actually mean here

Three different things get called "ordering" in casual conversation about
this framework. They are not the same operation, and only two of the
three are mechanical.

| Term | What it encodes | How it's determined |
|---|---|---|
| **Tier** | Dependency depth — what must exist before this can | **Mechanical.** `hierarchy.py: derive_tiers()`. tier(x) = 1 + deepest dependency's tier, 0 if none. |
| **Index** | Priority within a (tier, category) — what matters most, first | **Mechanical.** `hierarchy.py: derive_priority()`. Ranked by how many other entries transitively rely on it. |
| **Category** | Domain grouping — what a reader would browse together | **Judgment.** Not derivable from the dependency graph. See below. |

Tier and index are settled facts once dependencies are honestly declared
— there's no ambiguity left to resolve by hand. Category is the one place
this methodology asks for a human or agent decision, because it isn't a
fact about the data. Two equally foundational, equally-depended-upon
concepts can belong in completely different categories, and the
dependency graph has no opinion about that — it only knows what relies on
what, not what a reader would want shelved together.

## The process

Applies identically whether the input is one new fact or an entire
existing corpus being retrofitted — see "new vs. old" below for why.

**1. Check for an existing match first.**
Before declaring anything new, check whether this content — or something
close enough to depend on instead of duplicating — already exists.
`content_store.py`'s hash lookup does this mechanically for exact
matches; near-matches still require judgment. This step exists *before*
tier/index/category assignment because skipping it is the single biggest
way this system fails to compound (see below).

**2. Determine true dependencies.**
The test is not "what's related to this" — everything is related to
everything, that test never terminates usefully. The test is: *can this
be stated at all without already having something else defined?* If yes,
name that something else as a dependency. If no — if it bottoms out in
pure stipulation or convention, nothing else to point to — it's a tier-0
primitive. This is the same test that separated generative grammar from
irreducible vocabulary in the English example: grammar rules can be
stated in terms of other rules, but a root morpheme's meaning is
convention, full stop, nothing underneath it.

**3. Derive tier.**
Feed the label plus its declared dependencies into `derive_tiers()`. Not
a suggestion to sanity-check — the output *is* the tier. Hand-picking a
tier that disagrees with what the dependency graph implies is a sign the
dependency list from step 2 was wrong, not a sign the algorithm is wrong.

**4. Assign category.**
Judgment call. Two working heuristics: (a) if an existing category
already covers this domain, use it — category budget is scarce (2^4 = 16
with the current bootstrap split) and minting a new one for something
that fits an old one spends budget for no reason. (b) if genuinely
uncertain between two existing categories, that uncertainty is itself
information — it may mean the two categories should have been one, which
is a schema-level decision, not a per-entry one. One honest gap: the
schema as built doesn't yet store a human-readable name per category
index, so "does this fit an existing category" currently means
remembering what category 3 was for, not looking it up. A small
string-table addition to the schema block would fix this; not built yet,
flagged rather than skipped.

**5. Derive index priority.**
`derive_priority()` on the same label set. This determines *order*
within a (tier, category), not the tier itself. Assign indices following
`plan_ingestion()`'s suggested order: most transitively-relied-upon
first.

**6. Validate.**
Cycle check and undefined-reference check are already enforced by
`derive_tiers()` — a cycle or a dangling reference raises before you get
this far. Confirm the category and tier counts declared are still within
the schema's budget (`bootstrap.category_count`, `bootstrap.tier_count`).

**7. Write.**
`Store.write()` (or `write_ordered()` for a batch) from `payload_codec.py`
or `content_store.py`, using the tier from step 3, the category from step
4, and an index following the order from step 5.

## New information vs. old information

There is no second process for existing material. Retrofitting an old
corpus is step 1 through 7, run once per item, exactly as above — the
only practical difference is that a large existing corpus makes
`write_ordered()`'s batch form (topological-sort the whole set, then
write in the order it produces) far more useful than writing one at a
time, since a real corpus rarely arrives in dependency order. The
*method* doesn't change; only whether you reach for the single-entry or
batch tool does.

## Why it gets easier, not just theoretically but mechanically

This was the original claim worth being skeptical of, so here's the
actual mechanism, not just the hope: content-addressing
(`content_store.py`) already collapses identical content to one entry
regardless of where it's referenced from. Step 1 of this process is what
makes that pay off *before* writing, not just after — by directing every
new item to first ask "can this depend on something that already exists"
rather than "what new primitive does this need." The two reinforce each
other: the richer the existing foundation, the more likely new material
can be expressed as depending on it rather than requiring fresh tier-0
entries, and every time that happens, the marginal cost of the next new
item goes down. This is a real, checkable property of the running
system, not an aspiration — it's the same reason `walked-via-a` and
`walked-via-b` hashed identically in an earlier round despite being
written independently: shared foundation collapses automatically, the
process just makes sure new material is aimed at hitting that collapse
instead of missing it.

## What this doesn't claim

No closed, finite categorization can be complete over an open-ended
subject — new concepts keep arriving, same as it was true for English
vocabulary earlier this session. What this process gives instead is
closure under extension: the system can always absorb something new
without needing to be redesigned, which is a real and sufficient
property, just a different and more honest one than "complete." The one
step that stays irreducibly a judgment call, even with this whole
process followed exactly, is category — that was true on day one of this
conversation and remains true here. This document routes around that
limit with heuristics; it doesn't remove it, because it isn't removable.
