#!/bin/bash
# ratethat.tennis — Full ML Pipeline
# Builds features → trains models → backtests → opens ML Lab
cd "$(dirname "$0")"
echo "============================================"
echo " ratethat.tennis — ML Pipeline"
echo "============================================"
echo ""

echo "[1/4] Installing ML dependencies..."
pip3 install pandas numpy scikit-learn xgboost lightgbm pyarrow psycopg2-binary sqlalchemy scipy \
  --quiet --break-system-packages 2>/dev/null || \
pip3 install pandas numpy scikit-learn xgboost lightgbm pyarrow psycopg2-binary sqlalchemy scipy --quiet

# Fix XGBoost on macOS: needs libomp (OpenMP runtime)
if command -v brew &>/dev/null; then
  echo "      Installing libomp via Homebrew (needed for XGBoost)..."
  brew install libomp --quiet 2>/dev/null || true
fi

echo ""
echo "[2/4] Building feature matrix + training models..."
echo "      (reads from Railway PostgreSQL — 10-30 min first run)"
python3 -m ml.train --build-features --test-year 2023
if [ $? -ne 0 ]; then
  echo ""
  echo "ERROR: Training failed. Check output above."
  read -n 1
  exit 1
fi

echo ""
echo "[3/4] Running walk-forward backtest (2015-2024)..."
python3 -m ml.backtest --features ml/results/features.parquet --start-year 2015 --end-year 2024
if [ $? -ne 0 ]; then
  echo ""
  echo "ERROR: Backtest failed. Check output above."
  read -n 1
  exit 1
fi

echo ""
echo "[4/4] Copying results to ML Lab + opening..."
cp ml/results/backtest_results.json ml/lab/backtest_results.json
open ml/lab/index.html

echo ""
echo "============================================"
echo " Done! ML Lab opened in your browser."
echo "============================================"
read -n 1
