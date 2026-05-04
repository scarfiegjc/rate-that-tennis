# RTT Rating System — Technical Specification

> This document defines how every player rating on ratethat.tennis is computed.
> See `CLAUDE.md` for the project overview and the rating taxonomy summary.

---

## Design principles

1. **Proprietary ≠ secret.** The ratings are proprietary because of *how* they're computed,
   not what they measure. The methodology below is intentional and defensible.
2. **Normalised population scores.** A rating of 85 means the same thing on any player card:
   that player sits at the 85th percentile of the active player population on that dimension.
3. **Quality-weighted.** Beating the world #1 moves your rating more than beating a #200 wildcard.
4. **Surface-independent.** Clay, hard, and grass ratings are computed from surface-specific
   match subsets only — a player's hard-court stats have zero influence on their clay rating.
5. **Time-decayed.** Matches from 3 years ago are almost irrelevant. Use an exponential decay
   with a 180-day half-life so current form dominates.
6. **Calibrated.** Ratings feed the match predictor. They must be stable and consistent, not
   noisy — smooth over outlier matches rather than reacting wildly to a single result.

---

## Data sources

All ratings are derived from the **Sackmann `sa_matches` table** (historical, ~3M matches)
combined with the live **`matches` and `match_scores` tables** (current season).

### Key columns from `sa_matches`

```
Surface / context:
  surface            -- 'Clay' | 'Hard' | 'Grass' | 'Carpet'
  tourney_level      -- 'G'=Slam, 'M'=Masters, 'A'=500/250, 'C'=Challenger, 'S'=ITF/Satellite
  tourney_date       -- match date (for time decay)
  round              -- 'F', 'SF', 'QF', 'R16', 'R32', 'R64', 'R128', 'RR'

Player context:
  winner_rank, loser_rank              -- ATP/WTA ranking at time of match
  winner_rank_points, loser_rank_points
  winner_age, loser_age
  winner_ht, loser_ht                  -- height in cm

Winner serve stats (l_ prefix = loser equivalents):
  w_ace              -- aces
  w_df               -- double faults
  w_svpt             -- total serve points played
  w_1stIn            -- 1st serves in
  w_1stWon           -- 1st serve points won
  w_2ndWon           -- 2nd serve points won
  w_SvGms            -- service games played
  w_bpSaved          -- break points saved
  w_bpFaced          -- break points faced

Score / duration:
  score              -- e.g. '6-3 6-4' or '6-3 4-6 7-6(4)'
  minutes            -- match duration
  best_of            -- 3 or 5
```

### Derived stats (compute before rating)

```python
# Per-match, per-player
first_serve_pct     = w_1stIn / w_svpt
first_serve_won_pct = w_1stWon / w_1stIn
second_serve_won_pct= w_2ndWon / (w_svpt - w_1stIn)
bp_save_pct         = w_bpSaved / w_bpFaced       # handle w_bpFaced=0
ace_per_game        = w_ace / w_SvGms
df_per_game         = w_df / w_SvGms
return_pts_won_pct  = 1.0 - (l_1stWon/l_1stIn * l_1stIn/l_svpt
                             + l_2ndWon/(l_svpt-l_1stIn) * (1 - l_1stIn/l_svpt))
bp_conversion_pct   = (l_bpFaced - l_bpSaved) / l_bpFaced  # break points converted
games_won_pct       = winner_games / total_games  # parse from score string
```

---

## Time decay

Weight every historical match by how recent it is:

```python
import numpy as np
from datetime import date

HALF_LIFE_DAYS = 180   # matches 6 months ago have half the weight of today's

def decay_weight(match_date: date, reference_date: date = None) -> float:
    if reference_date is None:
        reference_date = date.today()
    days_ago = (reference_date - match_date).days
    if days_ago < 0:
        return 0.0   # future match — skip
    lam = np.log(2) / HALF_LIFE_DAYS
    return np.exp(-lam * days_ago)
```

Apply this weight to every match when computing rolling statistics. Matches older than
**3 years** (1095 days) are excluded entirely (weight rounds to < 0.02).

---

## Quality weighting

Weight each match by the strength of the opponent at the time:

```python
def quality_weight(opponent_rank: int) -> float:
    """
    Returns a weight in [0.1, 1.0] based on opponent ranking.
    Top-5 player = weight ~1.0
    Rank 50 = weight ~0.65
    Rank 200 = weight ~0.25
    Unranked / >500 = weight 0.1
    """
    if opponent_rank is None or opponent_rank > 500:
        return 0.10
    # Sigmoid centred on rank 100, full weight by top 5
    return float(np.clip(1.0 / (1.0 + np.exp(0.02 * (opponent_rank - 30))), 0.10, 1.00))
```

