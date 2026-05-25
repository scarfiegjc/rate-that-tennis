#!/bin/bash
# ratethat.tennis — Aggregate Sackmann charting data into serve_zones table
# Reads sa_charting_points (W/B/T serve placement from Match Charting Project)
# and aggregates by player / surface / serve number / court side / zone.
#
# PREREQUISITE: sa_charting_points must be populated first.
# If it's empty, run: python3 -m pipeline.sackmann_ingest --job charting
# (that takes 30-60 minutes and requires the tennis_MatchChartingProject repo cloned locally)
cd "$(dirname "$0")"

echo "============================================"
echo " ratethat.tennis — Serve Zones Aggregation"
echo "============================================"
echo ""

echo "Installing dependencies..."
pip3 install requests psycopg2-binary python-dotenv \
  --quiet --break-system-packages 2>/dev/null || \
pip3 install requests psycopg2-binary python-dotenv --quiet

echo ""
echo "Checking sa_charting_points..."
python3 -c "
import os, sys
sys.path.insert(0, '.')
from dotenv import load_dotenv
load_dotenv()
import psycopg2
conn = psycopg2.connect(os.environ.get('DATABASE_PUBLIC_URL') or os.environ['DATABASE_URL'])
cur = conn.cursor()
try:
    cur.execute('SELECT COUNT(*) FROM sa_charting_points')
    n = cur.fetchone()[0]
    print(f'sa_charting_points rows: {n}')
    if n == 0:
        print('WARNING: sa_charting_points is empty.')
        print('Run: python3 -m pipeline.sackmann_ingest --job charting')
        print('(this downloads and parses the Match Charting Project CSVs — takes ~30-60 min)')
        sys.exit(1)
except Exception as e:
    print(f'Table does not exist or error: {e}')
    print('Run: python3 -m pipeline.sackmann_ingest --job charting first')
    sys.exit(1)
conn.close()
"

if [ $? -ne 0 ]; then
  echo ""
  echo "⚠️  Charting data not yet loaded. See warning above."
  echo ""
  read -n 1 -s -r -p "Press any key to close..."
  echo ""
  exit 1
fi

echo ""
echo "Aggregating serve zones from charting data..."
python3 -m pipeline.charting_to_serve_zones --verbose

if [ $? -eq 0 ]; then
  echo ""
  echo "✅ Done. serve_zones table populated — Serve tab will now show W/B/T placement data."
else
  echo ""
  echo "❌ Something went wrong. Check the output above for details."
fi

echo ""
read -n 1 -s -r -p "Press any key to close..."
echo ""
