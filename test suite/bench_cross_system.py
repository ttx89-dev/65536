#!/usr/bin/env python3
"""
bench_cross_system.py — 65536 (DOTM) vs CBOR-equivalent 3-layer benchmark
═══════════════════════════════════════════════════════════════════════════════

Compares 65536's three-layer architecture against a functionally equivalent
CBOR-based implementation across the same dimensions:

  65536 Layer          CBOR Equivalent
  ─────────────        ─────────────────────
  Bootstrap Block      CBOR-encoded header (dict)
  Payload Codec        CBOR byte string store (heap w/o DAG)
  Content Store        CBOR map (hash → blob) with refcounts

Metrics: write/read throughput, storage efficiency, serialized size overhead,
and content dedup effectiveness at payloads from 64B → 1MB.

Run:   python bench_cross_system.py
       python bench_cross_system.py --json    # machine-readable JSON output

Exit:  0 = ok
═══════════════════════════════════════════════════════════════════════════════
"""

import sys, os, json, math, time, struct

sys.path.insert(0, os.path.dirname(__file__))
from framework import Timer, print_report

# ── 65536 imports ──
from bootstrap_block import BootstrapBlock, BootstrapError, ChecksumAlgo, BLOCK_SIZE
from payload_codec import Store as PayloadStore, EntryOutcome, PayloadError
from content_store import Store as ContentStore, fnv1a_64

# ── CBOR competitor ──
import cbor2

# ─────────────────────────────────────────────────────────────────────────────
#  CONFIG
# ─────────────────────────────────────────────────────────────────────────────

N_WARMUP = 5
N_TRIALS = 50
N_LARGE_TRIALS = 10

SIZES = {"64B": 64, "1KB": 1024, "64KB": 65536, "256KB": 262144}

# ANSI
R = "\033[0m"
G = "\033[92m"
Y = "\033[93m"
B = "\033[94m"
C = "\033[96m"
M = "\033[95m"


# ─────────────────────────────────────────────────────────────────────────────
#  CBOR EQUIVALENT — 3-LAYER ANALOGUE
# ─────────────────────────────────────────────────────────────────────────────

class CBORHeader:
    """CBOR equivalent of BootstrapBlock — a simple dict header."""
    __slots__ = ("magic", "version", "fields")

    MAGIC = b"DOTM"  # same magic bytes concept
    VERSION = 1

    def __init__(self, **fields):
        self.magic = self.MAGIC
        self.version = self.VERSION
        self.fields = fields

    def to_bytes(self) -> bytes:
        return cbor2.dumps({
            "magic": list(self.magic),
            "version": self.version,
            **self.fields,
        })

    @classmethod
    def parse(cls, data: bytes):
        d = cbor2.loads(data)
        return cls(**{k: v for k, v in d.items() if k not in ("magic", "version")})

    @property
    def size(self) -> int:
        return len(self.to_bytes())


class CBORPayloadStore:
    """CBOR equivalent of PayloadStore — flat byte-string heap w/o DAG."""

    def __init__(self):
        self.heap = bytearray()
        self.entries = {}  # addr → (offset, length)

    def write(self, addr: int, data: bytes):
        offset = len(self.heap)
        self.heap.extend(data)
        self.entries[addr] = (offset, len(data))
        return len(data)

    def read(self, addr: int):
        if addr not in self.entries:
            return EntryOutcome.MISSING, b"", []
        offset, length = self.entries[addr]
        return EntryOutcome.VALID, bytes(self.heap[offset:offset + length]), []

    def to_bytes(self) -> bytes:
        # Serialize: heap + index table
        index = {str(k): v for k, v in self.entries.items()}
        return cbor2.dumps({"heap": list(self.heap), "index": index})

    @classmethod
    def from_bytes(cls, data: bytes):
        d = cbor2.loads(data)
        store = cls()
        store.heap = bytearray(d["heap"])
        store.entries = {int(k): tuple(v) for k, v in d["index"].items()}
        return store


