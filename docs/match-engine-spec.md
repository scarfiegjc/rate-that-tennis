# Match Engine — Frontend & API Specification

> This is the authoritative spec for the match engine page UI and the API that powers it.
> For rating computation, see `docs/ratings-spec.md`. For project overview, see `CLAUDE.md`.

---

## Page structure

The match engine is a single-page view at `/match/{match_id}`. It has two zones:

1. **Match header** — always visible, above the fold. Contains the core prediction and edge.
2. **Tab panel** — five tabs of depth, switching below the header.

```
┌─────────────────────────────────────────────────────────────┐
│  MATCH HEADER (sticky / always visible)                     │
│  Tournament · Surface · Round · Date                        │
│  [Player 1]    42% ████░░░░░░ 58%    [Player 2]            │
│  Market odds · Implied prob · Model edge · Confidence       │
└─────────────────────────────────────────────────────────────┘
┌────────────────────────────────────────────────────────────┐
│  Overview │ Form │ Head to head │ Serve │ Intelligence      │
├────────────────────────────────────────────────────────────┤
│  [Active tab content]                                       │
└────────────────────────────────────────────────────────────┘
```

---

## Match header — data requirements

| Field | Source | Notes |
|---|---|---|
| Tournament name | `tournaments.name` | |
| Surface | `surfaces.name` | |
| Round | `matches.tournament_round` | |
| Event date / time | `matches.event_date`, `matches.event_time` | |
| Player 1 name, country, flag | `players.name`, `players.country_code` | |
| Player 1 current ranking | External rank feed or `player_ratings` | |
| Player 1 form dots (last 5) | Last 5 rows from `v_player_form` match history | W/L only |
| Player 1 prediction probability | `model_predictions.prob_first_player` | |
| Player 2 (same fields) | As above | |
| Decimal odds P1 / P2 | `bookmaker_odds` (latest row per player per match) | |
| Implied probability | Computed: `1 / decimal_odds`, overround-adjusted | |
| Model edge | `model_predictions.prob_X - implied_prob_X` | Shown if abs > 2% |
| Confidence | `model_predictions.confidence` | `high`/`medium`/`low` |

**Edge display logic:**
- Edge ≥ +5%: show green badge "**+N% on [Player]**"
- Edge +2%–4%: show muted green badge
- Edge < 2% either direction: show neutral "Market aligned"
- Edge < -3% (market strongly disagrees with model): show amber "Review"

---

## Tab 1 — Overview

### Skill radar (spider chart)

Six-axis Chart.js radar comparing both players. Axes:

| Axis | Source field |
|---|---|
| Serve | `player_ratings.serve_rating` |
| Return | `player_ratings.return_rating` |
| Surface form | Surface-specific rating for current match surface |
| BP conversion | Component of `return_rating` — expose separately if available |
| Mental | `player_ratings.pressure_rating` |
| Consistency | `player_ratings.consistency_rating` |

Radar min: 40, max: 100. Both players shown as overlapping polygons in their brand colours.

### Stat comparison bars

Horizontal bar comparison — player 1 bar grows left, player 2 bar grows right from a
centre label. Four switchable datasets:

| Dataset key | Description |
|---|---|
| `overall` | All surfaces, trailing 52 weeks |
| `surface` | Current match surface only |
| `top20` | Matches vs top-20 opponents only |
| `last20` | Most recent 20 matches regardless of surface |

Metrics shown (6 rows):

| Metric | Computation |
|---|---|
| 1st serve % | Rolling weighted average of `w_1stIn / w_svpt` |
| Aces / match | Rolling weighted average of `w_ace / w_SvGms` |
| Break pt conversion | Rolling weighted average of `(l_bpFaced - l_bpSaved) / l_bpFaced` |
| Return pts won | Rolling weighted average of derived `return_pts_won_pct` |
| Tiebreaks won | Win rate in tiebreaks, parsed from score strings |
| Games won % | Rolling weighted average of `games_won_pct` |

**API:** all six metrics pre-computed and stored, not computed at query time.

---

## Tab 2 — Form

### Performance index line chart

- X axis: last 15 matches (or last N with surface filter applied), oldest left
- Y axis: `form_rating` per match (from `player_ratings_history` or a per-match index)
- Two series: Player 1 and Player 2
- Both players' charts share the same X axis (aligned to their respective recent matches —
  they won't necessarily have played the same opponents)

**Surface switcher:** All / Clay / Hard / Grass — filters to matches on each surface only.
When filtered, X axis shows only matches on that surface.

**API:** `GET /players/{id}/form?surface=clay&limit=15`
Returns: `[{ match_id, date, opponent_name, opponent_rank, won, performance_index, surface }]`

