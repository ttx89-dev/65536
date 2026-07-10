#!/usr/bin/env python3
"""
glyph_protocol.py — standalone 65536 glyph serialization + subagent round-trip experiment.

Creates a self-contained "glyph" byte sequence that can be:
  1. Hex-encoded and passed across an agent boundary
  2. Decoded by any agent that knows the format
  3. Transformed and re-encoded
  4. Verified for integrity

Binary format:
  [magic:     4B]  b"GLPH"
  [crc16:     2B]  CRC-16 of everything from algo onward
  [algo:      1B]  ChecksumAlgo (0=NONE, 1=SUM8, 2=CRC16)
  [dep_count: 1B]  number of dependency addresses (0-255)
  [deps:     n*2B] dependency addresses, big-endian
  [content:   vB]  arbitrary byte content

Commands:
  mint <text>              — create a glyph, print hex
  verify <hex> <expected>  — verify glyph decodes to expected text
  roundtrip <hex>          — decode, reverse text, re-encode
  batch <text_file>        — mint one glyph per line
"""

import struct
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from bootstrap_block import ChecksumAlgo
from payload_codec import _crc16, compute_checksum

MAGIC = b"GLPH"
MAGIC_SIZE = 4
CRC_SIZE = 2
ALGO_SIZE = 1
DEP_COUNT_SIZE = 1

def pack_glyph(content: bytes, deps: list[int] | None = None,
               algo: ChecksumAlgo = ChecksumAlgo.CRC16) -> bytes:
    """Serialize a standalone glyph.

    Returns binary that can be hex-encoded and sent across
    an agent boundary. The CRC covers everything after the
    CRC field itself.
    """
    if deps is None:
        deps = []
    if len(deps) > 255:
        raise ValueError(f"at most 255 deps, got {len(deps)}")

    variant = int(algo)
    body = struct.pack(">BB", variant, len(deps))
    body += b"".join(struct.pack(">H", d) for d in deps)
    body += content

    crc = _crc16(body)
    return MAGIC + struct.pack(">H", crc) + body


def unpack_glyph(data: bytes) -> dict:
    """Deserialize and verify a standalone glyph.

    Returns dict with keys:
      valid       — bool, True if CRC matches
      algo        — int (ChecksumAlgo value)
      deps        — list[int]
      content     — bytes
      crc_stored  — int (from glyph)
      crc_computed— int (computed from data)
      content_text— str (decoded utf-8, errors='replace')
    """
    header = MAGIC_SIZE + CRC_SIZE + ALGO_SIZE + DEP_COUNT_SIZE
    if len(data) < header:
        return {"valid": False, "error": f"too short: {len(data)} < {header}"}
    if data[:MAGIC_SIZE] != MAGIC:
        return {"valid": False, "error": f"bad magic: {data[:MAGIC_SIZE]!r}"}

    crc_stored = struct.unpack(">H", data[MAGIC_SIZE:MAGIC_SIZE + CRC_SIZE])[0]
    body = data[MAGIC_SIZE + CRC_SIZE:]                # everything after CRC
    crc_computed = _crc16(body)

    algo_val = body[0]
    dep_count = body[1]
    pos = 2

    deps = []
    for _ in range(dep_count):
        (d,) = struct.unpack(">H", body[pos:pos + 2])
        deps.append(d)
        pos += 2

    content = body[pos:]

    return {
        "valid": crc_computed == crc_stored,
        "algo": algo_val,
        "deps": deps,
        "content": content,
        "crc_stored": crc_stored,
        "crc_computed": crc_computed,
        "content_text": content.decode("utf-8", errors="replace"),
        "error": None if crc_computed == crc_stored else f"CRC mismatch: stored={crc_stored:#06x} computed={crc_computed:#06x}",
    }


# ── CLI ─────────────────────────────────────────────────────────


def _fmt_glyph(data: bytes, label: str = "") -> dict:
    result = unpack_glyph(data)
    result["hex"] = data.hex()
    result["label"] = label
    result["bytes"] = len(data)
    return result


def cmd_mint(args: list[str]) -> None:
    text = " ".join(args) if args else "65536 glyph protocol"
    content = text.encode("utf-8")
    glyph = pack_glyph(content)
    r = unpack_glyph(glyph)
    print(f"minted: {len(glyph)}B | CRC={r['crc_computed']:#06x} | content={text!r}")
    print(glyph.hex())
    print(f"reversed: {text[::-1]!r}")


def cmd_verify(args: list[str]) -> None:
    if len(args) < 2:
        print("usage: verify <hex> <expected_text>")
        sys.exit(1)
    hex_str, expected = args[0], args[1]
    data = bytes.fromhex(hex_str)
    r = unpack_glyph(data)
    if not r["valid"]:
        print(f"INVALID: {r['error']}")
        sys.exit(1)
    text = r["content_text"]
    if text == expected:
        print(f"PASS: {expected!r} ({len(data)}B, CRC={r['crc_stored']:#06x})")
    else:
        print(f"FAIL: expected {expected!r}, got {text!r}")
        sys.exit(1)


def cmd_roundtrip(args: list[str]) -> None:
    """Decode, reverse text, re-encode, verify. No subagent needed."""
    if len(args) < 1:
        print("usage: roundtrip <hex>")
        sys.exit(1)
    hex_str = args[0]
    data = bytes.fromhex(hex_str)
    r = unpack_glyph(data)
    if not r["valid"]:
        print(f"INVALID: {r['error']}")
        sys.exit(1)
    reversed_text = r["content_text"][::-1]
    out = pack_glyph(reversed_text.encode("utf-8"), deps=r["deps"],
                     algo=ChecksumAlgo(r["algo"]))
    rr = unpack_glyph(out)
    assert rr["valid"], "re-packed glyph fails self-verify"
    print(f"roundtrip: {len(data)}B → {len(out)}B")
    print(f"  original:  {r['content_text']!r}")
    print(f"  reversed:  {reversed_text!r}")
    print(f"  input:  {hex_str}")
    print(f"  output: {out.hex()}")
    print(f"  status: PASS (local self-roundtrip)")


def cmd_batch(args: list[str]) -> None:
    """Mint one glyph per line from a text file."""
    if not args:
        print("usage: batch <text_file>")
        sys.exit(1)
    path = args[0]
    with open(path) as f:
        lines = [line.rstrip("\n") for line in f if line.strip()]
    for i, text in enumerate(lines):
        content = text.encode("utf-8")
        glyph = pack_glyph(content)
        r = unpack_glyph(glyph)
        print(f"[{i:3d}] {r['crc_stored']:#06x}  {len(glyph):3d}B  {text!r}")
        print(f"       {glyph.hex()}")


USAGE = __doc__


def main() -> None:
    if len(sys.argv) < 2:
        print(USAGE)
        return

    cmd = sys.argv[1]
    rest = sys.argv[2:]

    dispatch = {
        "mint": cmd_mint,
        "verify": cmd_verify,
        "roundtrip": cmd_roundtrip,
        "batch": cmd_batch,
    }

    if cmd in dispatch:
        dispatch[cmd](rest)
    else:
        print(f"unknown command: {cmd}")
        print(USAGE)


if __name__ == "__main__":
    main()