class CBORContentStore:
    """CBOR equivalent of ContentStore — hash-addressed blobs with refcounts."""

    def __init__(self):
        self.blobs = {}        # hash → blob bytes
        self.refcounts = {}    # hash → int
        self.addr_map = {}     # addr → hash

    def _hash(self, data: bytes) -> int:
        return fnv1a_64(data)  # same hash as 65536 content store

    def write(self, addr: int, data: bytes, depends_on=None):
        h = self._hash(data)
        if h not in self.blobs:
            self.blobs[h] = data
            self.refcounts[h] = 0
        self.refcounts[h] += 1
        self.addr_map[addr] = h
        return h

    def read(self, addr: int):
        if addr not in self.addr_map:
            return EntryOutcome.MISSING, b"", [], 0
        h = self.addr_map[addr]
        return EntryOutcome.VALID, self.blobs[h], [], h

    def delete(self, addr: int):
        if addr not in self.addr_map:
            return
        h = self.addr_map.pop(addr)
        self.refcounts[h] -= 1
        if self.refcounts[h] <= 0:
            del self.blobs[h]
            del self.refcounts[h]

    def to_bytes(self) -> bytes:
        return cbor2.dumps({
            "blobs": {f"0x{k:016x}": list(v) for k, v in self.blobs.items()},
            "refs": {f"0x{k:016x}": v for k, v in self.refcounts.items()},
            "map": {str(k): f"0x{v:016x}" for k, v in self.addr_map.items()},
        })


# ─────────────────────────────────────────────────────────────────────────────
#  BENCHMARK HELPERS
# ─────────────────────────────────────────────────────────────────────────────

def _timed(fn, trials=N_TRIALS, warmup=N_WARMUP):
    """Run fn() trials times, return timing dict in seconds."""
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
        "min": elapsed[0], "p50": elapsed[n // 2],
        "p95": elapsed[int(n * 0.95)], "max": elapsed[-1],
        "mean": sum(elapsed) / n, "trials": n,
    }


def _fmt_us(d):
    return {
        "min_us": d["min"] * 1e6, "p50_us": d["p50"] * 1e6,
        "p95_us": d["p95"] * 1e6, "max_us": d["max"] * 1e6,
        "mean_us": d["mean"] * 1e6,
    }


def _ratio(a, b):
    """Return a/b as float, or inf if b==0."""
    return a / b if b else float("inf")


# ─────────────────────────────────────────────────────────────────────────────
#  LAYER 1: HEADER SERIALIZATION
# ─────────────────────────────────────────────────────────────────────────────

def bench_header_65536():
    bb = BootstrapBlock()
    return _timed(lambda: bb.to_bytes()), len(bb.to_bytes())


def bench_header_65536_parse():
    data = BootstrapBlock().to_bytes()
    return _timed(lambda: BootstrapBlock.parse(data))


def bench_header_cbor():
    h = CBORHeader(tier_count=16, cat_count=16, checksum_algo=0)
    return _timed(lambda: h.to_bytes()), len(h.to_bytes())


def bench_header_cbor_parse():
    h = CBORHeader(tier_count=16, cat_count=16, checksum_algo=0)
    data = h.to_bytes()
    return _timed(lambda: CBORHeader.parse(data))


# ─────────────────────────────────────────────────────────────────────────────
#  LAYER 2: PAYLOAD WRITE/READ
# ─────────────────────────────────────────────────────────────────────────────

def bench_payload_write_65536(size):
    def _run():
        s = PayloadStore(BootstrapBlock(checksum_algo=ChecksumAlgo.NONE))
        s.write(s.compose(1, 1, 0x10), b"x" * size)
    return _timed(_run)


def bench_payload_read_65536(size):
    def _run():
        s = PayloadStore(BootstrapBlock(checksum_algo=ChecksumAlgo.NONE))
        addr = s.compose(1, 1, 0x10)
        s.write(addr, b"x" * size)
        s.read(addr)
    return _timed(_run)


def bench_payload_write_cbor(size):
    def _run():
        s = CBORPayloadStore()
        s.write(0x110, b"x" * size)
    return _timed(_run)


def bench_payload_read_cbor(size):
    def _run():
        s = CBORPayloadStore()
        s.write(0x110, b"x" * size)
        s.read(0x110)
    return _timed(_run)


# ─────────────────────────────────────────────────────────────────────────────
#  LAYER 3: CONTENT-STORE WRITE/READ + DEDUP
# ─────────────────────────────────────────────────────────────────────────────

