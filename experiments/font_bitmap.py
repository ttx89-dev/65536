"""
font_bitmap.py — Two-Glyph Protocol Font Generator (Bootstrap)

Builds a TrueType font where PUA codepoints U+E000..U+E0FF each
render as the ASCII character at the corresponding 16x16 grid position
in a schema. This makes the two-glyph protocol visually readable:
type a schema character + a message character and see the decoded text.

Usage:
    python experiments/font_bitmap.py generate <font_name>  # Build TTF
    python experiments/font_bitmap.py test                  # Print test table
    python experiments/font_bitmap.py inspect <ttf_path>    # Show font metadata

Dependencies: fonttools (pip install fonttools)
"""

import struct, sys, os
from io import BytesIO

# ── 5×7 ASCII bitmap font (public domain, embedded system standard) ──────
# Each printable ASCII character (32-126) encoded as 7 bytes × 5 bits/row.
# Bit 7..3 = pixel columns, bit 2..0 unused. 1 = black, 0 = white.
# 95 characters × 7 bytes = 665 bytes total.
_FONT5X7_RAW = bytes([
    0x00,0x00,0x00,0x00,0x00,0x00,0x00,  # 32  space
    0x20,0x20,0x20,0x20,0x00,0x20,0x00,  # 33  !
    0x50,0x50,0x50,0x00,0x00,0x00,0x00,  # 34  "
    0x50,0x50,0xf8,0x50,0xf8,0x50,0x50,  # 35  #
    0x20,0x78,0xa0,0x70,0x28,0xf0,0x20,  # 36  $
    0xc0,0xc8,0x10,0x20,0x40,0x98,0x18,  # 37  %
    0x40,0xa0,0x40,0xa8,0x90,0x68,0x00,  # 38  &
    0x10,0x20,0x40,0x00,0x00,0x00,0x00,  # 39  '
    0x10,0x20,0x40,0x40,0x40,0x20,0x10,  # 40  (
    0x40,0x20,0x10,0x10,0x10,0x20,0x40,  # 41  )
    0x00,0x20,0xa8,0x70,0xa8,0x20,0x00,  # 42  *
    0x00,0x20,0x20,0xf8,0x20,0x20,0x00,  # 43  +
    0x00,0x00,0x00,0x00,0x20,0x20,0x40,  # 44  ,
    0x00,0x00,0x00,0xf8,0x00,0x00,0x00,  # 45  -
    0x00,0x00,0x00,0x00,0x00,0x40,0x00,  # 46  .
    0x00,0x08,0x10,0x20,0x40,0x80,0x00,  # 47  /
    0x70,0x88,0x88,0x88,0x88,0x88,0x70,  # 48  0
    0x20,0x60,0x20,0x20,0x20,0x20,0x70,  # 49  1
    0x70,0x88,0x08,0x10,0x20,0x40,0xf8,  # 50  2
    0x70,0x88,0x08,0x30,0x08,0x88,0x70,  # 51  3
    0x10,0x30,0x50,0x90,0xf8,0x10,0x10,  # 52  4
    0xf8,0x80,0xf0,0x08,0x08,0x88,0x70,  # 53  5
    0x30,0x40,0x80,0xf0,0x88,0x88,0x70,  # 54  6
    0xf8,0x08,0x10,0x20,0x40,0x40,0x40,  # 55  7
    0x70,0x88,0x88,0x70,0x88,0x88,0x70,  # 56  8
    0x70,0x88,0x88,0x78,0x08,0x10,0x60,  # 57  9
    0x00,0x00,0x20,0x00,0x20,0x00,0x00,  # 58  :
    0x00,0x00,0x20,0x00,0x20,0x20,0x40,  # 59  ;
    0x10,0x20,0x40,0x80,0x40,0x20,0x10,  # 60  <
    0x00,0x00,0xf8,0x00,0xf8,0x00,0x00,  # 61  =
    0x40,0x20,0x10,0x08,0x10,0x20,0x40,  # 62  >
    0x70,0x88,0x08,0x10,0x20,0x00,0x20,  # 63  ?
    0x70,0x88,0x08,0x68,0xa8,0xa8,0x70,  # 64  @
    0x20,0x50,0x88,0x88,0xf8,0x88,0x88,  # 65  A
    0xf0,0x88,0x88,0xf0,0x88,0x88,0xf0,  # 66  B
    0x70,0x88,0x80,0x80,0x80,0x88,0x70,  # 67  C
    0xe0,0x90,0x88,0x88,0x88,0x90,0xe0,  # 68  D
    0xf8,0x80,0x80,0xf0,0x80,0x80,0xf8,  # 69  E
    0xf8,0x80,0x80,0xf0,0x80,0x80,0x80,  # 70  F
    0x70,0x88,0x80,0x98,0x88,0x88,0x70,  # 71  G
    0x88,0x88,0x88,0xf8,0x88,0x88,0x88,  # 72  H
    0x70,0x20,0x20,0x20,0x20,0x20,0x70,  # 73  I
    0x38,0x10,0x10,0x10,0x10,0x90,0x60,  # 74  J
    0x88,0x90,0xa0,0xc0,0xa0,0x90,0x88,  # 75  K
    0x80,0x80,0x80,0x80,0x80,0x80,0xf8,  # 76  L
    0x88,0xd8,0xa8,0xa8,0x88,0x88,0x88,  # 77  M
    0x88,0xc8,0xa8,0x98,0x88,0x88,0x88,  # 78  N
    0x70,0x88,0x88,0x88,0x88,0x88,0x70,  # 79  O
    0xf0,0x88,0x88,0xf0,0x80,0x80,0x80,  # 80  P
    0x70,0x88,0x88,0x88,0x88,0xa8,0x70,  # 81  Q  (with tail)
    0xf0,0x88,0x88,0xf0,0xa0,0x90,0x88,  # 82  R
    0x70,0x88,0x80,0x70,0x08,0x88,0x70,  # 83  S
    0xf8,0x20,0x20,0x20,0x20,0x20,0x20,  # 84  T
    0x88,0x88,0x88,0x88,0x88,0x88,0x70,  # 85  U
    0x88,0x88,0x88,0x88,0x50,0x50,0x20,  # 86  V
    0x88,0x88,0x88,0xa8,0xa8,0xd8,0x88,  # 87  W
    0x88,0x88,0x50,0x20,0x50,0x88,0x88,  # 88  X
    0x88,0x88,0x50,0x20,0x20,0x20,0x20,  # 89  Y
    0xf8,0x08,0x10,0x20,0x40,0x80,0xf8,  # 90  Z
    0x70,0x40,0x40,0x40,0x40,0x40,0x70,  # 91  [
    0x00,0x80,0x40,0x20,0x10,0x08,0x00,  # 92  backslash
    0x70,0x10,0x10,0x10,0x10,0x10,0x70,  # 93  ]
    0x20,0x50,0x88,0x00,0x00,0x00,0x00,  # 94  ^
    0x00,0x00,0x00,0x00,0x00,0x00,0xf8,  # 95  _
    0x40,0x20,0x10,0x00,0x00,0x00,0x00,  # 96  `
    0x00,0x00,0x70,0x08,0x78,0x88,0x78,  # 97  a
    0x80,0x80,0xf0,0x88,0x88,0x88,0xf0,  # 98  b
    0x00,0x00,0x70,0x88,0x80,0x88,0x70,  # 99  c
    0x08,0x08,0x78,0x88,0x88,0x88,0x78,  # 100 d
    0x00,0x00,0x70,0x88,0xf8,0x80,0x70,  # 101 e
    0x10,0x28,0x20,0x70,0x20,0x20,0x20,  # 102 f
    0x00,0x00,0x78,0x88,0x88,0x78,0x08,  # 103 g (with descender)
    0x80,0x80,0xf0,0x88,0x88,0x88,0x88,  # 104 h
    0x20,0x00,0x20,0x20,0x20,0x20,0x10,  # 105 i (with dot)
    0x08,0x00,0x08,0x08,0x08,0x08,0x88,  # 106 j (with descender)
    0x80,0x80,0x90,0xa0,0xc0,0xa0,0x90,  # 107 k
    0x60,0x20,0x20,0x20,0x20,0x20,0x70,  # 108 l
    0x00,0x00,0xd0,0xa8,0xa8,0xa8,0x88,  # 109 m
    0x00,0x00,0xf0,0x88,0x88,0x88,0x88,  # 110 n
    0x00,0x00,0x70,0x88,0x88,0x88,0x70,  # 111 o
    0x00,0x00,0xf0,0x88,0x88,0xf0,0x80,  # 112 p (with descender)
    0x00,0x00,0x78,0x88,0x88,0x78,0x08,  # 113 q (with descender)
    0x00,0x00,0xb0,0xc8,0x80,0x80,0x80,  # 114 r
    0x00,0x00,0x78,0x80,0x70,0x08,0xf0,  # 115 s
    0x20,0x20,0xf8,0x20,0x20,0x28,0x10,  # 116 t
    0x00,0x00,0x88,0x88,0x88,0x88,0x70,  # 117 u
    0x00,0x00,0x88,0x88,0x88,0x50,0x20,  # 118 v
    0x00,0x00,0x88,0xa8,0xa8,0xa8,0x50,  # 119 w
    0x00,0x00,0x88,0x50,0x20,0x50,0x88,  # 120 x
    0x00,0x00,0x88,0x88,0x78,0x08,0x70,  # 121 y (with descender)
    0x00,0x00,0xf8,0x10,0x20,0x40,0xf8,  # 122 z
    0x10,0x20,0x20,0x40,0x20,0x20,0x10,  # 123 {
    0x20,0x20,0x20,0x20,0x20,0x20,0x20,  # 124 |
    0x40,0x20,0x20,0x10,0x20,0x20,0x40,  # 125 }
    0x00,0x00,0x00,0x00,0x40,0xa8,0x10,  # 126 ~
])

