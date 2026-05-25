# ratethat.tennis — Data Gaps & Implementation Plan
*Audit date: 2026-05-25*

This document maps every unused or poorly-used data source to concrete implementation tasks.
Priority tiers: **P1** = do this week, **P2** = do this sprint, **P3** = next sprint.

---

## The Problem in One Paragraph

We have a Bzzoiro API subscription with rich match data; a Sackmann corpus of 644K matches; a matchstat feed with serve speeds and career stats; 2,583 players with clutch/pressure stats computed; 5,583 matches with full serve data stored; and a serve-zones pipeline with a complete frontend UI waiting for data. Almost none of it is surfaced. Meanwhile `bzzoiro_ingest.py` — the file `api/main.py` already expects — does not exist. The result is a match page where half the ratings are 50-point stubs, the Intelligence tab says "awaiting deep-reasoning pass" on matches that started hours ago, and T. Samuel's clay rating is 50 on a Roland Garros match.

---

## What the Audits Found

### Bzzoiro API — what exists vs what we use

| Endpoint | What's there | We use? |
|---|---|---|
| `/matches/` list | 13 fields incl. sets scores | ✅ via slam_backfill only |
| `/matches/{id}/` detail | **10 extra fields**: aces, DFs, 1st serve %, 1st won %, 2nd won %, current score, server | ❌ Never fetched |
| `/predictions/` | Win probability, confidence, + 7 totals fields (all null on their end) | ❌ Never ingested |
| `/rankings/` | Top 500 ATP/WTA, previous position, previous points — updated weekly | ❌ Never ingested |
| `/players/` | 5,129 players, DOB ~52% filled; height/hand 0% | ❌ Never synced to our `players` table |
| Match history | 28,390 matches since 2020 (covers UTR + events Sackmann misses) | ❌ `bzzoiro_ingest.py` doesn't exist |

### Database — columns that exist but are empty

| Table | Dead column(s) | Impact |
|---|---|---|
| `players` | `height_cm`, `current_rank`, `ranking_points`, `turned_pro` — all 0% | Height diff is a feature; rank is displayed on match cards |
| `player_ratings` | `overall_rating` 0%, `form_wins/losses` 0%, `form_summary/strengths/weaknesses` 0%, `big_match_rating` 0.4%, `vs_top10_rating` 0.1% | Big match and vs-top10 are shown on every match page as "—" |
| `model_predictions` | `bet_recommendations` 0%, `analogue_match_id/description` 0%, `hand/h2h/surface logits` 0% | Bet recs never generated; analogue matches never surfaced |
| `serve_zones` | **0 rows** | Serve tab shows 33/33/33 estimates for every match |
| `player_surface_stats` | **0 rows** | Designed to track surface W/L by season — never populated |
| `match_ratings` | **0 rows** | Match quality/excitement ratings never computed |
| `player_ratings_history` | Only 1 week of snapshots (May 3–9) | Daily snapshot pipeline not running |
| `bookmaker_odds` | Only 3.2% of upcoming matches have odds | Odds shown as "not yet available" on nearly every match |

### Computed data that exists but isn't surfaced

| Source | Data sitting idle | Where it should appear |
|---|---|---|
| `player_point_stats` (2,583 players) | `tiebreak_win_pct`, `pressure_win_pct`, `match_point_save_pct`, `set1_recovery_pct`, `set_point_save_pct` | Points Analysis tab, Intelligence tab |
| `match_serve_stats` (5,583 matches, 99% filled) | Aces, DFs, 1st serve %, 1st won %, 2nd won % — per match | Player form page, Statistics tab career averages |
| `ms_match_stats` (Matchstat, 52 MB) | Winners, UEs, net approaches, serve speeds for select matches | Serve tab, Intelligence tab, ML features |
| `aging_curve.py` | `age_factor()` function fitted and working | ML `features.py` — never called |
| Sackmann charting | `sa_charting_points` with serve direction (W/B/T) per point | `serve_zones` table → Serve tab |
| `ms_player_career_stats` | `slam_winner_ue_ratio` — strong predictor not in ML features | `ml/features.py` |

---

## Implementation Plan

---

### PHASE 1 — Get the data (this week)

#### P1-1: Write `pipeline/bzzoiro_ingest.py`

This is the most urgent item. `api/main.py` already has four admin endpoints that call this file. It doesn't exist.

