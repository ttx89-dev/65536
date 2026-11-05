#!/usr/bin/env python3
"""
generate_golden.py — produce golden test vectors for all 3 layers
═══════════════════════════════════════════════════════════════════════════════

Generates known-good reference blobs + JSON expectations for:
  • Bootstrap block  — default binary, parse roundtrip, address decomposition
  • Payload codec    — write/read with NONE / SUM8 checksums
  • Content store    — write/read with FNV1a-64 hashing, deduplication

Output:
  tests/vectors/golden/
    bootstrap_block.json   — key-value expectations
    payload_codec.json     — key-value expectations
    content_store.json     — key-value expectations
    bootstap_default.bin   — canonical 267-byte bootstrap block
    payload_descriptors.bin — serialized descriptor table (post-write)
    payload_heap.bin        — serialized heap region (post-write)
    content_addrtable.bin   — serialized address table (post-write)

Run:   python generate_golden.py              # regenerate all
       python generate_golden.py --verify     # compare against existing
       python generate_golden.py --list       # list all golden files + sizes
═══════════════════════════════════════════════════════════════════════════════
"""

import sys, os, json

sys.path.insert(0, os.path.dirname(__file__))
from framework import GoldenRegistry
from bootstrap_block import BootstrapBlock, ChecksumAlgo
from payload_codec import Store as PayloadStore
from content_store import Store as ContentStore

HERE = os.path.dirname(__file__)
GOLDEN_DIR = os.path.join(HERE, "vectors", "golden")
os.makedirs(GOLDEN_DIR, exist_ok=True)

R = "\033[0m"
G = "\033[92m"
Y = "\033[93m"
R_ = "\033[91m"


# ── helpers ────────────────────────────────────────────────────────────────

def _write_bin(name, data):
    """Write binary data to vectors/golden/<name>."""
    path = os.path.join(GOLDEN_DIR, name)
    with open(path, "wb") as f:
        f.write(data)
    return path


def _hex(b):
    return b.hex()


# ═══════════════════════════════════════════════════════════════════════════
#  BOOTSTRAP BLOCK — golden vectors
# ═══════════════════════════════════════════════════════════════════════════

def gen_bootstrap(verify_only=False):
    g = GoldenRegistry("bootstrap_block")
    g.load()
    passed = 0
    failed = 0

    # -- binary: default block --------------------------------------------
    bb = BootstrapBlock()
    default_bytes = bb.to_bytes()

    ok, msg = g.compare("default_bytes_hex", _hex(default_bytes))
    if not ok:
        print(f"  {R_}FAIL{R}  default_bytes_hex  {msg}")
        failed += 1
    else:
        passed += 1

    ok, msg = g.compare("default_size_bytes", len(default_bytes))
    if not ok:
        print(f"  {R_}FAIL{R}  default_size_bytes  {msg}")
        failed += 1
    else:
        passed += 1

    # -- binary: write to disk ---------------------------------------------
    if not verify_only:
        p = _write_bin("bootstrap_default.bin", default_bytes)
        g.set("bootstrap_default_bin", os.path.basename(p))
        g.set("bootstrap_default_bin_size", len(default_bytes))

    # -- parse roundtrip ---------------------------------------------------
    bb2 = BootstrapBlock.parse(default_bytes)
    rt_bytes = bb2.to_bytes()
    ok, msg = g.compare("parse_roundtrip_bytes_hex", _hex(rt_bytes))
    if not ok:
        print(f"  {R_}FAIL{R}  parse_roundtrip_bytes_hex  {msg}")
        failed += 1
    else:
        passed += 1
    ok, msg = g.compare("parse_roundtrip_match", rt_bytes == default_bytes)
    if not ok:
        print(f"  {R_}FAIL{R}  parse_roundtrip_match  {msg}")
        failed += 1
    else:
        passed += 1

    # -- checksum default --------------------------------------------------
    ok, msg = g.compare("checksum_algo", str(bb.checksum_algo))
    if not ok:
        print(f"  {R_}FAIL{R}  checksum_algo  {msg}")
        failed += 1
    else:
        passed += 1

    # -- checksum bytes (last 8 bytes of serialized block) -----------------
    cksum_bytes = default_bytes[-8:]
    ok, msg = g.compare("checksum_bytes_hex", _hex(cksum_bytes))
    if not ok:
        print(f"  {R_}FAIL{R}  checksum_bytes_hex  {msg}")
        failed += 1
    else:
        passed += 1

    # -- address decomposition ----------------------------------------------
    test_addrs = [0x0000, 0x0001, 0x1234, 0xABCD, 0xFFFF]
    decompositions = {}
    for addr in test_addrs:
        tier, category, idx = bb.decompose_address(addr)
        decompositions[f"0x{addr:04X}"] = {
            "tier": tier,
            "category": category,
            "index": idx,
        }
    ok, msg = g.compare("address_decompositions", decompositions)
    if not ok:
        print(f"  {R_}FAIL{R}  address_decompositions  {msg}")
        failed += 1
    else:
        passed += 1

    g.save()
    return passed, failed


