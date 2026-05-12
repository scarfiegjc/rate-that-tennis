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
from api.routes.odds import router as odds_router
from api.routes.auth import router as auth_router
from api.routes.picks import router as picks_router
from api.routes.stats import router as stats_router

# Optional routes — these files exist in dev but may not be in this image yet.
# Wrap each so a missing module doesn't crash the whole API on startup.
try:
    from api.routes.lab import router as lab_router
except ImportError:
    lab_router = None
try:
    from api.routes.health import router as health_router
except ImportError:
    health_router = None
try:
    from api.routes.diagnose import router as diagnose_router
except ImportError:
    diagnose_router = None
try:
    from api.routes.tournaments import router as tournaments_router
except ImportError:
    tournaments_router = None

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
    allow_credentials=True,
    allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
    allow_headers=["*"],
)

# ─────────────────────────────────────────────────────────────────────────────
# Routers
# ─────────────────────────────────────────────────────────────────────────────

app.include_router(matches_router, prefix="/api/v1")
app.include_router(players_router, prefix="/api/v1")
app.include_router(predictions_router, prefix="/api/v1")
app.include_router(odds_router, prefix="/api/v1")
app.include_router(auth_router, prefix="/api/v1")
app.include_router(picks_router, prefix="/api/v1")
app.include_router(stats_router, prefix="/api/v1")
if lab_router:         app.include_router(lab_router,         prefix="/api/v1")
if health_router:      app.include_router(health_router,      prefix="/api/v1")
if diagnose_router:    app.include_router(diagnose_router,    prefix="/api/v1")
if tournaments_router: app.include_router(tournaments_router, prefix="/api/v1")


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


# NOTE: An /admin/run-intel endpoint and a Step 5b in _daily_worker were
# briefly wired up here. Removed — intel/deep-reasoning prose is generated
# manually via Cowork sessions (analogous to the ratethat.dog and
# ratethat.horse "deep-reasoning" skills), not by an automated cron
# calling the Anthropic API. The /admin/intel/queue + /admin/intel/store
# endpoints in api/routes/predictions.py are kept — those are the
# read/write hooks the Cowork session uses.


@app.get("/admin/fix-stuck-live")
def admin_fix_stuck_live(dry_run: bool = True):
    """
    Some matches stay flagged is_live=TRUE in the matches table after the
    pipeline has already written event_status='Finished' + winner. This
    confuses the frontend, which shows a pulsing IN PLAY indicator on a
    match that's already over. One-shot: clear is_live for any Finished
    match. Going forward the API also defends in the serialization layer.
    """
    from api.db import query, get_conn
    stuck = query(
        """
        SELECT id, event_date, event_status, winner
        FROM matches
        WHERE is_live = TRUE
          AND event_status IN ('Finished','Retired','Walk Over','Walkover')
        ORDER BY event_date DESC
        LIMIT 1000
        """
    )
    if dry_run:
        return {"dry_run": True, "stuck_count": len(stuck), "sample": stuck[:10]}

    if not stuck:
        return {"dry_run": False, "cleared": 0}

    ids = [r["id"] for r in stuck]
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("UPDATE matches SET is_live = FALSE WHERE id = ANY(%s)", (ids,))
    return {"dry_run": False, "cleared": len(ids)}


@app.get("/admin/fix-stale-intel")
def admin_fix_stale_intel(dry_run: bool = True):
    """
    One-shot repair: clear stored intel on any match where the intel was
    generated BEFORE the most recent predicted_at (i.e. probabilities
    changed after the prose was written). Going forward, predictor
    upserts auto-invalidate, but this catches the historical backlog.
    """
    from api.db import query, get_conn
    candidates = query(
        """
        SELECT match_id, intel_generated_at, predicted_at,
               LENGTH(COALESCE(match_preview, '')) AS preview_len,
               predicted_winner
        FROM model_predictions
        WHERE intel_generated_at IS NOT NULL
          AND predicted_at IS NOT NULL
          AND intel_generated_at < predicted_at
          AND (match_preview IS NOT NULL OR p1_intel IS NOT NULL OR p2_intel IS NOT NULL)
        ORDER BY predicted_at DESC
        LIMIT 500
        """,
    )
    if dry_run or not candidates:
        return {"dry_run": dry_run, "stale_count": len(candidates),
                "sample": candidates[:10]}

    updated = 0
    for c in candidates:
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE model_predictions
                    SET p1_intel           = NULL,
                        p2_intel           = NULL,
                        match_preview      = NULL,
                        did_you_know       = NULL,
                        confidence_line    = NULL,
                        intel_generated_at = NULL
                    WHERE match_id = %s
                    """,
                    (c["match_id"],),
                )
        updated += 1
    return {"dry_run": False, "cleared": updated, "candidates": len(candidates)}


@app.get("/admin/fix-stale-picks")
def admin_fix_stale_picks(dry_run: bool = True):
    """
    One-shot repair: recompute predicted_winner + is_correct on every
    model_predictions row where the stored predicted_winner doesn't match
    the higher-probability side. These rows came from a predictor-version
    swap that updated probabilities without touching predicted_winner.
    """
    from api.db import query, get_conn
    candidates = query(
        """
        SELECT match_id, prob_first_player, prob_second_player,
               predicted_winner, actual_winner, is_correct
        FROM model_predictions
        WHERE prob_first_player IS NOT NULL
          AND prob_second_player IS NOT NULL
          AND predicted_winner IS NOT NULL
          AND (
                (predicted_winner = 'first_player'  AND prob_first_player  < prob_second_player)
             OR (predicted_winner = 'second_player' AND prob_second_player < prob_first_player)
          )
        """,
    )
    if dry_run or not candidates:
        return {"dry_run": dry_run, "stale_count": len(candidates),
                "sample": candidates[:10]}

    updated = 0
    for c in candidates:
        p1 = float(c["prob_first_player"]); p2 = float(c["prob_second_player"])
        correct_pick = "first_player" if p1 >= p2 else "second_player"
        new_is_correct = None
        if c.get("actual_winner") is not None:
            new_is_correct = (correct_pick == c["actual_winner"])
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE model_predictions
                    SET predicted_winner = %s,
                        is_correct       = COALESCE(%s, is_correct)
                    WHERE match_id = %s
                    """,
                    (correct_pick, new_is_correct, c["match_id"]),
                )
        updated += 1
    return {"dry_run": False, "fixed": updated, "candidates": len(candidates)}


@app.get("/admin/debug-prediction/{match_id}")
def admin_debug_prediction(match_id: int):
    """Show the full model_predictions + matches row for one match — used to
    diagnose data inconsistencies between endpoints."""
    from api.db import query_one
    mp = query_one(
        """
        SELECT match_id, prob_first_player, prob_second_player, confidence,
               predicted_winner, actual_winner, is_correct, settled_at,
               predicted_at, predictor_version, model_version
        FROM model_predictions
        WHERE match_id = %s
        """,
        (match_id,),
    )
    m = query_one(
        """
        SELECT id, event_date, event_status, winner, first_player_id, second_player_id,
               final_result
        FROM matches WHERE id = %s
        """,
        (match_id,),
    )
    return {"match": m, "prediction": mp}


