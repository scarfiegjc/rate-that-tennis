#!/usr/bin/env python3
"""
ratethat.tennis — automated daily healthcheck panel.

api/main.py's /admin/healthcheck endpoint has imported from this module
(`pipeline.healthcheck` / `healthcheck`) for months, but the module itself
never existed anywhere in the repository — every hit 500'd with
ModuleNotFoundError: No module named 'healthcheck'. This is the real
implementation, added during the 2026-08 data-feed audit.

What it checks (each a CheckResult):
    - matches_today            — does today have any match rows at all?
    - predictions_coverage     — % of upcoming (next 2 days) matches with a
                                  model_predictions row
    - bzzoiro_link_coverage    — % of upcoming matches with bzzoiro_id set
                                  (directly measures the 2026-08 match-merge fix)
    - ratings_freshness        — is player_ratings_history snapshotted today/yesterday?
    - seo_preview_coverage     — % of upcoming matches with a non-null seo_preview
    - odds_coverage            — % of upcoming matches with bookmaker odds
    - live_data_freshness      — are currently-live matches' live_data recent?
    - point_by_point_coverage  — % of yesterday's finished matches with PBP stored

Auto-repair (apply_auto_repair) only attempts safe, idempotent re-syncs for
checks where a repair is well-defined; everything else is report-only.

Usage (standalone):
    python -m pipeline.healthcheck
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from datetime import date, timedelta
from typing import List, Optional

import psycopg2
import psycopg2.extras

log = logging.getLogger("rtt-healthcheck")
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")


# ─────────────────────────────────────────────────────────────────────────────
# Result type
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class CheckResult:
    name: str
    severity: str            # "CRITICAL" | "WARNING"
    status: str              # "PASS" | "FAIL"
    value: Optional[object] = None
    threshold: Optional[object] = None
    message: str = ""
    auto_repaired: bool = False
    repair_message: str = ""


# ─────────────────────────────────────────────────────────────────────────────
# Connection helpers
# ─────────────────────────────────────────────────────────────────────────────

def _db_url() -> Optional[str]:
    return os.environ.get("DATABASE_URL") or os.environ.get("DATABASE_PUBLIC_URL")


def _connect():
    url = _db_url()
    if not url:
        raise RuntimeError("No DATABASE_URL/DATABASE_PUBLIC_URL set")
    conn = psycopg2.connect(url, connect_timeout=15,
                             cursor_factory=psycopg2.extras.RealDictCursor)
    conn.autocommit = True
    return conn


def _reopen(conn):
    """Return a healthy connection, reconnecting if the given one is dead.
    Used between run_checks() and the re-check pass after apply_auto_repair()."""
    try:
        if conn is not None and not conn.closed:
            with conn.cursor() as cur:
                cur.execute("SELECT 1")
            return conn
    except Exception:
        pass
    try:
        if conn is not None and not conn.closed:
            conn.close()
    except Exception:
        pass
    return _connect()


def _scalar(conn, sql, params=None, default=None):
    try:
        with conn.cursor() as cur:
            cur.execute(sql, params or ())
            row = cur.fetchone()
            if not row:
                return default
            return list(row.values())[0]
    except Exception as e:
        log.warning(f"healthcheck query failed ({sql[:50].strip()}...): {e}")
        try:
            conn.rollback()
        except Exception:
            pass
        return default


def _pct(numerator, denominator) -> Optional[float]:
    if not denominator:
        return None
    return round(100.0 * numerator / denominator, 1)


# ─────────────────────────────────────────────────────────────────────────────
# Checks
# ─────────────────────────────────────────────────────────────────────────────

def run_checks(conn) -> List[CheckResult]:
    results: List[CheckResult] = []
    today = date.today()
    yesterday = today - timedelta(days=1)

    # ── matches_today ────────────────────────────────────────────────────────
    n_today = _scalar(conn, "SELECT COUNT(*) FROM matches WHERE event_date = %s",
                       (today,), default=0) or 0
    results.append(CheckResult(
        name="matches_today", severity="CRITICAL",
        status="PASS" if n_today > 0 else "FAIL",
        value=n_today, threshold=">0",
        message=f"{n_today} matches for {today.isoformat()}"
                if n_today > 0 else
                f"No matches found for {today.isoformat()} — daily fixtures sync may be down",
    ))

    # ── predictions_coverage ─────────────────────────────────────────────────
    upcoming = _scalar(conn,
        "SELECT COUNT(*) FROM matches WHERE event_date BETWEEN %s AND %s "
        "AND event_status NOT IN ('Finished','Cancelled','Walkover','Postponed')",
        (today, today + timedelta(days=2)), default=0) or 0
    with_pred = _scalar(conn,
        "SELECT COUNT(*) FROM matches m JOIN model_predictions mp ON mp.match_id = m.id "
        "WHERE m.event_date BETWEEN %s AND %s "
        "AND m.event_status NOT IN ('Finished','Cancelled','Walkover','Postponed')",
        (today, today + timedelta(days=2)), default=0) or 0
    pct = _pct(with_pred, upcoming)
    results.append(CheckResult(
        name="predictions_coverage", severity="CRITICAL",
        status="PASS" if (pct is None or pct >= 80) else "FAIL",
        value=pct, threshold=">=80%",
        message=f"{with_pred}/{upcoming} upcoming matches have predictions ({pct}%)"
                if upcoming else "No upcoming matches to check",
    ))

    # ── bzzoiro_link_coverage ────────────────────────────────────────────────
    # Directly measures the 2026-08 match-merge fix: how many upcoming
    # matches are actually linked to Bzzoiro (bzzoiro_id set) rather than
    # sitting as a disconnected shadow row or never merged at all.
    with_bzz = _scalar(conn,
        "SELECT COUNT(*) FROM matches WHERE event_date BETWEEN %s AND %s "
        "AND bzzoiro_id IS NOT NULL",
        (today, today + timedelta(days=2)), default=0) or 0
    pct_bzz = _pct(with_bzz, upcoming)
    results.append(CheckResult(
        name="bzzoiro_link_coverage", severity="WARNING",
        status="PASS" if (pct_bzz is None or pct_bzz >= 30) else "FAIL",
        value=pct_bzz, threshold=">=30%",
        message=f"{with_bzz}/{upcoming} upcoming matches linked to Bzzoiro ({pct_bzz}%)"
                if upcoming else "No upcoming matches to check",
    ))

    # ── ratings_freshness ────────────────────────────────────────────────────
    last_snapshot = _scalar(conn, "SELECT MAX(snapshot_date) FROM player_ratings_history",
                             default=None)
    fresh = bool(last_snapshot and last_snapshot >= yesterday)
    results.append(CheckResult(
        name="ratings_freshness", severity="WARNING",
        status="PASS" if fresh else "FAIL",
        value=last_snapshot.isoformat() if last_snapshot else None,
        threshold=f">= {yesterday.isoformat()}",
        message=f"Last player_ratings_history snapshot: {last_snapshot}"
                if last_snapshot else "No player_ratings_history snapshots found",
    ))

    # ── seo_preview_coverage ─────────────────────────────────────────────────
    with_seo = _scalar(conn,
        "SELECT COUNT(*) FROM matches WHERE event_date BETWEEN %s AND %s "
        "AND seo_preview IS NOT NULL",
        (today, today + timedelta(days=2)), default=0) or 0
    pct_seo = _pct(with_seo, upcoming)
    results.append(CheckResult(
        name="seo_preview_coverage", severity="WARNING",
        status="PASS" if (pct_seo is None or pct_seo >= 10) else "FAIL",
        value=pct_seo, threshold=">=10%",
        message=f"{with_seo}/{upcoming} upcoming matches have an SEO preview ({pct_seo}%)"
                if upcoming else "No upcoming matches to check",
    ))

    # ── odds_coverage ────────────────────────────────────────────────────────
    with_odds = _scalar(conn,
        "SELECT COUNT(DISTINCT match_id) FROM bookmaker_odds bo "
        "JOIN matches m ON m.id = bo.match_id "
        "WHERE m.event_date BETWEEN %s AND %s",
        (today, today + timedelta(days=2)), default=0) or 0
    pct_odds = _pct(with_odds, upcoming)
    results.append(CheckResult(
        name="odds_coverage", severity="WARNING",
        status="PASS" if (pct_odds is None or pct_odds >= 20) else "FAIL",
        value=pct_odds, threshold=">=20%",
        message=f"{with_odds}/{upcoming} upcoming matches have bookmaker odds ({pct_odds}%)"
                if upcoming else "No upcoming matches to check",
    ))

    # ── live_data_freshness ──────────────────────────────────────────────────
    stale_live = _scalar(conn,
        "SELECT COUNT(*) FROM matches "
        "WHERE is_live = TRUE AND (updated_at IS NULL OR updated_at < NOW() - INTERVAL '15 minutes')",
        default=0) or 0
    n_live = _scalar(conn, "SELECT COUNT(*) FROM matches WHERE is_live = TRUE", default=0) or 0
    results.append(CheckResult(
        name="live_data_freshness", severity="WARNING",
        status="PASS" if stale_live == 0 else "FAIL",
        value=stale_live, threshold="0",
        message=f"{stale_live}/{n_live} live matches haven't updated in 15+ minutes"
                if n_live else "No matches currently live",
    ))

    # ── point_by_point_coverage ──────────────────────────────────────────────
    finished_yday = _scalar(conn,
        "SELECT COUNT(*) FROM matches WHERE event_date = %s AND event_status = 'Finished' "
        "AND bzzoiro_id IS NOT NULL",
        (yesterday,), default=0) or 0
    with_pbp = _scalar(conn,
        "SELECT COUNT(*) FROM matches m JOIN bzzoiro_point_by_point p ON p.match_id = m.id "
        "WHERE m.event_date = %s AND m.event_status = 'Finished'",
        (yesterday,), default=0) or 0
    pct_pbp = _pct(with_pbp, finished_yday)
    results.append(CheckResult(
        name="point_by_point_coverage", severity="WARNING",
        status="PASS" if (pct_pbp is None or pct_pbp >= 20) else "FAIL",
        value=pct_pbp, threshold=">=20%",
        message=f"{with_pbp}/{finished_yday} of yesterday's finished (bzzoiro-linked) "
                f"matches have point-by-point data ({pct_pbp}%)"
                if finished_yday else "No bzzoiro-linked finished matches yesterday to check",
    ))

    return results


# ─────────────────────────────────────────────────────────────────────────────
# Auto-repair — only safe, idempotent re-syncs for checks with a clear fix
# ─────────────────────────────────────────────────────────────────────────────

def apply_auto_repair(conn, results: List[CheckResult]) -> None:
    """Mutates `results` in place: for known-repairable FAIL checks, attempts
    a safe idempotent re-sync and records what happened.

    Only checks with a repair path that's actually available in *this*
    process are attempted. `pipeline/pipeline.py` and `ml/ratings.py` (needed
    to repair matches_today / ratings_freshness) are deliberately not bundled
    into the lean API image (see Dockerfile) — attempting them here would
    always ImportError and falsely look like a repair was tried. Those two
    checks stay report-only; the pipeline service's own schedule (fixtures at
    06:00/18:00 UTC, ratings at 01:00/08:00 UTC) is the real fix path for them.
    """
    by_name = {r.name: r for r in results}

    def _try(name, fn):
        r = by_name.get(name)
        if not r or r.status != "FAIL":
            return
        try:
            outcome = fn()
        except Exception as e:
            r.repair_message = f"Repair attempt failed: {type(e).__name__}: {e}"
            return
        if outcome is None:
            r.repair_message = "No repair available in this process"
            return
        r.auto_repaired = True
        r.repair_message = outcome

    def _repair_bzzoiro_link():
        try:
            from pipeline.bzzoiro import sync_fixtures
        except ImportError:
            from bzzoiro import sync_fixtures
        res = sync_fixtures(conn, days_ahead=3)
        return f"Re-ran bzzoiro sync_fixtures: {res}"

    def _repair_odds():
        try:
            from pipeline.odds import run as odds_run
        except ImportError:
            from odds import run as odds_run
        res = odds_run()
        return f"Re-ran odds sync: {res}"

    def _repair_pbp():
        try:
            from pipeline.bzzoiro import sync_point_by_point_recent
        except ImportError:
            from bzzoiro import sync_point_by_point_recent
        res = sync_point_by_point_recent(conn, days_back=5)
        return f"Re-ran point-by-point sync: {res}"

    _try("bzzoiro_link_coverage", _repair_bzzoiro_link)
    _try("odds_coverage", _repair_odds)
    _try("point_by_point_coverage", _repair_pbp)
    # matches_today / ratings_freshness: no repair module available in the
    # API image (see docstring above) — report-only.
    # predictions_coverage / seo_preview_coverage / live_data_freshness:
    # no safe one-shot repair (predictions need fresh fixtures first; SEO
    # previews are content-generation, not a re-sync; live staleness usually
    # means the match genuinely ended) — report-only.


# ─────────────────────────────────────────────────────────────────────────────
# Result logging
# ─────────────────────────────────────────────────────────────────────────────

def log_results(conn, run_id: str, results: List[CheckResult]) -> None:
    """Persist this run's results to healthcheck_runs (created on first use)."""
    with conn.cursor() as cur:
        cur.execute("""
            CREATE TABLE IF NOT EXISTS healthcheck_runs (
                id              SERIAL PRIMARY KEY,
                run_id          TEXT NOT NULL,
                check_name      TEXT NOT NULL,
                severity        TEXT,
                status          TEXT,
                value           TEXT,
                threshold       TEXT,
                message         TEXT,
                auto_repaired   BOOLEAN DEFAULT FALSE,
                repair_message  TEXT,
                checked_at      TIMESTAMPTZ DEFAULT NOW()
            )
        """)
        cur.execute("CREATE INDEX IF NOT EXISTS idx_healthcheck_runs_run_id "
                    "ON healthcheck_runs(run_id)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_healthcheck_runs_checked_at "
                    "ON healthcheck_runs(checked_at)")
        for r in results:
            cur.execute("""
                INSERT INTO healthcheck_runs
                    (run_id, check_name, severity, status, value, threshold,
                     message, auto_repaired, repair_message)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            """, (
                run_id, r.name, r.severity, r.status,
                str(r.value) if r.value is not None else None,
                str(r.threshold) if r.threshold is not None else None,
                r.message, r.auto_repaired, r.repair_message,
            ))
    log.info(f"log_results: wrote {len(results)} check rows for run_id={run_id}")


# ─────────────────────────────────────────────────────────────────────────────
# Standalone CLI
# ─────────────────────────────────────────────────────────────────────────────

def main():
    import uuid
    from datetime import datetime as _dt
    run_id = _dt.utcnow().strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:8]
    conn = _connect()
    try:
        results = run_checks(conn)
        apply_auto_repair(conn, results)
        log_results(conn, run_id, results)
        for r in results:
            print(f"[{r.status}] {r.name}: {r.message}"
                  + (f" (auto-repaired: {r.repair_message})" if r.auto_repaired else ""))
    finally:
        conn.close()


if __name__ == "__main__":
    main()
