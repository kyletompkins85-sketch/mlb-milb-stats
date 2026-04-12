#!/usr/bin/env python3
"""Minimal smoke test: hit the MLB Stats API and print a short summary."""

from __future__ import annotations

import json
import sys
import urllib.error
import urllib.request

BASE = "https://statsapi.mlb.com/api/v1"


def get_json(path: str, params: dict[str, str | int] | None = None) -> object:
    q = ""
    if params:
        from urllib.parse import urlencode

        q = "?" + urlencode(params)
    url = f"{BASE}{path}{q}"
    req = urllib.request.Request(url, headers={"User-Agent": "mlb-milb-stats-smoke/0.1"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode())


def main() -> int:
    sports = get_json("/sports")
    if not isinstance(sports, dict) or "sports" not in sports:
        print("Unexpected /sports shape", file=sys.stderr)
        return 1
    rows = sports["sports"]
    print(f"GET /sports — {len(rows)} sport rows (showing id, code, name)")
    for s in rows[:12]:
        print(f"  sportId={s.get('id')}\t{s.get('code')}\t{s.get('name')}")
    if len(rows) > 12:
        print(f"  ... and {len(rows) - 12} more")

    # Example: today's MLB schedule (no key required; date is optional for "today" behavior in some clients — here we omit for brevity or use schedule with sportId)
    sched = get_json("/schedule", {"sportId": 1, "date": "2026-04-01"})
    games = 0
    if isinstance(sched, dict) and "dates" in sched:
        for d in sched.get("dates") or []:
            games += len(d.get("games") or [])
    print(f"\nGET /schedule sportId=1 date=2026-04-01 — {games} game(s) listed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
