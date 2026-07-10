#!/usr/bin/env python3
"""
two_glyph_test.py — Two-glyph protocol: Schema + Message round trip.

VISION (user's):
  Glyph 1 = Schema — defines the coordinate space. "At dot (row=4, col=7)
            the character is 'H'." This IS the mapping framework.
  Glyph 2 = Message — the actual payload encoded using the schema. "Look
            up these coordinates to get: HELLO."

MECHANICS:
  Schema glyph encodes a 16×16 = 256-entry lookup table. Position
  (row, col) maps to a character. The table is the key — once known,
  any message can be encoded as coordinate references.

  Message glyph carries the payload text, with a DEPENDENCY link to
  the schema glyph. The subagent reads: "I depend on schema at addr X;
  resolve that to get the mapping table; now decode my payload."

PROTOCOL:
  1. Mint Schema Glyph: 256-byte mapping table → GLPH hex
  2. Mint Message Glyph: given text, look up each char in schema,
     store coordinates OR just store the text (with dep on schema)
  3. Send both to subagent
  4. Subagent: resolve schema → build table → decode message →
     transform → re-encode → send back
  5. Verify

ROUND TRIP (this file, local-only first):
  $ python experiments/two_glyph_test.py roundtrip "HELLO"
  → mints schema glyph + message glyph
  → decodes message using schema
  → reverses text
  → re-encodes
  → verifies

  Then (subagent):
  $ python experiments/two_glyph_test.py dispatch "HELLO"
  → same, but dispatches to subagent via GLPH hex

BINARY FORMAT:
  Schema glyph content:
    [magic:    4B]  b"SKMA"  (schema magic)
    [version:  1B]  schema version (1)
    [width:    1B]  grid width (16)
    [height:   1B]  grid height (16)
    [table:  256B]  lookup: table[row*16 + col] = ascii char code

  Message glyph content:
    [text:    vB]  UTF-8 encoded text to transform
"""

import struct
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from experiments.glyph_protocol import pack_glyph, unpack_glyph, _crc16, MAGIC

SCHEMA_MAGIC = b"SKMA"
SCHEMA_VERSION = 1
GRID_WIDTH = 16
GRID_HEIGHT = 16
GRID_SIZE = GRID_WIDTH * GRID_HEIGHT  # 256

# ── Schema Glyph ───────────────────────────────────────────────────

def build_schema_table(charset: str | None = None) -> bytes:
    """Build a 256-byte lookup table mapping grid positions to characters.

    Default charset fills the 16×16 grid with:
      row 0: A-P (alphabetic 1-16)
      row 1: Q-f (alphabetic 17-32)
      ...filling sequentially through A-Z, 0-9, punctuation
      Then wraps remaining cells
    """
    if charset is not None:
        encoded = charset.encode("ascii")
        if len(encoded) < GRID_SIZE:
            encoded = encoded + b"\x00" * (GRID_SIZE - len(encoded))
        return encoded[:GRID_SIZE]

    # Build a reasonable default 256-char charset
    chars = []
    # A-Z (26)
    chars.extend(range(ord('A'), ord('Z') + 1))
    # a-z (26)
    chars.extend(range(ord('a'), ord('z') + 1))
    # 0-9 (10)
    chars.extend(range(ord('0'), ord('9') + 1))
    # punctuation
    chars.extend([ord(' '), ord('.'), ord(','), ord('!'), ord('?'),
                  ord('\''), ord('"'), ord('-'), ord(':'), ord(';'),
                  ord('('), ord(')'), ord('/'), ord('\\'), ord('@'),
                  ord('#'), ord('$'), ord('%'), ord('^'), ord('&'),
                  ord('*'), ord('+'), ord('='), ord('<'), ord('>'),
                  ord('['), ord(']'), ord('{'), ord('}'), ord('~'),
                  ord('`'), ord('_'), ord('|')])
    # Repeat to fill 256
    while len(chars) < GRID_SIZE:
        chars.extend(chars[:GRID_SIZE - len(chars)])
    return bytes(chars[:GRID_SIZE])


