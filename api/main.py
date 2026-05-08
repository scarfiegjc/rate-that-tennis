"""
ratethat.tennis — FastAPI application.

Run locally:
    uvicorn api.main:app --reload --port 8000

Deploy on Railway:
    Procfile: web: uvicorn api.main:app --host 0.0.0.0 --port $PORT
"""
import logging
import os
import threading
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse

from api.routes.matches import router as matches_router
from api.routes.players import router as players_router
from api.routes.predictions import router as predictions_router

log = logging.getLogger("api.main")
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

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


@app.get("/diagnostics")
def diagnostics():
    """
    Self-diagnosing endpoint. Returns a snapshot of data health so the team
    can see at a glance whether the pipeline is producing the expected outputs.
    """
    from api.db import query, query_one

    def _safe_count(sql: str) -> int | str:
        try:
            row = query_one(sql)
            return list(row.values())[0] if row else 0
        except Exception as e:
            msg = str(e).lower()
            if "does not exist" in msg or "undefined" in msg:
                return "missing-schema"
            return f"error: {e}"

    # Core counts
    players_total           = _safe_count("SELECT COUNT(*) FROM players")
    players_with_rtt        = _safe_count("SELECT COUNT(*) FROM player_ratings WHERE rtt_score IS NOT NULL")
    upcoming_matches        = _safe_count(
        "SELECT COUNT(*) FROM matches WHERE event_date BETWEEN CURRENT_DATE AND CURRENT_DATE + INTERVAL '7 days' "
        "AND event_status NOT IN ('Cancelled','Walkover','Postponed','Finished')"
    )
    matches_with_predictions = _safe_count(
        "SELECT COUNT(*) FROM matches m JOIN model_predictions mp ON mp.match_id = m.id "
        "WHERE m.event_date BETWEEN CURRENT_DATE AND CURRENT_DATE + INTERVAL '7 days'"
    )
    matches_no_surface = _safe_count(
        "SELECT COUNT(*) FROM matches m "
        "LEFT JOIN tournaments t ON t.id = m.tournament_id "
        "LEFT JOIN surfaces s ON s.id = t.surface_id "
        "WHERE m.event_date BETWEEN CURRENT_DATE AND CURRENT_DATE + INTERVAL '7 days' "
        "AND (s.name IS NULL OR s.name = 'Unknown')"
    )
    fifty_fifty_predictions = _safe_count(
        "SELECT COUNT(*) FROM model_predictions WHERE prob_first_player BETWEEN 0.49 AND 0.51"
    )
    settled_predictions = _safe_count(
        "SELECT COUNT(*) FROM model_predictions WHERE settled_at IS NOT NULL"
    )
    correct_predictions = _safe_count(
        "SELECT COUNT(*) FROM model_predictions WHERE is_correct IS TRUE"
    )

    # Schema presence
    def _has_table(name: str) -> bool:
        try:
            query_one(f"SELECT 1 FROM {name} LIMIT 1")
            return True
        except Exception:
            return False

    schema = {
        "model_predictions":      _has_table("model_predictions"),
        "player_ratings":         _has_table("player_ratings"),
        "player_ratings_history": _has_table("player_ratings_history"),
        "player_hand_splits":     _has_table("player_hand_splits"),
        "systems":                _has_table("systems"),
        "system_picks":           _has_table("system_picks"),
        "v_predictions_with_results": _has_table("v_predictions_with_results"),
        "v_predictions_daily":        _has_table("v_predictions_daily"),
        "v_systems_stats":            _has_table("v_systems_stats"),
    }

    # Tournaments missing surface
    tournaments_missing_surface = []
    try:
        tournaments_missing_surface = query(
            """
            SELECT t.id, t.name, t.country, t.city, s.name AS surface
            FROM tournaments t
            LEFT JOIN surfaces s ON s.id = t.surface_id
            WHERE (s.name IS NULL OR s.name = 'Unknown')
              AND t.id IN (
                SELECT DISTINCT tournament_id FROM matches
                WHERE event_date BETWEEN CURRENT_DATE AND CURRENT_DATE + INTERVAL '7 days'
              )
            ORDER BY t.name
            LIMIT 25
            """,
        )
    except Exception:
        pass

    # Recent prediction sample
    recent_predictions = []
    try:
        recent_predictions = query(
            """
            SELECT mp.match_id, mp.prob_first_player, mp.prob_second_player,
                   mp.confidence, mp.predictor_version, mp.rtt_gap, mp.surface_gap,
                   p1.name AS p1, p2.name AS p2
            FROM model_predictions mp
            JOIN matches m ON m.id = mp.match_id
            LEFT JOIN players p1 ON p1.id = m.first_player_id
            LEFT JOIN players p2 ON p2.id = m.second_player_id
            ORDER BY mp.predicted_at DESC
            LIMIT 10
            """,
        )
    except Exception:
        pass

    return {
        "players": {
            "total": players_total,
            "with_rtt": players_with_rtt,
            "rtt_coverage_pct": (
                round(100.0 * players_with_rtt / players_total, 1)
                if isinstance(players_total, int) and isinstance(players_with_rtt, int) and players_total
                else None
            ),
        },
        "matches": {
            "upcoming_7d":          upcoming_matches,
            "with_predictions_7d":  matches_with_predictions,
            "no_surface_7d":        matches_no_surface,
            "fifty_fifty":          fifty_fifty_predictions,
        },
        "predictions": {
            "settled":  settled_predictions,
            "correct":  correct_predictions,
            "accuracy_pct": (
                round(100.0 * correct_predictions / settled_predictions, 1)
                if isinstance(settled_predictions, int) and isinstance(correct_predictions, int) and settled_predictions
                else None
            ),
        },
        "schema": schema,
        "tournaments_missing_surface": tournaments_missing_surface,
        "recent_predictions_sample": recent_predictions,
    }


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
            "GET /admin/bootstrap   — run all data migrations + predictions",
            "GET /admin/migrate     — schema migrations only",
            "GET /admin/predict     — re-run predictions only",
        ],
    }