# ── TrueType constants ────────────────────────────────────────────────────
from fontTools.pens.ttGlyphPen import TTGlyphPen

UNITS_PER_EM   = 1000
PIXEL_SIZE     = 120    # TrueType units per pixel
PADDING_X      = 50     # left/right padding
PADDING_Y      = 80     # top/bottom padding
GLYPH_WIDTH    = 5 * PIXEL_SIZE + 2 * PADDING_X   # 700
GLYPH_HEIGHT   = 7 * PIXEL_SIZE + 2 * PADDING_Y   # 1000
ADVANCE_WIDTH  = GLYPH_WIDTH                        # 700
DESCENDER      = PADDING_Y                          # 80 (space below baseline)

def _char_bitmap(ascii_code):
    """Return 7-byte bitmap for an ASCII character (32-126)."""
    idx = (ascii_code - 32) * 7
    return _FONT5X7_RAW[idx:idx+7]

def _bitmap_to_contours(bitmap, flip_y=True):
    """Convert a 5×7 bitmap (7 bytes) to list of TrueType contours.
    
    Each lit pixel becomes a small square contour (4 points, closed).
    Pixels are mapped to TrueType coordinates with y optionally flipped
    (TrueType y-axis points up, bitmap rows go top→bottom).
    """
    contours = []
    for row in range(7):
        byte = bitmap[row]
        for col in range(5):
            if byte & (0x80 >> col):  # bit 7 = leftmost pixel
                # Pixel square in TrueType coords
                x0 = PADDING_X + col * PIXEL_SIZE
                y0 = PADDING_Y + row * PIXEL_SIZE
                x1 = x0 + PIXEL_SIZE
                y1 = y0 + PIXEL_SIZE
                
                if flip_y:
                    # Flip y so row 0 (top of bitmap) → highest y in TTF
                    y0, y1 = GLYPH_HEIGHT - y1, GLYPH_HEIGHT - y0
                
                # Contour: 4 points (bottom-left → bottom-right → top-right → top-left)
                pts = [
                    (x0, y0),  # bottom-left
                    (x1, y0),  # bottom-right
                    (x1, y1),  # top-right
                    (x0, y1),  # top-left
                ]
                contours.append(pts)
    return contours

