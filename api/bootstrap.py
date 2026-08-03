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


# v1 systems — kept here so we can deactivate them by code (their settled
# picks history stays in system_picks, but they're hidden from the dashboard).
LEGACY_SYSTEM_CODES = [
    "surface_monster", "form_surge", "hand_advantage", "big_match_player",
    "underdog_value", "rtt_mismatch", "clutch_in_decider", "form_rocket",
]

# v2 systems — multi-signal convergence, designed for 80%+ win rates.
# Keep in lock-step with ml/systems.py SYSTEMS list.
CANONICAL_SYSTEMS = [
    ("class_lock",
     "Class Lock",
     "RTT class gap 20+ points, surface dominance 10+, model probability 75+ — the strongest convergence signal.",
     "🔒", "#DC2626"),
    ("surface_specialist",
     "Surface Specialist",
     "Surface-elite player (82+) faces a sub-average opponent (62-) on this exact surface; surface gap 20+ and model 70+.",
     "🏆", "#3B6D11"),
    ("triple_convergence",
     "Triple Convergence",
     "RTT, surface and form ratings all favour the same player (gaps 15/10/8+). All three independent signals point one way.",
     "🎯", "#9333EA"),
    ("smart_favourite",
     "Smart Favourite",
     "Model has the player at 70+ AND beats market implied probability by 4+ points. Favourite the bookies have under-priced.",
     "💎", "#2563EB"),
]


def seed_systems(conn) -> int:
    """Bake-the-systems-into-Python so we don't depend on the SQL splitter.

    Deactivates v1 legacy systems (preserving their picks history) and
    upserts the v2 convergence systems as is_active=TRUE.
    """
    try:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE systems SET is_active = FALSE WHERE code = ANY(%s)",
                (LEGACY_SYSTEM_CODES,),
            )
    except Exception as e:
        log.warning(f"  deactivate legacy systems: {e}")

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
                        accent_colour = EXCLUDED.accent_colour,
                        is_active = TRUE
                    """,
                    (code, name, desc, icon, colour),
                )
            written += 1
        except Exception as e:
            log.warning(f"  seed system {code}: {e}")
    return written


def apply_schema_migrations() -> dict:
    """Apply schema_additions.sql + predictions_schema.sql, then seed canonical systems. Idempotent.

    DDL safety: ALTER TABLE needs ACCESS EXCLUSIVE lock. If another long-running
    query holds a conflicting lock, Postgres queues the ALTER TABLE — and then
    queues EVERY subsequent SELECT on the same table behind it, poisoning the
    whole connection pool within seconds. We guard against this with a 1.5-second
    lock_timeout on every statement. If the lock can't be acquired in time, the
    statement is logged as 'lock_skipped' and migration continues. On the next
    boot the columns almost certainly already exist (IF NOT EXISTS) so the ALTER
    TABLE is a no-op anyway.
    """
    db_url = _db_url()
    if not db_url:
        log.error("apply_schema_migrations: no DATABASE_URL")
        return {"error": "no database url"}

    migrations_dir = APP_DIR / "api" / "_migrations"
    files = ["schema_additions.sql", "predictions_schema.sql", "matchstat_schema.sql", "bzzoiro_schema.sql"]
    summary: dict = {}

    conn = psycopg2.connect(db_url)
    conn.autocommit = True
    try:
        # Kill any idle-in-transaction connections older than 5 minutes before
        # running migrations. These are the root cause of ALTER TABLE lock cascades:
        # a stuck idle-in-transaction connection holds a RowShare lock, the ALTER
        # TABLE queues for ACCESS EXCLUSIVE, and every subsequent SELECT queues
        # behind the ALTER TABLE. Terminating them first breaks the deadlock chain.
        try:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT pg_terminate_backend(pid)
                    FROM pg_stat_activity
                    WHERE state = 'idle in transaction'
                      AND query_start < NOW() - INTERVAL '5 minutes'
                      AND pid <> pg_backend_pid()
                      AND datname = current_database()
                """)
                n_killed = cur.rowcount
            if n_killed:
                log.info(f"  [migration-preflight] terminated {n_killed} idle-in-transaction connections")
        except Exception as e:
            log.warning(f"  [migration-preflight] idle-in-tx cleanup failed (non-fatal): {e}")

        for fname in files:
            path = migrations_dir / fname
            if not path.exists():
                log.warning(f"  Migration {fname} not found at {path}")
                summary[fname] = "missing"
                continue

            sql = path.read_text()
            ok = errors = skipped = lock_skipped = 0
            for raw in sql.split(";"):
                lines = [l for l in raw.splitlines() if not l.strip().startswith("--")]
                stmt = "\n".join(lines).strip()
                if not stmt:
                    continue
                try:
                    with conn.cursor() as cur:
                        # Short lock timeout so DDL statements (ALTER TABLE) never
                        # queue-poison reads. 1500ms is enough for a quiet DB; on a
                        # loaded DB we'd rather skip and retry next boot.
                        cur.execute("SET lock_timeout = '1500ms'")
                        cur.execute(stmt)
                        cur.execute("SET lock_timeout = 0")
                    ok += 1
                except psycopg2.errors.LockNotAvailable:
                    # Could not acquire lock in time — column almost certainly
                    # already exists (IF NOT EXISTS), so this is safe to skip.
                    log.warning(f"  {fname}: lock_timeout hit — skipping (columns likely already exist)")
                    lock_skipped += 1
                    # Reset connection state after lock error
                    try:
                        conn.rollback()
                    except Exception:
                        pass
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
            summary[fname] = {"applied": ok, "skipped": skipped,
                              "lock_skipped": lock_skipped, "errors": errors}
            log.info(f"  {fname}: applied={ok}, skipped={skipped}, "
                     f"lock_skipped={lock_skipped}, errors={errors}")

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


