#!/usr/bin/env python3
"""
ratethat.tennis — Charting Project → serve_zones aggregation
=============================================================
Reads point-level serve direction data from sa_charting_points and
sa_charting_matches, maps charting player names to our players.id,
aggregates W/B/T placement percentages by player/surface/serve_number/
court_side, and upserts results into the serve_zones table.

Minimum data threshold: 20 points per (player, surface, serve_number,
court_side, zone) cell — cells below this are excluded.

Prerequisite:
    Run Sackmann charting ingest first:
        python3 -m pipeline.sackmann_ingest --job charting

Usage:
    python3 -m pipeline.charting_to_serve_zones
    python3 -m pipeline.charting_to_serve_zones --dry-run
    python3 -m pipeline.charting_to_serve_zones --min-samples 50
    python3 -m pipeline.charting_to_serve_zones --verbose
"""

import os
import sys
import logging
import argparse
import psycopg2
import psycopg2.extras
from typing import Optional

# ─────────────────────────────────────────────
# CONFIG
# ─────────────────────────────────────────────

DB_URL = (
    os.environ.get("DATABASE_PUBLIC_URL")
    or os.environ.get("DATABASE_URL")
    or "postgresql://postgres:DEKANqBEjmOvOGLCfzaQIBaKzhKcyKwS@switchyard.proxy.rlwy.net:39343/railway"
).strip()

DEFAULT_MIN_SAMPLES = 20

# Sackmann charting encode: T=T, B=Body, W=Wide
# Our serve_zones.zone CHECK: 'wide', 'body', 't'
SERVE_DIR_MAP = {
    "T": "t",
    "B": "body",
    "W": "wide",
}

# Sackmann charting surface strings → our surfaces.name
SURFACE_NAME_MAP = {
    "Hard":    "Hard",
    "Clay":    "Clay",
    "Grass":   "Grass",
    "Carpet":  "Carpet",
    "Indoor":  "Indoor Hard",
}

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
log = logging.getLogger("charting-serve-zones")


# ─────────────────────────────────────────────
# DB HELPERS
# ─────────────────────────────────────────────

def get_conn():
    conn = psycopg2.connect(DB_URL)
    conn.cursor_factory = psycopg2.extras.RealDictCursor
    return conn


def table_exists(cur, table_name: str) -> bool:
    cur.execute(
        "SELECT EXISTS (SELECT FROM information_schema.tables WHERE table_name = %s)",
        (table_name,),
    )
    return cur.fetchone()["exists"]


def get_table_columns(cur, table_name: str) -> list[str]:
    cur.execute(
        """
        SELECT column_name
        FROM information_schema.columns
        WHERE table_name = %s
        ORDER BY ordinal_position
        """,
        (table_name,),
    )
    return [row["column_name"] for row in cur.fetchall()]


def get_row_count(cur, table_name: str) -> int:
    cur.execute(f"SELECT COUNT(*) AS cnt FROM {table_name}")
    return cur.fetchone()["cnt"]


# ─────────────────────────────────────────────
# PRE-FLIGHT CHECKS
# ─────────────────────────────────────────────

def preflight(cur) -> bool:
    """
    Verify charting tables exist and have data.
    Returns True if it's safe to proceed, False otherwise.
    """
    if not table_exists(cur, "sa_charting_points"):
        log.error(
            "sa_charting_points table does not exist.\n"
            "  Run: python3 -m pipeline.sackmann_ingest --job charting"
        )
        return False

    point_count = get_row_count(cur, "sa_charting_points")
    if point_count == 0:
        log.error(
            "sa_charting_points table is empty — run: "
            "python3 -m pipeline.sackmann_ingest --job charting first"
        )
        return False

    log.info(f"sa_charting_points: {point_count:,} rows found")

    # Check sa_charting_matches
    has_matches_table = table_exists(cur, "sa_charting_matches")
    if has_matches_table:
        match_count = get_row_count(cur, "sa_charting_matches")
        log.info(f"sa_charting_matches: {match_count:,} rows found")
    else:
        log.warning("sa_charting_matches table not found — surface info will be unavailable")

    # Introspect columns
    point_cols = get_table_columns(cur, "sa_charting_points")
    log.info(f"sa_charting_points columns: {point_cols}")

    required_cols = {"serve_dir", "serve_no", "server", "match_id"}
    missing = required_cols - set(point_cols)
    if missing:
        log.error(f"sa_charting_points is missing expected columns: {missing}")
        log.error("Schema may differ from expected — cannot proceed safely.")
        return False

    # Check serve_zones target table
    if not table_exists(cur, "serve_zones"):
        log.error(
            "serve_zones table does not exist. "
            "Run: psql $DATABASE_URL -f pipeline/schema_additions.sql"
        )
        return False

    return True


