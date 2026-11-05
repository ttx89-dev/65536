# 65536 Benchmark Findings & Enhancement Proposals

Generated: 2026-07-08

**Status note (2026-11-05, documentation pass):** emoji status markers were
converted to ASCII ([PASS]/[OK]/[PARTIAL]); §1.1's "Julia not in parity runner"
note is superseded — `parity_check.py` now exercises all three layers in Julia
and the full run passes 15/15 under Julia 1.12.6.

---

## 1. Parity Verification Status

### 1.1 Python vs Julia — Correctness (PASS)
All 15 cross-language parity tests pass:

| Layer | Tests | Python | Julia |
|-------|-------|--------|-------|
| Bootstrap Block | 7 (hex, parse, decompose ×5) | [PASS] | [PASS] (hex-identical) |
| Payload Codec | 4 (NONE write/read, SUM8 write/read) | [PASS] | [PASS] (hex-identical; verified 2026-11-05) |
| Content Store | 4 (FNV-1a hash, write, read ×2) | [PASS] | [PASS] (hex-identical; verified 2026-11-05) |

**Note (updated 2026-11-05):** `parity_check.py` does drive all three layers in
Julia today — payload write/read (NONE, SUM8) and content-store hash/write/read
run through `jl/run_payload_tests.jl` and `jl/run_content_tests.jl` and arrive
byte-identical. The note above predates that harness; kept for history — trust
this note for current truth.

**Run commands (verified 2026-11-05, from the repository root):**
- `python3 tests/parity_check.py` (Python + Julia) → 15 passed, 0 failed
- `python3 tests/parity_check.py --py` → 15 passed, 0 failed
- `python3 tests/parity_check.py --jl` → 15 passed, 0 failed

### 1.2 Python vs Julia — Speed (NOT YET BENCHMARKED)
No cross-language benchmark exists. `bench_performance.py` only benchmarks the
Python implementation. A `bench_cross_language.py` would be needed to compare
Python vs Julia throughput on equivalent workloads.

---

## 2. Cross-System Benchmark: 65536 vs CBOR

**File:** `bench_cross_system.py`
**Library:** `cbor2` (IETF standard binary format, mature C implementation)

### 2.1 Results Summary

| Dimension | 65536 | CBOR | Winner |
|-----------|-------|------|--------|
| Header size (fixed) | 267B | 63B (variable) | CBOR (4.2× smaller) |
| Payload serialize (64B) | 22.2µs | 0.96µs | CBOR (23× faster) |
| Payload read (64B) | 30.4µs | 0.96µs | CBOR (32× faster) |
| Payload serialize (256KB) | 39.3µs | 10.1µs | CBOR (3.9× faster) |
| Payload read (256KB) | 1040µs | 23µs | CBOR (45× faster) |
| Content write (64B) | 24.3µs | 8.3µs | CBOR (2.9× faster) |
| Content read (256KB) | 62ms | 30ms | CBOR (2× faster) |
| Storage overhead (490B payload) | +55.9% (764B) | +105.1% (1,005B) | **65536** |
| Raw CBOR overhead | — | +0.6% (493B) | CBOR |
| Content dedup (1000× same) | 99.9% | 99.9% | Tie |

### 2.2 Interpretation

**CBOR wins on throughput** across all layers because:
- It's a mature C extension (`_cbor2.CBOR.encode`)
- No content-addressing or DAG overhead
- No integrity verification built in
- Simple byte-string-in/byte-string-out

**65536 wins on storage efficiency** for payload stores because:
- Its descriptor table (6B per entry) is cheaper than CBOR's dict-based index
- The 267B bootstrap block is a fixed cost that amortizes to zero at scale

**65536 provides things CBOR fundamentally does not:**
- Content-addressed addressing (address → hash → content)
- DAG traversal and structural integrity
- Multi-hash support with slot-based addressing
- Cross-language binary parity (Python ↔ Julia byte-identical)

---

## 3. Enhancement Proposals

### 3.1 [PROPOSAL] Variable-size BootstrapBlock Header

**Current design:** Fixed 267 bytes — 12B preamble + 255B structured slots (of
which 244 are reserved/zeros).

**Proposal:** Make the structured section variable-length, so the header scales
with the address space it describes:

- **Minimum:** 12B preamble + 10B fields = ~22B (for a minimal config)
- **Maximum:** 12B preamble + 255B slots = 267B (full 65536 address space)
- **Mechanism:** Use preamble byte[10] (`reserved_preamble`) or a new field to
  declare `structured_slot_count`. Parse reads preamble first to learn the
  actual block size, then reads the remaining bytes.

**Assessment — NOT RECOMMENDED at this stage:**

| Argument | Weight |
|----------|--------|
| 267B is negligible overhead for any real payload (<< 1% at 64KB+) | Strong |
| Fixed size simplifies parsers — no two-phase read needed | Strong |
| Reserved slots are forward-compat, not waste — they let us add fields without breaking the format | Strong |
| Scaling would break existing golden vectors and all parsers | Strong |
| The preamble already encodes address_width (16 bits) — that's the natural "scale" indicator | Moderate |

**If we do want to make it variable:**
1. Commit to a `block_struct_size` byte in the preamble (replace `reserved_preamble`)
2. Update `parse()` to read preamble first, then remaining bytes
3. Update `to_bytes()` to only emit populated slots
4. Update `BLOCK_SIZE` constant to be a computed property
5. Update all consumers (payload_codec, content_store, Julia impl)
6. Regenerate golden vectors

**Verdict:** Defer unless we have a concrete use case where 267 bytes of header
becomes a bottleneck (e.g., embedded systems with < 1KB total storage).

### 3.2 [PROPOSAL] Cross-Language Speed Benchmark

Add a `bench_cross_language.py` that runs the same benchmark suite in both
Python and Julia and reports speed ratios. This would:
- Expose whether Julia's LLVM JIT gives meaningful speedup on the hot paths
- Guide optimization effort toward the slower implementation
- Be useful for deciding which implementation to use for production workloads

**Status:** Not started. `bench_cross_system.py` compares 65536 vs CBOR (both in
Python). No Python-vs-Julia benchmark exists.

### 3.3 [PROPOSAL] Extend parity_check.py Julia Coverage

Currently `--jl` only exercises bootstrap block. Add payload codec and content
store Julia parity tests to the runner so `--jl` covers all 15 tests.

### 3.4 [PROPOSAL] Fill Golden Vector Directory

`test suite/vectors/golden/` is empty. Generate golden binary vectors for all
three layers at known addresses/configs so cross-language tests have a fixed
reference to compare against, rather than just Python↔Julia pairwise.

### 3.5 [PROPOSAL] Python vs Julia Performance

No benchmark run yet. `bench_performance.py` measures Python. A Julia equivalent
(`jl/bench_performance.jl`) would let us quantify the JIT advantage.

---

## 4. Known Gaps (from MASTER_PLAN.md)

| Item | Status |
|------|--------|
| `test_cross_language.py` | Not created |
| `test_edge_cases.py` | Not created |
| `bench/` subdirectory | Not created |
| `demos/` | Not created |
| `experiments/` | Not created |
| `vectors/golden/` | Empty directory |
| Julia payload/content parity in runner | Missing |

---

## 5. Font Tooling

There is no font editing, glyph rendering, or character tooling anywhere in the
65536 project or in our session history. This appears to be a separate project
or task — no work has been done on it, and I don't have context on what
tooling/scripting you're referring to. Can you point me at the relevant
files or repo?
