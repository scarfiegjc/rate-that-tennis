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
from fastapi.responses import HTMLResponse, Response

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
try:
    from api.routes.account import router as account_router
except ImportError:
    account_router = None
try:
    from api.routes.admin_marketing import router as admin_marketing_router
except ImportError:
    admin_marketing_router = None

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
if tournaments_router:      app.include_router(tournaments_router,      prefix="/api/v1")
if account_router:         app.include_router(account_router,         prefix="/api/v1")
if admin_marketing_router: app.include_router(admin_marketing_router, prefix="/api/v1")


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


@app.get("/sitemap.xml", response_class=Response)
def sitemap():
    """Dynamic XML sitemap — static pages + recent/upcoming match pages + player pages."""
    import datetime
    from api.db import get_conn

    base = "https://ratethat.tennis"
    today = datetime.date.today()
    week_ahead = today + datetime.timedelta(days=7)
    month_ago  = today - datetime.timedelta(days=90)

    urls = []

    # ── Static pages ──────────────────────────────────────────────────────
    static = [
        ("", "1.0",  "daily"),
        ("/predictions", "0.9", "daily"),
        ("/in-play",     "0.8", "always"),
        ("/systems",     "0.8", "weekly"),
        ("/players",     "0.8", "weekly"),
    ]
    for path, priority, freq in static:
        urls.append(f"""  <url>
    <loc>{base}{path}</loc>
    <changefreq>{freq}</changefreq>
    <priority>{priority}</priority>
  </url>""")

    # ── Match pages (upcoming + last 30 days) ─────────────────────────────
    try:
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT m.id,
                           COALESCE(p1.full_name, p1.name, '') AS p1,
                           COALESCE(p2.full_name, p2.name, '') AS p2,
                           m.event_date
                    FROM matches m
                    LEFT JOIN players p1 ON p1.id = m.first_player_id
                    LEFT JOIN players p2 ON p2.id = m.second_player_id
                    WHERE m.event_date BETWEEN %s AND %s
                      AND m.is_doubles = false
                    ORDER BY m.event_date DESC, m.id DESC
                    LIMIT 2000
                """, (str(month_ago), str(week_ahead)))
                rows = cur.fetchall()
        for row in rows:
            mid, p1, p2, edate = row['id'], row['p1'], row['p2'], row['event_date']
            # Build SEO slug matching matchUrl() helper in frontend
            slug_raw = f"{p1}-vs-{p2}".lower()
            slug = "".join(c if c.isalnum() or c == '-' else '-' for c in slug_raw)
            slug = "-".join(p for p in slug.split('-') if p)
            dt_str = str(edate) if edate else str(today)
            priority = "0.8" if edate and edate >= today else "0.5"
            urls.append(f"""  <url>
    <loc>{base}/match/{mid}/{slug}</loc>
    <lastmod>{dt_str}</lastmod>
    <changefreq>{"hourly" if edate and edate >= today else "never"}</changefreq>
    <priority>{priority}</priority>
  </url>""")
    except Exception:
        pass

    # ── Player pages ──────────────────────────────────────────────────────
    try:
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT p.id, COALESCE(p.full_name, p.name) AS player_name
                    FROM players p
                    JOIN player_ratings pr ON pr.player_id = p.id
                    ORDER BY pr.rtt_score DESC NULLS LAST
                    LIMIT 500
                """)
                players = cur.fetchall()
        for row in players:
            pid, name = row['id'], row['player_name']
            slug = "".join(c if c.isalnum() or c == '-' else '-' for c in (name or '').lower())
            slug = "-".join(p for p in slug.split('-') if p)
            slug_part = f"/{slug}" if slug else ""
            urls.append(f"""  <url>
    <loc>{base}/player/{pid}{slug_part}</loc>
    <changefreq>daily</changefreq>
    <priority>0.6</priority>
  </url>""")
    except Exception:
        pass

    xml = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
        + "\n".join(urls)
        + "\n</urlset>"
    )
    return Response(content=xml, media_type="application/xml")


# ─────────────────────────────────────────────────────────────────────────────
# SEO / Dynamic rendering endpoints
# Served to crawlers (Googlebot etc.) by nginx bot-detection.
# Returns lightweight HTML with full meta tags so Google indexes real content
# rather than an empty React shell.
# ─────────────────────────────────────────────────────────────────────────────

def _slug(name: str) -> str:
    """Convert a player name or match title into a URL slug."""
    s = (name or "").lower()
    s = "".join(c if c.isalnum() or c == "-" else "-" for c in s)
    return "-".join(p for p in s.split("-") if p)


def _esc(text) -> str:
    """Minimal HTML escaping for meta attribute values."""
    return str(text or "").replace("&", "&amp;").replace('"', "&quot;").replace("<", "&lt;").replace(">", "&gt;")


