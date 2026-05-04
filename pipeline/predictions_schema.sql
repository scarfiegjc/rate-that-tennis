-- ratethat.tennis — Prediction tracking + systems schema
-- Purpose: snapshot every prediction, link to actual results, support systems
-- and the historic results page (à la ratethat.dog / ratethat.horse).
-- Run: psql $DATABASE_URL -f pipeline/predictions_schema.sql
-- Idempotent — safe to re-run.

-- ─────────────────────────────────────────────────────────────────────────────
-- 1. Extend model_predictions with the structured features the new predictor
--    produces, and add result-tracking columns.
-- ─────────────────────────────────────────────────────────────────────────────

ALTER TABLE model_predictions
    -- Deep reasoning intelligence text (Claude-generated, 3 columns on the UI)
    ADD COLUMN IF NOT EXISTS p1_intel            TEXT,
    ADD COLUMN IF NOT EXISTS p2_intel            TEXT,
    ADD COLUMN IF NOT EXISTS match_preview       TEXT,
    ADD COLUMN IF NOT EXISTS did_you_know        TEXT,
    ADD COLUMN IF NOT EXISTS confidence_line     TEXT,
    ADD COLUMN IF NOT EXISTS intel_generated_at  TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS intel_model         TEXT,
    -- Inputs the prediction was based on (snapshot at predict time)
    ADD COLUMN IF NOT EXISTS p1_rtt              NUMERIC(6,2),
    ADD COLUMN IF NOT EXISTS p2_rtt              NUMERIC(6,2),
    ADD COLUMN IF NOT EXISTS p1_surface_rtt      NUMERIC(6,2),
    ADD COLUMN IF NOT EXISTS p2_surface_rtt      NUMERIC(6,2),
    ADD COLUMN IF NOT EXISTS rtt_gap             NUMERIC(6,2),
    ADD COLUMN IF NOT EXISTS surface_gap         NUMERIC(6,2),
    ADD COLUMN IF NOT EXISTS form_gap            NUMERIC(6,2),
    ADD COLUMN IF NOT EXISTS p1_momentum         TEXT,
    ADD COLUMN IF NOT EXISTS p2_momentum         TEXT,
    ADD COLUMN IF NOT EXISTS hand_matchup_logit  NUMERIC(6,3),
    ADD COLUMN IF NOT EXISTS h2h_logit           NUMERIC(6,3),
    ADD COLUMN IF NOT EXISTS surface_record_logit NUMERIC(6,3),
    ADD COLUMN IF NOT EXISTS total_logit         NUMERIC(6,3),
    ADD COLUMN IF NOT EXISTS predictor_version   TEXT,

    -- Result tracking (filled in once the match finishes)
    ADD COLUMN IF NOT EXISTS predicted_winner    TEXT       -- 'first_player' | 'second_player'
        CHECK (predicted_winner IS NULL OR predicted_winner IN ('first_player','second_player')),
    ADD COLUMN IF NOT EXISTS actual_winner       TEXT
        CHECK (actual_winner IS NULL OR actual_winner IN ('first_player','second_player')),
    ADD COLUMN IF NOT EXISTS is_correct          BOOLEAN,
    ADD COLUMN IF NOT EXISTS settled_at          TIMESTAMPTZ;

CREATE INDEX IF NOT EXISTS idx_predictions_settled
    ON model_predictions(settled_at DESC) WHERE settled_at IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_predictions_correct
    ON model_predictions(is_correct) WHERE is_correct IS NOT NULL;

