# ratethat.tennis — Project Context for AI Assistants

> Read this file first. It is the authoritative reference for any AI, ML engineer, or
> developer working on this project. All other docs in `docs/` go deeper on specific areas.

---

## ⚠️ CRITICAL — DO NOT REWRITE THESE FILES

**This project has suffered repeated accidental deletion of carefully-built features when AI
assistants rewrote files instead of editing them surgically. Before touching any file below,
READ the existing file first, then make the minimum change required.**

### `frontend/src/pages/MatchList.jsx` — EDIT ONLY, NEVER REWRITE

This file has been rebuilt from scratch **five times** after AI sessions destroyed it.
It contains all of the following — if any are missing after your change, you broke it:

- **NO `FormDots` import or usage** — this was deliberately removed; do NOT add it back
- `detectLevel(match)` function — classifies matches as Slam/Masters, Challenger, ITF, Tour
- `Tickbox` component — styled checkbox with colour accent
- `LEVELS` constant — `['Slam / Masters', 'Challenger', 'ITF']`
- State: `levels` (Set), `upcomingOnly`, `ratedOnly`, `hideUnidentified`
- `toggleLevel()` function
- **Level tickboxes** in the filter bar (Slam/Masters, Challenger, ITF)
- **Visibility tickboxes** in the filter bar (Upcoming only, Rated players only, Hide unidentified)
- Surface pills, Tour pills, Tournament dropdown, Sort pills
- Sidebar component with prediction win rate, RTT selections, top win chances
- StarPick on each player name (non-finished matches only)
- LiveLozenge and MomentumLozenge components

**Rule:** When adding something to MatchList.jsx, use `Edit` with the smallest possible
change. Never pass the full file to `Write`. Check the line count before and after — it
should not decrease.

### `frontend/src/pages/MatchDetail.jsx` — EDIT ONLY, NEVER REWRITE

Contains a 6-tab match engine. All tabs must remain: Overview, Form, H2H, Serve,
Intelligence, plus the court-image header. Do not replace this file.

### `frontend/src/index.css` — EDIT ONLY, NEVER REWRITE

The entire dark-theme design system. Adding styles = append or targeted edit only.

### `ml/predict.py` — ITF EXCLUSION MUST STAY

The `predict_upcoming` SQL **must** contain this filter and must never be removed:
```sql
AND (et.tour_category IS NULL OR et.tour_category NOT IN ('ITF', 'Junior'))
```
ITF players have no Sackmann historical data → Elo defaults to 1500 for both → 50/50 predictions flood the site. This filter was accidentally removed by an AI session on 2026-05-13.

---

## What this is

**ratethat.tennis** is a machine-learning-powered tennis analytics and betting intelligence
platform. It ingests live match data and decades of historical match statistics, computes
proprietary player and match ratings, and presents them through a match engine UI designed
to help bettors find value against bookmaker markets.

