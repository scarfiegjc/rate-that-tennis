-- ratethat.tennis — player injury / status tracking
--
-- Storage for known physical concerns per player. A row here means the
-- predictor will soften its probability AND surface a warning in the
-- Intelligence tab. Idempotent — safe to apply multiple times.
--
-- Apply with:
--   psql "$DATABASE_URL" -f pipeline/injury_status_schema.sql

CREATE TABLE IF NOT EXISTS player_injury_status (
  id            SERIAL PRIMARY KEY,
  player_id     INTEGER NOT NULL REFERENCES players(id) ON DELETE CASCADE,
  status        TEXT NOT NULL CHECK (status IN ('injury', 'illness', 'fatigue', 'doubt')),
  severity      TEXT NOT NULL CHECK (severity IN ('minor', 'moderate', 'major')),
  body_part     TEXT,                      -- e.g. 'wrist', 'left knee', 'shoulder'
  notes         TEXT,                      -- free-text from source
  source        TEXT NOT NULL,             -- 'atp_tour', 'wta_official', 'news_scrape', 'manual', etc.
  source_url    TEXT,
  noted_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  expires_at    TIMESTAMPTZ,               -- when the concern auto-clears (null = open-ended)
  resolved_at   TIMESTAMPTZ,               -- explicit resolution time (e.g. player won next match cleanly)
  created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at    TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_pis_player ON player_injury_status (player_id);
CREATE INDEX IF NOT EXISTS idx_pis_resolved ON player_injury_status (resolved_at);
CREATE INDEX IF NOT EXISTS idx_pis_expires  ON player_injury_status (expires_at);
CREATE INDEX IF NOT EXISTS idx_pis_noted_at ON player_injury_status (noted_at DESC);

-- Convenience view for "is this player currently flagged?" lookups.
-- Predict.py queries this view rather than computing the active filter
-- in every spot.
CREATE OR REPLACE VIEW v_active_injury_status AS
  SELECT *
    FROM player_injury_status
   WHERE resolved_at IS NULL
     AND (expires_at IS NULL OR expires_at > NOW());

COMMENT ON TABLE player_injury_status IS
  'Per-player injury / illness / fatigue tracking. The predictor reads
   active rows and softens prob accordingly, plus flags in key_factors.';
COMMENT ON COLUMN player_injury_status.severity IS
  'minor → -0.10 logit penalty (caution); moderate → -0.30; major → cap prob at 0.5';
