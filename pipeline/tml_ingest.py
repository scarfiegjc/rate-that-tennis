#!/usr/bin/env python3
"""
ratethat.tennis — TML-Database Ingestion
=========================================
Downloads ATP match CSVs from github.com/Tennismylife/TML-Database and loads
them into the sa_matches table using tour='TML'.

The TML-Database schema is identical to Jeff Sackmann's tennis_atp schema,
so we reuse the same ingest_matches_file() logic from sackmann_ingest.py.

Key differences from Sackmann:
  - Files are named YYYY.csv (not atp_matches_YYYY.csv)
  - No separate players file — players are upserted from match row data
  - Player IDs are ATP official IDs; we namespace them as tour='TML' in
    sa_players to avoid collision with Sackmann integer IDs

Source: github.com/Tennismylife/TML-Database
Licence: MIT (permissive — safe for commercial use)

Usage:
    python -m pipeline.tml_ingest                   # ingest all years
    python -m pipeline.tml_ingest --year 2025       # single year
    python -m pipeline.tml_ingest --start-year 2020 # from 2020 onwards
    python -m pipeline.tml_ingest --dry-run         # download + parse, no DB writes
"""

import os
import sys
import csv
import io
import logging
import argparse
from datetime import date, datetime
from pathlib import Path
from typing import Optional

import requests
import psycopg2
import psycopg2.extras

# ─────────────────────────────────────────────
# CONFIG
# ─────────────────────────────────────────────

DB_URL = (
    os.environ.get("DATABASE_PUBLIC_URL")
    or os.environ.get("DATABASE_URL")
    or "postgresql://postgres:DEKANqBEjmOvOGLCfzaQIBaKzhKcyKwS@switchyard.proxy.rlwy.net:39343/railway"
).strip()

TML_BASE_URL = "https://raw.githubusercontent.com/Tennismylife/TML-Database/master"

# Years to ingest (TML covers 1968–present but detailed stats from ~2000 onwards)
DEFAULT_START_YEAR = 2000
DEFAULT_END_YEAR   = datetime.now().year  # current year

TOUR = "TML"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
log = logging.getLogger("tml-ingest")


# ─────────────────────────────────────────────
# DB HELPERS
# ─────────────────────────────────────────────

def get_conn():
    conn = psycopg2.connect(DB_URL)
    conn.cursor_factory = psycopg2.extras.RealDictCursor
    return conn


def log_ingest(conn, tour: str, file_name: str, status: str,
               rows_processed=0, rows_inserted=0, rows_skipped=0, error_msg=None):
    with conn.cursor() as cur:
        cur.execute("""
            INSERT INTO sa_ingest_log (tour, file_name, status, rows_processed, rows_inserted, rows_skipped, error_msg, completed_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, NOW())
            ON CONFLICT (tour, file_name) DO UPDATE SET
                status         = EXCLUDED.status,
                rows_processed = EXCLUDED.rows_processed,
                rows_inserted  = EXCLUDED.rows_inserted,
                rows_skipped   = EXCLUDED.rows_skipped,
                error_msg      = EXCLUDED.error_msg,
                completed_at   = NOW()
        """, (tour, file_name, status, rows_processed, rows_inserted, rows_skipped, error_msg))
    conn.commit()


def already_loaded(conn, tour: str, file_name: str) -> bool:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT status FROM sa_ingest_log WHERE tour = %s AND file_name = %s",
            (tour, file_name)
        )
        row = cur.fetchone()
        return row is not None and row["status"] == "success"


# ─────────────────────────────────────────────
# PARSE HELPERS  (identical to sackmann_ingest)
# ─────────────────────────────────────────────

def to_int(val) -> Optional[int]:
    try:
        return int(val) if val not in (None, "", "NA") else None
    except (ValueError, TypeError):
        return None


def to_float(val) -> Optional[float]:
    try:
        return float(val) if val not in (None, "", "NA") else None
    except (ValueError, TypeError):
        return None


