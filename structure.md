# Point 1 — The Structural Framework for All Information

*A companion to `ontology.md`, incorporating all six refinements identified
during deep study. Together they constitute the complete Point 1: the
optimal logical structure for how any piece of information relates to any
other, derived from independent convergence across library science,
formal ontology, and cognitive linguistics.*

---

## 0. What this document is

`ontology.md` established:
- Five relation types (equivalence, is-a, instance-of, part-of, associative)
- Facets (orthogonal, independent classification dimensions)
- Salience (structural vs empirical)
- A three-layer model (facet → hierarchy → salience, ordered by derivability)
- A bridge table with five named gaps in what's built

This document does not replace `ontology.md`. It:
1. **Refines** each of the above where depth was missing
2. **Adds** six structural elements the original was silent on
3. **Synthesizes** everything into one unified Point 1

When these two documents agree, that's the framework. This document
extends; it does not contradict.

---

## 1. The five relation types (refined)

### 1.1 Equivalence

Two labels, one referent. No change from `ontology.md`.

**Refinement — expression-level equivalence**: The original document only
discusses term-level synonymy ("car" / "automobile"). But equivalence can
exist between compound expressions and single terms: "the president of
France in 2020" / "Emmanuel Macron". These require resolution — they
cannot be handled by a flat synonym map.

For the framework: equivalence lives at TWO levels:
- **Lexical equivalence** (term → canonical term): a hash map. Mechanical.
- **Referential equivalence** (expression → entity): requires resolution
  or assertion. Not purely mechanical.

Both are equivalence relation edges. The framework must allow both.

### 1.2 Is-a / subclass-of

No change from `ontology.md`. `derive_tiers()` covers this correctly.
Test: "is every X necessarily a Y."

### 1.3 Instance-of

No change from `ontology.md`. Must be distinguished from is-a.
Test: "does X have possible subtypes of its own within this scheme" —
if no, it's an instance, not a subclass.

**Refinement — what allows instance-of to carry meaning**:
Instance-of is meaningful only because individuals have PROPERTIES.
An instance of "car" has a specific color, weight, VIN — properties that
are inherited (or overrideable) from the class. Without properties,
instance-of collapses to a bare token-counting exercise. See §4.

### 1.4 Part-of (meronomy)

The original document treats part-of as one relation. The meronomy
literature (Winston, Chaffin & Herrmann 1987, followed by subsequent
work) identifies six distinct part-whole subtypes with different formal
properties:

| Subtype | Example | Transitive? | Homeomeric? | Separable? |
|---------|---------|-------------|-------------|------------|
| Component-object | branch-tree | Yes | No (branch ≠ tree) | Yes |
| Member-collection | tree-forest | No* | No (tree ≠ forest) | Yes |
| Portion-mass | slice-pie | Yes | Yes (slice = pie) | Yes |
| Stuff-object | steel-car | No | No (steel ≠ car) | No |
| Feature-activity | paying-shopping | No | No (paying ≠ shopping) | N/A |
| Place-area | oasis-desert | No | No (oasis ≠ desert) | N/A |

\*Member-collection is transitive in a weaker sense (a tree is part of a
forest, a branch is part of a tree — is a branch part of a forest? Not in
the same "member-collection" sense; this is the classic failure case for
mereological transitivity.)