@app.get("/admin/surface-audit")
def admin_surface_audit():
    """How many tournaments are still on Unknown, broken out by recency
    of their last match. Helps decide whether to extend the backfill map."""
    from api.db import query
    summary = query("""
        SELECT s.name AS surface_label,
               COUNT(*) AS tournament_count,
               COUNT(*) FILTER (WHERE EXISTS (
                   SELECT 1 FROM matches m
                   WHERE m.tournament_id = t.id
                     AND m.event_date >= CURRENT_DATE - INTERVAL '60 days'
               )) AS recent_active,
               COUNT(*) FILTER (WHERE EXISTS (
                   SELECT 1 FROM matches m
                   WHERE m.tournament_id = t.id
                     AND m.event_date >= CURRENT_DATE
               )) AS upcoming
        FROM tournaments t
        LEFT JOIN surfaces s ON s.id = t.surface_id
        GROUP BY s.name
        ORDER BY tournament_count DESC
    """)
    # Sample of Unknown tournaments with their recent activity
    sample = query("""
        SELECT t.id, t.name, t.city, t.country,
               (SELECT MAX(event_date) FROM matches m WHERE m.tournament_id = t.id) AS last_match,
               (SELECT COUNT(*) FROM matches m WHERE m.tournament_id = t.id) AS match_count
        FROM tournaments t
        LEFT JOIN surfaces s ON s.id = t.surface_id
        WHERE s.name = 'Unknown' OR s.name IS NULL
        ORDER BY (SELECT MAX(event_date) FROM matches m WHERE m.tournament_id = t.id) DESC NULLS LAST
        LIMIT 80
    """)
    return {"summary": summary, "unknown_sample": sample}


@app.get("/admin/picks-resolve-stuck")
def admin_picks_resolve_stuck(min_age_days: int = 1, dry_run: bool = True):
    """
    Resolve user_picks that are stuck in pending/live past their match date.

    Strategy:
      1. For each stale pick, look for a finished match between the same two
         players on the same event_date. Some matches get duplicated under
         a different match_id when a player has multiple ID variants — the
         "real" match with the result lives under the duplicate.
      2. If a finished twin is found: settle the pick against it.
      3. If no twin and the match is more than `min_age_days` past its date
         with no result: mark the pick as 'void' (no settlement will ever
         arrive — most likely a walkover/cancellation that wasn't recorded
         on our side).

    Default is dry-run — pass `?dry_run=false` to actually update.
    """
    from api.db import query, query_one, get_conn

    stale = query(
        """
        SELECT up.id  AS pick_id,
               up.user_id,
               up.match_id,
               up.player_id,
               up.confidence_stars,
               up.our_odds,
               up.status,
               m.event_date,
               m.event_status,
               m.winner,
               m.first_player_id,
               m.second_player_id,
               p1.name AS p1_name,
               p2.name AS p2_name,
               pp.name AS picked_name
        FROM user_picks up
        JOIN matches m  ON m.id = up.match_id
        LEFT JOIN players p1 ON p1.id = m.first_player_id
        LEFT JOIN players p2 ON p2.id = m.second_player_id
        LEFT JOIN players pp ON pp.id = up.player_id
        WHERE up.status IN ('pending','live')
          AND m.event_date < CURRENT_DATE - (%s || ' days')::interval
        ORDER BY m.event_date ASC
        LIMIT 200
        """,
        (min_age_days,),
    )

    actions = []

    for sp in stale:
        # Try to find a "twin" finished match for the same date + same surnames.
        # We match on the last word of the player name only (surname) so that
        # duplicate-player ghosts like "T. Etcheverry" vs "T. M. Etcheverry"
        # still resolve to the same physical match.
        def _surname(s):
            return (s or "").strip().split()[-1] if s else ""
        twin = None
        s1 = _surname(sp["p1_name"])
        s2 = _surname(sp["p2_name"])
        if s1 and s2:
            twin = query_one(
                """
                SELECT m.id AS match_id, m.winner,
                       m.first_player_id, m.second_player_id,
                       m.event_status, m.final_result,
                       p1.name AS p1_name, p2.name AS p2_name
                FROM matches m
                JOIN players p1 ON p1.id = m.first_player_id
                JOIN players p2 ON p2.id = m.second_player_id
                WHERE m.event_date = %s
                  AND m.id != %s
                  AND m.winner IN ('First Player','Second Player')
                  AND m.event_status ILIKE 'Finished'
                  AND (
                        (p1.name ILIKE %s AND p2.name ILIKE %s)
                     OR (p1.name ILIKE %s AND p2.name ILIKE %s)
                      )
                LIMIT 1
                """,
                (sp["event_date"], sp["match_id"],
                 f"%{s1}%", f"%{s2}%",
                 f"%{s2}%", f"%{s1}%"),
            )

        if twin:
            # Map the picked player_name to the twin's first/second slot.
            # Use surname matching (same fuzz reason as above).
            picked_surname = _surname(sp["picked_name"])
            picked_is_p1 = (
                picked_surname.lower() in (twin["p1_name"] or "").lower()
                and picked_surname.lower() not in (twin["p2_name"] or "").lower()
            )
            winner_is_p1 = twin["winner"] == "First Player"
            won = (picked_is_p1 == winner_is_p1)
            new_status = "won" if won else "lost"
            stake = float(sp.get("confidence_stars") or 1)
            if won:
                odds = float(sp.get("our_odds") or 2.0)
                pl = round((odds - 1) * stake, 2)
            else:
                pl = round(-stake, 2)

            actions.append({
                "pick_id":      sp["pick_id"],
                "action":       "settle_via_twin",
                "twin_match":   twin["match_id"],
                "twin_score":   twin["final_result"],
                "new_status":   new_status,
                "profit_loss":  pl,
            })
            if not dry_run:
                with get_conn() as conn:
                    with conn.cursor() as cur:
                        cur.execute(
                            """UPDATE user_picks
                               SET status = %s, settled_at = NOW(), profit_loss = %s
                               WHERE id = %s AND status IN ('pending','live')""",
                            (new_status, pl, sp["pick_id"]),
                        )
        else:
            # No twin — void it (no result is going to arrive)
            actions.append({
                "pick_id":     sp["pick_id"],
                "action":      "void",
                "reason":      "no twin match found and event_date is past",
                "match_status": sp["event_status"],
            })
            if not dry_run:
                with get_conn() as conn:
                    with conn.cursor() as cur:
                        cur.execute(
                            """UPDATE user_picks
                               SET status = 'void', settled_at = NOW(), profit_loss = 0
                               WHERE id = %s AND status IN ('pending','live')""",
                            (sp["pick_id"],),
                        )

    return {
        "dry_run":   dry_run,
        "stale_count": len(stale),
        "actions":   actions,
    }


@app.get("/admin/picks-diagnose")
def admin_picks_diagnose():
    """
    Diagnose stuck user_picks: list any pick still in pending/live whose
    underlying match has finished or is past event_date. Helps identify
    whether the settle pipeline is failing to catch certain match states
    (e.g. event_status case variants, walkovers, retirements, missing winners).
    """
    from api.db import query

    # Picks past their match date that are still pending/live
    stale = query(
        """
        SELECT up.id AS pick_id,
               up.user_id,
               up.match_id,
               up.status                     AS pick_status,
               up.player_id,
               up.confidence_stars,
               up.created_at,
               m.event_date,
               m.event_time,
               m.event_status                AS match_status,
               m.winner                      AS match_winner,
               m.first_player_id, m.second_player_id,
               m.final_result                AS match_score,
               p1.name AS p1_name, p2.name AS p2_name,
               pp.name AS picked_name
        FROM user_picks up
        JOIN matches m  ON m.id = up.match_id
        LEFT JOIN players p1 ON p1.id = m.first_player_id
        LEFT JOIN players p2 ON p2.id = m.second_player_id
        LEFT JOIN players pp ON pp.id = up.player_id
        WHERE up.status IN ('pending','live')
          AND m.event_date < CURRENT_DATE
        ORDER BY m.event_date ASC, up.created_at ASC
        LIMIT 50
        """,
    )

    # Status-value distribution for finished-but-unsettled context
    statuses = query(
        """
        SELECT m.event_status, m.winner, COUNT(*) AS n
        FROM user_picks up
        JOIN matches m ON m.id = up.match_id
        WHERE up.status IN ('pending','live')
          AND m.event_date <= CURRENT_DATE
        GROUP BY m.event_status, m.winner
        ORDER BY n DESC
        """,
    )

    return {
        "stale_picks":         stale,
        "stuck_status_breakdown": statuses,
        "settle_filter_used":  "m.event_status = 'Finished' AND m.winner IN ('First Player','Second Player')",
    }


