# 65536 Test Suite — Master Architecture Plan
**Version 1.0 | July 2026**

---

## I. Design Philosophy

This test suite is not a QA artifact — it is a **binary format specification by empirical
demonstration**. Every test asserts that the 65536 framework behaves identically
across:

| Dimension | Assertion |
|-----------|-----------|
| **Determinism** | Same input → same bytes, every time |
| **Idempotency** | decode(encode(x)) == x for all valid x |
| **Cross-language parity** | Python bytes == Julia bytes for the same logical payload |
| **Round-trip integrity** | Content stored → retrieved → verified matches original |
| **Boundary resilience** | Edge cases (empty, maximal, pathological) are handled without data loss |
| **Agent stability** | Glyph protocol proves format survives subagent boundary |

## II. File Topology

All new files live under `test suite/`. The existing files are verbatim copies of
the originals and are **never modified**. New test files import from them.

```
test suite/
├── MASTER_PLAN.md            ← This document
├── framework.py              ← Test infrastructure (assertions, runner, golden)
├── run_all.py                ← Master runner: discovers & executes everything
│
├── test_bootstrap.py         ← Unit tests: DotMatrixBootstrap
├── test_payload.py           ← Unit tests: PayloadCodec
├── test_content.py           ← Unit tests: ContentStore256
├── test_integration.py       ← Cross-module pipeline tests
├── test_cross_language.py    ← Python ↔ Julia parity via serialization vectors
├── test_edge_cases.py        ← Adversarial / boundary / fuzz inputs
│
├── bench/
│   ├── bench_crc16.py        ← CRC-16 bit-loop vs LUT speed cross-language
│   ├── bench_topological.py  ← Topological sort scaling analysis
│   └── bench_all.py          ← Bench suite runner
│
├── demos/
│   ├── demo_full_pipeline.py ← Bootstrap→Payload→ContentStore lifecycle
│   ├── demo_dag_complex.py   ← Complex 10+ node dependency DAG
│   └── demo_content_identity.py ← Content identity & dedup exploration
│
├── experiments/
│   ├── glyph_protocol.py     ← Subagent round-trip (the "glyph experiment")
│   └── font_bitmap.py        ← Font character encoding via 65536
│
├── vectors/
│   ├── __init__.py           ← Vector loader
│   ├── golden_bootstrap.py   ← Known bootstrap block hex/checksums
│   ├── golden_crc16.py       ← CRC-16 test vectors (cross-ref)
│   └── vector_registry.py    ← Auto-gen tool: produces/goldens/vectors
│
├── data/                     ← Runtime-generated test data (gitignored)
│
├── bootstrap_block.py        ═══ VERBATIM COPY — DO NOT TOUCH ═══
├── payload_codec.py          ═══ VERBATIM COPY — DO NOT TOUCH ═══
├── content_store.py          ═══ VERBATIM COPY — DO NOT TOUCH ═══
└── jl/
    ├── bootstrap_block.jl    ═══ VERBATIM COPY — DO NOT TOUCH ═══
    ├── payload_codec.jl      ═══ VERBATIM COPY — DO NOT TOUCH ═══
    └── content_store.jl      ═══ VERBATIM COPY — DO NOT TOUCH ═══
```

## III. Framework Contract (`framework.py`)

All tests share a common infrastructure:

```python
class TestResult:
    """Immutable test outcome: name, passed, detail, metrics."""
```

```python
class GoldenRegistry:
    """Load/save/compare golden files for cross-session regression."""
```

Key functions:
- `assert_bytes_equal(a, b, ctx)` — byte-level comparison with hex diff on failure
- `assert_roundtrip(encoder, decoder, value, ctx)` — encode→decode→check
- `run_tests_in_module(mod) → list[TestResult]` — discover `def test_*()` functions
- `print_report(results)` — formatted terminal output

## IV. Test Categories

### 4.1 Unit Tests (discovery)

Each module gets exhaustive tests matching its public API surface:

| Module | Tests | Key Assertions |
|--------|-------|----------------|
| `bootstrap_block` | 12+ | Block creation, field access, serialization,
  re-parse identity, CRUD slots (0–254), 3 read semantics, checksum
  recomputation, zero-block edge case, 255-slot boundary |
