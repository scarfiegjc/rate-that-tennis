#!/bin/bash
# ratethat.tennis — one-shot deploy script for the bookmaker odds feature.
#
# What this does:
#   1. Saves the current local commit (the odds feature) as a backup tag
#   2. Fetches the latest origin/deploy-clean
#   3. Hard-resets local deploy-clean to match origin/deploy-clean exactly
#   4. Cherry-picks the odds-feature commit on top, preferring the
#      cherry-picked changes (mine) on any conflicts
#   5. Pushes to origin/deploy-clean → triggers Railway auto-deploy
#
# Safe to re-run if it fails partway. The backup tag (odds-feature-backup)
# means no work is lost.

set -e
cd "$(dirname "$0")"

echo ""
echo "═══════════════════════════════════════════════════════"
echo "  ratethat.tennis — deploying bookmaker odds feature"
echo "═══════════════════════════════════════════════════════"
echo ""

# 1. Tag the current local commit so we can recover it if anything goes wrong
echo "→ Backing up current local HEAD as tag 'odds-feature-backup'..."
ODDS_COMMIT=$(git rev-parse HEAD)
git tag -f odds-feature-backup HEAD
echo "  Backed up: $ODDS_COMMIT"
echo ""

# 2. Fetch latest remote state
echo "→ Fetching origin/deploy-clean..."
git fetch origin deploy-clean
echo ""

# 3. Reset local to remote (discards 40 autosave commits — these are noise)
echo "→ Resetting local deploy-clean to match origin/deploy-clean..."
git reset --hard origin/deploy-clean
echo ""

# 4. Cherry-pick the odds commit on top, preferring my changes on conflicts
echo "→ Cherry-picking odds feature commit on top..."
if git cherry-pick -X theirs "$ODDS_COMMIT"; then
    echo "  Cherry-pick clean."
else
    echo "  Cherry-pick had conflicts; resolving by taking the odds branch's version..."
    # Take the cherry-picked version of any conflicting files
    git diff --name-only --diff-filter=U | while read f; do
        git checkout --theirs "$f"
        git add "$f"
        echo "    Resolved: $f"
    done
    git cherry-pick --continue --no-edit
fi
echo ""

# 5. Push
echo "→ Pushing to origin/deploy-clean..."
git push origin deploy-clean
echo ""

echo "═══════════════════════════════════════════════════════"
echo "  ✓ Done. Railway will auto-deploy in ~2 minutes."
echo "═══════════════════════════════════════════════════════"
echo ""
echo "Next: paste your ODDS_API_KEY into Railway → Variables."
echo "Key:  8ca16e3b4dd6430cef3e791f268ae722"
echo "Var:  ODDS_API_KEY"
echo ""
echo "After that, the scheduler runs the odds pipeline twice a day"
echo "automatically (20:00 + 05:00 UTC). Match pages will start showing"
echo "odds within a few hours of the next scheduled run, or you can"
echo "trigger one immediately by visiting:"
echo "    https://YOUR-RAILWAY-API/admin/run-odds"
echo ""
echo "(Press any key to close this window.)"
read -n 1
