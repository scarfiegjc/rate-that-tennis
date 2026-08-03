#!/usr/bin/env python3
"""
ratethat.tennis — Pipeline Scheduler

Runs continuously on Railway, keeping the database up-to-date automatically:
  - daily_fixtures          : 06:00 and 18:00 UTC every day (fetches today + next 2 days)
  - predictions             : 06:30 and 18:30 UTC (ML win probabilities, runs after fixtures)
  - livescore               : every 5 minutes (live match updates during play)
  - odds                    : 07:00, 12:00, and 19:00 UTC (bookmaker odds via The Odds API)
  - ratings                 : daily at 01:00 UTC and 08:00 UTC (RTT player ratings)
  - bzzoiro_matches         : 06:15 and 18:15 UTC (match sync, after fixtures)
  - bzzoiro_predictions     : 06:20 and 18:20 UTC (prediction fallback sync)
  - bzzoiro_rankings        : every Monday 07:00 UTC
  - bzzoiro_player_bios     : every Monday 07:05 UTC
  - sync_events             : once on startup (event types + tournaments)

No manual intervention needed once deployed.
"""
import os
import time
import logging
import sys
import schedule

from pipeline import run_job

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)]
)
log = logging.getLogger("rtt-scheduler")


# ─────────────────────────────────────────────
# JOB WRAPPERS  (swallow exceptions so the
# scheduler loop never dies on a single failure)
# ─────────────────────────────────────────────

def run_daily_fixtures():
    log.info("Scheduled: daily_fixtures")
    try:
        run_job("daily_fixtures")
    except Exception as e:
        log.error(f"daily_fixtures failed: {e}")


def run_livescore():
    try:
        run_job("livescore")
    except Exception as e:
        log.error(f"livescore failed: {e}")


def run_odds():
    """Fetch latest bookmaker odds — only runs if ODDS_API_KEY is configured."""
    api_key = os.environ.get("ODDS_API_KEY", "")
    if not api_key:
        log.info("Skipping odds sync — ODDS_API_KEY not set")
        return
    log.info("Scheduled: odds sync (the-odds-api.com)")
    try:
        from odds import run as odds_run
        odds_run()
    except Exception as e:
        log.error(f"odds sync failed: {e}")


def run_odds_io():
    """Fetch odds from odds-api.io (Challengers, ITF, broader coverage)."""
    api_key = os.environ.get("ODDS_API_IO_KEY", "")
    if not api_key:
        log.info("Skipping odds-api.io sync — ODDS_API_IO_KEY not set")
        return
    log.info("Scheduled: odds sync (odds-api.io)")
    try:
        from odds_io import run as odds_io_run
        odds_io_run()
    except Exception as e:
        log.error(f"odds-api.io sync failed: {e}")


def run_bresbet_links():
    """Scrape Bresbet tennis page and store affiliate deep links."""
    log.info("Scheduled: Bresbet deep-link scrape")
    try:
        try:
            from pipeline.bresbet_links import run as bresbet_run
        except ImportError:
            from bresbet_links import run as bresbet_run
        bresbet_run()
    except Exception as e:
        log.error(f"Bresbet links failed: {e}")


def run_cloudbet_odds():
    """Fetch Cloudbet tennis odds + per-event deep links via their API."""
    log.info("Scheduled: Cloudbet odds + deep links")
    try:
        try:
            from pipeline.cloudbet_odds import run as cloudbet_run
        except ImportError:
            from cloudbet_odds import run as cloudbet_run
        cloudbet_run()
    except Exception as e:
        log.error(f"Cloudbet odds failed: {e}")


# ─────────────────────────────────────────────
# BZZOIRO JOB WRAPPERS
# ─────────────────────────────────────────────

def _import_bzzoiro():
    """Import shim — works as pipeline.* package locally and flat in Docker."""
    try:
        from pipeline.bzzoiro_ingest import sync_matches, sync_predictions, sync_rankings, sync_player_bios, get_db_conn
    except ImportError:
        from bzzoiro_ingest import sync_matches, sync_predictions, sync_rankings, sync_player_bios, get_db_conn
    return sync_matches, sync_predictions, sync_rankings, sync_player_bios, get_db_conn


