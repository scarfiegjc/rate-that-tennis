#!/bin/bash
# ratethat.tennis — TML-Database Ingestion
# Downloads ATP match CSVs from github.com/Tennismylife/TML-Database
# and loads them into the sa_matches table (tour='TML').
#
# MIT-licensed data — safe for commercial use.
# Covers ATP matches 1968–present with full serve/return stats from ~2000.
#
# Run once to do the initial load, then occasionally for incremental updates.

cd "$(dirname "$0")"

echo ""
echo "╔══════════════════════════════════════════════════╗"
echo "║      ratethat.tennis — TML Data Ingestion        ║"
echo "╚══════════════════════════════════════════════════╝"
echo ""

# Load env vars
if [ -f .env ]; then
    export $(grep -v '^#' .env | xargs)
fi

echo "▶  Ingesting TML-Database (2000–$(date +%Y))..."
echo "   Source: github.com/Tennismylife/TML-Database"
echo "   Licence: MIT"
echo ""
python3 -m pipeline.tml_ingest "$@"

echo ""
read -p "Press Enter to close..."
