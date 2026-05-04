#!/bin/bash
# ratethat.tennis — RTT Rating Pipeline
# Computes all 13 player ratings from Sackmann data → writes to Railway DB
cd "$(dirname "$0")"
echo "============================================"
echo " ratethat.tennis — Rating Pipeline"
echo "============================================"
echo ""

pip3 install psycopg2-binary pandas numpy scipy --quiet --break-system-packages 2>/dev/null || \
pip3 install psycopg2-binary pandas numpy scipy --quiet

echo ""
echo "Running rating computation..."
python3 -m ml.ratings "$@"

echo ""
echo "============================================"
echo " Done! Press any key to close."
echo "============================================"
read -n 1
