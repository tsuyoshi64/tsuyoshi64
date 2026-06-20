#!/usr/bin/env python3
"""
.github/scripts/enhance_snake.py
─────────────────────────────────
Post-processes the raw snk SVG with a focused neon-cyberpunk treatment.

Effects injected (deliberately minimal — contrast does the work, not noise):
  · Per-level neon glow on contribution dots, L2–L4 only (L1 and L0 are silent)
  · Glow on snake head (fill) AND snake body path (stroke)
  · Breathing pulse animation on L4 cells only
  · Subtle dot-grid texture (15% opacity) behind the contribution grid
  · Month / day labels re-styled to GitHub's muted-text color (#8b949e)

Removed vs v1: animated border, CRT scanlines, glow on L0/L1, pulse on L3.

The script reads  dist/snake-raw.svg,
writes            dist/github-contribution-grid-snake-dark.svg,
then deletes      dist/snake-raw.svg so only the final file is deployed.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

# ── File paths ──────────────────────────────────────────────────────────────────
INPUT  = Path("dist/snake-raw.svg")
OUTPUT = Path("dist/github-contribution-grid-snake-dark.svg")

# ── Neon palette — MUST exactly match color_dots= in snake.yml ─────────────────
BG    = "#0d1117"   # background — GitHub dark-mode base
L0    = "#161b22"   # level 0   — empty, near-black        | no glow
L1    = "#2d1b4e"   # level 1   — deep purple (1–3 days)   | no glow
L2    = "#7b2fbe"   # level 2   — bright violet (4–6 days) | subtle glow
L3    = "#bf00ff"   # level 3   — magenta (7–9 days)       | glow
L4    = "#ff00ff"   # level 4   — hot-pink neon (10+ days) | glow + pulse
SNAKE = "#00f5ff"   # snake     — electric cyan             | max glow


# ── Helper: build a feGaussianBlur neon-glow SVG filter ────────────────────────
def _glow(fid: str, color: str, blur: float, layers: int, opacity: float = 0.9) -> str:
    """
    Returns a <filter> element that wraps the element in a colored bloom:
      1. Blur SourceGraphic by `blur` pixels
      2. Flood-fill with `color` at `opacity`
      3. Clip flood to blurred shape (feComposite operator="in")
      4. Merge `layers` copies of colored blur under the original graphic
    Increasing layers → wider, more saturated bloom.
    """
    merge_nodes = "\n        ".join(
        ['<feMergeNode in="colored-blur"/>'] * layers
        + ['<feMergeNode in="SourceGraphic"/>']
    )
    return (
        f'  <filter id="{fid}" x="-120%" y="-120%" width="340%" height="340%"\n'
        f'          color-interpolation-filters="sRGB">\n'
        f'    <feGaussianBlur in="SourceGraphic" stdDeviation="{blur}" result="blur"/>\n'
        f'    <feFlood flood-color="{color}" flood-opacity="{opacity}" result="flood"/>\n'
        f'    <feComposite in="flood" in2="blur" operator="in" result="colored-blur"/>\n'
        f'    <feMerge>\n'
        f'        {merge_nodes}\n'
        f'    </feMerge>\n'
        f'  </filter>'
    )


# ── <defs> block injected after the root <svg> tag ─────────────────────────────
DEFS = f"""\
<defs>
  <!-- ── Neon glow filters: L0/L1 have none — contrast does their work ── -->
{_glow("glow-l2", L2, 1.5, 1, opacity=0.65)}
{_glow("glow-l3", L3, 2.5, 2, opacity=0.75)}
{_glow("glow-l4", L4, 4.0, 3, opacity=0.90)}
{_glow("glow-snake", SNAKE, 5.0, 4, opacity=1.0)}

  <!-- ── Subtle dot-grid background texture (15% opacity — texture, not noise) ── -->
  <pattern id="dot-grid" x="0" y="0" width="14" height="14"
           patternUnits="userSpaceOnUse">
    <circle cx="7" cy="7" r="0.55" fill="#1e2d3d" opacity="0.8"/>
  </pattern>
