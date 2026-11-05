#!/usr/bin/env python3
"""
bench_cross_language.py — Python vs Julia speed comparison
═══════════════════════════════════════════════════════════════════════════════

Runs identical benchmark cases in Python (direct) and Julia (subprocess),
then prints a side-by-side comparison table with p50/mean timings and the
Python/Julia ratio.

Each case: 5 warmup, 50 timed trials. Cases cover all 3 layers:
  - Bootstrap: serialize, parse, decompose (5 addresses)
  - Payload:   write & read at 64B / 1KB / 64KB  (NONE checksum)
  - Content:   write & read at 64B / 1KB / 64KB

Run:   python bench_cross_language.py
       python bench_cross_language.py --json   # machine-readable JSON output

Exit code: 0 = all cases ran, 1 = error
═══════════════════════════════════════════════════════════════════════════════
"""

import sys, os, json, subprocess, time, shutil

sys.path.insert(0, os.path.dirname(__file__))
from bootstrap_block import BootstrapBlock, ChecksumAlgo
from payload_codec import Store as PayloadStore
from content_store import Store as ContentStore

HAS_JULIA = shutil.which("julia") is not None

N_WARMUP = 5
N_TRIALS = 50


# ═══════════════════════════════════════════════════════════════════════════
#  helpers
# ═══════════════════════════════════════════════════════════════════════════