def run_bzzoiro_matches():
    """Sync Bzzoiro match data: last 1 day + next 2 days. Runs after fixtures."""
    log.info("Scheduled: Bzzoiro match sync")
    try:
        from datetime import date, timedelta
        sync_matches, _, _, _, get_db_conn = _import_bzzoiro()
        date_from = (date.today() - timedelta(days=1)).isoformat()
        date_to = (date.today() + timedelta(days=2)).isoformat()
        conn = get_db_conn()
        try:
            sync_matches(conn, date_from, date_to)
        finally:
            conn.close()
    except Exception as e:
        log.error(f"Bzzoiro match sync failed: {e}")


def run_bzzoiro_predictions():
    """Sync Bzzoiro predictions as a fallback for matches our own model didn't predict."""
    log.info("Scheduled: Bzzoiro predictions sync")
    try:
        from datetime import date, timedelta
        _, sync_predictions, _, _, get_db_conn = _import_bzzoiro()
        date_from = (date.today() - timedelta(days=1)).isoformat()
        date_to = (date.today() + timedelta(days=2)).isoformat()
        conn = get_db_conn()
        try:
            sync_predictions(conn, date_from, date_to)
        finally:
            conn.close()
    except Exception as e:
        log.error(f"Bzzoiro predictions sync failed: {e}")


def run_bzzoiro_rankings():
    """Weekly sync of Bzzoiro player rankings."""
    log.info("Scheduled: Bzzoiro rankings sync")
    try:
        _, _, sync_rankings, _, get_db_conn = _import_bzzoiro()
        conn = get_db_conn()
        try:
            sync_rankings(conn)
        finally:
            conn.close()
    except Exception as e:
        log.error(f"Bzzoiro rankings sync failed: {e}")


def run_bzzoiro_player_bios():
    """Weekly sync of Bzzoiro player bios."""
    log.info("Scheduled: Bzzoiro player bios sync")
    try:
        _, _, _, sync_player_bios, get_db_conn = _import_bzzoiro()
        conn = get_db_conn()
        try:
            sync_player_bios(conn)
        finally:
            conn.close()
    except Exception as e:
        log.error(f"Bzzoiro player bios sync failed: {e}")


# ─────────────────────────────────────────────
# BZZOIRO.PY JOB WRAPPERS
# (fixtures with bzzoiro_id, live data, odds, O/U predictions, H2H)
# ─────────────────────────────────────────────

def _import_bzzoiro_new():
    """Import shim for pipeline/bzzoiro.py (the BzzoiroClient-based module)."""
    try:
        from pipeline.bzzoiro import (
            sync_fixtures, sync_live, sync_rankings as bzz_rankings,
            sync_odds, sync_predictions as bzz_predictions,
            sync_h2h_upcoming, sync_point_by_point_recent, get_db_conn,
        )
    except ImportError:
        from bzzoiro import (
            sync_fixtures, sync_live, sync_rankings as bzz_rankings,
            sync_odds, sync_predictions as bzz_predictions,
            sync_h2h_upcoming, sync_point_by_point_recent, get_db_conn,
        )
    return (sync_fixtures, sync_live, bzz_rankings, sync_odds, bzz_predictions,
            sync_h2h_upcoming, sync_point_by_point_recent, get_db_conn)


def run_bzzoiro_fixtures():
    """Sync bzzoiro upcoming fixtures (next 7 days) — stores bzzoiro_id on matches."""
    log.info("Scheduled: bzzoiro fixtures sync")
    try:
        sync_fixtures, _, _, _, _, _, _, get_db_conn = _import_bzzoiro_new()
        conn = get_db_conn()
        try:
            sync_fixtures(conn, days_ahead=7)
        finally:
            conn.close()
    except Exception as e:
        log.error(f"bzzoiro fixtures sync failed: {e}")


