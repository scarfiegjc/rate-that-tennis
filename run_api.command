#!/bin/bash
# ratethat.tennis — Start the REST API server
# Double-click to run. API will be available at http://localhost:8000
cd "$(dirname "$0")"
echo "============================================"
echo " ratethat.tennis — API Server"
echo "============================================"
echo ""

echo "Installing API dependencies..."
pip3 install fastapi uvicorn psycopg2-binary sqlalchemy python-dotenv \
  --quiet --break-system-packages 2>/dev/null || \
pip3 install fastapi uvicorn psycopg2-binary sqlalchemy python-dotenv --quiet

echo ""
echo "Starting API at http://localhost:8000"
echo "  Docs:    http://localhost:8000/docs"
echo "  Health:  http://localhost:8000/health"
echo ""
echo "Press Ctrl+C to stop."
echo ""

python3 -m uvicorn api.main:app --reload --host 0.0.0.0 --port 8000
