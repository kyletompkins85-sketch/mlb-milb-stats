"""Shared MLB Stats API helpers: game logs, aggregation, snapshot windows."""

from __future__ import annotations

import json
import urllib.parse
import urllib.request
from dataclasses import dataclass

BASE = "https://statsapi.mlb.com/api/v1"
# MiLB levels + MLB; game logs may live under one sportId depending on assignment.
SPORT_IDS_PROBE = (1, 11, 12, 13, 14, 16)
SNAPSHOT_WINDOWS = (1, 3, 5, 10, 30)


def _int(v: object) -> int:
    if v is None:
        return 0
    if isinstance(v, bool):
        return int(v)
    if isinstance(v, int):
        return v
    if isinstance(v, float):
        return int(v)
    if isinstance(v, str):
        v = v.strip()
        if not v or v in ("-.--", "-"):
            return 0
        try:
            return int(float(v))
        except ValueError:
            return 0
    return 0


@dataclass
class GameLine:
    game_pk: int
    game_date: str
    opponent: str
    is_home: bool | None
    stat: dict


def get_json(url: str) -> dict:
    req = urllib.request.Request(
        url,
        headers={"User-Agent": "mlb-milb-stats/0.1"},
    )
    with urllib.request.urlopen(req, timeout=45) as resp:
        return json.loads(resp.read().decode())


def _is_pitcher_person(p: dict) -> bool | None:
    """Stats API primaryPosition.code ``1`` = pitcher."""
    pos = p.get("primaryPosition")
    if not isinstance(pos, dict):
        return None
    code = pos.get("code")
    if code is None:
        return None
    return str(code) == "1"


def fetch_primary_is_pitcher(person_id: int) -> bool | None:
    """Single ``GET /people/{id}`` — use before pulling pitching logs to skip hitters cheaply."""
    url = f"{BASE}/people/{person_id}"
    try:
        data = get_json(url)
    except OSError:
        return None
    people = data.get("people") or []
    if not people:
        return None
    return _is_pitcher_person(people[0])


def _fetch_game_logs_for_group(
    person_id: int, season: int, group: str
) -> tuple[str | None, list[GameLine], bool | None]:
    """Merge gameLog splits across sportIds for ``hitting`` or ``pitching``."""
    by_pk: dict[int, GameLine] = {}
    current_team: str | None = None
    is_pitcher: bool | None = None

    for sport_id in SPORT_IDS_PROBE:
        hydrate = (
            f"stats(group=[{group}],type=gameLog,season={season},sportId={sport_id}),"
            "currentTeam"
        )
        params = urllib.parse.urlencode({"hydrate": hydrate})
        url = f"{BASE}/people/{person_id}?{params}"
        data = get_json(url)
        people = data.get("people") or []
        if not people:
            continue
        p = people[0]
        if is_pitcher is None:
            is_pitcher = _is_pitcher_person(p)
        if current_team is None and p.get("currentTeam"):
            current_team = (p.get("currentTeam") or {}).get("name")
        for block in p.get("stats") or []:
            for sp in block.get("splits") or []:
                g = sp.get("game") or {}
                pk = g.get("gamePk")
                if pk is None:
                    continue
                pk = int(pk)
                opp = (sp.get("opponent") or {}).get("name") or "?"
                gd = sp.get("date") or ""
                ih = sp.get("isHome")
                if isinstance(ih, str):
                    ih = ih.lower() == "true"
                st = sp.get("stat") or {}
                if pk not in by_pk:
                    by_pk[pk] = GameLine(
                        game_pk=pk,
                        game_date=gd,
                        opponent=opp,
                        is_home=ih,
                        stat=st,
                    )

    games = sorted(by_pk.values(), key=lambda x: (x.game_date, x.game_pk))
    return current_team, games, is_pitcher


def fetch_game_logs(
    person_id: int, season: int
) -> tuple[str | None, list[GameLine], bool | None]:
    """Merge **hitting** gameLog splits across sportIds; dedupe by gamePk.

    Returns ``(current_team_name, games, is_pitcher)``. ``is_pitcher`` is set from the
    first successful ``people`` payload (``None`` if no row was returned).
    """
    return _fetch_game_logs_for_group(person_id, season, "hitting")


def fetch_pitching_game_logs(
    person_id: int, season: int
) -> tuple[str | None, list[GameLine], bool | None]:
    """Merge **pitching** gameLog splits across sportIds; dedupe by gamePk."""
    return _fetch_game_logs_for_group(person_id, season, "pitching")


def innings_to_outs(ip_val: object) -> int:
    """Convert ``inningsPitched`` to outs. API strings like ``5.1`` = 5⅓ IP → 16 outs."""
    if ip_val is None:
        return 0
    if isinstance(ip_val, (int, float)):
        x = float(ip_val)
        if abs(x) < 1e-9:
            return 0
        return int(round(x * 3))
    s = str(ip_val).strip()
    if not s or s in ("-.--", "-", "0", "0.0"):
        return 0
    if "." not in s:
        try:
            return int(float(s)) * 3
        except ValueError:
            return 0
    whole_s, frac_s = s.split(".", 1)
    whole = int(whole_s) if whole_s else 0
    if not frac_s:
        return whole * 3
    d = int(frac_s[0])
    if d > 2:
        d = 2
    return whole * 3 + d


def outs_to_ip_display(outs: int) -> str:
    return f"{outs // 3}.{outs % 3}"


