# 65536 — Font and Ontology for Visual Knowledge Representation

**65,536** is a TrueType font (`65536-Glyph.ttf`) whose code points carry
meaning drawn from the O-OIS grammar — each of the 65,536 symbols is a
small picture standing for an entity kind, a relation, a meronymy
subtype, an epistemic tag, or a loading control. Where POINTS is
optimised for machines (fixed size, bit packing, parity), **65536 is
optimised for people** — pictures, hierarchy, immediate recognition.

The measured capacity of the font itself is future work (rendering
varies by viewer); the **grammar, hierarchy, and codec behaviour are
fully specified** and fully implemented here.

## Repository layout

| Path | Role |
|---|---|
| `65536-Glyph.ttf` | The complete 65,536-symbol TrueType font |
| `hierarchy.py` | The hierarchy codec — ordering/prioritising/categorising model |
| `hierarchy.jl` | Julia companion implementation of the same model |
| `payload_codec.py` | Payload encoding/decoding for glyph content |
| `content_store.py` | Content-addressed store for glyphs and fragments |
| `bootstrap_block.py` | Bootstrap block generator (first block of a chain) |
| `ontology.md`, `structure.md`, `hierarchy.md` | The three design documents: the structural theory of information, the structural framework, and the ingestion methodology |
| `loadbearing proof.md` | The proof document for the hierarchy's load-bearing claims |
| `font-visual-test.png` | Visual rendering check of the font |
| `experiments/` | `font_bitmap.py`, `glyph_protocol.py`, `two_glyph_test.py` |
| `test suite/` | Benchmarks and cross-language/cross-system benches; findings in `BENCHMARK_FINDINGS.md` |
| `jl/` | Julia helper sources |

## Quick start

Each module is runnable from the repository root:

```bash
python3 hierarchy.py        # hierarchy codec
python3 payload_codec.py    # payload encode/decode
python3 content_store.py    # content-addressed store
python3 bootstrap_block.py  # first-block bootstrap
```

The three documents are best read in this order:
`hierarchy.md` → `ontology.md` → `structure.md` (the discriminative,
concluded versions are `point1.md`/`point2.md` in the POINTS
repository, which supersede earlier drafts).

## Relationship to the ONE paper

65536 is one of the three instantiations of the O-OIS grammar in
"Maximum Semantic Capacity via the Ontology of Optimal Information
Structure" (2026). Its font, hierarchy codec, payload codec, and
content store demonstrate the same shared grammar in a human-facing,
image form — the "very large alphabet where every symbol is a whole
idea".

## License

MIT — see [`LICENSE`](LICENSE).
