#!/usr/bin/env python3
"""
Genuine bulk MLBAM ID resolution for the Bowman checklist:

- Uses overrides first, then cache, then **Stats API `/draft/{year}`** when
  ``--draft-year`` is set (default 2025): one request loads every pick with
  ``person.id``, matched on **full name + drafting team** (affiliation on the checklist).
  Remaining names use **people/search** with **name variants** (commas, Jr./Sr., II/III/IV)
  — see `search_name_variants` in `mlb_id_resolver.py`.
- Optionally **merges newly found IDs** into `bowman_2025_mlbam_overrides.json`
  so they persist without relying only on cache.

Respectful delays between HTTP calls. Run with `--base-only` for 200 base names.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date, datetime, timezone
from pathlib import Path

from bowman_checklist import load_bowman_draft_unique_players
from bowman_report_common import default_checklist_path, esc_cell
from mlb_id_resolver import (
    fetch_draft_name_team_lookup,
    load_cache,
    load_overrides,
    merge_into_cache,
    resolve_name,
    save_cache,
)


def main() -> int:
    repo_root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description="Bulk-resolve Bowman checklist → MLBAM IDs.")
    parser.add_argument("--checklist", type=Path, default=None)
    parser.add_argument(
        "--overrides",
        type=Path,
        default=repo_root / "data" / "bowman_2025_mlbam_overrides.json",
    )
    parser.add_argument(
        "--cache",
        type=Path,
        default=repo_root / "data" / "bowman_mlbam_id_cache.json",
    )
    parser.add_argument("--base-only", action="store_true")
    parser.add_argument("--sleep-search", type=float, default=0.12)
    parser.add_argument(
        "--draft-year",
        type=int,
        default=2025,
        help="Use Stats API /draft/{year} for name+team IDs (0 disables). Default: 2025.",
    )
    parser.add_argument(
        "--write-overrides",
        action="store_true",
        help="Merge newly search-resolved IDs into the overrides JSON (keeps existing keys).",
    )
    parser.add_argument(
        "--out-report",
        type=Path,
        default=None,
        help="Markdown summary path (default: data/bowman_bulk_resolve_{date}.md)",
    )
    args = parser.parse_args()

    checklist = args.checklist or default_checklist_path(repo_root)
    if not checklist.is_file():
        print(f"Checklist not found: {checklist}", file=sys.stderr)
        return 1

    players = load_bowman_draft_unique_players(checklist, base_bd_only=args.base_only)
    overrides = load_overrides(args.overrides)
    cache = load_cache(args.cache)

    draft_lookup: dict[tuple[str, str], int] | None = None
    if args.draft_year > 0:
        print(
            f"Loading draft {args.draft_year} index (GET /draft/{args.draft_year})…",
            file=sys.stderr,
            flush=True,
        )
        draft_lookup = fetch_draft_name_team_lookup(args.draft_year, sleep_s=0.0)
        print(f"  Draft name+team keys: {len(draft_lookup)}", file=sys.stderr, flush=True)

    rows: list[dict] = []
    new_from_search: dict[str, int] = {}

    for i, cp in enumerate(players, start=1):
        rr = resolve_name(
            cp.name,
            overrides=overrides,
            cache=cache,
            use_search=True,
            sleep_s=args.sleep_search,
            affiliation=cp.affiliation or None,
            draft_lookup=draft_lookup,
        )
        if rr.person_id is not None and rr.source in ("search", "draft"):
            merge_into_cache(cache, cp.name, rr.person_id, rr.source, rr.detail)
            if cp.name not in overrides:
                overrides[cp.name] = rr.person_id
                new_from_search[cp.name] = rr.person_id

        pid = rr.person_id
        rows.append(
            {
                "name": cp.name,
                "aff": cp.affiliation or "—",
                "person_id": pid,
                "found": pid is not None,
                "source": rr.source,
                "note": rr.detail or "",
            }
        )
        if i % 25 == 0:
            print(f"... {i}/{len(players)}", file=sys.stderr, flush=True)

    save_cache(args.cache, cache)

    if args.write_overrides:
        args.overrides.parent.mkdir(parents=True, exist_ok=True)
        with args.overrides.open("w", encoding="utf-8") as f:
            json.dump(dict(sorted(overrides.items(), key=lambda kv: kv[0].lower())), f, indent=2)
            f.write("\n")
        print(
            f"Saved overrides ({len(overrides)} keys, {len(new_from_search)} new this run) → {args.overrides}",
            file=sys.stderr,
            flush=True,
        )

    found = sum(1 for r in rows if r["found"])
    today = datetime.now(timezone.utc).date().isoformat()
    out_md = args.out_report
    if out_md is None:
        suf = "base200" if args.base_only else "all"
        out_md = repo_root / "data" / f"bowman_bulk_resolve_{suf}_{date.today().isoformat()}.md"

    lines: list[str] = [
        "# Bowman bulk ID resolution",
        "",
        f"- **UTC:** {today}",
        f"- **Checklist:** `{checklist}`",
        f"- **Scope:** {'BD-1…BD-200' if args.base_only else 'all names'}",
        f"- **Players:** {len(rows)} — **found:** {found} — **missing:** {len(rows) - found}",
        f"- **New IDs written to overrides:** {len(new_from_search) if args.write_overrides else 0}",
        f"- **Draft year index:** {args.draft_year if args.draft_year > 0 else 'off'}",
        "",
        "| # | Player | Affiliation | MLBAM ID | Found | Source | Notes |",
        "|---:|--------|-------------|----------:|:---|:---|--------|",
    ]
    for i, r in enumerate(rows, start=1):
        pid = r["person_id"]
        pid_s = str(pid) if pid is not None else "—"
        lines.append(
            f"| {i} | {esc_cell(r['name'])} | {esc_cell(r['aff'])} | {pid_s} | "
            f"{'Yes' if r['found'] else 'No'} | {r['source']} | {esc_cell(r['note'])} |"
        )
    lines.append("")
    out_md.parent.mkdir(parents=True, exist_ok=True)
    out_md.write_text("\n".join(lines), encoding="utf-8")

    print(f"\nDone. Found {found}/{len(rows)}. Report: {out_md}", file=sys.stderr, flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
