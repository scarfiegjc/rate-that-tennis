"""
ratethat.tennis — FastAPI application.

Run locally:
    uvicorn api.main:app --reload --port 8000

Deploy on Railway:
    Procfile: web: uvicorn api.main:app --host 0.0.0.0 --port $PORT
"""
import os
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api.routes.matches import router as matches_router
from api.routes.players import router as players_router
from api.routes.predictions import router as predictions_router

# ─────────────────────────────────────────────────────────────────────────────
# App setup
# ─────────────────────────────────────────────────────────────────────────────

app = FastAPI(
    title="ratethat.tennis API",
    description="Tennis match predictions, player ratings, and betting intelligence.",
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
)

# CORS — allow the frontend domain + localhost for development
ALLOWED_ORIGINS = os.environ.get(
    "CORS_ORIGINS",
    "https://ratethat.tennis,https://www.ratethat.tennis,http://localhost:3000,http://localhost:5173",
).split(",")

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=False,
    allow_methods=["GET", "OPTIONS"],
    allow_headers=["*"],
)

# ─────────────────────────────────────────────────────────────────────────────
# Routers
# ─────────────────────────────────────────────────────────────────────────────

app.include_router(matches_router, prefix="/api/v1")
app.include_router(players_router, prefix="/api/v1")
app.include_router(predictions_router, prefix="/api/v1")


# ─────────────────────────────────────────────────────────────────────────────
# Health check
# ─────────────────────────────────────────────────────────────────────────────

@app.get("/health")
def health():
    from api.db import query_one
    try:
        result = query_one("SELECT 1 AS ok")
        return {"status": "ok", "db": "connected"}
    except Exception as e:
        return {"status": "error", "db": str(e)}


@app.get("/")
def root():
    return {
        "service": "ratethat.tennis API",
        "version": "1.0.0",
        "docs": "/docs",
        "endpoints": [
            "GET /api/v1/matches/today",
            "GET /api/v1/matches/{id}",
            "GET /api/v1/players/{id}",
            "GET /api/v1/players/{id}/form",
            "GET /api/v1/players/{p1_id}/h2h/{p2_id}",
            "GET /api/v1/predictions/today",
            "GET /api/v1/predictions/history",
            "GET /api/v1/predictions/stats",
            "GET /api/v1/systems",
            "GET /api/v1/systems/{code}/picks",
            "GET /api/v1/systems/{code}/stats",
        ],
    }
