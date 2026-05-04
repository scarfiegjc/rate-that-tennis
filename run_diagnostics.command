#!/bin/bash
# ratethat.tennis — DB Diagnostics
# Checks what data is actually in the production database.

cd "$(dirname "$0")"

echo ""
echo "╔══════════════════════════════════════════════════╗"
echo "║        ratethat.tennis — DB Diagnostics          ║"
echo "╚══════════════════════════════════════════════════╝"
echo ""

if [ -f .env ]; then
    export $(grep -v '^#' .env | xargs)
fi

python3 - <<'EOF'
import os, sys
try:
    import psycopg2
    import psycopg2.extras
except ImportError:
    print("ERROR: psycopg2 not installed. Run: pip install psycopg2-binary")
    sys.exit(1)

DB_URL = (
    os.environ.get("DATABASE_PUBLIC_URL")
    or os.environ.get("DATABASE_URL")
    or "postgresql://postgres:DEKANqBEjmOvOGLCfzaQIBaKzhKcyKwS@switchyard.proxy.rlwy.net:39343/railway"
).strip()

conn = psycopg2.connect(DB_URL)
conn.cursor_factory = psycopg2.extras.RealDictCursor
cur = conn.cursor()

print("── Matches ──────────────────────────────────")
cur.execute("SELECT COUNT(*) AS total FROM matches")
print(f"  Total matches:             {cur.fetchone()['total']:,}")

cur.execute("SELECT COUNT(*) AS c FROM matches WHERE event_date >= CURRENT_DATE - 3 AND event_date <= CURRENT_DATE + 3")
print(f"  Matches ±3 days:           {cur.fetchone()['c']:,}")

cur.execute("SELECT event_date, COUNT(*) AS c FROM matches WHERE event_date >= CURRENT_DATE - 1 AND event_date <= CURRENT_DATE + 3 GROUP BY event_date ORDER BY event_date")
for row in cur.fetchall():
    print(f"    {row['event_date']}: {row['c']} matches")

print()
print("── Player Ratings ───────────────────────────")
cur.execute("SELECT COUNT(*) AS c FROM player_ratings")
total_pr = cur.fetchone()['c']
print(f"  player_ratings rows:       {total_pr:,}")

cur.execute("SELECT COUNT(*) AS c FROM player_ratings WHERE rtt_score IS NOT NULL")
print(f"  rows with rtt_score:       {cur.fetchone()['c']:,}")

if total_pr > 0:
    cur.execute("SELECT player_id, rtt_score, hard_rating, clay_rating FROM player_ratings ORDER BY rtt_score DESC NULLS LAST LIMIT 5")
    print("  Top 5 by RTT score:")
    for r in cur.fetchall():
        print(f"    player_id={r['player_id']}  rtt={r['rtt_score']}  hard={r['hard_rating']}  clay={r['clay_rating']}")

print()
print("── RTT join check (today's matches) ─────────")
cur.execute("""
    SELECT m.id, p1.name AS p1, pr1.rtt_score AS p1_rtt, p2.name AS p2, pr2.rtt_score AS p2_rtt
    FROM matches m
    JOIN players p1 ON p1.id = m.first_player_id
    JOIN players p2 ON p2.id = m.second_player_id
    LEFT JOIN player_ratings pr1 ON pr1.player_id = m.first_player_id
    LEFT JOIN player_ratings pr2 ON pr2.player_id = m.second_player_id
    WHERE m.event_date = CURRENT_DATE
    LIMIT 5
""")
rows = cur.fetchall()
if rows:
    for r in rows:
        print(f"  {r['p1']} (rtt={r['p1_rtt']}) vs {r['p2']} (rtt={r['p2_rtt']})")
else:
    print("  No matches today")

print()
print("── Predictions ──────────────────────────────")
cur.execute("SELECT COUNT(*) AS c FROM model_predictions")
print(f"  model_predictions rows:    {cur.fetchone()['c']:,}")

print()
print("── Bookmaker Odds ───────────────────────────")
cur.execute("SELECT COUNT(*) AS c FROM bookmaker_odds")
print(f"  bookmaker_odds rows:       {cur.fetchone()['c']:,}")

conn.close()
print()
print("── Done ──────────────────────────────────────")
EOF

echo ""
read -p "Press Enter to close..."