**What `derive_tiers()` computes**: construction-order dependency —
"component-object" meronomy with a temporal constraint (root morpheme must
exist before affixed word can exist). This is ONE of the six subtypes,
not the general case. For the 65536 project, this is the correct subtype
(we're building things hierarchically), but the framework should
acknowledge that part-of is richer than what's currently computed.

**Framework rule**: part-of edges carry a subtype label from the six
above. Code that doesn't need the distinction can treat all six as
"part-of". Code that does (e.g., transitivity inference) can check the
label.

### 1.5 Associative

The catch-all: related, but not hierarchical and not equivalent.

**Refinement — typed edge labels**: The original document mentions edge
labels as metadata. The framework should formalize a small set of
associative subtypes that carry inference rules:

| Label | Asymmetric? | Transitive? | Example |
|-------|-----------|-------------|---------|
| causes | Yes | Yes | drought → famine |
| precedes | Yes | Yes | planting → harvest |
| located-in | No | Yes | oasis → desert |
| has-property | Yes (functional) | Inherited via is-a | apple → red |
| produced-by | Yes | No | wine → fermentation |
| used-for | No | No | knife → cutting |
| antonym-of | Yes (symmetric reciprocal) | No | hot → cold |

These are NOT new relation types. They are labels on associative edges.
The relation type IS associate; the label carries inference behavior.

**Why this matters for Point 2**: the 65536 dot matrix must represent
edge labels, not just bare connections. Two glyphs that share an edge
need to encode what KIND of association they share.

---

## 2. Facets (refined)

No change to the core model from `ontology.md`: facets are independent
classification dimensions read simultaneously, not traversed in sequence.
Tier × category × index is a small instance of exactly this pattern.

**Refinement — cross-facet identity**: The same entity can appear in
multiple facet combinations. France appears in:
- continent = Europe
- language = French
- government = republic

These facet-combinations all refer to the SAME entity. This is NOT
equivalence (which covers synonymy of labels). It's identity across
facet paths. The framework needs a mechanism for this:
- A canonical identifier per entity (independent of facet paths)
- A mapping from any facet-path to that identifier
- A constraint that the identifier doesn't change when a new facet
  combination is discovered

For the 65536 grid: this means the dot matrix position encodes one
canonical representation per entity, not one per facet-combination.

**Refinement — adding a new facet**: The original document didn't specify
how a new facet is added. The extension mechanism:
1. Define the facet name and its possible values
2. Ensure values are disjoint from existing facet values (or declare
   overlap explicitly)
3. Register the facet in the framework's facet table
4. No existing code needs modification — new facets are additive

This is the same "closure under extension" property as the relation types.

---

## 3. Salience (refined)

**Structural salience**: derived from graph structure (how many things
depend on this node). `derive_priority()` computes this correctly.

**Empirical salience**: requires external measurement — corpus frequency,
prototype centrality, markedness. Not yet built.

**Refinement — two additional salience sources**:

**Designer-intended salience**: the creator of the scheme marks certain
entries as primary/default. An animal taxonomy might mark "mammal" as
the default entry point even though structurally it's at the same tier as
"reptile" and "bird". This is not derivable from the graph AND not
measurable from an external corpus — it's a design choice. It's also the
most immediately useful source for the 65536 project, since we control the
scheme's design.

**Situational salience**: what matters RIGHT NOW depends on context.
"Restaurant" is highly salient when looking for dinner, not salient when
planning a hiking trip. This is derived from query context, not from the
framework itself — the framework provides the interface for it.

**Framework rule for all three non-structural sources**:
- The INTERFACE is defined: salience is a rankable scalar per entity
  within a facet, per source
- The DATA is pluggable: empirical, designer-intended, and situational
  values can coexist and be combined
- The MECHANICAL part: once the data is in, sorting by salience is
  deterministic

---

## 4. Properties/attributes (new)

The single most significant thing `ontology.md` is silent on. Properties
are what make instance-of meaningful and what make is-a useful (via
inheritance). They are also the primary way that entities carry domain-
specific information in the 65536 grid.

**Where properties live in the five-type scheme**:

```
Entity A --[has-property]--> Property Value

Example:
Apple  --[has-color]-->  Red
```

- `has-property` is an ASSOCIATIVE relation (type 5) with a typed label
  indicating the property dimension (color, weight, shape, etc.)
- The property VALUE is itself an entity — it can participate in ALL five
  relation types: "crimson" is-a "red" (is-a), "red" and "blue" are both
  colors (equivalence at the property-dimension level), etc.
- Properties are INHERITED through is-a: if all mammals have hair, and
  dogs are mammals, then dogs have hair — unless explicitly overridden.

**Formal properties of has-property**:
- **Functional**: a simple entity has one value per property dimension
  at a time (an apple has one color, not simultaneously red and green,
  though it may have different colors at different times)
- **Inherited**: via is-a edges unless overridden
- **Monotonic**: adding a new property doesn't remove existing ones
  (unless explicit conflict resolution)

**Why this matters for Point 2**: The 65536 glyph encodes entities. Each
entity's properties are a significant portion of what the dot matrix
needs to represent. The mapping framework must allocate space for
property-value pairs, not just entity identity and relations.

---

## 5. Entity-relation duality / reification (new)

A relation between two entities can itself become an entity that
participates in relations:

```
John ----[married]----> Mary
  |                        |
  has-date              has-date
  |                        |
  2020-06-01            2020-06-01
```

Better modeled as:

```
Marriage_Event ----[spouse1]----> John
               |---[spouse2]----> Mary
               |---[has-date]---> 2020-06-01
```

This is **reification**: promoting a relation-edge to an entity-node so
it can have its own properties and relations.

**Framework rule**: Any relation edge may be reified into an entity when:
1. The edge needs properties of its own (date, location, certainty, etc.)
2. The edge needs to participate in relations (e.g., event A caused event B)
3. The edge is the object of discourse itself ("this marriage was brief")

**For the 65536 grid**: reification is always POSSIBLE but not always
NECESSARY. Simple edges (A depends-on B) don't need reification. Edges
with temporal or causal weight likely do. The mapping framework provides
a flag: "this edge is also an entity" with a pointer to its entity
encoding.

---

## 6. Design-time vs run-time (new)

`ontology.md` classifies each relation type as "mechanical" or "grounded."
This is correct but underspecified. The mechanical/grounded distinction
applies differently at two phases:

| Layer | Design-time (setup) | Run-time (use) |
|-------|-------------------|----------------|
| **Facets** | Which axes exist? **Requires judgment** | Once axes are fixed, reading a value off an axis is **mechanical** |
| **Hierarchy** | Which dependencies are real? **Requires honest declaration** | Once declared, topological sort is **mechanical** |
| **Salience** | Which data sources? What weighting? **Requires judgment** | Once data is loaded, ranking is **mechanical** |

**Why this matters**: The mechanical claim is a claim about run-time
determinism, not about the entire process. Every layer requires human
judgment (or external data) during setup. No framework removes that
requirement. What the framework does is:
1. Make the setup phase explicit (you MUST declare facets, dependencies,
   and salience sources — they cannot be left implicit)
2. Guarantee that once setup is done, run-time operations are fully
   deterministic (no ambiguity at decoding time)

This is the same "zero guesswork" property the 65536 grid has at the
reading stage — and the same honest boundary on what's achievable.

---

## 7. Closure under extension (new — the mechanism)

`ontology.md` claims: "new relation types, if one is ever genuinely found
missing, get added without requiring the other five to be redesigned."

This is the mechanism:

### For new relation types

A new relation type needs:
1. **Name**: unique identifier
2. **Definition**: what it captures (inclusion test)
3. **Existing overlap check**: does this reduce to, or combine, existing
   types? If yes, it's not a new type.
4. **Mechanical/grounded classification**: derivable from logic, or
   requires external measurement? Both are valid.
5. **Tier relevance**: does the new type participate in tier ordering
   (like is-a and part-of do), or is it non-tier (like equivalence and
   associative)? This determines whether `derive_tiers()` needs updating.
6. **Edge label set**: if the type has subtypes (like part-of has six),
   what are they?

**Existing code impact**:
- `derive_tiers()`: only needs updating if the new type is tier-relevant
- `pack_glyph()`/`unpack_glyph()`: only needs updating if storage format
  changes to include the new type
- Everything else: UNCHANGED. This is the closure property.

### For new facets

A new facet needs:
1. **Name**: unique identifier
2. **Value domain**: what values can this axis take?
3. **Disjointness check**: are values disjoint from existing facet values?
   If not, declare the overlap explicitly.
4. **Registration**: add to the framework's facet table

**Existing code impact**: ZERO. Facets are additive by construction.

### For new salience sources

A new salience source needs:
1. **Name**: unique identifier
2. **Source type**: empirical, designer-intended, or situational
3. **Data format**: what does the external data look like?
4. **Combination rule**: how does this source combine with others?

**Existing code impact**: ZERO — salience data is pluggable by design.

---

## 8. The complete three-layer model (synthesis)

This is the complete Point 1, stated as compactly as possible:

```
EVERY PIECE OF INFORMATION — every entity, every relation, every
attribute, every value — lives in a space defined by:

LAYER 1 — FACETS (orthogonal axes)
  Independent classification dimensions.
  Values are read simultaneously, not traversed sequentially.
  Each value can have its own is-a / part-of structure.
  Same entity may appear under multiple facet combinations.
  [Mechanical at run-time; judgment at design-time.]

LAYER 2 — HIERARCHIES (directional edges)
  Five relation types between entities:
    1. Equivalence    — same referent, different label
    2. Is-a           — subclass / superclass
    3. Instance-of    — individual / class
    4. Part-of        — component / whole (six subtypes)
    5. Associative    — everything else (typed labels carry inference)
  Types 2–4 participate in tier ordering (topological sort).
  Types 1 and 5 do not — they are cross-cutting links.
  [Mechanical at run-time for 2–4; grounded at run-time for 1 and 5.]

LAYER 3 — SALIENCE (rankings)
  Four sources, all providing the same interface (rankable scalar):
    a. Structural       — derived from graph (transitive dependents)
    b. Empirical        — from corpus frequency / prototype data
    c. Designer-intended — from scheme author's choices
    d. Situational       — from query context
  Salience combines across sources via configurable weighting.
  [Mechanical only after data is loaded.]

CROSS-CUTTING — PROPERTIES
  Has-property is an associative relation (type 5) with:
    - Typed label indicating the property dimension
    - Functional constraint (one value per dimension per entity)
    - Inheritance through is-a
  Property values are themselves entities — all five relation types apply.

CROSS-CUTTING — REIFICATION
  Any relation edge may be promoted to an entity when:
    - The edge needs properties
    - The edge needs to participate in relations
    - The edge is itself the subject of discourse
```

---

## 9. Bridge to Point 2

This structure is what the 65536 dot matrix must encode. The mapping
framework (Point 2) takes this logical structure and assigns:

- **Which dots represent entities** (the nodes of the graph)
- **Which dots represent relations** (the edges, typed and labeled)
- **Which dots represent properties** (entity + dimension → value)
- **Which dots represent reification** (edges promoted to entities)
- **Which dots represent facet values** (the axes themselves)
- **Which dots represent salience** (rankings per source)

And does so within the hard constraint of **one 65536-character glyph**
or a glyph sequence, maximizing semantic capacity per character.

The framework does not prescribe ONE mapping — it defines the space of
valid mappings. Point 2's job is to find the optimal one within that
space, given the 65536-point constraint.

[End of Point 1 — companion to ontology.md]

---

## Appendix A: Summary of differences from ontology.md

| Topic | ontology.md | This document |
|-------|------------|---------------|
| Equivalence | Term-level synonymy | + expression-level equivalence |
| Is-a / part-of | Separated but not precisely | Part-of: six subtypes identified |
| Instance-of | Conflated with is-a (gap) | + properties as enablers |
| Associative | Catch-all, edge labels mentioned | + typed label set with inference rules |
| Facets | Orthogonal axes described | + cross-facet identity, + facet-add mechanism |
| Salience | Structural vs empirical | + designer-intended, + situational |
| Properties | Not mentioned | Full treatment: functional, inherited, typed |
| Reification | Not mentioned | Rules for when edges become nodes |
| Design/run-time | Not distinguished | Mechanical claim scoped to run-time |
| Extension | Claimed without mechanism | Full extension API per type |
| Full three-layer model | Implicit | Made explicit with all cross-cuts |

## Appendix B: What has changed in the implementation gap table

| Gap | ontology.md status | Now |
|-----|--------------------|-----|
| Equivalence unhandled | Gap | Lexical: trivial. Expression-level: hard but named |
| Instance-of conflated | Gap | + Properties provide the enabling machinery |
| Associative unhandled | Gap | + Typed label set provides the structure |
| Empirical salience | Gap | + Designer-intended provides working alternative |
| Part-of conflated | Gap | Part-of has six subtypes; 65536 uses component-object |

All five remain implementation gaps. Each is now better bounded and more
precisely connected to the rest of the framework.
