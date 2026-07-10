"""
bench_performance.py — throughput & latency benchmarks, 65535-point framework
═══════════════════════════════════════════════════════════════════════════════

Measures: write/read latency, heap growth, throughput at scale for all three
layers. Uses the framework timer for consistent reporting.

Run:   python bench_performance.py

Each benchmark runs in isolation (fresh Store per trial) to avoid interference.
═══════════════════════════════════════════════════════════════════════════════
"""

import sys, os, math, struct, time
sys.path.insert(0, os.path.dirname(__file__))

from framework import Timer, print_report, assert_equal
from bootstrap_block import BootstrapBlock, BootstrapError, ChecksumAlgo, BLOCK_SIZE
from payload_codec import Store as PayloadStore, EntryOutcome, PayloadError
from content_store import Store as ContentStore, fnv1a_64


# ═══════════════════════════════════════════════════════════════════════════
# Configuration
# ═══════════════════════════════════════════════════════════════════════════

N_WARMUP = 5            # warmup iterations per measurement
N_TRIALS = 50           # measurement trials per point
N_LARGE_TRIALS = 10     # for slower benchmarks

# Sizes
SMALL_PAYLOAD = b"x" * 64
MEDIUM_PAYLOAD = b"x" * 1024
LARGE_PAYLOAD = b"x" * 65536

# Scales
SCALE_SMALL = 100
SCALE_MEDIUM = 1000
SCALE_LARGE = 10000