def run_bzzoiro_live():
    """Sync bzzoiro live match data (scores, serve stats → live_data JSONB)."""
    try:
        _, sync_live, _, _, _, _, _, get_db_conn = _import_bzzoiro_new()
        conn = get_db_conn()
        try:
            sync_live(conn)
        finally:
            conn.close()
    except Exception as e:
        log.error(f"bzzoiro live sync failed: {e}")


def run_bzzoiro_odds():
    """Fetch per-bookmaker odds for upcoming matches via bzzoiro /matches/{id}/odds/."""
    log.info("Scheduled: bzzoiro odds sync")
    try:
        _, _, _, sync_odds, _, _, _, get_db_conn = _import_bzzoiro_new()
        conn = get_db_conn()
        try:
            sync_odds(conn)
        finally:
            conn.close()
    except Exception as e:
        log.error(f"bzzoiro odds sync failed: {e}")


def run_bzzoiro_ou_predictions():
    """Sync bzzoiro O/U predictions → bzzoiro_predictions table."""
    log.info("Scheduled: bzzoiro O/U predictions sync")
    try:
        _, _, _, _, bzz_predictions, _, _, get_db_conn = _import_bzzoiro_new()
        conn = get_db_conn()
        try:
            bzz_predictions(conn)
        finally:
            conn.close()
    except Exception as e:
        log.error(f"bzzoiro O/U predictions sync failed: {e}")


def run_bzzoiro_rankings_new():
    """Sync ATP+WTA rankings with movement (ranking_movement, ranking_career_best)."""
    log.info("Scheduled: bzzoiro rankings sync (with movement)")
    try:
        _, _, bzz_rankings, _, _, _, _, get_db_conn = _import_bzzoiro_new()
        conn = get_db_conn()
        try:
            bzz_rankings(conn)
        finally:
            conn.close()
    except Exception as e:
        log.error(f"bzzoiro rankings (new) sync failed: {e}")


def run_bzzoiro_h2h():
    """Sync H2H data for upcoming matches that don't have it yet."""
    log.info("Scheduled: bzzoiro H2H sync")
    try:
        _, _, _, _, _, sync_h2h_upcoming, _, get_db_conn = _import_bzzoiro_new()
        conn = get_db_conn()
        try:
            sync_h2h_upcoming(conn)
        finally:
            conn.close()
    except Exception as e:
        log.error(f"bzzoiro H2H sync failed: {e}")


def run_bzzoiro_point_by_point():
    """Sync point-by-point data for recently finished matches that don't have it yet."""
    log.info("Scheduled: bzzoiro point-by-point sync")
    try:
        _, _, _, _, _, _, sync_point_by_point_recent, get_db_conn = _import_bzzoiro_new()
        conn = get_db_conn()
        try:
            sync_point_by_point_recent(conn, days_back=3)
        finally:
            conn.close()
    except Exception as e:
        log.error(f"bzzoiro point-by-point sync failed: {e}")


# ─────────────────────────────────────────────
# SEO CONTENT GENERATION WRAPPER
# ─────────────────────────────────────────────

def run_seo_previews():
    """Generate Anthropic-powered 250-word SEO match previews for upcoming matches."""
    log.info("Scheduled: SEO match preview generation")
    try:
        try:
            from pipeline.content_gen import generate_previews, append_results, get_db_conn as content_db_conn
        except ImportError:
            from content_gen import generate_previews, append_results, get_db_conn as content_db_conn

        conn = content_db_conn()
        try:
            result = generate_previews(conn, limit=50)
            log.info(f"  SEO previews generated: {result}")
            result2 = append_results(conn, days_back=3)
            log.info(f"  SEO results appended: {result2}")
        finally:
            conn.close()
    except Exception as e:
        log.error(f"SEO preview generation failed: {e}")
        import traceback
        log.error(traceback.format_exc())


# ─────────────────────────────────────────────
# DAILY HEALTHCHECK
# pipeline/healthcheck.py + pipeline/health_email.py were referenced by
# api/main.py's /admin/healthcheck for months but never existed until the
# 2026-08 audit. Running it here too means it happens automatically every
# day rather than depending on someone hitting the admin URL.
# ─────────────────────────────────────────────

