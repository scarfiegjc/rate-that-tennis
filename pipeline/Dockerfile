# ratethat.tennis — Pipeline service
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
COPY pipeline/odds_io.py             ./odds_io.py
COPY pipeline/email_tasks.py         ./email_tasks.py
COPY api/email.py                    ./email_utils.py
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
COPY pipeline/picks_schema.sql          ./picks_schema.sql

# ML package (proper package import — `from ml.rtt_predictor import …`).
# We deliberately copy ONLY the lightweight modules the scheduler needs at
# runtime — they use psycopg2 + stdlib only. Heavy modules (ratings.py uses
# scipy; train/backtest use xgboost+lightgbm) stay out so the pipeline image
# remains slim and boots fast.
COPY ml/__init__.py                  ./ml/__init__.py
COPY ml/rtt_predictor.py             ./ml/rtt_predictor.py
COPY ml/systems.py                   ./ml/systems.py

CMD ["python", "scheduler.py"]
