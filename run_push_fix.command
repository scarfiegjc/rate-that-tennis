#!/bin/bash
# One-shot: commit & push the FormDots + ITF filter fixes
cd "$(dirname "$0")"

echo ""
echo "╔══════════════════════════════════════════════════╗"
echo "║     ratethat.tennis — Push Today's Fixes         ║"
echo "╚══════════════════════════════════════════════════╝"
echo ""
echo "▶  Committing: FormDots removal + ITF prediction filter restore..."
git add frontend/src/pages/MatchList.jsx ml/predict.py CLAUDE.md
git commit -m "Remove FormDots from MatchList; restore ITF exclusion from predictions"
git push origin main
echo ""
echo "✓  Done. Railway will redeploy in ~2 minutes."
echo ""
read -p "Press Enter to close..."
