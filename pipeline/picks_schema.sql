-- ratethat.tennis — My Picks: user accounts + picks tables
-- Safe to run multiple times (all CREATE/ALTER are IF NOT EXISTS).
-- Run:  psql $DATABASE_URL -f pipeline/picks_schema.sql

-- ─────────────────────────────────────────────────────────────────────────────
-- 1. users — registered accounts
-- ─────────────────────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS users (
    id             SERIAL PRIMARY KEY,
    email          TEXT UNIQUE NOT NULL,
    password_hash  TEXT NOT NULL,
    display_name   TEXT,
    created_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_login_at  TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_users_email ON users(email);

-- ─────────────────────────────────────────────────────────────────────────────
-- 2. user_picks — a user's bet selections
-- ─────────────────────────────────────────────────────────────────────────────
-- confidence_stars  1-5  → used as stake multiplier for P&L (1 star = £1, 5 stars = £5)
-- our_odds          decimal odds implied by our model probability (e.g. 2.10)
-- best_odds         best available bookmaker decimal odds at pick time
-- best_odds_bookie  which bookmaker offered best_odds
-- status            pending → live → won | lost | void
-- ─────────────────────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS user_picks (
    id                  SERIAL PRIMARY KEY,
    user_id             INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    match_id            INTEGER NOT NULL REFERENCES matches(id) ON DELETE CASCADE,
    player_id           INTEGER NOT NULL REFERENCES players(id),
    confidence_stars    INTEGER NOT NULL DEFAULT 1 CHECK (confidence_stars BETWEEN 1 AND 5),
    our_odds            NUMERIC(6,2),
    best_odds           NUMERIC(6,2),
    best_odds_bookie    TEXT,
    status              TEXT NOT NULL DEFAULT 'pending'
                            CHECK (status IN ('pending','live','won','lost','void')),
    live_score          TEXT,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    settled_at          TIMESTAMPTZ,
    profit_loss         NUMERIC(8,2),   -- computed on settle: (odds-1)*stake if won, -stake if lost
    UNIQUE(user_id, match_id, player_id)
);

CREATE INDEX IF NOT EXISTS idx_user_picks_user     ON user_picks(user_id, status);
CREATE INDEX IF NOT EXISTS idx_user_picks_match    ON user_picks(match_id);
CREATE INDEX IF NOT EXISTS idx_user_picks_settled  ON user_picks(user_id, settled_at DESC NULLS LAST);