| `payload_codec`  | 15+ | Entry creation (all types), heap encoding/decoding,
  descriptor encoding/decoding, topological sort (chain/fork/diamond/
  disconnected), CRC-16, FNV-1a, flat repr, len, pack/unpack pipeline |
| `content_store`  | 12+ | Store creation, put/get keys, put/get CID,
  content identity (CID), dedup (same content, one CID), overwrite,
  missing-key behavior, compression toggle, store export/import |

### 4.2 Integration Tests

- **Pipeline:** Bootstrap → Insert payload descriptor → Content-store a blob →
  Extract → Verify
- **Bootstrap→Payload link:** Payload descriptor lives in bootstrap fields;
  verify cross-module consistency
- **Slot exhaustion:** Fill 255 slots, verify slot 256 raises

### 4.3 Cross-Language Parity

Python and Julia implementations must produce **identical binary output**
for the same logical inputs.

**Protocol:**
1. Define a suite of logical test cases (e.g., "bootstrap block with CID
   `b"abc"` and 3 slots filled")
2. Python serializes → produces hex string A
3. Julia serializes (same logical values) → produces hex string B
4. Assert A == B

**Known discrepancy:** Julia source files reference `Base.Crypto.crc32c`
which does not exist in Julia 1.12.6. The test MUST detect this and:
- Report it as a portability finding (not a test FAILURE)
- Provide the corrected import (`CRC32c.crc32c`) as a verified alternative
- Document the discrepancy in the cross-language report

### 4.4 Edge Cases & Fuzzing

| Category | Test |
|----------|------|
| Zero-length | Empty payload, empty heap, empty DAG |
| Max-size | 255-slot bootstrap, 2^16-byte heap, deep nesting |
| Invalid CRC | Flip bit in descriptor, verify detection |
| Invalid magic | Wrong magic bytes, verify rejection |
| Type confusion | Wrong type field for descriptor content |
| Unicode | CJK characters in payload fields |
| Binary | Null bytes, high-bit (>127) in strings |
| Pathological DAG | Circular dependencies, self-reference |

### 4.5 Benchmarks

| Benchmark | Method | Metric |
|-----------|--------|--------|
| CRC-16 bit-loop | 100K iterations, Python & Julia | μs/op |
| CRC-16 LUT | Same workload | μs/op, speedup ratio |
| Topological sort | n = 10, 100, 1000 in chain/random/bush | ms |
| Content dedup | Insert 1000 entries with 100 unique CIDs | dedup ratio |
| Payload encode/decode | 1000 entries | μs/entry |

## V. The Glyph Experiment

### Concept

A "glyph" is a self-contained piece of data encoded into the 65536 framework.
The glyph experiment proves the format is **deterministic**, **self-describing**,
and **stable across agent boundaries**.

### Protocol (3-phase)

**Phase 1 — Glyph Minting (us):**
1. Choose source data: a short text string
2. Create a PayloadDescriptor containing the string as `descriptor_text`
3. Serialize to bytes via `pack_descriptor()`
4. Record the hex + CRC-16

**Phase 2 — Subagent Translation:**
1. Send the serialized bytes to a subagent with instructions to:
   a. Decode using `unpack_descriptor()`
   b. Read the `descriptor_text` field
   c. Reverse the text string
   d. Create a NEW descriptor with reversed text
   e. Serialize and return the bytes
2. Receive the transformed bytes back

**Phase 3 — Verification (us):**
1. Decode the returned bytes
2. Verify: decoded text == reversed original
3. Verify: CRC-16 is valid (format integrity)
4. Verify: round-trip succeeded with correct transformation

### Success Criteria

- [ ] Subagent can decode bytes without prior context
- [ ] Text reversal transformation correct
- [ ] Returned bytes have valid CRC-16
- [ ] Round-trip proves format stability across agent boundary

### Why Not Just JSON?

Because JSON is not:
- **Deterministic** (key ordering, whitespace varies)
- **Self-describing** (need schema to interpret)
- **Binary-round-trippable** (no built-in CRC, padding, or structural integrity check)

65536's binary format encodes structure + data + integrity in one artifact.
The glyph experiment demonstrates this concretely.

## VI. Font Bitmap Experiment

### Concept

Define a set of bitmap glyphs as 65536 content entries, proving the framework
can store and retrieve binary image data.

### Protocol

1. Define a set of 8×8 pixel bitmap characters (e.g., 'A', 'B', 'C')
   as raw byte arrays (8 bytes each, 1 bit per pixel)
2. Store each via `ContentStore256.put_blob(cid, bitmap_bytes)`
3. Retrieve via `ContentStore256.get(key)` and verify byte-for-byte match
4. Have a subagent generate a new bitmap glyph, store it, return the CID
5. Verify the new glyph can be retrieved and rendered conceptually

### Bitmap Format

```
8 bytes per character, MSB-first row-major:
Row 0: b01000010  (2 bytes: two dots in the middle)
Row 1: b01100110  (4 dots)
...  etc
```

This is a recognizable letter rendered in a grid — font, not just data.

## VII. Runner Protocol (`run_all.py`)

```
$ python3 run_all.py
═══════════════════════════════════════════════════════
  65536 Test Suite v1.0 — Comprehensive Validation
═══════════════════════════════════════════════════════
[FRAMEWORK]  framework.py loaded | Python 3.14.3
───────────────────────────────────────────
  UNIT TESTS
───────────────────────────────────────────
  ✓ test_bootstrap.test_block_creation (2.3ms)
  ✓ test_bootstrap.test_slot_crud (4.1ms)
  ... (all test results)
───────────────────────────────────────────
  INTEGRATION
───────────────────────────────────────────
  ✓ test_integration.test_pipeline
  ...
───────────────────────────────────────────
  CROSS-LANGUAGE PARITY
───────────────────────────────────────────
  ✓ test_cross_language.test_bootstrap_parity
  ⚠ test_cross_language.test_julia_crc_compat [NOT RUN — no Base.Crypto in 1.12]
  ...
───────────────────────────────────────────
  EDGE CASES
───────────────────────────────────────────
  ✓ test_edge_cases.test_zero_length
  ...
───────────────────────────────────────────
  BENCHMARKS
───────────────────────────────────────────
  CRC-16 bit-loop:   12.34 μs/op  (Python)
  CRC-16 LUT:         0.56 μs/op  (speedup 22.0×)
  ...
───────────────────────────────────────────
  EXPERIMENTS
───────────────────────────────────────────
  ✓ glyph_protocol.test_glyph_mint
  ✓ glyph_protocol.test_glyph_roundtrip
  ✓ font_bitmap.test_bitmap_storage
═══════════════════════════════════════════════════════
  RESULTS: 47 passed, 0 failed, 2 skipped, 3 benchmarks
═══════════════════════════════════════════════════════
```

## VIII. Naming & Style Conventions

| Convention | Rule |
|------------|------|
| Test functions | `def test_<thing>_<condition>()` |
| Test modules | `test_<module>.py` |
| Benchmarks | `bench/bench_<thing>.py` runner + `bench_all.py` |
| Demos | `demos/demo_<topic>.py` |
| Experiments | `experiments/<experiment>.py` |
| Golden vectors | `vectors/golden_<topic>.py` |
| Return type | All test functions return `list[TestResult]` |
| No side effects | Tests never modify filesystem unless documented |
| Deterministic | No random values unless seeded explicitly |

## IX. Known Issues / Caveats

1. **Julia CRC compatibility:** Source files reference `Base.Crypto.crc32c`
   which does not exist in Julia 1.12.6. The stdlib `CRC32c` module provides
   `CRC32c.crc32c()` as a drop-in. Tests document this and verify the
   alternative.
2. **No Base64 in Julia 1.12:** Python's base64-encoded key serialization
   has no direct Julia equivalent. Testing uses hex encoding as the
   language-neutral format.
3. **Compression:** Content store compression is toggleable but not tested
   across languages (Julia implementation doesn't import compression libs).
4. **Floating-point in payload:** Payload entries store floats as binary;
   cross-language floating-point parity may differ at the last bit due to
   differences in `struct.pack('d', ...)` vs `reinterpret(Float64, ...)`.
5. **File locking:** Content store file operations are not tested for
   concurrent access (single-thread assumption).
