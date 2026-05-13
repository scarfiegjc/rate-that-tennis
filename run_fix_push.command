#!/bin/bash
# Fix stale macOS Keychain credential that's blocking git push, then push.
cd "$(dirname "$0")"

echo ""
echo "╔══════════════════════════════════════════════════╗"
echo "║     ratethat.tennis — Fix Auth & Push            ║"
echo "╚══════════════════════════════════════════════════╝"
echo ""

echo "▶  Clearing stale GitHub credential from macOS Keychain..."
printf 'protocol=https\nhost=github.com\n' | git credential-osxkeychain erase
echo "   Done."

echo ""
echo "▶  Pushing to GitHub (main)..."
git push origin main

echo ""
echo "✓  If you see 'Everything up-to-date' or branch info above, it worked."
echo "   Railway will redeploy in ~2 minutes."
echo ""
read -p "Press Enter to close..."