The **combined match weight** is `decay_weight × quality_weight`. Use this for all
weighted-average computations below.

---

## Computing each rating

### RTT Score (composite)

A weighted average of the four surface ratings and the five skill ratings, with surface
ratings weighted by how many matches the player has played on each surface (so a clay
specialist isn't penalised for having few grass matches):

```python
surface_weights = {
    'clay':   clay_match_count / total_match_count,
    'hard':   hard_match_count / total_match_count,
    'grass':  grass_match_count / total_match_count,
    'indoor': indoor_match_count / total_match_count,
}

# Blend surface ratings by surface exposure
surface_composite = sum(surface_weights[s] * surface_ratings[s] for s in surface_weights)

# Equal-weight skill ratings
skill_composite = mean([serve_rating, return_rating, net_game_rating,
                        pressure_rating, consistency_rating])

# RTT Score: 60% surface composite, 40% skills
rtt_score = 0.60 * surface_composite + 0.40 * skill_composite
```

### Surface ratings (clay / hard / grass / indoor)

Compute independently per surface using only matches on that surface:

```python
def compute_surface_rating(player_matches_on_surface: list) -> float:
    """
    Each match contributes a 'performance score' weighted by time decay × quality.
    Performance score: 100 if won, scaled by match quality; 0–50 if lost, scaled by quality.
    """
    total_weight = 0.0
    weighted_score = 0.0

    for match in player_matches_on_surface:
        w = decay_weight(match.date) * quality_weight(match.opponent_rank)
        if match.won:
            score = 100.0
        else:
            # Losing to a top-5 player is more forgivable than losing to a #200
            score = max(0, 50.0 - 0.1 * match.opponent_rank)
        weighted_score += w * score
        total_weight += w

    raw = weighted_score / total_weight if total_weight > 0 else 50.0
    return normalise_to_population(raw, dimension='surface')
```

### Serve rating

Composite of four serve metrics, each computed as a quality-weighted rolling average:

| Component | Weight | Derived from |
|---|---|---|
| 1st serve in % | 20% | `w_1stIn / w_svpt` |
| 1st serve won % | 35% | `w_1stWon / w_1stIn` |
| 2nd serve won % | 25% | `w_2ndWon / (w_svpt - w_1stIn)` |
| BP saved % | 20% | `w_bpSaved / w_bpFaced` |

Normalise the composite across the population to 0–100.

### Return rating

| Component | Weight | Derived from |
|---|---|---|
| Return points won % | 50% | Opponent's serve won % inverted |
| BP conversion % | 35% | `(l_bpFaced - l_bpSaved) / l_bpFaced` |
| Return games won % | 15% | Derived from score string |

### Net game rating

Direct net stats are not in the Sackmann dataset. Use a proxy:

- **Ace-to-DF ratio** as a serve aggressiveness proxy: `w_ace / (w_ace + w_df)`
- **Win % in short matches** (< 75 minutes) as a net-game proxy (net players win fast)
- When Hawk-Eye or Match Charting Project data becomes available, replace with
  `net_points_won / net_points_played`

Until direct net data is available, weight net_game_rating at 50% of its eventual target
contribution and flag it as `estimated: true` in the API response.

### Pressure rating

| Component | Weight | Derived from |
|---|---|---|
| Tiebreak win % | 40% | Parse score strings for tiebreaks, compute win rate |
| Deciding-set win % | 35% | Matches reaching the final set, win rate |
| Close-match win % (5+ games in final set) | 25% | Parse score strings |

### Consistency rating

Inverse of variance in performance — a player who beats everyone they should beat:

| Component | Weight | Derived from |
|---|---|---|
| Win % vs lower-ranked opponents (rank > own rank + 50) | 40% | `winner_rank > loser_rank + 50` |
| DF rate (inverted) | 30% | `w_df / w_svpt` normalised and inverted |
| Bagel sets given (inverted) | 30% | Count `6-0` sets where player was the `6` side |

### Form rating

Rolling 10-match performance index using the **most recent 10 completed matches**,
weighted by quality only (no time decay — recency is already enforced by the 10-match window):

```python
def compute_form_rating(last_10_matches: list) -> float:
    scores = []
    for match in last_10_matches:
        q = quality_weight(match.opponent_rank)
        perf = 100.0 * q if match.won else 50.0 * (1 - q)
        scores.append(perf)
    return normalise_to_population(mean(scores), dimension='form')
```

Momentum is derived by comparing the rolling 5-match form to the rolling 10-match form:
- `rising` if last-5 average > last-10 average by more than 3 points
- `falling` if last-5 average < last-10 average by more than 3 points
- `stable` otherwise

### Big match rating

Restrict to `tourney_level IN ('G', 'M')` (Slams and Masters 1000 only):

Use the same surface-rating computation applied to this filtered match subset.
Minimum 15 qualifying matches required; otherwise return `null` (not shown on UI).

### vs_top10_rating

Restrict to matches where `opponent_rank <= 10` at time of match.
Use the same composite performance computation.
Minimum 10 qualifying matches required; otherwise return `null`.

---

## Normalisation

All raw scores must be normalised to 0–100 against the current active player population:

```python
from scipy.stats import percentileofscore

def normalise_to_population(raw_score: float, dimension: str,
                             active_player_scores: list) -> float:
    """
    Maps a raw metric to a 0–100 scale based on current population distribution.
    Uses percentile rank with a small smoothing factor to avoid exact 0 and 100.
    """
    pct = percentileofscore(active_player_scores, raw_score, kind='mean')
    # Compress slightly: 2nd–98th percentile maps to 5–95, then scale to 0–100
    return float(np.clip(pct, 0, 100))
```

**Active player** = any player with >= 5 matches in the past 18 months.

Normalisation must be recomputed whenever the full population is re-rated (weekly cadence
is sufficient). Store the population percentile breakpoints in a `rating_calibration` table
so the frontend can show accurate tier labels without recomputing.

---

## Update cadence

| Rating type | Update frequency | Trigger |
|---|---|---|
| Surface ratings, RTT Score | Daily (after pipeline) | `daily_fixtures` job completes |
| Form rating, momentum | Daily | Same |
| Skill ratings | Weekly (Sunday midnight) | Cron |
| Big match, vs Top 10 | Weekly | Cron |
| player_ratings_history row | Daily snapshot | After ratings update |

---

## Schema additions required

Beyond `player_ratings` (which already exists as a snapshot table):

```sql
-- Rolling history for form chart
CREATE TABLE player_ratings_history (
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
    momentum           TEXT,          -- 'rising' | 'stable' | 'falling'
    big_match_rating   NUMERIC(5,2),
    vs_top10_rating    NUMERIC(5,2),
    match_count        INTEGER,       -- total matches used in computation
    UNIQUE(player_id, rated_at)
);
CREATE INDEX idx_prh_player_date ON player_ratings_history(player_id, rated_at DESC);

-- Population calibration checkpoints
CREATE TABLE rating_calibration (
    id           SERIAL PRIMARY KEY,
    dimension    TEXT NOT NULL,   -- e.g. 'clay_rating', 'serve_rating'
    calibrated_at DATE NOT NULL,
    p10          NUMERIC(5,2),    -- 10th percentile raw score
    p25          NUMERIC(5,2),
    p50          NUMERIC(5,2),
    p75          NUMERIC(5,2),
    p90          NUMERIC(5,2),
    player_count INTEGER,
    UNIQUE(dimension, calibrated_at)
);
```

Also add to `player_ratings` (existing table):

```sql
ALTER TABLE player_ratings
    ADD COLUMN IF NOT EXISTS indoor_rating      NUMERIC(5,2),
    ADD COLUMN IF NOT EXISTS net_game_rating    NUMERIC(5,2),
    ADD COLUMN IF NOT EXISTS return_rating      NUMERIC(5,2),
    ADD COLUMN IF NOT EXISTS pressure_rating    NUMERIC(5,2),
    ADD COLUMN IF NOT EXISTS big_match_rating   NUMERIC(5,2),
    ADD COLUMN IF NOT EXISTS vs_top10_rating    NUMERIC(5,2),
    ADD COLUMN IF NOT EXISTS momentum           TEXT,
    ADD COLUMN IF NOT EXISTS rtt_score          NUMERIC(5,2);
```

---

## Rating tier labels (for UI)

| Score | Tier label | Colour |
|---|---|---|
| 90–100 | Elite | Deep green `#3B6D11` |
| 82–89 | Strong | Green `#639922` |
| 72–81 | Average | Gray `#888780` |
| 62–71 | Below average | Amber `#EF9F27` |
| < 62 | Poor | Red `#E24B4A` |

These thresholds are fixed (not population-relative) so bettors learn a consistent vocabulary.
They correspond roughly to the 90th, 75th, 50th, and 30th population percentiles.
