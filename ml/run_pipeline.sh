#!/bin/bash
# ratethat.tennis — Full ML Pipeline Runner
# Run from the RateThatTennis/ root directory.
#
# Steps:
#   1. Build feature matrix from sa_matches (saved to ml/results/features.parquet)
#   2. Train all models (XGBoost, LightGBM, Logistic, Ensemble) — overall + per-surface
#   3. Walk-forward backtest (2015–2024) — saves ml/results/backtest_results.json
#   4. Open ML Lab in browser to review results

set -e

echo "================================================"
echo "  ratethat.tennis — ML Pipeline"
echo "================================================"
echo ""

# ── Install dependencies
echo "[1/4] Installing ML dependencies..."
pip3 install -r ml/requirements.txt --quiet --break-system-packages 2>/dev/null || \
pip3 install -r ml/requirements.txt --quiet

echo ""
echo "[2/4] Building feature matrix from sa_matches..."
echo "      (This reads from Railway PostgreSQL — takes 5-15 min depending on data size)"
python3 -m ml.train --build-features --test-year 2023

echo ""
echo "[3/4] Running walk-forward backtest (2015–2024)..."
python3 -m ml.backtest --features ml/results/features.parquet --start-year 2015 --end-year 2024

echo ""
echo "[4/4] Opening ML Lab..."
# Copy backtest results to the lab folder for auto-loading
cp ml/results/backtest_results.json ml/lab/backtest_results.json
open ml/lab/index.html

echo ""
echo "================================================"
echo "  Done! ML Lab opened in your browser."
echo "================================================"
