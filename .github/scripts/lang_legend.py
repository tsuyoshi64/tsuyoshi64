#!/usr/bin/env python3
"""
.github/scripts/lang_legend.py
────────────────────────────────
Queries the GitHub GraphQL API for the byte-weighted language breakdown
across all of the user's non-fork repositories, then renders a static SVG
legend: one row per language with a colored dot (GitHub's real per-language
color, not a theme color), the language name, and its percentage share —
deliberately NO progress bar, since the existing top-langs pie chart in the
README already conveys proportion visually and a second bar is redundant.

Styled to match the hand-built cards in .svg/ (info.svg, my-plan.svg,
skill-tree.svg): JetBrains Mono text, #0D1117 background, neon gradient
border (#00F5FF -> #BF00FF -> #FF00FF), #2D333B divider/panel color.

Required environment variables:
  GITHUB_TOKEN             - same default Actions token used by
                             fetch_contrib_total.py; sufficient for reading
                             a user's own public repo languages via GraphQL.
  GITHUB_REPOSITORY_OWNER  - the username to query (set automatically by
                             GitHub Actions; falls back to USER_LOGIN).

Output: dist/top-langs.svg
"""
from __future__ import annotations

import json
import os
import sys
import urllib.request

OUTPUT = "dist/top-langs.svg"

# Excludes forks (isFork: false) so the breakdown reflects the user's own
# written code, matching github-readme-stats' default behavior. Paginates
# up to 100 repos (GraphQL max per page) ordered by most recently pushed —
# matches the "first 100 repos" limitation github-readme-stats itself has,
# so results stay comparable to the existing pie chart in the README.
QUERY = """
query($login: String!, $cursor: String) {
  user(login: $login) {
    repositories(first: 100, after: $cursor, isFork: false, ownerAffiliations: OWNER) {
      pageInfo { hasNextPage endCursor }
      nodes {
        languages(first: 10, orderBy: {field: SIZE, direction: DESC}) {
          edges {
            size
            node { name color }
          }
        }
      }
    }
  }
}
"""

# House style, lifted directly from .svg/info.svg rather than reinvented.
BG = "#0D1117"
PANEL = "#161B22"
DIVIDER = "#2D333B"
TEXT_MAIN = "#c9d1d9"
TEXT_BOLD = "#ffffff"
FONT_STACK = "'JetBrains Mono', Consolas, 'Fira Code', monospace"

# Matches border_color=bf00ff used by the github-readme-stats cards
# directly above this one in the README (GitHub Stats, Streak Stats), so
# this hand-built card visually belongs to the same row instead of standing
# out with its own gradient treatment.
BORDER_COLOR = "#bf00ff"

CARD_W = 710
ROW_H = 64  # was 34; +10px gives the new per-row bar room without crowding the next row
HEADER_H = 56
PAD_X = 24
PAD_TOP = 18
PAD_BOTTOM = 18
MAX_LANGS = 8  # keep the card a readable height; smallest languages folded into "Other"


