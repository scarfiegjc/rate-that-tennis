#!/bin/bash
# Run bzzoiro schema additions on Railway DB
# Double-click this file to apply the schema changes
cd "$(dirname "$0")"
source .env 2>/dev/null || true

python3 << 'PYEOF'
import psycopg2, os

DB_URL = os.environ.get('DATABASE_PUBLIC_URL') or os.environ.get('DATABASE_URL') or 'postgresql://postgres:DEKANqBEjmOvOGLCfzaQIBaKzhKcyKwS@switchyard.proxy.rlwy.net:39343/railway'

STMTS = [
    'ALTER TABLE matches ADD COLUMN IF NOT EXISTS bzzoiro_id INTEGER',
    'ALTER TABLE matches ADD COLUMN IF NOT EXISTS live_data JSONB',
    'ALTER TABLE matches ADD COLUMN IF NOT EXISTS seo_preview TEXT',
    'ALTER TABLE matches ADD COLUMN IF NOT EXISTS seo_preview_generated_at TIMESTAMPTZ',
    'ALTER TABLE players ADD COLUMN IF NOT EXISTS bzzoiro_id INTEGER',
    'ALTER TABLE players ADD COLUMN IF NOT EXISTS ranking_movement INTEGER',
    'ALTER TABLE players ADD COLUMN IF NOT EXISTS ranking_career_best INTEGER',
    'ALTER TABLE players ADD COLUMN IF NOT EXISTS ranking_points INTEGER',
    'CREATE UNIQUE INDEX IF NOT EXISTS idx_matches_bzzoiro_id ON matches(bzzoiro_id) WHERE bzzoiro_id IS NOT NULL',
    'CREATE UNIQUE INDEX IF NOT EXISTS idx_players_bzzoiro_id ON players(bzzoiro_id) WHERE bzzoiro_id IS NOT NULL',
    """CREATE TABLE IF NOT EXISTS bzzoiro_predictions (
        id SERIAL PRIMARY KEY, match_id INTEGER REFERENCES matches(id),
        bzzoiro_match_id INTEGER, bzzoiro_prediction_id INTEGER UNIQUE,
        prob_player1_wins NUMERIC(5,4), prob_player2_wins NUMERIC(5,4),
        predicted_winner TEXT, confidence NUMERIC(5,4),
        expected_total_sets NUMERIC(4,2), prob_over_2_5_sets NUMERIC(5,4),
        expected_total_games NUMERIC(5,2), prob_over_20_5_games NUMERIC(5,4),
        prob_over_21_5_games NUMERIC(5,4), prob_over_22_5_games NUMERIC(5,4),
        prob_player1_wins_first_set NUMERIC(5,4), actual_winner TEXT,
        was_winner_correct BOOLEAN, synced_at TIMESTAMPTZ DEFAULT NOW()
    )""",
    """CREATE TABLE IF NOT EXISTS bzzoiro_h2h (
        id SERIAL PRIMARY KEY, match_id INTEGER REFERENCES matches(id),
        player1_id INTEGER REFERENCES players(id), player2_id INTEGER REFERENCES players(id),
        h2h_data JSONB, player1_last5 JSONB, player2_last5 JSONB,
        synced_at TIMESTAMPTZ DEFAULT NOW(), UNIQUE(match_id)
    )""",
]

print(f"Connecting to DB...")
conn = psycopg2.connect(DB_URL, connect_timeout=15)
conn.autocommit = True
cur = conn.cursor()

for s in STMTS:
    try:
        cur.execute(s)
        print('OK:', s[:70].replace('\n', ' '))
    except Exception as e:
        print('SKIP (already exists):', str(e)[:80])

conn.close()
print('\nSchema migration complete.')
PYEOF