# ─────────────────────────────────────────────────────────────────────────────
# Admin / bootstrap endpoints
# These let us self-heal data state without depending on the pipeline service.
# ─────────────────────────────────────────────────────────────────────────────

def _safe_admin(fn, *args, **kwargs):
    """Wrap an admin task so any exception comes back as JSON with the message + traceback."""
    import traceback
    try:
        return fn(*args, **kwargs)
    except Exception as e:
        log.error(f"admin task {fn.__name__} failed: {e}")
        return {
            "error": str(e),
            "type": type(e).__name__,
            "traceback": traceback.format_exc().splitlines()[-12:],
        }


@app.get("/admin", response_class=HTMLResponse)
def admin_dashboard():
    """Visible admin dashboard with auto-refreshing status + run buttons."""
    from api.admin_dashboard import DASHBOARD_HTML
    return HTMLResponse(content=DASHBOARD_HTML)


@app.get("/admin/bootstrap")
def admin_bootstrap():
    """Run schema + surface backfill + fill ratings + hand splits + predictions + settle + systems."""
    from api.bootstrap import full_bootstrap
    return _safe_admin(full_bootstrap)


@app.get("/admin/migrate")
def admin_migrate():
    """Apply schema migrations only."""
    from api.bootstrap import apply_schema_migrations
    return _safe_admin(apply_schema_migrations)


@app.get("/admin/predict")
def admin_predict(days_ahead: int = 7):
    """Run RTT predictor for upcoming matches."""
    from api.bootstrap import run_rtt_predictions
    return _safe_admin(run_rtt_predictions, days_ahead=days_ahead)


@app.get("/admin/matchstat-spike")
def admin_matchstat_spike(n: int = 10, tour: str = "atp"):
    """
    Diagnostic: probe the Matchstat API on N active players, report on
    name-resolution success, per-match stat coverage, and field population.
    Writes nothing to the database — purely a data-quality check before
    any backfill commitment.
    """
    from api.routes._matchstat_spike import run_spike
    return _safe_admin(run_spike, n_players=n, tour=tour)


@app.get("/admin/surface-backfill")
def admin_surface_backfill():
    """Run tournament surface backfill."""
    from api.bootstrap import run_surface_backfill
    return _safe_admin(run_surface_backfill)


@app.get("/admin/fill-ratings")
def admin_fill_ratings():
    """Fill missing player_ratings rows."""
    from api.bootstrap import run_fill_ratings
    return _safe_admin(run_fill_ratings)


@app.get("/admin/form-score")
def admin_form_score():
    """Recompute the richer form_score for every player."""
    from api.bootstrap import run_form_score
    return _safe_admin(run_form_score)


@app.get("/admin/point-analysis")
def admin_point_analysis():
    """Compute point stats (hold %, break %, BP save/conversion, tiebreak win %) per player."""
    from api.bootstrap import run_point_analysis
    return _safe_admin(run_point_analysis)


@app.get("/admin/point-backfill")
def admin_point_backfill():
    """Backfill sequential metrics (longest game run + deuce return %) only."""
    from api.bootstrap import run_point_backfill_only
    return _safe_admin(run_point_backfill_only)


