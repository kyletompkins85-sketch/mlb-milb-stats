# Bowman Draft app JSON (static files)

The batch script [`scripts/bowman_export_app_json.py`](../scripts/bowman_export_app_json.py) writes three files for mobile/web clients:

| File | Purpose |
|------|---------|
| `meta.json` | Schema version, `generated_at`, season, scope, counts, ranking rules, cut labels |
| `hitters.json` | `leaderboards` per cut (`l1` … `season`); each array is **pre-sorted** by `fp` (no client sort) |
| `pitchers.json` | Same for pitchers using `pp` |

## Generate locally

From the repo root (with `PYTHONPATH=scripts` or `cd` into `scripts` on `PATH`):

```bash
PYTHONPATH=scripts python3 scripts/bowman_export_app_json.py \
  --season 2026 \
  --no-search --draft-year 0 \
  --out-dir dist/bowman-app
```

- **`--base-only`**: BD-1…BD-200 checklist only.
- **`--compact`**: minified JSON (smaller over the wire).
- **`--checklist`**: path to `2025_Bowman_Draft_Normalized.csv` if not using the default sibling [`cardlotlister-oauth`](../scripts/bowman_report_common.py) layout.

Output is **overwritten** each run (`meta.json`, `hitters.json`, `pitchers.json`). The `dist/` directory is gitignored.

## App URLs (GitHub Pages)

After you enable **GitHub Pages** on the **`gh-pages`** branch (root), files are served at:

- `https://<owner>.github.io/<repo>/meta.json`
- `https://<owner>.github.io/<repo>/hitters.json`
- `https://<owner>.github.io/<repo>/pitchers.json`

Load `meta.json` first; use `generated_at` and `schema_version` to decide whether to refresh. Render leaderboards by iterating each cut’s array **in order** (no sorting).

## CI ID resolution (`--no-search`)

The deploy workflow runs the exporter with **`--no-search`**, so MLBAM IDs come only from **`data/bowman_2025_mlbam_overrides.json`** and **`data/bowman_mlbam_id_cache.json`**. The cache file is **tracked in git** (whitelisted in `.gitignore`) so CI matches local resolution for names you have already resolved (e.g. via search or bulk scripts). After resolving new players locally, commit updates to **`bowman_mlbam_id_cache.json`** (and/or overrides) before expecting them in published JSON.

## CI checklist path

The default [`default_checklist_path`](../scripts/bowman_report_common.py) expects the normalized CSV next to this repo (`../cardlotlister-oauth/...`). In GitHub Actions, add a **second** `actions/checkout` for that repository into `cardlotlister-oauth/` under the workspace, **or** pass `--checklist` to a CSV committed or downloaded in this repo.

Set the repository in workflow via the `CHECKLIST_REPO` secret (`org/repo` string), or edit the workflow to match your layout. If that repository is **private**, add a read-scoped PAT as `CHECKLIST_PAT` and pass `token: ${{ secrets.CHECKLIST_PAT }}` to the second checkout step in [`.github/workflows/deploy-bowman-app-json.yml`](../.github/workflows/deploy-bowman-app-json.yml).

Optional repository variable **`STATS_SEASON`** overrides the default season (`2026`) in the workflow export step.

## Retention

Do **not** commit daily JSON to `main` to avoid history bloat. The provided workflow deploys only to **`gh-pages`** (overwrite). Keep `main` free of generated snapshots.
