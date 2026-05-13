#!/bin/bash
cd "$(dirname "$0")"

echo "🎾 Pushing Join page + Admin marketing to Railway..."
echo ""

TOKEN="YOUR_GITHUB_TOKEN_HERE"
REMOTE="https://scarfiegjc:${TOKEN}@github.com/scarfiegjc/rate-that-tennis.git"

# Clear stale lock files
rm -f .git/index.lock .git/MERGE_HEAD .git/rebase-merge/head-name 2>/dev/null

# Stage our new/modified files first
echo "Staging changes..."
git add \
  frontend/src/App.jsx \
  frontend/src/pages/JoinPage.jsx \
  frontend/src/pages/AccountPage.jsx \
  frontend/src/pages/AdminPage.jsx \
  api/email.py \
  api/routes/account.py \
  api/routes/admin_marketing.py \
  api/main.py \
  pipeline/schema_additions.sql

# Commit our work (even if already committed, this is a no-op if nothing staged)
git -c user.email="gareth.cartman@gmail.com" -c user.name="Gareth" \
  commit -m "Add Join page, Account settings, Admin marketing, Resend email" 2>/dev/null || true

# Now pull remote changes with rebase so our commit sits on top
echo "Syncing with remote (rebase)..."
git -c user.email="gareth.cartman@gmail.com" -c user.name="Gareth" \
  pull --rebase "$REMOTE" main

if [ $? -ne 0 ]; then
  echo ""
  echo "❌ Rebase conflict — aborting and trying merge instead..."
  git rebase --abort 2>/dev/null || true

  # Stage + commit again in case rebase wiped working tree state
  git add \
    frontend/src/App.jsx \
    frontend/src/pages/JoinPage.jsx \
    frontend/src/pages/AccountPage.jsx \
    frontend/src/pages/AdminPage.jsx \
    api/email.py \
    api/routes/account.py \
    api/routes/admin_marketing.py \
    api/main.py \
    pipeline/schema_additions.sql

  git -c user.email="gareth.cartman@gmail.com" -c user.name="Gareth" \
    commit -m "Add Join page, Account settings, Admin marketing, Resend email" 2>/dev/null || true

  git -c user.email="gareth.cartman@gmail.com" -c user.name="Gareth" \
    pull --no-rebase -X ours "$REMOTE" main
fi

echo "Pushing..."
git push "$REMOTE" HEAD:main

if [ $? -eq 0 ]; then
  echo ""
  echo "✅ Done! Railway will redeploy in ~2 minutes."
  echo "   Join page:    ratethat.tennis/join"
  echo "   Account page: ratethat.tennis/account"
  echo "   Admin page:   ratethat.tennis/admin"
else
  echo ""
  echo "❌ Push failed — paste the error above."
fi

echo ""
read -p "Press Enter to close..."