def bench_content_write_65536(size):
    content = b"x" * size
    def _run():
        s = ContentStore(BootstrapBlock())
        s.write(s.compose(1, 1, 0x20), content)
    return _timed(_run)


def bench_content_read_65536(size):
    content = b"x" * size
    def _run():
        s = ContentStore(BootstrapBlock())
        s.write(s.compose(1, 1, 0x20), content)
        s.read(s.compose(1, 1, 0x20))
    return _timed(_run)


def bench_content_write_cbor(size):
    content = b"x" * size
    def _run():
        s = CBORContentStore()
        s.write(0x120, content)
    return _timed(_run)


def bench_content_read_cbor(size):
    content = b"x" * size
    def _run():
        s = CBORContentStore()
        s.write(0x120, content)
        s.read(0x120)
    return _timed(_run)


# ─────────────────────────────────────────────────────────────────────────────
#  DEDUP EFFECTIVENESS
# ─────────────────────────────────────────────────────────────────────────────

def bench_dedup_65536(n_writes=1000):
    """Write same content to many addresses, measure heap."""
    content = b"dedup-test"
    addrs = [0x1100 + i for i in range(n_writes)]
    s = ContentStore(BootstrapBlock())
    before = len(s.heap)
    for a in addrs:
        s.write(a, content)
    after = len(s.heap)
    naive = n_writes * len(content)
    return {
        "system": "65536 ContentStore",
        "writes": n_writes,
        "naive_bytes": naive,
        "actual_bytes": after - before,
        "savings_pct": round((1 - (after - before) / naive) * 100, 1),
    }


def bench_dedup_cbor(n_writes=1000):
    """Write same content to many CBOR content addresses."""
    content = b"dedup-test"
    s = CBORContentStore()
    for i in range(n_writes):
        s.write(0x1100 + i, content)
    # Measure serialized size — CBOR doesn't dedup internally,
    # so this is a measure of our refcount-based dedup overhead.
    total_blob_bytes = sum(len(v) for v in s.blobs.values())
    total_ref_bytes = len(json.dumps(s.refcounts))
    return {
        "system": "CBORContentStore",
        "writes": n_writes,
        "naive_bytes": n_writes * len(content),
        "actual_blob_bytes": total_blob_bytes,
        "savings_pct": round((1 - total_blob_bytes / (n_writes * len(content))) * 100, 1),
    }


# ─────────────────────────────────────────────────────────────────────────────
#  STORAGE EFFICIENCY
# ─────────────────────────────────────────────────────────────────────────────

def bench_storage_efficiency():
    """Compare serialized size overhead for equivalent payloads."""
    payload = b"Hello, 65536 framework - cross-system comparison!" * 10

    # 65536 payload store: header + offset table entries + heap
    bb = BootstrapBlock(checksum_algo=ChecksumAlgo.NONE)
    ps = PayloadStore(bb)
    addr = ps.compose(1, 1, 0x10)
    ps.write(addr, payload)
    # Storage = bootstrap block (267B) + descriptor table entry size + heap
    # Descriptor entry: address(2B) + offset(2B) + length(2B) = 6B
    HEADER = 267
    desc_entry_size = 6
    p_raw_len = HEADER + desc_entry_size + len(ps.heap)

    # CBOR payload store
    cs = CBORPayloadStore()
    cs.write(0x110, payload)
    c_raw_len = len(cs.to_bytes())

    # Raw CBOR of just the payload
    raw_cbor = len(cbor2.dumps(payload))

    return {
        "payload_bytes": len(payload),
        "65536_payload_store_bytes": p_raw_len,
        "cbor_payload_store_bytes": c_raw_len,
        "cbor_raw_bytes": raw_cbor,
        "65536_overhead_pct": round((p_raw_len / len(payload) - 1) * 100, 1),
        "cbor_store_overhead_pct": round((c_raw_len / len(payload) - 1) * 100, 1),
        "cbor_raw_overhead_pct": round((raw_cbor / len(payload) - 1) * 100, 1),
    }


# ─────────────────────────────────────────────────────────────────────────────
#  REPORT
# ─────────────────────────────────────────────────────────────────────────────

