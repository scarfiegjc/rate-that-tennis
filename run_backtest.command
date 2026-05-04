#!/bin/bash
# ratethat.tennis — Run walk-forward backtest only
# Requires ml/results/features.parquet to exist (run run_ml_pipeline.command first)
cd "$(dirname "$0")"
echo "============================================"
echo " ratethat.tennis — Walk-Forward Backtest"
echo "============================================"
echo ""

if [ ! -f "ml/results/features.parquet" ]; then
  echo "ERROR: ml/results/features.parquet not found."
  echo "Run run_ml_pipeline.command first to build features."
  read -n 1
  exit 1
fi

echo "Running walk-forward backtest (2015-2024)..."
python3 -m ml.backtest --features ml/results/features.parquet --start-year 2015 --end-year 2024
if [ $? -ne 0 ]; then
  echo ""
  echo "ERROR: Backtest failed. Check output above."
  read -n 1
  exit 1
fi

echo ""
echo "Copying results to ML Lab..."
cp ml/results/backtest_results.json ml/lab/backtest_results.json 2>/dev/null || true

echo "Opening ML Lab..."
open ml/lab/index.html

echo ""
echo "============================================"
echo " Done! Press any key to close."
echo "============================================"
read -n 1
