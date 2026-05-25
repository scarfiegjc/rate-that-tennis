-- ratethat.tennis — Schema additions for match engine + rating system
-- From docs/match-engine-spec.md and docs/ratings-spec.md
-- Run: psql $DATABASE_URL -f pipeline/schema_additions.sql
-- Safe to run multiple times (all changes are idempotent).

-- ─────────────────────────────────────────────────────────────────────────────
-- 1. Extend player_ratings with new rating dimensions
-- ─────────────────────────────────────────────────────────────────────────────

ALTER TABLE player_ratings
    ADD COLUMN IF NOT EXISTS indoor_rating      NUMERIC(5,2),
    ADD COLUMN IF NOT EXISTS net_game_rating    NUMERIC(5,2),
    ADD COLUMN IF NOT EXISTS return_rating      NUMERIC(5,2),
    ADD COLUMN IF NOT EXISTS pressure_rating    NUMERIC(5,2),
    ADD COLUMN IF NOT EXISTS big_match_rating   NUMERIC(5,2),
    ADD COLUMN IF NOT EXISTS vs_top10_rating    NUMERIC(5,2),
    ADD COLUMN IF NOT EXISTS momentum           TEXT CHECK (momentum IN ('rising','stable','falling')),
    ADD COLUMN IF NOT EXISTS rtt_score          NUMERIC(5,2);

-- ─────────────────────────────────────────────────────────────────────────────
-- 2. player_ratings_history — daily snapshots for form chart
-- ─────────────────────────────────────────────────────────────────────────────

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
    momentum           TEXT CHECK (momentum IN ('rising','stable','falling')),
    big_match_rating   NUMERIC(5,2),
    vs_top10_rating    NUMERIC(5,2),
    match_count        INTEGER,
    UNIQUE(player_id, rated_at)
);

CREATE INDEX IF NOT EXISTS idx_prh_player_date
    ON player_ratings_history(player_id, rated_at DESC);

-- ─────────────────────────────────────────────────────────────────────────────
-- 3. model_predictions — match win probability + reasoning
-- ─────────────────────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS model_predictions (
    id                    SERIAL PRIMARY KEY,
    match_id              INTEGER UNIQUE NOT NULL REFERENCES matches(id),
    prob_first_player     NUMERIC(5,4),
    prob_second_player    NUMERIC(5,4),
    confidence            TEXT CHECK (confidence IN ('high','medium','low')),
    key_factors           JSONB,
    narrative             TEXT,
    analogue_match_id     INTEGER REFERENCES sa_matches(id),
    analogue_description  TEXT,
    bet_recommendations   JSONB,
    model_version         TEXT DEFAULT 'v1',
    predicted_at          TIMESTAMPTZ DEFAULT NOW()
);

-- Add missing columns if table already exists from earlier schema
ALTER TABLE model_predictions
    ADD COLUMN IF NOT EXISTS narrative             TEXT,
    ADD COLUMN IF NOT EXISTS analogue_match_id     INTEGER REFERENCES sa_matches(id),
    ADD COLUMN IF NOT EXISTS analogue_description  TEXT,
    ADD COLUMN IF NOT EXISTS bet_recommendations   JSONB;

-- Ace / double-fault prediction columns (populated by ml/predict.py)
ALTER TABLE model_predictions
    ADD COLUMN IF NOT EXISTS expected_aces_p1       FLOAT,
    ADD COLUMN IF NOT EXISTS expected_aces_p2       FLOAT,
    ADD COLUMN IF NOT EXISTS expected_aces_combined FLOAT,
    ADD COLUMN IF NOT EXISTS expected_dfs_p1        FLOAT,
    ADD COLUMN IF NOT EXISTS expected_dfs_p2        FLOAT;

