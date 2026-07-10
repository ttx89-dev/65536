"""
bench_topological.py — Topological sort scaling analysis
═══════════════════════════════════════════════════════════════════════════════

Measures write_ordered() latency across various DAG topologies:
  - Chain (sequential deps)
  - Star (one root, many leaves)
  - Diamond (layered DAG)
  - Random DAG with known topological depth

Run:   python bench_topological.py
═══════════════════════════════════════════════════════════════════════════════
"""

import sys, os, time, random
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from framework import Timer
from bootstrap_block import BootstrapBlock, ChecksumAlgo
from payload_codec import Store as PayloadStore


N_WARMUP = 5
N_TRIALS = 30


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
    }


def _build_chain(n):
    """Chain: 0→1→2→...→n-1"""
    items = []
    prev = None
    for i in range(n):
        addr = (1 << 12) | (1 << 8) | min(i, 0xFF)
        deps = [prev] if prev is not None else []
        items.append((addr, f"chain-{i}".encode(), deps))
        prev = addr
    return items


def _build_star(n):
    """Star: root → leaf_1, root → leaf_2, ..."""
    root_addr = (1 << 12) | (1 << 8) | 0x01
    leaves = []
    for i in range(n):
        addr = (1 << 12) | (1 << 8) | min(i + 2, 0xFF)
        leaves.append((addr, f"star-{i}".encode(), [root_addr]))
    return [(root_addr, b"root", [])] + leaves


def _build_diamond(layers, width):
    """Diamond DAG: layer i depends on layer i-1 (fully connected)."""
    items = []
    layer_addrs = {}
    for layer in range(layers):
        addrs = []
        for j in range(width):
            idx = (layer * width + j) & 0xFF
            addr = (1 << 12) | (1 << 8) | idx
            addrs.append(addr)
            deps = layer_addrs.get(layer - 1, [])
            items.append((addr, f"diamond-{layer}-{j}".encode(), deps))
        layer_addrs[layer] = addrs
    return items


def bench_topology(name, items_fn, n_items):
    bb = BootstrapBlock(checksum_algo=ChecksumAlgo.NONE)

    def _run():
        s = PayloadStore(BootstrapBlock(checksum_algo=ChecksumAlgo.NONE))
        items = items_fn(n_items)
        s.write_ordered(items)

    return _timed(_run, trials=max(5, N_TRIALS // max(1, n_items // 10)))


def run_all():
    print("═" * 60)
    print("  Topological Sort — Scaling Analysis")
    print("═" * 60)
    print(f"  trials={N_TRIALS}  warmup={N_WARMUP}")
    print()

    configs = [
        ("Chain, 10",     _build_chain,   10),
        ("Chain, 100",    _build_chain,   100),
        ("Chain, 250",    _build_chain,   250),
        ("Star, 10",      _build_star,    10),
        ("Star, 100",     _build_star,    100),
        ("Star, 250",     _build_star,    250),
        ("Diamond 5×5",   lambda n: _build_diamond(5, 5),  None),
        ("Diamond 10×10", lambda n: _build_diamond(10, 10), None),
    ]

    print(f"  {'Topology':<20s}  {'mean':>10s}  {'p50':>10s}  {'p95':>10s}")
    print(f"  {'─' * 20}  {'─' * 10}  {'─' * 10}  {'─' * 10}")

    for name, fn, n in configs:
        if n is None:
            r = bench_topology(name, fn, 0)
        else:
            r = bench_topology(name, fn, n)
        print(f"  {name:<20s}  {r['mean_us']:>10.1f}µs  "
              f"{r['p50_us']:>10.1f}µs  {r['p95_us']:>10.1f}µs")

    print()


if __name__ == "__main__":
    run_all()