def run_healthcheck():
    """Run the daily data-health check panel and email a digest if configured."""
    log.info("Scheduled: healthcheck")
    try:
        try:
            from pipeline.healthcheck import _connect, run_checks, apply_auto_repair, log_results
        except ImportError:
            from healthcheck import _connect, run_checks, apply_auto_repair, log_results
        try:
            from pipeline.health_email import send_digest
        except ImportError:
            from health_email import send_digest

        import uuid
        from datetime import datetime as _dt
        run_id = _dt.utcnow().strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:8]

        conn = _connect()
        try:
            results = run_checks(conn)
            apply_auto_repair(conn, results)
            log_results(conn, run_id, results)
        finally:
            conn.close()

        send_digest(run_id, results)  # no-ops quietly if RESEND_API_KEY isn't set
        crit = sum(1 for r in results if r.status == "FAIL" and r.severity == "CRITICAL")
        log.info(f"  healthcheck run_id={run_id}: {len(results)} checks, {crit} critical failures")
    except Exception as e:
        log.error(f"healthcheck failed: {e}")
        import traceback
        log.error(traceback.format_exc())


# ─────────────────────────────────────────────
# Import shim — works both as a `pipeline.*` package locally and as flat
# files inside the Docker image (Dockerfile copies pipeline/*.py into /app).
# ─────────────────────────────────────────────

def _import_compute_hand_splits():
    try:
        from pipeline.player_splits import compute_hand_splits
        return compute_hand_splits
    except ImportError:
        from player_splits import compute_hand_splits
        return compute_hand_splits


def _import_settle():
    try:
        from pipeline.settle_predictions import settle_predictions
        return settle_predictions
    except ImportError:
        from settle_predictions import settle_predictions
        return settle_predictions


def _import_fill_ratings():
    try:
        from pipeline.fill_ratings import fill_missing_ratings
        return fill_missing_ratings
    except ImportError:
        from fill_ratings import fill_missing_ratings
        return fill_missing_ratings


def _import_surface_backfill():
    try:
        from pipeline.surface_backfill import backfill_surfaces
        return backfill_surfaces
    except ImportError:
        from surface_backfill import backfill_surfaces
        return backfill_surfaces


def run_predictions():
    """
    Full predictions pipeline (RTT v1):
      0. Refresh tournament surfaces (Wuxi → Hard, etc.)
      1. Fill missing player ratings (every active player gets an RTT)
      2. Refresh hand-vs-hand splits
      3. Compute RTT-based win probabilities for next 7 days
      4. Settle finished matches (last 14 days)
      5. Evaluate systems (Surface Monster, Form Surge, …)

    All stages use only psycopg2 + stdlib so they're Railway-safe.
    Each stage is wrapped so a single failure doesn't poison the rest.
    """
    log.info("Scheduled: predictions (RTT v1)")
    import psycopg2

    db_url = os.environ.get("DATABASE_URL") or os.environ.get("DATABASE_PUBLIC_URL")

    # 0) Surface backfill
    try:
        backfill_surfaces = _import_surface_backfill()
        conn = psycopg2.connect(db_url)
        try:
            backfill_surfaces(conn)
        finally:
            conn.close()
    except Exception as e:
        log.error(f"surface backfill failed: {e}")

    # 1) Fill missing player ratings — done before predictions so cold-start
    # players in upcoming matches always have an RTT score to drive predictions
    try:
        fill_missing_ratings = _import_fill_ratings()
        conn = psycopg2.connect(db_url)
        try:
            fill_missing_ratings(conn)
        finally:
            conn.close()
    except Exception as e:
        log.error(f"fill missing ratings failed: {e}")

    # 2) Hand splits
    try:
        compute_hand_splits = _import_compute_hand_splits()
        conn = psycopg2.connect(db_url)
        try:
            compute_hand_splits(conn)
        finally:
            conn.close()
    except Exception as e:
        log.error(f"hand splits failed: {e}")

    # 2) Predictions — use the name-keyed Elo predictor (ml.predict).
    # The previous additive-logit RttPredictor (model_version='rtt-v2'/'rtt-v3')
    # was retired in May 2026: it produced 50/50 outputs whenever the rtt_score
    # population was clustered (e.g. after a percentile-based rating refresh),
    # because rtt_gap → 0 and sigmoid(0) = 0.5. The replacement reads Elo from
    # the corrected sa_matches.winner_name + live history and blends in the
    # trained logistic only when it agrees with Elo direction.
    try:
        from ml.predict import LivePredictor
        predictor = LivePredictor(neutralise_rtt=False)
        predictor.load_models()
        predictor.load_player_history(years_back=8)
        predictor.predict_upcoming(days_ahead=7)
    except Exception as e:
        log.error(f"predictions failed: {e}")
        import traceback
        log.error(traceback.format_exc())

    # 3) Settle finished matches
    try:
        settle_predictions = _import_settle()
        conn = psycopg2.connect(db_url)
        try:
            settle_predictions(conn)
        finally:
            conn.close()
    except Exception as e:
        log.error(f"settle predictions failed: {e}")

    # 4) Systems engine
    try:
        from ml.systems import SystemsEngine
        eng = SystemsEngine()
        try:
            eng.evaluate_upcoming(days_ahead=7)
        finally:
            eng.close()
    except Exception as e:
        log.error(f"systems eval failed: {e}")


