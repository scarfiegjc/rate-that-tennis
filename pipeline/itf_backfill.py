#!/usr/bin/env python3
"""
ratethat.tennis — ITF Historical Backfill
==========================================
Pulls all historical ITF (and optionally Challenger/ATP/WTA) match results
from api-tennis.com going back N years and stores them in the matches table.
This gives the Elo engine the match history it needs to produce meaningful
predictions for ITF players — previously they were getting 1500 vs 1500 → 50/50.

Once complete, remove the ITF exclusion from ml/predict.py (the
predict_upcoming SQL filter) and re-run predictions.

Usage:
    python -m pipeline.itf_backfill                    # ITF only, last 3 years
    python -m pipeline.itf_backfill --years 4          # ITF only, last 4 years
    python -m pipeline.itf_backfill --all-tours        # all tours, last 3 years
    python -m pipeline.itf_backfill --from 2022-01-01  # ITF only, from specific date
    python -m pipeline.itf_backfill --week-size 7      # 7-day chunks (default 14)

The script is RESUMABLE — it skips date ranges where matches already exist.
It records progress to pipeline/backfill_checkpoint.txt so a killed run
can be restarted without re-fetching already-loaded weeks.
"""

from __future__ import annotations

import os
import sys
import json
import time
import logging
import argparse
import requests
import psycopg2
import psycopg2.extras
from datetime import date, timedelta
from pathlib import Path
from typing import Optional

# ── Import shared pipeline helpers ──────────────────────────────────────────
# Support running both as `python -m pipeline.itf_backfill` and directly.
try:
    from pipeline.pipeline import (
        TennisAPI, classify_event_type,
        get_surface_id, upsert_event_type, upsert_tournament,
        upsert_player, upsert_match, upsert_scores, upsert_pointbypoint,
        process_events, API_KEY, API_BASE, DB_URL,
    )
except ImportError:
    from pipeline import (
        TennisAPI, classify_event_type,
        get_surface_id, upsert_event_type, upsert_tournament,
        upsert_player, upsert_match, upsert_scores, upsert_pointbypoint,
        process_events, API_KEY, API_BASE, DB_URL,
    )

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
log = logging.getLogger("rtt-itf-backfill")

CHECKPOINT_FILE = Path(__file__).parent / "backfill_checkpoint.txt"

# Tour categories to include when --all-tours is NOT set
ITF_CATEGORIES = {"ITF", "Junior"}

# Tour categories to include when --all-tours IS set (add everything useful)
ALL_CATEGORIES = {"ITF", "Junior", "ATP", "WTA", "Challenger"}


def load_checkpoint() -> Optional[str]:
    """Return last completed week start (YYYY-MM-DD) from checkpoint file."""
    if CHECKPOINT_FILE.exists():
        txt = CHECKPOINT_FILE.read_text().strip()
        if txt:
            return txt
    return None


def save_checkpoint(week_start: str):
    CHECKPOINT_FILE.write_text(week_start)


def clear_checkpoint():
    if CHECKPOINT_FILE.exists():
        CHECKPOINT_FILE.unlink()


def get_itf_event_type_ids(conn, all_tours: bool = False) -> list[int]:
    """Return event_type_id values for ITF (or all useful) event types."""
    categories = ALL_CATEGORIES if all_tours else ITF_CATEGORIES
    with conn.cursor() as cur:
        placeholders = ",".join(["%s"] * len(categories))
        cur.execute(
            f"SELECT id FROM event_types WHERE tour_category IN ({placeholders})",
            tuple(categories),
        )
        rows = cur.fetchall()
    ids = [r["id"] for r in rows]
    log.info(f"  Found {len(ids)} event type IDs for categories: {categories}")
    return ids


def week_ranges(from_date: date, to_date: date, chunk_days: int = 14):
    """Yield (start, end) pairs covering [from_date, to_date] in chunks."""
    cur = from_date
    while cur <= to_date:
        end = min(cur + timedelta(days=chunk_days - 1), to_date)
        yield cur, end
        cur = end + timedelta(days=1)


def fetch_and_store_window(
    api: TennisAPI,
    conn,
    date_start: date,
    date_stop: date,
    itf_type_ids: set[int],
) -> tuple[int, int]:
    """
    Fetch all fixtures for [date_start, date_stop], filter to ITF finished
    singles matches, and store them. Returns (inserted, updated).
    """
    ds = date_start.isoformat()
    de = date_stop.isoformat()
    events = api.get_fixtures(date_start=ds, date_stop=de)

    if not events:
        return 0, 0

    # Filter: finished singles ITF matches only
    filtered = []
    for e in events:
        if e.get("event_status") != "Finished":
            continue
        if not e.get("event_winner"):
            continue
        et_type = (e.get("event_type_type") or "").lower()
        if "double" in et_type:
            continue  # skip doubles
        # Check event type is in our target categories
        cat, _, _ = classify_event_type(e.get("event_type_type") or "")
        if cat not in (ALL_CATEGORIES if itf_type_ids == "all" else ITF_CATEGORIES):
            continue
        filtered.append(e)

    if not filtered:
        return 0, 0

    with conn.cursor() as cur:
        ins, upd = process_events(cur, api, filtered)
    conn.commit()
    return ins, upd