# ═══════════════════════════════════════════════════════════════════════════
#  PAYLOAD CODEC — golden vectors
# ═══════════════════════════════════════════════════════════════════════════

def gen_payload(verify_only=False):
    g = GoldenRegistry("payload_codec")
    g.load()
    passed = 0
    failed = 0

    # Compose address: tier=1, cat=1, idx=0x10 → 0x1110
    # (tier << (cat_bits+idx_bits)) | (cat << idx_bits) | idx
    TIER_BITS = 4
    CAT_BITS = 4
    IDX_BITS = 8
    addr_none = (1 << (CAT_BITS + IDX_BITS)) | (1 << IDX_BITS) | 0x10
    addr_sum8 = (1 << (CAT_BITS + IDX_BITS)) | (2 << IDX_BITS) | 0x20

    # -- write 64B with NONE checksum --------------------------------------
    content_64 = b"\xAB" * 64
    s = PayloadStore(BootstrapBlock(checksum_algo=ChecksumAlgo.NONE))
    s.write(addr_none, content_64)

    ok, msg = g.compare("write_none_64B_addr", addr_none)
    if not ok:
        print(f"  {R_}FAIL{R}  write_none_64B_addr  {msg}")
        failed += 1
    else:
        passed += 1

    # -- read back 64B NONE (PayloadStore.read → 3-tuple) ------------------
    outcome, readback, deps = s.read(addr_none)
    ok, msg = g.compare("read_none_64B_outcome", outcome.name)
    if not ok:
        print(f"  {R_}FAIL{R}  read_none_64B_outcome  {msg}")
        failed += 1
    else:
        passed += 1
    ok, msg = g.compare("read_none_64B_content_hex", _hex(readback))
    if not ok:
        print(f"  {R_}FAIL{R}  read_none_64B_content_hex  {msg}")
        failed += 1
    else:
        passed += 1
    ok, msg = g.compare("read_none_64B_match", readback == content_64)
    if not ok:
        print(f"  {R_}FAIL{R}  read_none_64B_match  {msg}")
        failed += 1
    else:
        passed += 1

    # -- binary: descriptor table + heap (hasattr-guarded) ------------------
    if not verify_only:
        def _dump(name, data):
            if data:
                _write_bin(name, data)
                g.set(name.replace(".", "_").replace("-", "_") + "_size", len(data))
        _dump("payload_descriptors.bin", s.descriptors)
        _dump("payload_heap.bin", s.heap)

    # -- write 64B with SUM8 checksum ---------------------------------------
    s2 = PayloadStore(BootstrapBlock(checksum_algo=ChecksumAlgo.SUM8))
    s2.write(addr_sum8, content_64)
    outcome2, readback_sum8, _ = s2.read(addr_sum8)
    ok, msg = g.compare("write_sum8_64B_addr", addr_sum8)
    if not ok:
        print(f"  {R_}FAIL{R}  write_sum8_64B_addr  {msg}")
        failed += 1
    else:
        passed += 1
    ok, msg = g.compare("read_sum8_64B_match", readback_sum8 == content_64)
    if not ok:
        print(f"  {R_}FAIL{R}  read_sum8_64B_match  {msg}")
        failed += 1
    else:
        passed += 1

    # -- multi-write: 3 blocks ---------------------------------------------
    s3 = PayloadStore(BootstrapBlock(checksum_algo=ChecksumAlgo.NONE))
    addrs = [0x1111, 0x2222, 0x3333]
    payloads = [b"alpha", b"beta", b"gamma"]
    for a, p in zip(addrs, payloads):
        s3.write(a, p)
    for a, p in zip(addrs, payloads):
        outcome, r, _ = s3.read(a)
        key = f"multi_write_read_0x{a:04X}"
        ok, msg = g.compare(key, _hex(r))
        if not ok:
            print(f"  {R_}FAIL{R}  {key}  {msg}")
            failed += 1
        else:
            passed += 1

    g.save()
    return passed, failed