def to_date(val: str) -> Optional[date]:
    """Parse date formats: YYYYMMDD or YYYY-MM-DD."""
    if not val or val in ("", "NA"):
        return None
    val = val.strip()
    try:
        if len(val) == 8 and val.isdigit():
            return datetime.strptime(val, "%Y%m%d").date()
        return datetime.strptime(val[:10], "%Y-%m-%d").date()
    except ValueError:
        return None


def derived_serve_pct(won: Optional[int], total: Optional[int]) -> Optional[float]:
    if won is None or total is None or total == 0:
        return None
    return round(won / total, 4)


# ─────────────────────────────────────────────
# DOWNLOAD
# ─────────────────────────────────────────────

def fetch_tml_csv(year: int) -> Optional[str]:
    """Download a single TML year CSV. Returns raw text or None on 404."""
    url = f"{TML_BASE_URL}/{year}.csv"
    try:
        resp = requests.get(url, timeout=60)
        if resp.status_code == 404:
            log.info(f"  {year}.csv not found (404) — skipping")
            return None
        resp.raise_for_status()
        log.info(f"  Downloaded {year}.csv ({len(resp.content):,} bytes)")
        return resp.text
    except requests.RequestException as e:
        log.error(f"  Failed to download {year}.csv: {e}")
        return None


# ─────────────────────────────────────────────
# PLAYERS  (extracted from match rows)
# ─────────────────────────────────────────────

def upsert_players_from_rows(conn, player_rows: list, dry_run: bool = False):
    """
    Upsert players extracted from TML match data into sa_players.

    TML has no separate players file, so we collect player info from
    winner_*/loser_* columns in each match row.

    We use tour='TML' to namespace these players separately from
    Sackmann ATP/WTA players (which use integer IDs from a different
    registry). player_id here = ATP official ID (string like '105227').

    sa_players has UNIQUE(player_id) — TML IDs could collide with
    Sackmann IDs, so we store TML players with a negative ID offset:
    TML player_id stored as -(original_id) to guarantee no collision.

    Actually, safer approach: store player_id as-is but tour='TML'.
    The UNIQUE constraint is only on player_id (not tour+player_id).

    Since Sackmann ATP IDs are sequential small integers (e.g. 105227)
    and TML ATP official IDs are also similar integers, we use a large
    offset: TML_player_id = original_id + 10_000_000 to guarantee no
    collision with Sackmann's 6-digit IDs.
    """
    if not player_rows or dry_run:
        return

    TML_ID_OFFSET = 10_000_000
    rows = []
    seen_ids = set()

    for pid, name, hand, ht, ioc in player_rows:
        if pid is None or pid in seen_ids:
            continue
        seen_ids.add(pid)
        namespaced_id = pid + TML_ID_OFFSET

        # Split name: TML stores "Firstname Lastname"
        parts = name.strip().split(" ", 1) if name else ["", ""]
        name_first = parts[0] if len(parts) > 0 else None
        name_last  = parts[1] if len(parts) > 1 else None

        rows.append((
            namespaced_id,
            name_first or None,
            name_last or None,
            hand or None,
            None,       # dob — not in TML match rows
            ioc or None,
            to_int(ht),
            TOUR,
        ))

    if not rows:
        return

    with conn.cursor() as cur:
        psycopg2.extras.execute_values(cur, """
            INSERT INTO sa_players (player_id, name_first, name_last, hand, dob, ioc, height_cm, tour)
            VALUES %s
            ON CONFLICT (player_id) DO UPDATE SET
                name_first = COALESCE(EXCLUDED.name_first, sa_players.name_first),
                name_last  = COALESCE(EXCLUDED.name_last,  sa_players.name_last),
                hand       = COALESCE(EXCLUDED.hand,       sa_players.hand),
                ioc        = COALESCE(EXCLUDED.ioc,        sa_players.ioc),
                height_cm  = COALESCE(EXCLUDED.height_cm,  sa_players.height_cm)
        """, rows, page_size=500)
    conn.commit()
    log.info(f"    Players: upserted {len(rows)} unique players")


