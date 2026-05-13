# ratethat.tennis — Pipeline service — rebuild forced 2026-05-12i
# Railway deployment:
#   * Service Root Directory: / (repo root) — IMPORTANT: must be `/`, not `pipeline/`,
#     because the pipeline now also imports ml/ for the RTT predictor.
#   * Dockerfile path: pipeline/Dockerfile
#
# Environment variables required on Railway:
#   DATABASE_URL      — auto-linked from Railway Postgres service
#   API_TENNIS_KEY    — api-tennis.com API key

FROM python:3.12-slim

WORKDIR /app

# Install dependencies
COPY pipeline/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# Pipeline scripts (copied flat for legacy `from auto_data import …` imports)
COPY pipeline/pipeline.py            ./pipeline.py
COPY pipeline/scheduler.py           ./scheduler.py
COPY pipeline/odds.py                ./odds.py
COPY pipeline/auto_data.py           ./auto_data.py
COPY pipeline/player_splits.py       ./player_splits.py
COPY pipeline/settle_predictions.py  ./settle_predictions.py
COPY pipeline/surface_backfill.py    ./surface_backfill.py
COPY pipeline/player_sync.py         ./player_sync.py
COPY pipeline/fill_ratings.py        ./fill_ratings.py

# SQL migrations (applied on boot by scheduler.apply_schema_migrations).
# Idempotent — re-running them is a no-op.
COPY pipeline/schema_additions.sql      ./schema_additions.sql
COPY pipeline/predictions_schema.sql    ./predictions_schema.sql

# ML package — all modules needed by the scheduler plus the trained model
# pickles so LivePredictor uses the full XGBoost/LightGBM/Logistic ensemble
# instead of falling back to Elo-only. xgboost + lightgbm are now in
# requirements.txt so the ensemble pkl files deserialise correctly.
COPY ml/__init__.py                  ./ml/__init__.py
COPY ml/rtt_predictor.py             ./ml/rtt_predictor.py
COPY ml/systems.py                   ./ml/systems.py
COPY ml/predict.py                   ./ml/predict.py
COPY ml/elo.py                       ./ml/elo.py
COPY ml/features.py                  ./ml/features.py
COPY ml/train.py                     ./ml/train.py
COPY ml/models/                      ./ml/models/

CMD ["python", "scheduler.py"]
