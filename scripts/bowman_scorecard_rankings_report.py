#!/usr/bin/env python3
"""
Bowman 2025 Draft checklist: resolve MLBAM IDs, then rank players by FP
on each scorecard window (same counting formula as compare_snapshots_scorecard.py).

The **full leaderboard** lists every checklist player (200 with --base-only, ~220 without).
Unresolved names still appear with FP as "—"; only rows with MLBAM IDs get stats.
"""

from __future__ import annotations

import argparse
import sys
import time
from datetime import date, datetime, timezone
from pathlib import Path

from bowman_checklist import ChecklistPlayer, load_bowman_draft_unique_players
from bowman_report_common import SNAPSHOT_FP_LABELS, default_checklist_path, esc_cell, metrics_for_games
from mlb_game_logs import fetch_game_logs, fmt_rate
from mlb_id_resolver import (
    ResolveResult,
    fetch_draft_name_team_lookup,
    load_cache,
    load_overrides,
    merge_into_cache,
    resolve_name,
    save_cache,
)

full_key = "Full season (game log)"

# Never rank these names (e.g. checklist oddities outside the draft class).
_SCORECARD_EXCLUDED_NAMES = frozenset({"Sadaharu Oh"})


def _ops_display(m: dict) -> str:
    if int(m.get("g", 0) or 0) == 0:
        return "—"
    return fmt_rate(float(m.get("ops", 0.0)))


def build_markdown(
    *,
    season: int,
    checklist_path: Path,
    all_rows: list[dict],
    checklist_total: int,
    base_only: bool,
    limit_used: int | None,
    hitters_only: bool,
    pitchers_omitted: int,
) -> str:
    today = datetime.now(timezone.utc).date().isoformat()
    lines: list[str] = []

    lines.append("# Bowman 2025 Draft — FP scorecard rankings")
    lines.append("")
    lines.append(f"- **Season:** {season}")
    lines.append(f"- **Generated (UTC):** {today}")
    lines.append(f"- **Checklist:** `{checklist_path}`")
    scope = "**Base set (BD-1…BD-200) only**" if base_only else "**Full product (base + inserts, ~220 names)**"
    lines.append(f"- **Scope:** {scope}")
    if hitters_only:
        lines.append("- **Players:** non-pitchers only (primary position ≠ P).")
        if pitchers_omitted > 0:
            lines.append(
                f"- **Omitted as pitchers (resolved IDs):** {pitchers_omitted} — not listed below."
            )
    lines.append("")

    resolved = [r for r in all_rows if r.get("metrics") is not None]
    unresolved = [r for r in all_rows if r.get("metrics") is None]

    lines.append(
        f"**Rows in this report:** {len(all_rows)} (checklist names loaded: {checklist_total}). "
        f"**With MLBAM ID + stats:** {len(resolved)}. "
        f"**No ID yet:** {len(unresolved)}"
        + (
            " — those rows show **—** for FP until you add IDs to "
            "`data/bowman_2025_mlbam_overrides.json` or the API search finds them."
            if unresolved
            else "."
        )
    )
    if limit_used:
        lines.append(f"- **Note:** `--limit {limit_used}` was used — not the full checklist. Re-run without `--limit`.")
    lines.append("")
    lines.append(
        "**FP** (fantasy points): 1B×3, 2B×5, 3B×8, HR×10, BB×1, HBP×1, SB×2, CS×−1, RBI×1, R×1 "
        "(same as `compare_snapshots_scorecard.py`)."
    )
    lines.append("")
    lines.append(
        "Ranked sections below include **only players with resolved IDs**. "
        "The **full leaderboard** lists everyone on the checklist."
    )
    lines.append("")

    # --- Full leaderboard: resolved first (by FP szn), then unresolved (A–Z)
    by_full = sorted(
        resolved,
        key=lambda r: r["metrics"][full_key]["fp"],
        reverse=True,
    )
    by_un = sorted(unresolved, key=lambda r: r["name"].lower())

    fp_cols = " | ".join(["FP L1", "FP L3", "FP L5", "FP L10", "FP L30", "FP szn"])
    lines.append("## Full leaderboard (every checklist player)")
    lines.append("")
    lines.append(
        f"| Rank | Player | Affiliation | MLBAM ID | Src | {fp_cols} | OPS szn | G |"
    )
    lines.append(
        "| ---: | --- | --- | ---: | :--- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |"
    )

    rank = 0
    for r in by_full:
        rank += 1
        m = r["metrics"]
        fps = " | ".join(str(m[lbl]["fp"]) for lbl in SNAPSHOT_FP_LABELS)
        lines.append(
            f"| {rank} | {esc_cell(r['name'])} | {esc_cell(r['aff'])} | {r['pid']} | {r['src']} | "
            f"{fps} | {_ops_display(m[full_key])} | {m[full_key]['g']} |"
        )
    for r in by_un:
        dash = " | ".join(["—"] * 6)
        note = (r.get("note") or "").replace("|", "\\|")
        src = f"unresolved ({note})" if note else "unresolved"
        lines.append(
            f"| — | {esc_cell(r['name'])} | {esc_cell(r['aff'])} | — | {esc_cell(src)} | "
            f"{dash} | — | — |"
        )

    # --- Per-window: resolved only
    if not resolved:
        lines.append("")
        lines.append("*No resolved players — per-window rankings omitted.*")
    else:
        for lbl in SNAPSHOT_FP_LABELS:
            by_lbl = sorted(
                resolved,
                key=lambda x: x["metrics"][lbl]["fp"],
                reverse=True,
            )
            lines.append("")
            lines.append(f"## Rankings: {lbl} (resolved IDs only)")
            lines.append("")
            lines.append(f"| Rank | Player | Affiliation | ID | FP | G | OPS |")
            lines.append("|---:|--------|-------------|---:|---:|--:|----:|")
            for i, r in enumerate(by_lbl, start=1):
                mm = r["metrics"][lbl]
                lines.append(
                    f"| {i} | {esc_cell(r['name'])} | {esc_cell(r['aff'])} | {r['pid']} | "
                    f"{mm['fp']} | {mm['g']} | {_ops_display(mm)} |"
                )

    lines.append("")
    return "\n".join(lines)


