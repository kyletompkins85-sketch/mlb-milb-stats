"""Load unique players from 2025 Bowman Draft normalized checklist CSV."""

from __future__ import annotations

import csv
import re
from dataclasses import dataclass
from pathlib import Path

_BD_CARD = re.compile(r"^BD-(\d+)$", re.IGNORECASE)


def clean_player_name(raw: str) -> str:
    """Match cardlotlister `cardmatch.player_index._clean_player_name`."""
    return (raw or "").strip().rstrip(",").strip()


@dataclass(frozen=True)
class ChecklistPlayer:
    name: str
    affiliation: str


def load_bowman_draft_unique_players(
    checklist_csv: Path,
    *,
    base_bd_only: bool = False,
) -> list[ChecklistPlayer]:
    """
    Unique player names in first-seen order, with affiliation from the first row
    for each name.

    If ``base_bd_only`` is True, only rows whose ``card_number`` is **BD-1** … **BD-200**
    (200-card base checklist) are considered — **200 unique players** for 2025 Bowman Draft.
    If False, every row in the normalized file is considered (~220 unique names including inserts).
    """
    if not checklist_csv.is_file():
        raise FileNotFoundError(f"Checklist not found: {checklist_csv}")

    seen: set[str] = set()
    out: list[ChecklistPlayer] = []

    with checklist_csv.open(encoding="utf-8", newline="") as f:
        r = csv.DictReader(f)
        if not r.fieldnames or "player_name_raw" not in r.fieldnames:
            raise ValueError(f"Expected player_name_raw column in {checklist_csv}")
        for row in r:
            if base_bd_only:
                cn = (row.get("card_number") or "").strip()
                m = _BD_CARD.match(cn)
                if not m:
                    continue
                num = int(m.group(1))
                if num < 1 or num > 200:
                    continue
            nm = clean_player_name(row.get("player_name_raw") or "")
            if not nm or nm in seen:
                continue
            seen.add(nm)
            aff = (row.get("affiliation_raw") or "").strip()
            out.append(ChecklistPlayer(name=nm, affiliation=aff))

    return out
