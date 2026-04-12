#!/usr/bin/env python3
"""
Export Bowman Draft checklist stats to static JSON for app consumption.

Writes meta.json, hitters.json, pitchers.json with server-sorted leaderboards
per cut (zero client sorting). Overwrites output paths each run.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from bowman_checklist import ChecklistPlayer, load_bowman_draft_unique_players
from bowman_report_common import (
    LABEL_TO_CUT_KEY,
    SNAPSHOT_CUT_KEYS,
    default_checklist_path,
    metrics_for_games_full,
    metrics_for_pitching_games_full,
)
from mlb_game_logs import fetch_game_logs, fetch_pitching_game_logs, fetch_primary_is_pitcher
from mlb_id_resolver import (
    ResolveResult,
    fetch_draft_name_team_lookup,
    load_cache,
    load_overrides,
    merge_into_cache,
    resolve_name,
    save_cache,
)

SCHEMA_VERSION = 1
_EXCLUDED_NAMES = frozenset({"Sadaharu Oh"})


def _build_hitter_leaderboards(
    players: list[dict],
) -> dict[str, list[dict]]:
    """Per-cut arrays sorted by fp desc, tiebreak mlbam_id asc; rank 1..n."""
    leaderboards: dict[str, list[dict]] = {ck: [] for ck in SNAPSHOT_CUT_KEYS}
    for ck in SNAPSHOT_CUT_KEYS:
        rows: list[dict] = []
        for p in players:
            mc = p["cuts"][ck]
            rows.append(
                {
                    "mlbam_id": p["mlbam_id"],
                    "name": p["name"],
                    "affiliation": p["affiliation"],
                    "id_source": p["id_source"],
                    "fp": mc["fp"],
                    "stats": mc["stats"],
                }
            )
        rows.sort(key=lambda r: (-int(r["fp"]), int(r["mlbam_id"])))
        for i, r in enumerate(rows, start=1):
            leaderboards[ck].append({**r, "rank": i})
    return leaderboards


def _build_pitcher_leaderboards(
    players: list[dict],
) -> dict[str, list[dict]]:
    """Per-cut arrays sorted by pp desc, tiebreak mlbam_id asc."""
    leaderboards: dict[str, list[dict]] = {ck: [] for ck in SNAPSHOT_CUT_KEYS}
    for ck in SNAPSHOT_CUT_KEYS:
        rows = []
        for p in players:
            mc = p["cuts"][ck]
            rows.append(
                {
                    "mlbam_id": p["mlbam_id"],
                    "name": p["name"],
                    "affiliation": p["affiliation"],
                    "id_source": p["id_source"],
                    "pp": mc["pp"],
                    "stats": mc["stats"],
                }
            )
        rows.sort(key=lambda r: (-int(r["pp"]), int(r["mlbam_id"])))
        for i, r in enumerate(rows, start=1):
            leaderboards[ck].append({**r, "rank": i})
    return leaderboards


def _atomic_write_json(path: Path, data: object, *, compact: bool) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    if compact:
        text = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
    else:
        text = json.dumps(data, ensure_ascii=False, indent=2) + "\n"
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


def main() -> int:
    repo_root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(
        description="Export Bowman Draft stats to meta.json, hitters.json, pitchers.json."
    )
    parser.add_argument("--checklist", type=Path, default=None)
    parser.add_argument("--season", type=int, default=datetime.now().year)
    parser.add_argument(
        "--overrides",
        type=Path,
        default=repo_root / "data" / "bowman_2025_mlbam_overrides.json",
    )
    parser.add_argument("--cache", type=Path, default=repo_root / "data" / "bowman_mlbam_id_cache.json")
    parser.add_argument("--base-only", action="store_true")
    parser.add_argument("--no-search", action="store_true")
    parser.add_argument("--no-save-cache", action="store_true")
    parser.add_argument("--draft-year", type=int, default=2025)
    parser.add_argument("--sleep-search", type=float, default=0.12)
    parser.add_argument("--sleep-player", type=float, default=0.08)
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument(
        "--out-dir",
        type=Path,
        default=repo_root / "dist" / "bowman-app",
        help="Directory for meta.json, hitters.json, pitchers.json",
    )
    parser.add_argument("--compact", action="store_true", help="Minified JSON (no indent).")
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

    players = [p for p in players if p.name not in _EXCLUDED_NAMES]
    checklist_total = len(players)
    if args.limit and args.limit > 0:
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

    hitters_raw: list[dict] = []
    pitchers_raw: list[dict] = []
    unresolved = 0

    for cp, rr in resolutions:
        if rr.person_id is None:
            unresolved += 1
            continue
        time.sleep(args.sleep_player)
        is_p = fetch_primary_is_pitcher(rr.person_id)
        if is_p is True:
            _t, games, _ = fetch_pitching_game_logs(rr.person_id, args.season)
            cuts = metrics_for_pitching_games_full(games)
            pitchers_raw.append(
                {
                    "mlbam_id": rr.person_id,
                    "name": cp.name,
                    "affiliation": cp.affiliation or "",
                    "id_source": rr.source,
                    "cuts": cuts,
                }
            )
        elif is_p is False:
            _t, games, _ = fetch_game_logs(rr.person_id, args.season)
            cuts = metrics_for_games_full(games)
            hitters_raw.append(
                {
                    "mlbam_id": rr.person_id,
                    "name": cp.name,
                    "affiliation": cp.affiliation or "",
                    "id_source": rr.source,
                    "cuts": cuts,
                }
            )
        else:
            unresolved += 1

    scope_s = "base200" if args.base_only else "full"
    generated_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")

    meta = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": generated_at,
        "stats_season": args.season,
        "checklist_product": "2025_bowman_draft",
        "checklist_scope": scope_s,
        "checklist_csv": str(checklist),
        "counts": {
            "checklist_names": checklist_total,
            "hitters": len(hitters_raw),
            "pitchers": len(pitchers_raw),
            "unresolved_ids": unresolved,
        },
        "assets": {
            "hitters": "hitters.json",
            "pitchers": "pitchers.json",
        },
        "ranking": {
            "hitters": "fp_desc",
            "pitchers": "pp_desc",
            "tiebreak": "mlbam_id_asc",
        },
        "cuts": list(SNAPSHOT_CUT_KEYS),
        "cut_labels": {v: k for k, v in LABEL_TO_CUT_KEY.items()},
    }

    hitters_payload = {
        "sort_by": "fp_desc_per_cut",
        "leaderboards": _build_hitter_leaderboards(hitters_raw),
    }
    pitchers_payload = {
        "sort_by": "pp_desc_per_cut",
        "leaderboards": _build_pitcher_leaderboards(pitchers_raw),
    }

    out_dir = args.out_dir
    _atomic_write_json(out_dir / "meta.json", meta, compact=args.compact)
    _atomic_write_json(out_dir / "hitters.json", hitters_payload, compact=args.compact)
    _atomic_write_json(out_dir / "pitchers.json", pitchers_payload, compact=args.compact)

    print(
        f"Wrote {out_dir / 'meta.json'}, hitters.json, pitchers.json\n"
        f"  hitters={len(hitters_raw)} pitchers={len(pitchers_raw)} unresolved={unresolved}",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
