-- ratethat.tennis — Matchstat (matchstat.com via RapidAPI) ingestion schema
--
-- Purpose: store enriched player profile data + per-match stats from Matchstat
-- alongside (not replacing) our existing Sackmann/TML/api-tennis pipelines.
--
-- All tables are prefixed `ms_` to make their provenance unambiguous.
-- Rich-stat fields (winners, unforced_errors, net_approaches, fastest_serve,
-- average_first_serve_speed, average_second_serve_speed) are populated for
-- Grand Slam matches only — for non-Slam matches they remain NULL.
--
-- Run on every API boot via apply_schema_migrations() — idempotent.

-- ═════════════════════════════════════════════════════════════════════════
-- 1. ms_players — Matchstat player profiles
-- ═════════════════════════════════════════════════════════════════════════

CREATE TABLE IF NOT EXISTS ms_players (
    ms_id            INTEGER PRIMARY KEY,
    name             TEXT NOT NULL,
    country_acr      TEXT,                  -- 3-letter IOC code (ITA, ESP, USA…)
    tour             TEXT NOT NULL CHECK (tour IN ('atp', 'wta')),

    -- Ranking (snapshot at last sync)
    current_rank     INTEGER,
    current_rank_at  TIMESTAMPTZ,
    best_rank        INTEGER,
    best_rank_at     TIMESTAMPTZ,
    points           INTEGER,

    -- Surface point breakdown (current cycle)
    hard_points      INTEGER,
    ihard_points     INTEGER,
    clay_points      INTEGER,
    grass_points     INTEGER,
    carpet_points    INTEGER,

    -- Biographical
    birthday         DATE,
    height_cm        INTEGER,               -- from `information.height` (string cm)
    weight_kg        NUMERIC(5,2),          -- from `information.weight` (parsed)
    plays            TEXT,                  -- e.g. "Right-Handed, Two-Handed Backhand"
    coach            TEXT,
    birthplace       TEXT,
    residence        TEXT,
    turned_pro       INTEGER,
    player_status    TEXT,                  -- "Active" / "Inactive"

    -- Social / external links
    twitter          TEXT,
    instagram        TEXT,
    facebook         TEXT,
    site             TEXT,
    atp_page         TEXT,                  -- Official ATP/WTA profile URL

    -- Wikidata for future enrichment
    wikidata_id      TEXT,

    -- Career form snapshot (from include=form)
    form_string      TEXT,                  -- e.g. "wwlwwwwww"
    prize_usd        BIGINT,                -- Career prize money

    -- Bookkeeping
    raw              JSONB,                 -- Full raw payload for audit / future fields
    last_synced_at   TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS ms_players_name_lower_idx ON ms_players (LOWER(name));
CREATE INDEX IF NOT EXISTS ms_players_tour_rank_idx ON ms_players (tour, current_rank NULLS LAST);
CREATE INDEX IF NOT EXISTS ms_players_country_idx ON ms_players (country_acr);


-- ═════════════════════════════════════════════════════════════════════════
-- 2. ms_player_links — production players.id ↔ Matchstat ms_id mapping
-- ═════════════════════════════════════════════════════════════════════════

CREATE TABLE IF NOT EXISTS ms_player_links (
    player_id        INTEGER PRIMARY KEY REFERENCES players(id) ON DELETE CASCADE,
    ms_id            INTEGER NOT NULL REFERENCES ms_players(ms_id) ON DELETE CASCADE,
    tour             TEXT NOT NULL CHECK (tour IN ('atp', 'wta')),
    resolution_strategy TEXT,               -- 'rankings-exact' / 'rankings-surname' / 'rankings-initial'
    confidence       TEXT NOT NULL DEFAULT 'medium'
                     CHECK (confidence IN ('high', 'medium', 'low', 'manual')),
    linked_at        TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS ms_player_links_ms_id_idx ON ms_player_links (ms_id);


-- ═════════════════════════════════════════════════════════════════════════
-- 3. ms_matches — Match records (one row per Matchstat match)
-- ═════════════════════════════════════════════════════════════════════════
--
-- player1 is always the WINNER in Matchstat's archive convention.
-- Tournament tier strings carried as-is for filtering: "Grand Slam",
-- "Masters series", "Main tour", "Tour finals", "Davis/Fed Cup", etc.

CREATE TABLE IF NOT EXISTS ms_matches (
    ms_match_id      BIGINT PRIMARY KEY,    -- Matchstat's match `id`
    tour             TEXT NOT NULL CHECK (tour IN ('atp', 'wta')),
    match_date       DATE NOT NULL,
    result           TEXT,                  -- "6-3 6-2" — space-separated set scores
    best_of          INTEGER,
    round_id         INTEGER,
    round_name       TEXT,
    tournament_id    INTEGER,
    tournament_name  TEXT,
    tournament_tier  TEXT,                  -- "Grand Slam" / "Masters series" / etc.
    court_id         INTEGER,
    court_name       TEXT,                  -- "Hard" / "Clay" / "Grass" / "Indoor Hard"

    -- Players (winner = p1, loser = p2)
    p1_ms_id         INTEGER REFERENCES ms_players(ms_id) ON DELETE SET NULL,
    p2_ms_id         INTEGER REFERENCES ms_players(ms_id) ON DELETE SET NULL,
    p1_name          TEXT,
    p2_name          TEXT,

    -- Pre-match decimal odds (winner / loser)
    odd1             NUMERIC(6,2),
    odd2             NUMERIC(6,2),

    -- Bookkeeping
    raw              JSONB,
    last_synced_at   TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS ms_matches_p1_idx     ON ms_matches (p1_ms_id, match_date DESC);
CREATE INDEX IF NOT EXISTS ms_matches_p2_idx     ON ms_matches (p2_ms_id, match_date DESC);
CREATE INDEX IF NOT EXISTS ms_matches_tier_idx   ON ms_matches (tournament_tier);
CREATE INDEX IF NOT EXISTS ms_matches_court_idx  ON ms_matches (court_name);
CREATE INDEX IF NOT EXISTS ms_matches_date_idx   ON ms_matches (match_date DESC);


-- ═════════════════════════════════════════════════════════════════════════
-- 4. ms_match_stats — Per-match stat block
-- ═════════════════════════════════════════════════════════════════════════
--
-- Two rows per match (one per side) keyed by (match_id, side).
-- Premium fields (winners, unforced_errors, net_approaches, fastest_serve,
-- avg_first_serve_speed, avg_second_serve_speed) are NULL for non-Slam matches.

CREATE TABLE IF NOT EXISTS ms_match_stats (
    ms_match_id              BIGINT NOT NULL REFERENCES ms_matches(ms_match_id) ON DELETE CASCADE,
    side                     CHAR(1) NOT NULL CHECK (side IN ('1', '2')),
    ms_player_id             INTEGER REFERENCES ms_players(ms_id) ON DELETE SET NULL,

    -- Universal (all stat-block matches)
    aces                     INTEGER,
    double_faults            INTEGER,
    first_serve              INTEGER,
    first_serve_of           INTEGER,
    winning_on_first_serve   INTEGER,
    winning_on_first_serve_of INTEGER,
    winning_on_second_serve  INTEGER,
    winning_on_second_serve_of INTEGER,
    break_points_converted   INTEGER,
    break_points_converted_of INTEGER,
    total_points_won         INTEGER,

    -- Premium (Grand Slam only — NULL elsewhere)
    winners                  INTEGER,
    unforced_errors          INTEGER,
    net_approaches           INTEGER,
    net_approaches_of        INTEGER,
    fastest_serve            INTEGER,            -- km/h
    avg_first_serve_speed    INTEGER,
    avg_second_serve_speed   INTEGER,

    -- Return points won (rarely populated)
    rpw                      INTEGER,
    rpw_of                   INTEGER,

    PRIMARY KEY (ms_match_id, side)
);

CREATE INDEX IF NOT EXISTS ms_match_stats_player_idx ON ms_match_stats (ms_player_id);


-- ═════════════════════════════════════════════════════════════════════════
-- 5. ms_player_career_stats — pre-computed career averages per player
-- ═════════════════════════════════════════════════════════════════════════
--
-- Populated by a separate aggregation step after match-stat ingestion.
-- Used directly as features in the predictor — saves recomputing at predict time.

CREATE TABLE IF NOT EXISTS ms_player_career_stats (
    ms_player_id             INTEGER PRIMARY KEY REFERENCES ms_players(ms_id) ON DELETE CASCADE,

    -- Slam-only career averages (the predictively-valuable features)
    slam_matches             INTEGER,            -- Grand Slam matches with stat block
    slam_winners_per_match   NUMERIC(6,2),
    slam_ue_per_match        NUMERIC(6,2),
    slam_winner_ue_ratio     NUMERIC(6,3),       -- winners / max(ue, 1)
    slam_net_won_pct         NUMERIC(5,2),       -- net_approaches / net_approaches_of
    slam_avg_first_serve_kmh NUMERIC(6,1),
    slam_avg_second_serve_kmh NUMERIC(6,1),
    slam_fastest_serve_kmh   INTEGER,

    -- Universal averages (from all matches with stat block)
    all_matches              INTEGER,
    all_first_serve_pct      NUMERIC(5,2),
    all_first_serve_won_pct  NUMERIC(5,2),
    all_second_serve_won_pct NUMERIC(5,2),
    all_aces_per_match       NUMERIC(6,2),
    all_df_per_match         NUMERIC(6,2),
    all_bp_conv_pct          NUMERIC(5,2),
    all_total_pts_won_per_match NUMERIC(7,2),

    last_computed_at         TIMESTAMPTZ NOT NULL DEFAULT NOW()
);


-- ═════════════════════════════════════════════════════════════════════════
-- 6. View — convenient lookup of production player → ms career stats
-- ═════════════════════════════════════════════════════════════════════════

CREATE OR REPLACE VIEW v_player_ms_career AS
SELECT
    pl.player_id                   AS player_id,
    pl.ms_id                       AS ms_id,
    p.name                         AS production_name,
    msp.name                       AS ms_name,
    cs.*
FROM ms_player_links pl
JOIN players p           ON p.id    = pl.player_id
LEFT JOIN ms_players msp ON msp.ms_id = pl.ms_id
LEFT JOIN ms_player_career_stats cs ON cs.ms_player_id = pl.ms_id;