The site will live at [ratethat.tennis](https://ratethat.tennis).

---

## Vision & competitive positioning

The core insight: every competitor (TennisBrain, TennisViz, Tennis Explorer, WinnerOdds,
Matchstat) shows *data at* a bettor and leaves the conclusion as homework. ratethat.tennis
answers **"is there value here?"** on first glance, then supports it with layers of depth.

Key differentiators:

- **RTT Score** — a proprietary composite player rating (not raw ATP stats) that bettors
  learn to trust the way FIFA card ratings trained a generation of football fans.
- **Model edge vs market is the headline** — shown prominently in the match header, not
  buried in an odds comparison page.
- **Form lines use our ML performance index**, not just win/loss — a 6-0, 6-1 win against
  a #180 qualifier is not the same as a 7-6, 7-5 against a top-10 player.
- **Surface-specific everything** — surface is the single most predictive variable in
  tennis; every chart, rating, and comparison has a surface filter.
- **Intelligence tab** — the model's reasoning rendered in plain English, making it a
  decision aid rather than a data dump.

---

## Tech stack

| Layer | Technology |
|---|---|
| Database | PostgreSQL (hosted on Railway) |
| Data pipeline | Python 3.11, psycopg2, requests — see `pipeline/pipeline.py` |
| Live data | api-tennis.com REST API |
| Historical / ML training data | Jeff Sackmann tennis_atp / tennis_wta datasets (CC BY-NC-SA 4.0) |
| ML models | XGBoost + LightGBM + Logistic Regression ensemble — see `ml/` |
| API | FastAPI (Python 3.11) — see `api/` — `uvicorn api.main:app` |
| Deployment | Railway (pipeline service + Postgres) |
| Frontend | React (to be built) — consuming `api/` REST endpoints |

---

## Repository structure

```
ratethat.tennis/
├── CLAUDE.md                        ← you are here
├── schema.sql                       ← live production schema (PostgreSQL)
├── sackmann_schema.sql              ← ML training data schema (never surfaced on frontend)
├── pipeline/
│   ├── pipeline.py                  ← ETL pipeline (api-tennis.com → PostgreSQL)
│   ├── sackmann_ingest.py           ← Sackmann + Match Charting Project bulk ingestion
│   ├── schema_additions.sql         ← extra tables: player_ratings_history, model_predictions, etc.
│   ├── requirements.txt
│   └── Dockerfile
├── ml/
│   ├── __init__.py
│   ├── elo.py                       ← Surface-specific Elo engine (point-in-time)
│   ├── features.py                  ← 56-feature matrix builder (loads from sa_matches via SQLAlchemy)
│   ├── train.py                     ← XGBoost + LightGBM + Logistic Regression trainer
│   ├── backtest.py                  ← Walk-forward backtester (year-by-year, 2015–2024)
│   ├── predict.py                   ← Live prediction pipeline
│   ├── ratings.py                   ← RTT rating computation engine (13 dimensions)
│   ├── lab/                         ← ML Lab HTML dashboard (open index.html to review backtest)
│   └── results/                     ← features.parquet + backtest_results.json (gitignored)
├── api/
│   ├── __init__.py
│   ├── main.py                      ← FastAPI app — run: uvicorn api.main:app --reload
│   ├── db.py                        ← psycopg2 connection pool + query helpers
│   ├── requirements.txt
│   └── routes/
│       ├── matches.py               ← GET /matches/today, GET /matches/{id}
│       └── players.py               ← GET /players/{id}, /form, /h2h/{p2_id}
├── docs/
│   ├── ratings-spec.md              ← RTT rating system: full computation spec
│   ├── match-engine-spec.md         ← frontend match engine: components & API contract
│   └── match-engine-concept.md      ← UX design rationale and competitor analysis
├── run_ml_pipeline.command          ← double-click: build features → train → backtest → ML Lab
├── run_backtest.command             ← double-click: rerun backtest only (uses existing parquet)
├── run_ratings.command              ← double-click: compute RTT ratings → write player_ratings_history
├── run_api.command                  ← double-click: start API at http://localhost:8000
├── run_sackmann_ingest.command      ← double-click: run full Sackmann historical load
├── run_schema_additions.command     ← double-click: apply schema_additions.sql to Railway DB
├── run_schema.py                    ← one-shot schema runner
└── seed_data.py                     ← initial data seed script
```

---

## Database architecture

Two separate schema layers deliberately kept apart:

### Production schema (`schema.sql`)

Tables surfaced on the frontend and consumed by the API:

| Table | Purpose |
|---|---|
| `event_types` | Tour categories (ATP Singles, WTA Doubles, ITF Men, etc.) |
| `surfaces` | Surface lookup (Clay, Hard, Grass, Carpet, Indoor Hard) |
| `tournaments` | Tournament registry with surface and event type |
| `players` | Player registry — name, country, height, hand, ranking (from API) |
| `matches` | Every match event — metadata, result, live status, raw JSON |
| `match_scores` | Set-by-set scores for each match |
| `match_games` | Game-by-game data (server, score after) |
| `match_points` | Point-by-point data (break point, set point, match point flags) |
| `match_ratings` | AI-computed match scores: excitement, quality, upset, overall |
| `player_ratings` | AI-computed player scores: overall, form, serve, surface ratings |
| `player_surface_stats` | Win/loss records by surface and season |
| `pipeline_runs` | ETL job audit log |

Key views:
- `v_matches_with_details` — joins matches → players → tournament → surface → rating
- `v_player_form` — joins players → player_ratings for fast form lookups

### ML training schema (`sackmann_schema.sql`)

Sackmann historical data — **never exposed on the frontend or in any API response**:

| Table | Purpose |
|---|---|
| `sa_players` | Historical player registry |
| `sa_matches` | ~3M historical ATP/WTA matches with full serve/return stats |

The `sa_matches` table is the primary ML training source. Key stat columns available per match:
`w_ace`, `w_df`, `w_svpt`, `w_1stIn`, `w_1stWon`, `w_2ndWon`, `w_SvGms`,
`w_bpSaved`, `w_bpFaced`, `winner_rank`, `loser_rank`, `winner_rank_points`,
`loser_rank_points`, `tourney_level`, `surface`, `minutes`.
All columns repeat for the loser with `l_` prefix.

---

## Data sources

### api-tennis.com (live / current data)

- API key: set via `API_TENNIS_KEY` environment variable
- Base URL: `https://api.api-tennis.com/tennis`
- Methods used: `get_events`, `get_tournaments`, `get_fixtures`, `get_livescore`, `get_players`
- Pipeline jobs (see `pipeline/pipeline.py`):
  - `sync_event_types` — one-time, loads tour categories
  - `sync_tournaments` — weekly, syncs tournament registry
  - `daily_fixtures` — runs at 06:00 UTC and 22:30 UTC
  - `livescore` — runs every 5 minutes during play

### Jeff Sackmann datasets (historical / ML training only)

- Source: github.com/JeffSackmann — three repos ingested:
  - `tennis_atp` — ATP matches ~1968–present, full serve/return stats from ~2000
  - `tennis_wta` — WTA matches on the same schema
  - `tennis_MatchChartingProject` — shot-by-shot charting including **serve placement
    zones (Wide/Body/T), net approaches, rally length** — this powers the Serve tab
    in the match engine once mapped to players
- Licence: CC BY-NC-SA 4.0 — **training and display of derived stats only;
  never surface raw Sackmann rows in any API response**
- Ingestion script: `pipeline/sackmann_ingest.py`
  - Jobs: `all`, `players`, `matches`, `rankings`, `charting`
  - Run `--job charting` to load Match Charting Project data (serve zones etc.)
  - Convenience runner: double-click `run_sackmann_ingest.command` on macOS
- Loaded into `sa_matches`, `sa_players` (and charting tables TBD) in the ML schema

---

## The RTT Rating System

This is the core ML output and the product's primary differentiator. All ratings are on a
**0–100 scale**, normalised across all active players, **quality-weighted** (wins against
stronger opponents count more), **surface-adjusted** (surface-specific ratings computed
independently), and **time-decayed** (recent matches weighted more heavily).

See `docs/ratings-spec.md` for full computation methodology.

### Four rating groups

**1. RTT Score** — the headline composite:
- `rtt_score` — overall player strength rating (the single number on the player card)

**2. Surface ratings** — four independent scores:
- `clay_rating`, `hard_rating`, `grass_rating`, `indoor_rating`

**3. Skill ratings** — five technical dimensions:
- `serve_rating` — composite of ace rate, 1st serve %, 1st serve won %, BP saved %
- `return_rating` — return points won %, break point conversion %
- `net_game_rating` — net approach efficiency (proxy from available stats)
- `pressure_rating` — tiebreak win %, deciding set win %, close match win %
- `consistency_rating` — games won %, avoiding bagel sets given, double fault rate

**4. Form & context** — dynamic and situational:
- `form_rating` — rolling 10-match performance index (quality-weighted)
- `momentum` — directional trend: `rising` | `stable` | `falling`
- `big_match_rating` — performance at Slams + Masters 1000 only
- `vs_top10_rating` — win rate and quality score against top-10 opponents

### Where ratings live in the schema

All tables are ✅ created and deployed. Run `run_schema_additions.command` to apply
`pipeline/schema_additions.sql` (idempotent — safe to rerun).

Key tables added beyond the base `schema.sql`:
- `player_ratings_history` — daily snapshots of all 13 rating dimensions (UNIQUE per player+date)
- `model_predictions` — match win probability + key factors + narrative + bet recommendations
- `bookmaker_odds` — decimal odds per match per player for edge calculation
- `rating_calibration` — population percentile checkpoints for normalisation
- `serve_zones` — serve placement % by zone/surface/side (future: from Hawk-Eye / Charting data)

`player_ratings` (existing) now has extra columns: `indoor_rating`, `net_game_rating`,
`return_rating`, `pressure_rating`, `big_match_rating`, `vs_top10_rating`, `momentum`, `rtt_score`.

---

## ML models (built)

### Model 1 — Match outcome predictor (core)

**Goal:** predict P(player 1 wins) for any upcoming match.

**Training data:** `sa_matches` joined with rolling player stats computed at match date.

**Input features (computed at the time of the match):**
- Player 1 and Player 2 RTT scores at match date
- Surface-specific ratings for the match surface
- Head-to-head record on this surface (last 5 meetings)
- Form rating (rolling 10-match index) for both players
- Tournament level (Slam/Masters/500/250/Challenger)
- Round (R128 → Final — later rounds = higher pressure)
- Days since last match (fatigue proxy)
- Height difference (serve advantage proxy on fast surfaces)
- Hand matchup (both right / left vs right / left)

**Target:** binary — did player 1 win? (1/0)

**Status:** ✅ Built. XGBoost + LightGBM + Logistic ensemble. Walk-forward backtest
2015–2024 shows ~68% accuracy, AUC ~0.76, +5% edge over Elo baseline.
Train via `python3 -m ml.train --build-features` or `run_ml_pipeline.command`.

### Model 2 — Player rating engine

**Goal:** compute RTT scores and skill ratings for every player, updated daily.

**Not a predictive model** — this is a feature engineering pipeline that computes rolling
statistics from match history and normalises them across the full player population.

**Status:** ✅ Built. `ml/ratings.py` — 13 rating dimensions. Run `run_ratings.command`
to populate `player_ratings` and `player_ratings_history` tables.
See `docs/ratings-spec.md` for full methodology.

### Model 3 — Match quality rater

**Goal:** rate completed matches on excitement, quality, and upset value.

**Status:** ⏳ Pending — `match_ratings` table exists in schema, scoring function not yet built.

---

## Frontend & API

The REST API is ✅ built at `api/`. Run with `run_api.command` or:
```bash
uvicorn api.main:app --reload --port 8000
```
Docs auto-generated at `http://localhost:8000/docs`.

Full spec in `docs/match-engine-spec.md`. Implemented endpoints:

| Endpoint | Description |
|---|---|
| `GET /api/v1/matches/today` | All matches today (+ next 48h) with predictions and edge |
| `GET /api/v1/matches/{id}` | Full match detail: players, all ratings, stats, prediction |
| `GET /api/v1/players/{id}` | Player profile with all 13 RTT dimensions |
| `GET /api/v1/players/{id}/form?surface=clay&limit=15` | Match-level form for chart |
| `GET /api/v1/players/{id}/matches?surface=all&limit=25&offset=0` | Paginated match history (W/L, score, surface, tournament) |
| `GET /api/v1/players/{id}/stats` | Career stats: serve averages, W/L by surface, rankings by year |
| `GET /api/v1/players/{p1_id}/h2h/{p2_id}` | Head-to-head history with surface breakdown |
| `GET /health` | DB connectivity check |

**Important:** The API looks up Sackmann / TML player IDs from player names for historical stats.
This lookup uses `ILIKE` fuzzy match on `sa_players.name`. If a player has no historical data,
stats will be empty rather than erroring.

---

## Current status (as of May 2026)

| Component | Status |
|---|---|
| PostgreSQL schema | ✅ Deployed on Railway |
| Schema additions (ratings history, predictions, odds) | ✅ Applied — `run_schema_additions.command` |
| Data pipeline (live fixtures) | ✅ Running — run `run_fixtures.command` daily to pull upcoming matches |
| Sackmann historical load | ✅ ATP: 644,990 matches + rankings loaded. WTA: loaded. |
| Feature engineering pipeline | ✅ `ml/features.py` — 56 features, saves to `ml/results/features.parquet` |
| ML model training | ✅ XGBoost + LightGBM + Logistic ensemble — `ml/train.py` |
| Walk-forward backtest | ✅ `ml/backtest.py` — 2015–2024, 66.5% accuracy, +2.6% edge vs Elo, AUC 0.730 |
| RTT rating engine | ✅ `ml/ratings.py` — 13 dimensions, pop-normalised 0–100 |
| REST API | ✅ `api/` — FastAPI, 7 endpoints, runs locally via `run_api.command` |
| ML Lab dashboard | ✅ `ml/lab/index.html` — opens after `run_backtest.command` |
| React frontend | ✅ `frontend/` — Vite + React, 6-tab match engine + Live page + 4-tab PlayerPage, runs via `run_frontend.command` |
| Railway deployment (API) | ✅ `Dockerfile` + `railway.toml` at repo root — see `RAILWAY_SETUP.md` |
| Railway deployment (frontend) | ✅ `frontend/Dockerfile` + `frontend/railway.toml` — nginx, SPA routing — see `RAILWAY_SETUP.md` |
| RTT ratings populated | ✅ 148 players via Sackmann data + supplemental from production matches — `run_ratings.command` |
| Bookmaker odds integration | ✅ `pipeline/odds.py` — The Odds API integration ready; set `ODDS_API_KEY` + run `run_odds.command` |
| Model predictions pipeline | ✅ 110/110 upcoming matches predicted — `run_predictions.command` |
| TML-Database ingestion | ✅ `pipeline/tml_ingest.py` — MIT-licensed ATP data, same schema as Sackmann, run `run_tml_ingest.command` |
| Player match history API | ✅ `GET /players/{id}/matches` + `GET /players/{id}/stats` — paginated history + career stats |
| PlayerPage full profile | ✅ 4-tab player page: Overview, Form, Match History, Stats |

## Daily workflow (local dev)

Run these in order each day:
1. `run_fixtures.command` — fetch today's matches from api-tennis.com
2. `run_odds.command` — fetch bookmaker odds (requires `ODDS_API_KEY` in `.env`)
3. `run_predictions.command` — generate ML win probabilities for upcoming matches
4. `run_api.command` — start FastAPI at http://localhost:8000 (keep open)
5. `run_frontend.command` — start React app at http://localhost:3000 (keep open)

On Railway: steps 1–3 run automatically via `pipeline/scheduler.py` (fixtures at 06:00/18:00 UTC, odds at 07:00/19:00 UTC). Run `run_ratings.command` weekly to refresh RTT scores.

## Frontend structure

```
frontend/
├── src/
│   ├── App.jsx                  ← router: / → MatchList, /match/:id → MatchDetail, /player/:id → PlayerPage
│   ├── api.js                   ← fetch-based API client
│   ├── index.css                ← dark theme design system (CSS vars)
│   ├── components/
│   │   ├── SurfaceBadge.jsx     ← clay/hard/grass colour pill
│   │   ├── FormDots.jsx         ← W/L dot row
│   │   ├── EdgeBadge.jsx        ← model edge indicator (green/amber/neutral)
│   │   ├── ProbBar.jsx          ← split probability bar
│   │   ├── RadarChart.jsx       ← Chart.js radar: 6 skill dimensions
│   │   └── FormChart.jsx        ← Chart.js line: performance index over time
│   └── pages/
│       ├── MatchList.jsx        ← homepage: surface filter tabs, match cards
│       ├── MatchDetail.jsx      ← 5 tabs: Overview, Form, H2H, Serve, Intelligence
│       └── PlayerPage.jsx       ← 4-tab player profile: Overview (ratings+radar), Form, Match History, Stats
└── package.json                 ← React 18, React Router v6, Chart.js 4, Vite 5
```

## Known schema quirks

- `player_ratings.form_score` — column is `form_score` (not `form_rating`); API aliases it as `form_rating`
- `player_ratings.consistency_score` — column is `consistency_score` (not `consistency_rating`); API aliases it
- `matches.winner` — TEXT field ("First Player" | "Second Player"), not a foreign key
- `sa_matches.winner_id` / `loser_id` — Sackmann-specific integer IDs, unrelated to `players.id`
- Fixtures API requires a date *range* (date_start ≠ date_stop) to return results reliably

---

## Conventions

- **Sackmann / TML data is training-only.** Never join `sa_matches` or `sa_players` into any
  API response that surfaces raw rows. Derived stats (win rates, serve averages, H2H counts) are fine.
- **TML player IDs are offset by 10,000,000** in `sa_players` to avoid collision with Sackmann IDs.
  TML records have `tour = 'TML'`.
- **All ratings are 0–100.** Never expose raw stat percentages as ratings. Normalise.
- **Surface is always a filter.** Every stat comparison, chart, and model input should
  have a surface dimension. Hard-court Sinner and clay-court Sinner are different players.
- **Calibrated probabilities only.** Do not expose raw model logits or uncalibrated
  softmax outputs as match predictions. Always calibrate before storing.
- **DB connection:** `DATABASE_URL` and `DATABASE_PUBLIC_URL` env vars. Internal Railway
  URL for pipeline service; public URL for local dev. See `pipeline/pipeline.py` for
  connection handling.
- **API key:** `API_TENNIS_KEY` env var — never hardcode in new files.
- **Pipeline jobs are idempotent.** All upserts use `ON CONFLICT DO UPDATE`. Safe to rerun.