@app.get("/seo/match/{match_id}", response_class=HTMLResponse)
def seo_match(match_id: int):
    """
    Server-side rendered HTML for Googlebot crawling match pages.
    Returns a lightweight HTML page with proper title, meta description,
    canonical URL, Open Graph tags and JSON-LD structured data.
    Nginx routes crawler User-Agents here; humans get the React SPA.
    """
    from api.db import get_conn

    row = None
    try:
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT m.id,
                           COALESCE(p1.full_name, p1.name, '') AS p1,
                           COALESCE(p2.full_name, p2.name, '') AS p2,
                           COALESCE(t.name,'')         AS tournament,
                           COALESCE(s.name,'') AS surface,
                           m.event_date,
                           mp.prob_first_player  AS p1_win_probability,
                           mp.prob_second_player AS p2_win_probability,
                           mp.narrative
                    FROM matches m
                    LEFT JOIN players p1         ON p1.id = m.first_player_id
                    LEFT JOIN players p2         ON p2.id = m.second_player_id
                    LEFT JOIN tournaments t      ON t.id  = m.tournament_id
                    LEFT JOIN surfaces s         ON s.id  = t.surface_id
                    LEFT JOIN model_predictions mp ON mp.match_id = m.id
                    WHERE m.id = %s
                    LIMIT 1
                """, (match_id,))
                row = cur.fetchone()
    except Exception as exc:
        logging.warning("seo_match DB error: %s", exc)
        return HTMLResponse(status_code=500, content=f"<html><body><pre>DB ERROR: {exc}</pre></body></html>")

    if not row:
        return HTMLResponse(status_code=404, content="<html><body><p>Match not found.</p></body></html>")

    mid       = row['id']
    p1        = row['p1']
    p2        = row['p2']
    tournament = row['tournament']
    surface   = row['surface']
    event_date = row['event_date']
    p1_prob   = row['p1_win_probability']
    p2_prob   = row['p2_win_probability']
    narrative = row['narrative']

    slug = _slug(f"{p1}-vs-{p2}")
    canonical = f"https://ratethat.tennis/match/{mid}/{slug}"
    title = _esc(f"{p1} vs {p2} | {tournament} | RateThatTennis")

    desc_parts = [f"{p1} vs {p2}"]
    if tournament:
        desc_parts.append(f"at {tournament}")
    if surface:
        desc_parts.append(f"on {surface}")
    if p1_prob is not None and p2_prob is not None:
        desc_parts.append(
            f"ML win probability: {p1} {round(float(p1_prob) * 100)}% — {p2} {round(float(p2_prob) * 100)}%"
        )
    desc_parts.append("Free tennis analytics and predictions on RateThatTennis.")
    description = _esc(". ".join(desc_parts))

    prob_row = ""
    if p1_prob is not None and p2_prob is not None:
        prob_row = f"<p><strong>ML Win Probability:</strong> {_esc(p1)} {round(float(p1_prob)*100)}% | {_esc(p2)} {round(float(p2_prob)*100)}%</p>"

    narrative_block = f"<p>{_esc(narrative)}</p>" if narrative else ""

    json_ld = f"""{{
    "@context": "https://schema.org",
    "@type": "SportsEvent",
    "name": "{_esc(f'{p1} vs {p2}')}",
    "description": "{description}",
    "url": "{_esc(canonical)}",
    "startDate": "{_esc(str(event_date) if event_date else '')}",
    "location": {{"@type": "Place", "name": "{_esc(tournament)}"}},
    "sport": "Tennis",
    "competitor": [
      {{"@type": "Person", "name": "{_esc(p1)}"}},
      {{"@type": "Person", "name": "{_esc(p2)}"}}
    ]
  }}"""

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>{title}</title>
  <meta name="description" content="{description}">
  <link rel="canonical" href="{_esc(canonical)}">
  <meta name="robots" content="index, follow">
  <meta property="og:type"        content="article">
  <meta property="og:site_name"   content="RateThatTennis">
  <meta property="og:title"       content="{title}">
  <meta property="og:description" content="{description}">
  <meta property="og:url"         content="{_esc(canonical)}">
  <meta property="og:image"       content="https://ratethat.tennis/og-image.png">
  <meta name="twitter:card"        content="summary_large_image">
  <meta name="twitter:site"        content="@ratethattennis">
  <meta name="twitter:title"       content="{title}">
  <meta name="twitter:description" content="{description}">
  <meta name="twitter:image"       content="https://ratethat.tennis/og-image.png">
  <script type="application/ld+json">{json_ld}</script>
</head>
<body>
  <header><a href="https://ratethat.tennis">RateThatTennis</a></header>
  <main>
    <h1>{_esc(p1)} vs {_esc(p2)}</h1>
    <p><strong>Tournament:</strong> {_esc(tournament) or 'TBC'}</p>
    <p><strong>Surface:</strong> {_esc(surface) or 'TBC'}</p>
    <p><strong>Date:</strong> {_esc(str(event_date)) if event_date else 'TBC'}</p>
    {prob_row}
    {narrative_block}
    <p><a href="{_esc(canonical)}">View full match analysis →</a></p>
  </main>
</body>
</html>"""

    return HTMLResponse(content=html, headers={"Cache-Control": "public, max-age=3600"})