# ─────────────────────────────────────────────
# SURFACE LOOKUP
# ─────────────────────────────────────────────

def build_surface_lookup(cur) -> dict[str, int]:
    """Return {surface_name: surfaces.id} mapping."""
    cur.execute("SELECT id, name FROM surfaces")
    return {row["name"]: row["id"] for row in cur.fetchall()}


# ─────────────────────────────────────────────
# PLAYER NAME → players.id MAPPING
# ─────────────────────────────────────────────

def build_player_name_map(cur) -> dict[str, int]:
    """
    Build a lookup: normalised_name → players.id

    Priority order:
      1. sa_players.full_name matched via sackmann external_id → players.id
      2. Direct full_name match from players table
    """
    mapping: dict[str, int] = {}

    # Strategy 1: via external_id
    cur.execute("""
        SELECT LOWER(TRIM(sp.full_name)) AS norm_name, p.id AS player_id
        FROM sa_players sp
        JOIN player_external_ids pei
            ON pei.external_id = sp.player_id::TEXT AND pei.source = 'sackmann'
        JOIN players p ON p.id = pei.player_id
    """)
    for row in cur.fetchall():
        mapping[row["norm_name"]] = row["player_id"]

    # Strategy 2: direct name match (fill gaps — don't override ID-based matches)
    cur.execute("SELECT id, full_name FROM players")
    for row in cur.fetchall():
        norm = row["full_name"].lower().strip() if row["full_name"] else None
        if norm and norm not in mapping:
            mapping[norm] = row["id"]

    log.info(f"Player name map built: {len(mapping):,} entries")
    return mapping


# ─────────────────────────────────────────────
# AGGREGATE CHARTING DATA
# ─────────────────────────────────────────────

