# MLB Stats API — research notes

**Base URL:** `https://statsapi.mlb.com/api/{ver}/...`  
**Common version:** `v1` (e.g. `https://statsapi.mlb.com/api/v1/sports`)

This is the same **Stats API** used by MLB web and mobile experiences. It returns JSON. There is **no official public developer portal** with guaranteed stability; the community documents behavior by exploration. The [toddrob99/MLB-StatsAPI](https://github.com/toddrob99/MLB-StatsAPI) Python wrapper maintains an [Endpoints wiki](https://github.com/toddrob99/MLB-StatsAPI/wiki/Endpoints) that tracks paths and query parameters.

## Important disclaimers

- **Not an official product name** — “MLB Stats API” is the usual shorthand for `statsapi.mlb.com`.
- **Terms:** Each response includes copyright text; see http://gdx.mlb.com/components/copyright.txt before running large or commercial-style automation.
- **Rate limiting:** Be polite (cache responses, backoff on errors). Undocumented limits may exist.

## Core concepts

### `ver`

Path segment, almost always `v1`.

### `fields`

Optional query parameter to **prune** the JSON to specific keys (reduces payload size). Format is documented in community guides; experiment with small requests first.

### `hydrate`

On some endpoints, asks the API to **embed** related objects (e.g. roster + person details). Exact hydrate tokens vary by endpoint; the wrapper wiki and trial-and-error are the practical references.

### Meta lookups

**`GET /api/v1/meta/{type}`** — Valid `type` values include: `statGroups`, `statTypes`, `gameTypes`, `positions`, `standingsTypes`, `situationCodes`, and others. Use these to discover **legal values** for `group`, `stats`, etc. on stats endpoints.

Example:

```http
GET https://statsapi.mlb.com/api/v1/meta/statTypes
GET https://statsapi.mlb.com/api/v1/meta/statGroups
```

### Sports and MiLB

**`GET /api/v1/sports`** — Lists sports/league levels with `id`, `name`, `code` (e.g. MLB vs Triple-A vs Double-A). You filter many queries with **`sportId`** (or `sportIds`) to separate MLB from affiliated minors.

MiLB coverage is generally accessed **through the same host** by choosing the appropriate `sportId` / team / season, not a different API domain. Exact coverage for every minor level can still require spot-checking responses for your season.

## Endpoints most relevant to “who’s hot”

| Area | Endpoint pattern | Notes |
|------|------------------|--------|
| Leaderboards | `/api/v1/stats/leaders` | `leaderCategories`, `season`, `leagueId`, `sportId`, `limit`, etc. |
| Custom stat queries | `/api/v1/stats` | Requires `stats` + `group`; default **limit 50** if omitted. Supports `season`, `sportIds`, `teamId`, `gameType`, date ranges, sorting. |
| Streaks | `/api/v1/stats/streaks` | `streakType`, `streakSpan`, `season`, `sportId`, `limit`. |
| People | `/api/v1/people/{personId}` | Bio, current team context; use `hydrate` for related data. |
| Team roster | `/api/v1/teams/{teamId}/roster` | `season`, `rosterType`, `date`. |
| Schedule | `/api/v1/schedule` | Games for a date range; `sportId`, `teamId`, `hydrate`. |
| Standings | `/api/v1/standings` | `leagueId`, `season`, etc. |

### Stats endpoint (high level)

From the community wiki:

- **URL:** `https://statsapi.mlb.com/api/v1/stats`
- **Required:** `stats` and `group` (look up allowed values via `meta(statTypes)` / `meta(statGroups)`).
- **Default:** If `limit` is omitted, responses may cap at **50** rows.

### Leaders endpoint

- **URL:** `https://statsapi.mlb.com/api/v1/stats/leaders`
- **Required:** `leaderCategories` (and usually `season` for seasonal leaders).

## Tools and libraries (optional)

- **[toddrob99/MLB-StatsAPI](https://github.com/toddrob99/MLB-StatsAPI)** — Python wrapper; good for discovering calling patterns.
- **[PyMLB StatsAPI](https://pymlb-statsapi.readthedocs.io/)** — Alternative Python client with schema-oriented docs.

Using `requests` + raw URLs is fine for learning and small scripts.

## Further reading

- Endpoints wiki (unofficial): https://github.com/toddrob99/MLB-StatsAPI/wiki/Endpoints  
- Copyright notice referenced in API payloads: http://gdx.mlb.com/components/copyright.txt  
