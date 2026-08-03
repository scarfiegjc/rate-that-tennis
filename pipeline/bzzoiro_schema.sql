-- ratethat.tennis — bzzoiro integration schema additions
-- Run: psql $DATABASE_URL -f pipeline/bzzoiro_schema.sql
-- Safe to run multiple times (all changes are idempotent).

-- ─────────────────────────────────────────────────────────────────────────────
-- 1. bzzoiro match ID on matches table
-- ─────────────────────────────────────────────────────────────────────────────

ALTER TABLE matches ADD COLUMN IF NOT EXISTS bzzoiro_id INTEGER;
CREATE UNIQUE INDEX IF NOT EXISTS idx_matches_bzzoiro_id ON matches(bzzoiro_id) WHERE bzzoiro_id IS NOT NULL;

-- ─────────────────────────────────────────────────────────────────────────────
-- 2. bzzoiro player ID on players table
-- ─────────────────────────────────────────────────────────────────────────────

ALTER TABLE players ADD COLUMN IF NOT EXISTS bzzoiro_id INTEGER;
CREATE UNIQUE INDEX IF NOT EXISTS idx_players_bzzoiro_id ON players(bzzoiro_id) WHERE bzzoiro_id IS NOT NULL;

-- ─────────────────────────────────────────────────────────────────────────────
-- 3. Ranking movement columns on players
-- ─────────────────────────────────────────────────────────────────────────────

-- ranking_movement: positive = moved up (previous_position - current_position)
ALTER TABLE players ADD COLUMN IF NOT EXISTS ranking_movement   INTEGER;
ALTER TABLE players ADD COLUMN IF NOT EXISTS ranking_career_best INTEGER;
ALTER TABLE players ADD COLUMN IF NOT EXISTS ranking_points      INTEGER;

-- ─────────────────────────────────────────────────────────────────────────────
-- 4. Live match data column on matches
-- ─────────────────────────────────────────────────────────────────────────────

-- Stores current set/game/point + serve stats from bzzoiro live endpoint
ALTER TABLE matches ADD COLUMN IF NOT EXISTS live_data JSONB;

-- ─────────────────────────────────────────────────────────────────────────────
-- 5. SEO match preview columns on matches
-- ─────────────────────────────────────────────────────────────────────────────

-- 250-word AI-generated match preview. Persists after match ends.
ALTER TABLE matches ADD COLUMN IF NOT EXISTS seo_preview              TEXT;
ALTER TABLE matches ADD COLUMN IF NOT EXISTS seo_preview_generated_at TIMESTAMPTZ;

-- ─────────────────────────────────────────────────────────────────────────────
-- 6. bzzoiro_predictions — O/U markets + match winner predictions
-- ─────────────────────────────────────────────────────────────────────────────

-- Supplements model_predictions — bzzoiro's own model predictions stored separately
-- so they don't conflict with our ML output.
CREATE TABLE IF NOT EXISTS bzzoiro_predictions (
    id                          SERIAL PRIMARY KEY,
    match_id                    INTEGER REFERENCES matches(id),
    bzzoiro_match_id            INTEGER,
    bzzoiro_prediction_id       INTEGER,
    prob_player1_wins           NUMERIC(5,4),
    prob_player2_wins           NUMERIC(5,4),
    predicted_winner            TEXT,
    confidence                  NUMERIC(5,4),
    expected_total_sets         NUMERIC(4,2),
    prob_over_2_5_sets          NUMERIC(5,4),
    expected_total_games        NUMERIC(5,2),
    prob_over_20_5_games        NUMERIC(5,4),
    prob_over_21_5_games        NUMERIC(5,4),
    prob_over_22_5_games        NUMERIC(5,4),
    prob_player1_wins_first_set NUMERIC(5,4),
    actual_winner               TEXT,
    was_winner_correct          BOOLEAN,
    synced_at                   TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(bzzoiro_prediction_id)
);

CREATE INDEX IF NOT EXISTS idx_bzzoiro_predictions_match
    ON bzzoiro_predictions(match_id);

CREATE INDEX IF NOT EXISTS idx_bzzoiro_predictions_bzz_match
    ON bzzoiro_predictions(bzzoiro_match_id);

-- ─────────────────────────────────────────────────────────────────────────────
-- 7. bzzoiro_h2h — H2H cache per match
-- ─────────────────────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS bzzoiro_h2h (
    id              SERIAL PRIMARY KEY,
    match_id        INTEGER REFERENCES matches(id),
    player1_id      INTEGER REFERENCES players(id),
    player2_id      INTEGER REFERENCES players(id),
    h2h_data        JSONB,   -- full H2H response from /matches/{id}/h2h/
    player1_last5   JSONB,   -- last 5 matches for player 1
    player2_last5   JSONB,   -- last 5 matches for player 2
    synced_at       TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(match_id)
);

CREATE INDEX IF NOT EXISTS idx_bzzoiro_h2h_player1 ON bzzoiro_h2h(player1_id);
CREATE INDEX IF NOT EXISTS idx_bzzoiro_h2h_player2 ON bzzoiro_h2h(player2_id);

-- ─────────────────────────────────────────────────────────────────────────────
-- 8. bzzoiro_point_by_point — set → game → point granularity per finished match
-- Added 2026-08 audit: genuinely new Bzzoiro endpoint not previously ingested.
-- Stored as raw JSONB (sets[].games[].points[]) so richer parsing/aggregation
-- (e.g. into serve_zones-style stats) can be layered on without re-fetching.
-- ─────────────────────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS bzzoiro_point_by_point (
    id          SERIAL PRIMARY KEY,
    match_id    INTEGER REFERENCES matches(id),
    available   BOOLEAN DEFAULT FALSE,
    sets        JSONB,   -- [{duration_seconds, games:[{server,winner,break,player1_games,player2_games,points:[...]}]}]
    synced_at   TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(match_id)
);

CREATE INDEX IF NOT EXISTS idx_bzzoiro_pbp_match ON bzzoiro_point_by_point(match_id);

-- ─────────────────────────────────────────────────────────────────────────────
-- Done
-- ─────────────────────────────────────────────────────────────────────────────

SELECT 'bzzoiro schema additions applied successfully' AS status;