def mint_schema_glyph(charset: str | None = None, addr: int = 0x0101) -> tuple[bytes, dict]:
    """Create a schema glyph. Returns (glyph_bytes, info_dict)."""
    table = build_schema_table(charset)
    content = SCHEMA_MAGIC + bytes([SCHEMA_VERSION, GRID_WIDTH, GRID_HEIGHT]) + table
    glyph = pack_glyph(content, deps=[])  # schema has no deps
    info = unpack_glyph(glyph)
    info["table"] = table
    info["address"] = addr
    info["grid_width"] = GRID_WIDTH
    info["grid_height"] = GRID_HEIGHT
    info["charset"] = charset or "default"
    info["char_count"] = len(set(b for b in table if b != 0))
    return glyph, info


def decode_schema_glyph(data: bytes) -> dict:
    """Read a schema glyph and return the lookup and reverse-lookup tables."""
    r = unpack_glyph(data)
    if not r["valid"]:
        return {"valid": False, "error": r.get("error", "invalid glyph")}
    content = r["content"]
    if content[:4] != SCHEMA_MAGIC:
        return {"valid": False, "error": f"bad schema magic: {content[:4]!r}"}

    version = content[4]
    width = content[5]
    height = content[6]
    table = content[7:7 + width * height]

    # Build forward lookup: (row, col) → char
    forward = {}
    for idx, char_code in enumerate(table):
        row = idx // width
        col = idx % width
        forward[(row, col)] = chr(char_code) if char_code else None

    # Build reverse lookup: char → (row, col)
    reverse = {}
    for idx, char_code in enumerate(table):
        if char_code:
            row = idx // width
            col = idx % width
            ch = chr(char_code)
            if ch not in reverse:  # first occurrence wins
                reverse[ch] = (row, col)

    return {
        "valid": True,
        "version": version,
        "width": width,
        "height": height,
        "table": table,
        "forward": forward,
        "reverse": reverse,
        "char_count": len(reverse),
    }


# ── Message Glyph ──────────────────────────────────────────────────

def mint_message_glyph(text: str, schema_addr: int = 0x0101,
                       raw: bool = True) -> tuple[bytes, dict]:
    """Create a message glyph encoding the given text.

    If raw=True: the content IS the UTF-8 text (simple, testable).
    If raw=False: the content is coordinate references using the schema.

    The glyph declares a dependency on schema_addr.
    """
    content = text.encode("utf-8")
    glyph = pack_glyph(content, deps=[schema_addr])
    info = unpack_glyph(glyph)
    info["text"] = text
    info["schema_addr"] = schema_addr
    return glyph, info


def decode_message_glyph(data: bytes, schema_data: bytes | None = None) -> dict:
    """Read a message glyph. If schema_data is provided, also decode
    the text using the schema's mapping."""
    r = unpack_glyph(data)
    if not r["valid"]:
        return {"valid": False, "error": r.get("error", "invalid glyph")}

    text = r["content_text"]
    deps = r["deps"]

    result = {
        "valid": True,
        "text": text,
        "deps": deps,
        "content": r["content"],
    }

    # If schema is provided, show the coordinate-based encoding
    if schema_data is not None:
        schema = decode_schema_glyph(schema_data)
        if schema.get("valid"):
            reverse = schema["reverse"]
            coords = []
            for ch in text:
                if ch in reverse:
                    coords.append(reverse[ch])
                else:
                    coords.append(NONE)
            result["schema_coords"] = coords
            result["schema_char_count"] = schema["char_count"]

    return result


# ── Text-to-schema encoding (coordinate form) ─────────────────────

def text_to_coords(text: str, schema_data: bytes) -> list:
    """Convert text to a list of (row, col) coordinates using schema."""
    schema = decode_schema_glyph(schema_data)
    if not schema.get("valid"):
        raise ValueError(f"invalid schema: {schema.get('error')}")
    forward = schema["forward"]
    # Build char→coord map
    char_to_coord = {}
    for (r, c), ch in forward.items():
        if ch and ch not in char_to_coord:
            char_to_coord[ch] = (r, c)

    coords = []
    for ch in text:
        if ch in char_to_coord:
            coords.append(char_to_coord[ch])
        else:
            raise ValueError(f"character {ch!r} not in schema")
    return coords


def coords_to_text(coords: list, schema_data: bytes) -> str:
    """Convert a list of (row, col) coordinates back to text using schema."""
    schema = decode_schema_glyph(schema_data)
    if not schema.get("valid"):
        raise ValueError(f"invalid schema: {schema.get('error')}")
    forward = schema["forward"]
    chars = []
    for (r, c) in coords:
        ch = forward.get((r, c))
        if ch is None:
            raise ValueError(f"no character at ({r}, {c})")
        chars.append(ch)
    return "".join(chars)


