#!/usr/bin/env python3
"""
ratethat.tennis — Pipeline Scheduler

Runs continuously on Railway, keeping the database up-to-date automatically:
  - daily_fixtures  : 06:00 and 18:00 UTC every day (fetches today + next 2 days)
  - predictions     : 06:30 and 18:30 UTC (ML win probabilities, runs after fixtures)
  - livescore       : every 5 minutes (live match updates during play)
  - odds            : 07:00 and 19:00 UTC (bookmaker odds via The Odds API)
  - ratings         : daily at 01:00 UTC (RTT player ratings — all active players)
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


def run_accuracy_report():
    """
    Compute and log rolling prediction accuracy from model_predictions table.
    Runs daily at 23:00 UTC. Logs accuracy over last 7d, 30d, and all time.
    """
    log.info("Running: prediction accuracy report...")
    try:
        import psycopg2
        import psycopg2.extras
        db_url = os.environ.get("DATABASE_URL") or os.environ.get("DATABASE_PUBLIC_URL")
        conn = psycopg2.connect(db_url)
        conn.cursor_factory = psycopg2.extras.RealDictCursor
        with conn.cursor() as cur:
            cur.execute("""
                SELECT
                    COUNT(*) FILTER (WHERE settled_at IS NOT NULL) AS total_settled,
                    ROUND(100.0 * SUM(CASE WHEN is_correct AND settled_at IS NOT NULL THEN 1 ELSE 0 END)::numeric
                          / NULLIF(COUNT(*) FILTER (WHERE settled_at IS NOT NULL), 0), 2) AS all_time_pct,
                    COUNT(*) FILTER (WHERE settled_at >= CURRENT_DATE - 30) AS settled_30d,
                    ROUND(100.0 * SUM(CASE WHEN is_correct AND settled_at >= CURRENT_DATE - 30 THEN 1 ELSE 0 END)::numeric
                          / NULLIF(COUNT(*) FILTER (WHERE settled_at >= CURRENT_DATE - 30), 0), 2) AS pct_30d,
                    COUNT(*) FILTER (WHERE settled_at >= CURRENT_DATE - 7) AS settled_7d,
                    ROUND(100.0 * SUM(CASE WHEN is_correct AND settled_at >= CURRENT_DATE - 7 THEN 1 ELSE 0 END)::numeric
                          / NULLIF(COUNT(*) FILTER (WHERE settled_at >= CURRENT_DATE - 7), 0), 2) AS pct_7d,
                    model_version
                FROM model_predictions
                GROUP BY model_version
                ORDER BY COUNT(*) FILTER (WHERE settled_at IS NOT NULL) DESC
            """)
            rows = cur.fetchall()
        conn.close()
        if not rows:
            log.info("  No settled predictions yet")
            return
        for r in rows:
            log.info(
                f"  [{r['model_version']}] "
                f"All-time: {r['all_time_pct']}% ({r['total_settled']} matches) | "
                f"30d: {r['pct_30d']}% ({r['settled_30d']}) | "
                f"7d: {r['pct_7d']}% ({r['settled_7d']})"
            )
    except Exception as e:
        log.error(f"accuracy report failed: {e}")


def run_weekly_retrain():
    """
    Weekly model retrain from the expanded feature matrix (sa_matches + live data).
    Runs Sunday at 02:00 UTC. Only promotes new model if AUC improves.
    """
    log.info("Weekly retrain: starting...")
    try:
        import json
        from pathlib import Path
        from ml.features import FeatureBuilder
        from ml.train import (
            make_xgboost, make_lightgbm, EnsembleModel,
            CORE_FEATURES, MODELS_DIR, RESULTS_DIR,
        )
        import pickle
        import numpy as np
        import pandas as pd
        from sklearn.metrics import roc_auc_score
        from sklearn.impute import SimpleImputer

        db_url = os.environ.get("DATABASE_URL") or os.environ.get("DATABASE_PUBLIC_URL")

        # 1) Build fresh feature matrix
        log.info("  Building feature matrix...")
        fb = FeatureBuilder(db_url=db_url)
        fb.load(min_year=2010)
        X, y, meta = fb.build()

        # Only train on features the model knows about
        feature_cols = [c for c in CORE_FEATURES if c in X.columns]
        X_train = X[feature_cols]

        # 2) Simple 80/20 chronological split for validation
        n = len(X_train)
        split = int(n * 0.8)
        X_tr, X_va = X_train.iloc[:split], X_train.iloc[split:]
        y_tr, y_va = y.iloc[:split], y.iloc[split:]

        # 3) Train ensemble
        log.info(f"  Training on {len(X_tr):,} matches, validating on {len(X_va):,}...")
        imputer = SimpleImputer(strategy='median')
        X_tr_imp = pd.DataFrame(imputer.fit_transform(X_tr), columns=X_tr.columns)
        X_va_imp = pd.DataFrame(imputer.transform(X_va), columns=X_va.columns)

        models = []
        xgb_m = make_xgboost()
        if xgb_m:
            xgb_m.fit(X_tr_imp, y_tr)
            models.append(xgb_m)
        try:
            lgb_m = make_lightgbm()
            if lgb_m:
                lgb_m.fit(X_tr_imp, y_tr)
                models.append(lgb_m)
        except Exception:
            pass
        if not models:
            log.warning("  No tree models available — skipping retrain")
            return

        new_ensemble = EnsembleModel(models)
        new_auc = roc_auc_score(y_va, new_ensemble.predict_proba(X_va_imp)[:, 1])
        log.info(f"  New model AUC on validation: {new_auc:.4f}")

        # 4) Compare vs current champion
        champion_path = MODELS_DIR / "overall_ensemble.pkl"
        promote = True
        if champion_path.exists():
            try:
                with open(champion_path, 'rb') as f:
                    import pickle as _pk
                    old_model = _pk.load(f)
                old_auc = roc_auc_score(y_va, old_model.predict_proba(X_va_imp)[:, 1])
                log.info(f"  Current champion AUC: {old_auc:.4f}")
                if new_auc <= old_auc:
                    log.info("  New model did not improve — keeping champion")
                    promote = False
            except Exception as e:
                log.warning(f"  Could not load champion for comparison: {e} — promoting anyway")

        if promote:
            MODELS_DIR.mkdir(parents=True, exist_ok=True)
            with open(champion_path, 'wb') as f:
                pickle.dump(new_ensemble, f)
            # Save accuracy record
            record = {
                'date': str(pd.Timestamp.now().date()),
                'auc': round(new_auc, 4),
                'n_train': len(X_tr),
                'n_val': len(X_va),
                'promoted': True,
            }
            records_path = RESULTS_DIR / "retrain_history.json"
            try:
                existing = json.loads(records_path.read_text()) if records_path.exists() else []
            except Exception:
                existing = []
            existing.append(record)
            RESULTS_DIR.mkdir(parents=True, exist_ok=True)
            records_path.write_text(json.dumps(existing, indent=2))
            log.info(f"  Promoted new model (AUC {new_auc:.4f}) — saved to {champion_path}")
        else:
            log.info("  Retrain complete — champion unchanged")

    except Exception as e:
        log.error(f"weekly retrain failed: {e}")
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


def run_fixture_pipeline():
    """
    The full fixture→prediction→intel-ready pipeline in a single call.

    Sequence:
      1. Fetch fixtures — identify any NEW matches inserted this run
      2. Backfill surfaces + fill missing ratings (so new players have RTT)
      3. Run predictions for all upcoming matches (catches new + any gaps)
      4. Log the chain for each new match: found → predicted → needs intel
      5. Settle finished matches

    This replaces the old staggered cron approach (fixtures @ :00, surface
    backfill @ :15, fill ratings @ :20, predictions @ :30) which left a
    30-minute window where new matches had no prediction.
    """
    import psycopg2
    import psycopg2.extras
    db_url = os.environ.get("DATABASE_URL") or os.environ.get("DATABASE_PUBLIC_URL")

    log.info("Pipeline: fixtures → predictions starting")

    # ── 1. Fixtures ──────────────────────────────────────────────────────────
    new_match_ids = []
    try:
        result = run_job("daily_fixtures")
        new_match_ids = (result or {}).get("new_match_ids", [])
        if new_match_ids:
            log.info(f"  ✦ {len(new_match_ids)} new match(es) found: {new_match_ids}")
        else:
            updated = (result or {}).get("updated", 0)
            log.info(f"  No new matches this run ({updated} updated)")
    except Exception as e:
        log.error(f"  fixtures failed: {e}")

    # ── 2. Surface backfill + fill missing ratings ───────────────────────────
    try:
        backfill_surfaces = _import_surface_backfill()
        conn = psycopg2.connect(db_url)
        try:
            backfill_surfaces(conn)
        finally:
            conn.close()
    except Exception as e:
        log.error(f"  surface backfill failed: {e}")

    try:
        fill_missing_ratings = _import_fill_ratings()
        conn = psycopg2.connect(db_url)
        try:
            fill_missing_ratings(conn)
        finally:
            conn.close()
    except Exception as e:
        log.error(f"  fill missing ratings failed: {e}")

    # ── 3. Predictions ───────────────────────────────────────────────────────
    run_predictions()

    # ── 4. Log the chain for each new match ──────────────────────────────────
    if new_match_ids:
        try:
            conn = psycopg2.connect(db_url)
            conn.cursor_factory = psycopg2.extras.RealDictCursor
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT
                        m.id,
                        p1.name  AS p1_name,
                        p2.name  AS p2_name,
                        t.name   AS tournament,
                        m.event_date,
                        mp.prob_first_player,
                        mp.prob_second_player,
                        mp.confidence,
                        mp.p1_intel
                    FROM matches m
                    JOIN players p1 ON p1.id = m.first_player_id
                    JOIN players p2 ON p2.id = m.second_player_id
                    LEFT JOIN tournaments t ON t.id = m.tournament_id
                    LEFT JOIN model_predictions mp ON mp.match_id = m.id
                    WHERE m.id = ANY(%s)
                    ORDER BY m.event_date, m.id
                """, (new_match_ids,))
                rows = cur.fetchall()
            conn.close()

            log.info("  ── New match pipeline status ──────────────────────────────────")
            for r in rows:
                p1       = r['p1_name'] or '?'
                p2       = r['p2_name'] or '?'
                tourn    = r['tournament'] or '?'
                date_str = str(r['event_date'])
                prob1    = r['prob_first_player']
                prob2    = r['prob_second_player']
                conf     = r['confidence'] or '?'
                has_intel = bool(r['p1_intel'])

                pred_str  = (f"predicted {prob1*100:.0f}/{prob2*100:.0f}% [{conf}]"
                             if prob1 is not None else "⚠ NO PREDICTION — check logs")
                intel_str = "intel ✓" if has_intel else "intel ✗ (needs Cowork run)"
                log.info(
                    f"  match {r['id']} | {tourn} {date_str} | "
                    f"{p1} vs {p2} | {pred_str} | {intel_str}"
                )
            log.info("  ───────────────────────────────────────────────────────────────")
        except Exception as e:
            log.error(f"  chain logging failed: {e}")

    # ── 5. Settle finished matches ───────────────────────────────────────────
    try:
        settle_predictions = _import_settle()
        conn = psycopg2.connect(db_url)
        try:
            settle_predictions(conn)
        finally:
            conn.close()
    except Exception as e:
        log.error(f"  settle failed: {e}")

    log.info("Pipeline: fixtures → predictions complete")