# ─────────────────────────────────────────────
# MATCHES
# ─────────────────────────────────────────────

TML_ID_OFFSET = 10_000_000


def ingest_tml_csv_text(conn, csv_text: str, year: int, dry_run: bool = False) -> dict:
    """
    Parse a TML CSV (already downloaded as text) and load into sa_matches.

    Returns stats dict: {processed, inserted, skipped}
    """
    fname = f"tml_{year}.csv"

    if not dry_run and already_loaded(conn, TOUR, fname):
        log.info(f"  Skipping {fname} (already loaded)")
        return {"processed": 0, "inserted": 0, "skipped": 0}

    log.info(f"  Parsing {fname} ...")
    processed = inserted = skipped = 0
    match_rows = []
    player_data = []  # (pid, name, hand, ht, ioc) for player upsert

    reader = csv.DictReader(io.StringIO(csv_text))

    for row in reader:
        processed += 1

        tourney_id = row.get("tourney_id", "").strip()
        match_num  = to_int(row.get("match_num"))
        if not tourney_id or match_num is None:
            skipped += 1
            continue

        # Derive season
        tourney_date = to_date(row.get("tourney_date", ""))
        season = tourney_date.year if tourney_date else year

        # Player IDs — offset to avoid collision with Sackmann IDs
        raw_winner_id = to_int(row.get("winner_id"))
        raw_loser_id  = to_int(row.get("loser_id"))
        winner_id = (raw_winner_id + TML_ID_OFFSET) if raw_winner_id else None
        loser_id  = (raw_loser_id  + TML_ID_OFFSET) if raw_loser_id  else None

        # Collect player data for upsert
        if raw_winner_id:
            player_data.append((
                raw_winner_id,
                row.get("winner_name", ""),
                row.get("winner_hand", ""),
                row.get("winner_ht", ""),
                row.get("winner_ioc", ""),
            ))
        if raw_loser_id:
            player_data.append((
                raw_loser_id,
                row.get("loser_name", ""),
                row.get("loser_hand", ""),
                row.get("loser_ht", ""),
                row.get("loser_ioc", ""),
            ))

        # Serve stats
        w_svpt    = to_int(row.get("w_svpt"))
        w_1st_in  = to_int(row.get("w_1stIn"))
        w_1st_won = to_int(row.get("w_1stWon"))
        w_2nd_won = to_int(row.get("w_2ndWon"))
        w_bp_saved = to_int(row.get("w_bpSaved"))
        w_bp_faced = to_int(row.get("w_bpFaced"))
        w_sv_gms   = to_int(row.get("w_SvGms"))

        l_svpt    = to_int(row.get("l_svpt"))
        l_1st_in  = to_int(row.get("l_1stIn"))
        l_1st_won = to_int(row.get("l_1stWon"))
        l_2nd_won = to_int(row.get("l_2ndWon"))
        l_bp_saved = to_int(row.get("l_bpSaved"))
        l_bp_faced = to_int(row.get("l_bpFaced"))
        l_sv_gms   = to_int(row.get("l_SvGms"))

        w_2nd_att = (w_svpt - w_1st_in) if w_svpt and w_1st_in else None
        l_2nd_att = (l_svpt - l_1st_in) if l_svpt and l_1st_in else None

        match_rows.append((
            TOUR,
            tourney_id,
            row.get("tourney_name", "").strip() or None,
            row.get("surface", "").strip() or None,
            to_int(row.get("draw_size")),
            row.get("tourney_level", "").strip() or None,
            tourney_date,
            season,
            match_num,
            row.get("round", "").strip() or None,
            to_int(row.get("best_of")),
            # Winner
            winner_id,
            to_int(row.get("winner_seed")),
            row.get("winner_entry", "").strip() or None,
            row.get("winner_name", "").strip() or None,
            row.get("winner_hand", "").strip() or None,
            to_int(row.get("winner_ht")),
            row.get("winner_ioc", "").strip() or None,
            to_float(row.get("winner_age")),
            to_int(row.get("winner_rank")),
            to_int(row.get("winner_rank_points")),
            # Loser
            loser_id,
            to_int(row.get("loser_seed")),
            row.get("loser_entry", "").strip() or None,
            row.get("loser_name", "").strip() or None,
            row.get("loser_hand", "").strip() or None,
            to_int(row.get("loser_ht")),
            row.get("loser_ioc", "").strip() or None,
            to_float(row.get("loser_age")),
            to_int(row.get("loser_rank")),
            to_int(row.get("loser_rank_points")),
            # Result
            row.get("score", "").strip() or None,
            to_int(row.get("minutes")),
            # Winner serve stats
            to_int(row.get("w_ace")),
            to_int(row.get("w_df")),
            w_svpt, w_1st_in, w_1st_won, w_2nd_won, w_sv_gms, w_bp_saved, w_bp_faced,
            # Loser serve stats
            to_int(row.get("l_ace")),
            to_int(row.get("l_df")),
            l_svpt, l_1st_in, l_1st_won, l_2nd_won, l_sv_gms, l_bp_saved, l_bp_faced,
            # Derived
            derived_serve_pct(w_1st_in, w_svpt),
            derived_serve_pct(w_1st_won, w_1st_in),
            derived_serve_pct(w_2nd_won, w_2nd_att),
            derived_serve_pct(w_bp_saved, w_bp_faced),
            None,   # w_hold_pct
            derived_serve_pct(l_1st_in, l_svpt),
            derived_serve_pct(l_1st_won, l_1st_in),
            derived_serve_pct(l_2nd_won, l_2nd_att),
            derived_serve_pct(l_bp_saved, l_bp_faced),
            None,   # l_hold_pct
        ))

    if dry_run:
        log.info(f"  [DRY RUN] {fname}: {processed} rows parsed, {skipped} skipped, {len(match_rows)} would be inserted")
        return {"processed": processed, "inserted": 0, "skipped": skipped}

    if not match_rows:
        log.info(f"    No valid rows in {fname}")
        log_ingest(conn, TOUR, fname, "success", processed, 0, skipped)
        return {"processed": processed, "inserted": 0, "skipped": skipped}

    # Upsert players first
    upsert_players_from_rows(conn, player_data, dry_run=False)

    # Upsert matches
    with conn.cursor() as cur:
        psycopg2.extras.execute_values(cur, """
            INSERT INTO sa_matches (
                tour, tourney_id, tourney_name, surface, draw_size, tourney_level,
                tourney_date, season, match_num, round, best_of,
                winner_id, winner_seed, winner_entry, winner_name, winner_hand,
                winner_ht, winner_ioc, winner_age, winner_rank, winner_rank_points,
                loser_id, loser_seed, loser_entry, loser_name, loser_hand,
                loser_ht, loser_ioc, loser_age, loser_rank, loser_rank_points,
                score, minutes,
                w_ace, w_df, w_svpt, w_1st_in, w_1st_won, w_2nd_won,
                w_sv_gms, w_bp_saved, w_bp_faced,
                l_ace, l_df, l_svpt, l_1st_in, l_1st_won, l_2nd_won,
                l_sv_gms, l_bp_saved, l_bp_faced,
                w_1st_serve_pct, w_1st_won_pct, w_2nd_won_pct, w_bp_save_pct, w_hold_pct,
                l_1st_serve_pct, l_1st_won_pct, l_2nd_won_pct, l_bp_save_pct, l_hold_pct
            ) VALUES %s
            ON CONFLICT (tour, tourney_id, match_num) DO UPDATE SET
                score           = EXCLUDED.score,
                winner_rank     = EXCLUDED.winner_rank,
                loser_rank      = EXCLUDED.loser_rank,
                w_ace           = EXCLUDED.w_ace,
                w_df            = EXCLUDED.w_df,
                w_svpt          = EXCLUDED.w_svpt,
                w_1st_in        = EXCLUDED.w_1st_in,
                w_1st_won       = EXCLUDED.w_1st_won,
                w_2nd_won       = EXCLUDED.w_2nd_won,
                w_bp_saved      = EXCLUDED.w_bp_saved,
                w_bp_faced      = EXCLUDED.w_bp_faced,
                l_ace           = EXCLUDED.l_ace,
                l_df            = EXCLUDED.l_df,
                l_svpt          = EXCLUDED.l_svpt,
                l_1st_in        = EXCLUDED.l_1st_in,
                l_1st_won       = EXCLUDED.l_1st_won,
                l_2nd_won       = EXCLUDED.l_2nd_won,
                l_bp_saved      = EXCLUDED.l_bp_saved,
                l_bp_faced      = EXCLUDED.l_bp_faced,
                w_1st_serve_pct = EXCLUDED.w_1st_serve_pct,
                w_1st_won_pct   = EXCLUDED.w_1st_won_pct,
                w_2nd_won_pct   = EXCLUDED.w_2nd_won_pct,
                w_bp_save_pct   = EXCLUDED.w_bp_save_pct,
                l_1st_serve_pct = EXCLUDED.l_1st_serve_pct,
                l_1st_won_pct   = EXCLUDED.l_1st_won_pct,
                l_2nd_won_pct   = EXCLUDED.l_2nd_won_pct,
                l_bp_save_pct   = EXCLUDED.l_bp_save_pct
        """, match_rows, page_size=200)
        inserted = cur.rowcount

    conn.commit()
    log.info(f"    {fname}: {processed} processed, {inserted} upserted, {skipped} skipped")
    log_ingest(conn, TOUR, fname, "success", processed, inserted, skipped)

    return {"processed": processed, "inserted": inserted, "skipped": skipped}