def _timed(fn, trials=N_TRIALS, warmup=N_WARMUP):
    """Run fn() trials times, return {(min, p50, p95, max, mean)} in seconds."""
    for _ in range(warmup):
        fn()
    elapsed = []
    for _ in range(trials):
        t0 = time.perf_counter()
        fn()
        elapsed.append(time.perf_counter() - t0)
    elapsed.sort()
    n = len(elapsed)
    return {
        "min": elapsed[0],
        "p50": elapsed[n // 2],
        "p95": elapsed[int(n * 0.95)],
        "max": elapsed[-1],
        "mean": sum(elapsed) / n,
        "trials": n,
    }


def _fmt_us(d):
    """Format timing dict as microseconds."""
    return {
        "min_us": d["min"] * 1e6,
        "p50_us": d["p50"] * 1e6,
        "p95_us": d["p95"] * 1e6,
        "max_us": d["max"] * 1e6,
        "mean_us": d["mean"] * 1e6,
    }


R = "\033[0m"
G = "\033[92m"
Y = "\033[93m"
B = "\033[94m"
C = "\033[96m"


# ═══════════════════════════════════════════════════════════════════════════
# 1. Bootstrap Block Benchmarks
# ═══════════════════════════════════════════════════════════════════════════

def bench_bootstrap_serialize():
    """BootstrapBlock.to_bytes() throughput."""
    bb = BootstrapBlock()
    t = _timed(lambda: bb.to_bytes())
    return _fmt_us(t)


def bench_bootstrap_parse():
    """BootstrapBlock.parse() throughput."""
    data = BootstrapBlock().to_bytes()
    t = _timed(lambda: BootstrapBlock.parse(data))
    return _fmt_us(t)


def bench_bootstrap_decompose():
    """Address decomposition throughput."""
    bb = BootstrapBlock()
    addrs = [0x0000, 0x0001, 0x1234, 0xABCD, 0xFFFF]
    t = _timed(lambda: [bb.decompose_address(a) for a in addrs])
    return _fmt_us(t)


def bench_bootstrap_tamper_reject():
    """Tamper detection overhead — constructing a known-bad block and
    catching the expected BootstrapError."""
    data = bytearray(BootstrapBlock().to_bytes())
    data[50] ^= 0xFF
    bad = bytes(data)
    t = _timed(lambda: _expect_bootstrap_error(bad))
    return _fmt_us(t)


def _expect_bootstrap_error(bad):
    try:
        BootstrapBlock.parse(bad)
    except BootstrapError:
        pass
    else:
        raise AssertionError("expected parse failure")


# ═══════════════════════════════════════════════════════════════════════════
# 2. Payload Store Benchmarks
# ═══════════════════════════════════════════════════════════════════════════

def bench_payload_write(size, algo=ChecksumAlgo.CRC16):
    """Write latency vs payload size."""
    bb = BootstrapBlock(checksum_algo=algo)
    store = PayloadStore(bb)
    addr = store.compose(1, 1, 0x10)
    content = b"x" * size
    return _timed(lambda: store.write(addr, content))


def bench_payload_read(size, algo=ChecksumAlgo.CRC16):
    """Read latency vs payload size."""
    bb = BootstrapBlock(checksum_algo=algo)
    store = PayloadStore(bb)
    addr = store.compose(1, 1, 0x10)
    store.write(addr, b"x" * size)
    return _timed(lambda: store.read(addr))


def bench_payload_write_ordered(n_items):
    """write_ordered latency for chain of N items (strict chain topology)."""
    bb = BootstrapBlock()
    store = PayloadStore(bb)
    items = []
    prev = None
    for i in range(n_items):
        addr = store.compose(1, 1, i & 0xFF)
        if i < 256:
            deps = [prev] if prev is not None else []
            items.append((addr, b"payload", deps))
        prev = addr

    def _run():
        s2 = PayloadStore(bb)
        s2.write_ordered(items)

    return _timed(_run)


def bench_payload_fill(n_writes):
    """Sustained write throughput: fill N entries at distinct addresses."""
    addrs = []
    n = min(n_writes, 0xFF)
    # compose manually: (tier << (cat_bits+idx_bits)) | (cat << idx_bits) | idx
    for i in range(n):
        addrs.append((1 << 12) | (1 << 8) | ((i + 1) & 0xFF))

    def _run():
        s = PayloadStore(BootstrapBlock(checksum_algo=ChecksumAlgo.NONE))
        for a in addrs:
            s.write(a, b"x" * 32)

    return _timed(_run, trials=max(5, N_TRIALS // max(1, n_writes // 10)))


def bench_payload_checksum_overhead():
    """Compare write latency across algo variants."""
    results = {}
    for algo in (ChecksumAlgo.NONE, ChecksumAlgo.SUM8, ChecksumAlgo.CRC16):
        r = bench_payload_write(1024, algo)
        algo_name = algo.name
        results[algo_name] = _fmt_us(r)
    return results


# ═══════════════════════════════════════════════════════════════════════════
# 3. Content Store Benchmarks
# ═══════════════════════════════════════════════════════════════════════════

def bench_content_write(size):
    """Content store write latency vs payload size (fresh store per trial)."""
    content = b"x" * size
    def _run():
        s = ContentStore(BootstrapBlock())
        s.write(s.compose(1, 1, 0x20), content)
    return _timed(_run)


def bench_content_read(size):
    """Content store read latency vs payload size (fresh store per trial)."""
    content = b"x" * size
    def _run():
        s = ContentStore(BootstrapBlock())
        s.write(s.compose(1, 1, 0x20), content)
        s.read(s.compose(1, 1, 0x20))
    return _timed(_run)


def bench_content_dedup_gain():
    """Measure heap savings from deduplication: write same content to N
    addresses, report heap growth (should be ~1× despite N writes)."""
    bb = BootstrapBlock()
    store = ContentStore(bb)
    content = b"dedup-test-content"
    addrs = _content_addrs(store, SCALE_MEDIUM)
    heap_before = len(store.heap)
    for a in addrs:
        store.write(a, content)
    heap_after = len(store.heap)
    # Without dedup: SCALE_MEDIUM * len(content) bytes
    naively = SCALE_MEDIUM * len(content)
    actual = heap_after - heap_before
    savings_pct = (1 - actual / naively) * 100 if naively > 0 else 0
    return {
        "writes": SCALE_MEDIUM,
        "naive_bytes": naively,
        "actual_bytes": actual,
        "savings_pct": round(savings_pct, 1),
    }


def _content_addrs(store, n):
    """Generate n unique content store addresses.
    Uses raw 16-bit addresses starting at 0x1100 to avoid (tier=0,category=0)
    reserved range while staying within the valid address space."""
    BASE = 0x1100  # tier=1, category=1, index=0
    return [BASE + i for i in range(n)]


def bench_content_dedup_mixed():
    """Dedup with mixed content: 10% duplicate content, 90% unique."""
    bb = BootstrapBlock()
    store = ContentStore(bb)
    N = SCALE_MEDIUM
    unique_count = int(N * 0.9)
    dup_count = N - unique_count
    content_unique = [b"unique-" + str(i).encode() * 4 for i in range(unique_count)]
    content_dup = b"shared-content-block"
    addrs = _content_addrs(store, N)

    heap_before = len(store.heap)
    for i, c in enumerate(content_unique):
        store.write(addrs[i], c, depends_on=[])
    for i in range(dup_count):
        store.write(addrs[unique_count + i], content_dup, depends_on=[])

    heap_growth = len(store.heap) - heap_before
    naive = sum(len(c) for c in content_unique) + dup_count * len(content_dup)
    savings = (1 - heap_growth / naive) * 100 if naive > 0 else 0

    return {
        "total_writes": N,
        "unique_writes": unique_count,
        "duplicate_writes": dup_count,
        "naive_bytes": naive,
        "actual_bytes": heap_growth,
        "savings_pct": round(savings, 1),
    }


def bench_content_refcount_stress():
    """Refcounting correctness under stress: write same content to many
    addresses, then delete half, verify refcounts."""
    bb = BootstrapBlock()
    store = ContentStore(bb)
    content = b"refcount-stress"
    addrs = _content_addrs(store, SCALE_LARGE)

    # Write all
    h = None
    for a in addrs:
        h = store.write(a, content)

    assert h is not None
    record = store.content_table[h]
    expected = len(addrs)
    assert record.refcount == expected, \
        f"refcount {record.refcount} != {expected}"

    # Delete half
    for a in addrs[:len(addrs) // 2]:
        store.delete(a)

    expected_after = expected // 2
    assert record.refcount == expected_after, \
        f"refcount after partial delete {record.refcount} != {expected_after}"

    return {
        "writes": len(addrs),
        "expected_refcount": expected,
        "after_half_delete": record.refcount,
    }


def bench_content_write_with_deps(depth=8, width=2):
    """Content store write latency for an entry with N dependencies."""
    n_deps = depth * width
    dep_content = b"dep"

    def _run():
        s = ContentStore(BootstrapBlock())
        # Build dependency tree — deps at indices 0x30..0x3F+ (up to 64)
        dep_addrs = []
        for i in range(n_deps):
            a = s.compose(1, 1, 0x30 + i)
            s.write(a, dep_content)
            dep_addrs.append(a)
        # Main entry in a separate slot (not overlapping dep range)
        addr = s.compose(1, 1, 0x70)
        s.write(addr, b"payload", depends_on=dep_addrs)

    t = _timed(_run, trials=N_TRIALS)
    return _fmt_us(t)


# ═══════════════════════════════════════════════════════════════════════════
# 4. Scale Stress Tests
# ═══════════════════════════════════════════════════════════════════════════

def stress_payload_large_payload():
    """Write and read very large entries (up to 1 MB) in payload store."""
    bb = BootstrapBlock(checksum_algo=ChecksumAlgo.CRC16)
    store = PayloadStore(bb)
    sizes = [1024, 4096, 16384, 65536, 262144]  # 1K to 256K
    results = {}
    for size in sizes:
        content = b"L" * size
        addr = store.compose(1, 1, 0x60)
        t0 = time.perf_counter()
        store.write(addr, content)
        tw = time.perf_counter() - t0

        t0 = time.perf_counter()
        o, d, _ = store.read(addr)
        tr = time.perf_counter() - t0

        assert o == EntryOutcome.VALID and d == content
        heap_used = len(store.heap)
        results[size] = {
            "write_ms": round(tw * 1000, 3),
            "read_ms": round(tr * 1000, 3),
            "heap_bytes": heap_used,
        }
    return results


def stress_content_heap_growth():
    """Heap growth pattern with unique vs duplicate writes."""
    bb = BootstrapBlock()
    store = ContentStore(bb)
    growth = {"unique": [], "dup": []}

    # Write 100 unique entries
    for i in range(100):
        j = i + 0x100
        store.write(store.compose((j >> 8) & 0xF, (j >> 4) & 0xF, j & 0xFF),
                    b"unique-" + str(i).encode() * 8)
        growth["unique"].append(len(store.heap))

    # Write 100 duplicate entries (same content) to unique addresses
    for i in range(100):
        j = 0x100 + 100 + i
        store.write(store.compose((j >> 8) & 0xF, (j >> 4) & 0xF, j & 0xFF),
                    b"duplicate-content-benchmark")
        growth["dup"].append(len(store.heap))

    return growth


def stress_many_dep_deps():
    """Write entries with up to 255 dependencies."""
    bb = BootstrapBlock(checksum_algo=ChecksumAlgo.NONE)
    store = PayloadStore(bb)

    # Create 255 valid dep entries (some overlap due to 8-bit index wrap)
    for i in range(255):
        store.write(store.compose(1, 1, i & 0xFF), b"d")

    addr = store.compose(3, 3, 3)
    many_deps = [store.compose(1, 1, i & 0xFF) for i in range(255)]

    t = _timed(lambda: store.write(addr, b"many-dep payload", depends_on=many_deps),
               trials=N_TRIALS)
    return _fmt_us(t)


# ═══════════════════════════════════════════════════════════════════════════
# Report
# ═══════════════════════════════════════════════════════════════════════════

def _print_header(title):
    print()
    print(f"{C}{'═' * 72}{R}")
    print(f"{B}  {title}{R}")
    print(f"{C}{'═' * 72}{R}")


def _print_timing(label, d):
    print(f"  {label:<40s}  min={d['min_us']:8.2f}µs  "
          f"p50={d['p50_us']:8.2f}µs  p95={d['p95_us']:8.2f}µs  "
          f"max={d['max_us']:8.2f}µs  (n={d.get('trials', '')})")


def run_all():
    print(f"{G}65535-POINT FRAMEWORK — PERFORMANCE BENCHMARKS{R}")
    print(f"{C}{'─' * 72}{R}")
    print(f"  python: {sys.version.split()[0]}")
    print(f"  platform: {sys.platform}")
    print(f"  trials: {N_TRIALS}  warmup: {N_WARMUP}")
    print(f"  small={len(SMALL_PAYLOAD)}B  med={len(MEDIUM_PAYLOAD)}B  large={len(LARGE_PAYLOAD)}B")
    print()

    # ── 1. Bootstrap ────────────────────────────────────────────
    _print_header("1. Bootstrap Block (267-byte fixed block)")

    t = bench_bootstrap_serialize()
    _print_timing("serialize (to_bytes)", t)

    t = bench_bootstrap_parse()
    _print_timing("parse (from_bytes)", t)

    t = bench_bootstrap_decompose()
    _print_timing("decompose address (5 addresses)", t)

    t = bench_bootstrap_tamper_reject()
    _print_timing("tamper detection (parse + reject)", t)

    # ── 2. Payload Store ────────────────────────────────────────
    _print_header("2. Payload Store (descriptor-table + heap)")

    for label, size in [("write — 64B", 64), ("write — 1KB", 1024),
                        ("write — 64KB", 65536)]:
        t = _fmt_us(bench_payload_write(size, ChecksumAlgo.NONE))
        _print_timing(label, t)

    for label, size in [("read — 64B", 64), ("read — 1KB", 1024),
                        ("read — 64KB", 65536)]:
        t = _fmt_us(bench_payload_read(size, ChecksumAlgo.NONE))
        _print_timing(label, t)

    # Checksum overhead
    ck = bench_payload_checksum_overhead()
    print(f"\n  Checksum overhead (write 1KB):")
    for algo, d in ck.items():
        print(f"    {algo:<12s}  {d['mean_us']:8.2f}µs mean  "
              f"(min={d['min_us']:.2f}  p95={d['p95_us']:.2f})")

    # write_ordered at scale
    t = _fmt_us(bench_payload_write_ordered(10))
    _print_timing("write_ordered (10-chain)", t)

    t = _fmt_us(bench_payload_write_ordered(100))
    _print_timing("write_ordered (100-chain)", t)

    # Sustained throughput
    t = _fmt_us(bench_payload_fill(100))
    _print_timing("fill 100 entries (32B each)", t)

    # Large payload stress
    _print_header("3. Large Payload Stress")
    large = stress_payload_large_payload()
    print(f"  {'Size':>10s}  {'Write ms':>10s}  {'Read ms':>10s}  {'Heap':>12s}")
    print(f"  {'─' * 10}  {'─' * 10}  {'─' * 10}  {'─' * 12}")
    for size, r in large.items():
        h = r["heap_bytes"]
        hstr = f"{h/1024:.1f}KB" if h >= 1024 else f"{h}B"
        print(f"  {size:>10d}  {r['write_ms']:>10.3f}  {r['read_ms']:>10.3f}  {hstr:>12s}")

    # Many-dependency write
    t = stress_many_dep_deps()
    _print_timing("write with 255 deps", t)

    # ── 3. Content Store ────────────────────────────────────────
    _print_header("4. Content Store (content-addressed)")

    for label, size in [("write — 64B", 64), ("write — 1KB", 1024),
                        ("write — 64KB", 65536)]:
        t = _fmt_us(bench_content_write(size))
        _print_timing(label, t)

    for label, size in [("read — 64B", 64), ("read — 1KB", 1024),
                        ("read — 64KB", 65536)]:
        t = _fmt_us(bench_content_read(size))
        _print_timing(label, t)

    # Dedup
    dedup = bench_content_dedup_gain()
    print(f"\n  Dedup gain ({dedup['writes']}× same content):")
    print(f"    Naive: {dedup['naive_bytes']:,}B  Actual heap growth: "
          f"{dedup['actual_bytes']:,}B  Savings: {dedup['savings_pct']}%")

    dedup2 = bench_content_dedup_mixed()
    print(f"\n  Mixed dedup ({dedup2['total_writes']} writes, "
          f"{dedup2['duplicate_writes']} duplicate):")
    print(f"    Naive: {dedup2['naive_bytes']:,}B  Actual: "
          f"{dedup2['actual_bytes']:,}B  Savings: {dedup2['savings_pct']}%")

    # Refcounting
    rc = bench_content_refcount_stress()
    print(f"\n  Refcount stress ({rc['writes']} writes, delete half):")
    print(f"    Initial refcount: {rc['expected_refcount']}")
    print(f"    After half-delete: {rc['after_half_delete']}")

    # Write with deps
    t = bench_content_write_with_deps(depth=8, width=2)
    _print_timing("write with 16 deps", t)

    t = bench_content_write_with_deps(depth=32, width=2)
    _print_timing("write with 64 deps", t)

    # Heap growth pattern
    _print_header("5. Heap Growth Pattern (Content Store)")
    growth = stress_content_heap_growth()
    print(f"  After 100 unique writes: {growth['unique'][-1]:,} heap bytes "
          f"(+{growth['unique'][0] if len(growth['unique']) > 0 else 0} initial)")
    print(f"  After +100 duplicate writes: {growth['dup'][-1]:,} heap bytes "
          f"(+{growth['dup'][-1] - growth['unique'][-1]} — should be 0)")
    print()

    # ── Summary ─────────────────────────────────────────────────
    _print_header("SUMMARY")
    total_time = sum(
        (r.get("mean", 0) for r in [
            bench_bootstrap_serialize(),
            bench_bootstrap_parse(),
            bench_payload_write(1024, ChecksumAlgo.NONE),
            bench_payload_read(1024, ChecksumAlgo.NONE),
            bench_content_write(1024),
            bench_content_read(1024),
        ])
    )
    print(f"  Critical path estimates (1KB payload, CRC16):")
    print(f"    Payload write mean:   ~{bench_payload_write(1024, ChecksumAlgo.CRC16).get('mean', 0)*1e6:.1f}µs")
    print(f"    Payload read mean:    ~{bench_payload_read(1024, ChecksumAlgo.CRC16).get('mean', 0)*1e6:.1f}µs")
    print(f"    Content write mean:   ~{bench_content_write(1024).get('mean', 0)*1e6:.1f}µs")
    print(f"    Content read mean:    ~{bench_content_read(1024).get('mean', 0)*1e6:.1f}µs")
    print(f"  All benchmarks completed.{R}")
    print()


if __name__ == "__main__":
    run_all()