def run_email_predictions_digest():
    """Send the daily top-20 predictions email to all opted-in users."""
    log.info("Scheduled: daily predictions email digest")
    try:
        from email_tasks import send_daily_predictions_digest
        result = send_daily_predictions_digest()
        log.info(f"Predictions digest complete: {result}")
    except Exception as e:
        log.error(f"Predictions digest failed: {e}")


def run_email_picks_summary():
    """Send personalised picks + P&L update to users with active/recent picks."""
    log.info("Scheduled: daily picks email summary")
    try:
        from email_tasks import send_daily_picks_emails
        result = send_daily_picks_emails()
        log.info(f"Picks summary complete: {result}")
    except Exception as e:
        log.error(f"Picks summary failed: {e}")


def run_ratings():
    """
    Compute player ratings (Elo-based, 0-100) for all players.
    Uses auto_data (psycopg2-only, no ml/ dependencies).
    Writes to player_ratings and player_ratings_history tables.
    Runs on startup and daily at 01:00 UTC.
    """
    log.info("Running: player ratings computation...")
    try:
        from auto_data import run_ratings as _run
        _run()
        log.info("Player ratings computation complete")
    except Exception as e:
        log.error(f"ratings failed: {e}")
        import traceback
        log.error(traceback.format_exc())


def apply_schema_migrations():
    """
    Apply pending schema migrations on every boot.
    Each migration is idempotent (CREATE TABLE IF NOT EXISTS, ADD COLUMN IF NOT EXISTS,
    CREATE OR REPLACE VIEW, INSERT … ON CONFLICT DO UPDATE), so running on every
    boot is safe and self-healing.

    Files applied (in order):
      - pipeline/schema_additions.sql        (existing — ratings history, odds, etc.)
      - pipeline/predictions_schema.sql      (new — prediction tracking + systems)
    """
    log.info("Startup: applying schema migrations...")
    import psycopg2
    db_url = os.environ.get("DATABASE_URL") or os.environ.get("DATABASE_PUBLIC_URL")
    if not db_url:
        log.error("  No DATABASE_URL — skipping migrations")
        return

    here = os.path.dirname(os.path.abspath(__file__))
    # Files live next to scheduler.py in the Docker image (flat copy);
    # locally they're inside pipeline/.
    candidate_dirs = [here, os.path.join(here, "pipeline")]

    migrations = ["schema_additions.sql", "predictions_schema.sql", "picks_schema.sql", "bzzoiro_schema.sql"]

    conn = psycopg2.connect(db_url)
    conn.autocommit = True
    try:
        for fname in migrations:
            path = None
            for d in candidate_dirs:
                p = os.path.join(d, fname)
                if os.path.exists(p):
                    path = p
                    break
            if not path:
                log.warning(f"  {fname} not found in {candidate_dirs} — skipping")
                continue

            with open(path) as f:
                sql = f.read()

            # Split on semicolons but skip --comment lines
            ok = errors = skipped = 0
            for raw in sql.split(";"):
                lines = [l for l in raw.splitlines() if not l.strip().startswith("--")]
                stmt = "\n".join(lines).strip()
                if not stmt:
                    continue
                try:
                    with conn.cursor() as cur:
                        cur.execute(stmt)
                    ok += 1
                except (psycopg2.errors.DuplicateTable,
                        psycopg2.errors.DuplicateObject,
                        psycopg2.errors.DuplicateColumn):
                    skipped += 1
                except Exception as e:
                    msg = str(e).lower()
                    if "already exists" in msg:
                        skipped += 1
                    else:
                        log.warning(f"  {fname}: statement error: {e}")
                        errors += 1
            log.info(f"  {fname}: applied={ok}, skipped={skipped}, errors={errors}")
    finally:
        conn.close()