def _make_glyph_pen(ascii_code):
    """Build a TTGlyphPen for an ASCII character, returns (pen, glyph)."""
    from fontTools.pens.ttGlyphPen import TTGlyphPen
    
    pen = TTGlyphPen(None)
    bitmap = _char_bitmap(ascii_code)
    contours = _bitmap_to_contours(bitmap)
    
    if not contours:
        # Empty glyph (space) — just add a zero-width contour to make it valid
        pen.moveTo((0, 0))
        pen.lineTo((ADVANCE_WIDTH, 0))
        pen.lineTo((ADVANCE_WIDTH, 20))
        pen.lineTo((0, 20))
        pen.closePath()
    else:
        for contour in contours:
            pen.moveTo(contour[0])
            for pt in contour[1:]:
                pen.lineTo(pt)
            pen.closePath()
    
    return pen, pen.glyph()

# ── Font generation ──────────────────────────────────────────────────────

def build_schema_table():
    """Build the default 256-entry schema table (same as two_glyph_test.py).
    
    Positions populated with ASCII characters in a logical layout:
    - Rows 0-1: uppercase A-Z, 0-9, punctuation
    - Rows 2-3: lowercase a-z, 0-9, punctuation
    - Remaining: repeats for coverage
    """
    table = bytearray(256)
    chars = (
        "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
        "abcdefghijklmnopqrstuvwxyz"
        "0123456789 .!?'\"-:;()/\\@#$%^&*+=<>[]{}~_|"
    )
    pos = 0
    for c in chars:
        if pos < 256:
            table[pos] = ord(c)
            pos += 1
    # Fill remaining with space
    while pos < 256:
        table[pos] = 32
        pos += 1
    return bytes(table)