@app.get("/admin/db-kill-stuck")
def admin_db_kill_stuck(min_seconds: int = 60, dry_run: bool = True):
    """
    Terminate any backend that has been running a query for longer than
    `min_seconds` (default 60). Use when an ALTER TABLE has queued for
    ACCESS EXCLUSIVE and is blocking every subsequent read.

    Default is dry-run — pass `?dry_run=false` to actually terminate.
    Returns the list of pids it killed (or would kill) plus the queries
    so you can sanity-check before retrying.
    """
    from api.db import get_conn

    candidates = []
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(f"SET LOCAL statement_timeout = 3000")
            cur.execute("""
                SELECT pid,
                       application_name,
                       state,
                       EXTRACT(EPOCH FROM (clock_timestamp() - query_start))::int AS runtime_sec,
                       LEFT(query, 240) AS query
                FROM pg_stat_activity
                WHERE datname = current_database()
                  AND pid <> pg_backend_pid()
                  AND query_start IS NOT NULL
                  AND state IN ('active','idle in transaction')
                  AND EXTRACT(EPOCH FROM (clock_timestamp() - query_start)) > %s
                  AND query NOT LIKE '%%pg_stat_activity%%'
                ORDER BY query_start ASC
            """, (min_seconds,))
            for r in cur.fetchall():
                candidates.append(dict(r))

    if dry_run or not candidates:
        return {
            "dry_run": dry_run,
            "min_seconds": min_seconds,
            "would_kill": candidates,
            "note": "Pass ?dry_run=false to actually terminate." if dry_run else "Nothing matched.",
        }

    killed = []
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SET LOCAL statement_timeout = 5000")
            for c in candidates:
                try:
                    cur.execute("SELECT pg_terminate_backend(%s) AS ok", (c["pid"],))
                    row = cur.fetchone()
                    killed.append({**c, "terminated": bool(row.get("ok"))})
                except Exception as e:
                    killed.append({**c, "terminated": False, "error": str(e)[:200]})
    return {"dry_run": False, "killed": killed, "count": len(killed)}


@app.get("/admin/db-stats")
def admin_db_stats():
    """
    Quick DB-side diagnostic: table sizes, row counts, vacuum/analyze status,
    long-running queries, and lock status. Run this when endpoints time out
    to identify the bottleneck without needing direct DB access.
    Each query has its own short statement_timeout so the endpoint itself
    can't hang.
    """
    from api.db import query, query_one

    def _safe(sql, params=None, ms=3000):
        try:
            with __import__("api.db", fromlist=["get_conn"]).get_conn() as conn:
                with conn.cursor() as cur:
                    cur.execute(f"SET LOCAL statement_timeout = {ms}")
                    cur.execute(sql, params or ())
                    rows = cur.fetchall()
                    return [dict(r) for r in rows]
        except Exception as e:
            return {"error": f"{type(e).__name__}: {str(e)[:200]}"}

    out = {}

    # Table sizes for the suspects
    out["table_sizes"] = _safe("""
        SELECT relname AS table,
               pg_size_pretty(pg_total_relation_size(c.oid)) AS total_size,
               pg_size_pretty(pg_relation_size(c.oid))       AS heap_size,
               n_live_tup AS live_rows,
               n_dead_tup AS dead_rows,
               last_autovacuum, last_autoanalyze, last_vacuum, last_analyze
        FROM pg_stat_user_tables s
        JOIN pg_class c ON c.relname = s.relname
        WHERE s.relname IN ('model_predictions','matches','match_points',
                            'match_games','match_scores','sa_matches',
                            'player_ratings_history','bookmaker_odds')
        ORDER BY pg_total_relation_size(c.oid) DESC
    """, ms=4000)

    # In-flight queries longer than 5s
    out["long_running"] = _safe("""
        SELECT pid, age(clock_timestamp(), query_start) AS runtime,
               state, application_name, LEFT(query, 200) AS query
        FROM pg_stat_activity
        WHERE state != 'idle'
          AND query_start IS NOT NULL
          AND age(clock_timestamp(), query_start) > interval '5 seconds'
          AND query NOT LIKE '%pg_stat_activity%'
        ORDER BY query_start
        LIMIT 20
    """, ms=2000)

    # Locks held that are blocking other queries
    out["blocking_locks"] = _safe("""
        SELECT blocked.pid AS blocked_pid,
               LEFT(blocked.query, 100) AS blocked_query,
               blocking.pid AS blocking_pid,
               LEFT(blocking.query, 100) AS blocking_query,
               age(clock_timestamp(), blocked.query_start) AS blocked_for
        FROM pg_stat_activity blocked
        JOIN pg_locks bl ON bl.pid = blocked.pid AND NOT bl.granted
        JOIN pg_locks bg ON bg.locktype = bl.locktype
                        AND bg.database IS NOT DISTINCT FROM bl.database
                        AND bg.relation IS NOT DISTINCT FROM bl.relation
                        AND bg.page     IS NOT DISTINCT FROM bl.page
                        AND bg.tuple    IS NOT DISTINCT FROM bl.tuple
                        AND bg.granted
                        AND bg.pid <> bl.pid
        JOIN pg_stat_activity blocking ON blocking.pid = bg.pid
        LIMIT 10
    """, ms=2000)

    # Connection counts by application
    out["connections"] = _safe("""
        SELECT application_name, state, COUNT(*) AS n
        FROM pg_stat_activity
        WHERE datname = current_database()
        GROUP BY application_name, state
        ORDER BY n DESC
    """, ms=2000)

    # Try the slow query plan: predictions/stats
    out["plan_predictions_stats"] = _safe("""
        EXPLAIN (FORMAT JSON, ANALYZE FALSE, BUFFERS FALSE)
        SELECT COUNT(*) FILTER (WHERE settled_at IS NOT NULL) AS settled,
               COUNT(*) FILTER (WHERE is_correct)             AS correct
        FROM model_predictions
    """, ms=2000)

    return out


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


@app.get("/admin/deactivate-legacy-systems")
def admin_deactivate_legacy_systems():
    """Directly deactivate the v1 legacy systems that have negative ROI."""
    from contextlib import contextmanager
    import psycopg2, os
    legacy = [
        "surface_monster", "form_surge", "hand_advantage", "big_match_player",
        "underdog_value", "rtt_mismatch", "clutch_in_decider",
    ]
    try:
        db_url = (os.environ.get("DATABASE_URL") or os.environ.get("DATABASE_PUBLIC_URL") or "").strip()
        conn = psycopg2.connect(db_url)
        conn.autocommit = False
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE systems SET is_active = FALSE WHERE code = ANY(%s) RETURNING code",
                (legacy,),
            )
            deactivated = [r[0] for r in cur.fetchall()]
        conn.commit()
        conn.close()
        return {"deactivated": deactivated, "count": len(deactivated)}
    except Exception as e:
        return {"error": str(e)}


_PREDICT_STATUS: dict = {
    "running": False, "started_at": None, "finished_at": None,
    "days_ahead": None, "result": None, "error": None,
}


def _predict_worker(days_ahead: int):
    import time
    _PREDICT_STATUS.update({
        "running": True, "started_at": time.time(), "finished_at": None,
        "days_ahead": days_ahead, "result": None, "error": None,
    })
    try:
        from api.bootstrap import run_rtt_predictions
        result = run_rtt_predictions(days_ahead=days_ahead)
        _PREDICT_STATUS.update({"running": False, "finished_at": time.time(), "result": result})
    except Exception as e:
        import traceback
        _PREDICT_STATUS.update({"running": False, "finished_at": time.time(), "error": str(e)})
        log.error(f"predict worker failed: {e}\n{traceback.format_exc()}")


