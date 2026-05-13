#!/bin/bash
# ratethat.tennis — ITF Historical Backfill
# Fetches 3 years of ITF match results from api-tennis.com so ITF players
# get real Elo history and meaningful predictions (not 50/50).
# Resumable: safe to stop and restart — won't re-fetch completed weeks.

cd "$(dirname "$0")"

echo ""
echo "╔══════════════════════════════════════════════════╗"
echo "║    ratethat.tennis — ITF Historical Backfill     ║"
echo "╚══════════════════════════════════════════════════╝"
echo ""

# Load env vars
if [ -f .env ]; then
    export $(grep -v '^#' .env | xargs)
fi

echo "▶  1/3 Fetching 3 years of ITF match history from api-tennis.com..."
echo "     (14-day chunks, resumable — ~5 mins for full 3-year run)"
python3 -m pipeline.itf_backfill --years 3

echo ""
echo "▶  2/3 Re-running predictions (ITF players now have Elo history)..."
python3 -m ml.predict --upcoming 7

echo ""
echo "▶  3/3 Evaluating systems..."
python3 -m ml.systems --upcoming 7

echo ""
echo "✓  Done. ITF players should now have real predictions."
echo "   Check the site to verify predictions look reasonable."
echo ""
read -p "Press Enter to close..."
