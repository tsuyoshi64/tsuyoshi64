#!/usr/bin/env python3
"""
.github/scripts/enhance_snake.py
─────────────────────────────────
Post-processes the raw snk SVG with a neon-cyberpunk treatment AND adds
real calendar chrome that snk does not generate natively:

  · Month labels along the top (computed from real calendar dates)
  · Day-of-week labels down the left (Mon / Wed / Fri, GitHub-style sparse)
  · A "Less -> More" legend with the 5 dot colors
  · A "X contributions in the last year" total, fetched via GraphQL in a
    separate workflow step and written to dist/contrib-total.txt, which
    this script reads (see snake.yml)

Effects injected (deliberately minimal — contrast does the work, not noise):
  · Per-level neon glow on contribution dots, L2-L4 only (L1 and L0 are silent)
  · Glow on snake head (fill) AND snake body path (stroke)
  · Breathing pulse animation on L4 cells only
  · Subtle dot-grid texture (15% opacity) behind the contribution grid
  · Month / day / legend / total-count text in neon-themed monospace

How cell geometry is determined (IMPORTANT — do not hardcode pixel constants):
  snk's internal cell size/spacing is not part of its public API and could
  change across versions. Instead of guessing fixed numbers, this script
  empirically derives cell width, height, and grid origin by reading the
  actual <rect> elements snk emitted for the contribution dots (matched by
  their fill="{L0..L4}" attribute). Week-column x positions and weekday-row
  y positions are recovered from the real rects, so labels always line up
  with whatever snk actually rendered.

  GitHub's contribution calendar is always 7 rows (Sun..Sat) by however many
  week-columns fit the date range, oldest week first, ending with the week
  containing "today" (UTC). snk does not embed dates as text, so we rebuild
  the column -> date mapping using that convention.
"""
from __future__ import annotations

import datetime as dt
import re
import sys
from pathlib import Path

# ── File paths ──────────────────────────────────────────────────────────────────
INPUT      = Path("dist/snake-raw.svg")
OUTPUT     = Path("dist/github-contribution-grid-snake-dark.svg")
TOTAL_FILE = Path("dist/contrib-total.txt")  # written by the GraphQL step in snake.yml

# ── Neon palette — MUST exactly match color_dots= in snake.yml ─────────────────
BG    = "#0d1117"
L0    = "#161b22"
L1    = "#2d1b4e"
L2    = "#7b2fbe"
L3    = "#bf00ff"
L4    = "#ff00ff"
SNAKE = "#00f5ff"

LEVEL_COLORS = [L0, L1, L2, L3, L4]

# ── Label styling (neon-themed: brighter than GitHub default, monospace) ───────
LABEL_COLOR       = "#7dd8ff"
LABEL_FONT        = "ui-monospace, SFMono-Regular, 'SF Mono', Menlo, Consolas, monospace"
LABEL_FONT_SIZE   = 11
LEGEND_TEXT_COLOR = "#9bb4c9"

# ── Layout margins added around the original grid (px) ─────────────────────────
MARGIN_TOP    = 24
MARGIN_LEFT   = 28
MARGIN_BOTTOM = 50
MARGIN_RIGHT  = 4


def _glow(fid: str, color: str, blur: float, layers: int, opacity: float = 0.9) -> str:
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


def build_defs() -> str:
    return f"""<defs>
  <!-- Neon glow filters: L0/L1 have none — contrast does their work -->
{_glow("glow-l2", L2, 1.5, 1, opacity=0.65)}
{_glow("glow-l3", L3, 2.5, 2, opacity=0.75)}
{_glow("glow-l4", L4, 4.0, 3, opacity=0.90)}
{_glow("glow-snake", SNAKE, 5.0, 4, opacity=1.0)}
  <pattern id="dot-grid" x="0" y="0" width="14" height="14" patternUnits="userSpaceOnUse">
    <circle cx="7" cy="7" r="0.55" fill="#1e2d3d" opacity="0.8"/>
  </pattern>
</defs>"""


def build_css() -> str:
    return f"""
[fill="{L2}"] {{ filter: url(#glow-l2); }}
[fill="{L3}"] {{ filter: url(#glow-l3); }}
[fill="{L4}"] {{ filter: url(#glow-l4); animation: pulse-l4 2.4s ease-in-out infinite; }}
[fill="{SNAKE}"], [stroke="{SNAKE}"] {{ filter: url(#glow-snake); }}
@keyframes pulse-l4 {{ 0%, 100% {{ opacity: 1; }} 50% {{ opacity: 0.65; }} }}
.cal-label {{
  fill: {LABEL_COLOR};
  font-family: {LABEL_FONT};
  font-size: {LABEL_FONT_SIZE}px;
  letter-spacing: 0.04em;
}}
.cal-legend-text {{
  fill: {LEGEND_TEXT_COLOR};
  font-family: {LABEL_FONT};
  font-size: 10px;
  letter-spacing: 0.03em;
}}
.cal-total {{
  fill: {LABEL_COLOR};
  font-family: {LABEL_FONT};
  font-size: 12px;
  font-weight: 600;
  letter-spacing: 0.05em;
}}
"""