@app.get("/admin/predict")
def admin_predict(days_ahead: int = 7, bg: bool = True):
    """Run RTT predictor for upcoming matches.
    bg=true (default): fires in a background thread and returns immediately.
    bg=false: runs synchronously (will timeout for large date ranges).
    """
    if bg:
        if _PREDICT_STATUS.get("running"):
            return {"status": "already_running", "started_at": _PREDICT_STATUS.get("started_at")}
        import threading
        t = threading.Thread(target=_predict_worker, args=(days_ahead,), daemon=True)
        t.start()
        return {"status": "started", "days_ahead": days_ahead,
                "check": "/admin/predict-status"}
    from api.bootstrap import run_rtt_predictions
    return _safe_admin(run_rtt_predictions, days_ahead=days_ahead)


@app.get("/admin/predict-status")
def admin_predict_status():
    """Check the status of the background prediction run."""
    import time
    s = dict(_PREDICT_STATUS)
    if s.get("started_at"):
        elapsed = (s.get("finished_at") or time.time()) - s["started_at"]
        s["elapsed_seconds"] = round(elapsed, 1)
    return s

_MS_BACKFILL_STATUS = {
    "running": False, "started_at": None, "finished_at": None,
    "tour": None, "params": None,
    "progress": None,         # {"current": i, "total": n, "resolved": k, "matches": m}
    "result": None, "error": None,
}


def _matchstat_backfill_worker(tour: str, limit: int, max_match_pages: int,
                                page_size: int, skip_already_linked: bool):
    import os, time, traceback, psycopg2
    _MS_BACKFILL_STATUS.update({
        "running": True, "started_at": time.time(), "finished_at": None,
        "tour": tour,
        "params": {"limit": limit, "max_match_pages": max_match_pages,
                    "page_size": page_size,
                    "skip_already_linked": skip_already_linked},
        "progress": None, "result": None, "error": None,
    })
    try:
        from matchstat_ingest import backfill_active
        conn = psycopg2.connect(os.environ.get("DATABASE_URL", ""))
        try:
            res = backfill_active(
                conn, tour=tour,
                limit=(limit or None),
                max_match_pages=max_match_pages,
                page_size=page_size,
                skip_already_linked=skip_already_linked,
            )
            # Strip the per-player details list to keep the status payload small.
            res_summary = {k: v for k, v in res.items() if k != "details"}
            res_summary["details_count"] = len(res.get("details") or [])
            _MS_BACKFILL_STATUS["result"] = res_summary
        finally:
            conn.close()
    except Exception as e:
        _MS_BACKFILL_STATUS["error"] = f"{type(e).__name__}: {e}"
        log.error(f"matchstat backfill worker failed: {e}")
        log.error(traceback.format_exc())
    finally:
        _MS_BACKFILL_STATUS["finished_at"] = time.time()
        _MS_BACKFILL_STATUS["running"] = False


@app.get("/admin/matchstat-backfill")
def admin_matchstat_backfill(tour: str = "atp", limit: int = 0,
                              max_match_pages: int = 3,
                              page_size: int = 50,
                              skip_already_linked: bool = True,
                              sync: bool = False):
    """
    Run the Matchstat ingestion backfill across active rated players.

    `limit=0` means no limit (whole pool). `skip_already_linked=true` skips
    players we've already ingested.

    Default mode is ASYNC (fire-and-forget) — returns immediately, poll
    /admin/matchstat-backfill/status for progress. Pass `sync=true` to run
    synchronously (only safe for small `limit` values — Railway will time
    out long requests).
    """
    if sync:
        # Legacy synchronous path for small probe runs.
        def _run():
            import os, psycopg2
            from matchstat_ingest import backfill_active
            conn = psycopg2.connect(os.environ.get("DATABASE_URL", ""))
            try:
                return backfill_active(
                    conn, tour=tour, limit=(limit or None),
                    max_match_pages=max_match_pages, page_size=page_size,
                    skip_already_linked=skip_already_linked,
                )
            finally:
                conn.close()
        return _safe_admin(_run)

    if _MS_BACKFILL_STATUS.get("running"):
        return {"status": "already_running",
                "started_at": _MS_BACKFILL_STATUS["started_at"],
                "tour": _MS_BACKFILL_STATUS.get("tour"),
                "poll": "/admin/matchstat-backfill/status"}

    threading.Thread(
        target=_matchstat_backfill_worker,
        args=(tour, limit, max_match_pages, page_size, skip_already_linked),
        daemon=True,
    ).start()
    return {
        "status": "started",
        "poll":   "/admin/matchstat-backfill/status",
        "tour":   tour,
        "note":   "Backfill runs in background. Whole pool ≈ 30-90 minutes; "
                  "poll the status URL.",
    }


@app.get("/admin/matchstat-backfill/status")
def admin_matchstat_backfill_status():
    return _MS_BACKFILL_STATUS


@app.get("/admin/merge-player-pair")
def admin_merge_player_pair(from_id: int, to_id: int, dry_run: bool = True):
    """
    Manually merge one player record into another. Use for cases the auto
    merge-duplicate-players doesn't catch — typically when the two records
    have different full_names (e.g. short form 'J. Sinner' vs long form
    'Jannik Sinner') so the normaliser refuses to cluster them.

    Moves every foreign-key reference from `from_id` to `to_id` and deletes
    the from_id row. Pass dry_run=true to see what would happen first.
    """
    def _run():
        import os, psycopg2
        from merge_duplicate_players import _merge_pair
        from api.db import get_conn, query_one

        # Sanity check: confirm both exist
        from_row = query_one("SELECT id, name, full_name, country_code FROM players WHERE id = %s", (from_id,))
        to_row   = query_one("SELECT id, name, full_name, country_code FROM players WHERE id = %s", (to_id,))
        if not from_row or not to_row:
            return {"error": "one of the IDs doesn't exist", "from": from_row, "to": to_row}

        if dry_run:
            # Count references that would move
            ref_count = query_one(
                """
                SELECT
                    (SELECT COUNT(*) FROM matches WHERE first_player_id = %s OR second_player_id = %s) AS match_refs,
                    (SELECT COUNT(*) FROM player_ratings WHERE player_id = %s) AS rating_refs,
                    (SELECT COUNT(*) FROM model_predictions mp JOIN matches m ON m.id = mp.match_id
                     WHERE m.first_player_id = %s OR m.second_player_id = %s) AS pred_refs
                """,
                (from_id, from_id, from_id, from_id, from_id),
            )
            return {
                "dry_run": True,
                "from": from_row,
                "to":   to_row,
                "would_move": ref_count,
                "next_step": "Re-call with ?dry_run=false to execute the merge.",
            }

        with get_conn() as conn:
            with conn.cursor() as cur:
                result = _merge_pair(cur, canonical_id=to_id, shadow_id=from_id)
        return {"dry_run": False, "from": from_row, "to": to_row, "merge_result": result}

    return _safe_admin(_run)


@app.get("/admin/merge-duplicate-players")
def admin_merge_duplicate_players(dry_run: bool = True, limit: int = 0):
    """
    Find and merge duplicate `players` rows that share the same physical
    identity but ended up with different IDs (typically because api-tennis.com
    handed us different api_key values for diacritic spelling variants).

    `dry_run=true` (default) → returns the merge plan without writing anything.
    `dry_run=false`          → executes the merges and deletes shadow rows.
    `limit=N`                → process only the top N most-impactful groups.
    """
    def _run():
        import os, psycopg2
        from merge_duplicate_players import merge_all
        conn = psycopg2.connect(os.environ.get("DATABASE_URL", ""))
        try:
            return merge_all(conn, dry_run=dry_run, limit=limit)
        finally:
            conn.close()
    return _safe_admin(_run)


@app.get("/admin/matchstat-aggregate")
def admin_matchstat_aggregate():
    """Recompute ms_player_career_stats from ms_match_stats."""
    def _run():
        import os, psycopg2
        from matchstat_ingest import compute_career_stats
        conn = psycopg2.connect(os.environ.get("DATABASE_URL", ""))
        try:
            return compute_career_stats(conn)
        finally:
            conn.close()
    return _safe_admin(_run)


