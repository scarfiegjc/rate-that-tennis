#!/bin/bash
# push_picks_fix.command — double-click to commit and push the picks bug fix

cd "$(dirname "$0")"

echo ""
echo "🎾 Pushing picks fix to Railway..."
echo ""

git add api/routes/picks.py frontend/src/components/StarPick.jsx
git commit -m "Fix 409 star handling + expose enrich errors for debugging"
git push origin main

echo ""
echo "✅ Done! Railway will redeploy in ~3 minutes."
echo ""
read -p "Press Enter to close..."