### Summary cards (below chart)

Three metric cards auto-computed from the form data:
- Average performance index (last 15)
- Momentum delta (last 5 avg minus last 10 avg)
- Win rate (last 15)

---

## Tab 3 — Head to head

### All-time record

- Total wins: P1 vs P2 from `matches` table where both player IDs appear
- Surface breakdown: count wins by surface (join via `tournaments.surface_id`)
- Rendered as: big win count numbers + mini horizontal bars per surface

### Recent meetings list

Up to 10 most recent H2H matches, each showing:
- Winner indicator dot (coloured by player)
- Score string (formatted from `match_scores`)
- Tournament name + round + surface badge
- Date

**API:** `GET /players/{p1_id}/h2h/{p2_id}`
Returns: `{ summary: { p1_wins, p2_wins, by_surface: {...} }, matches: [...] }`

---

## Tab 4 — Serve

### Serve placement zones

Three zones per service box: **Wide**, **Body**, **T**.

Displayed as a 1×3 coloured tile grid (representing the service box from above).
Colour intensity indicates frequency: light = rare, vivid = dominant zone.

**Three independent switchers:**
- Player: Player 1 / Player 2
- Serve number: 1st serve / 2nd serve
- Court side: Deuce court / Ad court

**Colour intensity thresholds** (using player brand colour at varying opacity):

| % of serves | Shade stop |
|---|---|
| < 25% | 50 (very light) |
| 25–35% | 100 |
| 35–45% | 200 |
| > 45% | 400 (vivid) |

### Serve stats cards (beside zones)

- Serve in % (1st or 2nd, whichever is selected)
- Average speed (show as "~N km/h" — estimated from ace rate and surface if Hawk-Eye unavailable)
- Aces per match

### Data availability note

Serve zone placement data comes from the **Jeff Sackmann Match Charting Project**, which
is already ingested by `pipeline/sackmann_ingest.py --job charting`. The charting data
includes shot-by-shot records with serve placement direction (wide/body/T).

The `serve_zones` table (schema below) needs to be populated from the charting tables as
part of the rating pipeline. Until that ETL step is built:
- Show the zone grid with placeholder percentages derived from serve stat proxies
- Mark with `data: 'estimated'` flag in API response so frontend can show a disclaimer

**Future schema addition:**
```sql
CREATE TABLE serve_zones (
    id          SERIAL PRIMARY KEY,
    player_id   INTEGER NOT NULL REFERENCES players(id),
    surface_id  INTEGER REFERENCES surfaces(id),
    serve_number INTEGER NOT NULL CHECK (serve_number IN (1, 2)),
    court_side  TEXT NOT NULL CHECK (court_side IN ('deuce', 'ad')),
    zone        TEXT NOT NULL CHECK (zone IN ('wide', 'body', 't')),
    pct         NUMERIC(5,2),       -- % of serves to this zone
    sample_size INTEGER,            -- number of serves in sample
    updated_at  TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(player_id, surface_id, serve_number, court_side, zone)
);
```

---

## Tab 5 — Intelligence

### Key factor cards

A list of 4–6 factor cards sourced from `model_predictions.key_factors` (JSONB array).

Each card contains:
- Factor name (e.g. "Clay surface dominance")
- Impact level: `high` / `medium` / `low` — rendered as coloured badge
- Direction: which player this factor favours
- Description: one or two plain-English sentences
- Weight bar: visual indicator of relative model feature importance (0–100)

**`key_factors` JSONB schema:**
```json
[
  {
    "factor": "Clay surface dominance",
    "impact": "high",
    "favours": "second_player",
    "weight": 88,
    "description": "Alcaraz clay rating 96 vs Sinner 92. Heavier topspin and court position create structural advantage on this surface."
  }
]
```

The ML pipeline populates this array at prediction time using SHAP values or feature
importance from the trained model, mapped to human-readable descriptions.

### AI narrative

A single paragraph (`model_predictions` — add a `narrative TEXT` column) summarising
the model's reasoning in plain English. Generated by an LLM (Claude) at prediction time,
grounded in the key factors above. 100–150 words.

### Historical analogue

A brief callout — the most similar historical matchup in the training data, with outcome.
Computed from embedding similarity of the match feature vector against historical matches.
Store in `model_predictions` as `analogue_match_id` (references `sa_matches.id`) and
`analogue_description TEXT`.

### Recommended bet types

Three recommended bets pre-computed at prediction time from the model output + market odds:

| Bet type | How edge is computed |
|---|---|
| Match winner | `model_prob - implied_market_prob` |
| Total games over/under | Separate total-games model (v2 feature) |
| Set handicap | Separate set model (v2 feature) |