-- ─────────────────────────────────────────────────────────────────────────────
-- 4. bookmaker_odds — for edge calculation
-- ─────────────────────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS bookmaker_odds (
    id              SERIAL PRIMARY KEY,
    match_id        INTEGER NOT NULL REFERENCES matches(id),
    bookmaker       TEXT NOT NULL,
    player_ref      TEXT NOT NULL CHECK (player_ref IN ('first_player','second_player')),
    decimal_odds    NUMERIC(8,4),
    implied_prob    NUMERIC(5,4),
    fetched_at      TIMESTAMPTZ DEFAULT NOW()
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_odds_match_bm_player
    ON bookmaker_odds(match_id, bookmaker, player_ref);

CREATE INDEX IF NOT EXISTS idx_odds_match
    ON bookmaker_odds(match_id, fetched_at DESC);

-- ─────────────────────────────────────────────────────────────────────────────
-- 5. rating_calibration — population percentile checkpoints
-- ─────────────────────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS rating_calibration (
    id             SERIAL PRIMARY KEY,
    dimension      TEXT NOT NULL,
    calibrated_at  DATE NOT NULL,
    p10            NUMERIC(5,2),
    p25            NUMERIC(5,2),
    p50            NUMERIC(5,2),
    p75            NUMERIC(5,2),
    p90            NUMERIC(5,2),
    player_count   INTEGER,
    UNIQUE(dimension, calibrated_at)
);

-- ─────────────────────────────────────────────────────────────────────────────
-- 6. serve_zones — serve placement data (charting project + future Hawk-Eye)
-- ─────────────────────────────────────────────────────────────────────────────

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

-- ─────────────────────────────────────────────────────────────────────────────
-- Done
-- ─────────────────────────────────────────────────────────────────────────────

-- ─────────────────────────────────────────────────────────────────────────────
-- 7. bookmaker_affiliates — affiliate URLs per bookmaker (admin-managed)
-- ─────────────────────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS bookmaker_affiliates (
    bookmaker_key   TEXT PRIMARY KEY,          -- matches bookmaker_odds.bookmaker
    display_name    TEXT NOT NULL,
    affiliate_url   TEXT,                      -- set when affiliate deal is live
    homepage_url    TEXT,                      -- fallback link for users
    is_active       BOOLEAN NOT NULL DEFAULT true,
    priority        INTEGER NOT NULL DEFAULT 50,  -- lower = show first
    notes           TEXT,
    updated_at      TIMESTAMPTZ DEFAULT NOW()
);

-- Pre-populate with the two bookmakers we fetch odds for
INSERT INTO bookmaker_affiliates (bookmaker_key, display_name, homepage_url, priority)
VALUES
    ('Bet365',  'bet365',  'https://www.bet365.com', 10),
    ('Unibet',  'Unibet',  'https://www.unibet.com', 20)
ON CONFLICT (bookmaker_key) DO NOTHING;

-- ─────────────────────────────────────────────────────────────────────────────
-- Unique constraint on player_external_ids(player_id, source) — needed for
-- ON CONFLICT upserts in bzzoiro_ingest.py.  Deduplicate first; then add.
-- ─────────────────────────────────────────────────────────────────────────────

-- Remove duplicate (player_id, source) rows, keeping the highest-confidence/latest entry
DELETE FROM player_external_ids
WHERE id IN (
    SELECT id FROM (
        SELECT id,
               ROW_NUMBER() OVER (
                   PARTITION BY player_id, source
                   ORDER BY
                       CASE confidence WHEN 'high' THEN 1 WHEN 'medium' THEN 2 WHEN 'manual' THEN 3 WHEN 'low' THEN 4 END,
                       id DESC
               ) AS rn
        FROM player_external_ids
    ) ranked
    WHERE rn > 1
);

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'player_external_ids_player_source_key'
    ) THEN
        ALTER TABLE player_external_ids
            ADD CONSTRAINT player_external_ids_player_source_key UNIQUE (player_id, source);
    END IF;
END $$;

-- Add expected_aces / expected_dfs columns to model_predictions
ALTER TABLE model_predictions ADD COLUMN IF NOT EXISTS expected_aces_p1       FLOAT;
ALTER TABLE model_predictions ADD COLUMN IF NOT EXISTS expected_aces_p2       FLOAT;
ALTER TABLE model_predictions ADD COLUMN IF NOT EXISTS expected_aces_combined FLOAT;
ALTER TABLE model_predictions ADD COLUMN IF NOT EXISTS expected_dfs_p1        FLOAT;
ALTER TABLE model_predictions ADD COLUMN IF NOT EXISTS expected_dfs_p2        FLOAT;

-- ─────────────────────────────────────────────────────────────────────────────
-- Deactivate all v1 betting systems — underperforming, cleared 2026-05-13
-- The systems infrastructure stays in place for future v2 systems.
-- ─────────────────────────────────────────────────────────────────────────────
UPDATE systems SET is_active = FALSE
WHERE code IN (
    'surface_monster', 'form_surge', 'hand_advantage',
    'big_match_player', 'underdog_value', 'rtt_mismatch', 'clutch_in_decider'
);

SELECT 'Schema additions applied successfully' AS status;