def run_merge_duplicates() -> dict:
    """
    Merge duplicate player records that the pipeline creates daily.

    Root cause: api-tennis.com ingestion creates new player rows with the
    live api_key. Sackmann/TML players already exist with negative api_keys.
    The ON CONFLICT (api_key) upsert doesn't fire across the two sources, so
    every daily fixture pull re-creates shadow records for top players like
    Sinner, Zverev, etc. This function normalises names and merges shadows into
    their canonical record (most match history wins), moving all FK references.
    """
    import traceback
    db_url = _db_url()
    if not db_url:
        return {"error": "no database url"}
    try:
        from merge_duplicate_players import merge_all  # noqa
    except Exception as e:
        return {"error": f"import: {e}", "traceback": traceback.format_exc().splitlines()[-8:]}
    try:
        conn = psycopg2.connect(db_url)
    except Exception as e:
        return {"error": f"connect: {e}"}
    try:
        result = merge_all(conn, dry_run=False, limit=0)
        merged = result.get("groups_processed", result.get("merged", 0))
        log.info(f"  merge_duplicates: {merged} groups processed")
        # Return a compact summary — full group list can be huge
        return {
            "groups_found":     result.get("groups_found", 0),
            "groups_processed": result.get("groups_processed", 0),
        }
    except Exception as e:
        return {"error": str(e), "type": type(e).__name__,
                "traceback": traceback.format_exc().splitlines()[-12:]}
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
    """
    Run match predictions for the next `days_ahead` days.

    Primary path: LivePredictor (ml.predict) — Elo-led ensemble. Requires
    numpy/pandas which are NOT in the API image, so this will fail there.

    Fallback: RttPredictor (ml.rtt_predictor) — pure-psycopg2, always
    importable on the API service. Runs fill_missing_ratings first so every
    player in an upcoming match gets at least a rank-based RTT score, avoiding
    blanket 50/50 outputs.
    """
    # ── Primary: LivePredictor (Elo + ensemble) ───────────────────────────────
    try:
        from ml.predict import LivePredictor  # needs numpy/pandas
        predictor = LivePredictor()
        predictor.load_models()
        predictor.load_player_history()
        n = predictor.predict_upcoming(days_ahead=days_ahead)
        log.info(f"LivePredictor wrote {n} predictions")
        return {"predictor": "LivePredictor", "predicted": n}
    except ImportError as e:
        log.warning(f"LivePredictor not available ({e}), falling back to RttPredictor")
    except Exception as e:
        log.error(f"LivePredictor failed: {e}")
        return {"error": str(e)}

    # ── Fallback: RttPredictor (psycopg2-only) ────────────────────────────────
    # Ensure every player in an upcoming match has at least a rank-based RTT
    # score so RttPredictor produces meaningful probabilities instead of 50/50.
    db_url = _db_url()
    try:
        from fill_ratings import fill_missing_ratings
        conn = psycopg2.connect(db_url)
        try:
            fill_missing_ratings(conn)
        finally:
            conn.close()
        log.info("fill_missing_ratings complete (pre-RttPredictor)")
    except Exception as e:
        log.warning(f"fill_missing_ratings pre-step failed (non-fatal): {e}")

    try:
        from ml.rtt_predictor import RttPredictor
        predictor = RttPredictor(db_url=db_url)
        try:
            n = predictor.predict_upcoming(days_ahead=days_ahead)
            log.info(f"RttPredictor wrote {n} predictions")
            return {"predictor": "RttPredictor", "predicted": n}
        finally:
            predictor.close()
    except Exception as e:
        log.error(f"RttPredictor failed: {e}")
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
        result = {"settled_predictions": upd_pred,
                  "settled_system_picks": upd_sys,
                  "settled_user_picks": upd_user}
    finally:
        conn.close()

    # Sweep up stale user_picks the standard settler can't reach: matches
    # whose status never made it to 'Finished' (typically because the live
    # match is recorded under a duplicate-player-ID twin). Look up the twin
    # by surname + same date and settle against its winner.
    try:
        result["stuck_picks_resolved"] = _resolve_stuck_picks(min_age_days=1)
    except Exception as e:
        log.error(f"stuck picks sweep failed: {e}")
        result["stuck_picks_resolved"] = {"error": str(e)}

    return result


