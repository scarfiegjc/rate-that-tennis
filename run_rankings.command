#!/bin/bash
# ratethat.tennis — Re-run rankings ingestion only
cd "$(dirname "$0")"
echo "============================================"
echo " ratethat.tennis — Rankings Re-ingestion"
echo "============================================"
echo ""
pip3 install psycopg2-binary requests --quiet --break-system-packages 2>/dev/null || \
pip3 install psycopg2-binary requests --quiet
echo ""
python3 pipeline/sackmann_ingest.py --job rankings
echo ""
echo "============================================"
echo " Done! Press any key to close."
echo "============================================"
read -n 1
