#!/usr/bin/env python3
"""
Augment the normalized Bowman Draft checklist CSV with MLBAM ID columns from
`bowman_2025_mlbam_overrides.json` and `bowman_mlbam_id_cache.json` (no API calls).

Writes:
  data/bowman_2025_checklist_with_ids.csv  (mlbam_id, id_source, id_resolved first; omits set_key, year, brand, product, section, section_card_count)
  data/bowman_2025_checklist_with_ids_summary.md  (unique players + status)

By default only **base paper** rows are included (card numbers BD-1 … BD-200). Pass ``--all-card-types`` for inserts (BDC, CPA, AA, PDA, …).
"""

from __future__ import annotations

import argparse
import csv
import re
import sys
from collections import OrderedDict
from datetime import datetime, timezone
from pathlib import Path

from bowman_checklist import clean_player_name
from bowman_report_common import default_checklist_path
from mlb_id_resolver import load_cache, load_overrides

# Omit redundant product metadata from the export (user request).
_DROP_COLUMNS = frozenset(
    {"set_key", "year", "brand", "product", "section", "section_card_count"}
)

# Base checklist only: BD-1 … BD-200 — not BD-201+, BDC-*, CPA-*, AA-*, PDA-*, etc.
_BD_PREFIX = re.compile(r"^BD-(\d+)$", re.IGNORECASE)


def is_bd_base_card_number(card_number: str) -> bool:
    m = _BD_PREFIX.match((card_number or "").strip())
    if not m:
        return False
    n = int(m.group(1))
    return 1 <= n <= 200


def lookup_id(
    name: str,
    overrides: dict[str, int],
    cache_players: dict[str, dict],
) -> tuple[str, str]:
    """Returns (id_str or '', source: override|cache|none)."""
    if name in overrides:
        return str(overrides[name]), "override"
    c = cache_players.get(name)
    if c and isinstance(c.get("id"), int):
        return str(c["id"]), "cache"
    return "", "none"


def main() -> int:
    repo_root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(
        description="Export checklist CSV + mlbam_id / id_source columns."
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
    parser.add_argument("--out-csv", type=Path, default=None)
    parser.add_argument("--out-md", type=Path, default=None)
    parser.add_argument(
        "--missing-only",
        action="store_true",
        help="Only include rows where no MLBAM ID is known (still missing). "
        "Default output: bowman_2025_checklist_missing_ids.csv",
    )
    parser.add_argument(
        "--all-card-types",
        action="store_true",
        help="Include every checklist row (inserts, BDC, CPA, …). "
        "Default is **BD-# base cards only** (matches ^BD-\\\\d+$).",
    )
    args = parser.parse_args()

    checklist = args.checklist or default_checklist_path(repo_root)
    if not checklist.is_file():
        print(f"Checklist not found: {checklist}", file=sys.stderr)
        return 1

    overrides = load_overrides(args.overrides)
    cache_raw = load_cache(args.cache)
    # load_cache returns inner "players" dict when version matches; else empty
    # Re-read file if we need full structure - load_cache already returns players dict
    cache_players = cache_raw

    if args.missing_only:
        out_csv = args.out_csv or repo_root / "data" / "bowman_2025_checklist_missing_ids.csv"
        out_md = args.out_md or repo_root / "data" / "bowman_2025_checklist_missing_ids_summary.md"
    else:
        out_csv = args.out_csv or repo_root / "data" / "bowman_2025_checklist_with_ids.csv"
        out_md = args.out_md or repo_root / "data" / "bowman_2025_checklist_with_ids_summary.md"

    rows_out: list[dict[str, str]] = []
    unique_status: "OrderedDict[str, tuple[str, str]]" = OrderedDict()

    with checklist.open(encoding="utf-8", newline="") as f:
        r = csv.DictReader(f)
        if not r.fieldnames:
            print("Empty checklist", file=sys.stderr)
            return 1
        base_fields = [fn for fn in r.fieldnames if fn not in _DROP_COLUMNS]
        # ID columns first (mlbam_id in column A)
        fieldnames = ["mlbam_id", "id_source", "id_resolved"] + base_fields

        for row in r:
            cn = (row.get("card_number") or "").strip()
            if not args.all_card_types and not is_bd_base_card_number(cn):
                continue
            raw_name = row.get("player_name_raw") or ""
            name = clean_player_name(raw_name)
            mid, src = lookup_id(name, overrides, cache_players)
            resolved = "yes" if mid else "no"
            row_out = {k: row.get(k, "") for k in base_fields}
            row_out["mlbam_id"] = mid
            row_out["id_source"] = src
            row_out["id_resolved"] = resolved
            rows_out.append(row_out)
            if name and name not in unique_status:
                unique_status[name] = (mid, src)

    if args.missing_only:
        rows_out = [row for row in rows_out if row.get("id_resolved") == "no"]
        unique_status = OrderedDict(
            (n, (m, s)) for n, (m, s) in unique_status.items() if not m
        )

    out_csv.parent.mkdir(parents=True, exist_ok=True)
    with out_csv.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        for row in rows_out:
            w.writerow(row)

    # Summary markdown: unique players
    today = datetime.now(timezone.utc).date().isoformat()
    n_u = len(unique_status)
    n_ok = sum(1 for mid, _ in unique_status.values() if mid)
    title = (
        "# Bowman 2025 Draft — still missing MLBAM ID (unique players)"
        if args.missing_only
        else "# Bowman 2025 Draft — ID coverage (unique players)"
    )
    scope = (
        "- **Rows:** base paper checklist only (`BD-1`…`BD-200`; excludes BDC, CPA, AA, PDA, …)."
        if not args.all_card_types
        else "- **Rows:** full normalized checklist (all sections / inserts)."
    )
    lines = [
        title,
        "",
        f"- **Generated:** {today}",
        scope,
        f"- **Sources:** `{args.overrides}` + `{args.cache}`",
        f"- **Unique players:** {n_u} — **with MLBAM ID:** {n_ok} — **missing:** {n_u - n_ok}",
        f"- **CSV:** `{out_csv.name}`",
        "",
        "| Player | MLBAM ID | Source |",
        "|--------|----------|--------|",
    ]
    for name, (mid, src) in sorted(unique_status.items(), key=lambda kv: kv[0].lower()):
        lines.append(f"| {name} | {mid or '—'} | {src} |")
    lines.append("")
    out_md.write_text("\n".join(lines), encoding="utf-8")

    label = "missing-only " if args.missing_only else ""
    print(f"Wrote {label}{out_csv} ({len(rows_out)} rows)", file=sys.stderr)
    print(f"Wrote {label}{out_md} ({n_u} unique players)", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