**What to write:**

```
sync_matches(conn, date_from, date_to)
  - Paginate /matches/ for the date range
  - For each match, hit /matches/{id}/ to get the 10 serve-stat fields
  - Upsert into `matches` (api_event_key = -abs(bzz_id))
  - Upsert serve stats into `match_serve_stats`
  - Upsert set scores into `match_scores`

sync_predictions(conn, date_from, date_to)
  - Paginate /predictions/ filtered by match date
  - Store prob_player1_wins, prob_player2_wins, confidence
  - Link to our match via api_event_key → match.id join

sync_rankings(conn)
  - Paginate /rankings/?ranking_type=ATP and WTA
  - Upsert current_rank, ranking_points into players table
  - Also write to player_ratings_history (enables weekly movement tracking)

sync_player_bios(conn)
  - Paginate /players/ (5,129 records)
  - Update players.birthday where currently null (Bzzoiro ~52% filled)
  - Update players.country where currently null

backfill_history(conn, date_from="2020-01-01")
  - Pull all 28,390 matches since 2020
  - Upsert into sa_matches-equivalent table (or a new bzz_matches table)
  - This fills the coverage gap for UTR/recent players that Sackmann misses
```

**Schedule:** Add to `scheduler.py`:
- `sync_matches` + `sync_predictions`: daily at 06:10 UTC (after fixtures) and 18:10 UTC
- `sync_rankings`: weekly Monday 07:00 UTC
- `sync_player_bios`: weekly Monday 07:05 UTC

---

#### P1-2: Populate `players.current_rank` and `ranking_points`

These columns are 0% populated but are displayed on match cards (the "50" RTT badge). The Bzzoiro `/rankings/` endpoint has current ATP/WTA rankings for 500 players. Run once immediately, then weekly via `sync_rankings`.

Separately: run `pipeline/fill_ratings.py` to supplement with api-tennis.com ranking data for the remaining players.

---

#### P1-3: Run `player_ratings_history` daily

`ml/ratings.py` computes all 13 dimensions but the scheduler doesn't run it daily. The table has only one week of snapshots from May 3–9. Without daily snapshots, `features.py` can't do point-in-time lookups for the 18 RTT features — they default to 50.0 for all historical training data, making those features useless.

**Action:** Add `run_ratings.command` (or a lightweight `ratings_daily.py`) to `scheduler.py` at 08:00 UTC daily.

---

#### P1-4: Populate `players.height_cm` and `hand` from Sackmann

Sackmann `sa_players` has height and hand for ~80% of ATP players. We have a `player_external_ids` mapping. Write a one-shot backfill:

```python
# pipeline/player_bio_backfill.py
UPDATE players p
SET height_cm = sp.height, hand = sp.hand
FROM sa_players sp
JOIN player_external_ids pei ON pei.external_id = sp.sackmann_id
WHERE pei.source = 'sackmann' AND pei.player_id = p.id
```

`height_diff` is a feature in `features.py` but is null in ~40% of training rows because `sa_players.height` is missing. TML data also has height. This is a straightforward join.

---

### PHASE 2 — Surface the data (days 3–7)

#### P2-1: Add serve stats to the player profile API

`match_serve_stats` has aces, DFs, and serve % for 5,583 matches. The player profile API (`GET /players/{id}`) doesn't aggregate or expose this. 

**Add to `api/routes/players.py`:**
```sql
SELECT 
  AVG(aces) as avg_aces, AVG(dfs) as avg_dfs,
  AVG(first_serve_pct) as avg_first_serve_pct,
  AVG(first_serve_won_pct) as avg_first_serve_won_pct,
  AVG(second_serve_won_pct) as avg_second_serve_won_pct
FROM match_serve_stats mss
JOIN matches m ON mss.match_id = m.id
WHERE mss.player_id = :player_id 
  AND m.surface_id = :surface_id  -- surface filter
  AND m.event_date > NOW() - INTERVAL '18 months'
```

Surface on: player profile Overview tab, Serve tab in MatchDetail (replace estimated values), Intelligence tab narrative.

---

#### P2-2: Expose `player_point_stats` clutch data in the API

The most impactful single change. These stats are computed for 2,583 players but are never returned by any API endpoint:

