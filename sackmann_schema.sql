-- ============================================================
-- ratethat.tennis — Sackmann Historical Data Schema
-- ML training data only — never surfaced on front-end
-- Source: github.com/JeffSackmann (CC BY-NC-SA 4.0)
-- ============================================================

-- ─────────────────────────────────────────────
-- PLAYERS
-- ─────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS sa_players (
    player_id       INTEGER PRIMARY KEY,   -- Sackmann's player_id
    name_first      TEXT,
    name_last       TEXT,
    full_name       TEXT GENERATED ALWAYS AS (name_first || ' ' || name_last) STORED,
    hand            TEXT,                  -- 'R', 'L', 'U'
    dob             DATE,
    ioc             TEXT,                  -- IOC country code
    height_cm       INTEGER,
    tour            TEXT NOT NULL,         -- 'ATP' or 'WTA'
    created_at      TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_sa_players_name ON sa_players(name_last, name_first);
CREATE INDEX IF NOT EXISTS idx_sa_players_tour ON sa_players(tour);

COMMENT ON TABLE sa_players IS 'Sackmann player reference — ML training only, not surfaced on front-end';

-- ─────────────────────────────────────────────
-- MATCHES (core ML training table)
-- ─────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS sa_matches (
    id                  SERIAL PRIMARY KEY,
    tour                TEXT NOT NULL,         -- 'ATP' or 'WTA'

    -- Tournament
    tourney_id          TEXT NOT NULL,          -- e.g. '2024-M006'
    tourney_name        TEXT,
    surface             TEXT,                  -- 'Hard', 'Clay', 'Grass', 'Carpet'
    draw_size           INTEGER,
    tourney_level       TEXT,                  -- 'G'=Slam, 'M'=Masters, 'A'=500/250, 'D'=Davis, 'C'=Challenger, 'S'=Satellite/ITF, 'F'=Tour Finals
    tourney_date        DATE,
    season              INTEGER,               -- extracted year

    -- Match metadata
    match_num           INTEGER,
    round               TEXT,                  -- 'R128', 'R64', 'R32', 'R16', 'QF', 'SF', 'F', 'RR', 'BR'
    best_of             INTEGER,               -- 3 or 5

    -- Winner
    winner_id           INTEGER REFERENCES sa_players(player_id),
    winner_seed         INTEGER,
    winner_entry        TEXT,                  -- 'WC', 'Q', 'LL', 'PR', 'SE', 'ALT'
    winner_name         TEXT,
    winner_hand         TEXT,
    winner_ht           INTEGER,               -- height in cm
    winner_ioc          TEXT,
    winner_age          NUMERIC(5,2),
    winner_rank         INTEGER,
    winner_rank_points  INTEGER,

    -- Loser
    loser_id            INTEGER REFERENCES sa_players(player_id),
    loser_seed          INTEGER,
    loser_entry         TEXT,
    loser_name          TEXT,
    loser_hand          TEXT,
    loser_ht            INTEGER,
    loser_ioc           TEXT,
    loser_age           NUMERIC(5,2),
    loser_rank          INTEGER,
    loser_rank_points   INTEGER,

    -- Result
    score               TEXT,                  -- e.g. '6-3 6-4'
    minutes             INTEGER,

    -- Winner serve stats
    w_ace               INTEGER,
    w_df                INTEGER,
    w_svpt              INTEGER,               -- serve points total
    w_1st_in            INTEGER,               -- 1st serves in
    w_1st_won           INTEGER,               -- points won on 1st serve
    w_2nd_won           INTEGER,               -- points won on 2nd serve
    w_sv_gms            INTEGER,               -- service games played
    w_bp_saved          INTEGER,
    w_bp_faced          INTEGER,

    -- Loser serve stats
    l_ace               INTEGER,
    l_df                INTEGER,
    l_svpt              INTEGER,
    l_1st_in            INTEGER,
    l_1st_won           INTEGER,
    l_2nd_won           INTEGER,
    l_sv_gms            INTEGER,
    l_bp_saved          INTEGER,
    l_bp_faced          INTEGER,

    -- Derived features (computed on insert for ML convenience)
    w_1st_serve_pct     NUMERIC(6,4),          -- w_1st_in / w_svpt
    w_1st_won_pct       NUMERIC(6,4),          -- w_1st_won / w_1st_in
    w_2nd_won_pct       NUMERIC(6,4),          -- w_2nd_won / (w_svpt - w_1st_in)
    w_bp_save_pct       NUMERIC(6,4),          -- w_bp_saved / w_bp_faced
    w_hold_pct          NUMERIC(6,4),          -- service games held / w_sv_gms
    l_1st_serve_pct     NUMERIC(6,4),
    l_1st_won_pct       NUMERIC(6,4),
    l_2nd_won_pct       NUMERIC(6,4),
    l_bp_save_pct       NUMERIC(6,4),
    l_hold_pct          NUMERIC(6,4),

    -- Uniqueness
    UNIQUE (tour, tourney_id, match_num)
);

CREATE INDEX IF NOT EXISTS idx_sa_matches_tour_date  ON sa_matches(tour, tourney_date);
CREATE INDEX IF NOT EXISTS idx_sa_matches_winner      ON sa_matches(winner_id, tourney_date);
CREATE INDEX IF NOT EXISTS idx_sa_matches_loser       ON sa_matches(loser_id, tourney_date);
CREATE INDEX IF NOT EXISTS idx_sa_matches_surface     ON sa_matches(surface);
CREATE INDEX IF NOT EXISTS idx_sa_matches_level       ON sa_matches(tourney_level);
CREATE INDEX IF NOT EXISTS idx_sa_matches_season      ON sa_matches(season);

COMMENT ON TABLE sa_matches IS 'Sackmann historical match results — core ML training dataset';

-- ─────────────────────────────────────────────
-- RANKINGS
-- ─────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS sa_rankings (
    id              SERIAL PRIMARY KEY,
    tour            TEXT NOT NULL,
    ranking_date    DATE NOT NULL,
    rank            INTEGER NOT NULL,
    player_id       INTEGER REFERENCES sa_players(player_id),
    points          INTEGER,
    UNIQUE (tour, ranking_date, rank)
);

CREATE INDEX IF NOT EXISTS idx_sa_rankings_player ON sa_rankings(player_id, ranking_date);
CREATE INDEX IF NOT EXISTS idx_sa_rankings_date   ON sa_rankings(tour, ranking_date);

COMMENT ON TABLE sa_rankings IS 'Sackmann weekly ATP/WTA rankings — for point-in-time rank lookups during feature engineering';

-- ─────────────────────────────────────────────
-- CHARTING PROJECT — MATCH METADATA
-- ─────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS sa_charting_matches (
    match_id        TEXT PRIMARY KEY,          -- Sackmann charting match ID e.g. '20240128-M-AO-F-Sinner-Medvedev'
    tour            TEXT,                      -- 'M' or 'W'
    date            DATE,
    tournament      TEXT,
    surface         TEXT,
    round           TEXT,
    server1         TEXT,                      -- player serving first
    server2         TEXT,
    winner          INTEGER,                   -- 1 or 2
    w_sets          INTEGER,
    l_sets          INTEGER,
    score           TEXT,
    status          TEXT,                      -- 'Completed', 'Retired', 'Walkover'
    created_at      TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_sa_charting_matches_tour ON sa_charting_matches(tour, date);

COMMENT ON TABLE sa_charting_matches IS 'Sackmann Match Charting Project — match index. Shot-level data in sa_charting_points';

-- ─────────────────────────────────────────────
-- CHARTING PROJECT — POINT-BY-POINT
-- ─────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS sa_charting_points (
    id              BIGSERIAL PRIMARY KEY,
    match_id        TEXT NOT NULL REFERENCES sa_charting_matches(match_id) ON DELETE CASCADE,

    -- Point context
    set_no          INTEGER,
    game_no         INTEGER,
    point_no        INTEGER,
    server          INTEGER,                   -- 1 or 2
    serve_no        INTEGER,                   -- 1 or 2 (first/second serve)

    -- Score state
    p1_sets         INTEGER,
    p2_sets         INTEGER,
    p1_games        INTEGER,
    p2_games        INTEGER,
    p1_points       TEXT,                      -- '0','15','30','40','AD'
    p2_points       TEXT,

    -- Outcome flags
    is_break_point  BOOLEAN,
    is_set_point    BOOLEAN,
    is_match_point  BOOLEAN,
    point_winner    INTEGER,                   -- 1 or 2

    -- Shot sequence (Sackmann notation)
    shot_sequence   TEXT,                      -- raw shot string e.g. '4f2b2w*'

    -- Parsed shot features
    serve_dir       TEXT,                      -- 'T'=T, 'B'=Body, 'W'=Wide
    serve_fault     BOOLEAN,
    rally_length    INTEGER,
    point_end_type  TEXT,                      -- 'W'=winner, 'E'=error, 'A'=ace, 'D'=double fault, '!'=forced error
    last_shot_type  TEXT,                      -- 'f'=forehand, 'b'=backhand, 's'=slice, 'v'=volley, etc.
    last_shot_dir   TEXT,                      -- 'w'=wide, 'n'=net, 'd'=deep, '@'=unforced

    UNIQUE (match_id, set_no, game_no, point_no, serve_no)
);

CREATE INDEX IF NOT EXISTS idx_sa_charting_points_match   ON sa_charting_points(match_id);
CREATE INDEX IF NOT EXISTS idx_sa_charting_points_server  ON sa_charting_points(match_id, server);
CREATE INDEX IF NOT EXISTS idx_sa_charting_points_bp      ON sa_charting_points(is_break_point) WHERE is_break_point = TRUE;

COMMENT ON TABLE sa_charting_points IS 'Sackmann Match Charting Project — point-level shot data. ~4M rows. ML training only.';

-- ─────────────────────────────────────────────
-- INGESTION TRACKING
-- ─────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS sa_ingest_log (
    id              SERIAL PRIMARY KEY,
    tour            TEXT,
    file_name       TEXT,
    rows_processed  INTEGER DEFAULT 0,
    rows_inserted   INTEGER DEFAULT 0,
    rows_skipped    INTEGER DEFAULT 0,
    status          TEXT DEFAULT 'running',    -- 'running', 'success', 'failed'
    error_msg       TEXT,
    started_at      TIMESTAMPTZ DEFAULT NOW(),
    completed_at    TIMESTAMPTZ,
    UNIQUE (tour, file_name)
);

COMMENT ON TABLE sa_ingest_log IS 'Tracks which Sackmann CSV files have been loaded — enables incremental updates';