# ── CLI ───────────────────────────────────────────────────────────

SCHEMA_ADDR = 0x0101  # Schema lives at tier=1, cat=0, idx=1


def cmd_mint_schema(args: list[str]) -> None:
    """Mint a schema glyph. Optionally provide a charset string."""
    charset = " ".join(args) if args else None
    glyph, info = mint_schema_glyph(charset)
    print(f"schema glyph: {len(glyph)}B | CRC={info['crc_stored']:#06x} | {info['charset']}")
    print(f"  charset size: {info['char_count']} unique chars in {GRID_SIZE} cells")
    print(f"  hex: {glyph.hex()}")
    print(f"  address: 0x{SCHEMA_ADDR:04x}")


def cmd_mint_message(args: list[str]) -> None:
    """Mint a message glyph encoding the given text."""
    text = " ".join(args) if args else "HELLO"
    glyph, info = mint_message_glyph(text, schema_addr=SCHEMA_ADDR)
    print(f"message glyph: {len(glyph)}B | CRC={info['crc_stored']:#06x}")
    print(f"  text: {text!r}")
    print(f"  deps: {[hex(d) for d in info['deps']]}")
    print(f"  hex: {glyph.hex()}")


def cmd_decode(args: list[str]) -> None:
    """Decode a glyph hex, with optional schema for coordinate decode."""
    if not args:
        print("usage: decode <glyph_hex> [schema_hex]")
        sys.exit(1)
    data = bytes.fromhex(args[0])
    schema_data = bytes.fromhex(args[1]) if len(args) > 1 else None
    r = unpack_glyph(data)
    print(f"valid: {r['valid']} | algo={r['algo']} | deps={[hex(d) for d in r['deps']]}")
    print(f"content: {r['content_text']!r}")
    if schema_data:
        coords = text_to_coords(r["content_text"], schema_data)
        print(f"coords: {coords}")
    if not r["valid"]:
        print(f"error: {r['error']}")


def cmd_roundtrip(args: list[str]) -> None:
    """Full two-glyph round trip: mint schema + message, decode, reverse,
    re-encode, verify."""
    text = " ".join(args) if args else "HELLO"
    print(f"=== TWO-GLYPH ROUND TRIP: {text!r} ===\n")

    # 1. Mint schema
    schema_glyph, schema_info = mint_schema_glyph()
    print(f"[1] Schema glyph: {len(schema_glyph)}B | CRC={schema_info['crc_stored']:#06x}")
    print(f"    {schema_info['char_count']} unique chars")
    print(f"    hex: {schema_glyph.hex()}\n")

    # 2. Mint message
    msg_glyph, msg_info = mint_message_glyph(text, schema_addr=SCHEMA_ADDR)
    print(f"[2] Message glyph: {len(msg_glyph)}B | CRC={msg_info['crc_stored']:#06x}")
    print(f"    text: {text!r}")
    print(f"    deps: {[hex(d) for d in msg_info['deps']]}")
    print(f"    hex: {msg_glyph.hex()}\n")

    # 3. Decode message using schema
    msg_decoded = decode_message_glyph(msg_glyph, schema_glyph)
    print(f"[3] Decoded: {msg_decoded['text']!r}")
    if msg_decoded.get("schema_coords"):
        coord_str = ", ".join(f"({r},{c})" for r, c in msg_decoded["schema_coords"])
        print(f"    coords: {coord_str}")
        # Also encode as raw coordinate bytes
        coord_bytes = b""
        for r, c in msg_decoded["schema_coords"]:
            coord_bytes += bytes([r, c])
        coord_glyph = pack_glyph(coord_bytes, deps=[SCHEMA_ADDR])
        print(f"    as coordinate glyph: {coord_bytes.hex()} ({len(coord_glyph)}B total)\n")

    # 4. Reverse text
    reversed_text = text[::-1]
    print(f"[4] Reversed: {reversed_text!r}\n")

    # 5. Mint reversed message
    rev_glyph, rev_info = mint_message_glyph(reversed_text, schema_addr=SCHEMA_ADDR)
    print(f"[5] Reversed message glyph: {len(rev_glyph)}B | CRC={rev_info['crc_stored']:#06x}")
    print(f"    hex: {rev_glyph.hex()}\n")

    # 6. Verify
    rev_decoded = decode_message_glyph(rev_glyph)
    assert rev_decoded["valid"], "reversed glyph failed self-verify"
    assert rev_decoded["text"] == reversed_text, \
        f"text mismatch: expected {reversed_text!r}, got {rev_decoded['text']!r}"
    print(f"[6] VERIFY PASS: {text!r} → {reversed_text!r}")
    print(f"    schema: {len(schema_glyph)}B + msg: {len(msg_glyph)}B + reversed: {len(rev_glyph)}B")
    total = len(schema_glyph) + len(msg_glyph) + len(rev_glyph)
    print(f"    total two-glyph traffic: {total}B ({total - len(schema_glyph)}B excluding schema reuse)")


