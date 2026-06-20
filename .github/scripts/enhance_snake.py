#!/usr/bin/env python3
"""
.github/scripts/enhance_snake.py
─────────────────────────────────
Post-processes the raw snk SVG to apply a full neon-cyberpunk treatment.

Effects injected:
  · Per-level neon glow on contribution dots (feGaussianBlur bloom)
  · Electric-cyan bloom on the snake body
  · Breathing pulse animation on L3 and L4 cells
  · Cyberpunk dot-grid texture behind the contribution grid
  · CRT scanline overlay (subtle, 0.07 opacity)
  · Neon gradient border frame with slow breathing animation
  · Month / day labels re-styled in a purple-tinted muted tone

The script reads  dist/snake-raw.svg,
writes            dist/github-contribution-grid-snake-dark.svg,
then deletes      dist/snake-raw.svg so only the final file is deployed.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

# File paths 
INPUT  = Path("dist/snake-raw.svg")
OUTPUT = Path("dist/github-contribution-grid-snake-dark.svg")

# Neon palette — MUST exactly match color_dots= in snake.yml 
BG    = "#0d1117"   # background  — GitHub dark-mode base
L0    = "#161b22"   # level 0     — empty, near-black
L1    = "#2d1b4e"   # level 1     — deep purple      (1–3 contributions)
L2    = "#6929c4"   # level 2     — electric violet  (4–6)
L3    = "#bf00ff"   # level 3     — bright magenta   (7–9)
L4    = "#ff00ff"   # level 4     — hot-pink neon    (10+)
SNAKE = "#00f5ff"   # snake       — electric cyan


# Helper: build a feGaussianBlur neon-glow SVG filter 
def _glow(fid: str, color: str, blur: float, layers: int) -> str:
    """
    Produces a <filter> that:
      1. Blurs the source graphic
      2. Flood-fills the blur with `color`
      3. Merges `layers` copies of the colored blur under the original
    Result: the element glows with `color` at radius `blur`.
    """
    merge_nodes = "\n        ".join(
        ['<feMergeNode in="colored-blur"/>'] * layers
        + ['<feMergeNode in="SourceGraphic"/>']
    )
    return (
        f'  <filter id="{fid}" x="-120%" y="-120%" width="340%" height="340%"\n'
        f'          color-interpolation-filters="sRGB">\n'
        f'    <feGaussianBlur in="SourceGraphic" stdDeviation="{blur}" result="blur"/>\n'
        f'    <feFlood flood-color="{color}" flood-opacity="0.9" result="flood"/>\n'
        f'    <feComposite in="flood" in2="blur" operator="in" result="colored-blur"/>\n'
        f'    <feMerge>\n'
        f'        {merge_nodes}\n'
        f'    </feMerge>\n'
        f'  </filter>'
    )


# <defs> block injected after the root <svg> tag 
DEFS = f"""\
<defs>
  <!-- ── Neon glow filters: intensity scales with contribution level ── -->
{_glow("glow-l1", L1, 1.5, 1)}
{_glow("glow-l2", L2, 2.5, 2)}
{_glow("glow-l3", L3, 3.5, 3)}
{_glow("glow-l4", L4, 5.0, 4)}
{_glow("glow-snake", SNAKE, 6.0, 5)}

  <!-- ── Cyberpunk dot-grid background texture ── -->
  <pattern id="dot-grid" x="0" y="0" width="14" height="14"
           patternUnits="userSpaceOnUse">
    <circle cx="7" cy="7" r="0.65" fill="#1e2d3d" opacity="0.65"/>
  </pattern>

  <!-- ── CRT scanlines ── -->
  <pattern id="scanlines" x="0" y="0" width="1" height="3"
           patternUnits="userSpaceOnUse">
    <rect width="1" height="1" fill="black" opacity="0.07"/>
  </pattern>

  <!-- ── Neon gradient for border frame ── -->
  <linearGradient id="neon-border-grad" x1="0%" y1="0%" x2="100%" y2="0%">
    <stop offset="0%"   stop-color="{L4}"    stop-opacity="0.85"/>
    <stop offset="40%"  stop-color="#bf00ff" stop-opacity="0.85"/>
    <stop offset="100%" stop-color="{SNAKE}" stop-opacity="0.85"/>
  </linearGradient>