@app.get("/admin/point-diag")
def admin_point_diag():
    """Show what point-by-point data we actually have in the DB."""
    from api.db import query_one, query
    out = {}
    try:
        out["total_matches"] = (query_one("SELECT COUNT(*) AS n FROM matches WHERE event_status = 'Finished'") or {}).get("n", 0)
        out["total_match_games"] = (query_one("SELECT COUNT(*) AS n FROM match_games") or {}).get("n", 0)
        out["match_games_with_player_served"] = (query_one(
            "SELECT COUNT(*) AS n FROM match_games WHERE player_served IS NOT NULL AND player_served != ''"
        ) or {}).get("n", 0)
        out["match_games_with_serve_winner"] = (query_one(
            "SELECT COUNT(*) AS n FROM match_games WHERE serve_winner IS NOT NULL AND serve_winner != ''"
        ) or {}).get("n", 0)
        out["sample_player_served_values"] = query(
            "SELECT player_served, COUNT(*) AS n FROM match_games GROUP BY player_served ORDER BY n DESC LIMIT 5"
        )
        out["total_match_points"] = (query_one("SELECT COUNT(*) AS n FROM match_points") or {}).get("n", 0)
        out["matches_with_games"] = (query_one(
            "SELECT COUNT(DISTINCT match_id) AS n FROM match_games") or {}).get("n", 0)
        out["matches_with_games_24m"] = (query_one("""
            SELECT COUNT(DISTINCT mg.match_id) AS n FROM match_games mg
            JOIN matches m ON m.id = mg.match_id
            WHERE m.event_date >= CURRENT_DATE - INTERVAL '24 months'
        """) or {}).get("n", 0)
        out["distinct_players_with_games"] = (query_one("""
            SELECT COUNT(DISTINCT pid) AS n FROM (
                SELECT m.first_player_id AS pid FROM matches m JOIN match_games mg ON mg.match_id = m.id
                UNION
                SELECT m.second_player_id      FROM matches m JOIN match_games mg ON mg.match_id = m.id
            ) x
            WHERE pid IS NOT NULL
        """) or {}).get("n", 0)
        out["player_point_stats_rows"] = (query_one("SELECT COUNT(*) AS n FROM player_point_stats") or {}).get("n", 0)
        # Top 5 players by service games
        out["top_players_by_service_games"] = query("""
            SELECT pps.player_id, p.name, pps.service_games, pps.service_hold_pct, pps.matches_analyzed
            FROM player_point_stats pps
            JOIN players p ON p.id = pps.player_id
            ORDER BY pps.service_games DESC NULLS LAST
            LIMIT 5
        """)
    except Exception as e:
        out["error"] = str(e)
    return out


@app.get("/admin/intel/wipe")
def admin_intel_wipe(days_ahead: int = 7):
    """
    Wipe existing intelligence text from upcoming matches so the next scheduled
    run regenerates it with the new prompt. Returns count wiped.
    """
    from api.db import query_one
    try:
        row = query_one(
            """
            UPDATE model_predictions mp
            SET p1_intel = NULL, p2_intel = NULL, match_preview = NULL,
                did_you_know = NULL, confidence_line = NULL,
                intel_generated_at = NULL
            FROM matches m
            WHERE mp.match_id = m.id
              AND m.event_date BETWEEN CURRENT_DATE AND CURRENT_DATE + (%s || ' days')::interval
              AND m.event_status NOT IN ('Cancelled','Walkover','Postponed','Finished')
              AND mp.match_preview IS NOT NULL
            RETURNING mp.match_id
            """ if False else
            """
            WITH wipe AS (
                UPDATE model_predictions mp
                SET p1_intel = NULL, p2_intel = NULL, match_preview = NULL,
                    did_you_know = NULL, confidence_line = NULL,
                    intel_generated_at = NULL
                FROM matches m
                WHERE mp.match_id = m.id
                  AND m.event_date BETWEEN CURRENT_DATE AND CURRENT_DATE + (%s || ' days')::interval
                  AND m.event_status NOT IN ('Cancelled','Walkover','Postponed','Finished')
                  AND mp.match_preview IS NOT NULL
                RETURNING mp.match_id
            )
            SELECT COUNT(*) AS n FROM wipe
            """,
            (days_ahead,),
        )
        return {"wiped": int((row or {}).get("n") or 0)}
    except Exception as e:
        return {"error": str(e)}


@app.get("/admin/hand-backfill")
def admin_hand_backfill():
    """Backfill player.hand from sa_players for any player missing it."""
    from api.bootstrap import run_hand_backfill
    return _safe_admin(run_hand_backfill)


