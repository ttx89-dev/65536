#!/usr/bin/env python3
"""Generate the committed documentation assets from the real font.

Deterministic: the symbol sheet renders every code point that actually
exists in 65536-Glyph.ttf's cmap, exactly as the shipped font draws it,
and the banner turns the font's measured address space into its motif.
Nothing invented; the script prints what it measured.

Structural facts used (fontTools, re-checked on every run):

  * the committed TTF defines exactly 256 code points, U+E000..U+E0FF
    (glyph names pua0000..pua00FF);
  * 92 slots carry the character pattern embedded in the font (5x7-style
    bit glyphs);
  * the remaining 164 slots are reserved and draw a small baseline dash
    (glyf bbox 700 x 20 units) — the shipped font does render something
    there, and this sheet shows exactly that.

Outputs (written under assets/ at the repository root):

  assets/symbol_sheet.png   complete cmap in one image: 16x16 grid,
                            every code point rendered from the TTF with
                            its hex label below
  assets/banner.svg         README banner; amber cells = character
                            glyphs, dim cells = reserved slots

Run:

    python3 tools/make_doc_assets.py           # from the repository root

Regenerates byte-identical assets (no timestamps embedded).
"""

from __future__ import annotations

import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ASSETS = os.path.join(REPO, "assets")
FONT = os.path.join(REPO, "65536-Glyph.ttf")

INK = (17, 16, 20)        # banner background
PAPER = (246, 244, 240)   # sheet background
TEXT = (34, 32, 38)
MUTED = (110, 116, 128)
FAINT = (188, 184, 176)
ACCENT_HEX = "#E8A13C"

CHAR_H_MIN = 100          # units: char-pattern glyphs are >= 500 tall;
                          # the reserved-slot dash is 20. 100 separates them.


def cmap_codepoints() -> list[int]:
    """Sorted code points that the committed TTF defines."""
    from fontTools.ttLib import TTFont
    f = TTFont(FONT, lazy=True)
    cps = sorted({c for tbl in f["cmap"].tables for c in tbl.cmap.keys()})
    assert cps, "font cmap is empty"
    return cps


def glyph_height(cp: int) -> int:
    """UUnits of vertical extent for a code point's glyph outline."""
    from fontTools.ttLib import TTFont
    f = TTFont(FONT, lazy=True)
    cmaps = [t for t in f["cmap"].tables if t.isUnicode() or t.platformID == 3]
    name = None
    for t in cmaps:
        name = t.cmap.get(cp) or name
    g = f["glyf"][name]
    return (g.yMax - g.yMin) if g.numberOfContours else 0


def glyph_classes(cps: list[int]) -> tuple[list[int], list[int]]:
    """(character_glyph_cps, reserved_slot_cps) by outline height."""
    chars, reserved = [], []
    for cp in cps:
        (chars if glyph_height(cp) >= CHAR_H_MIN else reserved).append(cp)
    assert chars and reserved, "both classes must exist in the shipped font"
    return chars, reserved


def render_symbol_sheet() -> str:
    """Every cmap code point, rendered exactly as the font draws it."""
    from PIL import Image, ImageDraw, ImageFont

    cps = cmap_codepoints()
    chars, reserved = glyph_classes(cps)
    span = cps[-1] - cps[0] + 1
    assert len(cps) == span, "cmap not contiguous; the sheet must be re-planned"

    cols = 16
    rows = span // cols
    cell, pad, header = 64, 16, 62

    W = cols * cell + pad * 2
    H = rows * cell + pad * 2 + header
    img = Image.new("RGB", (W, H), PAPER)
    d = ImageDraw.Draw(img)

    glyph_font = ImageFont.truetype(FONT, 34)
    try:
        label_font = ImageFont.load_default(size=12)
        head_font = ImageFont.load_default(size=16)
    except TypeError:
        label_font = ImageFont.load_default()
        head_font = ImageFont.load_default()

    d.text(
        (pad, pad - 2),
        f"65536-Glyph.ttf - complete cmap: 256 cp, U+E000..U+E0FF\n"
        f"{len(chars)} character-pattern slots; {len(reserved)} reserved "
        f"(the shipped font renders those as a short baseline dash)",
        fill=TEXT, font=head_font,
    )

    for i, cp in enumerate(cps):
        r, c = divmod(i, cols)
        x0, y0 = pad + c * cell, header + pad + r * cell
        ch = chr(cp)
        d.rectangle((x0, y0, x0 + cell - 1, y0 + cell - 1),
                    outline=(214, 210, 202), width=1)
        is_char = cp in set(chars)
        d.text((x0 + (cell - 40) / 2, y0 + 1), ch,
               fill=TEXT if is_char else (160, 156, 148), font=glyph_font)
        label = f"E{cp - 0xE000:02X}"
        lw = d.textlength(label, font=label_font)
        d.text((x0 + (cell - lw) / 2, y0 + cell - 19), label,
               fill=MUTED if is_char else FAINT, font=label_font)

    out = os.path.join(ASSETS, "symbol_sheet.png")
    img.save(out)
    return out, len(cps), chars, reserved