# ═══════════════════════════════════════════════════════════════════════════
#  CONTENT STORE — golden vectors
# ═══════════════════════════════════════════════════════════════════════════

def gen_content(verify_only=False):
    g = GoldenRegistry("content_store")
    g.load()
    passed = 0
    failed = 0

    # Compose address: tier=1, cat=1, idx=0x20 → 0x1120
    TIER_BITS = 4
    CAT_BITS = 4
    IDX_BITS = 8
    addr_ct = (1 << (CAT_BITS + IDX_BITS)) | (1 << IDX_BITS) | 0x20

    # -- write 64B content --------------------------------------------------
    content_64 = b"\xCD" * 64
    s = ContentStore(BootstrapBlock())
    s.write(addr_ct, content_64)

    ok, msg = g.compare("write_64B_addr", addr_ct)
    if not ok:
        print(f"  {R_}FAIL{R}  write_64B_addr  {msg}")
        failed += 1
    else:
        passed += 1

    # -- read back 64B (ContentStore.read → 4-tuple) -----------------------
    outcome, readback, dep_hashes, content_hash = s.read(addr_ct)
    ok, msg = g.compare("read_64B_outcome", outcome.name)
    if not ok:
        print(f"  {R_}FAIL{R}  read_64B_outcome  {msg}")
        failed += 1
    else:
        passed += 1
    ok, msg = g.compare("read_64B_content_hex", _hex(readback))
    if not ok:
        print(f"  {R_}FAIL{R}  read_64B_content_hex  {msg}")
        failed += 1
    else:
        passed += 1
    ok, msg = g.compare("read_64B_match", readback == content_64)
    if not ok:
        print(f"  {R_}FAIL{R}  read_64B_match  {msg}")
        failed += 1
    else:
        passed += 1
    ok, msg = g.compare("read_64B_hash", f"{content_hash:016x}")
    if not ok:
        print(f"  {R_}FAIL{R}  read_64B_hash  {msg}")
        failed += 1
    else:
        passed += 1

    # -- binary: address table + content table + heap -----------------------
    if not verify_only:
        def _dump(name, data):
            if data:
                _write_bin(name, data)
                g.set(name.replace(".", "_").replace("-", "_") + "_size", len(data))
        _dump("content_addrtable.bin", s.address_table)

    # -- deduplication: same content → same address? ------------------------
    s2 = ContentStore(BootstrapBlock())
    addr_a = s2.compose(1, 1, 0x30)
    s2.write(addr_a, content_64)
    addr_b = s2.compose(1, 1, 0x31)
    s2.write(addr_b, content_64)
    _, read_a, _, _ = s2.read(addr_a)
    _, read_b, _, _ = s2.read(addr_b)
    ok, msg = g.compare("dedup_same_content_read_a", _hex(read_a))
    if not ok:
        print(f"  {R_}FAIL{R}  dedup_same_content_read_a  {msg}")
        failed += 1
    else:
        passed += 1
    ok, msg = g.compare("dedup_same_content_read_b", _hex(read_b))
    if not ok:
        print(f"  {R_}FAIL{R}  dedup_same_content_read_b  {msg}")
        failed += 1
    else:
        passed += 1
    ok, msg = g.compare("dedup_both_match_original", read_a == content_64 and read_b == content_64)
    if not ok:
        print(f"  {R_}FAIL{R}  dedup_both_match_original  {msg}")
        failed += 1
    else:
        passed += 1

    # -- different content → different address -----------------------------
    s3 = ContentStore(BootstrapBlock())
    addr_c = s3.compose(1, 1, 0x40)
    addr_d = s3.compose(1, 1, 0x41)
    s3.write(addr_c, b"unique_content_1")
    s3.write(addr_d, b"unique_content_2")
    _, c_read, _, _ = s3.read(addr_c)
    _, d_read, _, _ = s3.read(addr_d)
    ok, msg = g.compare("unique_content_addr_c_read", _hex(c_read))
    if not ok:
        print(f"  {R_}FAIL{R}  unique_content_addr_c_read  {msg}")
        failed += 1
    else:
        passed += 1
    ok, msg = g.compare("unique_content_addr_d_read", _hex(d_read))
    if not ok:
        print(f"  {R_}FAIL{R}  unique_content_addr_d_read  {msg}")
        failed += 1
    else:
        passed += 1
    ok, msg = g.compare("unique_contents_differ", c_read != d_read)
    if not ok:
        print(f"  {R_}FAIL{R}  unique_contents_differ  {msg}")
        failed += 1
    else:
        passed += 1

    g.save()
    return passed, failed


