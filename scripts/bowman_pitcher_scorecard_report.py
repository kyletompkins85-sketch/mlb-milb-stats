#!/usr/bin/env python3
"""
Bowman 2025 Draft — pitcher scorecard: emphasize K, BB, HR; de-emphasize wins.

**PP** (pitching points) is a counting score from K / BB / HR / IP only — wins are not used.
Strk% = strikes ÷ pitches (all strikes in the line; not Statcast swinging-strike rate).
"""

from __future__ import annotations

import argparse
import sys
import time
from datetime import date, datetime, timezone
from pathlib import Path

from bowman_checklist import ChecklistPlayer, load_bowman_draft_unique_players
from bowman_report_common import SNAPSHOT_FP_LABELS, default_checklist_path, esc_cell, metrics_for_pitching_games
from mlb_game_logs import fetch_pitching_game_logs, fetch_primary_is_pitcher, outs_to_ip_display
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

_SCORECARD_EXCLUDED_NAMES = frozenset({"Sadaharu Oh"})

_PP_HDR = {
    "Last 1 games": "PP L1",
    "Last 3 games": "PP L3",
    "Last 5 games": "PP L5",
    "Last 10 games": "PP L10",
    "Last 30 games": "PP L30",
    "Full season (game log)": "PP szn",
}


def _fmt_rate(x: float) -> str:
    return f"{x:.2f}"


def _fmt_strk_pct(m: dict) -> str:
    if int(m.get("pitches", 0) or 0) == 0:
        return "—"
    return f"{100.0 * float(m['strike_pct']):.1f}%"


def build_markdown(
    *,
    season: int,
    checklist_path: Path,
    rows: list[dict],
    checklist_total: int,
    base_only: bool,
    limit_used: int | None,
    non_pitchers_skipped: int,
    unresolved_no_id: int,
) -> str:
    today = datetime.now(timezone.utc).date().isoformat()
    lines: list[str] = []

    lines.append("# Bowman 2025 Draft — pitcher scorecard (K / BB / HR)")
    lines.append("")
    lines.append(f"- **Season:** {season}")
    lines.append(f"- **Generated (UTC):** {today}")
    lines.append(f"- **Checklist:** `{checklist_path}`")
    scope = "**Base set (BD-1…BD-200) only**" if base_only else "**Full product (base + inserts, ~220 names)**"
    lines.append(f"- **Scope:** {scope}")
    lines.append("- **Players:** primary pitchers only (Stats API `primaryPosition` = P).")
    if non_pitchers_skipped > 0:
        lines.append(
            f"- **Skipped (not pitchers):** {non_pitchers_skipped} resolved checklist names."
        )
    lines.append("")
    lines.append(
        f"**Pitchers listed:** {len(rows)} (checklist names loaded: {checklist_total}). "
        f"**Unresolved (no MLBAM ID):** {unresolved_no_id} — not listed."
    )
    if limit_used:
        lines.append(f"- **Note:** `--limit {limit_used}` — re-run without for full checklist.")
    lines.append("")
    lines.append(
        "**PP** (pitching points): `3×SO − 2×BB − 4×HR + floor(IP innings)` — "
        "**wins are not included.** Sorting uses PP on rolling windows the same way as hitting FP."
    )
    lines.append(
        "**Strk%** = `strikes ÷ pitches` from the game line (includes called strikes and fouls; "
        "not Statcast whiff%). *v1 does not pull Statcast swinging-strike data.*"
    )
    lines.append("")

    if not rows:
        lines.append("*No qualifying pitchers with resolved IDs in this run.*")
        lines.append("")
        return "\n".join(lines)

    pp_headers = " | ".join(_PP_HDR[l] for l in SNAPSHOT_FP_LABELS)
    by_full = sorted(rows, key=lambda r: r["metrics"][full_key]["pp"], reverse=True)

    lines.append("## Full leaderboard (pitchers)")
    lines.append("")
    lines.append(
        "| Rank | Player | Affiliation | MLBAM ID | Src | "
        + pp_headers
        + " | SO | BB | HR | IP | K/9 | BB/9 | HR/9 | WHIP | Strk% | W |"
    )
    lines.append("| " + " | ".join(["---:"] * 21) + " |")

    m_full = full_key
    for rank, r in enumerate(by_full, start=1):
        m = r["metrics"][m_full]
        pps = " | ".join(str(r["metrics"][lbl]["pp"]) for lbl in SNAPSHOT_FP_LABELS)
        ip_s = outs_to_ip_display(m["ip_outs"]) if m.get("ip_outs", 0) else "0.0"
        wl = f"{m['wins']}-{m['losses']}"
        lines.append(
            f"| {rank} | {esc_cell(r['name'])} | {esc_cell(r['aff'])} | {r['pid']} | {r['src']} | {pps} | "
            f"{m['so']} | {m['bb']} | {m['hr']} | {ip_s} | {_fmt_rate(m['k9'])} | {_fmt_rate(m['bb9'])} | "
            f"{_fmt_rate(m['hr9'])} | {_fmt_rate(m['whip'])} | {_fmt_strk_pct(m)} | {wl} |"
        )

    for lbl in SNAPSHOT_FP_LABELS:
        by_lbl = sorted(rows, key=lambda x: x["metrics"][lbl]["pp"], reverse=True)
        short = _PP_HDR[lbl]
        lines.append("")
        lines.append(f"## Rankings: {lbl} ({short})")
        lines.append("")
        lines.append(
            "| Rank | Player | Affiliation | ID | PP | SO | BB | HR | IP | K/9 | WHIP | Strk% |"
        )
        lines.append("|---:|--------|-------------|---:|---:|---:|---:|---:|---:|---:|---:|---:|")
        for i, r in enumerate(by_lbl, start=1):
            mm = r["metrics"][lbl]
            ip_s = outs_to_ip_display(mm["ip_outs"]) if mm.get("ip_outs", 0) else "0.0"
            lines.append(
                f"| {i} | {esc_cell(r['name'])} | {esc_cell(r['aff'])} | {r['pid']} | {mm['pp']} | "
                f"{mm['so']} | {mm['bb']} | {mm['hr']} | {ip_s} | {_fmt_rate(mm['k9'])} | "
                f"{_fmt_rate(mm['whip'])} | {_fmt_strk_pct(mm)} |"
            )

    lines.append("")
    return "\n".join(lines)