def generate_ttf(schema_table=None, font_name="65536-Glyph"):
    """Generate a TTF font where U+E000+n renders the char at schema[n].
    
    Returns the TTF as bytes.
    """
    if schema_table is None:
        schema_table = build_schema_table()
    
    if len(schema_table) != 256:
        raise ValueError(f"Schema table must be 256 bytes, got {len(schema_table)}")
    
    # ── Step 1: Build TrueType font via manual table construction ──
    # For maximum control, we write the TTF directly using low-level APIs.
    
    from fontTools.ttLib import TTFont
    from fontTools.fontBuilder import FontBuilder
    
    fb = FontBuilder(UNITS_PER_EM, isTTF=True)
    
    # Glyph order: .notdef, then PUA_0000 through PUA_00FF
    # We'll create one base glyph per unique ASCII character, then
    # composite glyphs for the PUA codepoints that reference them.
    
    # Collect unique characters in the schema
    unique_chars = sorted(set(schema_table))
    base_glyph_map = {}  # ascii_code → glyph name
    
    # Build glyph order
    glyph_order = [".notdef"]
    for code in unique_chars:
        name = f"char{code:02X}"
        base_glyph_map[code] = name
        glyph_order.append(name)
    
    # Add PUA glyph names
    pua_names = []
    for i in range(256):
        name = f"pua{i:04X}"
        pua_names.append(name)
        glyph_order.append(name)
    
    fb.setupGlyphOrder(glyph_order)
    
    # ── Step 2: Build character map ──
    # PUA codepoints: U+E000 + position
    cmap = {0xE000 + i: f"pua{i:04X}" for i in range(256)}
    cmap[0x0000] = ".notdef"  # .notdef should handle unencoded chars
    fb.setupCharacterMap(cmap)
    
    # ── Step 3: Build glyph outlines ──
    # Build all simple glyphs first, then composite PUA glyphs.
    glyf = {}
    
    # .notdef (empty glyph)
    pen = TTGlyphPen(None)
    pen.moveTo((0, 0))
    pen.lineTo((ADVANCE_WIDTH, 0))
    pen.lineTo((ADVANCE_WIDTH, 20))
    pen.lineTo((0, 20))
    pen.closePath()
    glyf[".notdef"] = pen.glyph()
    
    # Build all base glyphs
    for code, name in base_glyph_map.items():
        _, glyph = _make_glyph_pen(code)
        glyf[name] = glyph
    
    # PUA composite glyphs: need a glyphSet so component resolution works
    # Create a minimal mapping: glyph name → glyph object
    class GlyphSet:
        def __init__(self, glyphs):
            self._glyphs = glyphs
        def __contains__(self, name):
            return name in self._glyphs
        def __getitem__(self, name):
            return self._glyphs[name]
    
    glyph_set = GlyphSet(glyf)
    
    for i in range(256):
        name = pua_names[i]
        char_code = schema_table[i]
        base_name = base_glyph_map.get(char_code, ".notdef")
        
        pen = TTGlyphPen(glyph_set)
        pen.addComponent(base_name, (1.0, 0.0, 0.0, 1.0, 0.0, 0.0))
        glyf[name] = pen.glyph()
    
    fb.setupGlyf(glyf)
    
    # ── Step 4: Horizontal metrics ──
    hmtx = {name: (ADVANCE_WIDTH, 0) for name in glyph_order}
    fb.setupHorizontalMetrics(hmtx)
    
    # ── Step 5: Required tables ──
    fb.setupHorizontalHeader()
    fb.setupNameTable({
        "familyName": font_name,
        "styleName": "Regular",
    })
    fb.setupOS2(sTypoAscender=800, sTypoDescender=-200, usWinAscent=1000, usWinDescent=0)
    fb.setupPost()
    
    # ── Step 6: Save to bytes ──
    buf = BytesIO()
    fb.font.save(buf)
    return buf.getvalue()