Show each with: odds, model probability, edge badge.

**Add to `model_predictions`:**
```sql
ALTER TABLE model_predictions
    ADD COLUMN IF NOT EXISTS narrative         TEXT,
    ADD COLUMN IF NOT EXISTS analogue_match_id INTEGER REFERENCES sa_matches(id),
    ADD COLUMN IF NOT EXISTS analogue_description TEXT,
    ADD COLUMN IF NOT EXISTS bet_recommendations JSONB;
```

---

## Full API contract

### `GET /matches/today`

Returns all matches for today (and next 48h for upcoming) with prediction summaries.

```json
{
  "matches": [
    {
      "match_id": 12345,
      "tournament": "Roland Garros 2026",
      "surface": "Clay",
      "round": "Quarter-final",
      "event_date": "2026-06-02",
      "event_time": "14:00",
      "first_player": { "id": 1, "name": "J. Sinner", "country_code": "IT", "rtt_score": 94 },
      "second_player": { "id": 2, "name": "C. Alcaraz", "country_code": "ES", "rtt_score": 93 },
      "prediction": { "prob_p1": 0.42, "prob_p2": 0.58, "confidence": "high" },
      "market": { "odds_p1": 2.10, "odds_p2": 1.92, "implied_p1": 0.476, "implied_p2": 0.521 },
      "edge": { "p1": -0.056, "p2": 0.059, "best_value": "p2" }
    }
  ]
}
```

### `GET /matches/{id}`

Full match detail for the match engine page.

```json
{
  "match": { ...all header fields... },
  "players": {
    "first": {
      ...player fields...,
      "ratings": {
        "rtt_score": 94, "clay_rating": 92, "hard_rating": 96,
        "grass_rating": 85, "indoor_rating": 96,
        "serve_rating": 88, "return_rating": 72, "net_game_rating": 71,
        "pressure_rating": 76, "consistency_rating": 90,
        "form_rating": 80, "momentum": "stable",
        "big_match_rating": 91, "vs_top10_rating": 86
      },
      "form_dots": ["W","W","W","L","W"],
      "stats": {
        "overall": { ... },
        "surface": { ... },
        "top20": { ... },
        "last20": { ... }
      }
    },
    "second": { ...same structure... }
  },
  "prediction": {
    "prob_first_player": 0.42,
    "prob_second_player": 0.58,
    "confidence": "high",
    "key_factors": [ ...array... ],
    "narrative": "...",
    "analogue_description": "...",
    "bet_recommendations": [ ...array... ]
  },
  "market": { ...odds... }
}
```

### `GET /players/{id}/form?surface=all&limit=15`

```json
{
  "player_id": 1,
  "matches": [
    {
      "match_id": 12000,
      "date": "2026-04-15",
      "tournament": "Monte Carlo 2026",
      "surface": "Clay",
      "opponent_name": "A. Zverev",
      "opponent_rank": 4,
      "won": true,
      "performance_index": 84.2
    }
  ]
}
```

### `GET /players/{p1_id}/h2h/{p2_id}`

```json
{
  "summary": {
    "p1_wins": 5, "p2_wins": 8, "total": 13,
    "by_surface": {
      "Clay":  { "p1": 2, "p2": 3 },
      "Hard":  { "p1": 3, "p2": 4 },
      "Grass": { "p1": 0, "p2": 1 }
    }
  },
  "matches": [
    {
      "match_id": 11800, "date": "2025-06-06",
      "tournament": "Roland Garros 2025", "round": "Semi-final",
      "surface": "Clay", "winner": "second_player",
      "score": "6-4, 6-2"
    }
  ]
}
```

### `GET /players/{id}`

```json
{
  "player": {
    "id": 2, "name": "C. Alcaraz", "full_name": "Carlos Alcaraz",
    "country": "Spain", "country_code": "ES",
    "birthday": "2003-05-05", "height_cm": 185, "hand": "Right",
    "turned_pro": 2018
  },
  "ratings": { ...all 13 RTT ratings... },
  "recent_form": { "wins": 9, "losses": 1, "last_10": "W W W W W W W W L W" }
}
```

---

## Real-time vs static data split

| Data type | Freshness | Caching strategy |
|---|---|---|
| Match predictions | Computed once pre-match, refreshed if odds move > 5% | Cache until match starts |
| Player ratings | Updated daily after pipeline run | Cache for 24h |
| Form history | Recomputed after each match result | Cache for 24h |
| Live match status / score | Real-time (livescore job every 5 min) | No cache |
| Market odds | Refreshed every 30 min | Cache for 30 min |
| H2H history | Static (historical) | Cache for 7 days |

---

## Schema additions summary

