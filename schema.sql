-- ============================================================
-- ratethat.tennis — PostgreSQL Schema
-- ============================================================
-- Generated: 2026-05-01
-- Source API: api-tennis.com
-- ============================================================

-- Extensions
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS "pg_trgm"; -- for fuzzy player name search

-- ============================================================
-- REFERENCE / LOOKUP TABLES
-- ============================================================

CREATE TABLE IF NOT EXISTS event_types (
    id              SERIAL PRIMARY KEY,
    api_key         INTEGER UNIQUE NOT NULL,  -- e.g. 265
    type_name       TEXT NOT NULL,             -- e.g. "Atp Singles"
    tour_category   TEXT,                      -- 'ATP', 'WTA', 'ITF', 'Challenger', 'Exhibition', 'Junior', 'Teams'
    gender          TEXT,                      -- 'Men', 'Women', 'Mixed', null
    is_doubles      BOOLEAN DEFAULT FALSE,
    created_at      TIMESTAMPTZ DEFAULT NOW()
);

COMMENT ON TABLE event_types IS 'Tennis tour/category types from api-tennis get_events endpoint';

CREATE TABLE IF NOT EXISTS surfaces (
    id      SERIAL PRIMARY KEY,
    name    TEXT UNIQUE NOT NULL  -- 'Clay', 'Hard', 'Grass', 'Carpet', 'Indoor Hard', etc.
);

INSERT INTO surfaces (name) VALUES
    ('Clay'), ('Hard'), ('Grass'), ('Carpet'), ('Indoor Hard'), ('Indoor Clay'), ('Unknown')
ON CONFLICT (name) DO NOTHING;

-- ============================================================
-- TOURNAMENTS
-- ============================================================

