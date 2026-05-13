#!/bin/bash
# One-shot fix for the GitHub push that was blocked because
# _apply_surface_fix.command contained a hard-coded token.
#
# Steps:
#   1. Delete _apply_surface_fix.command (it was a one-off, already applied)
#   2. Amend the latest commit to drop the file
#   3. Force-push the cleaned commit
#
# Safe to delete this file after running.

set -e
cd "$(dirname "$0")"

echo "🎾 Fixing blocked push..."
echo ""

# Clear any stale git lock
rm -f .git/index.lock .git/HEAD.lock .git/ORIG_HEAD .git/MERGE_HEAD 2>/dev/null

# 1) Drop the offending file
if [ -f _apply_surface_fix.command ]; then
  echo "Removing _apply_surface_fix.command (contains hard-coded token)..."
  git rm -f _apply_surface_fix.command
else
  echo "_apply_surface_fix.command already gone — checking if it's still in the commit..."
  git ls-files --error-unmatch _apply_surface_fix.command 2>/dev/null && \
    git rm --cached _apply_surface_fix.command || \
    echo "  (not tracked)"
fi

# 2) Amend the latest commit so the offending file is removed from it
echo ""
echo "Amending latest commit..."
git -c user.email="gareth.cartman@gmail.com" -c user.name="Gareth" \
    commit --amend --no-edit

# 3) Force-push (commit hash changed because of the amend)
echo ""
echo "Force-pushing cleaned commit to GitHub..."
GIT_TERMINAL_PROMPT=0 git -c credential.helper= push --force \
  https://github.com/scarfiegjc/rate-that-tennis.git \
  HEAD:main

if [ $? -eq 0 ]; then
  echo ""
  echo "✅ Done. Railway will redeploy with the new scheduler.py + predict.py."
  echo ""
  echo "💡 Recommendation: rotate the GitHub token at"
  echo "   https://github.com/settings/tokens"
  echo "   and store the new one in ~/.netrc or a keychain rather than embedding"
  echo "   it in push_to_github.command."
else
  echo ""
  echo "❌ Push failed. Most likely the token has expired — generate a fresh one"
  echo "   at https://github.com/settings/tokens (scope: 'repo'), then update"
  echo "   push_to_github.command and rerun this file."
fi

echo ""
read -p "Press Enter to close..."