@app.get("/seo/player/{player_id}", response_class=HTMLResponse)
def seo_player(player_id: int):
    """
    Server-side rendered HTML for Googlebot crawling player pages.
    """
    from api.db import get_conn

    row = None
    try:
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT p.id, COALESCE(p.full_name, p.name) AS player_name, p.country,
                           pr.rtt_score, pr.form_score,
                           pr.serve_rating, pr.clay_rating, pr.hard_rating, pr.grass_rating
                    FROM players p
                    LEFT JOIN player_ratings pr ON pr.player_id = p.id
                    WHERE p.id = %s
                    LIMIT 1
                """, (player_id,))
                row = cur.fetchone()
    except Exception as exc:
        logging.warning("seo_player DB error: %s", exc)

    if not row:
        return HTMLResponse(status_code=404, content="<html><body><p>Player not found.</p></body></html>")

    pid        = row['id']
    name       = row['player_name']
    country    = row['country']
    rtt_score  = row['rtt_score']
    form_score = row['form_score']
    serve_rating = row['serve_rating']
    clay       = row['clay_rating']
    hard       = row['hard_rating']
    grass      = row['grass_rating']

    slug = _slug(name or "")
    canonical = f"https://ratethat.tennis/player/{pid}/{slug}"
    title = _esc(f"{name} | Tennis Analytics & Predictions | RateThatTennis")
    rtt_str = f"RTT Score {round(float(rtt_score))}/100" if rtt_score is not None else ""
    desc = _esc(
        f"{name} tennis analytics on RateThatTennis. {rtt_str}. "
        f"ML win predictions, RTT player ratings, form, serve stats and match history."
    )

    rating_rows = ""
    for label, val in [("RTT Score", rtt_score), ("Form", form_score), ("Serve", serve_rating),
                       ("Clay", clay), ("Hard", hard), ("Grass", grass)]:
        if val is not None:
            rating_rows += f"<p><strong>{label}:</strong> {round(float(val))}/100</p>\n    "

    json_ld = f"""{{
    "@context": "https://schema.org",
    "@type": "Person",
    "name": "{_esc(name)}",
    "description": "{desc}",
    "url": "{_esc(canonical)}",
    "sport": "Tennis"
  }}"""

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>{title}</title>
  <meta name="description" content="{desc}">
  <link rel="canonical" href="{_esc(canonical)}">
  <meta name="robots" content="index, follow">
  <meta property="og:type"        content="profile">
  <meta property="og:site_name"   content="RateThatTennis">
  <meta property="og:title"       content="{title}">
  <meta property="og:description" content="{desc}">
  <meta property="og:url"         content="{_esc(canonical)}">
  <meta property="og:image"       content="https://ratethat.tennis/og-image.png">
  <meta name="twitter:card"        content="summary_large_image">
  <meta name="twitter:site"        content="@ratethattennis">
  <meta name="twitter:title"       content="{title}">
  <meta name="twitter:description" content="{desc}">
  <meta name="twitter:image"       content="https://ratethat.tennis/og-image.png">
  <script type="application/ld+json">{json_ld}</script>
</head>
<body>
  <header><a href="https://ratethat.tennis">RateThatTennis</a></header>
  <main>
    <h1>{_esc(name)}</h1>
    {f"<p><strong>Country:</strong> {_esc(country)}</p>" if country else ""}
    {rating_rows}
    <p><a href="{_esc(canonical)}">View full player profile →</a></p>
  </main>
</body>
</html>"""

    return HTMLResponse(content=html, headers={"Cache-Control": "public, max-age=3600"})


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
              AND m.event_status = 'Finished'
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


@app.get("/admin/run-odds-io")
def admin_run_odds_io():
    """Fetch odds from odds-api.io (broader coverage: Challengers, ITF)."""
    def _run():
        if not os.environ.get("ODDS_API_IO_KEY"):
            return {"skipped": True, "reason": "ODDS_API_IO_KEY not set on Railway env vars"}
        try:
            from pipeline.odds_io import run as odds_io_run
        except ImportError:
            from odds_io import run as odds_io_run
        return odds_io_run()
    return _safe_admin(_run)