def fetch_language_bytes(token: str, login: str) -> dict[str, dict]:
    """Returns {language_name: {"bytes": int, "color": str|None}}."""
    totals: dict[str, dict] = {}
    cursor = None

    while True:
        payload = json.dumps(
            {"query": QUERY, "variables": {"login": login, "cursor": cursor}}
        ).encode("utf-8")
        req = urllib.request.Request(
            "https://api.github.com/graphql",
            data=payload,
            headers={
                "Authorization": f"bearer {token}",
                "Content-Type": "application/json",
                "User-Agent": "lang-legend-workflow",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                body = json.loads(resp.read().decode("utf-8"))
        except Exception as e:
            sys.exit(f"X GraphQL request failed: {e}")

        if "errors" in body:
            sys.exit(f"X GraphQL returned errors: {body['errors']}")

        try:
            repos = body["data"]["user"]["repositories"]
        except (KeyError, TypeError):
            sys.exit(f"X Unexpected GraphQL response shape: {body}")

        for repo in repos["nodes"]:
            for edge in repo["languages"]["edges"]:
                name = edge["node"]["name"]
                color = edge["node"]["color"]
                size = edge["size"]
                entry = totals.setdefault(name, {"bytes": 0, "color": color})
                entry["bytes"] += size
                if entry["color"] is None and color is not None:
                    entry["color"] = color

        page_info = repos["pageInfo"]
        if not page_info["hasNextPage"]:
            break
        cursor = page_info["endCursor"]

    return totals


def compute_percentages(totals: dict[str, dict]) -> list[tuple[str, float, str]]:
    """
    Returns sorted [(name, pct, color), ...] descending by pct, capped at
    MAX_LANGS rows with any remainder folded into an "Other" row (gray dot)
    rather than silently dropped — dropping data without accounting for it
    would make the percentages not sum to ~100%, which is misleading.
    """
    grand_total = sum(e["bytes"] for e in totals.values())
    if grand_total == 0:
        sys.exit("X No language bytes found across repositories — nothing to render.")

    ranked = sorted(totals.items(), key=lambda kv: kv[1]["bytes"], reverse=True)
    rows: list[tuple[str, float, str]] = []
    shown_bytes = 0

    for name, entry in ranked[:MAX_LANGS]:
        pct = (entry["bytes"] / grand_total) * 100
        color = entry["color"] or "#8b949e"  # GitHub's fallback gray for colorless languages
        rows.append((name, pct, color))
        shown_bytes += entry["bytes"]

    if len(ranked) > MAX_LANGS:
        remainder_bytes = grand_total - shown_bytes
        remainder_pct = (remainder_bytes / grand_total) * 100
        if remainder_pct > 0.005:  # avoid a 0.0% "Other" row from float rounding
            rows.append(("Other", remainder_pct, "#8b949e"))

    return rows


def render_svg(rows: list[tuple[str, float, str]]) -> str:
    card_h = PAD_TOP + len(rows) * ROW_H + PAD_BOTTOM

    # Slim proportional tick-bar per row (distinct from the old compact-card
    # bar that was removed for being redundant with the pie chart): the pie
    # shows relative share at a glance, this shows each language's absolute
    # scale at a glance, sitting quietly under the name/dot rather than
    # competing with them for attention. Track length matches the dot+name
    # column width (CARD_W - PAD_X*2 - 60, leaving room for the % text).
    bar_max_w = CARD_W - (PAD_X * 2) - 60
    bar_h = 4
    max_pct = max(pct for _, pct, _ in rows) if rows else 1.0

    body_rows = []
    y = PAD_TOP
    for name, pct, color in rows:
        dot_cy = y + ROW_H / 2 - 10
        text_y = y + ROW_H / 2 - 5
        bar_y = y + ROW_H / 2 + 8
        bar_w = max((pct / max_pct) * bar_max_w, 3)  # floor so trace languages stay visible
        body_rows.append(
            f'  <circle cx="{PAD_X + 6}" cy="{dot_cy:.1f}" r="6" fill="{color}"/>\n'
            f'  <text x="{PAD_X + 22}" y="{text_y:.1f}" class="lang-name">{name}</text>\n'
            f'  <text x="{CARD_W - PAD_X}" y="{text_y:.1f}" text-anchor="end" class="lang-pct">{pct:.2f}%</text>\n'
            f'  <rect x="{PAD_X}" y="{bar_y:.1f}" width="{bar_max_w:.1f}" height="{bar_h}" rx="2" fill="{DIVIDER}"/>\n'
            f'  <rect x="{PAD_X}" y="{bar_y:.1f}" width="{bar_w:.1f}" height="{bar_h}" rx="2" fill="{color}"/>'
        )
        y += ROW_H

    return f'''<svg width="{CARD_W}" height="{card_h:.0f}" viewBox="0 0 {CARD_W} {card_h:.0f}" fill="none" xmlns="http://www.w3.org/2000/svg">
  <style>
    .lang-name  {{ font-family: {FONT_STACK}; font-size: 13px; fill: {TEXT_MAIN}; }}
    .lang-pct   {{ font-family: {FONT_STACK}; font-weight: bold; font-size: 13px; fill: {TEXT_BOLD}; }}
  </style>

  <!-- Flat solid border (BORDER_COLOR), matching the surrounding
       github-readme-stats cards' border_color=bf00ff param exactly —
       NOT a gradient, so this card visually belongs to the same row as
       the GitHub Stats / Streak cards above it. rx=4.5 and stroke-width=1
       are the ACTUAL defaults read from github-readme-stats' own source
       (src/common/Card.js: border_radius defaults to 4.5, and the border
       <rect> sets no stroke-width attribute at all, which means it falls
       back to the SVG default of 1 — not the rx=14/stroke-width=2 guessed
       here previously). Header band, divider, and title were removed on
       request — card now starts directly at the language rows. -->
  <rect x="2" y="2" width="{CARD_W - 4}" height="{card_h - 4:.0f}" rx="4.5" stroke="{BORDER_COLOR}" stroke-width="1"/>
  <rect x="3" y="3" width="{CARD_W - 6}" height="{card_h - 6:.0f}" rx="3.5" fill="{BG}"/>

{chr(10).join(body_rows)}
</svg>
'''


def main() -> None:
    token = os.environ.get("GITHUB_TOKEN")
    login = os.environ.get("GITHUB_REPOSITORY_OWNER") or os.environ.get("USER_LOGIN")

    if not token:
        sys.exit("X GITHUB_TOKEN environment variable is required.")
    if not login:
        sys.exit("X GITHUB_REPOSITORY_OWNER (or USER_LOGIN) environment variable is required.")

    totals = fetch_language_bytes(token, login)
    rows = compute_percentages(totals)
    svg = render_svg(rows)

    os.makedirs(os.path.dirname(OUTPUT), exist_ok=True)
    with open(OUTPUT, "w", encoding="utf-8") as f:
        f.write(svg)

    print(f"OK wrote {OUTPUT} ({len(rows)} language rows)")


if __name__ == "__main__":
    main()