- `tiebreak_win_pct` — "wins 71% of tiebreaks"
- `match_point_save_pct` — "saves 68% of match points when serving"
- `pressure_win_pct` — composite clutch metric
- `set_point_save_pct`
- `set1_recovery_pct` — wins after losing the first set

**Add to `api/routes/matches.py`** (match detail join):
```sql
SELECT tiebreak_win_pct, match_point_save_pct, pressure_win_pct,
       set_point_save_pct, set1_recovery_pct, bp_save_pct, bp_conv_pct
FROM player_point_stats WHERE player_id = :player_id
```

Surface on: Points Analysis tab (already has the UI), Intelligence tab narrative (the deep-reasoning skill uses this data), ML features (add tiebreak/pressure as features — these are significant predictors).

---

#### P2-3: Add tiebreak and pressure stats to ML features

Currently `ml/features.py` has 56 features but none directly capture clutch performance. Add from `player_point_stats`:
- `p1_tiebreak_win_pct`, `p2_tiebreak_win_pct`, `tiebreak_diff`
- `p1_pressure_win_pct`, `p2_pressure_win_pct`, `pressure_diff`
- `p1_bp_save_pct`, `p2_bp_save_pct`, `bp_save_diff` (already in features as rolling avg — swap for point_stats values which are more stable)

These are among the top predictors for tight matches. This is directly what Bzzoiro's model uses with its "64 signals."

---

#### P2-4: Wire the aging curve into features

`pipeline/aging_curve.py` has a fitted `age_factor()` function that is never called. In `ml/features.py`, age features are raw (`p1_age`, `p2_age`). Replace with age-adjusted effective rating:

```python
from pipeline.aging_curve import age_factor
row['p1_age_adj'] = row['p1_rtt'] * age_factor(row['p1_age'])
```

This costs zero additional data — the function is already fitted. It would help differentiate a 33-year-old rated 80 from a 26-year-old rated 80.

---

#### P2-5: Populate `serve_zones` from Sackmann charting

The Serve tab frontend is **completely built** and waiting. It renders W/B/T percentages per player, surface, and serve number. The data exists in `sa_charting_points.serve_dir`. What's missing is one aggregation step:

```python
# pipeline/charting_to_serve_zones.py
INSERT INTO serve_zones (player_id, surface_id, serve_number, wide_pct, body_pct, t_pct, sample_size)
SELECT 
  player_id, surface_id, serve_number,
  COUNT(*) FILTER (WHERE serve_dir = 'W') * 100.0 / COUNT(*),
  COUNT(*) FILTER (WHERE serve_dir = 'B') * 100.0 / COUNT(*),
  COUNT(*) FILTER (WHERE serve_dir = 'T') * 100.0 / COUNT(*),
  COUNT(*)
FROM sa_charting_points
GROUP BY player_id, surface_id, serve_number
HAVING COUNT(*) >= 20  -- minimum sample
```

Then add `serve_zones` to the match detail API response. The frontend stops showing "estimated."

**Note:** First confirm `sa_charting_points` is populated — run `SELECT COUNT(*) FROM sa_charting_points`. If it's empty, run `python3 -m pipeline.sackmann_ingest --job charting` first (this may take 30–60 minutes).

---

#### P2-6: Fix odds coverage (3.2% → target 60%+)

Bookmaker odds exist for only 23 of 717 upcoming matches. The Odds API pipeline (`pipeline/odds.py`) is working but either: (a) not running frequently enough, or (b) the sport key list doesn't cover all active tournaments. 

**Check:** Does `_active_sport_keys()` in `odds.py` include `tennis_atp_french_open`? Slams often require explicit sport keys.

**Also check:** `pipeline/odds_io.py` uses odds-api.io (broader coverage). Is it running on schedule? Is `ODDS_API_IO_KEY` set in Railway?

Fix the scheduler to run both odds pipelines at 07:00, 12:00, and 19:00 UTC (three times daily during Grand Slams).

---

### PHASE 3 — Improve the model (next sprint)

#### P3-1: Backfill `player_ratings_history` retroactively

The 18 RTT features in `features.py` all default to 50.0 for historical training data (2000–2024) because we only have ratings snapshots from May 2026. This means those 18 features contribute almost nothing to model accuracy.

**Solution:** Run `ml/ratings.py` at yearly intervals across Sackmann data to build a point-in-time history. This is computationally expensive (~hours) but would dramatically improve the training signal for the RTT features. Could take model accuracy from current 66.5% toward 68–70%.