def run_predict_unpredicted():
    """
    Lightweight pass after the odds pull: predict any upcoming matches that
    have bookmaker odds but still no prediction. Catches matches that arrived
    between the last fixture pipeline run and the odds pull.
    """
    import psycopg2
    import psycopg2.extras
    db_url = os.environ.get("DATABASE_URL") or os.environ.get("DATABASE_PUBLIC_URL")

    try:
        conn = psycopg2.connect(db_url)
        conn.cursor_factory = psycopg2.extras.RealDictCursor
        with conn.cursor() as cur:
            cur.execute("""
                SELECT m.id
                FROM matches m
                JOIN bookmaker_odds bo ON bo.match_id = m.id
                LEFT JOIN model_predictions mp ON mp.match_id = m.id
                WHERE m.event_date >= CURRENT_DATE
                  AND m.event_status NOT IN ('Finished', 'Cancelled', 'Retired')
                  AND (mp.match_id IS NULL OR mp.prob_first_player IS NULL)
                GROUP BY m.id
            """)
            unpredicted = [r['id'] for r in cur.fetchall()]
        conn.close()
    except Exception as e:
        log.error(f"predict_unpredicted: query failed: {e}")
        return

    if not unpredicted:
        return

    log.info(f"predict_unpredicted: ✦ {len(unpredicted)} match(es) with odds but no prediction: {unpredicted}")
    run_predictions()


