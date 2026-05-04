#!/bin/bash
# ratethat.tennis — Fetch today's match fixtures
# Run this once a day to pull upcoming matches into the database.
cd "$(dirname "$0")"

echo "============================================"
echo " ratethat.tennis — Fetch Fixtures"
echo "============================================"
echo ""

echo "Installing dependencies..."
pip3 install requests psycopg2-binary python-dotenv \
  --quiet --break-system-packages 2>/dev/null || \
pip3 install requests psycopg2-binary python-dotenv --quiet

echo ""
echo "Fetching today's fixtures from api-tennis.com..."
python3 pipeline/pipeline.py --job daily_fixtures

if [ $? -eq 0 ]; then
  echo ""
  echo "✅ Done. Refresh http://localhost:3000 to see today's matches."
else
  echo ""
  echo "❌ Something went wrong. Check the output above for details."
fi

echo ""
read -n 1 -s -r -p "Press any key to close..."
echo ""