</defs>"""


# ── CSS injected at the top of the SVG's <style> block ─────────────────────────
# Attribute selectors work inside a GitHub README <img> tag with no JS needed.
# Two snake selectors are needed:
#   [fill=SNAKE]   — matches the snake head rect (fill attribute)
#   [stroke=SNAKE] — matches the snake body <path> (stroke attribute, fill="none")
CSS = f"""\
/* ── Neon glow: L2 subtle, L3 present, L4 strong — L0/L1 untouched ── */
[fill="{L2}"] {{ filter: url(#glow-l2); }}
[fill="{L3}"] {{ filter: url(#glow-l3); }}
[fill="{L4}"] {{ filter: url(#glow-l4); animation: pulse-l4 2.4s ease-in-out infinite; }}

/* ── Snake: target both head (fill) and body path (stroke) ── */
[fill="{SNAKE}"],
[stroke="{SNAKE}"] {{ filter: url(#glow-snake); }}

/* ── L4 breathing pulse: active, not frantic ── */
@keyframes pulse-l4 {{
  0%, 100% {{ opacity: 1;    }}
  50%      {{ opacity: 0.65; }}
}}

/* ── Month / day labels: GitHub's own muted-text tone ── */
text {{
  fill: #8b949e;
  font-family: ui-monospace, SFMono-Regular, "SF Mono", Menlo, Consolas, monospace;
  font-size: 10px;
  letter-spacing: 0.04em;
}}
"""


# ── Core SVG transformation ─────────────────────────────────────────────────────
def transform(raw: str) -> str:
    # 1. Resolve canvas dimensions — viewBox is more reliable than width/height attrs
    vb = re.search(r'viewBox="[0-9.]+ [0-9.]+ ([0-9.]+) ([0-9.]+)"', raw)
    if vb:
        W, H = float(vb.group(1)), float(vb.group(2))
    else:
        mw = re.search(r'<svg\b[^>]+\bwidth="([0-9.]+)"', raw)
        mh = re.search(r'<svg\b[^>]+\bheight="([0-9.]+)"', raw)
        W = float(mw.group(1)) if mw else 870.0
        H = float(mh.group(1)) if mh else 128.0

    out = raw

    # 2. Patch the background rect and inject the dot-grid texture rect behind it.
    #    CRITICAL ORDER: run on raw SVG *before* injecting <defs>, because the
    #    <defs> block also contains <rect> elements (pattern tiles) that would
    #    trigger the first-rect match and set replaced_bg=True prematurely.
    replaced_bg = False

    def patch_bg(m: re.Match) -> str:
        nonlocal replaced_bg
        if replaced_bg:
            return m.group(0)
        replaced_bg = True
        darkened = re.sub(r'\bfill="[^"]*"', f'fill="{BG}"', m.group(0), count=1)
        # Dot-grid at 15% — adds texture without competing with the glow effects
        texture = (
            f'\n<rect width="{W:.0f}" height="{H:.0f}" '
            f'fill="url(#dot-grid)" opacity="0.15" pointer-events="none"/>'
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

    # 4. Prepend neon CSS into the existing <style> block
    #    (snk always emits a <style> block; fallback path handles edge cases)
    if re.search(r'<style\b', out):
        out = re.sub(r'(<style\b[^>]*>)', rf'\1\n{CSS}', out, count=1)
    else:
        out = out.replace(
            '</defs>',
            f'</defs>\n<style type="text/css">\n{CSS}\n</style>',
            1,
        )

    return out


def main() -> None:
    if not INPUT.exists():
        sys.exit(f"✗  {INPUT} not found — did the snk step succeed?")

    raw = INPUT.read_text(encoding="utf-8")
    result = transform(raw)

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(result, encoding="utf-8")
    print(f"✓  {OUTPUT}  ({len(result):,} bytes)")

    # Remove the intermediate raw file — only the enhanced SVG goes to output branch
    INPUT.unlink(missing_ok=True)
    print(f"✓  Removed {INPUT}")


if __name__ == "__main__":
    main()
