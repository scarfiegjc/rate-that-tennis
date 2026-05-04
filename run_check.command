#!/bin/bash
# ratethat.tennis — Diagnostic check
cd "$(dirname "$0")"
pip3 install psycopg2-binary requests --quiet --break-system-packages 2>/dev/null

python3 - <<'EOF'
import os, requests, psycopg2

DB_URL = "postgresql://postgres:DEKANqBEjmOvOGLCfzaQIBaKzhKcyKwS@switchyard.proxy.rlwy.net:39343/railway"
API_KEY = "7b2c30d69f93cbbaa699c7a65483e620ec4bf53adc0a105eb9d38876d307002a"

print("=" * 50)
print("1. Testing database connection...")
try:
    conn = psycopg2.connect(DB_URL)
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM matches")
    total = cur.fetchone()[0]
    print(f"   ✅ Connected. Total matches in DB: {total}")

    cur.execute("SELECT COUNT(*) FROM matches WHERE event_date >= CURRENT_DATE")
    upcoming = cur.fetchone()[0]
    print(f"   Matches from today onwards: {upcoming}")

    cur.execute("SELECT event_date, event_status, COUNT(*) FROM matches GROUP BY event_date, event_status ORDER BY event_date DESC LIMIT 10")
    rows = cur.fetchall()
    if rows:
        print("\n   Most recent dates in DB:")
        for r in rows:
            print(f"     {r[0]}  status={r[1]}  count={r[2]}")
    conn.close()
except Exception as e:
    print(f"   ❌ DB error: {e}")

print()
print("2. Testing API key...")
try:
    resp = requests.get(
        "https://api.api-tennis.com/tennis/",
        params={"method": "get_fixtures", "APIkey": API_KEY,
                "date_start": "2026-05-02", "date_stop": "2026-05-04"},
        timeout=15
    )
    data = resp.json()
    if data.get("error"):
        print(f"   ❌ API error: {data}")
    else:
        results = data.get("result", [])
        print(f"   ✅ API returned {len(results)} fixtures for 2026-05-02 to 2026-05-04")
        if results:
            print(f"   First event: {results[0].get('event_first_player')} vs {results[0].get('event_second_player')}")
except Exception as e:
    print(f"   ❌ API error: {e}")

print()
print("=" * 50)
EOF

echo ""
read -n 1 -s -r -p "Press any key to close..."
