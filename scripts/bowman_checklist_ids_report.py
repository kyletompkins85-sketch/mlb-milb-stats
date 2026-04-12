#!/usr/bin/env python3
"""
Every Bowman Draft checklist player: MLBAM ID resolution (override / cache / search).

Does not fetch stats — only ID lookup. Fast compared to snapshot reports.
"""

from __future__ import annotations

import argparse
import csv
import sys
from datetime import date, datetime, timezone
from pathlib import Path

from bowman_checklist import load_bowman_draft_unique_players
from bowman_report_common import default_checklist_path, esc_cell
from mlb_id_resolver import (
    ResolveResult,
    fetch_draft_name_team_lookup,
    load_cache,
    load_overrides,
    merge_into_cache,
    resolve_name,
    save_cache,
)


def build_markdown(
    *,
    checklist_path: Path,
    rows: list[dict],
    base_only: bool,
    limit_used: int | None,
) -> str:
    today = datetime.now(timezone.utc).date().isoformat()
    n = len(rows)
    found = sum(1 for r in rows if r["found"])
    lines: list[str] = []

    lines.append("# Bowman checklist — MLBAM player ID resolution")
    lines.append("")
    lines.append(f"- **Generated (UTC):** {today}")
    lines.append(f"- **Checklist file:** `{checklist_path}`")
    lines.append(
        f"- **Scope:** {'Base set BD-1…BD-200 (200 players)' if base_only else 'All unique names in CSV (~220)'}"
    )
    lines.append(f"- **Rows:** {n} — **with MLBAM ID:** {found} — **not found:** {n - found}")
    if limit_used:
        lines.append(f"- **Note:** `--limit {limit_used}` — re-run without `--limit` for everyone.")
    lines.append("")
    lines.append(
        "| # | Player | Affiliation | MLBAM ID | Found | Source | Notes |"
    )
    lines.append("|---:|--------|-------------|----------:|:---|:---|--------|")

    for i, r in enumerate(rows, start=1):
        pid = r["person_id"]
        pid_s = str(pid) if pid is not None else "—"
        found_s = "Yes" if r["found"] else "No"
        notes = esc_cell((r.get("note") or "").replace("\n", " "))
        lines.append(
            f"| {i} | {esc_cell(r['name'])} | {esc_cell(r['aff'])} | {pid_s} | {found_s} | {r['source']} | {notes} |"
        )

    lines.append("")
    return "\n".join(lines)


def write_csv(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(
            f,
            fieldnames=["player", "affiliation", "mlbam_id", "found", "source", "notes"],
        )
        w.writeheader()
        for r in rows:
            w.writerow(
                {
                    "player": r["name"],
                    "affiliation": r["aff"],
                    "mlbam_id": r["person_id"] if r["person_id"] is not None else "",
                    "found": "yes" if r["found"] else "no",
                    "source": r["source"],
                    "notes": r.get("note") or "",
                }
            )


def main() -> int:
    repo_root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(
        description="Table of every checklist player and MLBAM ID resolution status."
    )
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
    parser.add_argument(
        "--base-only",
        action="store_true",
        help="Only BD-1…BD-200 base checklist (200 players).",
    )
    parser.add_argument("--no-search", action="store_true")
    parser.add_argument("--no-save-cache", action="store_true")
    parser.add_argument(
        "--draft-year",
        type=int,
        default=2025,
        help="Use /draft/{year} for name+team (0 disables). Default: 2025.",
    )
    parser.add_argument("--sleep-search", type=float, default=0.12)
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--out", type=Path, default=None)
    parser.add_argument(
        "--csv-out",
        type=Path,
        default=None,
        help="CSV path (default: same path as markdown with .csv).",
    )
    parser.add_argument(
        "--no-csv",
        action="store_true",
        help="Do not write a CSV file.",
    )
    args = parser.parse_args()

    checklist = args.checklist or default_checklist_path(repo_root)
    if not checklist.is_file():
        print(f"Checklist not found: {checklist}", file=sys.stderr)
        return 1

    try:
        players = load_bowman_draft_unique_players(checklist, base_bd_only=args.base_only)
    except (OSError, ValueError) as e:
        print(e, file=sys.stderr)
        return 1

    checklist_total = len(players)
    limit_used: int | None = None
    if args.limit and args.limit > 0:
        limit_used = args.limit
        players = players[: args.limit]

    overrides = load_overrides(args.overrides)
    cache = load_cache(args.cache)

    draft_lookup = (
        fetch_draft_name_team_lookup(args.draft_year, sleep_s=0.0)
        if args.draft_year > 0
        else None
    )

    rows: list[dict] = []
    for cp in players:
        rr = resolve_name(
            cp.name,
            overrides=overrides,
            cache=cache,
            use_search=not args.no_search,
            sleep_s=args.sleep_search,
            affiliation=cp.affiliation or None,
            draft_lookup=draft_lookup,
        )
        assert isinstance(rr, ResolveResult)
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
        if pid is not None and rr.source in ("search", "draft") and not args.no_save_cache:
            merge_into_cache(cache, cp.name, pid, rr.source, rr.detail)

    if not args.no_save_cache:
        save_cache(args.cache, cache)

    md = build_markdown(
        checklist_path=checklist,
        rows=rows,
        base_only=args.base_only,
        limit_used=limit_used,
    )

    out_md = args.out
    if out_md is None:
        d = date.today().isoformat()
        suf = "base200" if args.base_only else "all"
        out_md = repo_root / "data" / f"bowman_checklist_ids_{suf}_{d}.md"

    out_md.parent.mkdir(parents=True, exist_ok=True)
    out_md.write_text(md, encoding="utf-8")

    csv_path: Path | None = None
    if not args.no_csv:
        csv_path = args.csv_out or out_md.with_suffix(".csv")
        write_csv(csv_path, rows)

    print(md, flush=True)
    print(f"\nWrote: {out_md}", file=sys.stderr, flush=True)
    if csv_path is not None:
        print(f"Wrote: {csv_path}", file=sys.stderr, flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
