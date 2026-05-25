#!/bin/bash
# ratethat.tennis — Bzzoiro data ingestion
# Pulls match serve stats, win predictions, ATP/WTA rankings, and player bios
# from the Bzzoiro API and upserts into the production database.
cd "$(dirname "$0")"

echo "============================================"
echo " ratethat.tennis — Bzzoiro Ingestion"
echo "============================================"
echo ""

echo "Installing dependencies..."
pip3 install requests psycopg2-binary python-dotenv \
  --quiet --break-system-packages 2>/dev/null || \
pip3 install requests psycopg2-binary python-dotenv --quiet

echo ""

# Default to last 30 days if no args
DAYS_BACK=${1:-30}

echo "Syncing rankings..."
python3 -m pipeline.bzzoiro_ingest --job rankings

echo ""
echo "Syncing player bios..."
python3 -m pipeline.bzzoiro_ingest --job bios

echo ""
echo "Syncing matches (last ${DAYS_BACK} days — this may take a few minutes)..."
python3 -m pipeline.bzzoiro_ingest --job matches --days-back "$DAYS_BACK"

echo ""
echo "Syncing predictions (last ${DAYS_BACK} days)..."
python3 -m pipeline.bzzoiro_ingest --job predictions --days-back "$DAYS_BACK"

if [ $? -eq 0 ]; then
  echo ""
  echo "✅ Done. New serve stats, rankings, and predictions are now in the DB."
  echo "   Run run_predictions.command to regenerate RTT predictions with the fresh data."
else
  echo ""
  echo "❌ Something went wrong. Check the output above for details."
fi

echo ""
read -n 1 -s -r -p "Press any key to close..."
echo ""
