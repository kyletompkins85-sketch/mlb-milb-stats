"""Resolve checklist display names to MLBAM person IDs (search + cache + overrides)."""

from __future__ import annotations

import json
import re
import time
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from mlb_game_logs import BASE, get_json

CACHE_VERSION = 1


def _norm_whitespace(s: str) -> str:
    return " ".join((s or "").split())


def draft_pick_key(full_name: str, team_name: str) -> tuple[str, str]:
    """Lowercase (name, team) for matching checklist rows to /draft/{year} picks."""
    return (_norm_whitespace(full_name).lower(), _norm_whitespace(team_name).lower())


def fetch_draft_name_team_lookup(year: int, *, sleep_s: float = 0.0) -> dict[tuple[str, str], int]:
    """
    Load all picks from Stats API ``GET /draft/{year}`` and map
    (player fullName, drafting team name) → MLBAM person id.

    One HTTP call. Use this when ``people/search`` misses very new draftees but the
    draft feed already lists them with ids.
    """
    if sleep_s > 0:
        time.sleep(sleep_s)
    url = f"{BASE}/draft/{year}"
    data = get_json(url)
    drafts = data.get("drafts")
    if not isinstance(drafts, dict):
        return {}
    rounds = drafts.get("rounds")
    if not isinstance(rounds, list):
        return {}
    out: dict[tuple[str, str], int] = {}
    for rnd in rounds:
        if not isinstance(rnd, dict):
            continue
        picks = rnd.get("picks")
        if not isinstance(picks, list):
            continue
        for pick in picks:
            if not isinstance(pick, dict):
                continue
            person = pick.get("person")
            team = pick.get("team")
            if not isinstance(person, dict) or not isinstance(team, dict):
                continue
            fn = person.get("fullName")
            tid = person.get("id")
            tname = team.get("name")
            if not isinstance(fn, str) or not fn.strip():
                continue
            if tid is None:
                continue
            if not isinstance(tname, str) or not tname.strip():
                continue
            try:
                pid = int(tid)
            except (TypeError, ValueError):
                continue
            key = draft_pick_key(fn, tname)
            if key in out and out[key] != pid:
                # Extremely rare; keep first id for determinism.
                continue
            out[key] = pid
    return out


def lookup_id_from_draft(
    name: str,
    affiliation: str,
    draft_lookup: dict[tuple[str, str], int],
) -> int | None:
    """Match cleaned checklist name + affiliation to a draft pick."""
    aff = _norm_whitespace(affiliation)
    if not aff or aff == "—":
        return None
    key = draft_pick_key(name, aff)
    return draft_lookup.get(key)


@dataclass
class ResolveResult:
    person_id: int | None
    source: str  # override | cache | draft | search | unresolved
    detail: str


def _load_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    with path.open(encoding="utf-8") as f:
        data = json.load(f)
    return data if isinstance(data, dict) else {}


def load_overrides(path: Path) -> dict[str, int]:
    raw = _load_json(path)
    out: dict[str, int] = {}
    for k, v in raw.items():
        if isinstance(k, str) and isinstance(v, int):
            out[k.strip()] = v
        elif isinstance(k, str) and isinstance(v, str) and v.isdigit():
            out[k.strip()] = int(v)
    return out


def load_cache(path: Path) -> dict[str, dict[str, Any]]:
    raw = _load_json(path)
    if not raw:
        return {}
    if raw.get("_version") != CACHE_VERSION:
        return {}
    players = raw.get("players")
    if not isinstance(players, dict):
        return {}
    return {str(k): v for k, v in players.items() if isinstance(v, dict)}


def save_cache(path: Path, cache: dict[str, dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"_version": CACHE_VERSION, "players": cache}
    with path.open("w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, sort_keys=True)
        f.write("\n")


def search_people_by_name(full_name: str, sleep_s: float = 0.12) -> list[dict[str, Any]]:
    """Call Stats API people search; return people list."""
    q = urllib.parse.urlencode({"names": full_name})
    url = f"https://statsapi.mlb.com/api/v1/people/search?{q}"
    time.sleep(sleep_s)
    data = get_json(url)
    people = data.get("people")
    if not isinstance(people, list):
        return []
    return [p for p in people if isinstance(p, dict)]


def search_name_variants(canonical_name: str) -> list[str]:
    """
    Try these in order when the first search returns no hits.
    Handles checklist punctuation (commas) and common suffixes.
    """
    n = (canonical_name or "").strip().rstrip(",").strip()
    out: list[str] = []

    def add(x: str) -> None:
        x = (x or "").strip().rstrip(",").strip()
        if x and x not in out:
            out.append(x)

    add(n)
    # "Last, Jr." style
    add(re.sub(r",?\s*Jr\.?$", "", n, flags=re.I).strip())
    add(re.sub(r",?\s*Sr\.?$", "", n, flags=re.I).strip())
    for suf in (" III", " II", " IV"):
        if n.endswith(suf):
            add(n[: -len(suf)].strip())
    return out


def pick_best_person(people: list[dict[str, Any]], query_name: str) -> dict[str, Any] | None:
    if not people:
        return None
    if len(people) == 1:
        return people[0]

    qn = query_name.lower().strip()
    # Prefer exact fullName match
    exact = [p for p in people if (p.get("fullName") or "").strip().lower() == qn]
    if len(exact) == 1:
        return exact[0]
    if len(exact) > 1:
        people = exact

    # Prefer active players
    active = [p for p in people if p.get("active") is True]
    if active:
        people = active

    # Prefer isPlayer
    players_only = [p for p in people if p.get("isPlayer") is True]
    if players_only:
        people = players_only

    # Deterministic: lowest id
    return sorted(people, key=lambda p: int(p.get("id") or 0))[0]


def resolve_name(
    name: str,
    *,
    overrides: dict[str, int],
    cache: dict[str, dict[str, Any]],
    use_search: bool,
    sleep_s: float,
    affiliation: str | None = None,
    draft_lookup: dict[tuple[str, str], int] | None = None,
) -> ResolveResult:
    if name in overrides:
        return ResolveResult(overrides[name], "override", "")

    cached = cache.get(name)
    if cached and isinstance(cached.get("id"), int):
        return ResolveResult(int(cached["id"]), "cache", cached.get("note") or "")

    if draft_lookup:
        pid = lookup_id_from_draft(name, affiliation or "", draft_lookup)
        if pid is not None:
            return ResolveResult(pid, "draft", "matched Stats API draft feed (name + team)")

    if not use_search:
        return ResolveResult(None, "unresolved", "not in cache/overrides and search disabled")

    tried: list[str] = []
    for vn in search_name_variants(name):
        tried.append(vn)
        people = search_people_by_name(vn, sleep_s=sleep_s)
        best = pick_best_person(people, vn)
        if best is None:
            continue
        pid = int(best["id"])
        note = f"n_candidates={len(people)}"
        if vn != name.strip().rstrip(",").strip():
            note += f"; matched_variant={vn!r}"
        return ResolveResult(pid, "search", note)

    return ResolveResult(
        None,
        "unresolved",
        "search returned 0 for all variants: " + ", ".join(repr(t) for t in tried),
    )


def merge_into_cache(
    cache: dict[str, dict[str, Any]],
    name: str,
    person_id: int,
    source: str,
    detail: str,
) -> None:
    cache[name] = {
        "id": person_id,
        "source": source,
        "note": detail,
    }