@app.get("/admin/run-bresbet-links")
def admin_run_bresbet_links():
    """Scrape Bresbet tennis page and store affiliate deep links for matched upcoming matches."""
    def _run():
        try:
            from pipeline.bresbet_links import run as bresbet_run
        except ImportError:
            from bresbet_links import run as bresbet_run
        return bresbet_run()
    return _safe_admin(_run)


# ─── Affiliate link management ───────────────────────────────────────────────

@app.get("/admin/affiliates")
def admin_affiliates_list():
    """List all bookmakers with their affiliate URL config."""
    from api.db import query
    rows = query("""
        SELECT ba.bookmaker_key, ba.display_name, ba.affiliate_url,
               ba.homepage_url, ba.is_active, ba.priority, ba.notes,
               ba.updated_at,
               COUNT(DISTINCT bo.match_id) AS matches_with_odds
        FROM bookmaker_affiliates ba
        LEFT JOIN bookmaker_odds bo ON bo.bookmaker = ba.bookmaker_key
        GROUP BY ba.bookmaker_key, ba.display_name, ba.affiliate_url,
                 ba.homepage_url, ba.is_active, ba.priority, ba.notes, ba.updated_at
        ORDER BY ba.priority ASC, ba.bookmaker_key ASC
    """)
    return {"bookmakers": [dict(r) for r in rows]}


from pydantic import BaseModel as _BaseModel
from typing import Optional as _OptStr

class AffiliateUpdate(_BaseModel):
    affiliate_url: _OptStr[str] = None
    homepage_url:  _OptStr[str] = None
    display_name:  _OptStr[str] = None
    is_active:     _OptStr[bool] = None
    priority:      _OptStr[int]  = None
    notes:         _OptStr[str]  = None

@app.put("/admin/affiliates/{bookmaker_key}")
def admin_affiliates_update(bookmaker_key: str, body: AffiliateUpdate):
    """Update affiliate URL and settings for one bookmaker."""
    import psycopg2
    db_url = os.environ.get("DATABASE_URL") or os.environ.get("DATABASE_PUBLIC_URL")
    conn = psycopg2.connect(db_url)
    conn.autocommit = False
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO bookmaker_affiliates (bookmaker_key, display_name)
                VALUES (%s, %s)
                ON CONFLICT (bookmaker_key) DO NOTHING
                """,
                (bookmaker_key, body.display_name or bookmaker_key),
            )
            fields = {}
            if body.affiliate_url is not None: fields["affiliate_url"] = body.affiliate_url
            if body.homepage_url  is not None: fields["homepage_url"]  = body.homepage_url
            if body.display_name  is not None: fields["display_name"]  = body.display_name
            if body.is_active     is not None: fields["is_active"]     = body.is_active
            if body.priority      is not None: fields["priority"]      = body.priority
            if body.notes         is not None: fields["notes"]         = body.notes
            if fields:
                set_parts = []
                values = []
                for k, v in fields.items():
                    set_parts.append(f"{k} = %s")
                    values.append(v)
                set_parts.append("updated_at = NOW()")
                cur.execute(
                    f"UPDATE bookmaker_affiliates SET {', '.join(set_parts)} WHERE bookmaker_key = %s",
                    values + [bookmaker_key],
                )
        conn.commit()
        with conn.cursor() as cur:
            cur.execute(
                "SELECT bookmaker_key, display_name, affiliate_url, homepage_url, "
                "is_active, priority, notes FROM bookmaker_affiliates WHERE bookmaker_key = %s",
                (bookmaker_key,),
            )
            row = cur.fetchone()
            cols = ["bookmaker_key","display_name","affiliate_url","homepage_url",
                    "is_active","priority","notes"]
            return {"updated": dict(zip(cols, row)) if row else None}
    finally:
        conn.close()


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


def _periodic_surface_backfill():
    """Run surface backfill every 6 hours so new tournament records never stay
    'Unknown' for long between full-bootstrap / deploy cycles."""
    import time
    # Initial delay — let startup bootstrap finish first
    time.sleep(600)
    while True:
        try:
            from api.bootstrap import run_surface_backfill
            result = run_surface_backfill()
            n = result.get("updated", 0)
            if n:
                log.info(f"[surface-backfill periodic] updated {n} tournament surfaces")
        except Exception as e:
            log.warning(f"[surface-backfill periodic] failed: {e}")
        time.sleep(6 * 3600)  # 6 hours


@app.on_event("startup")
def _kick_off_bootstrap():
    if os.environ.get("RTT_DISABLE_AUTO_BOOTSTRAP", "").lower() in ("1", "true", "yes"):
        log.info("[startup] auto-bootstrap disabled via RTT_DISABLE_AUTO_BOOTSTRAP")
        return
    threading.Thread(target=_startup_bootstrap, daemon=True).start()
    threading.Thread(target=_periodic_surface_backfill, daemon=True).start()
