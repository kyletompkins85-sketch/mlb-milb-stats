# MLB / MiLB stats (data pulls)

Scratchpad for pulling baseball stats so you can analyze **who is hot** (MLB and MiLB prospects), with an eye toward daily or periodic reports later.

## Layout

| Path | Purpose |
|------|---------|
| `docs/` | Research notes (APIs, parameters, caveats) |
| `scripts/` | Small fetch / probe scripts |
| `data/` | Local JSON/CSV output (gitignored by default) |

## Quick start

```bash
cd mlb-milb-stats
python3 -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
python scripts/smoke_fetch.py
```

### Rolling snapshots (game log → 1 / 3 / 5 / 10 / 30 / full season)

Defaults to **Eli Willits** (`personId` 816113). Writes markdown under `data/` and prints the same to stdout.

```bash
python scripts/player_snapshots_report.py
python scripts/player_snapshots_report.py --season 2026 --person-id 816113 --name "Eli Willits"
```

### Head-to-head scorecard (counting points + OPS by window)

Compares two players on the same snapshot windows. Default is **JoJo Parker vs Eli Willits**; FP uses counting stats only (weights are documented in the markdown).

```bash
python scripts/compare_snapshots_scorecard.py --season 2026
python scripts/compare_snapshots_scorecard.py --a-id 828098 --a-name "JoJo Parker" --b-id 816113 --b-name "Eli Willits"
```

### Bowman 2025 Draft — full checklist batch report

Reads **`cardlotlister-oauth/data/checklists/normalized/2025_Bowman_Draft_Normalized.csv`** (sibling repo), resolves **~220 unique names** to MLBAM IDs via **`data/bowman_2025_mlbam_overrides.json`** → **`data/bowman_mlbam_id_cache.json`** (auto-filled from API search) → Stats API, then writes a **summary markdown** table (season / last 5 / last 1 FP + OPS).

```bash
# Default checklist path: ../cardlotlister-oauth/.../2025_Bowman_Draft_Normalized.csv
python scripts/bowman_draft_snapshot_report.py --season 2026

# Dry-run ID resolution only (no cache writes); limit players for testing
python scripts/bowman_draft_snapshot_report.py --season 2026 --limit 15 --no-save-cache

# Huge appendix: per-player snapshot tables like the single-player report
python scripts/bowman_draft_snapshot_report.py --season 2026 --detail
```

Add missing IDs to **`data/bowman_2025_mlbam_overrides.json`** as `"Player Name": 123456` when search returns no results. Re-run to refresh stats.

### Bowman — FP scorecard rankings (full checklist rows)

Same FP formula as **`compare_snapshots_scorecard.py`**. The **full leaderboard** lists **every** checklist player: resolved names get FP columns; unresolved names get **—** until you add MLBAM IDs (overrides) or search succeeds. **Window rankings** (Last 1 … full season) include **resolved IDs only**.

- **`--base-only`** — only **BD-1…BD-200** (exactly **200** base names). Omit for **~220** names (inserts included).
- **Do not use `--limit`** for a full run — `--limit` was only for quick tests (that is why a short run showed only a handful of rows).

```bash
# All 200 base players (recommended for “the whole set”)
python scripts/bowman_scorecard_rankings_report.py --season 2026 --base-only

# ~220 names including inserts (longer run)
python scripts/bowman_scorecard_rankings_report.py --season 2026
```

Writes **`data/bowman_scorecard_rankings_{season}_base200_{date}.md`** or **`..._all_{date}.md`**. Full run can take many minutes (search + stats per player).

### Checklist → MLBAM ID table (no stats)

One row per checklist player: **Found** (Yes/No), **MLBAM ID**, **Source** (override / cache / search / unresolved). Does not pull game logs — good for auditing who still needs an ID. Writes markdown + CSV under `data/`.

```bash
python scripts/bowman_checklist_ids_report.py --base-only
python scripts/bowman_checklist_ids_report.py --base-only --no-csv
```

Use default search to fill IDs (slow once); use **`--no-search`** to only show overrides + existing cache.

### Bulk resolve (genuine API pass for the whole checklist)

Runs **Stats API search** for every name (with **variant names**: commas, Jr./Sr., II/III/IV), updates **`bowman_mlbam_id_cache.json`**, and with **`--write-overrides`** merges all discovered IDs into **`bowman_2025_mlbam_overrides.json`**. Takes a few minutes for 200 players.

```bash
python scripts/bowman_bulk_resolve_ids.py --base-only --write-overrides
```

Anyone still **unresolved** after this is usually **not findable** via `people/search` (not in MLB’s index yet, or spelling differs from MiLB.com) — look up the ID on MiLB/MLB and add it to the overrides JSON by hand.

### Checklist export (IDs merged into a copy of the CSV)

Creates **`data/bowman_2025_checklist_with_ids.csv`** — same rows as the cardlotlister normalized checklist, but **drops** `set_key`, `year`, `brand`, `product`, `section`, and `section_card_count`; adds **`mlbam_id`** (first column), **`id_source`** (`override` / `cache` / `none`), and **`id_resolved`** (`yes` / `no`). Also writes **`data/bowman_2025_checklist_with_ids_summary.md`** (one line per **unique** player). Re-run after updating overrides or cache.

```bash
python scripts/bowman_export_checklist_with_ids.py
# Only rows still missing an ID:
python scripts/bowman_export_checklist_with_ids.py --missing-only
```

## MLB Stats API

The public JSON API at `statsapi.mlb.com` is what MLB’s own sites use. It is **not** a published, versioned product with a formal SLA; treat it as stable enough for hobby analysis but subject to change.

See **`docs/research-mlb-stats-api.md`** for base URL, key endpoints, MiLB via `sportId`, and links to community references.

## Legal / terms

Responses include a `copyright` field and point to MLB’s terms. Read them before heavy automated use:  
http://gdx.mlb.com/components/copyright.txt
