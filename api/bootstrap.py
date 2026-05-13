"""
ratethat.tennis API — self-bootstrap.

Runs the heavy lifting that normally lives in the pipeline service, but from
the API service. This is a safety net so the site keeps working when the
pipeline service has issues (build errors, didn't redeploy, etc.).

Stages:
  1. apply_schema_migrations      — run schema_additions + predictions_schema SQL
  2. backfill_surfaces            — Wuxi/Istanbul/Rome → known surfaces
  3. fill_missing_ratings         — every active player gets at least an estimated RTT
  4. compute_hand_splits          — per-player record vs each opponent hand
  5. predict_upcoming             — RTT-based probabilities for next 7 days
  6. settle_predictions           — mark finished matches correct/incorrect
  7. evaluate_systems             — Surface Monster / Form Surge / etc. picks

All stages are idempotent so calling this on every API boot is safe.
"""

from __future__ import annotations

import logging
import os
import sys
from pathlib import Path

import psycopg2

log = logging.getLogger("api.bootstrap")

# Ensure /app is on sys.path so `import surface_backfill` etc. works
APP_DIR = Path(__file__).resolve().parent.parent  # /app
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))


def _db_url() -> str:
    return (
        os.environ.get("DATABASE_URL")
        or os.environ.get("DATABASE_PUBLIC_URL")
        or ""
    ).strip()


# v1 systems removed 2026-05-13 — all underperforming.
# New systems will be added here once backtested and validated.
CANONICAL_SYSTEMS: list = []


