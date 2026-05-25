#!/bin/bash
# ratethat.tennis — Player bio backfill from Sackmann historical data
# Populates height_cm, hand, country_code, and current_rank for players
# where these fields are missing, by matching against sa_players / sa_rankings.
cd "$(dirname "$0")"

echo "============================================"
echo " ratethat.tennis — Player Bio Backfill"
echo "============================================"
echo ""

echo "Installing dependencies..."
pip3 install requests psycopg2-binary python-dotenv \
  --quiet --break-system-packages 2>/dev/null || \
pip3 install requests psycopg2-binary python-dotenv --quiet

echo ""
echo "Running player bio backfill from Sackmann data..."
python3 -m pipeline.player_bio_backfill --verbose

if [ $? -eq 0 ]; then
  echo ""
  echo "✅ Done. Player height, hand, and ranking data updated from Sackmann records."
else
  echo ""
  echo "❌ Something went wrong. Check the output above for details."
fi

echo ""
read -n 1 -s -r -p "Press any key to close..."
echo ""
