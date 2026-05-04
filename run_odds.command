#!/bin/bash
# ratethat.tennis — Fetch Bookmaker Odds
# Pulls tennis H2H odds from The Odds API and writes to bookmaker_odds table.
#
# REQUIRES: ODDS_API_KEY environment variable
#   Free key at: https://the-odds-api.com  (500 requests/month free)
#   Set it in .env:  ODDS_API_KEY=your_key_here
#
# Run this once or twice daily alongside run_fixtures.command.

cd "$(dirname "$0")"

echo ""
echo "╔══════════════════════════════════════════════════╗"
echo "║        ratethat.tennis — Bookmaker Odds          ║"
echo "╚══════════════════════════════════════════════════╝"
echo ""

# Load env vars
if [ -f .env ]; then
    export $(grep -v '^#' .env | xargs)
fi

if [ -z "$ODDS_API_KEY" ]; then
    echo "❌  ODDS_API_KEY is not set."
    echo ""
    echo "   1. Get a free key at https://the-odds-api.com"
    echo "   2. Add to .env:  ODDS_API_KEY=your_key_here"
    echo "   3. Run this script again."
    echo ""
    read -p "Press Enter to close..."
    exit 1
fi

echo "▶  Fetching odds from The Odds API..."
python3 -m pipeline.odds

echo ""
read -p "Press Enter to close..."
