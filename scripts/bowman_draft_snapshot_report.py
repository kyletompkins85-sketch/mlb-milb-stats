#!/usr/bin/env python3
"""
Bowman 2025 Draft checklist → MLBAM IDs (search + cache + overrides) → hitting snapshots.

Reads normalized checklist CSV from cardlotlister-oauth by default, resolves players,
optionally writes ID cache, and emits markdown (summary; optional per-player detail).
"""

from __future__ import annotations

import argparse
import sys
import time
from datetime import date, datetime, timezone
from pathlib import Path

from bowman_checklist import ChecklistPlayer, load_bowman_draft_unique_players
from bowman_report_common import default_checklist_path, metrics_for_games
from mlb_game_logs import (
    aggregate_hitting,
    counting_fantasy_points,
    fetch_game_logs,
    fmt_rate,
    snapshot_rows,
)
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
    season: int,
    checklist_path: Path,
    rows: list[dict],
    unresolved: list[tuple[str, str]],
    detail_players: list[dict] | None,
) -> str:
    today = datetime.now(timezone.utc).date().isoformat()
    lines: list[str] = []
    lines.append("# Bowman 2025 Draft — hitting snapshot report")
    lines.append("")
    lines.append(f"- **Season stats:** {season}")
    lines.append(f"- **Generated (UTC):** {today}")
    lines.append(f"- **Checklist:** `{checklist_path}`")
    lines.append("")
    lines.append(
        "**FP** = counting fantasy points (same formula as `compare_snapshots_scorecard.py`). "
        "IDs from **overrides** → **cache** → **draft (name+team)** → **search**."
    )
    lines.append("")
    lines.append("## Summary")
    lines.append("")
    lines.append(
        "| Player | Affiliation | MLBAM ID | Src | G | PA | FP szn | OPS szn | FP L5 | OPS L5 | FP L1 | OPS L1 |"
    )
    lines.append("|--------|-------------|----------|:---|--:|---:|-------:|--------:|------:|--------:|------:|--------:|")

    for r in rows:
        lines.append(
            "| {name} | {aff} | {pid} | {src} | {g} | {pa} | {fpf} | {opsf} | {fp5} | {ops5} | {fp1} | {ops1} |".format(
                **r
            )
        )

    if unresolved:
        lines.append("")
        lines.append("## Unresolved (no MLBAM ID)")
        lines.append("")
        for name, reason in unresolved:
            lines.append(f"- **{name}** — {reason}")
        lines.append("")

    if detail_players:
        lines.append("")
        lines.append("## Per-player snapshot tables")
        lines.append("")
        for block in detail_players:
            lines.append(block)
            lines.append("")

    return "\n".join(lines)


def format_player_detail(name: str, person_id: int, team: str | None, games) -> str:
    lines: list[str] = []
    lines.append(f"### {name} (`{person_id}`)")
    if team:
        lines.append(f"*Current team (API): {team}*")
    lines.append("")
    lines.append("| Snapshot | G | PA | FP | AVG | OPS |")
    lines.append("|----------|--:|---:|---:|----:|----:|")
    if not games:
        lines.append("| *(no game log)* | 0 | 0 | 0 | — | — |")
        return "\n".join(lines)

    for label, subset in snapshot_rows(games):
        a = aggregate_hitting(subset)
        fp = counting_fantasy_points(a)
        avg_s = fmt_rate(float(a["avg"])) if int(a["ab"]) else "—"
        ops_s = fmt_rate(float(a["ops"]))
        lines.append(
            f"| {label} | {int(a['games'])} | {int(a['pa'])} | {fp} | {avg_s} | {ops_s} |"
        )
    return "\n".join(lines)


