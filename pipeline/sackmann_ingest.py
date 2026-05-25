#!/usr/bin/env python3
"""
ratethat.tennis — Sackmann Historical Data Ingestion
=====================================================
Downloads Jeff Sackmann's tennis_atp, tennis_wta, and tennis_charting_project
repos from GitHub and loads them into PostgreSQL ML training tables.

Data is used for ML training ONLY and is never surfaced on the front-end.
Source: github.com/JeffSackmann (CC BY-NC-SA 4.0)

Usage:
    python sackmann_ingest.py --job all               # full initial load
    python sackmann_ingest.py --job players           # players only
    python sackmann_ingest.py --job matches           # ATP + WTA matches
    python sackmann_ingest.py --job rankings          # ATP + WTA rankings
    python sackmann_ingest.py --job charting          # charting project
    python sackmann_ingest.py --job matches --year 2024  # single year

    python sackmann_ingest.py --schema-only           # just run the schema SQL
"""

import os
import sys
import csv
import gzip
import json
import logging
import argparse
import subprocess
import tempfile
import shutil
import io
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

SACKMANN_REPOS = {
    "ATP": "https://github.com/JeffSackmann/tennis_atp/archive/refs/heads/master.zip",
    "WTA": "https://github.com/JeffSackmann/tennis_wta/archive/refs/heads/master.zip",
    "CHARTING": "https://github.com/JeffSackmann/tennis_MatchChartingProject/archive/refs/heads/master.zip",
}

SCHEMA_FILE = Path(__file__).parent.parent / "sackmann_schema.sql"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
log = logging.getLogger("sackmann-ingest")


# ─────────────────────────────────────────────
# DB HELPERS
# ─────────────────────────────────────────────

def get_conn():
    conn = psycopg2.connect(DB_URL)
    conn.cursor_factory = psycopg2.extras.RealDictCursor
    return conn


def run_schema(conn):
    """Apply sackmann_schema.sql to the database."""
    if not SCHEMA_FILE.exists():
        log.error(f"Schema file not found: {SCHEMA_FILE}")
        sys.exit(1)
    sql = SCHEMA_FILE.read_text()
    with conn.cursor() as cur:
        cur.execute(sql)
    conn.commit()
    log.info("Schema applied successfully")


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
# DOWNLOAD HELPERS
# ─────────────────────────────────────────────

def download_repo_zip(url: str, dest_dir: Path) -> Path:
    """Download a GitHub repo zip and extract it. Returns the extracted folder path."""
    import zipfile

    log.info(f"Downloading {url} ...")
    resp = requests.get(url, stream=True, timeout=120)
    resp.raise_for_status()

    zip_path = dest_dir / "repo.zip"
    with open(zip_path, "wb") as f:
        for chunk in resp.iter_content(chunk_size=65536):
            f.write(chunk)

    log.info(f"Extracting to {dest_dir} ...")
    with zipfile.ZipFile(zip_path) as zf:
        zf.extractall(dest_dir)

    zip_path.unlink()

    # The extracted folder is usually named <repo>-master
    extracted = [p for p in dest_dir.iterdir() if p.is_dir()]
    if not extracted:
        raise RuntimeError(f"Nothing extracted from {url}")
    return extracted[0]


# ─────────────────────────────────────────────
# PARSE HELPERS
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
    """Parse Sackmann date formats: YYYYMMDD or YYYY-MM-DD."""
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