---

#### P3-2: Add `slam_winner_ue_ratio` to ML features

`ms_player_career_stats.slam_winner_ue_ratio` is computed and stored for ~1,500 players. This is winners-to-unforced-errors ratio at Grand Slams specifically — a strong predictor of big-match performance that no current feature captures. Add as `p1_slam_wue`, `p2_slam_wue`, `slam_wue_diff`.

---

#### P3-3: Add expected ace totals to model predictions

We now have (or will have with P1-1 and P2-1):
- Per-player historical ace rate by surface from `match_serve_stats`
- Live ace counts from Bzzoiro match detail
- Sackmann `w_ace`/`l_ace` for 644K matches

**Compute and store in `model_predictions`:**
```
expected_aces_p1 = p1_avg_ace_rate_on_surface × expected_service_games
expected_aces_p2 = p2_avg_ace_rate_on_surface × expected_service_games
expected_aces_combined = expected_aces_p1 + expected_aces_p2
```

Surface on the Intelligence tab: *"De Minaur averages 4.2 aces/match on clay. Samuel averages 7.1. Combined expected: 11 aces. Bet over 9.5."*

This also enables the "interesting bets" angle for Marathonbet/Bresbet when they add those markets.

---

#### P3-4: Generate `bet_recommendations` in `model_predictions`

`bet_recommendations` column is 0% populated. The prediction pipeline computes probabilities but never converts them to actionable bet advice. Add logic in `ml/predict.py`:

```python
# Convert model edge to bet recommendation
edge = prob_p1 - implied_prob_from_best_odds_p1
if edge > 0.05:
    bet_recommendations = f"Back {p1_name} — model edge: +{edge:.1%}. Best odds: {best_odds} at {bookie}."
```

This is the core product promise: "is there value here?" answered in plain language.

---

### PHASE 4 — Quick wins (can do anytime)

| Item | Effort | Impact |
|---|---|---|
| Bzzoiro `/rankings/` → `previous_position` shown on match cards (rising/falling indicator) | 1 hour | Visual differentiation on match list |
| Run `player_ratings_history` daily (it already works, just needs scheduler entry) | 10 min | Enables momentum tracking over time |
| Surface `edge` from `player_hand_splits` directly (not just as 0–100 score) | 2 hours | "+8 pts vs lefties" is more legible than score 71 |
| Add `set1_recovery_pct` to Points Analysis tab | 2 hours | High-value bettor metric, data already exists |
| Run `match_ratings` scoring (the table exists, 0 rows) | 4 hours | Enables match quality sort on the homepage |

---

## Quick Reference: Data → Feature → Display

```
Bzzoiro /matches/{id}/ serve stats
  → match_serve_stats (via bzzoiro_ingest.py P1-1)
  → Player avg serve stats by surface (P2-1)
  → Serve tab, Intelligence narrative, ML features (P2-2, P3-3)

player_point_stats clutch data (already computed)
  → API match detail response (P2-2)
  → Points Analysis tab, Intelligence tab
  → ML features: tiebreak_diff, pressure_diff (P2-3)

Bzzoiro /rankings/ (weekly)
  → players.current_rank + ranking_points (P1-2)
  → Match cards, model features, rankings indicator

Sackmann charting sa_charting_points
  → serve_zones aggregation script (P2-5)
  → Serve tab (frontend already built)

aging_curve.age_factor() (already fitted)
  → features.py p1_age_adj, p2_age_adj (P2-4)
  → Better model accuracy on veteran vs young matchups

Expected aces computation (P3-3)
  → model_predictions.expected_aces_combined
  → Intelligence tab, prop bet recommendations
```

---

## Execution Order

1. **`bzzoiro_ingest.py`** — the master unlock. Everything downstream depends on this.
2. **`players.current_rank`** via rankings sync — fixes the stubs on match cards.
3. **`player_point_stats` → API** — biggest immediate impact on match page quality.
4. **Daily `ratings.py`** — fixes the 50-stub epidemic in player_ratings_history.
5. **Serve zones** — Sackmann charting → serve_zones → Serve tab live.
6. **Odds pipeline** — fix scheduler to run 3× daily, ensure all sport keys.
7. **ML feature additions** — clutch stats, aging curve, UE ratio.
8. **Ace predictions** — the new bet angle.