def seed_systems(conn) -> int:
    """Bake-the-systems-into-Python so we don't depend on the SQL splitter."""
    written = 0
    for code, name, desc, icon, colour in CANONICAL_SYSTEMS:
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO systems (code, name, description, icon, accent_colour, is_active)
                    VALUES (%s, %s, %s, %s, %s, TRUE)
                    ON CONFLICT (code) DO UPDATE SET
                        name = EXCLUDED.name,
                        description = EXCLUDED.description,
                        icon = EXCLUDED.icon,
                        accent_colour = EXCLUDED.accent_colour
                    """,
                    (code, name, desc, icon, colour),
                )
            written += 1
        except Exception as e:
            log.warning(f"  seed system {code}: {e}")
    return written


def apply_schema_migrations() -> dict:
    """Apply schema_additions.sql + predictions_schema.sql, then seed canonical systems. Idempotent."""
    db_url = _db_url()
    if not db_url:
        log.error("apply_schema_migrations: no DATABASE_URL")
        return {"error": "no database url"}

    migrations_dir = APP_DIR / "api" / "_migrations"
    files = ["schema_additions.sql", "predictions_schema.sql", "matchstat_schema.sql"]
    summary: dict = {}

    conn = psycopg2.connect(db_url)
    conn.autocommit = True
    try:
        for fname in files:
            path = migrations_dir / fname
            if not path.exists():
                log.warning(f"  Migration {fname} not found at {path}")
                summary[fname] = "missing"
                continue

            sql = path.read_text()
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
                        log.warning(f"  {fname}: {e}")
                        errors += 1
            summary[fname] = {"applied": ok, "skipped": skipped, "errors": errors}
            log.info(f"  {fname}: applied={ok}, skipped={skipped}, errors={errors}")

        # Always seed/update the canonical systems via Python — independent of SQL parsing.
        try:
            n = seed_systems(conn)
            summary["systems_seeded"] = n
            log.info(f"  Systems seeded: {n}")
        except Exception as e:
            log.warning(f"  systems seed failed: {e}")
            summary["systems_seeded"] = f"error: {e}"
    finally:
        conn.close()

    return summary


def run_surface_backfill() -> dict:
    db_url = _db_url()
    if not db_url:
        return {"error": "no database url"}
    try:
        from surface_backfill import backfill_surfaces  # noqa
    except Exception as e:
        log.error(f"surface_backfill import failed: {e}")
        return {"error": f"import: {e}"}
    conn = psycopg2.connect(db_url)
    try:
        n = backfill_surfaces(conn)
        return {"updated": n}
    finally:
        conn.close()


def run_player_sync(do_tournaments: bool = False) -> dict:
    """Enrich existing players (phase 1) + optionally discover new ones (phase 2)."""
    import traceback
    db_url = _db_url()
    if not db_url:
        return {"error": "no database url"}
    try:
        from player_sync import run_full_sync  # noqa
    except Exception as e:
        return {"error": f"import: {e}", "traceback": traceback.format_exc().splitlines()[-8:]}
    try:
        conn = psycopg2.connect(db_url)
    except Exception as e:
        return {"error": f"connect: {e}"}
    try:
        return run_full_sync(conn, do_tournaments=do_tournaments)
    except Exception as e:
        return {"error": str(e), "type": type(e).__name__,
                "traceback": traceback.format_exc().splitlines()[-12:]}
    finally:
        try:
            conn.close()
        except Exception:
            pass


def run_hand_backfill() -> dict:
    """Fill player.hand from sa_players for any production player missing it."""
    import traceback
    db_url = _db_url()
    if not db_url:
        return {"error": "no database url"}
    try:
        from hand_backfill import backfill_hands  # noqa
    except Exception as e:
        return {"error": f"import: {e}", "traceback": traceback.format_exc().splitlines()[-8:]}
    try:
        conn = psycopg2.connect(db_url)
    except Exception as e:
        return {"error": f"connect: {e}"}
    try:
        n = backfill_hands(conn)
        return {"updated": n}
    except Exception as e:
        return {"error": str(e), "type": type(e).__name__,
                "traceback": traceback.format_exc().splitlines()[-12:]}
    finally:
        try:
            conn.close()
        except Exception:
            pass


def run_point_analysis() -> dict:
    """Compute service hold %, break %, BP save/conversion, tiebreak win % per player."""
    import traceback
    db_url = _db_url()
    if not db_url:
        return {"error": "no database url"}
    try:
        from point_analysis import run as _run, backfill_all  # noqa
    except Exception as e:
        return {"error": f"import: {e}", "traceback": traceback.format_exc().splitlines()[-8:]}
    try:
        conn = psycopg2.connect(db_url)
    except Exception as e:
        return {"error": f"connect: {e}"}
    try:
        result = _run(conn)
        # _run now returns a dict with breakdown; older code returned an int
        if isinstance(result, dict):
            run_summary = result
        else:
            run_summary = {"written": result}
        # After computing aggregates, backfill the sequential metrics
        # (longest game run + deuce-as-returner) — both done in pure SQL.
        backfill_summary = backfill_all(conn)
        return {"run": run_summary, "backfill": backfill_summary}
    except Exception as e:
        return {"error": str(e), "type": type(e).__name__,
                "traceback": traceback.format_exc().splitlines()[-12:]}
    finally:
        try:
            conn.close()
        except Exception:
            pass


def run_point_backfill_only() -> dict:
    """Just run the sequential-metrics backfill (longest run + deuce return %)."""
    import traceback
    db_url = _db_url()
    if not db_url:
        return {"error": "no database url"}
    try:
        from point_analysis import backfill_all  # noqa
    except Exception as e:
        return {"error": f"import: {e}", "traceback": traceback.format_exc().splitlines()[-8:]}
    try:
        conn = psycopg2.connect(db_url)
    except Exception as e:
        return {"error": f"connect: {e}"}
    try:
        return backfill_all(conn)
    except Exception as e:
        return {"error": str(e), "type": type(e).__name__,
                "traceback": traceback.format_exc().splitlines()[-12:]}
    finally:
        try:
            conn.close()
        except Exception:
            pass


def run_form_score() -> dict:
    """Compute the richer form_score for every player."""
    import traceback
    db_url = _db_url()
    if not db_url:
        return {"error": "no database url"}
    try:
        from form_score import update_all_form_scores  # noqa
    except Exception as e:
        return {"error": f"import: {e}", "traceback": traceback.format_exc().splitlines()[-8:]}
    try:
        conn = psycopg2.connect(db_url)
    except Exception as e:
        return {"error": f"connect: {e}"}
    try:
        n = update_all_form_scores(conn)
        return {"updated": n}
    except Exception as e:
        return {"error": str(e), "type": type(e).__name__,
                "traceback": traceback.format_exc().splitlines()[-12:]}
    finally:
        try:
            conn.close()
        except Exception:
            pass


def run_fill_ratings() -> dict:
    import traceback
    db_url = _db_url()
    if not db_url:
        return {"error": "no database url"}
    try:
        from fill_ratings import fill_missing_ratings  # noqa
    except Exception as e:
        log.error(f"fill_ratings import failed: {e}")
        return {"error": f"import: {e}", "traceback": traceback.format_exc().splitlines()[-8:]}
    try:
        conn = psycopg2.connect(db_url)
    except Exception as e:
        return {"error": f"connect: {e}"}
    try:
        n = fill_missing_ratings(conn)
        return {"filled": n}
    except Exception as e:
        log.error(f"fill_missing_ratings raised: {e}")
        return {
            "error": str(e),
            "type": type(e).__name__,
            "traceback": traceback.format_exc().splitlines()[-12:],
        }
    finally:
        try:
            conn.close()
        except Exception:
            pass


def run_hand_splits() -> dict:
    db_url = _db_url()
    if not db_url:
        return {"error": "no database url"}
    try:
        from player_splits import compute_hand_splits  # noqa
    except Exception as e:
        log.error(f"hand splits import failed: {e}")
        return {"error": f"import: {e}"}
    conn = psycopg2.connect(db_url)
    try:
        n = compute_hand_splits(conn)
        return {"rows": n}
    finally:
        conn.close()


def run_rtt_predictions(days_ahead: int = 7) -> dict:
    try:
        from ml.predict import LivePredictor  # noqa
    except Exception as e:
        log.error(f"ml.predict import failed: {e}")
        return {"error": f"import: {e}"}
    predictor = LivePredictor()
    try:
        predictor.load_models()
        predictor.load_player_history()
        n = predictor.predict_upcoming(days_ahead=days_ahead)
        return {"predicted": n}
    except Exception as e:
        log.error(f"LivePredictor failed: {e}")
        return {"error": str(e)}


def run_settle() -> dict:
    db_url = _db_url()
    if not db_url:
        return {"error": "no database url"}
    try:
        from settle_predictions import settle_predictions  # noqa
    except Exception as e:
        log.error(f"settle import failed: {e}")
        return {"error": f"import: {e}"}
    conn = psycopg2.connect(db_url)
    try:
        upd_pred, upd_sys, upd_user = settle_predictions(conn)
        return {"settled_predictions": upd_pred, "settled_system_picks": upd_sys, "settled_user_picks": upd_user}
    finally:
        conn.close()


def run_systems(days_ahead: int = 7) -> dict:
    try:
        from ml.systems import SystemsEngine  # noqa
    except Exception as e:
        log.error(f"systems import failed: {e}")
        return {"error": f"import: {e}"}
    eng = SystemsEngine()
    try:
        n = eng.evaluate_upcoming(days_ahead=days_ahead)
        return {"picks": n}
    finally:
        eng.close()


def full_bootstrap() -> dict:
    """Run every stage in order. Each is wrapped so a single failure doesn't poison the rest."""
    results: dict = {}

    log.info("[bootstrap] 1/7 schema migrations…")
    try:
        results["schema"] = apply_schema_migrations()
    except Exception as e:
        log.error(f"  schema failed: {e}")
        results["schema"] = {"error": str(e)}

    log.info("[bootstrap] 2/7 surface backfill…")
    try:
        results["surface_backfill"] = run_surface_backfill()
    except Exception as e:
        log.error(f"  surface backfill failed: {e}")
        results["surface_backfill"] = {"error": str(e)}

    log.info("[bootstrap] 2b/7 hand backfill…")
    try:
        results["hand_backfill"] = run_hand_backfill()
    except Exception as e:
        log.error(f"  hand backfill failed: {e}")
        results["hand_backfill"] = {"error": str(e)}

    log.info("[bootstrap] 3/7 fill missing ratings…")
    try:
        results["fill_ratings"] = run_fill_ratings()
    except Exception as e:
        log.error(f"  fill ratings failed: {e}")
        results["fill_ratings"] = {"error": str(e)}

    log.info("[bootstrap] 4/7 hand splits…")
    try:
        results["hand_splits"] = run_hand_splits()
    except Exception as e:
        log.error(f"  hand splits failed: {e}")
        results["hand_splits"] = {"error": str(e)}

    log.info("[bootstrap] 4b/7 richer form_score…")
    try:
        results["form_score"] = run_form_score()
    except Exception as e:
        log.error(f"  form score failed: {e}")
        results["form_score"] = {"error": str(e)}

    log.info("[bootstrap] 4c/7 point analysis (hold %, break %, BP save…)…")
    try:
        results["point_analysis"] = run_point_analysis()
    except Exception as e:
        log.error(f"  point analysis failed: {e}")
        results["point_analysis"] = {"error": str(e)}

    log.info("[bootstrap] 5/7 RTT predictions…")
    try:
        results["predictions"] = run_rtt_predictions(days_ahead=7)
    except Exception as e:
        log.error(f"  predictions failed: {e}")
        results["predictions"] = {"error": str(e)}

    log.info("[bootstrap] 6/7 settle…")
    try:
        results["settle"] = run_settle()
    except Exception as e:
        log.error(f"  settle failed: {e}")
        results["settle"] = {"error": str(e)}

    log.info("[bootstrap] 7/7 systems…")
    try:
        results["systems"] = run_systems(days_ahead=7)
    except Exception as e:
        log.error(f"  systems failed: {e}")
        results["systems"] = {"error": str(e)}

    log.info("[bootstrap] complete")
    return results
