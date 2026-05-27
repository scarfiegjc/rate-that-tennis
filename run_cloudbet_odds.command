#!/bin/bash
cd "$(dirname "$0")"

echo "╔══════════════════════════════════════════════════╗"
echo "║      ratethat.tennis — Cloudbet Odds             ║"
echo "╚══════════════════════════════════════════════════╝"
echo ""

set -a; [ -f .env ] && source .env; set +a

echo "▶  Fetching odds from Cloudbet..."
python3 -m pipeline.cloudbet_odds

echo ""
echo "Press Enter to close..."
read