@app.get("/admin/matchstat-spike")
def admin_matchstat_spike(n: int = 10, tour: str = "atp", names: str = ""):
    """
    Diagnostic: probe the Matchstat API on N active players, report on
    name-resolution success, per-match stat coverage, and field population.
    Writes nothing to the database — purely a data-quality check before
    any backfill commitment.

    Pass ?names=Aryna Sabalenka,Iga Swiatek to override the auto-picked
    sample with literal player names (useful for cross-tour probing).
    """
    from api.routes._matchstat_spike import run_spike
    return _safe_admin(run_spike, n_players=n, tour=tour, names=names)



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
    """Settle finished predictions AND user picks."""
    from api.bootstrap import run_settle
    return _safe_admin(run_settle)


@app.get("/admin/settle-picks")
def admin_settle_picks():
    """
    Force-settle all stuck user_picks whose match has finished.
    Run this to immediately fix picks that are showing as pending/live
    after their match has completed.
    """
    def _run():
        from api.db import query, get_conn
        rows = query(
            """
            SELECT up.id, up.player_id, up.confidence_stars, up.our_odds, up.status,
                   m.first_player_id, m.second_player_id, m.winner
            FROM user_picks up
            JOIN matches m ON m.id = up.match_id
            WHERE up.status IN ('pending','live')
              AND m.event_status IN ('Finished','Retired','Walk Over','Walkover')
              AND m.winner IN ('First Player','Second Player')
            """
        )
        settled = 0
        for r in rows:
            winner_pid = r["first_player_id"] if r["winner"] == "First Player" else r["second_player_id"]
            status = "won" if r["player_id"] == winner_pid else "lost"
            stake  = float(r["confidence_stars"] or 1)
            pl     = round((float(r["our_odds"] or 2.0) - 1) * stake, 2) if status == "won" else round(-stake, 2)
            with get_conn() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        "UPDATE user_picks SET status=%s, settled_at=NOW(), profit_loss=%s WHERE id=%s AND status IN ('pending','live')",
                        (status, pl, r["id"]),
                    )
            settled += 1
        return {"settled_user_picks": settled}
    return _safe_admin(_run)


@app.get("/admin/run-odds")
def admin_run_odds():
    """
    Fetch latest bookmaker odds from The Odds API and write to bookmaker_odds.
    Skips silently if ODDS_API_KEY is not set on the environment.
    Same job the scheduler runs at 20:00 + 05:00 UTC — useful for an instant
    refresh after applying schema changes or resetting the cache.
    """
    def _run():
        if not os.environ.get("ODDS_API_KEY"):
            return {"skipped": True, "reason": "ODDS_API_KEY not set on Railway env vars"}
        try:
            from pipeline.odds import run as odds_run
        except ImportError:
            from odds import run as odds_run  # flat-image fallback
        return odds_run()
    return _safe_admin(_run)


@app.get("/admin/odds-debug")
def admin_odds_debug():
    """
    Diagnose the odds pipeline: check API key, list available tennis sport keys,
    and show a sample of raw events returned for the active keys.
    """
    import requests as _requests
    key = os.environ.get("ODDS_API_KEY", "")
    if not key:
        return {"error": "ODDS_API_KEY is not set on this service's Railway env vars"}

    base = "https://api.the-odds-api.com/v4"

    # 1. List all available tennis sports
    try:
        r = _requests.get(f"{base}/sports", params={"apiKey": key}, timeout=10)
        all_sports = r.json() if r.status_code == 200 else {"http_error": r.status_code, "body": r.text[:200]}
        tennis_sports = [s for s in (all_sports if isinstance(all_sports, list) else []) if "tennis" in s.get("key","")]
    except Exception as e:
        return {"error": f"sports list failed: {e}"}

    # 2. Try fetching odds for the base keys and report counts
    results = {}
    for key_name in ["tennis_atp", "tennis_wta", "tennis_atp_french_open", "tennis_wta_french_open"]:
        try:
            r2 = _requests.get(f"{base}/sports/{key_name}/odds",
                               params={"apiKey": key, "regions": "uk,eu", "markets": "h2h",
                                       "oddsFormat": "decimal"},
                               timeout=10)
            if r2.status_code == 200:
                events = r2.json()
                results[key_name] = {"status": 200, "events": len(events),
                                     "sample": [e.get("home_team","?") + " v " + e.get("away_team","?") for e in events[:3]]}
            else:
                results[key_name] = {"status": r2.status_code, "body": r2.text[:200]}
        except Exception as e:
            results[key_name] = {"error": str(e)}

    return {"key_set": bool(key), "key_prefix": key[:6] + "…", "tennis_sport_keys": [s["key"] for s in tennis_sports], "odds_fetch": results}


@app.get("/admin/odds-matches")
def admin_odds_matches():
    """List all matches that currently have odds in the DB."""
    from api.db import query
    rows = query("""
        SELECT bo.match_id, p1.name AS p1, p2.name AS p2,
               COUNT(DISTINCT bo.bookmaker) AS bookmakers,
               MAX(bo.fetched_at) AS last_fetched
        FROM bookmaker_odds bo
        JOIN matches m ON m.id = bo.match_id
        JOIN players p1 ON p1.id = m.first_player_id
        JOIN players p2 ON p2.id = m.second_player_id
        GROUP BY bo.match_id, p1.name, p2.name
        ORDER BY last_fetched DESC
        LIMIT 30
    """)
    return {"count": len(rows), "matches": [dict(r) for r in rows]}


_BZZOIRO_BIOS_STATUS = {"running": False, "started_at": None, "finished_at": None,
                        "updated": None, "error": None}


def _bzzoiro_bios_worker():
    """Background worker — paginates ~10k bzzoiro players, can take 60-180s."""
    import os, traceback, time
    import psycopg2
    _BZZOIRO_BIOS_STATUS.update({"running": True, "started_at": time.time(),
                                  "finished_at": None, "updated": None, "error": None})
    try:
        try:
            from pipeline.bzzoiro_ingest import sync_player_bios
        except ImportError:
            from bzzoiro_ingest import sync_player_bios

        db_url = os.environ.get("DATABASE_URL") or os.environ.get("DATABASE_PUBLIC_URL")
        if not db_url:
            _BZZOIRO_BIOS_STATUS["error"] = "DATABASE_URL not set"
            return
        conn = psycopg2.connect(db_url)
        conn.autocommit = True
        try:
            n = sync_player_bios(conn)
            _BZZOIRO_BIOS_STATUS["updated"] = n
        finally:
            conn.close()
    except Exception as e:
        _BZZOIRO_BIOS_STATUS["error"] = f"{type(e).__name__}: {e}"
        log.error(f"bzzoiro bios worker failed: {e}")
        log.error(traceback.format_exc())
    finally:
        _BZZOIRO_BIOS_STATUS["finished_at"] = time.time()
        _BZZOIRO_BIOS_STATUS["running"] = False


@app.get("/admin/bzzoiro-bios")
def admin_bzzoiro_bios():
    """
    Trigger the bzzoiro bios backfill in a BACKGROUND thread (fire and forget).
    Returns immediately with a status URL — poll /admin/bzzoiro-bios/status.

    Iterates every bzzoiro player and fills DOB / country / hand / height on
    existing players rows where those fields are NULL. Most reliable way to
    populate Krejcikova-style ghosts.
    """
    if _BZZOIRO_BIOS_STATUS.get("running"):
        return {"status": "already_running", "started_at": _BZZOIRO_BIOS_STATUS["started_at"]}

    threading.Thread(target=_bzzoiro_bios_worker, daemon=True).start()
    return {
        "status": "started",
        "poll":   "/admin/bzzoiro-bios/status",
        "note":   "Job runs in background, takes 60-180s. Poll the status URL.",
    }


_BZZOIRO_MATCHES_STATUS = {"running": False, "started_at": None, "finished_at": None,
                           "result": None, "error": None}