def main() -> int:
    repo_root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(
        description="Bowman Draft: pitcher K/BB/HR scorecard (pitching game logs)."
    )
    parser.add_argument("--checklist", type=Path, default=None)
    parser.add_argument("--season", type=int, default=datetime.now().year)
    parser.add_argument(
        "--overrides",
        type=Path,
        default=repo_root / "data" / "bowman_2025_mlbam_overrides.json",
    )
    parser.add_argument("--cache", type=Path, default=repo_root / "data" / "bowman_mlbam_id_cache.json")
    parser.add_argument(
        "--base-only",
        action="store_true",
        help="Only BD-1…BD-200 (200 names). Default: full checklist (~220).",
    )
    parser.add_argument("--no-search", action="store_true")
    parser.add_argument("--no-save-cache", action="store_true")
    parser.add_argument("--draft-year", type=int, default=2025)
    parser.add_argument("--sleep-search", type=float, default=0.12)
    parser.add_argument("--sleep-player", type=float, default=0.08)
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--out", type=Path, default=None)
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
        fetch_draft_name_team_lookup(args.draft_year, sleep_s=0.0) if args.draft_year > 0 else None
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

    rows: list[dict] = []
    non_pitchers_skipped = 0
    unresolved_no_id = 0

    for cp, rr in resolutions:
        if rr.person_id is None:
            unresolved_no_id += 1
            continue

        time.sleep(args.sleep_player)
        if fetch_primary_is_pitcher(rr.person_id) is not True:
            non_pitchers_skipped += 1
            continue
        _team, games, _ = fetch_pitching_game_logs(rr.person_id, args.season)

        metrics = metrics_for_pitching_games(games)
        rows.append(
            {
                "name": cp.name,
                "aff": cp.affiliation or "—",
                "pid": rr.person_id,
                "src": rr.source,
                "metrics": metrics,
            }
        )

    md = build_markdown(
        season=args.season,
        checklist_path=checklist,
        rows=rows,
        checklist_total=checklist_total,
        base_only=args.base_only,
        limit_used=limit_used,
        non_pitchers_skipped=non_pitchers_skipped,
        unresolved_no_id=unresolved_no_id,
    )

    out_path = args.out
    if out_path is None:
        d = date.today().isoformat()
        suf = "base200" if args.base_only else "all"
        out_path = repo_root / "data" / f"bowman_pitcher_scorecard_{args.season}_{suf}_{d}.md"

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(md, encoding="utf-8")
    print(md, flush=True)
    print(
        f"\nWrote: {out_path}\nPitchers in file: {len(rows)} "
        f"(non-pitchers skipped: {non_pitchers_skipped}, no ID: {unresolved_no_id}).",
        file=sys.stderr,
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
