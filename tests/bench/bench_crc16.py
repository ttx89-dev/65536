"""
bench_crc16.py — CRC-16 bit-loop vs LUT speed, cross-language
═══════════════════════════════════════════════════════════════════════════════

Measures CRC-16 computation throughput via bit-loop and LUT implementations.
Compares Python vs Julia if available.

The payload_codec module provides _crc16() (bit-by-bit loop).  We add a
pre-computed 256-entry lookup-table version inline so the two approaches can
be compared directly.

Run:   python bench_crc16.py
═══════════════════════════════════════════════════════════════════════════════
"""

import sys, os, time, math
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from framework import Timer, print_report
from payload_codec import _crc16 as _crc16_bit

# ── LUT implementation (pre-computed 256-entry table for CRC-16/MCRF4XX) ──
def _build_crc16_lut(poly: int = 0x1021) -> list[int]:
    lut = []
    for byte in range(256):
        crc = byte << 8
        for _ in range(8):
            crc = ((crc << 1) ^ poly) & 0xFFFF if (crc & 0x8000) else (crc << 1) & 0xFFFF
        lut.append(crc)
    return lut

_CRC16_LUT = _build_crc16_lut(0x1021)

def _crc16_lut(data: bytes, init: int = 0xFFFF) -> int:
    crc = init
    for byte in data:
        crc = ((crc << 8) ^ _CRC16_LUT[((crc >> 8) ^ byte) & 0xFF]) & 0xFFFF
    return crc

N_WARMUP = 10
N_TRIALS = 200
SIZES = [16, 64, 256, 1024, 4096, 65536]


def _timed(fn, trials=N_TRIALS, warmup=N_WARMUP):
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
        "min_us": elapsed[0] * 1e6,
        "p50_us": elapsed[n // 2] * 1e6,
        "p95_us": elapsed[int(n * 0.95)] * 1e6,
        "max_us": elapsed[-1] * 1e6,
        "mean_us": sum(elapsed) / n * 1e6,
        "trials": n,
    }


def bench_bit_loop(size):
    data = b"x" * size
    return _timed(lambda: _crc16_bit(data))


def bench_lut(size):
    data = b"x" * size
    return _timed(lambda: _crc16_lut(data))


def run_all():
    print("═" * 60)
    print("  CRC-16: Bit-Loop vs LUT")
    print("═" * 60)
    print(f"  trials={N_TRIALS}  warmup={N_WARMUP}")
    print()

    print(f"  {'Size':>10s}  {'Method':>10s}  {'mean':>8s}  {'p50':>8s}  {'p95':>8s}  "
          f"{'MB/s':>8s}")
    print(f"  {'─' * 10}  {'─' * 10}  {'─' * 8}  {'─' * 8}  {'─' * 8}  {'─' * 8}")

    for size in SIZES:
        for label, fn in [("bit-loop", bench_bit_loop), ("lut", bench_lut)]:
            r = fn(size)
            mb_per_sec = (size / r["mean_us"]) if r["mean_us"] > 0 else 0
            print(f"  {size:>10d}  {label:>10s}  {r['mean_us']:>8.1f}µs  "
                  f"{r['p50_us']:>8.1f}µs  {r['p95_us']:>8.1f}µs  "
                  f"{mb_per_sec:>8.1f}")
        print()

    # Speedup factor
    bit_1k = bench_bit_loop(1024)
    lut_1k = bench_lut(1024)
    speedup = bit_1k["mean_us"] / lut_1k["mean_us"] if lut_1k["mean_us"] > 0 else 0
    print(f"  Speedup at 1KB: LUT is {speedup:.1f}× faster than bit-loop")
    print()


if __name__ == "__main__":
    run_all()