# ─────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────

def run(start_year: int = DEFAULT_START_YEAR,
        end_year: int = DEFAULT_END_YEAR,
        year: Optional[int] = None,
        dry_run: bool = False):
    """
    Main entry point. Downloads and ingests TML CSV files.

    Args:
        start_year: First year to ingest (default 2000)
        end_year:   Last year to ingest (default current year)
        year:       If set, only ingest this single year
        dry_run:    Parse and count rows but don't write to DB
    """
    log.info(f"TML-Database ingestion {'[DRY RUN] ' if dry_run else ''}starting")

    if dry_run:
        conn = None
    else:
        conn = get_conn()

    years = [year] if year else range(start_year, end_year + 1)
    total = {"processed": 0, "inserted": 0, "skipped": 0}

    try:
        for yr in years:
            log.info(f"Year {yr}:")
            csv_text = fetch_tml_csv(yr)
            if csv_text is None:
                continue

            try:
                stats = ingest_tml_csv_text(conn, csv_text, yr, dry_run=dry_run)
                for k in total:
                    total[k] += stats[k]
            except Exception as e:
                log.error(f"  Error processing {yr}.csv: {e}")
                if conn:
                    try:
                        conn.rollback()
                        log_ingest(conn, TOUR, f"tml_{yr}.csv", "failed", error_msg=str(e))
                    except Exception:
                        pass

    finally:
        if conn:
            conn.close()

    log.info(
        f"\nTML ingestion complete. "
        f"Total: {total['processed']:,} processed, "
        f"{total['inserted']:,} upserted, "
        f"{total['skipped']:,} skipped."
    )
    return total


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Ingest TML-Database ATP match data into sa_matches"
    )
    parser.add_argument("--year",       type=int, help="Ingest a single year only")
    parser.add_argument("--start-year", type=int, default=DEFAULT_START_YEAR, help=f"Start year (default {DEFAULT_START_YEAR})")
    parser.add_argument("--end-year",   type=int, default=DEFAULT_END_YEAR,   help=f"End year (default {DEFAULT_END_YEAR})")
    parser.add_argument("--dry-run",    action="store_true", help="Parse only, no DB writes")
    args = parser.parse_args()

    run(
        start_year=args.start_year,
        end_year=args.end_year,
        year=args.year,
        dry_run=args.dry_run,
    )