def aggregate_serve_zones(
    cur,
    surface_lookup: dict[str, int],
    player_name_map: dict[str, int],
    min_samples: int,
    verbose: bool,
) -> list[dict]:
    """
    Aggregate sa_charting_points into per-player/surface/serve_number/court_side/zone
    counts and percentages.

    Returns a list of dicts ready for upsert into serve_zones.
    """
    has_matches = table_exists(cur, "sa_charting_matches")

    if has_matches:
        # Join to sa_charting_matches to get surface
        query = """
            WITH point_data AS (
                SELECT
                    cp.match_id,
                    cp.server,
                    cp.serve_no,
                    cp.serve_dir,
                    cp.set_no,
                    cp.game_no,
                    cm.server1,
                    cm.server2,
                    cm.surface
                FROM sa_charting_points cp
                JOIN sa_charting_matches cm ON cm.match_id = cp.match_id
                WHERE
                    cp.serve_dir IS NOT NULL
                    AND cp.serve_dir IN ('T', 'B', 'W')
                    AND cp.serve_no IN (1, 2)
                    AND (cp.serve_fault IS NULL OR cp.serve_fault = FALSE)
            ),
            -- Determine who is serving each point (server 1 or 2 maps to player name)
            named AS (
                SELECT
                    match_id,
                    surface,
                    CASE WHEN server = 1 THEN server1 ELSE server2 END AS player_name,
                    serve_no,
                    -- Court side from game number: odd game = deuce, even game = ad
                    -- (game 1 in a set is server's first service game)
                    CASE WHEN (game_no % 2) = 1 THEN 'deuce' ELSE 'ad' END AS court_side,
                    serve_dir
                FROM point_data
            )
            SELECT
                player_name,
                surface,
                serve_no        AS serve_number,
                court_side,
                serve_dir       AS zone_raw,
                COUNT(*)        AS zone_count
            FROM named
            WHERE player_name IS NOT NULL
            GROUP BY player_name, surface, serve_no, court_side, serve_dir
            ORDER BY player_name, surface, serve_no, court_side, serve_dir
        """
    else:
        # No surface info — aggregate without surface (surface_id will be NULL)
        log.warning("No sa_charting_matches table — aggregating without surface breakdown")
        query = """
            WITH named AS (
                SELECT
                    cp.match_id,
                    NULL::TEXT AS surface,
                    cp.server,
                    cp.serve_no,
                    CASE WHEN (cp.game_no % 2) = 1 THEN 'deuce' ELSE 'ad' END AS court_side,
                    cp.serve_dir
                FROM sa_charting_points cp
                WHERE
                    cp.serve_dir IS NOT NULL
                    AND cp.serve_dir IN ('T', 'B', 'W')
                    AND cp.serve_no IN (1, 2)
                    AND (cp.serve_fault IS NULL OR cp.serve_fault = FALSE)
            )
            SELECT
                NULL::TEXT AS player_name,
                surface,
                serve_no   AS serve_number,
                court_side,
                serve_dir  AS zone_raw,
                COUNT(*)   AS zone_count
            FROM named
            GROUP BY surface, serve_no, court_side, serve_dir
            ORDER BY surface, serve_no, court_side, serve_dir
        """

    log.info("Running serve direction aggregation query...")
    cur.execute(query)
    raw_rows = cur.fetchall()
    log.info(f"Raw aggregation: {len(raw_rows):,} rows")

    # Group into (player_name, surface, serve_number, court_side) → {zone: count}
    from collections import defaultdict
    grouped: dict = defaultdict(lambda: defaultdict(int))

    for row in raw_rows:
        key = (
            (row["player_name"] or "").strip() if row["player_name"] else None,
            row["surface"],
            row["serve_number"],
            row["court_side"],
        )
        zone = row["zone_raw"]
        grouped[key][zone] += row["zone_count"]

    results = []
    skipped_player = 0
    skipped_surface = 0
    skipped_min_samples = 0

    for (player_name, surface, serve_number, court_side), zone_counts in grouped.items():
        total = sum(zone_counts.values())

        # Resolve player_id
        if player_name is None:
            player_id = None
        else:
            norm = player_name.lower().strip()
            player_id = player_name_map.get(norm)
            if player_id is None:
                skipped_player += 1
                if verbose:
                    log.debug(f"  No player match for: {player_name!r}")
                continue

        # Resolve surface_id
        surface_id = None
        if surface:
            mapped_surface = SURFACE_NAME_MAP.get(surface, surface)
            surface_id = surface_lookup.get(mapped_surface)
            if surface_id is None and verbose:
                log.debug(f"  Unknown surface: {surface!r}")
                skipped_surface += 1

        # Emit one row per zone
        for zone_raw, count in zone_counts.items():
            if count < min_samples:
                skipped_min_samples += 1
                continue

            zone = SERVE_DIR_MAP.get(zone_raw)
            if zone is None:
                continue

            pct = round((count / total) * 100, 2)

            results.append({
                "player_id":    player_id,
                "surface_id":   surface_id,
                "serve_number": serve_number,
                "court_side":   court_side,
                "zone":         zone,
                "pct":          pct,
                "sample_size":  count,
            })

    log.info(f"Aggregation complete:")
    log.info(f"  Zones to upsert:         {len(results):,}")
    log.info(f"  Skipped (no player map): {skipped_player:,}")
    log.info(f"  Skipped (< {min_samples} samples):  {skipped_min_samples:,}")
    if skipped_surface:
        log.info(f"  Skipped (unknown surface): {skipped_surface:,}")

    return results