def _resolve_stuck_picks(min_age_days: int = 1) -> dict:
    """
    Find user_picks still in pending/live for matches whose event_date is
    `min_age_days`+ days in the past, and try to resolve them by finding a
    finished twin match (same date, fuzzy-matched surnames) under a
    different match_id. If no twin exists, void the pick.
    """
    from api.db import query, query_one, get_conn
    stale = query(
        """
        SELECT up.id AS pick_id, up.player_id, up.confidence_stars,
               up.our_odds, up.match_id,
               m.event_date,
               p1.name AS p1_name, p2.name AS p2_name,
               pp.name AS picked_name
        FROM user_picks up
        JOIN matches m  ON m.id = up.match_id
        LEFT JOIN players p1 ON p1.id = m.first_player_id
        LEFT JOIN players p2 ON p2.id = m.second_player_id
        LEFT JOIN players pp ON pp.id = up.player_id
        WHERE up.status IN ('pending','live')
          AND m.event_date < CURRENT_DATE - (%s || ' days')::interval
        LIMIT 200
        """,
        (min_age_days,),
    )

    def _surname(s):
        return (s or "").strip().split()[-1] if s else ""

    settled = 0
    voided  = 0
    for sp in stale:
        s1 = _surname(sp["p1_name"])
        s2 = _surname(sp["p2_name"])
        twin = None
        if s1 and s2:
            twin = query_one(
                """
                SELECT m.id, m.winner, m.first_player_id, m.second_player_id,
                       p1.name AS p1_name, p2.name AS p2_name
                FROM matches m
                JOIN players p1 ON p1.id = m.first_player_id
                JOIN players p2 ON p2.id = m.second_player_id
                WHERE m.event_date = %s
                  AND m.id != %s
                  AND m.winner IN ('First Player','Second Player')
                  AND m.event_status ILIKE 'Finished'
                  AND ((p1.name ILIKE %s AND p2.name ILIKE %s)
                    OR (p1.name ILIKE %s AND p2.name ILIKE %s))
                LIMIT 1
                """,
                (sp["event_date"], sp["match_id"],
                 f"%{s1}%", f"%{s2}%", f"%{s2}%", f"%{s1}%"),
            )
        if twin:
            picked_surname = _surname(sp["picked_name"]).lower()
            picked_is_p1 = (
                picked_surname in (twin["p1_name"] or "").lower()
                and picked_surname not in (twin["p2_name"] or "").lower()
            )
            winner_is_p1 = twin["winner"] == "First Player"
            won = picked_is_p1 == winner_is_p1
            stake = float(sp.get("confidence_stars") or 1)
            new_status = "won" if won else "lost"
            pl = round((float(sp.get("our_odds") or 2.0) - 1) * stake, 2) if won else round(-stake, 2)
            with get_conn() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """UPDATE user_picks
                           SET status = %s, settled_at = NOW(), profit_loss = %s
                           WHERE id = %s AND status IN ('pending','live')""",
                        (new_status, pl, sp["pick_id"]),
                    )
            settled += 1
        else:
            with get_conn() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """UPDATE user_picks
                           SET status = 'void', settled_at = NOW(), profit_loss = 0
                           WHERE id = %s AND status IN ('pending','live')""",
                        (sp["pick_id"],),
                    )
            voided += 1

    return {"considered": len(stale), "settled_via_twin": settled, "voided": voided}


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
    """Run every stage in order. Each is wrapped so a single failure doesn't poison the rest.

    Cluster-wide single-flight: we hold a Postgres advisory lock for the
    duration. If another API container is already running the bootstrap
    (typically because two redeploys happened back-to-back and the previous
    container's bootstrap thread is still going), this one skips. The lock
    is session-scoped and is released when the connection closes — so a
    crashed container can't strand the lock.
    """
    # Lock key chosen arbitrarily but stable. Any 64-bit signed int works.
    BOOTSTRAP_LOCK_KEY = 4827361092000  # "rttbootstrap"

    from api.db import get_conn
    lock_conn = None
    got_lock = False
    try:
        # Open a dedicated connection for the lock so it persists for the
        # duration of the bootstrap and isn't returned to the pool mid-flight.
        import psycopg2
        from api.db import DATABASE_URL
        lock_conn = psycopg2.connect(DATABASE_URL, application_name="rtt-bootstrap-lock")
        lock_conn.autocommit = True
        with lock_conn.cursor() as cur:
            cur.execute("SELECT pg_try_advisory_lock(%s)", (BOOTSTRAP_LOCK_KEY,))
            got_lock = bool(cur.fetchone()[0])
        if not got_lock:
            log.info("[bootstrap] another bootstrap already running on this DB — skipping")
            return {"skipped": True, "reason": "another bootstrap already holds the advisory lock"}
    except Exception as e:
        log.warning(f"[bootstrap] could not acquire advisory lock ({e}); proceeding without it")

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

    log.info("[bootstrap] 2c/7 merge duplicate players…")
    try:
        results["merge_duplicates"] = run_merge_duplicates()
    except Exception as e:
        log.error(f"  merge duplicates failed: {e}")
        results["merge_duplicates"] = {"error": str(e)}

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

    # Release the advisory lock so the next bootstrap can acquire it.
    # Closing the connection is enough (session-scoped lock auto-releases),
    # but we're explicit so the intent is obvious.
    if lock_conn is not None:
        try:
            if got_lock:
                with lock_conn.cursor() as cur:
                    cur.execute("SELECT pg_advisory_unlock(%s)", (BOOTSTRAP_LOCK_KEY,))
        except Exception as e:
            log.warning(f"[bootstrap] could not release advisory lock: {e}")
        finally:
            try:
                lock_conn.close()
            except Exception:
                pass

    return results