def parse_shot_sequence(seq: str) -> dict:
    """
    Parse Sackmann shot notation into structured fields.
    Format: [serve_direction][serve_speed][rally_shots...][outcome]
    Returns dict of parsed features.
    """
    if not seq:
        return {}

    result = {
        "serve_dir": None,
        "serve_fault": False,
        "rally_length": 0,
        "point_end_type": None,
        "last_shot_type": None,
        "last_shot_dir": None,
    }

    try:
        # Serve direction: 4=wide, 5=body, 6=T (for deuce court)
        serve_chars = {"4": "W", "5": "B", "6": "T"}
        if seq and seq[0] in serve_chars:
            result["serve_dir"] = serve_chars[seq[0]]

        # Fault: starts with f or +
        if "f" in seq[:3]:
            result["serve_fault"] = True

        # Count rally shots (alpha chars in body of sequence)
        body = seq[1:] if seq else ""
        shot_chars = [c for c in body if c.isalpha() and c not in ("f", "n", "e", "x", "w")]
        result["rally_length"] = len(shot_chars)

        # Point end type
        for char, label in [("*", "W"), ("!", "E"), ("#", "A"), ("@", "UE"), ("n", "N")]:
            if char in seq:
                result["point_end_type"] = label
                break

        # Last shot type and direction (last two meaningful chars)
        if len(body) >= 1:
            # Common shot type chars
            shot_types = {"f": "f", "b": "b", "r": "r", "s": "s", "v": "v",
                          "z": "z", "o": "o", "p": "p", "u": "u", "y": "y", "l": "l"}
            for char in reversed(body):
                if char in shot_types:
                    result["last_shot_type"] = char
                    break
            # Direction
            dir_chars = {"w": "W", "n": "N", "d": "D", "@": "UE"}
            for char in reversed(body):
                if char in dir_chars:
                    result["last_shot_dir"] = dir_chars[char]
                    break

    except Exception:
        pass

    return result


# ─────────────────────────────────────────────
# PLAYERS
# ─────────────────────────────────────────────

def ingest_players(conn, repo_dir: Path, tour: str):
    """Load atp_players.csv or wta_players.csv into sa_players."""
    prefix = "atp" if tour == "ATP" else "wta"
    players_file = repo_dir / f"{prefix}_players.csv"

    if not players_file.exists():
        log.warning(f"Players file not found: {players_file}")
        return

    if already_loaded(conn, tour, players_file.name):
        log.info(f"  Skipping {players_file.name} (already loaded)")
        return

    log.info(f"  Loading {players_file.name} ...")
    processed = inserted = skipped = 0

    with open(players_file, encoding="utf-8", errors="replace") as f:
        reader = csv.DictReader(f)
        rows = []
        for row in reader:
            processed += 1
            pid = to_int(row.get("player_id"))
            if not pid:
                skipped += 1
                continue

            dob = to_date(row.get("dob", ""))
            ht = to_int(row.get("height"))

            rows.append((
                pid,
                row.get("name_first", "").strip() or None,
                row.get("name_last", "").strip() or None,
                row.get("hand", "").strip() or None,
                dob,
                row.get("ioc", "").strip() or None,
                ht,
                tour,
            ))

    with conn.cursor() as cur:
        psycopg2.extras.execute_values(cur, """
            INSERT INTO sa_players (player_id, name_first, name_last, hand, dob, ioc, height_cm, tour)
            VALUES %s
            ON CONFLICT (player_id) DO UPDATE SET
                name_first = EXCLUDED.name_first,
                name_last  = EXCLUDED.name_last,
                hand       = EXCLUDED.hand,
                dob        = EXCLUDED.dob,
                ioc        = EXCLUDED.ioc,
                height_cm  = EXCLUDED.height_cm
        """, rows, page_size=500)
        inserted = cur.rowcount
    conn.commit()

    log.info(f"    Players: {processed} processed, {inserted} upserted, {skipped} skipped")
    log_ingest(conn, tour, players_file.name, "success", processed, inserted, skipped)


# ─────────────────────────────────────────────
# MATCHES
# ─────────────────────────────────────────────