def cmd_dispatch(args: list[str]) -> None:
    """Prepare for subagent dispatch. Mints schema + message and prints
    the dispatch packet: schema_hex, message_hex, instructions."""
    text = " ".join(args) if args else "HELLO"
    schema_glyph, si = mint_schema_glyph()
    msg_glyph, mi = mint_message_glyph(text)

    print(f"""=== DISPATCH PACKET for subagent ===

INSTRUCTIONS:
You receive two glyphs: one schema glyph and one message glyph.
1. Decode the schema glyph → build the character mapping table
2. Decode the message glyph (depends on schema) → get the text
3. Reverse the text
4. Encode the reversed text as a new message glyph (same schema dependency)
5. Return ONLY the GLPH hex of the new message glyph

SCHEMA ADDRESS: 0x{SCHEMA_ADDR:04x}
SCHEMA GLYPH ({len(schema_glyph)}B, CRC={si['crc_stored']:#06x}): {schema_glyph.hex()}

MESSAGE ({len(msg_glyph)}B, CRC={mi['crc_stored']:#06x}): {msg_glyph.hex()}
""")

    # Verify we can decode our own glyphs
    sd = decode_schema_glyph(schema_glyph)
    md = decode_message_glyph(msg_glyph, schema_glyph)
    print(f"Self-verify: schema valid={sd.get('valid')} ({sd.get('char_count', 0)} chars)")
    print(f"             message valid={md.get('valid')} text={md.get('text')!r}")
    if md.get("schema_coords"):
        print(f"             coords: {[(r,c) for r,c in md['schema_coords']]}")


def cmd_dispatch_efi_engineer(args: list[str]) -> None:
    """Produce prompt for EFE-Engineer subagent dispatch."""
    text = " ".join(args) if args else "HELLO"
    schema_glyph, si = mint_schema_glyph()
    msg_glyph, mi = mint_message_glyph(text)

    print(f"""Dispatch to EFE-ENGINEER (or any subagent):

You are given a two-glyph protocol packet.

GLYPH 1 (SCHEMA): {schema_glyph.hex()}
  This is the schema definition. It contains a 16×16 character mapping
  table. Decode it using the GLPH protocol:
    - Strip 4B magic "GLPH"
    - Read 2B CRC (verify it, don't trust it blindly)
    - Read 1B algo, 1B dep_count (should be 0 for schema)
    - Remaining bytes are content: 4B "SKMA" magic + 1B version +
      1B width + 1B height + 256B lookup table
    - The lookup table maps grid[row*16 + col] → ASCII character

GLYPH 2 (MESSAGE): {msg_glyph.hex()}
  This is a message that depends on GLYPH 1 (dep_count=1).
  Decode similarly: strip GLPH header, verify CRC, read deps.
  The remaining content is UTF-8 text.

TASK:
  1. Decode GLYPH 1 to build the character mapping.
  2. Decode GLYPH 2 to extract the text.
  3. Reverse the text (character order).
  4. Encode the reversed text as a new message glyph using the SAME
     GLPH format, depending on address 0x{SCHEMA_ADDR:04x}.
  5. Return ONLY the hex of the new message glyph.

EXPECTED: The reversed text of {text!r} = {text[::-1]!r}
""")

    print(f"Self-verify:\n  Schema glyph: {len(schema_glyph)}B valid={decode_schema_glyph(schema_glyph).get('valid')}")
    md = decode_message_glyph(msg_glyph, schema_glyph)
    print(f"  Message glyph: {len(msg_glyph)}B text={md.get('text')!r}")
    if md.get("schema_coords"):
        print(f"  Coords: {[(r,c) for r,c in md['schema_coords']]}")
    print(f"  Expected reversed: {text[::-1]!r}")
    rev = pack_glyph(text[::-1].encode('utf-8'), deps=[SCHEMA_ADDR])
    print(f"  Pre-computed reversed hex (for verification): {rev.hex()}")