def main() -> int:
    repo_root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(
        description="Bowman Draft checklist: FP scorecard rankings (full checklist rows + ranked windows)."
    )
    parser.add_argument("--checklist", type=Path, default=None)
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
        "--base-only",
        action="store_true",
        help="Only BD-1…BD-200 base checklist (200 unique players). Default is all names in the CSV (~220).",
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
    parser.add_argument("--sleep-player", type=float, default=0.08)
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--out", type=Path, default=None)
    parser.add_argument(
        "--include-pitchers",
        action="store_true",
        help="Include primary pitchers (default: omit them; this is a hitting FP scorecard).",
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

    players = [p for p in players if p.name not in _SCORECARD_EXCLUDED_NAMES]

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

    resolutions: list[tuple[ChecklistPlayer, ResolveResult]] = []
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

    all_rows: list[dict] = []
    pitchers_omitted = 0

    for cp, rr in resolutions:
        if rr.person_id is None:
            all_rows.append(
                {
                    "name": cp.name,
                    "aff": cp.affiliation or "—",
                    "pid": None,
                    "src": "unresolved",
                    "metrics": None,
                    "note": rr.detail or rr.source,
                }
            )
            continue

        time.sleep(args.sleep_player)
        _team, games, is_pitcher = fetch_game_logs(rr.person_id, args.season)
        if not args.include_pitchers and is_pitcher is True:
            pitchers_omitted += 1
            continue
        m = metrics_for_games(games)
        all_rows.append(
            {
                "name": cp.name,
                "aff": cp.affiliation or "—",
                "pid": rr.person_id,
                "src": rr.source,
                "metrics": m,
                "note": None,
            }
        )

    md = build_markdown(
        season=args.season,
        checklist_path=checklist,
        all_rows=all_rows,
        checklist_total=checklist_total,
        base_only=args.base_only,
        limit_used=limit_used,
        hitters_only=not args.include_pitchers,
        pitchers_omitted=pitchers_omitted,
    )

    out_path = args.out
    if out_path is None:
        d = date.today().isoformat()
        suf = "base200" if args.base_only else "all"
        hit_suf = "_hitters" if not args.include_pitchers else ""
        out_path = (
            repo_root / "data" / f"bowman_scorecard_rankings_{args.season}_{suf}{hit_suf}_{d}.md"
        )

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(md, encoding="utf-8")
    print(md, flush=True)
    print(
        f"\nWrote: {out_path}\n"
        f"Players in file: {len(all_rows)} (resolved: {sum(1 for r in all_rows if r.get('metrics'))}).",
        file=sys.stderr,
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
