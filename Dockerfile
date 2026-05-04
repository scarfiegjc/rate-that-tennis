# ratethat.tennis — API service
# Railway deployment: set root directory to / (repo root), Dockerfile path to ./Dockerfile
#
# Environment variables required on Railway:
#   DATABASE_URL      — auto-linked from Railway Postgres service
#   CORS_ORIGINS      — comma-separated, e.g. https://ratethat.tennis,https://www.ratethat.tennis

FROM python:3.12-slim

WORKDIR /app

# Install dependencies
COPY api/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# Copy the api package (imports as 'api.main', 'api.routes', 'api.db')
COPY api/ ./api/

# Expose port — must match $PORT injected by Railway (default 8080)
EXPOSE 8080

# Start uvicorn — PORT is injected by Railway (defaults to 8080)
CMD ["sh", "-c", "uvicorn api.main:app --host 0.0.0.0 --port ${PORT:-8080}"]
