#!/usr/bin/env python3
"""
Fetch MiLB/MLB game logs for a player and report rolling hitting snapshots:
last 1, 3, 5, 10, 30 games and full season (current year).

Defaults: Eli Willits (816113).
"""

from __future__ import annotations

import argparse
import sys
from datetime import date, datetime, timezone
from pathlib import Path

from mlb_game_logs import aggregate_hitting, fetch_game_logs, fmt_rate, snapshot_rows


def build_report(
    player_name: str,
    person_id: int,
    season: int,
    current_team: str | None,
    games,
) -> str:
    from mlb_game_logs import GameLine

    lines: list[str] = []
    today = datetime.now(timezone.utc).date().isoformat()
    lines.append(f"# Hitting snapshot report: {player_name}")
    lines.append("")
    lines.append(f"- **MLBAM person ID:** {person_id}")
    lines.append(f"- **Season:** {season}")
    lines.append(f"- **Report date (UTC):** {today}")
    if current_team:
        lines.append(f"- **Current team (API):** {current_team}")
    lines.append(f"- **Games in game log:** {len(games)}")
    lines.append("")
    lines.append("Rolling windows use the **most recent** games in the log (including any level returned by the API).")
    lines.append("")
    lines.append("| Snapshot | Games | PA | AB | H | HR | BB | SO | SB | AVG | OBP | SLG | OPS |")
    lines.append("|----------|------:|---:|---:|--:|---:|---:|---:|---:|----:|----:|----:|----:|")

    if not games:
        lines.append("| *(no game log rows for this season)* | | | | | | | | | | | | |")
        lines.append("")
        return "\n".join(lines)

    for label, subset in snapshot_rows(games):
        a = aggregate_hitting(subset)
        lines.append(
            "| "
            + " | ".join(
                [
                    label,
                    str(int(a["games"])),
                    str(int(a["pa"])),
                    str(int(a["ab"])),
                    str(int(a["h"])),
                    str(int(a["hr"])),
                    str(int(a["bb"])),
                    str(int(a["so"])),
                    str(int(a["sb"])),
                    fmt_rate(float(a["avg"])),
                    fmt_rate(float(a["obp"])),
                    fmt_rate(float(a["slg"])),
                    fmt_rate(float(a["ops"])),
                ]
            )
            + " |"
        )

    lines.append("")
    lines.append("## Detail (full log, newest first)")
    lines.append("")
    for g in reversed(games):
        s = g.stat
        sm = (s.get("summary") or "").replace("|", "\\|")
        hm = "vs" if g.is_home else "@"
        lines.append(
            f"- **{g.game_date}** {hm} {g.opponent} — {sm} "
            f"(gamePk {g.game_pk})"
        )
    lines.append("")
    return "\n".join(lines)


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description="Rolling hitting snapshots from MLB Stats API game logs.")
    parser.add_argument("--person-id", type=int, default=816113, help="MLBAM person ID (default: Eli Willits)")
    parser.add_argument("--name", type=str, default="Eli Willits", help="Display name for the report")
    parser.add_argument("--season", type=int, default=datetime.now().year, help="Season year")
    parser.add_argument(
        "--out",
        type=Path,
        default=None,
        help="Write markdown here (default: data/<slug>_snapshots_<season>_<date>.md)",
    )
    args = parser.parse_args()

    current_team, games, _ = fetch_game_logs(args.person_id, args.season)
    report = build_report(args.name, args.person_id, args.season, current_team, games)

    out_path = args.out
    if out_path is None:
        slug = args.name.lower().replace(" ", "_").replace(".", "")
        d = date.today().isoformat()
        out_path = root / "data" / f"{slug}_snapshots_{args.season}_{d}.md"

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(report, encoding="utf-8")
    print(report, flush=True)
    print(f"\nWrote: {out_path}", file=sys.stderr, flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