def _print_hdr(title):
    print(f"\n{C}{'═' * 72}{R}")
    print(f"{B}  {title}{R}")
    print(f"{C}{'═' * 72}{R}")


def _print_timing(label, d, prefix=""):
    print(f"  {prefix}{label:<36s}  min={d['min_us']:8.2f}µs  "
          f"p50={d['p50_us']:8.2f}µs  p95={d['p95_us']:8.2f}µs  "
          f"max={d['max_us']:8.2f}µs  (n={d.get('trials', '')})")


def _winning(label, v1, v2, lower_better=True):
    """Compare two values and return a winner arrow."""
    if lower_better:
        return f"{Y}← 65536 wins{R}" if v1 < v2 else f"{M}← CBOR wins{R}"
    return f"{Y}← 65536 wins{R}" if v1 > v2 else f"{M}← CBOR wins{R}"


def run_all():
    results = {}

    print(f"{G}65535-POINT FRAMEWORK {R}v{self()}{M} CBOR EQUIVALENT{R}")
    print(f"{'─' * 72}")
    print(f"  python: {sys.version.split()[0]}")
    print(f"  cbor2:  {getattr(cbor2, '__version__', '?')}")
    print(f"  trials: {N_TRIALS}  warmup: {N_WARMUP}")

    # ── Layer 1: Header ──────────────────────────────────────────
    _print_hdr("LAYER 1: HEADER SERIALIZATION")
    _, size_65536 = bench_header_65536()
    _, size_cbor = bench_header_cbor()
    print(f"  {'65536 BootstrapBlock':<40s}  {size_65536}B  (fixed 267B)")
    print(f"  {'CBORHeader':<40s}  {size_cbor}B  (variable)")
    print(f"  Size ratio (CBOR/65536):  {size_cbor / size_65536:.2f}×")

    t_65536, _ = bench_header_65536()
    t_cbor, _ = bench_header_cbor()
    _print_timing("65536 serialize", _fmt_us(t_65536))
    _print_timing("CBOR serialize",   _fmt_us(t_cbor))
    print(f"  {'':>36s}  {_winning('header serialize', t_65536['mean'], t_cbor['mean'])}")

    t_65536_p = bench_header_65536_parse()
    t_cbor_p = bench_header_cbor_parse()
    _print_timing("65536 parse", _fmt_us(t_65536_p))
    _print_timing("CBOR parse",   _fmt_us(t_cbor_p))
    print(f"  {'':>36s}  {_winning('header parse', t_65536_p['mean'], t_cbor_p['mean'])}")

    results["layer1_header"] = {
        "65536_size_bytes": size_65536,
        "cbor_size_bytes": size_cbor,
        "65536_serialize_mean_us": t_65536["mean"] * 1e6,
        "cbor_serialize_mean_us": t_cbor["mean"] * 1e6,
        "65536_parse_mean_us": t_65536_p["mean"] * 1e6,
        "cbor_parse_mean_us": t_cbor_p["mean"] * 1e6,
    }

    # ── Layer 2: Payload ─────────────────────────────────────────
    _print_hdr("LAYER 2: PAYLOAD WRITE/READ")
    for label, size in SIZES.items():
        t65_w = bench_payload_write_65536(size)
        tcb_w = bench_payload_write_cbor(size)
        _print_timing(f"65536 write {label}", _fmt_us(t65_w))
        _print_timing(f"CBOR write {label}",   _fmt_us(tcb_w))
        print(f"  {'':>36s}  {_winning(f'write {label}', t65_w['mean'], tcb_w['mean'])}")

        t65_r = bench_payload_read_65536(size)
        tcb_r = bench_payload_read_cbor(size)
        _print_timing(f"65536 read  {label}", _fmt_us(t65_r))
        _print_timing(f"CBOR read  {label}",   _fmt_us(tcb_r))
        print(f"  {'':>36s}  {_winning(f'read {label}', t65_r['mean'], tcb_r['mean'])}")

        results[f"layer2_payload_{label}"] = {
            "65536_write_mean_us": t65_w["mean"] * 1e6,
            "cbor_write_mean_us": tcb_w["mean"] * 1e6,
            "65536_read_mean_us": t65_r["mean"] * 1e6,
            "cbor_read_mean_us": tcb_r["mean"] * 1e6,
        }

    # ── Layer 3: Content Store ────────────────────────────────────
    _print_hdr("LAYER 3: CONTENT STORE WRITE/READ")
    for label, size in SIZES.items():
        t65_w = bench_content_write_65536(size)
        tcb_w = bench_content_write_cbor(size)
        _print_timing(f"65536 write {label}", _fmt_us(t65_w))
        _print_timing(f"CBOR write {label}",   _fmt_us(tcb_w))
        print(f"  {'':>36s}  {_winning(f'content write {label}', t65_w['mean'], tcb_w['mean'])}")

        t65_r = bench_content_read_65536(size)
        tcb_r = bench_content_read_cbor(size)
        _print_timing(f"65536 read  {label}", _fmt_us(t65_r))
        _print_timing(f"CBOR read  {label}",   _fmt_us(tcb_r))
        print(f"  {'':>36s}  {_winning(f'content read {label}', t65_r['mean'], tcb_r['mean'])}")

        results[f"layer3_content_{label}"] = {
            "65536_write_mean_us": t65_w["mean"] * 1e6,
            "cbor_write_mean_us": tcb_w["mean"] * 1e6,
            "65536_read_mean_us": t65_r["mean"] * 1e6,
            "cbor_read_mean_us": tcb_r["mean"] * 1e6,
        }

    # ── Dedup ─────────────────────────────────────────────────────
    _print_hdr("CONTENT DEDUPLICATION")
    d65 = bench_dedup_65536()
    dcb = bench_dedup_cbor()
    print(f"  {'65536 ContentStore':<40s}  {d65['savings_pct']}% savings "
          f"({d65['writes']}× same content)")
    print(f"  {'CBORContentStore':<40s}  {dcb['savings_pct']}% savings "
          f"({dcb['writes']}× same content)")
    print(f"  {'':>36s}  {_winning('dedup', d65['savings_pct'], dcb['savings_pct'], lower_better=False)}")
    results["dedup"] = {"65536_savings_pct": d65["savings_pct"], "cbor_savings_pct": dcb["savings_pct"]}

    # ── Storage efficiency ────────────────────────────────────────
    _print_hdr("STORAGE EFFICIENCY")
    eff = bench_storage_efficiency()
    print(f"  {'Payload size:':<40s}  {eff['payload_bytes']:,}B")
    print(f"  {'65536 PayloadStore serialized:':<40s}  {eff['65536_payload_store_bytes']:,}B  "
          f"(+{eff['65536_overhead_pct']}%)")
    print(f"  {'CBOR PayloadStore serialized:':<40s}  {eff['cbor_payload_store_bytes']:,}B  "
          f"(+{eff['cbor_store_overhead_pct']}%)")
    print(f"  {'Raw CBOR payload:':<40s}  {eff['cbor_raw_bytes']:,}B  "
          f"(+{eff['cbor_raw_overhead_pct']}%)")
    results["storage_efficiency"] = eff

    # ── JSON output ───────────────────────────────────────────────
    if "--json" in sys.argv:
        print(f"\n{json.dumps(results, indent=2)}")

    # ── Summary ───────────────────────────────────────────────────
    _print_hdr("VERDICT")
    wins_65536 = sum(
        1 for k, v in results.items()
        if isinstance(v, dict) and "65536_write_mean_us" in v
        and v["65536_write_mean_us"] < v.get("cbor_write_mean_us", float("inf"))
    )
    wins_cbor = sum(
        1 for k, v in results.items()
        if isinstance(v, dict) and "65536_write_mean_us" in v
        and v["65536_write_mean_us"] > v.get("cbor_write_mean_us", float("inf"))
    )
    print(f"  65536 wins in  {wins_65536}  timing comparisons")
    print(f"  CBOR  wins in  {wins_cbor}  timing comparisons")
    print(f"  Header size:  65536={results['layer1_header']['65536_size_bytes']}B  "
          f"CBOR={results['layer1_header']['cbor_size_bytes']}B")
    print(f"  Dedup: 65536={d65['savings_pct']}%  CBOR={dcb['savings_pct']}%")
    print()
    print(f"{G}  Done.{R}")


def self():
    """Return framework version string."""
    return "1.0"


if __name__ == "__main__":
    run_all()
