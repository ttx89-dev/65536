"""
bench_all.py — Run all benchmarks
═══════════════════════════════════════════════════════════════════════════════

Run:   python bench_all.py
═══════════════════════════════════════════════════════════════════════════════
"""

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from framework import print_report
from bench_crc16 import run_all as run_crc16
from bench_topological import run_all as run_topological


def main():
    print("═" * 72)
    print("  65536 Framework — Full Benchmark Suite")
    print("═" * 72)

    run_crc16()
    run_topological()

    print()
    print("═" * 72)
    print("  All benchmarks complete.")
    print("═" * 72)


if __name__ == "__main__":
    main()