# ── PUA Rendering ──────────────────────────────────────────────────

def _resolve_schema_table(schema_data: bytes) -> bytes | None:
    """Extract the 256-byte lookup table from a schema glyph, or None."""
    sd = decode_schema_glyph(schema_data)
    if sd.get("valid"):
        return sd["table"]
    return None


def text_to_pua(text: str, schema_data: bytes) -> str:
    """Convert text to PUA codepoint string using schema table.
    
    Each character is looked up in the schema's 256-entry table.
    Its (row, col) position becomes PUA codepoint U+E000 + (row*16 + col).
    """
    table = _resolve_schema_table(schema_data)
    if table is None:
        raise ValueError("invalid schema")
    # Build char → position map (first occurrence wins)
    char_pos = {}
    for idx, code in enumerate(table):
        if code and chr(code) not in char_pos:
            char_pos[chr(code)] = 0xE000 + idx
    # Convert text
    out = []
    for ch in text:
        cp = char_pos.get(ch)
        if cp is None:
            out.append("?")  # fallback for unmapped chars
        else:
            out.append(chr(cp))
    return "".join(out)


def text_from_pua(pua_text: str, schema_data: bytes) -> str:
    """Reverse of text_to_pua: convert PUA text back to ASCII using schema."""
    table = _resolve_schema_table(schema_data)
    if table is None:
        raise ValueError("invalid schema")
    out = []
    for ch in pua_text:
        cp = ord(ch)
        if 0xE000 <= cp < 0xE100:
            idx = cp - 0xE000
            if idx < len(table) and table[idx]:
                out.append(chr(table[idx]))
            else:
                out.append("?")
        else:
            out.append(ch)
    return "".join(out)


def cmd_render(args: list[str]) -> None:
    """Mint schema + message and show as PUA codepoint text.
    
    Requires the 65536-Glyph font installed in the terminal.
    """
    text = " ".join(args) if args else "GLYPH"
    schema_glyph, si = mint_schema_glyph()
    pua_text = text_to_pua(text, schema_glyph)
    print(f"=== PUA RENDER: {text!r} ===\n")
    print(f"Schema: {len(schema_glyph)}B | CRC={si['crc_stored']:#06x}")
    print(f"PUA text  : {pua_text!r}")
    print(f"PUA hex   : {pua_text.encode('utf-8').hex()}")
    print(f"PUA codepoints: {' '.join(f'U+{ord(c):04X}' for c in pua_text)}")
    print()
    # Also show coordinate encoding size
    coords = text_to_coords(text, schema_glyph)
    coord_bytes = b"".join(bytes([r, c]) for r, c in coords)
    print(f"Coordinate encoding: {coord_bytes.hex()} ({len(coord_bytes)}B)")
    print(f"UTF-8 (PUA): {len(pua_text.encode('utf-8'))}B")
    print(f"UTF-8 (raw): {len(text.encode('utf-8'))}B")
    print()
    # Recover original text from PUA
    recovered = text_from_pua(pua_text, schema_glyph)
    ok = recovered == text
    print(f"PUA round trip: {recovered!r} → {'✓' if ok else '✗'}")
    print()
    print("To see in terminal (with font installed):")
    print(f"  python -c 'print({pua_text!r})'")


USAGE = """
Two-glyph protocol test commands:

  schema [charset]       — Mint a schema glyph
  message <text>         — Mint a message glyph  
  decode <hex> [schema]  — Decode a glyph
  roundtrip [text]       — Full local round trip
  render [text]          — Mint schema + message, output as PUA text
  dispatch [text]        — Prepare dispatch packet for subagent
  dispatch-efe [text]    — Prepare EFE-Engineer dispatch packet
"""


def main() -> None:
    if len(sys.argv) < 2:
        print(USAGE.strip())
        return

    cmd = sys.argv[1]
    rest = sys.argv[2:]

    dispatch = {
        "schema": cmd_mint_schema,
        "message": cmd_mint_message,
        "decode": cmd_decode,
        "roundtrip": cmd_roundtrip,
        "render": cmd_render,
        "dispatch": cmd_dispatch,
        "dispatch-efe": cmd_dispatch_efi_engineer,
    }

    if cmd in dispatch:
        dispatch[cmd](rest)
    else:
        print(f"unknown command: {cmd}")
        print(USAGE)


if __name__ == "__main__":
    main()
