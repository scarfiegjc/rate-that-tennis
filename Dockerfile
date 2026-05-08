# ratethat.tennis — API service
# Railway deployment: set root directory to / (repo root), Dockerfile path to ./Dockerfile
#
# This image now also carries the lightweight pipeline modules so the API can
# self-bootstrap (schema migrations + surface backfill + fill ratings +
# predictions) on startup and via /admin/* endpoints. This is a safety net so
# the site keeps working even if the pipeline service has issues.
#
# Environment variables required on Railway:
#   DATABASE_URL      — auto-linked from Railway Postgres service
#   CORS_ORIGINS      — comma-separated, e.g. https://ratethat.tennis,https://www.ratethat.tennis

FROM python:3.12-slim

WORKDIR /app

# Install dependencies
COPY api/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# API package
COPY api/ ./api/

# Pipeline modules the bootstrap path needs (psycopg2 + stdlib only, no pandas/scipy).
COPY pipeline/predictions_schema.sql ./api/_migrations/predictions_schema.sql
COPY pipeline/schema_additions.sql   ./api/_migrations/schema_additions.sql
COPY pipeline/matchstat_schema.sql   ./api/_migrations/matchstat_schema.sql
COPY pipeline/surface_backfill.py    ./surface_backfill.py
COPY pipeline/hand_backfill.py       ./hand_backfill.py
COPY pipeline/player_sync.py         ./player_sync.py
COPY pipeline/fill_ratings.py        ./fill_ratings.py
COPY pipeline/form_score.py          ./form_score.py
COPY pipeline/point_analysis.py      ./point_analysis.py
COPY pipeline/player_splits.py       ./player_splits.py
COPY pipeline/settle_predictions.py  ./settle_predictions.py
COPY pipeline/matchstat_ingest.py    ./matchstat_ingest.py

# ML package (rtt_predictor + systems engine — both lightweight)
COPY ml/__init__.py                  ./ml/__init__.py
COPY ml/rtt_predictor.py             ./ml/rtt_predictor.py
COPY ml/systems.py                   ./ml/systems.py

# Expose port — must match $PORT injected by Railway (default 8080)
EXPOSE 8080

# Start uvicorn — PORT is injected by Railway (defaults to 8080)
CMD ["sh", "-c", "uvicorn api.main:app --host 0.0.0.0 --port ${PORT:-8080}"]
