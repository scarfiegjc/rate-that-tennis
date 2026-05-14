#!/bin/bash
# Scrape Bresbet tennis page and store affiliate deep links for upcoming matches.
# Double-click to run, or: ./run_bresbet_links.command

cd "$(dirname "$0")"

if [ -f .env ]; then
  export $(grep -v '^#' .env | xargs)
fi

echo "🎾 Scraping Bresbet for deep links..."
python3 -m pipeline.bresbet_links "$@"
echo ""
echo "Done. Check above for matched/skipped counts."