# ─────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────

if __name__ == "__main__":
    log.info("ratethat.tennis pipeline scheduler starting...")

    # ── Self-healing schema migrations (idempotent, safe to re-run) ─────────
    apply_schema_migrations()

    # ── Startup jobs in DEPENDENCY ORDER ─────────────────────────────────────
    # 1. Schema (above)
    # 2. Tournament/event type sync — populate lookup tables first
    log.info("Running startup: event type + tournament sync...")
    run_startup_sync()

    # 3. Ratings — needs sa_matches history; done before fixture pipeline so
    #    new players in today's fixtures get a proper RTT immediately.
    log.info("Running startup: RTT ratings computation...")
    run_ratings()

    # 4. Fixture pipeline — fetches fixtures, surfaces, fill ratings, predicts,
    #    logs the full new-match chain, settles finished matches.
    log.info("Running startup: fixture pipeline (fixtures → predictions)...")
    run_fixture_pipeline()

    # 5. Odds (independent — can run any time after fixtures)
    log.info("Running startup: odds...")
    run_odds()
    run_predict_unpredicted()

    # ── Scheduled jobs ──────────────────────────────────────────────────────
    #
    # PIPELINE DESIGN: fixture pull and predictions are a single chain, not
    # separate cron jobs. run_fixture_pipeline() fetches fixtures, identifies
    # new match IDs, immediately predicts them, and logs the full chain.
    # This eliminates the gap where a match sits unpredicted between the
    # fixtures pull and the old staggered prediction cron 30 min later.
    #
    # After odds arrive, run_predict_unpredicted() catches any match that
    # has odds but still no prediction (e.g. added between pipeline runs).
    #
    schedule.every().day.at("06:00").do(run_fixture_pipeline)  # morning: fixtures → predictions
    schedule.every().day.at("18:00").do(run_fixture_pipeline)  # evening: fixtures → predictions
    # Surface backfill every 30 minutes — ensures surface data is never stale
    # even if the fixture pipeline temporarily overwrites known surfaces.
    def _surface_backfill_rolling():
        try:
            backfill_surfaces = _import_surface_backfill()
            if backfill_surfaces:
                import psycopg2
                conn = psycopg2.connect(
                    os.environ.get("DATABASE_URL") or os.environ.get("DATABASE_PUBLIC_URL")
                )
                try:
                    n = backfill_surfaces(conn)
                    if n:
                        log.info(f"[surface-backfill rolling] fixed {n} tournaments")
                finally:
                    conn.close()
        except Exception as e:
            log.error(f"surface backfill rolling failed: {e}")
    schedule.every(30).minutes.do(_surface_backfill_rolling)
    schedule.every(5).minutes.do(run_livescore)                # live scores every 5 min
    # Settle predictions every 15 minutes — keeps the tracker live as matches finish
    def _settle_only():
        try:
            import psycopg2
            settle_predictions = _import_settle()
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
    # Odds pull — followed immediately by a safety net prediction pass
    schedule.every().day.at("07:00").do(run_odds)              # morning odds
    schedule.every().day.at("07:05").do(run_predict_unpredicted)  # catch anything odds revealed
    schedule.every().day.at("19:00").do(run_odds)              # evening odds
    schedule.every().day.at("19:05").do(run_predict_unpredicted)  # same safety net
    schedule.every().day.at("01:00").do(run_ratings)           # nightly ratings refresh
    # Weekly player roster sync
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
    schedule.every().day.at("23:00").do(run_accuracy_report)   # daily accuracy report
    schedule.every().sunday.at("02:00").do(run_weekly_retrain) # weekly retrain

    log.info(
        "Scheduler running. "
        "Fixture pipeline (fixtures+predictions) at 06:00 and 18:00 UTC. "
        "Odds at 07:00 and 19:00 UTC + predict-unpredicted safety pass at :05. "
        "Ratings nightly at 01:00 UTC. "
        "Livescore every 5 min. Settle every 15 min."
    )

    # ── Loop forever ────────────────────────────────────────────────────────
    while True:
        schedule.run_pending()
        time.sleep(30)