def aggregate_pitching(games: list[GameLine]) -> dict[str, float | int]:
    """Sum pitching game-log stats; recompute K/9, BB/9, HR/9, WHIP, ERA, strike rate."""
    so = bb = hr = h = er = wins = losses = runs = hbp = 0
    strikes = pitches = 0
    outs = 0
    for g in games:
        s = g.stat
        so += _int(s.get("strikeOuts"))
        bb += _int(s.get("baseOnBalls")) + _int(s.get("intentionalWalks"))
        hr += _int(s.get("homeRuns"))
        h += _int(s.get("hits"))
        er += _int(s.get("earnedRuns"))
        runs += _int(s.get("runs"))
        wins += _int(s.get("wins"))
        losses += _int(s.get("losses"))
        strikes += _int(s.get("strikes"))
        pitches += _int(s.get("numberOfPitches"))
        hbp += _int(s.get("hitBatsmen")) + _int(s.get("hitByPitch"))
        outs += innings_to_outs(s.get("inningsPitched"))
    ip = outs / 3.0 if outs else 0.0
    k9 = 9.0 * so / ip if ip else 0.0
    bb9 = 9.0 * bb / ip if ip else 0.0
    hr9 = 9.0 * hr / ip if ip else 0.0
    whip = (h + bb) / ip if ip else 0.0
    strike_pct = (strikes / pitches) if pitches else 0.0
    era = 9.0 * er / ip if ip else 0.0
    return {
        "games": len(games),
        "so": so,
        "bb": bb,
        "hr": hr,
        "h": h,
        "er": er,
        "runs": runs,
        "hbp": hbp,
        "wins": wins,
        "losses": losses,
        "strikes": strikes,
        "pitches": pitches,
        "ip_outs": outs,
        "ip": ip,
        "k9": k9,
        "bb9": bb9,
        "hr9": hr9,
        "whip": whip,
        "strike_pct": strike_pct,
        "era": era,
    }


def pitching_fantasy_points(a: dict[str, float | int]) -> int:
    """
    K / BB / HR–focused counting score (**wins excluded**).

    ``PP = 3×SO − 2×BB − 4×HR + floor(IP in full innings)`` — small volume bonus.
    """
    k = int(a["so"])
    bb = int(a["bb"])
    hr = int(a["hr"])
    outs = int(a["ip_outs"])
    return 3 * k - 2 * bb - 4 * hr + outs // 3


def aggregate_hitting(games: list[GameLine]) -> dict[str, float | int]:
    """Sum counting stats; recompute AVG/OBP/SLG/OPS from totals."""
    ab = h = doubles = triples = hr = 0
    bb = hbp = sf = 0
    so = tb = rbi = 0
    sb = cs = pa = 0
    runs = 0
    for g in games:
        s = g.stat
        ab += _int(s.get("atBats"))
        h += _int(s.get("hits"))
        doubles += _int(s.get("doubles"))
        triples += _int(s.get("triples"))
        hr += _int(s.get("homeRuns"))
        bb += _int(s.get("baseOnBalls"))
        bb += _int(s.get("intentionalWalks"))
        hbp += _int(s.get("hitByPitch"))
        sf += _int(s.get("sacFlies"))
        so += _int(s.get("strikeOuts"))
        tb += _int(s.get("totalBases"))
        rbi += _int(s.get("rbi"))
        sb += _int(s.get("stolenBases"))
        cs += _int(s.get("caughtStealing"))
        pa += _int(s.get("plateAppearances"))
        runs += _int(s.get("runs"))

    singles = h - doubles - triples - hr
    if singles < 0:
        singles = 0

    avg = h / ab if ab else 0.0
    obp_denom = ab + bb + hbp + sf
    obp = (h + bb + hbp) / obp_denom if obp_denom else 0.0
    slg = tb / ab if ab else 0.0
    ops = obp + slg

    return {
        "games": len(games),
        "pa": pa,
        "ab": ab,
        "h": h,
        "1b": singles,
        "2b": doubles,
        "3b": triples,
        "hr": hr,
        "bb": bb,
        "so": so,
        "hbp": hbp,
        "sb": sb,
        "cs": cs,
        "tb": tb,
        "rbi": rbi,
        "r": runs,
        "avg": avg,
        "obp": obp,
        "slg": slg,
        "ops": ops,
    }


def counting_fantasy_points(a: dict[str, float | int]) -> int:
    """
    Single integer from counting stats only (no rate stats).

    Weights (common points-league style): 1B=3, 2B=5, 3B=8, HR=10, BB=1, HBP=1,
    SB=2, CS=-1, RBI=1, R=1.
    """
    s1 = int(a["1b"])
    s2 = int(a["2b"])
    s3 = int(a["3b"])
    hr = int(a["hr"])
    bb = int(a["bb"])
    hbp = int(a["hbp"])
    sb = int(a["sb"])
    cs = int(a["cs"])
    rbi = int(a["rbi"])
    r = int(a["r"])
    return (
        3 * s1
        + 5 * s2
        + 8 * s3
        + 10 * hr
        + bb
        + hbp
        + 2 * sb
        - cs
        + rbi
        + r
    )


def fmt_rate(x: float) -> str:
    """Three-decimal display (e.g. 0.305 -> .305, 1.052 -> 1.052)."""
    s = f"{x:.3f}"
    if s.startswith("0.") and x < 1.0:
        return s[1:]
    return s


def snapshot_rows(games: list[GameLine]) -> list[tuple[str, list[GameLine]]]:
    out: list[tuple[str, list[GameLine]]] = []
    for n in SNAPSHOT_WINDOWS:
        if len(games) == 0:
            out.append((f"Last {n} games", []))
            continue
        take = min(n, len(games))
        out.append((f"Last {n} games", games[-take:]))
    out.append(("Full season (game log)", games))
    return out