RECT_TAG_RE = re.compile(r'<rect\b([^>]*?)/?>')


def _attr(attrs: str, name: str) -> str | None:
    m = re.search(rf'\b{name}="([^"]*)"', attrs)
    return m.group(1) if m else None


def find_cells(svg: str) -> list[dict]:
    cells = []
    for m in RECT_TAG_RE.finditer(svg):
        attrs = m.group(1)
        fill = _attr(attrs, "fill")
        if fill not in LEVEL_COLORS:
            continue
        x, y, w, h = (_attr(attrs, k) for k in ("x", "y", "width", "height"))
        if None in (x, y, w, h):
            continue
        cells.append({"x": float(x), "y": float(y), "w": float(w), "h": float(h), "fill": fill})
    return cells


def derive_grid_geometry(cells: list[dict]) -> dict:
    if not cells:
        raise ValueError("No contribution cells found in raw SVG — snk output format may have changed.")
    cell_w = min(c["w"] for c in cells)
    cell_h = min(c["h"] for c in cells)
    col_xs = sorted(set(round(c["x"], 1) for c in cells))
    row_ys = sorted(set(round(c["y"], 1) for c in cells))
    return {
        "cell_w": cell_w, "cell_h": cell_h,
        "col_xs": col_xs, "row_ys": row_ys,
        "origin_x": col_xs[0], "origin_y": row_ys[0],
    }


def build_week_dates(num_weeks: int) -> list[dt.date]:
    today = dt.datetime.now(dt.timezone.utc).date()
    days_since_sunday = (today.weekday() + 1) % 7
    last_sunday = today - dt.timedelta(days=days_since_sunday)
    return [last_sunday - dt.timedelta(weeks=(num_weeks - 1 - i)) for i in range(num_weeks)]


MONTH_ABBR = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


def build_month_labels(geom: dict) -> list[tuple[float, str]]:
    col_xs = geom["col_xs"]
    week_dates = build_week_dates(len(col_xs))
    labels, last_month = [], None
    for x, wk_date in zip(col_xs, week_dates):
        if wk_date.month != last_month:
            labels.append((x, MONTH_ABBR[wk_date.month - 1]))
            last_month = wk_date.month
    return labels


DAY_LABELS = {1: "Mon", 3: "Wed", 5: "Fri"}


def build_day_labels(geom: dict) -> list[tuple[float, str]]:
    return [(y, DAY_LABELS[idx]) for idx, y in enumerate(geom["row_ys"]) if idx in DAY_LABELS]


def read_total_contributions() -> str | None:
    if TOTAL_FILE.exists():
        text = TOTAL_FILE.read_text(encoding="utf-8").strip()
        if text.isdigit():
            return f"{int(text):,} contributions in the last year"
    print(f"WARN: {TOTAL_FILE} missing or invalid — total-count line omitted.", file=sys.stderr)
    return None


def build_overlay_svg(geom: dict, margin_left: float, margin_top: float, total_line: str | None) -> str:
    parts = [f'<g transform="translate({margin_left},{margin_top})">']

    for x, label in build_month_labels(geom):
        parts.append(f'<text class="cal-label" x="{x - geom["origin_x"]:.1f}" y="-8">{label}</text>')

    for y, label in build_day_labels(geom):
        ty = (y - geom["origin_y"]) + geom["cell_h"] - 1
        parts.append(f'<text class="cal-label" x="-24" y="{ty:.1f}" text-anchor="start">{label}</text>')

    parts.append("</g>")

    # Total-contributions line and the Less->More legend are stacked on separate
    # rows (rather than packed onto one row) — estimating exact monospace text
    # width to avoid overlap is unreliable across renderers/fonts, so vertical
    # stacking sidesteps that fragility entirely.
    grid_bottom = margin_top + (geom["row_ys"][-1] - geom["origin_y"]) + geom["cell_h"]
    total_y = grid_bottom + 20
    legend_y = grid_bottom + 34
    legend_x = margin_left

    if total_line:
        parts.append(f'<text class="cal-total" x="{legend_x}" y="{total_y:.1f}">{total_line}</text>')

    swatch, gap = 10, 4
    parts.append(f'<g transform="translate({legend_x},{legend_y})">')
    lx = 0
    parts.append(f'<text class="cal-legend-text" x="{lx:.1f}" y="0">Less</text>')
    lx += 30
    for color in LEVEL_COLORS:
        parts.append(f'<rect x="{lx:.1f}" y="{-swatch + 2}" width="{swatch}" height="{swatch}" rx="2" fill="{color}"/>')
        lx += swatch + gap
    parts.append(f'<text class="cal-legend-text" x="{lx + 2:.1f}" y="0">More</text>')
    parts.append("</g>")

    return "\n".join(parts)