-- ─────────────────────────────────────────────────────────────────────────────
-- 1b. Player point stats — derived from match_games + match_points
--     (production point-by-point data — fully ours, no Sackmann).
-- ─────────────────────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS player_point_stats (
    player_id            INTEGER PRIMARY KEY REFERENCES players(id) ON DELETE CASCADE,
    -- Service
    service_games        INTEGER DEFAULT 0,
    service_holds        INTEGER DEFAULT 0,
    service_hold_pct     NUMERIC(5,2),
    bp_faced             INTEGER DEFAULT 0,
    bp_saved             INTEGER DEFAULT 0,
    bp_save_pct          NUMERIC(5,2),
    -- Return
    return_games         INTEGER DEFAULT 0,
    return_breaks        INTEGER DEFAULT 0,
    break_pct            NUMERIC(5,2),
    bp_chances           INTEGER DEFAULT 0,
    bp_converted         INTEGER DEFAULT 0,
    bp_conversion_pct    NUMERIC(5,2),
    -- Clutch
    tiebreaks_played     INTEGER DEFAULT 0,
    tiebreaks_won        INTEGER DEFAULT 0,
    tiebreak_win_pct     NUMERIC(5,2),
    set_points_faced     INTEGER DEFAULT 0,
    set_points_saved     INTEGER DEFAULT 0,
    set_point_save_pct   NUMERIC(5,2),
    match_points_faced   INTEGER DEFAULT 0,
    match_points_saved   INTEGER DEFAULT 0,
    match_point_save_pct NUMERIC(5,2),
    -- Sample size
    matches_analyzed     INTEGER DEFAULT 0,
    last_match_date      DATE,
    updated_at           TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_pps_matches ON player_point_stats(matches_analyzed DESC);

-- ─────────────────────────────────────────────────────────────────────────────
-- 2. Hand-matchup splits — per-player record vs each opponent hand
--    Refreshed nightly from production matches + sa_matches (training-only).
--    The TABLE itself is derived data — fine to expose on frontend.
-- ─────────────────────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS player_hand_splits (
    id              SERIAL PRIMARY KEY,
    player_id       INTEGER NOT NULL REFERENCES players(id) ON DELETE CASCADE,
    vs_hand         TEXT NOT NULL CHECK (vs_hand IN ('Right','Left')),
    matches         INTEGER NOT NULL DEFAULT 0,
    wins            INTEGER NOT NULL DEFAULT 0,
    losses          INTEGER NOT NULL DEFAULT 0,
    win_pct         NUMERIC(5,2),       -- 0–100
    expected_pct    NUMERIC(5,2),       -- baseline win rate vs all opponents
    edge            NUMERIC(5,2),       -- win_pct - expected_pct
    updated_at      TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE (player_id, vs_hand)
);

CREATE INDEX IF NOT EXISTS idx_hand_splits_player
    ON player_hand_splits(player_id);

-- ─────────────────────────────────────────────────────────────────────────────
-- 3. Systems — bettor-friendly heuristics that tag interesting matches.
--    Each system has a definition + a record of every pick it has made.
-- ─────────────────────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS systems (
    id              SERIAL PRIMARY KEY,
    code            TEXT UNIQUE NOT NULL,           -- e.g. 'surface_monster'
    name            TEXT NOT NULL,                  -- 'Surface Monster'
    description     TEXT NOT NULL,
    icon            TEXT,                            -- emoji or icon id
    accent_colour   TEXT,                           -- hex for badge
    is_active       BOOLEAN DEFAULT TRUE,
    created_at      TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS system_picks (
    id              SERIAL PRIMARY KEY,
    system_id       INTEGER NOT NULL REFERENCES systems(id) ON DELETE CASCADE,
    match_id        INTEGER NOT NULL REFERENCES matches(id) ON DELETE CASCADE,
    pick            TEXT NOT NULL CHECK (pick IN ('first_player','second_player')),
    confidence      TEXT CHECK (confidence IN ('low','medium','high')),
    reason          TEXT NOT NULL,                  -- one-line human explanation
    rationale       JSONB,                          -- structured breakdown
    -- Snapshots so backtest is reproducible
    pick_prob       NUMERIC(5,4),                   -- model prob at pick time
    market_odds     NUMERIC(8,4),                   -- best decimal odds at pick time
    -- Outcome
    is_correct      BOOLEAN,
    profit_loss     NUMERIC(8,4),                   -- +odds-1 if win, -1 if loss, NULL if open
    settled_at      TIMESTAMPTZ,
    picked_at       TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE (system_id, match_id)
);

CREATE INDEX IF NOT EXISTS idx_system_picks_system_settled
    ON system_picks(system_id, settled_at DESC);
CREATE INDEX IF NOT EXISTS idx_system_picks_match
    ON system_picks(match_id);

-- ─────────────────────────────────────────────────────────────────────────────
-- 4. Seed canonical system definitions
-- ─────────────────────────────────────────────────────────────────────────────

INSERT INTO systems (code, name, description, icon, accent_colour) VALUES
    ('surface_monster',
     'Surface Monster',
     'Player is elite on this surface (rating 85+) and faces an opponent below 70 on the same surface.',
     '🏆', '#3B6D11'),
    ('form_surge',
     'Form Surge',
     'Player has rising momentum and a form rating 10+ points above their opponent.',
     '📈', '#639922'),
    ('hand_advantage',
     'Hand Advantage',
     'Player has a 7+ point edge above expected win rate against the opponent''s hand (left/right).',
     '🤚', '#2563EB'),
    ('big_match_player',
     'Big Match Player',
     'Slam or Masters round, and the player''s big-match rating is 80+ and 10+ points above their opponent''s.',
     '🎯', '#9333EA'),
    ('underdog_value',
     'Underdog Value',
     'Model probability beats market implied probability by 8+ points; favourite is "wrong" by the market.',
     '💎', '#F59E0B'),
    ('rtt_mismatch',
     'RTT Mismatch',
     'RTT score gap of 12+ points — a clear class difference the model is highly confident about.',
     '⚡', '#DC2626'),
    ('clutch_in_decider',
     'Clutch in Decider',
     'Best-of-5 match and the player''s pressure rating is 80+ and 10+ points above their opponent''s.',
     '💪', '#EA580C')
ON CONFLICT (code) DO UPDATE SET
    name           = EXCLUDED.name,
    description    = EXCLUDED.description,
    icon           = EXCLUDED.icon,
    accent_colour  = EXCLUDED.accent_colour;

-- ─────────────────────────────────────────────────────────────────────────────
-- 5. View: predictions with their results joined in (fast for tracker pages)
-- ─────────────────────────────────────────────────────────────────────────────

CREATE OR REPLACE VIEW v_predictions_with_results AS
SELECT
    mp.match_id,
    m.event_date,
    m.event_time,
    m.event_status,
    m.winner                 AS match_winner_text,
    t.name                   AS tournament_name,
    s.name                   AS surface_name,
    m.tournament_round,
    p1.id                    AS p1_id,
    p1.name                  AS p1_name,
    p1.country_code          AS p1_country,
    p2.id                    AS p2_id,
    p2.name                  AS p2_name,
    p2.country_code          AS p2_country,
    mp.prob_first_player,
    mp.prob_second_player,
    mp.confidence,
    mp.predicted_winner,
    mp.actual_winner,
    mp.is_correct,
    mp.settled_at,
    mp.predictor_version,
    mp.rtt_gap,
    mp.surface_gap,
    mp.form_gap,
    mp.total_logit,
    mp.predicted_at,
    mp.key_factors
FROM model_predictions mp
JOIN matches m       ON m.id = mp.match_id
LEFT JOIN tournaments t ON t.id = m.tournament_id
LEFT JOIN surfaces s    ON s.id = t.surface_id
LEFT JOIN players p1    ON p1.id = m.first_player_id
LEFT JOIN players p2    ON p2.id = m.second_player_id;

-- ─────────────────────────────────────────────────────────────────────────────
-- 6. View: per-day rollup (for the historic results page)
-- ─────────────────────────────────────────────────────────────────────────────

CREATE OR REPLACE VIEW v_predictions_daily AS
SELECT
    event_date,
    COUNT(*)                                                          AS predictions,
    COUNT(*) FILTER (WHERE settled_at IS NOT NULL)                    AS settled,
    COUNT(*) FILTER (WHERE is_correct IS TRUE)                        AS correct,
    COUNT(*) FILTER (WHERE is_correct IS FALSE)                       AS incorrect,
    ROUND(
        100.0 * COUNT(*) FILTER (WHERE is_correct IS TRUE)
              / NULLIF(COUNT(*) FILTER (WHERE settled_at IS NOT NULL), 0),
        2
    )                                                                 AS accuracy_pct,
    -- High-confidence subset
    COUNT(*) FILTER (WHERE confidence = 'high')                       AS high_conf,
    COUNT(*) FILTER (WHERE confidence = 'high' AND is_correct IS TRUE) AS high_conf_correct,
    ROUND(
        100.0 * COUNT(*) FILTER (WHERE confidence = 'high' AND is_correct IS TRUE)
              / NULLIF(COUNT(*) FILTER (WHERE confidence = 'high' AND settled_at IS NOT NULL), 0),
        2
    )                                                                 AS high_conf_accuracy_pct
FROM v_predictions_with_results
GROUP BY event_date;

-- ─────────────────────────────────────────────────────────────────────────────
-- 7. View: per-system rollup
-- ─────────────────────────────────────────────────────────────────────────────

CREATE OR REPLACE VIEW v_systems_stats AS
SELECT
    sy.id                                       AS system_id,
    sy.code,
    sy.name,
    sy.description,
    sy.icon,
    sy.accent_colour,
    COUNT(sp.id)                                AS picks_total,
    COUNT(sp.id) FILTER (WHERE sp.settled_at IS NOT NULL) AS picks_settled,
    COUNT(sp.id) FILTER (WHERE sp.is_correct)   AS picks_correct,
    ROUND(
        100.0 * COUNT(sp.id) FILTER (WHERE sp.is_correct)
              / NULLIF(COUNT(sp.id) FILTER (WHERE sp.settled_at IS NOT NULL), 0),
        2
    )                                           AS accuracy_pct,
    ROUND(SUM(sp.profit_loss)::numeric, 2)      AS profit_units,
    ROUND(
        100.0 * SUM(sp.profit_loss)
              / NULLIF(COUNT(sp.id) FILTER (WHERE sp.settled_at IS NOT NULL), 0),
        2
    )                                           AS roi_pct
FROM systems sy
LEFT JOIN system_picks sp ON sp.system_id = sy.id
GROUP BY sy.id, sy.code, sy.name, sy.description, sy.icon, sy.accent_colour;

-- Done.
SELECT 'predictions_schema applied successfully' AS status;