def _bzzoiro_matches_worker(days_back: int):
    import os, traceback, time
    from datetime import date, timedelta
    import psycopg2
    _BZZOIRO_MATCHES_STATUS.update({"running": True, "started_at": time.time(),
                                     "finished_at": None, "result": None, "error": None})
    try:
        try:
            from pipeline.bzzoiro_ingest import sync_matches, get_db_conn
        except ImportError:
            from bzzoiro_ingest import sync_matches, get_db_conn

        date_from = (date.today() - timedelta(days=days_back)).isoformat()
        date_to   = (date.today() + timedelta(days=2)).isoformat()
        conn = get_db_conn()
        try:
            res = sync_matches(conn, date_from, date_to)
            _BZZOIRO_MATCHES_STATUS["result"] = res
        finally:
            conn.close()
    except SystemExit as e:
        _BZZOIRO_MATCHES_STATUS["error"] = f"SystemExit: {e.code}"
    except BaseException as e:
        _BZZOIRO_MATCHES_STATUS["error"] = f"{type(e).__name__}: {e}"
        log.error(f"bzzoiro matches worker failed: {e}")
        log.error(traceback.format_exc())
    finally:
        _BZZOIRO_MATCHES_STATUS["finished_at"] = time.time()
        _BZZOIRO_MATCHES_STATUS["running"] = False


@app.get("/admin/bzzoiro-live")
def admin_bzzoiro_live():
    """
    Refresh live bzzoiro matches RIGHT NOW. Synchronous (fast, ~5-10s) — pulls
    today's matches from bzzoiro and upserts their current status, set scores,
    and serve stats. Fixes the 'stuck on live all day' problem for matches
    bzzoiro marked live but never refreshed.

    Schedule this every 5 minutes during play hours via the pipeline service.
    """
    import os, traceback
    from datetime import date
    try:
        try:
            from pipeline.bzzoiro_ingest import sync_matches, get_db_conn
        except ImportError:
            from bzzoiro_ingest import sync_matches, get_db_conn
        d = date.today().isoformat()
        conn = get_db_conn()
        try:
            res = sync_matches(conn, d, d)
        finally:
            conn.close()
        return {"ok": True, "date": d, "result": res}
    except Exception as e:
        return {"error": str(e), "type": type(e).__name__,
                "traceback": traceback.format_exc().splitlines()[-10:]}


@app.get("/admin/bzzoiro-matches")
def admin_bzzoiro_matches(days_back: int = 7):
    """Fetch bzzoiro matches for the last `days_back` days + next 2 days.
    Background-threaded — returns immediately, poll /status."""
    if _BZZOIRO_MATCHES_STATUS.get("running"):
        return {"status": "already_running"}
    threading.Thread(target=_bzzoiro_matches_worker, args=(days_back,), daemon=True).start()
    return {"status": "started", "poll": "/admin/bzzoiro-matches/status",
            "days_back": days_back}


@app.get("/admin/bzzoiro-matches/status")
def admin_bzzoiro_matches_status():
    import time
    s = dict(_BZZOIRO_MATCHES_STATUS)
    if s.get("started_at"):
        s["elapsed_sec"] = round((s.get("finished_at") or time.time()) - s["started_at"], 1)
    return s


# ─── /admin/run-daily — chain everything in one fire-and-forget ────────────
_DAILY_STATUS = {"running": False, "phase": None, "started_at": None,
                 "finished_at": None, "log": [], "error": None}


def _daily_worker():
    import os, time, traceback
    import psycopg2

    def _log(msg):
        log.info(f"[daily] {msg}")
        _DAILY_STATUS["log"].append(msg)
        _DAILY_STATUS["log"] = _DAILY_STATUS["log"][-100:]

    _DAILY_STATUS.update({"running": True, "started_at": time.time(),
                           "finished_at": None, "log": [], "error": None})
    try:
        # 1. bzzoiro matches (last 7 + next 2 days)
        _DAILY_STATUS["phase"] = "bzzoiro_matches"
        _log("Step 1/6: bzzoiro matches sync (last 7d + next 2d)")
        try:
            try:
                from pipeline.bzzoiro_ingest import sync_matches, get_db_conn
            except ImportError:
                from bzzoiro_ingest import sync_matches, get_db_conn
            from datetime import date, timedelta
            date_from = (date.today() - timedelta(days=7)).isoformat()
            date_to   = (date.today() + timedelta(days=2)).isoformat()
            conn = get_db_conn()
            try:
                res = sync_matches(conn, date_from, date_to)
                _log(f"bzzoiro matches: {res}")
            finally:
                conn.close()
        except Exception as e:
            _log(f"bzzoiro matches FAILED: {e}")

        # 2. bzzoiro bios (DOB / country / full_name backfill)
        _DAILY_STATUS["phase"] = "bzzoiro_bios"
        _log("Step 2/6: bzzoiro bios fill")
        try:
            try:
                from pipeline.bzzoiro_ingest import sync_player_bios
            except ImportError:
                from bzzoiro_ingest import sync_player_bios
            db_url = os.environ.get("DATABASE_URL") or os.environ.get("DATABASE_PUBLIC_URL")
            conn = psycopg2.connect(db_url); conn.autocommit = True
            try:
                n = sync_player_bios(conn)
                _log(f"bzzoiro bios: updated {n} players")
            finally:
                conn.close()
        except Exception as e:
            _log(f"bzzoiro bios FAILED: {e}")

        # 3. Heal everything (3 enrichment passes)
        _DAILY_STATUS["phase"] = "heal_everything"
        _log("Step 3/6: heal-everything (heal-ghosts → enrich → fuzzy)")
        try:
            from api.routes.diagnose import heal_everything as _he
            r = _he()
            _log(f"heal-everything: {r}")
        except Exception as e:
            _log(f"heal-everything FAILED: {e}")

        # 4. Bootstrap (surface + ratings + hand splits + predictions + settle + systems)
        _DAILY_STATUS["phase"] = "bootstrap"
        _log("Step 4/6: full bootstrap (surface → ratings → predictions → settle → systems)")
        try:
            from api.bootstrap import full_bootstrap
            r = full_bootstrap()
            _log(f"bootstrap: {r}")
        except Exception as e:
            _log(f"bootstrap FAILED: {e}")

        # 5. Bookmaker odds
        _DAILY_STATUS["phase"] = "odds"
        _log("Step 5/7: bookmaker odds sync")
        try:
            if os.environ.get("ODDS_API_KEY"):
                try:
                    from pipeline.odds import run as odds_run
                except ImportError:
                    from odds import run as odds_run
                r = odds_run()
                _log(f"odds: {r}")
            else:
                _log("odds: skipped (ODDS_API_KEY not set)")
        except Exception as e:
            _log(f"odds FAILED: {e}")

        # Intentionally no auto-intel step here. Intel/deep-reasoning prose
        # is generated by Cowork sessions (the human/Claude driven path),
        # not via an automated Anthropic API call. The hook was briefly
        # added and then removed — don't re-add without explicit ask.

        # 6. Force fill ratings (recompute cold-start)
        _DAILY_STATUS["phase"] = "fill_ratings_force"
        _log("Step 6/7: force fill_ratings (refresh cold-start values)")
        try:
            from api.bootstrap import run_fill_ratings
            r = run_fill_ratings(force=True)
            _log(f"fill_ratings: {r}")
        except Exception as e:
            _log(f"fill_ratings FAILED: {e}")

        # 6. Healthcheck + auto-repair + email
        _DAILY_STATUS["phase"] = "healthcheck"
        _log("Step 7/7: healthcheck + auto-repair + email digest")
        try:
            try:
                from pipeline.healthcheck import (_connect, run_checks, log_results,
                                                    apply_auto_repair, _reopen)
            except ImportError:
                from healthcheck import (_connect, run_checks, log_results,
                                         apply_auto_repair, _reopen)
            try:
                from pipeline.health_email import send_digest
            except ImportError:
                try:
                    from health_email import send_digest
                except ImportError:
                    send_digest = None
            import uuid as _uuid
            from datetime import datetime as _dt
            run_id = _dt.utcnow().strftime("%Y%m%d-%H%M%S") + "-" + _uuid.uuid4().hex[:8]
            conn = _connect()
            try:
                results = run_checks(conn)
                rcon = _connect()
                try:
                    apply_auto_repair(rcon, results)
                finally:
                    rcon.close()
                # Re-check
                results = run_checks(_reopen(conn))
                conn = _connect()
                log_results(conn, run_id, results)
            finally:
                conn.close()
            if send_digest:
                try:
                    send_digest(run_id, results, force=True)
                except TypeError:
                    send_digest(run_id, results)
            _log(f"healthcheck done: run_id={run_id}, "
                 f"crit_fail={sum(1 for r in results if r.status=='FAIL' and r.severity=='CRITICAL')}")
        except Exception as e:
            _log(f"healthcheck FAILED: {e}")

        _DAILY_STATUS["phase"] = "done"
        _log("✅ Daily run complete")
    except SystemExit as e:
        _DAILY_STATUS["error"] = f"SystemExit: {e.code}"
    except BaseException as e:
        _DAILY_STATUS["error"] = f"{type(e).__name__}: {e}"
        log.error(f"daily worker failed: {e}")
        log.error(traceback.format_exc())
    finally:
        _DAILY_STATUS["finished_at"] = time.time()
        _DAILY_STATUS["running"] = False