def transform(raw: str) -> str:
    vb = re.search(r'viewBox="[0-9.]+ [0-9.]+ ([0-9.]+) ([0-9.]+)"', raw)
    if vb:
        orig_w, orig_h = float(vb.group(1)), float(vb.group(2))
    else:
        mw = re.search(r'<svg\b[^>]+\bwidth="([0-9.]+)"', raw)
        mh = re.search(r'<svg\b[^>]+\bheight="([0-9.]+)"', raw)
        orig_w = float(mw.group(1)) if mw else 870.0
        orig_h = float(mh.group(1)) if mh else 128.0

    cells = find_cells(raw)
    geom = derive_grid_geometry(cells)

    new_w = orig_w + MARGIN_LEFT + MARGIN_RIGHT
    new_h = orig_h + MARGIN_TOP + MARGIN_BOTTOM

    out = raw
    replaced_bg = False
    bg_block = ""

    def patch_bg(m: re.Match) -> str:
        nonlocal replaced_bg, bg_block
        if replaced_bg:
            return m.group(0)
        replaced_bg = True
        darkened = re.sub(r'\bfill="[^"]*"', f'fill="{BG}"', m.group(0), count=1)
        darkened = re.sub(r'\bwidth="[0-9.]+"', f'width="{new_w:.0f}"', darkened, count=1)
        darkened = re.sub(r'\bheight="[0-9.]+"', f'height="{new_h:.0f}"', darkened, count=1)
        darkened = re.sub(r'\bx="[0-9.]+"', 'x="0"', darkened) if 'x=' in darkened else darkened
        darkened = re.sub(r'\by="[0-9.]+"', 'y="0"', darkened) if 'y=' in darkened else darkened
        texture = (
            f'\n<rect width="{new_w:.0f}" height="{new_h:.0f}" '
            f'fill="url(#dot-grid)" opacity="0.15" pointer-events="none"/>'
        )
        # Stash the background block to be re-inserted OUTSIDE the margin-shift
        # group (it must cover the full new canvas at absolute 0,0 — not be
        # shifted down/right with the rest of snk's original content).
        bg_block = darkened + texture
        return ""  # remove from its original position; we re-insert it below

    out = re.sub(r'<rect\b[^>]*/>', patch_bg, out, count=1)
    if not replaced_bg:
        print("WARN: background rect not found — SVG structure may have changed.", file=sys.stderr)

    # Insert: <svg> -> __DEFS__ -> background (absolute, full new canvas) ->
    #         <g translate(margin)> (everything else snk drew, shifted into place)
    out = re.sub(
        r'(<svg\b[^>]*>)',
        rf'\1\n__DEFS__\n{bg_block}\n<g transform="translate({MARGIN_LEFT},{MARGIN_TOP})">\n',
        out,
        count=1,
    )
    out = out.rstrip()
    assert out.endswith("</svg>"), "Expected SVG to end with </svg> — structure unexpected."
    out = out[: -len("</svg>")]
    out += "\n</g>\n__OVERLAY__\n</svg>\n"

    out = re.sub(r'(<svg\b[^>]*?)\swidth="[0-9.]+"', rf'\1 width="{new_w:.0f}"', out, count=1)
    out = re.sub(r'(<svg\b[^>]*?)\sheight="[0-9.]+"', rf'\1 height="{new_h:.0f}"', out, count=1)
    out = re.sub(
        r'viewBox="[0-9.]+ [0-9.]+ [0-9.]+ [0-9.]+"',
        f'viewBox="0 0 {new_w:.0f} {new_h:.0f}"',
        out,
        count=1,
    )

    out = out.replace("__DEFS__", build_defs(), 1)

    if re.search(r'<style\b', out):
        out = re.sub(r'(<style\b[^>]*>)', rf'\1\n{build_css()}', out, count=1)
    else:
        out = out.replace("</defs>", f'</defs>\n<style type="text/css">\n{build_css()}\n</style>', 1)

    total_line = read_total_contributions()
    overlay = build_overlay_svg(geom, MARGIN_LEFT, MARGIN_TOP, total_line)
    out = out.replace("__OVERLAY__", overlay, 1)

    return out


def main() -> None:
    if not INPUT.exists():
        sys.exit(f"X {INPUT} not found — did the snk step succeed?")
    raw = INPUT.read_text(encoding="utf-8")
    try:
        result = transform(raw)
    except ValueError as e:
        sys.exit(f"X {e}")
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(result, encoding="utf-8")
    print(f"OK {OUTPUT} ({len(result):,} bytes)")
    INPUT.unlink(missing_ok=True)
    print(f"OK removed {INPUT}")


if __name__ == "__main__":
    main()
