#!/bin/bash
# ratethat.tennis — Fix all Unknown tournament surfaces in the live DB
# Double-click to run.

cd "$(dirname "$0")"

echo ""
echo "╔══════════════════════════════════════════════════╗"
echo "║   ratethat.tennis — Fix Unknown Surfaces         ║"
echo "╚══════════════════════════════════════════════════╝"
echo ""

# Load env vars if .env exists
if [ -f .env ]; then
    export $(grep -v '^#' .env | xargs)
fi

echo "▶  Running surface backfill (keyword inference + Hard default)..."
python3 -m pipeline.surface_backfill

echo ""
echo "✓  Done. All Unknown surfaces have been resolved."
echo "   (Known tournaments → correct surface; unrecognised → Hard)"
echo ""
read -p "Press Enter to close..."