# ═══════════════════════════════════════════════════════════════════════════
#  main
# ═══════════════════════════════════════════════════════════════════════════

def _list():
    """List all golden files with sizes."""
    print(f"{'File':<45s}  {'Size':>8s}")
    print(f"{'─' * 45}  {'─' * 8}")
    for entry in sorted(os.listdir(GOLDEN_DIR)):
        path = os.path.join(GOLDEN_DIR, entry)
        if os.path.isfile(path):
            size = os.path.getsize(path)
            print(f"  {entry:<43s}  {size:>8d}")
    print()


def main():
    args = set(sys.argv[1:])
    verify_only = "--verify" in args
    do_list = "--list" in args

    if do_list:
        _list()
        return

    label = "VERIFY" if verify_only else "GENERATE"
    print(f"{'─' * 60}")
    print(f"  GOLDEN VECTOR GENERATOR — {label}")
    print(f"{'─' * 60}")
    print(f"  Golden dir: {GOLDEN_DIR}")
    print()

    total_p = 0
    total_f = 0

    # Bootstrap
    print(f"{'▸ Bootstrap':-^60s}")
    p, f = gen_bootstrap(verify_only)
    total_p += p
    total_f += f
    print(f"  {G}✓{R} {p} passed  {R_ if f else ''}{f'✗ {f} failed' if f else '✓ all passed'}{R}\n")

    # Payload
    print(f"{'▸ Payload':-^60s}")
    p, f = gen_payload(verify_only)
    total_p += p
    total_f += f
    print(f"  {G}✓{R} {p} passed  {R_ if f else ''}{f'✗ {f} failed' if f else '✓ all passed'}{R}\n")

    # Content
    print(f"{'▸ Content':-^60s}")
    p, f = gen_content(verify_only)
    total_p += p
    total_f += f
    print(f"  {G}✓{R} {p} passed  {R_ if f else ''}{f'✗ {f} failed' if f else '✓ all passed'}{R}\n")

    # Summary
    print(f"{'─' * 60}")
    if total_f == 0:
        print(f"  {G}ALL {total_p} GOLDEN VECTORS {'VERIFIED' if verify_only else 'GENERATED'} ✓{R}")
    else:
        print(f"  {R_}{total_f} FAILURES out of {total_p + total_f} checks{R}")
        sys.exit(1)

    if not verify_only:
        _list()


if __name__ == "__main__":
    main()