def print_test_table(ttf_bytes):
    """Print a visual test table showing the PUA mapping."""
    # We can't render the font in terminal, but we can show the mapping table
    schema = build_schema_table()
    
    print("╔══════════════════════════════════════════╗")
    print("║  65536 Glyph Font — Schema Mapping       ║")
    print("║  PUA U+E000..U+E0FF (256 codepoints)     ║")
    print("╚══════════════════════════════════════════╝")
    print()
    
    for row in range(16):
        row_chars = []
        for col in range(16):
            idx = row * 16 + col
            cp = 0xE000 + idx
            ch = chr(schema[idx]) if 32 <= schema[idx] < 127 else "?"
            row_chars.append(f"U+{cp:04X}={ch}")
        
        label = f"Row {row:2d}: "
        print(label + "  ".join(f"{cp:04X}={ch}" for cp, ch in 
              [(0xE000 + row*16 + col, chr(schema[row*16+col]) if 32 <= schema[row*16+col] < 127 else "?")
               for col in range(16)]))
    
    print()
    print(f"Font size: {len(ttf_bytes)} bytes")
    print(f"{256} PUA codepoints mapped")
    print(f"{len(set(schema))} unique ASCII characters")

# ── CLI ────────────────────────────────────────────────────────────────────

def cmd_generate(args):
    """Generate the TTF font file."""
    font_name = args[0] if args else "65536-Glyph"
    ttf = generate_ttf(font_name=font_name)
    path = f"{font_name}.ttf"
    with open(path, "wb") as f:
        f.write(ttf)
    print(f"✓ Generated {path} ({len(ttf)} bytes)")
    print(f"  PUA range: U+E000..U+E0FF")
    print(f"  Install: copy {path} to ~/.fonts/ then set terminal font")
    return path

def cmd_inspect(args):
    """Inspect a generated TTF file."""
    path = args[0] if args else "65536-Glyph.ttf"
    if not os.path.exists(path):
        print(f"✗ File not found: {path}")
        return
    
    from fontTools.ttLib import TTFont
    font = TTFont(path)
    
    print(f"File: {path}")
    print(f"Units per em: {font['head'].unitsPerEm}")
    print(f"Glyph count: {len(font.getGlyphOrder())}")
    
    cmap = font['cmap']
    for table in cmap.tables:
        if table.format == 4 or table.format == 12:
            pua_count = sum(1 for cp in table.cmap if 0xE000 <= cp <= 0xE0FF)
            print(f"cmap format {table.format}: {len(table.cmap)} entries ({pua_count} PUA)")
    
    print(f"OS/2: usWeightClass={font['OS/2'].usWeightClass}")

def cmd_test(args):
    """Print the schema mapping table."""
    schema = build_schema_table()
    ttf = generate_ttf()
    print_test_table(ttf)

# ── Main ───────────────────────────────────────────────────────────────────

def main():
    if len(sys.argv) < 2:
        print("Usage:")
        print("  python experiments/font_bitmap.py generate [name]   Build TTF")
        print("  python experiments/font_bitmap.py test              Print mapping table")
        print("  python experiments/font_bitmap.py inspect [path]    Inspect TTF")
        return
    
    cmd = sys.argv[1]
    rest = sys.argv[2:]
    
    if cmd == "generate":
        cmd_generate(rest)
    elif cmd == "test":
        cmd_test(rest)
    elif cmd == "inspect":
        cmd_inspect(rest)
    else:
        print(f"Unknown command: {cmd}")

if __name__ == "__main__":
    main()
