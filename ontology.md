# The structural theory of information

Not digital. Not about glyphs, bits, or the 65536-point spec. This is the
layer underneath all of that — the answer to: when any two pieces of
information are related at all, what are the *kinds* of relation that
can hold between them, and which of those kinds can be derived by pure
logic versus which require going out into the world and measuring
something. Point 2 — the dot-matrix mapping — is downstream of this and
depends on getting this right first.

## The method, stated plainly

This isn't proposed from scratch. It's a convergence check: library
science, formal ontology, and cognitive linguistics each independently
spent the better part of a century on exactly this question, for
different practical reasons (organizing physical books, building
machine-reasoning systems, explaining how human categories actually
behave) — and they converged on the same small set of relation types.
Independent convergence across fields that weren't talking to each other
is real evidence a structure is load-bearing rather than arbitrary. That
convergence is what's being reported here, pressure-tested once more for
gaps, not invented fresh.

## Five relation types

Every meaningful connection between two pieces of information is one of
these five. Mixing them up — forcing an associative relation into a
hierarchy because hierarchy is the only tool at hand — is the classic,
well-documented failure mode in ontology engineering, which is exactly
why keeping them separate matters.

**1. Equivalence** — two labels, one referent. "Car" and "automobile."
The classic library-science pairing is USE/UF (use this term / used
for) — a preferred term and its synonyms, collapsed to one entry.
*Mechanical or grounded:* mechanical once known, but *discovering* that
two things are equivalent is not always mechanical — it can require
world knowledge. **This is currently unhandled anywhere in what's been
built.** Content-addressing collapses byte-identical content; it has no
mechanism for two different words that mean the same thing. Real gap,
worth naming plainly rather than glossing over.

**2. Is-a / subclass-of** — genus-differentia, Aristotle's original
formulation: define a thing by its nearest general category plus what
distinguishes it. Same shape in Linnaean taxonomy, same shape in
WordNet's hypernym trees. Test: "is every X necessarily a Y" — a mammal
is necessarily an animal, so mammal is-a animal holds.
*Mechanical:* yes, once dependencies are honestly declared —
`derive_tiers()` already computes exactly this, just labeled generically
as "depends-on."

**3. Instance-of** — an individual belongs to a class, but is not a
subtype of it. France is an instance of "country," not a kind of
country the way "island nation" is a kind of country — France doesn't
itself have further subtypes underneath it the way a class does. Formal
ontology (description logics, OWL, RDF Schema) keeps this as a
structurally distinct edge — `rdf:type` versus `rdfs:subClassOf` — for
exactly this reason: collapsing the two produces a knowledge structure
that implies wrong things about individuals. Test: "does X have possible
subtypes of its own within this scheme" — if no, it's an instance, not a
subclass. *Mechanical:* yes, the same way is-a is, but **currently
conflated with is-a in what's been built** — `derive_tiers()` doesn't
distinguish them, which is a second real, specific gap.

**4. Part-of (meronomy)** — compositional, whole-part, distinct from
is-a since Leśniewski formalized it: a wheel is part of a car, but a
wheel is not a kind of car. Test: "is X a component of Y, not a type of
Y." *Mechanical:* yes — and this is the more precise name for what
`derive_tiers()` is actually computing when a root morpheme must exist
before an affixed word can. That's compositional dependency, meronomy
with a construction-order constraint on top, not is-a. Worth being exact
about, since "hierarchy" was being used loosely to cover both 2 and 4
before this pass.

**5. Associative** — related, but not hierarchical and not equivalent.
Thesaurus construction (the current standard is ISO 25964, superseding
the older ISO 2788) keeps this as its own bucket precisely because
forcing every real-world relation into is-a or part-of breaks down fast
— "drought" relates to "famine" without either containing the other.
Associative relations can carry a label — causal ("causes"), temporal
("precedes"), locative ("located in"), oppositional (antonymy) — without
needing separate top-level categories for each; the label is metadata on
the edge, not a new kind of edge. *Mechanical:* no — *that* two things
are associated, and how strongly, is a fact about the world, not
something derivable from the two concepts alone. **Also currently
unhandled.**

One more, orthogonal to all five above rather than a sixth member of the
list: **facets** — independent classification dimensions that get read
simultaneously rather than traversed in sequence, Ranganathan's Colon
Classification being the canonical case (a book is subject × place ×
time × form, all at once, not nested). This is not a relation between
two pieces of information — it's a statement about how many independent
axes a single classification scheme has. Tier × category × index, built
this whole session, is a small instance of exactly this pattern — arrived
at independently, unnamed as such until a few rounds ago. That
convergence, unplanned, is itself a small piece of evidence the pattern
is real rather than a coincidence of this project's design choices.

## The cross-cutting layer: salience

Every relation above answers "how does X connect to Y." None of them
answer "which X matters most." That's a separate axis, and it cannot be
derived from the relations themselves — it requires an external,
empirical source: corpus frequency (Zipf's law — usage frequency follows
a measurable power law, not a logical one), prototype centrality (Rosch
— some category members are cognitively more central than others, e.g.
robin more than penguin for "bird," as a measured fact about human
categorization, not a deduced one), or markedness (the unmarked, default
form of a category versus its marked variants). `derive_priority()`
computes one specific, real instance of this — transitive reliance
within an already-known dependency graph — but that's structural
salience, derived from graph shape. The fully general version, salience
grounded in external frequency or prevalence data, doesn't exist yet in
what's built. Real, specific, third gap.

## Where this stands

This is the most refined version of this synthesis this pass can
produce — converged from roughly a century of independent work across
three fields that weren't in dialogue with each other, which is real
evidence, not just a well-organized guess. What it is not, and
shouldn't be allowed to quietly become, is a claim of provable
completeness. The same limit named earlier in this project for the
65536-point address space applies one level up here too: no finite,
closed categorization scheme can be proven complete over an
open-ended subject. What's being claimed is closure under extension —
new relation types, if one is ever genuinely found missing, get added
without requiring the other five to be redesigned — not a guarantee
that five is the final number forever.

## Bridge to what's already built

| Relation | Built? | Where |
|---|---|---|
| Is-a / subclass-of | Yes | `derive_tiers()` — labeled generically as dependency |
| Part-of (meronomy) | Yes, same mechanism as is-a | `derive_tiers()` — the two are currently conflated |
| Instance-of | No | Not distinguished from is-a anywhere |
| Equivalence | No | Content-addressing only catches byte-identical, not synonymous |
| Associative | No | No mechanism exists for "related, not hierarchical" |
| Facet | Yes | tier × category × index, `bootstrap_block.py` onward |
| Structural salience | Yes | `derive_priority()` — transitive reliance within a known graph |
| Empirical salience | No | No external frequency/prevalence grounding exists |

Five real gaps, all precisely named rather than papered over, and all
of them addressable without touching the parts that already work —
which is exactly the "closure under extension" property this whole
framework has been built to have from the bootstrap block onward.