def main() -> int:
    repo_root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description="Bowman Draft checklist → MLBAM stats report.")
    parser.add_argument(
        "--checklist",
        type=Path,
        default=None,
        help="Path to 2025_Bowman_Draft_Normalized.csv (default: sibling cardlotlister-oauth/...)",
    )
    parser.add_argument("--season", type=int, default=datetime.now().year)
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
        "--no-search",
        action="store_true",
        help="Only use overrides + cache (no API name search).",
    )
    parser.add_argument(
        "--no-save-cache",
        action="store_true",
        help="Do not write resolved search hits to cache file.",
    )
    parser.add_argument(
        "--draft-year",
        type=int,
        default=2025,
        help="Use /draft/{year} for name+team (0 disables). Default: 2025.",
    )
    parser.add_argument(
        "--sleep-search",
        type=float,
        default=0.12,
        help="Seconds between search API calls.",
    )
    parser.add_argument(
        "--sleep-player",
        type=float,
        default=0.08,
        help="Seconds between player stat fetches.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=0,
        help="Only process first N players (0 = all).",
    )
    parser.add_argument(
        "--detail",
        action="store_true",
        help="Include per-player snapshot markdown tables (large output).",
    )
    parser.add_argument(
        "--base-only",
        action="store_true",
        help="Only BD-1…BD-200 base names (~200 players). Default: all unique names in CSV (~220).",
    )
    parser.add_argument("--out", type=Path, default=None)
    args = parser.parse_args()

    checklist = args.checklist or default_checklist_path(repo_root)
    if not checklist.is_file():
        print(f"Checklist not found: {checklist}", file=sys.stderr)
        print("Pass --checklist /path/to/2025_Bowman_Draft_Normalized.csv", file=sys.stderr)
        return 1

    try:
        players = load_bowman_draft_unique_players(checklist, base_bd_only=args.base_only)
    except (OSError, ValueError) as e:
        print(e, file=sys.stderr)
        return 1

    if args.limit and args.limit > 0:
        players = players[: args.limit]

    overrides = load_overrides(args.overrides)
    cache = load_cache(args.cache)

    draft_lookup = (
        fetch_draft_name_team_lookup(args.draft_year, sleep_s=0.0)
        if args.draft_year > 0
        else None
    )

    resolutions: list[tuple[ChecklistPlayer, ResolveResult]] = []
    unresolved: list[tuple[str, str]] = []

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
        resolutions.append((cp, rr))
        if rr.person_id is not None and rr.source in ("search", "draft") and not args.no_save_cache:
            merge_into_cache(cache, cp.name, rr.person_id, rr.source, rr.detail)

    if not args.no_save_cache:
        save_cache(args.cache, cache)

    # Stats phase
    summary_rows: list[dict] = []
    detail_blocks: list[str] | None = [] if args.detail else None

    for cp, rr in resolutions:
        if rr.person_id is None:
            unresolved.append((cp.name, rr.detail or rr.source))
            summary_rows.append(
                {
                    "name": cp.name,
                    "aff": cp.affiliation or "—",
                    "pid": "—",
                    "src": rr.source,
                    "g": "—",
                    "pa": "—",
                    "fpf": "—",
                    "opsf": "—",
                    "fp5": "—",
                    "ops5": "—",
                    "fp1": "—",
                    "ops1": "—",
                }
            )
            continue

        time.sleep(args.sleep_player)
        team, games, _ = fetch_game_logs(rr.person_id, args.season)
        m = metrics_for_games(games)
        full = m.get("Full season (game log)", {})
        l5 = m.get("Last 5 games", {})
        l1 = m.get("Last 1 games", {})

        def _ops_cell(m: dict) -> str:
            if int(m.get("g", 0) or 0) == 0:
                return "—"
            return fmt_rate(float(m.get("ops", 0.0)))

        summary_rows.append(
            {
                "name": cp.name.replace("|", "\\|"),
                "aff": (cp.affiliation or "—").replace("|", "\\|"),
                "pid": str(rr.person_id),
                "src": rr.source,
                "g": str(full.get("g", 0)),
                "pa": str(full.get("pa", 0)),
                "fpf": str(full.get("fp", 0)),
                "opsf": _ops_cell(full),
                "fp5": str(l5.get("fp", 0)),
                "ops5": _ops_cell(l5),
                "fp1": str(l1.get("fp", 0)),
                "ops1": _ops_cell(l1),
            }
        )

        if detail_blocks is not None:
            detail_blocks.append(format_player_detail(cp.name, rr.person_id, team, games))

    md = build_markdown(
        season=args.season,
        checklist_path=checklist,
        rows=summary_rows,
        unresolved=unresolved,
        detail_players=detail_blocks,
    )

    out_path = args.out
    if out_path is None:
        d = date.today().isoformat()
        out_path = repo_root / "data" / f"bowman_draft_snapshots_{args.season}_{d}.md"

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(md, encoding="utf-8")
    print(md, flush=True)
    print(f"\nWrote: {out_path}", file=sys.stderr, flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
