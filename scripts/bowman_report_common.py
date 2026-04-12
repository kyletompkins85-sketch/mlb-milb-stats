"""Shared defaults and metrics for Bowman checklist reports."""

from __future__ import annotations

from pathlib import Path

from mlb_game_logs import (
    aggregate_hitting,
    aggregate_pitching,
    counting_fantasy_points,
    pitching_fantasy_points,
    snapshot_rows,
)

# Window labels match `snapshot_rows()` / compare_snapshots_scorecard FP rows.
SNAPSHOT_FP_LABELS = (
    "Last 1 games",
    "Last 3 games",
    "Last 5 games",
    "Last 10 games",
    "Last 30 games",
    "Full season (game log)",
)

# Short keys for app JSON / APIs (order matches SNAPSHOT_FP_LABELS).
SNAPSHOT_CUT_KEYS = ("l1", "l3", "l5", "l10", "l30", "season")

LABEL_TO_CUT_KEY: dict[str, str] = {
    "Last 1 games": "l1",
    "Last 3 games": "l3",
    "Last 5 games": "l5",
    "Last 10 games": "l10",
    "Last 30 games": "l30",
    "Full season (game log)": "season",
}


def default_checklist_path(repo_root: Path) -> Path:
    return repo_root.parent / "cardlotlister-oauth" / "data" / "checklists" / "normalized" / "2025_Bowman_Draft_Normalized.csv"


def metrics_for_games(games) -> dict[str, dict]:
    """Label -> fp, ops, games, pa, avg from snapshot windows."""
    out: dict[str, dict] = {}
    for label, subset in snapshot_rows(games):
        a = aggregate_hitting(subset)
        out[label] = {
            "fp": counting_fantasy_points(a),
            "ops": float(a["ops"]),
            "g": int(a["games"]),
            "pa": int(a["pa"]),
            "avg": float(a["avg"]),
        }
    return out


def metrics_for_pitching_games(games) -> dict[str, dict]:
    """Label -> pitch PP, K/BB/HR, rates, W/L (for display only) from snapshot windows."""
    out: dict[str, dict] = {}
    for label, subset in snapshot_rows(games):
        a = aggregate_pitching(subset)
        out[label] = {
            "pp": pitching_fantasy_points(a),
            "so": int(a["so"]),
            "bb": int(a["bb"]),
            "hr": int(a["hr"]),
            "g": int(a["games"]),
            "ip_outs": int(a["ip_outs"]),
            "ip": float(a["ip"]),
            "k9": float(a["k9"]),
            "bb9": float(a["bb9"]),
            "hr9": float(a["hr9"]),
            "whip": float(a["whip"]),
            "strike_pct": float(a["strike_pct"]),
            "strikes": int(a["strikes"]),
            "pitches": int(a["pitches"]),
            "wins": int(a["wins"]),
            "losses": int(a["losses"]),
            "er": int(a["er"]),
            "runs": int(a["runs"]),
            "hbp": int(a["hbp"]),
            "h": int(a["h"]),
            "era": float(a["era"]),
        }
    return out


def _hitting_stats_json(a: dict[str, float | int]) -> dict[str, float | int]:
    """JSON-serializable traditional hitting line from aggregate_hitting."""
    return {
        "g": int(a["games"]),
        "pa": int(a["pa"]),
        "ab": int(a["ab"]),
        "h": int(a["h"]),
        "1b": int(a["1b"]),
        "2b": int(a["2b"]),
        "3b": int(a["3b"]),
        "hr": int(a["hr"]),
        "r": int(a["r"]),
        "rbi": int(a["rbi"]),
        "bb": int(a["bb"]),
        "so": int(a["so"]),
        "hbp": int(a["hbp"]),
        "sb": int(a["sb"]),
        "cs": int(a["cs"]),
        "tb": int(a["tb"]),
        "avg": round(float(a["avg"]), 3),
        "obp": round(float(a["obp"]), 3),
        "slg": round(float(a["slg"]), 3),
        "ops": round(float(a["ops"]), 3),
    }


def _pitching_stats_json(a: dict[str, float | int]) -> dict[str, float | int]:
    """JSON-serializable traditional pitching line from aggregate_pitching."""
    return {
        "g": int(a["games"]),
        "ip_outs": int(a["ip_outs"]),
        "ip": round(float(a["ip"]), 3),
        "w": int(a["wins"]),
        "l": int(a["losses"]),
        "so": int(a["so"]),
        "bb": int(a["bb"]),
        "hr": int(a["hr"]),
        "h": int(a["h"]),
        "er": int(a["er"]),
        "runs": int(a["runs"]),
        "hbp": int(a["hbp"]),
        "pitches": int(a["pitches"]),
        "strikes": int(a["strikes"]),
        "k9": round(float(a["k9"]), 2),
        "bb9": round(float(a["bb9"]), 2),
        "hr9": round(float(a["hr9"]), 2),
        "whip": round(float(a["whip"]), 2),
        "era": round(float(a["era"]), 2),
        "strike_pct": round(float(a["strike_pct"]), 4),
    }


def metrics_for_games_full(games) -> dict[str, dict]:
    """Cut key (l1…season) -> { fp, stats } for app JSON."""
    out: dict[str, dict] = {}
    for label, subset in snapshot_rows(games):
        ck = LABEL_TO_CUT_KEY[label]
        a = aggregate_hitting(subset)
        out[ck] = {
            "fp": counting_fantasy_points(a),
            "stats": _hitting_stats_json(a),
        }
    return out


def metrics_for_pitching_games_full(games) -> dict[str, dict]:
    """Cut key (l1…season) -> { pp, stats } for app JSON."""
    out: dict[str, dict] = {}
    for label, subset in snapshot_rows(games):
        ck = LABEL_TO_CUT_KEY[label]
        a = aggregate_pitching(subset)
        out[ck] = {
            "pp": pitching_fantasy_points(a),
            "stats": _pitching_stats_json(a),
        }
    return out


def esc_cell(s: str) -> str:
    return (s or "").replace("|", "\\|")
