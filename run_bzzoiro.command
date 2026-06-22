#!/bin/bash
# ratethat.tennis — Run bzzoiro pipeline (all jobs)
# Double-click to run, or: bash run_bzzoiro.command

cd "$(dirname "$0")"

# Load environment variables
if [ -f .env ]; then
    source .env 2>/dev/null || true
fi

echo "ratethat.tennis — bzzoiro pipeline"
echo "==================================="

python3 -m pipeline.bzzoiro --job all

echo ""
echo "Done."