def run_backfill(
    years: int = 3,
    from_date: Optional[date] = None,
    all_tours: bool = False,
    chunk_days: int = 14,
    resume: bool = True,
    dry_run: bool = False,
):
    log.info("=" * 60)
    log.info("ratethat.tennis — ITF Historical Backfill")
    log.info("=" * 60)

    api = TennisAPI(API_KEY, rate_limit_delay=0.3)
    conn = psycopg2.connect(DB_URL, cursor_factory=psycopg2.extras.RealDictCursor)
    conn.autocommit = False

    itf_type_ids = get_itf_event_type_ids(conn, all_tours)
    if not itf_type_ids:
        log.warning("No ITF event types found in DB — run sync_event_types first.")
        conn.close()
        return

    today = date.today()
    start = from_date or (today - timedelta(days=years * 365))
    end = today - timedelta(days=1)  # don't fetch today — incomplete

    log.info(f"  Date range: {start} → {end}  ({(end - start).days} days)")
    log.info(f"  Chunk size: {chunk_days} days")

    # Resume from checkpoint
    checkpoint = load_checkpoint() if resume else None
    skip_until = None
    if checkpoint:
        skip_until = date.fromisoformat(checkpoint)
        log.info(f"  Resuming from checkpoint: {checkpoint}")

    total_ins = total_upd = total_weeks = 0
    windows = list(week_ranges(start, end, chunk_days))
    log.info(f"  Total chunks to process: {len(windows)}")
    log.info("")

    for i, (ws, we) in enumerate(windows, 1):
        # Skip already-processed weeks
        if skip_until and ws <= skip_until:
            log.info(f"  [{i}/{len(windows)}] Skipping {ws} → {we} (already done)")
            continue

        if dry_run:
            log.info(f"  [{i}/{len(windows)}] DRY RUN: would fetch {ws} → {we}")
            continue

        log.info(f"  [{i}/{len(windows)}] Fetching {ws} → {we} ...")
        try:
            ins, upd = fetch_and_store_window(api, conn, ws, we, set(itf_type_ids))
            total_ins += ins
            total_upd += upd
            total_weeks += 1
            save_checkpoint(ws.isoformat())
            log.info(f"    ✓ {ins} new, {upd} updated  (API calls: {api.calls_made})")
        except Exception as e:
            log.error(f"    ✗ Error on {ws}–{we}: {e}")
            conn.rollback()
            log.info("    Skipping and continuing...")

    conn.close()

    log.info("")
    log.info("=" * 60)
    log.info(f"Backfill complete: {total_ins} inserted, {total_upd} updated")
    log.info(f"Chunks processed: {total_weeks}/{len(windows)}")
    log.info(f"Total API calls:  {api.calls_made}")
    log.info("=" * 60)
    log.info("")
    log.info("Next steps:")
    log.info("  1. Run: python -m ml.predict --upcoming 7")
    log.info("     ITF matches should now get real Elo-based predictions.")
    log.info("  2. If predictions look good, remove the ITF exclusion filter")
    log.info("     from ml/predict.py predict_upcoming() SQL.")
    log.info("")

    if total_ins + total_upd > 0:
        clear_checkpoint()
        log.info("Checkpoint cleared — backfill complete.")


def main():
    parser = argparse.ArgumentParser(description="Backfill ITF historical match data")
    parser.add_argument("--years", type=int, default=3,
                        help="How many years back to fetch (default: 3)")
    parser.add_argument("--from", dest="from_date", type=str, default=None,
                        help="Start date YYYY-MM-DD (overrides --years)")
    parser.add_argument("--all-tours", action="store_true",
                        help="Fetch ATP/WTA/Challenger too, not just ITF")
    parser.add_argument("--week-size", type=int, default=14,
                        help="Days per API chunk (default: 14)")
    parser.add_argument("--no-resume", action="store_true",
                        help="Ignore checkpoint and start from scratch")
    parser.add_argument("--dry-run", action="store_true",
                        help="Print what would be fetched without calling the API")
    args = parser.parse_args()

    from_date = date.fromisoformat(args.from_date) if args.from_date else None

    run_backfill(
        years=args.years,
        from_date=from_date,
        all_tours=args.all_tours,
        chunk_days=args.week_size,
        resume=not args.no_resume,
        dry_run=args.dry_run,
    )


if __name__ == "__main__":
    main()
