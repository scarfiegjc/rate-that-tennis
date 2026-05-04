#!/bin/bash
# ratethat.tennis — Run predictions pipeline
# Double-click to predict all upcoming matches and write to model_predictions table.

cd "$(dirname "$0")"

echo ""
echo "╔══════════════════════════════════════════════════╗"
echo "║        ratethat.tennis — Predictions             ║"
echo "╚══════════════════════════════════════════════════╝"
echo ""

# Load env vars if .env exists
if [ -f .env ]; then
    export $(grep -v '^#' .env | xargs)
fi

echo "▶  1/4 Refresh hand-vs-hand splits..."
python3 -m pipeline.player_splits || echo "    (player_splits step skipped — table may not exist yet)"

echo ""
echo "▶  2/4 Predict upcoming matches (RTT v1 — RTT-based, transparent factors)..."
python3 -m ml.rtt_predictor --upcoming 7

echo ""
echo "▶  3/4 Settle finished matches (last 14 days)..."
python3 -m pipeline.settle_predictions

echo ""
echo "▶  4/4 Evaluate systems (Surface Monster, Form Surge, Hand Advantage, …)..."
python3 -m ml.systems --upcoming 7

echo ""
echo "✓  Predictions complete. Refresh the site to see probabilities."
echo ""
read -p "Press Enter to close..."