@app.get("/admin/run-daily")
def admin_run_daily():
    """
    Run the full daily automation pipeline RIGHT NOW. Background-threaded —
    returns immediately, takes 5-15 min total.

    Sequence:
      1. bzzoiro matches sync (fresh fixture data)
      2. bzzoiro bios fill (DOB / country / full_name)
      3. heal-everything (twin merges + enrichment + fuzzy)
      4. full bootstrap (surface + ratings + predictions + settle + systems)
      5. force fill_ratings (refresh cold-start)
      6. healthcheck + auto-repair + email digest

    Poll /admin/run-daily/status for progress.
    """
    if _DAILY_STATUS.get("running"):
        return {"status": "already_running",
                "phase":  _DAILY_STATUS.get("phase"),
                "started_at": _DAILY_STATUS.get("started_at")}
    threading.Thread(target=_daily_worker, daemon=True).start()
    return {
        "status": "started",
        "poll":   "/admin/run-daily/status",
        "note":   "Background, 5-15 min. Same as scheduler does at 04:30/05:30/06:00/06:30/07:00 UTC.",
    }


@app.get("/admin/run-daily/status")
def admin_run_daily_status():
    import time
    s = dict(_DAILY_STATUS)
    if s.get("started_at"):
        s["elapsed_sec"] = round((s.get("finished_at") or time.time()) - s["started_at"], 1)
    s["log_tail"] = s.get("log", [])[-15:]
    s.pop("log", None)
    return s


@app.get("/admin/bzzoiro-bios/status")
def admin_bzzoiro_bios_status():
    """Return the latest bzzoiro-bios run state."""
    import time
    s = dict(_BZZOIRO_BIOS_STATUS)
    if s.get("started_at"):
        s["elapsed_sec"] = round(
            (s.get("finished_at") or time.time()) - s["started_at"], 1)
    return s


# ─────────────────────────────────────────────────────────────────────────────
# Sackmann WTA backfill — one-off; downloads + ingests Jeff Sackmann's
# tennis_wta repo to fill the gap that's stopping all WTA enrichment.
# ─────────────────────────────────────────────────────────────────────────────

_SACKMANN_WTA_STATUS = {
    "running": False, "phase": None, "started_at": None, "finished_at": None,
    "error": None, "log": [],
}


def _sackmann_wta_worker():
    import os, time, tempfile, traceback, shutil
    from pathlib import Path
    import psycopg2
    _SACKMANN_WTA_STATUS.update({
        "running": True, "phase": "starting",
        "started_at": time.time(), "finished_at": None, "error": None, "log": [],
    })

    def _log(msg):
        log.info(f"[sackmann-wta] {msg}")
        _SACKMANN_WTA_STATUS["log"].append(msg)
        _SACKMANN_WTA_STATUS["log"] = _SACKMANN_WTA_STATUS["log"][-200:]

    try:
        try:
            from pipeline.sackmann_ingest import (
                SACKMANN_REPOS, download_repo_zip,
                ingest_players, ingest_matches, ingest_rankings,
            )
        except ImportError:
            from sackmann_ingest import (
                SACKMANN_REPOS, download_repo_zip,
                ingest_players, ingest_matches, ingest_rankings,
            )

        db_url = os.environ.get("DATABASE_URL") or os.environ.get("DATABASE_PUBLIC_URL")
        if not db_url:
            _SACKMANN_WTA_STATUS["error"] = "DATABASE_URL not set"
            return

        conn = psycopg2.connect(db_url)
        # WTA-only ingestion (skip ATP — already loaded).
        # Skip run_schema — sa_players/sa_matches already exist in production
        # (ATP is loaded). Calling run_schema in a thread can sys.exit() the
        # thread silently if the SQL file isn't packaged in the image, which
        # is the case here.
        try:
            tmpdir = Path(tempfile.mkdtemp(prefix="sackmann_wta_"))
            try:
                _SACKMANN_WTA_STATUS["phase"] = "downloading"
                _log(f"Downloading WTA zip from {SACKMANN_REPOS['WTA']}")
                extracted = download_repo_zip(SACKMANN_REPOS["WTA"], tmpdir)
                _log(f"Extracted to {extracted}")

                _SACKMANN_WTA_STATUS["phase"] = "players"
                _log("Ingesting WTA players...")
                ingest_players(conn, extracted, "WTA")

                _SACKMANN_WTA_STATUS["phase"] = "matches"
                _log("Ingesting WTA matches (this is the long one)...")
                ingest_matches(conn, extracted, "WTA")

                _SACKMANN_WTA_STATUS["phase"] = "rankings"
                _log("Ingesting WTA rankings...")
                ingest_rankings(conn, extracted, "WTA")

                _SACKMANN_WTA_STATUS["phase"] = "done"
                _log("✅ WTA Sackmann backfill complete")
            finally:
                shutil.rmtree(tmpdir, ignore_errors=True)
        finally:
            conn.close()
    except SystemExit as e:
        _SACKMANN_WTA_STATUS["error"] = f"SystemExit: code={e.code}"
        log.error(f"sackmann-wta thread sys.exit() with code={e.code}")
    except BaseException as e:
        _SACKMANN_WTA_STATUS["error"] = f"{type(e).__name__}: {e}"
        log.error(f"sackmann-wta worker failed: {e}")
        log.error(traceback.format_exc())
    finally:
        _SACKMANN_WTA_STATUS["finished_at"] = time.time()
        _SACKMANN_WTA_STATUS["running"] = False


@app.get("/admin/sackmann-wta")
def admin_sackmann_wta():
    """
    Background WTA-only Sackmann ingestion. Downloads ~20MB zip, parses
    decades of WTA matches and players. Total runtime ~5-15 minutes.
    Idempotent — safe to retry; uses sa_ingest_log for resumability.
    """
    if _SACKMANN_WTA_STATUS.get("running"):
        return {"status": "already_running",
                "phase":  _SACKMANN_WTA_STATUS.get("phase"),
                "started_at": _SACKMANN_WTA_STATUS.get("started_at")}
    threading.Thread(target=_sackmann_wta_worker, daemon=True).start()
    return {
        "status": "started",
        "poll":   "/admin/sackmann-wta/status",
        "note":   "Runs in background, takes 5-15 min. Poll status URL.",
    }


@app.get("/admin/sackmann-wta/status")
def admin_sackmann_wta_status():
    """Latest Sackmann WTA ingestion state."""
    import time
    s = dict(_SACKMANN_WTA_STATUS)
    if s.get("started_at"):
        s["elapsed_sec"] = round(
            (s.get("finished_at") or time.time()) - s["started_at"], 1)
    # truncate log preview
    s["log_tail"] = s.get("log", [])[-15:]
    s.pop("log", None)
    return s