def _timed(fn, trials=N_TRIALS, warmup=N_WARMUP):
    """Run fn() trials times, return {min_us, p50_us, p95_us, max_us, mean_us, trials}."""
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
        "min_us": round(elapsed[0] * 1e6, 2),
        "p50_us": round(elapsed[n // 2] * 1e6, 2),
        "p95_us": round(elapsed[int(n * 0.95)] * 1e6, 2),
        "max_us": round(elapsed[-1] * 1e6, 2),
        "mean_us": round(sum(elapsed) / n * 1e6, 2),
        "trials": n,
    }


def _run_julia():
    """Run jl/run_bench.jl and return parsed JSON dict of results."""
    jl_dir = os.path.join(os.path.dirname(__file__), "..", "jl")
    script = os.path.join(jl_dir, "run_bench.jl")
    try:
        r = subprocess.run(
            ["julia", script],
            capture_output=True, text=True, timeout=120,
            cwd=jl_dir,
        )
        if r.returncode != 0:
            print(f"  ⚠  Julia errored: exit={r.returncode} stderr={r.stderr.strip()}", file=sys.stderr)
            return None
        return json.loads(r.stdout)
    except FileNotFoundError:
        return None
    except json.JSONDecodeError as e:
        print(f"  ⚠  Julia JSON parse error: {e}", file=sys.stderr)
        print(f"  stderr was: {r.stderr}", file=sys.stderr)
        return None


R = "\033[0m"
G = "\033[92m"
Y = "\033[93m"
B = "\033[94m"
C = "\033[96m"


# ═══════════════════════════════════════════════════════════════════════════
#  Python benchmark cases — mirror jl/run_bench.jl exactly
# ═══════════════════════════════════════════════════════════════════════════

def py_bench_bootstrap_serialize():
    bb = BootstrapBlock()
    return _timed(lambda: bb.to_bytes())


def py_bench_bootstrap_parse():
    data = BootstrapBlock().to_bytes()
    return _timed(lambda: BootstrapBlock.parse(data))


def py_bench_bootstrap_decompose():
    bb = BootstrapBlock()
    addrs = [0x0000, 0x0001, 0x1234, 0xABCD, 0xFFFF]
    return _timed(lambda: [bb.decompose_address(a) for a in addrs])


def py_bench_payload_write(size):
    content = b"\x00" * size
    def _run():
        s = PayloadStore(BootstrapBlock(checksum_algo=ChecksumAlgo.NONE))
        s.write(0x1110, content)
    return _timed(_run)


def py_bench_payload_read(size):
    content = b"\x00" * size
    bb = BootstrapBlock(checksum_algo=ChecksumAlgo.NONE)
    s = PayloadStore(bb)
    s.write(0x1110, content)

    def _run():
        s.read(0x1110)
    return _timed(_run)


def py_bench_content_write(size):
    content = b"\x00" * size

    def _run():
        s = ContentStore(BootstrapBlock())
        a = s.compose(1, 1, 0x20)
        s.write(a, content)
    return _timed(_run)


def py_bench_content_read(size):
    content = b"\x00" * size

    def _run():
        s = ContentStore(BootstrapBlock())
        a = s.compose(1, 1, 0x20)
        s.write(a, content)
        s.read(a)
    return _timed(_run)


# ═══════════════════════════════════════════════════════════════════════════
#  main
# ═══════════════════════════════════════════════════════════════════════════

PY_CASES = {
    "bootstrap_serialize":        py_bench_bootstrap_serialize,
    "bootstrap_parse":            py_bench_bootstrap_parse,
    "bootstrap_decompose":        py_bench_bootstrap_decompose,
    "payload_write_nonce_64B":    lambda: py_bench_payload_write(64),
    "payload_write_nonce_1KB":    lambda: py_bench_payload_write(1024),
    "payload_write_nonce_64KB":   lambda: py_bench_payload_write(65536),
    "payload_read_nonce_64B":     lambda: py_bench_payload_read(64),
    "payload_read_nonce_1KB":     lambda: py_bench_payload_read(1024),
    "payload_read_nonce_64KB":    lambda: py_bench_payload_read(65536),
    "content_write_64B":          lambda: py_bench_content_write(64),
    "content_write_1KB":          lambda: py_bench_content_write(1024),
    "content_write_64KB":         lambda: py_bench_content_write(65536),
    "content_read_64B":           lambda: py_bench_content_read(64),
    "content_read_1KB":           lambda: py_bench_content_read(1024),
    "content_read_64KB":          lambda: py_bench_content_read(65536),
}

# Human-readable labels
CASE_LABELS = {
    "bootstrap_serialize":        "Bootstrap → serialize",
    "bootstrap_parse":            "Bootstrap → parse",
    "bootstrap_decompose":        "Bootstrap → decompose (5 addr)",
    "payload_write_nonce_64B":    "Payload → write 64B",
    "payload_write_nonce_1KB":    "Payload → write 1KB",
    "payload_write_nonce_64KB":   "Payload → write 64KB",
    "payload_read_nonce_64B":     "Payload → read 64B",
    "payload_read_nonce_1KB":     "Payload → read 1KB",
    "payload_read_nonce_64KB":    "Payload → read 64KB",
    "content_write_64B":          "Content → write 64B",
    "content_write_1KB":          "Content → write 1KB",
    "content_write_64KB":         "Content → write 64KB",
    "content_read_64B":           "Content → read 64B",
    "content_read_1KB":           "Content → read 1KB",
    "content_read_64KB":          "Content → read 64KB",
}


def _fmt_us(v):
    return f"{v:>8.2f}"


def _ratio(py, jl):
    if jl is None or jl == 0:
        return "  N/A  "
    r = py / jl
    if r >= 1.0:
        return f"{G}{r:>6.2f}x slower{R}"
    else:
        return f"{C}{r:>6.2f}x faster{R}"


def main():
    do_json = "--json" in sys.argv

    print(f"{G}65535-POINT FRAMEWORK — CROSS-LANGUAGE BENCHMARK{R}")
    print(f"{C}{'─' * 72}{R}")
    print(f"  Python: {sys.version.split()[0]}")
    print(f"  Julia:  {'found' if HAS_JULIA else 'NOT FOUND'}")
    print(f"  Trials: {N_TRIALS}  Warmup: {N_WARMUP}")
    print()

    # ── Run Julia benchmarks ──────────────────────────────────
    jl_results = _run_julia() if HAS_JULIA else None
    if jl_results is None and HAS_JULIA:
        print(f"{Y}  ⚠  Julia benchmarks failed — running Python only{R}\n")

    # ── Run Python benchmarks ────────────────────────────────
    py_results = {}
    for key, fn in PY_CASES.items():
        py_results[key] = fn()

    # ── Output ────────────────────────────────────────────────
    if do_json:
        output = {"python": py_results, "julia": jl_results}
        print(json.dumps(output, indent=2))
        return

    # Header
    print(f"{'Benchmark':<40s}  {'Python p50':>10s}  {'Julia p50':>10s}  {'Ratio':>14s}  {'Python mean':>12s}  {'Julia mean':>12s}")
    print(f"{'─' * 40}  {'─' * 10}  {'─' * 10}  {'─' * 14}  {'─' * 12}  {'─' * 12}")

    for key in PY_CASES:
        label = CASE_LABELS.get(key, key)
        py = py_results[key]
        jl = jl_results.get(key) if jl_results else None
        py_p50 = _fmt_us(py["p50_us"])
        jl_p50 = _fmt_us(jl["p50_us"]) if jl else "   N/A   "
        py_mean = _fmt_us(py["mean_us"])
        jl_mean = _fmt_us(jl["mean_us"]) if jl else "   N/A   "
        rat = _ratio(py["p50_us"], jl["p50_us"] if jl else None)
        print(f"  {label:<38s}  {py_p50}  {jl_p50}  {rat}  {py_mean}  {jl_mean}")

    # Summary
    print(f"\n{C}{'─' * 72}{R}")
    print(f"  All benchmarks completed.")
    print(f"  Ratio > 1.0 = Python slower than Julia on that case.")
    print(f"  Ratio < 1.0 = Python faster than Julia on that case.{R}")

    if not HAS_JULIA:
        print(f"\n{Y}  ⚠  Install Julia for cross-language comparison.{R}")


if __name__ == "__main__":
    main()
