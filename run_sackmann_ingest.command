#!/bin/bash
# ratethat.tennis — Sackmann Ingestion Runner
# Double-click this file to run the full historical data load

cd "$(dirname "$0")"

echo "============================================"
echo " ratethat.tennis — Sackmann Data Ingestion"
echo "============================================"
echo ""

# Install deps if needed
echo "Checking dependencies..."
pip3 install psycopg2-binary requests --quiet --break-system-packages 2>/dev/null || \
pip3 install psycopg2-binary requests --quiet

echo ""
echo "Starting ingestion... (this will take 10-20 minutes)"
echo ""

python3 pipeline/sackmann_ingest.py --job all

echo ""
echo "============================================"
echo " Done! Press any key to close."
echo "============================================"
read -n 1