@app.get("/admin/healthcheck")
def admin_healthcheck(auto_repair: bool = True, email: bool = True):
    """
    Run the full healthcheck panel right now. Optionally auto-repair failing
    checks (default: yes) and send the email digest (default: yes).

    Hit this URL in your browser whenever the site looks broken:
        /admin/healthcheck?auto_repair=true&email=true

    Returns a JSON summary so you can see what passed/failed/was repaired.
    """
    def _run():
        import uuid as _uuid
        from datetime import datetime as _dt
        # Pipeline modules may live at pipeline.X (local dev) OR flat in /app
        # (Docker image built by api/Dockerfile — see scheduler.py for the same shim).
        try:
            from pipeline.healthcheck import (
                _connect, run_checks, log_results, apply_auto_repair, _reopen,
            )
        except ImportError:
            from healthcheck import (
                _connect, run_checks, log_results, apply_auto_repair, _reopen,
            )
        try:
            from pipeline.health_email import send_digest
        except ImportError:
            try:
                from health_email import send_digest
            except ImportError:
                send_digest = None
        except Exception:
            send_digest = None

        run_id = _dt.utcnow().strftime("%Y%m%d-%H%M%S") + "-" + _uuid.uuid4().hex[:8]
        conn = _connect()
        try:
            results = run_checks(conn)
        finally:
            pass

        if auto_repair:
            repair_conn = _connect()
            try:
                apply_auto_repair(repair_conn, results)
            finally:
                repair_conn.close()
            # Re-check after repair
            try:
                after = run_checks(_reopen(conn))
                by_name = {r.name: r for r in results}
                for r in after:
                    prev = by_name.get(r.name)
                    if prev and prev.auto_repaired:
                        r.auto_repaired = True
                        r.repair_message = prev.repair_message
                results = after
                conn = _connect()
            except Exception as e:
                log.warning(f"Re-check after repair failed: {e}")

        try:
            log_results(conn, run_id, results)
        except Exception as e:
            log.error(f"log_results failed: {e}")
        finally:
            conn.close()

        if email and send_digest is not None:
            try:
                send_digest(run_id, results, force=True)
            except TypeError:
                # Older send_digest signature without 'force'
                try:
                    send_digest(run_id, results)
                except Exception as e:
                    log.error(f"send_digest failed: {e}")
            except Exception as e:
                log.error(f"send_digest failed: {e}")

        # Return a tidy summary
        crit = sum(1 for r in results if r.status == "FAIL" and r.severity == "CRITICAL")
        warn = sum(1 for r in results if r.status == "FAIL" and r.severity == "WARNING")
        repaired = sum(1 for r in results if r.auto_repaired)
        return {
            "run_id":     run_id,
            "auto_repair": auto_repair,
            "summary": {
                "total":         len(results),
                "critical_fail": crit,
                "warning_fail":  warn,
                "auto_repaired": repaired,
                "all_passing":   crit == 0 and warn == 0,
            },
            "checks": [
                {
                    "name":           r.name,
                    "severity":       r.severity,
                    "status":         r.status,
                    "value":          r.value,
                    "threshold":      r.threshold,
                    "message":        r.message,
                    "auto_repaired":  r.auto_repaired,
                    "repair_message": r.repair_message,
                } for r in results
            ],
        }

    return _safe_admin(_run)


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

    # Fetch bookmaker odds on startup so the strip is populated immediately.
    # Runs silently if ODDS_API_KEY is not set.
    try:
        if os.environ.get("ODDS_API_KEY"):
            log.info("[startup] fetching bookmaker odds…")
            try:
                from pipeline.odds import run as odds_run
            except ImportError:
                from odds import run as odds_run
            result = odds_run()
            log.info(f"[startup] odds complete: {result}")
        else:
            log.info("[startup] ODDS_API_KEY not set — skipping odds fetch. "
                     "Add it to Railway Variables to enable bookmaker odds.")
    except Exception as e:
        log.error(f"[startup] odds fetch failed: {e}")


@app.on_event("startup")
def _kick_off_bootstrap():
    if os.environ.get("RTT_DISABLE_AUTO_BOOTSTRAP", "").lower() in ("1", "true", "yes"):
        log.info("[startup] auto-bootstrap disabled via RTT_DISABLE_AUTO_BOOTSTRAP")
        return
    # Deactivate legacy v1 systems immediately (synchronous, fast) before
    # the heavy bootstrap thread starts — ensures they're gone on every deploy.
    try:
        import psycopg2
        db_url = (os.environ.get("DATABASE_URL") or os.environ.get("DATABASE_PUBLIC_URL") or "").strip()
        if db_url:
            _conn = psycopg2.connect(db_url)
            _conn.autocommit = True
            with _conn.cursor() as _cur:
                legacy = ["surface_monster","form_surge","hand_advantage",
                          "big_match_player","underdog_value","rtt_mismatch","clutch_in_decider"]
                _cur.execute("UPDATE systems SET is_active = FALSE WHERE code = ANY(%s)", (legacy,))

                # ── Comprehensive surface correction ──────────────────────────
                # Root cause: pipeline inserts tournaments as Unknown when the
                # live API omits a surface field; _infer_surface import fails on
                # Railway flat-copy so inference never fires for new records.
                # Fix: on every deploy, correct all well-known clay/grass names.
                # Unconditional — NULL, Unknown, and wrong values all get fixed.

                clay_keywords = [
                    '%rome%','%internazionali%','%italian open%',
                    '%roland garros%','%french open%',
                    '%monte carlo%','%monte-carlo%',
                    '%madrid open%','%mutua madrid%',
                    '%barcelona%',
                    '%hamburg%',
                    '%buenos aires%','%rio open%',
                    '%geneva%','%lyon%',
                    '%parma%','%reggio emilia%',
                    '%bordeaux%','%strasbourg%',
                    '%marrakech%','%rabat%','%tunis%',
                    '%istanbul%',
                    '%houston%','%charleston%',
                    '%bucharest%','%warsaw%',
                    '%budapest%','%bastad%',
                    '%estoril%','%oeiras%','%estoril%',
                    '%cordoba%',
                    '%santiago%',
                    '%zagreb%','%umag%','%gstaad%',
                    '%kitzbuhel%','%kitzbuehel%',
                    '%marbella%','%valencia%',
                    '%trnava%','%prostejov%',
                    '%louny%','%kutaisi%','%vic%',
                    '%monastir%',
                ]
                grass_keywords = [
                    '%wimbledon%',
                    '%queen\'s%','%queens club%',
                    '%halle%',
                    '%eastbourne%','%bad homburg%',
                    '%nottingham%','%surbiton%','%ilkley%',
                    '%den bosch%','%rosmalen%',
                    '%birmingham%',
                    '%mallorca%',
                    '%newport%',
                    '%boss open%',
                ]
                clay_conditions = " OR ".join(f"LOWER(name) LIKE '{kw}'" for kw in clay_keywords)
                grass_conditions = " OR ".join(f"LOWER(name) LIKE '{kw}'" for kw in grass_keywords)

                _cur.execute(f"""
                    UPDATE tournaments
                    SET surface_id = (SELECT id FROM surfaces WHERE LOWER(name) = 'clay' LIMIT 1)
                    WHERE {clay_conditions}
                """)
                clay_fixed = _cur.rowcount

                _cur.execute(f"""
                    UPDATE tournaments
                    SET surface_id = (SELECT id FROM surfaces WHERE LOWER(name) = 'grass' LIMIT 1)
                    WHERE {grass_conditions}
                """)
                grass_fixed = _cur.rowcount

            _conn.close()
            log.info(f"[startup] legacy systems deactivated; surface fixed: {clay_fixed} clay, {grass_fixed} grass")
    except Exception as _e:
        log.warning(f"[startup] quick-fix failed (non-fatal): {_e}")
    threading.Thread(target=_startup_bootstrap, daemon=True).start()
