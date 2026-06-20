#!/usr/bin/env python3
"""
.github/scripts/fetch_contrib_total.py
────────────────────────────────────────
Queries the GitHub GraphQL API for the authenticated user's real total
contribution count over the last year, and writes it as a bare integer to
dist/contrib-total.txt for enhance_snake.py to read.

snk (the snake-generator action) does not expose this number anywhere in
its output — it only emits colored grid cells bucketed into 5 levels — so
getting an exact total requires its own API call.

Required environment variables:
  GITHUB_TOKEN  - any token with read access to the user (the workflow's
                  default secrets.GITHUB_TOKEN is sufficient for the
                  authenticated user's own public contribution data)
  GITHUB_REPOSITORY_OWNER - the username to query (set automatically by
                  GitHub Actions; falls back to USER_LOGIN if provided)
"""
from __future__ import annotations

import json
import os
import sys
import urllib.request

OUTPUT = "dist/contrib-total.txt"

QUERY = """
query($login: String!) {
  user(login: $login) {
    contributionsCollection {
      contributionCalendar {
        totalContributions
      }
    }
  }
}
"""


def main() -> None:
    token = os.environ.get("GITHUB_TOKEN")
    login = os.environ.get("GITHUB_REPOSITORY_OWNER") or os.environ.get("USER_LOGIN")

    if not token:
        sys.exit("X GITHUB_TOKEN environment variable is required.")
    if not login:
        sys.exit("X GITHUB_REPOSITORY_OWNER (or USER_LOGIN) environment variable is required.")

    payload = json.dumps({"query": QUERY, "variables": {"login": login}}).encode("utf-8")

    req = urllib.request.Request(
        "https://api.github.com/graphql",
        data=payload,
        headers={
            "Authorization": f"bearer {token}",
            "Content-Type": "application/json",
            "User-Agent": "enhance-snake-workflow",
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
        total = (
            body["data"]["user"]["contributionsCollection"]
            ["contributionCalendar"]["totalContributions"]
        )
    except (KeyError, TypeError):
        sys.exit(f"X Unexpected GraphQL response shape: {body}")

    os.makedirs(os.path.dirname(OUTPUT), exist_ok=True)
    with open(OUTPUT, "w", encoding="utf-8") as f:
        f.write(str(total))

    print(f"OK wrote {OUTPUT}: {total}")


if __name__ == "__main__":
    main()