def ingest_matches_file(conn, filepath: Path, tour: str):
    """Load a single matches CSV (e.g. atp_matches_2024.csv) into sa_matches."""
    fname = filepath.name

    if already_loaded(conn, tour, fname):
        log.info(f"  Skipping {fname} (already loaded)")
        return

    log.info(f"  Loading {fname} ...")
    processed = inserted = skipped = 0
    rows = []

    with open(filepath, encoding="utf-8", errors="replace") as f:
        reader = csv.DictReader(f)
        for row in reader:
            processed += 1

            tourney_id = row.get("tourney_id", "").strip()
            match_num  = to_int(row.get("match_num"))
            if not tourney_id or match_num is None:
                skipped += 1
                continue

            # Derive season from tourney_date or tourney_id
            tourney_date = to_date(row.get("tourney_date", ""))
            season = tourney_date.year if tourney_date else to_int(str(tourney_id)[:4])

            # Serve stats
            w_svpt   = to_int(row.get("w_svpt"))
            w_1st_in = to_int(row.get("w_1stIn"))
            w_1st_won = to_int(row.get("w_1stWon"))
            w_2nd_won = to_int(row.get("w_2ndWon"))
            w_bp_saved = to_int(row.get("w_bpSaved"))
            w_bp_faced = to_int(row.get("w_bpFaced"))
            w_sv_gms  = to_int(row.get("w_SvGms"))

            l_svpt   = to_int(row.get("l_svpt"))
            l_1st_in = to_int(row.get("l_1stIn"))
            l_1st_won = to_int(row.get("l_1stWon"))
            l_2nd_won = to_int(row.get("l_2ndWon"))
            l_bp_saved = to_int(row.get("l_bpSaved"))
            l_bp_faced = to_int(row.get("l_bpFaced"))
            l_sv_gms  = to_int(row.get("l_SvGms"))

            # Derived percentages
            w_2nd_att = (w_svpt - w_1st_in) if w_svpt and w_1st_in else None
            l_2nd_att = (l_svpt - l_1st_in) if l_svpt and l_1st_in else None

            rows.append((
                tour,
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
                to_int(row.get("winner_id")),
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
                to_int(row.get("loser_id")),
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
                None,  # w_hold_pct — compute separately if needed
                derived_serve_pct(l_1st_in, l_svpt),
                derived_serve_pct(l_1st_won, l_1st_in),
                derived_serve_pct(l_2nd_won, l_2nd_att),
                derived_serve_pct(l_bp_saved, l_bp_faced),
                None,  # l_hold_pct
            ))

    if not rows:
        log.info(f"    No valid rows in {fname}")
        log_ingest(conn, tour, fname, "success", processed, 0, skipped)
        return

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
        """, rows, page_size=200)
        inserted = cur.rowcount

    conn.commit()
    log.info(f"    {fname}: {processed} processed, {inserted} upserted, {skipped} skipped")
    log_ingest(conn, tour, fname, "success", processed, inserted, skipped)


def ingest_matches(conn, repo_dir: Path, tour: str, year: Optional[int] = None):
    """Ingest all match files for a tour, optionally filtered to a single year."""
    prefix = "atp" if tour == "ATP" else "wta"

    # Find all match files, sorted chronologically
    match_files = sorted(repo_dir.glob(f"{prefix}_matches_????.csv"))

    if year:
        match_files = [f for f in match_files if str(year) in f.name]

    if not match_files:
        log.warning(f"  No match files found in {repo_dir}")
        return

    # Also handle futures/qual files
    futures_files = sorted(repo_dir.glob(f"{prefix}_matches_futures_????.csv"))
    qual_files    = sorted(repo_dir.glob(f"{prefix}_matches_qual_chall_????.csv"))
    slam_files    = sorted(repo_dir.glob(f"{prefix}_matches_slam_pointbypoint_????.csv"))

    all_files = match_files + futures_files + qual_files

    log.info(f"  Found {len(all_files)} match files for {tour}")

    for fpath in all_files:
        try:
            ingest_matches_file(conn, fpath, tour)
        except Exception as e:
            log.error(f"  Error loading {fpath.name}: {e}")
            try:
                conn.rollback()
                log_ingest(conn, tour, fpath.name, "failed", error_msg=str(e))
            except Exception:
                pass


# ─────────────────────────────────────────────
# RANKINGS
# ─────────────────────────────────────────────

def ingest_rankings_file(conn, filepath: Path, tour: str):
    """Load a rankings CSV into sa_rankings."""
    fname = filepath.name

    if already_loaded(conn, tour + "_RANK", fname):
        log.info(f"  Skipping {fname} (already loaded)")
        return

    log.info(f"  Loading {fname} ...")
    processed = inserted = skipped = 0
    rows = []

    with open(filepath, encoding="utf-8", errors="replace") as f:
        reader = csv.DictReader(f)
        # Handle both header formats: ranking_date,rank,player,points
        for row in reader:
            processed += 1
            rank_date = to_date(row.get("ranking_date", ""))
            rank      = to_int(row.get("rank"))
            player_id = to_int(row.get("player"))
            points    = to_int(row.get("points"))

            if not rank_date or not rank or not player_id:
                skipped += 1
                continue

            rows.append((tour, rank_date, rank, player_id, points))

    if not rows:
        log_ingest(conn, tour + "_RANK", fname, "success", processed, 0, skipped)
        return

    # Deduplicate on (tour, ranking_date, rank) — keeps last occurrence.
    # Required because *_current.csv files sometimes have duplicate rows that
    # would cause "ON CONFLICT DO UPDATE command cannot affect row a second time".
    seen: dict = {}
    for r in rows:
        key = (r[0], r[1], r[2])  # tour, ranking_date, rank
        seen[key] = r
    rows = list(seen.values())

    with conn.cursor() as cur:
        # Use a SQL-level approach:
        # 1. Feed rows via VALUES %s into a subquery
        # 2. JOIN against sa_players to skip FK violations (unknown player_ids)
        # 3. DISTINCT ON (tour, ranking_date, rank) to eliminate within-batch dupes
        # This avoids both the FK constraint error and the ON CONFLICT dupe error.
        psycopg2.extras.execute_values(cur, """
            INSERT INTO sa_rankings (tour, ranking_date, rank, player_id, points)
            SELECT DISTINCT ON (v_tour, v_date, v_rank)
                v_tour, v_date::date, v_rank::int, v_pid::int, v_pts::int
            FROM (VALUES %s) AS v(v_tour, v_date, v_rank, v_pid, v_pts)
            JOIN sa_players sp ON sp.player_id = v_pid::int
            ON CONFLICT (tour, ranking_date, rank) DO UPDATE SET
                player_id = EXCLUDED.player_id,
                points    = EXCLUDED.points
        """, rows, page_size=500)
        inserted = cur.rowcount

    conn.commit()
    log.info(f"    {fname}: {processed} processed, {inserted} upserted, {skipped} skipped")
    log_ingest(conn, tour + "_RANK", fname, "success", processed, inserted, skipped)


def ingest_rankings(conn, repo_dir: Path, tour: str):
    """Ingest all ranking files for a tour."""
    prefix = "atp" if tour == "ATP" else "wta"

    ranking_files = (
        sorted(repo_dir.glob(f"{prefix}_rankings_??.csv"))    # atp_rankings_70s.csv etc.
        + sorted(repo_dir.glob(f"{prefix}_rankings_???s.csv"))
        + [repo_dir / f"{prefix}_rankings_current.csv"]
    )
    ranking_files = [f for f in ranking_files if f.exists()]

    log.info(f"  Found {len(ranking_files)} ranking files for {tour}")
    for fpath in ranking_files:
        try:
            ingest_rankings_file(conn, fpath, tour)
        except Exception as e:
            log.error(f"  Error loading {fpath.name}: {e}")
            try:
                conn.rollback()   # clear broken transaction before logging
                log_ingest(conn, tour + "_RANK", fpath.name, "failed", error_msg=str(e))
            except Exception:
                pass  # log failure is non-fatal


# ─────────────────────────────────────────────
# CHARTING PROJECT
# ─────────────────────────────────────────────

def ingest_charting_matches(conn, repo_dir: Path, tour: str):
    """Load charting match metadata."""
    gender = "m" if tour == "ATP" else "w"
    fpath = repo_dir / f"charting-{gender}-matches.csv"

    if not fpath.exists():
        log.warning(f"  Charting matches file not found: {fpath}")
        return

    if already_loaded(conn, "CHARTING_" + tour, fpath.name):
        log.info(f"  Skipping {fpath.name} (already loaded)")
        return

    log.info(f"  Loading {fpath.name} ...")
    processed = inserted = skipped = 0
    rows = []

    with open(fpath, encoding="utf-8", errors="replace") as f:
        reader = csv.DictReader(f)
        for row in reader:
            processed += 1
            match_id = row.get("match_id", "").strip()
            if not match_id:
                skipped += 1
                continue

            # Parse date from match_id (first 8 chars are YYYYMMDD)
            match_date = to_date(match_id[:8]) if len(match_id) >= 8 else None

            rows.append((
                match_id,
                gender.upper(),
                match_date,
                row.get("Tournament", "").strip() or None,
                row.get("Surface", "").strip() or None,
                row.get("Round", "").strip() or None,
                row.get("Player 1", "").strip() or None,
                row.get("Player 2", "").strip() or None,
                to_int(row.get("Winner")),
                to_int(row.get("w sets")),
                to_int(row.get("l sets")),
                row.get("Score", "").strip() or None,
                row.get("Status", "Completed").strip() or None,
            ))

    if rows:
        # Deduplicate by match_id — CSV may contain duplicate rows for the same match
        seen = {}
        for r in rows:
            seen[r[0]] = r  # r[0] is match_id; last writer wins
        rows = list(seen.values())

        with conn.cursor() as cur:
            psycopg2.extras.execute_values(cur, """
                INSERT INTO sa_charting_matches
                    (match_id, tour, date, tournament, surface, round,
                     server1, server2, winner, w_sets, l_sets, score, status)
                VALUES %s
                ON CONFLICT (match_id) DO UPDATE SET
                    tournament = EXCLUDED.tournament,
                    score      = EXCLUDED.score,
                    status     = EXCLUDED.status
            """, rows, page_size=200)
            inserted = cur.rowcount
        conn.commit()

    log.info(f"    {fpath.name}: {processed} processed, {inserted} upserted, {skipped} skipped")
    log_ingest(conn, "CHARTING_" + tour, fpath.name, "success", processed, inserted, skipped)


def ingest_charting_points(conn, repo_dir: Path, tour: str):
    """
    Load point-by-point charting data.
    The repo splits points into decade files (charting-m-points-2010s.csv etc.)
    OR provides a single charting-m-points.csv. We handle both.
    """
    gender = "m" if tour == "ATP" else "w"

    # Collect all matching points files (single or decade-split)
    import glob as _glob
    all_files = sorted(repo_dir.glob(f"charting-{gender}-points*.csv"))
    if not all_files:
        log.warning(f"  No charting points files found for {tour} in {repo_dir}")
        return

    processed = inserted = skipped = 0

    for fpath in all_files:
        fname = fpath.name
        if already_loaded(conn, "CHARTING_" + tour, fname):
            log.info(f"  Skipping {fname} (already loaded)")
            continue

        log.info(f"  Loading {fname} (this may take a few minutes) ...")
        file_processed = file_skipped = file_inserted = 0
        CHUNK = 2000
        rows = []

        def flush(rows):
            nonlocal inserted
            if not rows:
                return
            with conn.cursor() as cur:
                psycopg2.extras.execute_values(cur, """
                    INSERT INTO sa_charting_points (
                        match_id, set_no, game_no, point_no, server, serve_no,
                        p1_sets, p2_sets, p1_games, p2_games, p1_points, p2_points,
                        is_break_point, is_set_point, is_match_point, point_winner,
                        shot_sequence, serve_dir, serve_fault, rally_length,
                        point_end_type, last_shot_type, last_shot_dir
                    ) VALUES %s
                    ON CONFLICT (match_id, set_no, game_no, point_no, serve_no) DO NOTHING
                """, rows, page_size=500)
                inserted += cur.rowcount
            conn.commit()

        with open(fpath, encoding="utf-8", errors="replace") as f:
            reader = csv.DictReader(f)
            for row in reader:
                file_processed += 1
                processed += 1

                match_id = row.get("match_id", "").strip()
                if not match_id:
                    file_skipped += 1
                    skipped += 1
                    continue

                set_no   = to_int(row.get("set_no") or row.get("Set"))
                game_no  = to_int(row.get("game_no") or row.get("game"))
                point_no = to_int(row.get("point_no") or row.get("point"))
                serve_no = to_int(row.get("serve_no") or row.get("Serve"))
                server   = to_int(row.get("server") or row.get("Svr"))

                if not all([set_no, game_no, point_no is not None, serve_no]):
                    file_skipped += 1
                    skipped += 1
                    continue

                shot_seq = row.get("1st", "") or row.get("shot_seq", "") or ""
                parsed = parse_shot_sequence(shot_seq)

                rows.append((
                    match_id,
                    set_no, game_no, point_no, server, serve_no,
                    to_int(row.get("p1_sets") or row.get("Sets1")),
                    to_int(row.get("p2_sets") or row.get("Sets2")),
                    to_int(row.get("p1_games") or row.get("Games1")),
                    to_int(row.get("p2_games") or row.get("Games2")),
                    row.get("p1_points") or row.get("Pts1") or None,
                    row.get("p2_points") or row.get("Pts2") or None,
                    bool(to_int(row.get("isBreakPt") or row.get("bp", "0"))),
                    bool(to_int(row.get("isSetPt") or row.get("sp", "0"))),
                    bool(to_int(row.get("isMatchPt") or row.get("mp", "0"))),
                    to_int(row.get("PtWinner") or row.get("pw")),
                    shot_seq or None,
                    parsed.get("serve_dir"),
                    parsed.get("serve_fault", False),
                    parsed.get("rally_length", 0),
                    parsed.get("point_end_type"),
                    parsed.get("last_shot_type"),
                    parsed.get("last_shot_dir"),
                ))

                if len(rows) >= CHUNK:
                    flush(rows)
                    rows = []
                    if processed % 100000 == 0:
                        log.info(f"    ... {processed:,} points processed, {inserted:,} inserted")

        flush(rows)
        log.info(f"    {fname}: {file_processed:,} processed, {file_inserted:,} inserted, {file_skipped:,} skipped")
        log_ingest(conn, "CHARTING_" + tour, fname, "success", file_processed, file_inserted, file_skipped)

    log.info(f"  {tour} charting points total: {processed:,} processed, {inserted:,} inserted, {skipped:,} skipped")


# ─────────────────────────────────────────────
# MAIN JOBS
# ─────────────────────────────────────────────

def job_players(conn, tmpdir: Path):
    for tour, zip_url in [("ATP", SACKMANN_REPOS["ATP"]), ("WTA", SACKMANN_REPOS["WTA"])]:
        log.info(f"=== Players: {tour} ===")
        repo_dir = tmpdir / tour.lower()
        repo_dir.mkdir(exist_ok=True)
        extracted = download_repo_zip(zip_url, repo_dir)
        ingest_players(conn, extracted, tour)


def job_matches(conn, tmpdir: Path, year: Optional[int] = None):
    for tour, zip_url in [("ATP", SACKMANN_REPOS["ATP"]), ("WTA", SACKMANN_REPOS["WTA"])]:
        log.info(f"=== Matches: {tour} {'(' + str(year) + ')' if year else '(all years)'} ===")
        repo_dir = tmpdir / tour.lower()
        if not (repo_dir / "extracted").exists():
            repo_dir.mkdir(exist_ok=True)
            extracted = download_repo_zip(zip_url, repo_dir)
        else:
            extracted = next(repo_dir.iterdir())

        # Load players first (foreign key deps)
        ingest_players(conn, extracted, tour)
        ingest_matches(conn, extracted, tour, year=year)


def job_rankings(conn, tmpdir: Path):
    for tour, zip_url in [("ATP", SACKMANN_REPOS["ATP"]), ("WTA", SACKMANN_REPOS["WTA"])]:
        log.info(f"=== Rankings: {tour} ===")
        repo_dir = tmpdir / tour.lower()
        repo_dir.mkdir(exist_ok=True)
        extracted = download_repo_zip(zip_url, repo_dir)
        ingest_rankings(conn, extracted, tour)


def job_charting(conn, tmpdir: Path):
    log.info("=== Match Charting Project ===")
    repo_dir = tmpdir / "charting"
    repo_dir.mkdir(exist_ok=True)
    extracted = download_repo_zip(SACKMANN_REPOS["CHARTING"], repo_dir)

    for tour in ["ATP", "WTA"]:
        ingest_charting_matches(conn, extracted, tour)
        ingest_charting_points(conn, extracted, tour)


def job_all(conn, tmpdir: Path):
    """Full initial load: players, matches, rankings, charting."""
    for tour, zip_url in [("ATP", SACKMANN_REPOS["ATP"]), ("WTA", SACKMANN_REPOS["WTA"])]:
        log.info(f"\n{'='*50}")
        log.info(f"=== Full load: {tour} ===")
        log.info(f"{'='*50}")
        repo_dir = tmpdir / tour.lower()
        repo_dir.mkdir(exist_ok=True)
        extracted = download_repo_zip(zip_url, repo_dir)
        ingest_players(conn, extracted, tour)
        ingest_matches(conn, extracted, tour)
        ingest_rankings(conn, extracted, tour)

    log.info(f"\n{'='*50}")
    log.info("=== Charting Project ===")
    log.info(f"{'='*50}")
    job_charting(conn, tmpdir)


# ─────────────────────────────────────────────
# ENTRY POINT
# ─────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="ratethat.tennis — Sackmann data ingestion")
    parser.add_argument("--job", choices=["all", "players", "matches", "rankings", "charting"],
                        default="all", help="Which job to run")
    parser.add_argument("--year", type=int, default=None,
                        help="Load only a specific year (for matches job)")
    parser.add_argument("--schema-only", action="store_true",
                        help="Apply schema SQL and exit")
    parser.add_argument("--keep-tmp", action="store_true",
                        help="Don't delete downloaded repo zips after ingestion")
    args = parser.parse_args()

    conn = get_conn()

    if args.schema_only:
        log.info("Applying Sackmann schema...")
        run_schema(conn)
        conn.close()
        return

    # Always ensure schema exists
    run_schema(conn)

    # Use a temp directory for downloaded repos
    tmpdir = Path(tempfile.mkdtemp(prefix="sackmann_"))
    log.info(f"Working directory: {tmpdir}")

    try:
        if args.job == "all":
            job_all(conn, tmpdir)
        elif args.job == "players":
            job_players(conn, tmpdir)
        elif args.job == "matches":
            job_matches(conn, tmpdir, year=args.year)
        elif args.job == "rankings":
            job_rankings(conn, tmpdir)
        elif args.job == "charting":
            job_charting(conn, tmpdir)

        log.info("\n✅ Ingestion complete.")

    finally:
        if not args.keep_tmp:
            shutil.rmtree(tmpdir, ignore_errors=True)
        conn.close()


if __name__ == "__main__":
    main()