All required schema additions in one place (run in order):

```sql
-- 1. Extend player_ratings with new dimensions
ALTER TABLE player_ratings
    ADD COLUMN IF NOT EXISTS indoor_rating      NUMERIC(5,2),
    ADD COLUMN IF NOT EXISTS net_game_rating    NUMERIC(5,2),
    ADD COLUMN IF NOT EXISTS return_rating      NUMERIC(5,2),
    ADD COLUMN IF NOT EXISTS pressure_rating    NUMERIC(5,2),
    ADD COLUMN IF NOT EXISTS big_match_rating   NUMERIC(5,2),
    ADD COLUMN IF NOT EXISTS vs_top10_rating    NUMERIC(5,2),
    ADD COLUMN IF NOT EXISTS momentum           TEXT,
    ADD COLUMN IF NOT EXISTS rtt_score          NUMERIC(5,2);

-- 2. Rating history for form chart
CREATE TABLE IF NOT EXISTS player_ratings_history (
    id                 SERIAL PRIMARY KEY,
    player_id          INTEGER NOT NULL REFERENCES players(id) ON DELETE CASCADE,
    rated_at           DATE NOT NULL,
    rtt_score          NUMERIC(5,2),
    clay_rating        NUMERIC(5,2),
    hard_rating        NUMERIC(5,2),
    grass_rating       NUMERIC(5,2),
    indoor_rating      NUMERIC(5,2),
    serve_rating       NUMERIC(5,2),
    return_rating      NUMERIC(5,2),
    net_game_rating    NUMERIC(5,2),
    pressure_rating    NUMERIC(5,2),
    consistency_rating NUMERIC(5,2),
    form_rating        NUMERIC(5,2),
    momentum           TEXT,
    big_match_rating   NUMERIC(5,2),
    vs_top10_rating    NUMERIC(5,2),
    match_count        INTEGER,
    UNIQUE(player_id, rated_at)
);
CREATE INDEX IF NOT EXISTS idx_prh_player_date
    ON player_ratings_history(player_id, rated_at DESC);

-- 3. Match win probability and model reasoning
CREATE TABLE IF NOT EXISTS model_predictions (
    id                    SERIAL PRIMARY KEY,
    match_id              INTEGER UNIQUE NOT NULL REFERENCES matches(id),
    prob_first_player     NUMERIC(5,4),
    prob_second_player    NUMERIC(5,4),
    confidence            TEXT CHECK (confidence IN ('high','medium','low')),
    key_factors           JSONB,
    narrative             TEXT,
    analogue_match_id     INTEGER,
    analogue_description  TEXT,
    bet_recommendations   JSONB,
    model_version         TEXT DEFAULT 'v1',
    predicted_at          TIMESTAMPTZ DEFAULT NOW()
);

-- 4. Bookmaker odds for edge calculation
CREATE TABLE IF NOT EXISTS bookmaker_odds (
    id              SERIAL PRIMARY KEY,
    match_id        INTEGER NOT NULL REFERENCES matches(id),
    bookmaker       TEXT NOT NULL,
    player_ref      TEXT NOT NULL CHECK (player_ref IN ('first_player','second_player')),
    decimal_odds    NUMERIC(8,4),
    implied_prob    NUMERIC(5,4),
    fetched_at      TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_odds_match
    ON bookmaker_odds(match_id, fetched_at DESC);

-- 5. Rating calibration checkpoints
CREATE TABLE IF NOT EXISTS rating_calibration (
    id            SERIAL PRIMARY KEY,
    dimension     TEXT NOT NULL,
    calibrated_at DATE NOT NULL,
    p10           NUMERIC(5,2),
    p25           NUMERIC(5,2),
    p50           NUMERIC(5,2),
    p75           NUMERIC(5,2),
    p90           NUMERIC(5,2),
    player_count  INTEGER,
    UNIQUE(dimension, calibrated_at)
);

-- 6. Serve zone placement data (future — Hawk-Eye source)
CREATE TABLE IF NOT EXISTS serve_zones (
    id           SERIAL PRIMARY KEY,
    player_id    INTEGER NOT NULL REFERENCES players(id) ON DELETE CASCADE,
    surface_id   INTEGER REFERENCES surfaces(id),
    serve_number INTEGER NOT NULL CHECK (serve_number IN (1, 2)),
    court_side   TEXT NOT NULL CHECK (court_side IN ('deuce', 'ad')),
    zone         TEXT NOT NULL CHECK (zone IN ('wide', 'body', 't')),
    pct          NUMERIC(5,2),
    sample_size  INTEGER,
    updated_at   TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(player_id, surface_id, serve_number, court_side, zone)
);
```