def run_startup_sync():
    """One-time sync of event types and tournaments on first boot."""
    log.info("Startup: syncing event types...")
    try:
        run_job("sync_event_types")
    except Exception as e:
        log.error(f"sync_event_types failed: {e}")

    log.info("Startup: syncing tournaments...")
    try:
        run_job("sync_tournaments")
    except Exception as e:
        log.error(f"sync_tournaments failed: {e}")


# ─────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────

if __name__ == "__main__":
    log.info("ratethat.tennis pipeline scheduler starting...")

    # ── Self-healing schema migrations (idempotent, safe to re-run) ─────────
    apply_schema_migrations()

    # ── Startup jobs in DEPENDENCY ORDER ─────────────────────────────────────
    # 1. Schema (above)
    # 2. Fixtures + tournaments — populate the data layer first
    log.info("Running startup: daily fixtures...")
    run_daily_fixtures()
    log.info("Running startup: bzzoiro matches...")
    run_bzzoiro_matches()
    log.info("Running startup: bzzoiro fixtures...")
    run_bzzoiro_fixtures()
    log.info("Running startup: event type + tournament sync...")
    run_startup_sync()

    # 3. Surface backfill — now that we have all tournaments
    log.info("Startup: backfilling tournament surfaces...")
    try:
        try:
            from pipeline.surface_backfill import backfill_surfaces
        except ImportError:
            from surface_backfill import backfill_surfaces
        import psycopg2
        conn = psycopg2.connect(
            os.environ.get("DATABASE_URL") or os.environ.get("DATABASE_PUBLIC_URL")
        )
        try:
            backfill_surfaces(conn)
        finally:
            conn.close()
    except Exception as e:
        log.error(f"surface backfill failed: {e}")

    # 4. Compute proper RTT ratings (auto_data — uses sa_matches history)
    log.info("Running startup: RTT ratings computation...")
    run_ratings()

    # 5. Fill any gaps — every player in an upcoming match should have an RTT
    log.info("Startup: filling missing player ratings...")
    try:
        try:
            from pipeline.fill_ratings import fill_missing_ratings
        except ImportError:
            from fill_ratings import fill_missing_ratings
        import psycopg2
        conn = psycopg2.connect(
            os.environ.get("DATABASE_URL") or os.environ.get("DATABASE_PUBLIC_URL")
        )
        try:
            fill_missing_ratings(conn)
        finally:
            conn.close()
    except Exception as e:
        log.error(f"fill_missing_ratings failed: {e}")

    # 6. Predictions (uses RTT data + hand splits + systems)
    log.info("Running startup: predictions...")
    run_predictions()

    # 7. Odds (independent — runs anytime)
    log.info("Running startup: odds...")
    run_odds()
    run_odds_io()
    run_bresbet_links()
    # NOTE: run_cloudbet_odds() deliberately NOT called here.
    # Cloudbet deep-link matching is run manually via run_cloudbet_odds.command.
    # Running it on every Railway startup was overwriting locally-populated odds data
    # with empty/unmatched results, causing OddsRail to disappear after deploys.

    # ── Scheduled jobs ──────────────────────────────────────────────────────
    schedule.every().day.at("06:00").do(run_daily_fixtures)   # 06:00 UTC
    # Surface backfill before predictions so any new tournaments get a surface
    def _surface_backfill_only():
        try:
            try:
                from pipeline.surface_backfill import backfill_surfaces
            except ImportError:
                from surface_backfill import backfill_surfaces
            import psycopg2
            conn = psycopg2.connect(
                os.environ.get("DATABASE_URL") or os.environ.get("DATABASE_PUBLIC_URL")
            )
            try:
                backfill_surfaces(conn)
            finally:
                conn.close()
        except Exception as e:
            log.error(f"surface backfill (rolling) failed: {e}")
    schedule.every().day.at("06:15").do(_surface_backfill_only)
    def _fill_ratings_only():
        try:
            try:
                from pipeline.fill_ratings import fill_missing_ratings
            except ImportError:
                from fill_ratings import fill_missing_ratings
            import psycopg2
            conn = psycopg2.connect(
                os.environ.get("DATABASE_URL") or os.environ.get("DATABASE_PUBLIC_URL")
            )
            try:
                fill_missing_ratings(conn)
            finally:
                conn.close()
        except Exception as e:
            log.error(f"fill ratings (rolling) failed: {e}")
    schedule.every().day.at("06:20").do(_fill_ratings_only)
    schedule.every().day.at("06:30").do(run_predictions)      # predictions after morning fixtures
    schedule.every().day.at("18:00").do(run_daily_fixtures)   # 18:00 UTC
    schedule.every().day.at("18:15").do(_surface_backfill_only)
    schedule.every().day.at("18:20").do(_fill_ratings_only)
    schedule.every().day.at("18:30").do(run_predictions)      # predictions after evening fixtures
    # Hourly results refresh 08:00–22:00 UTC — catches completed matches and
    # withdrawals between the main 06:00 and 18:00 fixture pulls.
    # Skips hours already covered by the main pulls (06, 18).
    for _hr in ["08", "09", "10", "11", "12", "13", "14", "15", "16", "17",
                "19", "20", "21", "22"]:
        schedule.every().day.at(f"{_hr}:00").do(run_daily_fixtures)
    schedule.every(5).minutes.do(run_livescore)               # live scores
    # Settle predictions every 15 minutes — keeps the tracker page live as
    # matches finish through the day.
    def _settle_only():
        try:
            settle_predictions = _import_settle()
            import psycopg2
            conn = psycopg2.connect(
                os.environ.get("DATABASE_URL") or os.environ.get("DATABASE_PUBLIC_URL")
            )
            try:
                settle_predictions(conn)
            finally:
                conn.close()
        except Exception as e:
            log.error(f"settle (rolling) failed: {e}")
    schedule.every(15).minutes.do(_settle_only)
    schedule.every().day.at("07:00").do(run_odds)             # odds after fixtures
    schedule.every().day.at("07:05").do(run_odds_io)          # odds-api.io (Challengers/ITF)
    schedule.every().day.at("07:10").do(run_bresbet_links)    # Bresbet affiliate deep links
    schedule.every().day.at("12:00").do(run_odds)             # midday odds refresh
    schedule.every().day.at("12:05").do(run_odds_io)          # odds-api.io midday refresh
    schedule.every().day.at("19:00").do(run_odds)             # evening refresh
    schedule.every().day.at("19:05").do(run_odds_io)          # odds-api.io evening refresh
    schedule.every().day.at("19:10").do(run_bresbet_links)    # Bresbet evening refresh
    schedule.every().day.at("07:15").do(run_cloudbet_odds)    # Cloudbet odds + deep links (morning)
    schedule.every().day.at("12:10").do(run_cloudbet_odds)    # Cloudbet midday refresh
    schedule.every().day.at("19:15").do(run_cloudbet_odds)    # Cloudbet evening refresh
    schedule.every().day.at("01:00").do(run_ratings)           # daily ratings refresh (overnight)
    schedule.every().day.at("08:00").do(run_ratings)           # daily ratings refresh (morning, after predictions)
    schedule.every().day.at("08:15").do(run_email_predictions_digest)  # predictions digest email
    schedule.every().day.at("08:45").do(run_email_picks_summary)       # personalised picks email
    # Bzzoiro match + predictions sync — runs after each fixtures pull
    schedule.every().day.at("06:15").do(run_bzzoiro_matches)       # after morning fixtures
    schedule.every().day.at("06:20").do(run_bzzoiro_predictions)   # after morning Bzzoiro matches
    schedule.every().day.at("18:15").do(run_bzzoiro_matches)       # after evening fixtures
    schedule.every().day.at("18:20").do(run_bzzoiro_predictions)   # after evening Bzzoiro matches
    # Bzzoiro weekly syncs — Monday morning
    schedule.every().monday.at("07:00").do(run_bzzoiro_rankings)   # player rankings
    schedule.every().monday.at("07:05").do(run_bzzoiro_player_bios)  # player bios
    # bzzoiro.py — fixtures, live, odds, O/U predictions, H2H (BzzoiroClient module)
    schedule.every().day.at("06:30").do(run_bzzoiro_fixtures)      # after morning fixtures + predictions
    schedule.every().day.at("18:30").do(run_bzzoiro_fixtures)      # after evening fixtures + predictions
    schedule.every(60).seconds.do(run_bzzoiro_live)                 # live scores every 60s
    schedule.every().day.at("07:00").do(run_bzzoiro_rankings_new)  # rankings with movement (daily)
    schedule.every().day.at("07:30").do(run_bzzoiro_odds)          # bookmaker odds morning
    schedule.every().day.at("19:30").do(run_bzzoiro_odds)          # bookmaker odds evening
    schedule.every().day.at("08:00").do(run_bzzoiro_ou_predictions)  # O/U predictions daily
    schedule.every().day.at("07:45").do(run_bzzoiro_h2h)           # H2H for upcoming matches
    schedule.every().day.at("20:00").do(run_bzzoiro_point_by_point)  # PBP for matches finished today
    schedule.every().day.at("08:30").do(run_bzzoiro_point_by_point)  # catch overnight/early finishes
    # SEO content generation — after fixtures + predictions are in
    schedule.every().day.at("09:00").do(run_seo_previews)          # generate match previews
    # Daily healthcheck — after the morning's fixtures/predictions/ratings/odds/SEO
    # jobs have all had a chance to run, so it reports on a settled state.
    schedule.every().day.at("09:30").do(run_healthcheck)
    # Weekly player roster sync from api-tennis — enrich existing rows + light discovery
    def _player_sync_weekly():
        try:
            try:
                from pipeline.player_sync import run_full_sync
            except ImportError:
                from player_sync import run_full_sync
            import psycopg2
            conn = psycopg2.connect(
                os.environ.get("DATABASE_URL") or os.environ.get("DATABASE_PUBLIC_URL")
            )
            try:
                run_full_sync(conn, do_tournaments=True)
            finally:
                conn.close()
        except Exception as e:
            log.error(f"weekly player sync failed: {e}")
    schedule.every().sunday.at("03:00").do(_player_sync_weekly)

    log.info(
        "Scheduler running. "
        "Fixtures at 06:00 and 18:00 UTC. "
        "Predictions at 06:30 and 18:30 UTC. "
        "Bzzoiro matches at 06:15 and 18:15 UTC. "
        "Bzzoiro predictions at 06:20 and 18:20 UTC. "
        "Bzzoiro rankings/bios every Monday 07:00/07:05 UTC. "
        "bzzoiro.py fixtures at 06:30/18:30 UTC. "
        "bzzoiro.py live every 60s. "
        "bzzoiro.py rankings daily 07:00. "
        "bzzoiro.py odds at 07:30/19:30 UTC. "
        "bzzoiro.py O/U predictions daily 08:00 UTC. "
        "SEO previews daily 09:00 UTC. "
        "Odds at 07:00, 12:00, and 19:00 UTC. "
        "Ratings every day 01:00 and 08:00 UTC. "
        "Livescore every 5 minutes."
    )

    # ── Loop forever ────────────────────────────────────────────────────────
    while True:
        schedule.run_pending()
        time.sleep(30)