@app.get("/admin/player-sync")
def admin_player_sync(tournaments: bool = False):
    """Enrich existing players from api-tennis. Pass ?tournaments=true to also discover new ones."""
    from api.bootstrap import run_player_sync
    return _safe_admin(run_player_sync, do_tournaments=tournaments)


@app.get("/predictions/backtest")
def predictions_backtest():
    """
    Historical backtest summary — 10-year walk-forward evaluation (2015-2024)
    of the trained XGBoost+LightGBM+Logistic ensemble on ~115k historic matches.
    Numbers baked in here so the response works even if the JSON isn't deployed.
    """
    return {
        "summary": {
            "years_tested":     [2015, 2016, 2017, 2018, 2019, 2020, 2021, 2022, 2023, 2024],
            "total_matches":    114720,
            "mean_accuracy":    0.6641,
            "mean_log_loss":    0.6053,
            "mean_auc":         0.7292,
            "elo_mean_acc":     0.6381,
            "mean_edge_vs_elo": 0.026,
        },
        "year_by_year": [
            {"year": 2015, "n": 9841,  "best_acc": 0.6917, "best_auc": 0.7643, "elo_acc": 0.6723, "edge_acc": 0.0194},
            {"year": 2016, "n": 12771, "best_acc": 0.6840, "best_auc": 0.7585, "elo_acc": 0.6361, "edge_acc": 0.0479},
            {"year": 2017, "n": 12033, "best_acc": 0.6776, "best_auc": 0.7449, "elo_acc": 0.6461, "edge_acc": 0.0315},
            {"year": 2018, "n": 13060, "best_acc": 0.6619, "best_auc": 0.7274, "elo_acc": 0.6371, "edge_acc": 0.0248},
            {"year": 2019, "n": 11454, "best_acc": 0.6472, "best_auc": 0.7085, "elo_acc": 0.6306, "edge_acc": 0.0166},
            {"year": 2020, "n": 4746,  "best_acc": 0.6475, "best_auc": 0.7083, "elo_acc": 0.6214, "edge_acc": 0.0261},
            {"year": 2021, "n": 10177, "best_acc": 0.6585, "best_auc": 0.7185, "elo_acc": 0.6330, "edge_acc": 0.0255},
            {"year": 2022, "n": 12860, "best_acc": 0.6635, "best_auc": 0.7227, "elo_acc": 0.6431, "edge_acc": 0.0204},
            {"year": 2023, "n": 13898, "best_acc": 0.6560, "best_auc": 0.7180, "elo_acc": 0.6330, "edge_acc": 0.0230},
            {"year": 2024, "n": 13880, "best_acc": 0.6532, "best_auc": 0.7212, "elo_acc": 0.6286, "edge_acc": 0.0246},
        ],
        "calibration_band_85": {
            "predicted_prob": 0.85,
            "actual_win_rate": 0.798,
            "n": 712,
            "note": "When the model says 85% sure, the favourite actually wins ~80% of the time. This is the headroom for hitting 75%+ on high-confidence picks.",
        },
        "note": "Trained ensemble. The live RTT predictor (rtt-v2) is a lightweight logit using a subset of these features; live accuracy is reported separately at /api/v1/predictions/accuracy.",
    }


@app.get("/admin/hand-splits")
def admin_hand_splits():
    """Compute player_hand_splits."""
    from api.bootstrap import run_hand_splits
    return _safe_admin(run_hand_splits)


@app.get("/admin/settle")
def admin_settle():
    """Settle finished predictions."""
    from api.bootstrap import run_settle
    return _safe_admin(run_settle)


@app.get("/admin/systems")
def admin_systems(days_ahead: int = 7):
    """Run systems engine."""
    from api.bootstrap import run_systems
    return _safe_admin(run_systems, days_ahead=days_ahead)


# ─────────────────────────────────────────────────────────────────────────────
# Auto-bootstrap on startup
# Runs in a background thread so uvicorn boot isn't blocked. Idempotent.
# ─────────────────────────────────────────────────────────────────────────────

def _startup_bootstrap():
    try:
        from api.bootstrap import full_bootstrap
        log.info("[startup] running full bootstrap in background…")
        result = full_bootstrap()
        log.info(f"[startup] bootstrap complete: {result}")
    except Exception as e:
        log.error(f"[startup] bootstrap failed: {e}")


@app.on_event("startup")
def _kick_off_bootstrap():
    if os.environ.get("RTT_DISABLE_AUTO_BOOTSTRAP", "").lower() in ("1", "true", "yes"):
        log.info("[startup] auto-bootstrap disabled via RTT_DISABLE_AUTO_BOOTSTRAP")
        return
    threading.Thread(target=_startup_bootstrap, daemon=True).start()
