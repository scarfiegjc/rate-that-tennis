#!/usr/bin/env python3
"""
ratethat.tennis — Pipeline Scheduler

Runs continuously on Railway, keeping the database up-to-date automatically:
  - daily_fixtures  : 06:00 and 18:00 UTC every day (fetches today + next 2 days)
  - predictions     : 06:30 and 18:30 UTC (ML win probabilities, runs after fixtures)
  - livescore       : every 5 minutes (live match updates during play)
  - odds            : 07:00 and 19:00 UTC (bookmaker odds via The Odds API)
  - ratings         : Sundays at 02:00 UTC (RTT player ratings — all active players)
  - sync_events     : once on startup (event types + tournaments)

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
    log.info("Scheduled: odds sync")
    try:
        from odds import run as odds_run
        odds_run()
    except Exception as e:
        log.error(f"odds sync failed: {e}")


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


def run_predictions():
    """
    Full predictions pipeline (RTT v1):
      1. Refresh hand-vs-hand splits
      2. Compute RTT-based win probabilities for next 7 days
      3. Settle finished matches (last 14 days)
      4. Evaluate systems (Surface Monster, Form Surge, …)

    All four stages use only psycopg2 + stdlib so they're Railway-safe.
    Each stage is wrapped so a single failure doesn't poison the rest.
    """
    log.info("Scheduled: predictions (RTT v1)")
    import psycopg2

    db_url = os.environ.get("DATABASE_URL") or os.environ.get("DATABASE_PUBLIC_URL")

    # 1) Hand splits
    try:
        compute_hand_splits = _import_compute_hand_splits()
        conn = psycopg2.connect(db_url)
        try:
            compute_hand_splits(conn)
        finally:
            conn.close()
    except Exception as e:
        log.error(f"hand splits failed: {e}")

    # 2) RTT predictions
    try:
        from ml.rtt_predictor import RttPredictor
        rp = RttPredictor()
        try:
            rp.predict_upcoming(days_ahead=7)
        finally:
            rp.close()
    except Exception as e:
        log.error(f"rtt predictions failed: {e}")
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


def run_ratings():
    """
    Compute player ratings (Elo-based, 0-100) for all players.
    Uses auto_data (psycopg2-only, no ml/ dependencies).
    Writes to player_ratings and player_ratings_history tables.
    Runs on startup and weekly (Sundays 02:00 UTC).
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

    migrations = ["schema_additions.sql", "predictions_schema.sql"]

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

    # ── Surface backfill — Wuxi etc. should never be "Unknown" ──────────────
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

    # ── Startup jobs (run immediately on boot) ──────────────────────────────
    log.info("Running startup: daily fixtures...")
    run_daily_fixtures()   # populate DB immediately so the site has data

    log.info("Running startup: event type + tournament sync...")
    run_startup_sync()     # ensure lookup tables are populated

    log.info("Running startup: RTT ratings computation...")
    run_ratings()          # populate player_ratings for all active players

    log.info("Running startup: predictions...")
    run_predictions()      # generate win probabilities for all upcoming matches

    log.info("Running startup: odds...")
    run_odds()             # fetch bookmaker odds if key is available

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
    schedule.every().day.at("06:30").do(run_predictions)      # predictions after morning fixtures
    schedule.every().day.at("18:00").do(run_daily_fixtures)   # 18:00 UTC
    schedule.every().day.at("18:15").do(_surface_backfill_only)
    schedule.every().day.at("18:30").do(run_predictions)      # predictions after evening fixtures
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
    schedule.every().day.at("19:00").do(run_odds)             # evening refresh
    schedule.every().sunday.at("02:00").do(run_ratings)       # weekly ratings refresh

    log.info(
        "Scheduler running. "
        "Fixtures at 06:00 and 18:00 UTC. "
        "Predictions at 06:30 and 18:30 UTC. "
        "Odds at 07:00 and 19:00 UTC. "
        "Ratings every Sunday 02:00 UTC. "
        "Livescore every 5 minutes."
    )

    # ── Loop forever ────────────────────────────────────────────────────────
    while True:
        schedule.run_pending()
        time.sleep(30)
