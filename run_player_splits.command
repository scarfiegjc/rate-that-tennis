#!/bin/bash
# ratethat.tennis — Compute player hand-vs-hand splits
cd "$(dirname "$0")"
echo ""
echo "╔══════════════════════════════════════════════════╗"
echo "║   ratethat.tennis — Player Hand Splits           ║"
echo "╚══════════════════════════════════════════════════╝"
echo ""

if [ -f .env ]; then
    export $(grep -v '^#' .env | xargs)
fi

pip3 install psycopg2-binary --quiet --break-system-packages 2>/dev/null || \
pip3 install psycopg2-binary --quiet

python3 -m pipeline.player_splits

echo ""
echo "✓  Player splits computed."
echo ""
read -p "Press Enter to close..."