CREATE TABLE IF NOT EXISTS tournaments (
    id              SERIAL PRIMARY KEY,
    api_key         INTEGER UNIQUE NOT NULL,   -- tournament_key from API
    name            TEXT NOT NULL,
    event_type_id   INTEGER REFERENCES event_types(id),
    surface_id      INTEGER REFERENCES surfaces(id),
    country         TEXT,
    city            TEXT,
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    updated_at      TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_tournaments_event_type ON tournaments(event_type_id);
CREATE INDEX IF NOT EXISTS idx_tournaments_name ON tournaments USING gin(name gin_trgm_ops);

COMMENT ON TABLE tournaments IS 'Tennis tournaments. api_key = tournament_key from api-tennis';

-- ============================================================
-- PLAYERS
-- ============================================================

CREATE TABLE IF NOT EXISTS players (
    id              SERIAL PRIMARY KEY,
    api_key         INTEGER UNIQUE NOT NULL,   -- player_key from API
    name            TEXT NOT NULL,             -- short name e.g. "N. Djokovic"
    full_name       TEXT,                      -- full name if available
    country         TEXT,
    country_code    TEXT,                      -- ISO 3166 alpha-2
    birthday        DATE,
    logo_url        TEXT,
    hand            TEXT,                      -- 'Right', 'Left', 'Unknown'
    turned_pro      INTEGER,                   -- year
    height_cm       INTEGER,
    is_active       BOOLEAN DEFAULT TRUE,
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    updated_at      TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_players_name ON players USING gin(name gin_trgm_ops);
CREATE INDEX IF NOT EXISTS idx_players_country ON players(country_code);

-- ============================================================
-- MATCHES (FIXTURES / EVENTS)
-- ============================================================

CREATE TABLE IF NOT EXISTS matches (
    id                      SERIAL PRIMARY KEY,
    api_event_key           BIGINT UNIQUE NOT NULL,    -- event_key from API
    tournament_id           INTEGER REFERENCES tournaments(id),
    event_type_id           INTEGER REFERENCES event_types(id),

    -- Players (singles or doubles pair represented as single player record)
    first_player_id         INTEGER REFERENCES players(id),
    second_player_id        INTEGER REFERENCES players(id),

    -- Match metadata
    event_date              DATE NOT NULL,
    event_time              TIME,
    tournament_round        TEXT,              -- e.g. "Quarter-finals"
    season                  TEXT,              -- e.g. "2026"
    is_qualification        BOOLEAN DEFAULT FALSE,
    is_doubles              BOOLEAN DEFAULT FALSE,

    -- Result
    final_result            TEXT,              -- e.g. "2 - 1" (sets)
    game_result             TEXT,              -- current game score if live
    serve                   TEXT,              -- "First Player" | "Second Player"
    winner                  TEXT,              -- "First Player" | "Second Player"
    event_status            TEXT,              -- "Finished", "Set 1", "Cancelled", etc.
    is_live                 BOOLEAN DEFAULT FALSE,

    -- Raw data for reference
    raw_json                JSONB,

    created_at              TIMESTAMPTZ DEFAULT NOW(),
    updated_at              TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_matches_date ON matches(event_date);
CREATE INDEX IF NOT EXISTS idx_matches_tournament ON matches(tournament_id);
CREATE INDEX IF NOT EXISTS idx_matches_first_player ON matches(first_player_id);
CREATE INDEX IF NOT EXISTS idx_matches_second_player ON matches(second_player_id);
CREATE INDEX IF NOT EXISTS idx_matches_status ON matches(event_status);
CREATE INDEX IF NOT EXISTS idx_matches_live ON matches(is_live) WHERE is_live = TRUE;

COMMENT ON TABLE matches IS 'All match events. api_event_key = event_key from api-tennis';

-- ============================================================
-- SET SCORES
-- ============================================================

CREATE TABLE IF NOT EXISTS match_scores (
    id              SERIAL PRIMARY KEY,
    match_id        INTEGER NOT NULL REFERENCES matches(id) ON DELETE CASCADE,
    set_number      INTEGER NOT NULL,          -- 1, 2, 3, 4, 5
    score_first     TEXT,                      -- e.g. "6" or "7.6" for tiebreak
    score_second    TEXT,
    is_tiebreak     BOOLEAN DEFAULT FALSE,
    UNIQUE(match_id, set_number)
);

CREATE INDEX IF NOT EXISTS idx_match_scores_match ON match_scores(match_id);

-- ============================================================
-- POINT-BY-POINT DATA
-- ============================================================

CREATE TABLE IF NOT EXISTS match_games (
    id              SERIAL PRIMARY KEY,
    match_id        INTEGER NOT NULL REFERENCES matches(id) ON DELETE CASCADE,
    set_number      INTEGER NOT NULL,
    game_number     INTEGER NOT NULL,
    player_served   TEXT,                      -- "First Player" | "Second Player"
    serve_winner    TEXT,
    score_after     TEXT,                      -- set score after game e.g. "3 - 2"
    UNIQUE(match_id, set_number, game_number)
);

CREATE INDEX IF NOT EXISTS idx_match_games_match ON match_games(match_id);

CREATE TABLE IF NOT EXISTS match_points (
    id              SERIAL PRIMARY KEY,
    game_id         INTEGER NOT NULL REFERENCES match_games(id) ON DELETE CASCADE,
    match_id        INTEGER NOT NULL REFERENCES matches(id) ON DELETE CASCADE,
    point_number    INTEGER NOT NULL,
    score           TEXT,                      -- e.g. "15 - 0"
    is_break_point  BOOLEAN DEFAULT FALSE,
    is_set_point    BOOLEAN DEFAULT FALSE,
    is_match_point  BOOLEAN DEFAULT FALSE,
    UNIQUE(game_id, point_number)
);

CREATE INDEX IF NOT EXISTS idx_match_points_game ON match_points(game_id);
CREATE INDEX IF NOT EXISTS idx_match_points_match ON match_points(match_id);

-- ============================================================
-- AI / USER RATINGS — MATCHES
-- ============================================================

CREATE TABLE IF NOT EXISTS match_ratings (
    id                  SERIAL PRIMARY KEY,
    match_id            INTEGER UNIQUE NOT NULL REFERENCES matches(id) ON DELETE CASCADE,

    -- Composite rating scores (0-100)
    excitement_score    NUMERIC(5,2),          -- how exciting/dramatic was the match
    quality_score       NUMERIC(5,2),          -- level of tennis played
    upset_score         NUMERIC(5,2),          -- how unexpected the result was
    overall_score       NUMERIC(5,2),          -- headline ratethat.tennis score

    -- Rating inputs
    num_sets            INTEGER,
    num_tiebreaks       INTEGER,
    num_break_points    INTEGER,
    deciding_set        BOOLEAN DEFAULT FALSE,
    set_scores          TEXT,                  -- human-readable e.g. "6-3, 4-6, 7-6"

    -- AI narrative
    headline            TEXT,                  -- 1-line match description
    analysis            TEXT,                  -- full AI analysis paragraph
    key_moments         TEXT[],                -- array of key moment strings
    surface_relevance   TEXT,                  -- how surface affected play

    -- Metadata
    model_version       TEXT DEFAULT 'v1',
    rated_at            TIMESTAMPTZ DEFAULT NOW(),
    updated_at          TIMESTAMPTZ DEFAULT NOW()
);

COMMENT ON TABLE match_ratings IS 'AI-generated match quality and excitement ratings';

-- ============================================================
-- AI / USER RATINGS — PLAYERS
-- ============================================================

CREATE TABLE IF NOT EXISTS player_ratings (
    id                  SERIAL PRIMARY KEY,
    player_id           INTEGER UNIQUE NOT NULL REFERENCES players(id) ON DELETE CASCADE,

    -- Overall ratings (0-100)
    overall_rating      NUMERIC(5,2),
    form_score          NUMERIC(5,2),          -- recent form (last 10 matches)
    consistency_score   NUMERIC(5,2),
    serve_rating        NUMERIC(5,2),

    -- Surface ratings (0-100)
    clay_rating         NUMERIC(5,2),
    hard_rating         NUMERIC(5,2),
    grass_rating        NUMERIC(5,2),

    -- Recent form window
    form_window_matches INTEGER DEFAULT 10,
    form_wins           INTEGER,
    form_losses         INTEGER,
    form_sets_won       INTEGER,
    form_sets_lost      INTEGER,

    -- Narrative
    form_summary        TEXT,                  -- AI paragraph about current form
    strengths           TEXT[],                -- e.g. ['Big serve', 'Clay specialist']
    weaknesses          TEXT[],

    -- Meta
    model_version       TEXT DEFAULT 'v1',
    calculated_at       TIMESTAMPTZ DEFAULT NOW(),
    updated_at          TIMESTAMPTZ DEFAULT NOW()
);

COMMENT ON TABLE player_ratings IS 'AI-generated player form and quality ratings';

-- Surface-specific win/loss stats
CREATE TABLE IF NOT EXISTS player_surface_stats (
    id          SERIAL PRIMARY KEY,
    player_id   INTEGER NOT NULL REFERENCES players(id) ON DELETE CASCADE,
    surface_id  INTEGER NOT NULL REFERENCES surfaces(id),
    season      TEXT,                          -- NULL = all-time
    wins        INTEGER DEFAULT 0,
    losses      INTEGER DEFAULT 0,
    updated_at  TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(player_id, surface_id, season)
);

CREATE INDEX IF NOT EXISTS idx_surface_stats_player ON player_surface_stats(player_id);

-- ============================================================
-- PIPELINE / ETL TRACKING
-- ============================================================

CREATE TABLE IF NOT EXISTS pipeline_runs (
    id                  SERIAL PRIMARY KEY,
    job_type            TEXT NOT NULL,         -- 'daily_fixtures', 'livescore', 'player_sync', 'ratings'
    target_date         DATE,                  -- which date was fetched (for daily jobs)
    started_at          TIMESTAMPTZ DEFAULT NOW(),
    completed_at        TIMESTAMPTZ,
    status              TEXT DEFAULT 'running', -- 'running', 'success', 'failed', 'partial'
    records_fetched     INTEGER DEFAULT 0,
    records_inserted    INTEGER DEFAULT 0,
    records_updated     INTEGER DEFAULT 0,
    error_message       TEXT,
    api_calls_made      INTEGER DEFAULT 0,
    metadata            JSONB
);

CREATE INDEX IF NOT EXISTS idx_pipeline_runs_job ON pipeline_runs(job_type, started_at DESC);
CREATE INDEX IF NOT EXISTS idx_pipeline_runs_date ON pipeline_runs(target_date);

-- ============================================================
-- HELPER VIEWS
-- ============================================================

CREATE OR REPLACE VIEW v_matches_with_details AS
SELECT
    m.id,
    m.api_event_key,
    m.event_date,
    m.event_time,
    m.event_status,
    m.is_live,
    t.name AS tournament_name,
    et.type_name AS event_type,
    et.tour_category,
    s.name AS surface,
    m.tournament_round,
    m.season,
    m.is_qualification,
    m.is_doubles,
    p1.name AS first_player_name,
    p1.country AS first_player_country,
    p2.name AS second_player_name,
    p2.country AS second_player_country,
    m.final_result,
    m.winner,
    mr.overall_score AS match_rating,
    mr.excitement_score,
    mr.quality_score,
    mr.upset_score,
    mr.headline AS rating_headline
FROM matches m
LEFT JOIN tournaments t ON m.tournament_id = t.id
LEFT JOIN event_types et ON m.event_type_id = et.id
LEFT JOIN surfaces s ON t.surface_id = s.id
LEFT JOIN players p1 ON m.first_player_id = p1.id
LEFT JOIN players p2 ON m.second_player_id = p2.id
LEFT JOIN match_ratings mr ON m.id = mr.match_id;

CREATE OR REPLACE VIEW v_player_form AS
SELECT
    p.id,
    p.api_key,
    p.name,
    p.country,
    p.logo_url,
    pr.overall_rating,
    pr.form_score,
    pr.clay_rating,
    pr.hard_rating,
    pr.grass_rating,
    pr.form_wins,
    pr.form_losses,
    pr.form_summary,
    pr.calculated_at
FROM players p
LEFT JOIN player_ratings pr ON p.id = pr.player_id;

-- ============================================================
-- UPDATED_AT TRIGGER FUNCTION
-- ============================================================

CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_tournaments_updated_at
    BEFORE UPDATE ON tournaments
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

CREATE TRIGGER trg_players_updated_at
    BEFORE UPDATE ON players
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

CREATE TRIGGER trg_matches_updated_at
    BEFORE UPDATE ON matches
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

CREATE TRIGGER trg_match_ratings_updated_at
    BEFORE UPDATE ON match_ratings
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

CREATE TRIGGER trg_player_ratings_updated_at
    BEFORE UPDATE ON player_ratings
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();