# ─────────────────────────────────────────────
# UPSERT INTO serve_zones
# ─────────────────────────────────────────────

def upsert_serve_zones(cur, rows: list[dict], dry_run: bool, verbose: bool) -> int:
    """
    Upsert rows into serve_zones.
    Returns count of rows processed.
    """
    if not rows:
        log.info("No rows to upsert.")
        return 0

    upsert_sql = """
        INSERT INTO serve_zones
            (player_id, surface_id, serve_number, court_side, zone, pct, sample_size, updated_at)
        VALUES
            (%(player_id)s, %(surface_id)s, %(serve_number)s, %(court_side)s,
             %(zone)s, %(pct)s, %(sample_size)s, NOW())
        ON CONFLICT (player_id, surface_id, serve_number, court_side, zone)
        DO UPDATE SET
            pct         = EXCLUDED.pct,
            sample_size = EXCLUDED.sample_size,
            updated_at  = NOW()
    """

    count = 0
    for row in rows:
        if verbose:
            log.info(
                f"  serve_zones upsert: player={row['player_id']} "
                f"surface_id={row['surface_id']} "
                f"serve={row['serve_number']} side={row['court_side']} "
                f"zone={row['zone']} pct={row['pct']}% n={row['sample_size']}"
            )
        if not dry_run:
            cur.execute(upsert_sql, row)
        count += 1

    return count


# ─────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────

def run(dry_run: bool, verbose: bool, min_samples: int):
    log.info("=" * 60)
    log.info("Charting → serve_zones — ratethat.tennis")
    log.info(f"Mode: {'DRY RUN (no writes)' if dry_run else 'LIVE'}")
    log.info(f"Minimum samples per zone cell: {min_samples}")
    log.info("=" * 60)

    conn = get_conn()
    try:
        cur = conn.cursor()

        # ── Pre-flight ─────────────────────────────────────────────
        log.info("")
        log.info("Pre-flight checks...")
        if not preflight(cur):
            sys.exit(1)

        # ── Build lookup tables ────────────────────────────────────
        log.info("")
        log.info("Building lookup tables...")
        surface_lookup = build_surface_lookup(cur)
        log.info(f"  Surfaces known: {list(surface_lookup.keys())}")

        player_name_map = build_player_name_map(cur)

        # ── Aggregate ─────────────────────────────────────────────
        log.info("")
        log.info("Aggregating serve direction data...")
        rows = aggregate_serve_zones(cur, surface_lookup, player_name_map, min_samples, verbose)

        if not rows:
            log.warning("No rows produced after aggregation — nothing to write.")
            return

        # ── Upsert ─────────────────────────────────────────────────
        log.info("")
        log.info(f"Upserting {len(rows):,} rows into serve_zones...")
        count = upsert_serve_zones(cur, rows, dry_run, verbose)

        if not dry_run:
            conn.commit()
            log.info("")
            log.info(f"Done. {count:,} serve_zones rows committed.")
        else:
            conn.rollback()
            log.info("")
            log.info(f"Dry run complete. {count:,} rows would be upserted (nothing written).")

    except Exception as e:
        conn.rollback()
        log.error(f"Fatal error: {e}", exc_info=True)
        sys.exit(1)
    finally:
        conn.close()


if __name__ == "__main__":
    # Load .env from project root if present
    env_path = os.path.join(os.path.dirname(__file__), "..", ".env")
    if os.path.exists(env_path):
        with open(env_path) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    os.environ.setdefault(k.strip(), v.strip())

    parser = argparse.ArgumentParser(
        description="Aggregate Sackmann charting data into serve_zones table."
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be upserted without writing to the database.",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Log every individual upsert row.",
    )
    parser.add_argument(
        "--min-samples",
        type=int,
        default=DEFAULT_MIN_SAMPLES,
        help=f"Minimum data points per zone cell (default: {DEFAULT_MIN_SAMPLES}).",
    )
    args = parser.parse_args()

    run(dry_run=args.dry_run, verbose=args.verbose, min_samples=args.min_samples)