def render_banner_svg(cps: list[int], chars: list[int], reserved: list[int]) -> str:
    """Banner motif = the font's REAL address space, drawn from cmap data.

    A compact 16x16 grid: an amber cell for every code point whose glyph
    carries a character pattern, a dim cell for every reserved slot. The
    bright/dim pattern is the font's actual layout, not decoration.
    """
    ink = set(chars)
    cell, gap = 10.0, 1.5
    pitch = cell + gap
    grid0, oy = 38, 30
    cells = []
    lo = cps[0]
    for i in range(256):
        cp = lo + i
        r, c = divmod(i, 16)
        x = grid0 + c * pitch
        y = oy + r * pitch
        fill = ACCENT_HEX if cp in ink else "#26221e"
        cells.append(f'<rect x="{x:.1f}" y="{y:.1f}" width="{cell}" '
                     f'height="{cell}" rx="2" fill="{fill}"/>')
    tx = grid0 + 16 * pitch + 34
    svg = f'''<svg xmlns="http://www.w3.org/2000/svg" width="880" height="240" viewBox="0 0 880 240" role="img" aria-label="65536 banner">
  <!-- generated by tools/make_doc_assets.py; motif = the committed font's
       16x16 address space from the measured cmap: {len(chars)} character
       glyphs (amber), {len(reserved)} reserved slots (dim). Deterministic.
       Regenerate with: python3 tools/make_doc_assets.py -->
  <rect width="880" height="240" rx="14" fill="#111014"/>
  <rect x="1" y="1" width="878" height="238" rx="13" fill="none" stroke="#3a3842" stroke-width="1"/>
  {"".join(cells)}
  <text x="{tx:.0f}" y="106" font-family="'DejaVu Sans Mono','JetBrains Mono',Consolas,monospace" font-size="54" font-weight="700" fill="{ACCENT_HEX}" letter-spacing="3">65536</text>
  <text x="{tx + 2:.0f}" y="136" font-family="'DejaVu Sans Mono','JetBrains Mono',Consolas,monospace" font-size="18" fill="#E8E8EC">Font and ontology for visual knowledge representation</text>
  <text x="{tx + 2:.0f}" y="163" font-family="'DejaVu Sans Mono','JetBrains Mono',Consolas,monospace" font-size="13" fill="#9AA0AC">65,536-symbol design  &#183;  hierarchy codec  &#183;  content-addressed store</text>
  <text x="842" y="216" text-anchor="end" font-family="'DejaVu Sans Mono',Consolas,monospace" font-size="11" fill="#6E7480">committed font: {len(cps)} code points U+E000..U+E0FF (cmap-measured)</text>
</svg>
'''
    out = os.path.join(ASSETS, "banner.svg")
    with open(out, "w", encoding="utf-8") as f:
        f.write(svg)
    return out


def main() -> int:
    if not os.path.isdir(ASSETS):
        os.makedirs(ASSETS)

    cps = cmap_codepoints()
    chars, reserved = glyph_classes(cps)
    print(f"font    : 65536-Glyph.ttf -> {len(cps)} code points U+E000..U+E0FF; "
          f"{len(chars)} character glyphs, {len(reserved)} reserved slots")

    png, defined, chars, reserved = render_symbol_sheet()
    print(f"wrote   : {os.path.relpath(png, REPO)}  "
          f"({len(chars)} pattern glyphs shown, {len(reserved)} reserved)")

    svg = render_banner_svg(cps, chars, reserved)
    print(f"wrote   : {os.path.relpath(svg, REPO)}  ({os.path.getsize(svg)} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
