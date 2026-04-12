#!/usr/bin/env python3
"""
Compare two players on rolling snapshot windows using a single counting-based score (FP)
plus OPS for context. Writes markdown under data/.
"""

from __future__ import annotations

import argparse
import sys
from datetime import date, datetime, timezone
from pathlib import Path

from mlb_game_logs import (
    aggregate_hitting,
    counting_fantasy_points,
    fetch_game_logs,
    fmt_rate,
    snapshot_rows,
)

# Defaults: JoJo Parker vs Eli Willits
DEFAULT_A = (828098, "JoJo Parker")
DEFAULT_B = (816113, "Eli Willits")


def build_scorecard(
    season: int,
    player_a: tuple[int, str],
    player_b: tuple[int, str],
) -> str:
    id_a, name_a = player_a
    id_b, name_b = player_b

    team_a, games_a, _ = fetch_game_logs(id_a, season)
    team_b, games_b, _ = fetch_game_logs(id_b, season)

    today = datetime.now(timezone.utc).date().isoformat()
    lines: list[str] = []
    lines.append("# Snapshot scorecard: counting points vs OPS")
    lines.append("")
    lines.append(f"- **Season:** {season}")
    lines.append(f"- **Report date (UTC):** {today}")
    lines.append("")
    lines.append(f"| Player | MLBAM ID | Team (API) | Games in log |")
    lines.append(f"|--------|----------|------------|-------------:|")
    lines.append(f"| {name_a} | {id_a} | {team_a or '—'} | {len(games_a)} |")
    lines.append(f"| {name_b} | {id_b} | {team_b or '—'} | {len(games_b)} |")
    lines.append("")
    lines.append("## FP (counting score)")
    lines.append("")
    lines.append(
        "**FP** is an integer built only from counting stats: "
        "1B×3, 2B×5, 3B×8, HR×10, BB×1, HBP×1, SB×2, CS×−1, RBI×1, R×1. "
        "Higher is better; it does not penalize strikeouts."
    )
    lines.append("")
    short_a, short_b = name_a.split()[-1], name_b.split()[-1]
    lines.append(
        f"| Window | {name_a} FP | {name_b} FP | "
        f"Δ ({short_a} − {short_b}) | Leader | {name_a} OPS | {name_b} OPS |"
    )
    lines.append("|--------|---:|---:|---:|:---|---:|---:|")

    labels_a = snapshot_rows(games_a)
    labels_b = snapshot_rows(games_b)

    for (label_a, sub_a), (label_b, sub_b) in zip(labels_a, labels_b):
        assert label_a == label_b, (label_a, label_b)
        agg_a = aggregate_hitting(sub_a)
        agg_b = aggregate_hitting(sub_b)
        fp_a = counting_fantasy_points(agg_a)
        fp_b = counting_fantasy_points(agg_b)
        delta = fp_a - fp_b
        if delta > 0:
            leader = name_a.split()[-1]
        elif delta < 0:
            leader = name_b.split()[-1]
        else:
            leader = "Tie"
        oa = fmt_rate(float(agg_a["ops"]))
        ob = fmt_rate(float(agg_b["ops"]))
        lines.append(
            f"| {label_a} | {fp_a} | {fp_b} | {delta:+d} | {leader} | {oa} | {ob} |"
        )

    lines.append("")
    lines.append("## Side-by-side FP only")
    lines.append("")
    lines.append(f"| Window | {name_a} | {name_b} |")
    lines.append("|--------|-------:|-------:|")
    for (label_a, sub_a), (label_b, sub_b) in zip(labels_a, labels_b):
        fp_a = counting_fantasy_points(aggregate_hitting(sub_a))
        fp_b = counting_fantasy_points(aggregate_hitting(sub_b))
        lines.append(f"| {label_a} | {fp_a} | {fp_b} |")

    lines.append("")
    return "\n".join(lines)


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description="Compare two players on snapshot windows (FP + OPS).")
    parser.add_argument("--season", type=int, default=datetime.now().year)
    parser.add_argument("--a-id", type=int, default=DEFAULT_A[0])
    parser.add_argument("--a-name", type=str, default=DEFAULT_A[1])
    parser.add_argument("--b-id", type=int, default=DEFAULT_B[0])
    parser.add_argument("--b-name", type=str, default=DEFAULT_B[1])
    parser.add_argument("--out", type=Path, default=None)
    args = parser.parse_args()

    player_a = (args.a_id, args.a_name)
    player_b = (args.b_id, args.b_name)
    report = build_scorecard(args.season, player_a, player_b)

    out_path = args.out
    if out_path is None:
        slug_a = args.a_name.lower().replace(" ", "_")
        slug_b = args.b_name.lower().replace(" ", "_")
        d = date.today().isoformat()
        out_path = root / "data" / f"scorecard_{slug_a}_vs_{slug_b}_{args.season}_{d}.md"

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(report, encoding="utf-8")
    print(report, flush=True)
    print(f"\nWrote: {out_path}", file=sys.stderr, flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