</defs>"""


# ── CSS injected at the top of the SVG's <style> block ───────────────────────
# Uses SVG attribute selectors — no JS, works as <img> in GitHub README.
CSS = f"""\
/* ── Neon glow per contribution level (attribute selectors) ── */
[fill="{L1}"] {{ filter: url(#glow-l1); }}
[fill="{L2}"] {{ filter: url(#glow-l2); }}
[fill="{L3}"] {{ filter: url(#glow-l3); animation: pulse-l3 3s ease-in-out infinite; }}
[fill="{L4}"] {{ filter: url(#glow-l4); animation: pulse-l4 2.4s ease-in-out infinite; }}
[fill="{SNAKE}"] {{ filter: url(#glow-snake); }}

/* ── Breathing pulse on high-intensity cells ── */
@keyframes pulse-l3 {{
  0%, 100% {{ opacity: 1;    }}
  50%      {{ opacity: 0.82; }}
}}
@keyframes pulse-l4 {{
  0%, 100% {{ opacity: 1;   }}
  50%      {{ opacity: 0.68; }}
}}

/* ── Animated neon border ── */
@keyframes border-breath {{
  0%, 100% {{ stroke-opacity: 0.8;  }}
  50%      {{ stroke-opacity: 0.28; }}
}}
.neon-frame {{ animation: border-breath 4s ease-in-out infinite; }}

/* ── Month / day label re-style ── */
text {{
  fill: #3d4b60;
  font-family: ui-monospace, SFMono-Regular, "SF Mono", Menlo, Consolas, monospace;
  font-size: 10px;
  letter-spacing: 0.05em;
}}
"""


#  SVG transformation 
def transform(raw: str) -> str:
    # 1. Resolve canvas dimensions (viewBox is more reliable than w/h attrs)
    vb = re.search(r'viewBox="[0-9.]+ [0-9.]+ ([0-9.]+) ([0-9.]+)"', raw)
    if vb:
        W, H = float(vb.group(1)), float(vb.group(2))
    else:
        mw = re.search(r'<svg\b[^>]+\bwidth="([0-9.]+)"', raw)
        mh = re.search(r'<svg\b[^>]+\bheight="([0-9.]+)"', raw)
        W = float(mw.group(1)) if mw else 870.0
        H = float(mh.group(1)) if mh else 128.0

    out = raw

    # 2. Darken the background rect + inject dot-grid texture right behind dots.
    #    IMPORTANT: must run on the raw SVG *before* we inject <defs>, because
    #    the defs block itself contains a <rect> (scanline pattern) that would
    #    otherwise be matched first and consume the `replaced_bg` flag early.
    replaced_bg = False

    def patch_bg(m: re.Match) -> str:
        nonlocal replaced_bg
        if replaced_bg:
            return m.group(0)
        replaced_bg = True
        darkened = re.sub(r'\bfill="[^"]*"', f'fill="{BG}"', m.group(0), count=1)
        texture = (
            f'\n<rect width="{W:.0f}" height="{H:.0f}" '
            f'fill="url(#dot-grid)" opacity="0.4" pointer-events="none"/>'
        )
        return darkened + texture

    out = re.sub(r'<rect\b[^>]*/>', patch_bg, out)

    if not replaced_bg:
        print(
            "WARN: background rect not found — SVG structure may have changed.",
            file=sys.stderr,
        )

    # 3. Inject <defs> immediately after the opening <svg …> tag
    out = re.sub(r'(<svg\b[^>]*>)', rf'\1\n{DEFS}\n', out, count=1)

    # 4. Prepend neon CSS to the existing <style> block
    #    (snk always outputs one; fallback creates one after </defs>)
    if re.search(r'<style\b', out):
        out = re.sub(r'(<style\b[^>]*>)', rf'\1\n{CSS}', out, count=1)
    else:
        out = out.replace(
            '</defs>',
            f'</defs>\n<style type="text/css">\n{CSS}\n</style>',
            1,
        )

    # 5. Append scanlines + animated neon border before </svg>
    overlays = (
        f'\n<!-- ── CRT scanline overlay ── -->'
        f'\n<rect width="{W:.0f}" height="{H:.0f}" '
        f'fill="url(#scanlines)" pointer-events="none"/>'
        f'\n<!-- ── Animated neon border frame ── -->'
        f'\n<rect x="0.75" y="0.75"'
        f' width="{W - 1.5:.1f}" height="{H - 1.5:.1f}"'
        f' rx="4" ry="4" fill="none"'
        f' stroke="url(#neon-border-grad)" stroke-width="1.5"'
        f' class="neon-frame" pointer-events="none"/>'
        f'\n'
    )
    out = out.replace('</svg>', overlays + '</svg>', 1)

    return out


def main() -> None:
    if not INPUT.exists():
        sys.exit(f"✗  {INPUT} not found — did the snk step succeed?")

    raw = INPUT.read_text(encoding="utf-8")
    result = transform(raw)

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(result, encoding="utf-8")
    print(f"✓  {OUTPUT}  ({len(result):,} bytes)")

    # Remove intermediate raw file — only the enhanced SVG goes to the output branch
    INPUT.unlink(missing_ok=True)
    print(f"✓  Removed {INPUT}")


if __name__ == "__main__":
    main()
