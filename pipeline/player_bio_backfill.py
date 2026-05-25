#!/usr/bin/env python3
"""
ratethat.tennis — Player Bio Backfill
======================================
Backfills height_cm, hand, and current ranking data into the players table
using Sackmann historical data.

Two match strategies:
  1. Direct ID match — players with a sackmann external_id in player_external_ids
  2. Name match — fuzzy (exact case-insensitive) fallback for unmapped players

Rankings are pulled from sa_rankings (most recent per player) and used to
update players.current_rank / ranking_points where currently null.

Usage:
    python3 -m pipeline.player_bio_backfill
    python3 -m pipeline.player_bio_backfill --dry-run
    python3 -m pipeline.player_bio_backfill --skip-rankings
    python3 -m pipeline.player_bio_backfill --dry-run --verbose
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

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
log = logging.getLogger("bio-backfill")


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


# ─────────────────────────────────────────────
# PHASE 1 — BACKFILL VIA EXTERNAL ID
# ─────────────────────────────────────────────

def backfill_by_id(cur, dry_run: bool, verbose: bool) -> dict:
    """
    For players with a 'sackmann' external_id, join directly to sa_players
    and update height_cm / hand where our record is currently null.
    """
    cur.execute("""
        SELECT
            p.id            AS player_id,
            p.full_name     AS player_name,
            p.height_cm     AS current_height,
            p.hand          AS current_hand,
            sp.height_cm    AS sa_height,
            sp.hand         AS sa_hand
        FROM players p
        JOIN player_external_ids pei
            ON pei.player_id = p.id AND pei.source = 'sackmann'
        JOIN sa_players sp
            ON sp.player_id = pei.external_id::INTEGER
        WHERE
            (p.height_cm IS NULL AND sp.height_cm IS NOT NULL)
            OR (p.hand IS NULL AND sp.hand IS NOT NULL AND sp.hand != 'U')
    """)
    rows = cur.fetchall()

    stats = {"matched": len(rows), "updated": 0, "skipped": 0}

    for row in rows:
        new_height = row["sa_height"] if row["current_height"] is None else None
        new_hand = row["sa_hand"] if (row["current_hand"] is None and row["sa_hand"] not in (None, "U")) else None

        if new_height is None and new_hand is None:
            stats["skipped"] += 1
            continue

        if verbose:
            changes = []
            if new_height:
                changes.append(f"height_cm={new_height}")
            if new_hand:
                changes.append(f"hand={new_hand}")
            log.info(f"  [ID match] {row['player_name']} (id={row['player_id']}): {', '.join(changes)}")

        if not dry_run:
            if new_height is not None and new_hand is not None:
                cur.execute(
                    "UPDATE players SET height_cm = %s, hand = %s WHERE id = %s",
                    (new_height, new_hand, row["player_id"]),
                )
            elif new_height is not None:
                cur.execute(
                    "UPDATE players SET height_cm = %s WHERE id = %s",
                    (new_height, row["player_id"]),
                )
            else:
                cur.execute(
                    "UPDATE players SET hand = %s WHERE id = %s",
                    (new_hand, row["player_id"]),
                )

        stats["updated"] += 1

    return stats


# ─────────────────────────────────────────────
# PHASE 2 — BACKFILL VIA NAME MATCH
# ─────────────────────────────────────────────

def backfill_by_name(cur, dry_run: bool, verbose: bool) -> dict:
    """
    For players WITHOUT a sackmann external_id (or where id-based join didn't match),
    attempt an exact case-insensitive name match against sa_players.full_name.

    Only updates where exactly one sa_players row matches (no ambiguity).
    """
    # Players that still need at least one of height/hand
    cur.execute("""
        SELECT p.id AS player_id, p.full_name, p.height_cm, p.hand
        FROM players p
        WHERE (p.height_cm IS NULL OR p.hand IS NULL)
          AND p.id NOT IN (
              SELECT player_id FROM player_external_ids WHERE source = 'sackmann'
          )
    """)
    candidates = cur.fetchall()

    stats = {"candidates": len(candidates), "name_matched": 0, "updated": 0, "ambiguous": 0, "no_match": 0}

    for player in candidates:
        cur.execute(
            """
            SELECT player_id, hand, height_cm
            FROM sa_players
            WHERE LOWER(TRIM(full_name)) = LOWER(TRIM(%s))
            """,
            (player["full_name"],),
        )
        matches = cur.fetchall()

        if len(matches) == 0:
            stats["no_match"] += 1
            continue

        if len(matches) > 1:
            # Multiple Sackmann rows with this name — too ambiguous to trust
            if verbose:
                log.info(
                    f"  [Name match] AMBIGUOUS — {player['full_name']}: "
                    f"{len(matches)} Sackmann rows found, skipping"
                )
            stats["ambiguous"] += 1
            continue

        sa = matches[0]
        stats["name_matched"] += 1

        new_height = sa["height_cm"] if (player["height_cm"] is None and sa["height_cm"] is not None) else None
        new_hand = sa["hand"] if (player["hand"] is None and sa["hand"] not in (None, "U")) else None

        if new_height is None and new_hand is None:
            continue

        if verbose:
            changes = []
            if new_height:
                changes.append(f"height_cm={new_height}")
            if new_hand:
                changes.append(f"hand={new_hand}")
            log.info(
                f"  [Name match] {player['full_name']} (id={player['player_id']}): {', '.join(changes)}"
            )

        if not dry_run:
            if new_height is not None and new_hand is not None:
                cur.execute(
                    "UPDATE players SET height_cm = %s, hand = %s WHERE id = %s",
                    (new_height, new_hand, player["player_id"]),
                )
            elif new_height is not None:
                cur.execute(
                    "UPDATE players SET height_cm = %s WHERE id = %s",
                    (new_height, player["player_id"]),
                )
            else:
                cur.execute(
                    "UPDATE players SET hand = %s WHERE id = %s",
                    (new_hand, player["player_id"]),
                )

        stats["updated"] += 1

    return stats


# ─────────────────────────────────────────────
# PHASE 3 — BACKFILL RANKINGS
# ─────────────────────────────────────────────

def backfill_rankings(cur, dry_run: bool, verbose: bool) -> dict:
    """
    Pull the most recent ranking per sa_players entry from sa_rankings.
    Update players.current_rank and ranking_points where currently null,
    joining via player_external_ids (sackmann) or name match.
    """
    # Check sa_rankings exists
    if not table_exists(cur, "sa_rankings"):
        log.warning("sa_rankings table does not exist — skipping rankings backfill")
        return {"skipped": True}

    # Check if it has rows
    cur.execute("SELECT COUNT(*) AS cnt FROM sa_rankings")
    count = cur.fetchone()["cnt"]
    if count == 0:
        log.warning("sa_rankings table is empty — skipping rankings backfill")
        return {"empty": True}

    log.info(f"sa_rankings has {count:,} rows — proceeding with rankings backfill")

    # Strategy A: via external_id
    cur.execute("""
        SELECT
            p.id            AS player_id,
            p.full_name,
            p.current_rank,
            p.ranking_points,
            r.rank          AS sa_rank,
            r.points        AS sa_points,
            r.ranking_date
        FROM players p
        JOIN player_external_ids pei
            ON pei.player_id = p.id AND pei.source = 'sackmann'
        JOIN LATERAL (
            SELECT rank, points, ranking_date
            FROM sa_rankings
            WHERE player_id = pei.external_id::INTEGER
            ORDER BY ranking_date DESC
            LIMIT 1
        ) r ON TRUE
        WHERE p.current_rank IS NULL OR p.ranking_points IS NULL
    """)
    id_rows = cur.fetchall()

    stats = {"id_matched": 0, "name_matched": 0, "updated": 0, "no_match": 0}

    def apply_ranking(player_id: int, full_name: str, current_rank: Optional[int],
                      current_pts: Optional[int], sa_rank: int, sa_points: int,
                      ranking_date, source: str):
        new_rank = sa_rank if current_rank is None else None
        new_pts = sa_points if current_pts is None else None

        if new_rank is None and new_pts is None:
            return False

        if verbose:
            changes = []
            if new_rank:
                changes.append(f"current_rank={new_rank}")
            if new_pts:
                changes.append(f"ranking_points={new_pts}")
            log.info(
                f"  [Ranking/{source}] {full_name} (id={player_id}): "
                f"{', '.join(changes)} (from {ranking_date})"
            )

        if not dry_run:
            if new_rank is not None and new_pts is not None:
                cur.execute(
                    "UPDATE players SET current_rank = %s, ranking_points = %s WHERE id = %s",
                    (new_rank, new_pts, player_id),
                )
            elif new_rank is not None:
                cur.execute(
                    "UPDATE players SET current_rank = %s WHERE id = %s",
                    (new_rank, player_id),
                )
            else:
                cur.execute(
                    "UPDATE players SET ranking_points = %s WHERE id = %s",
                    (new_pts, player_id),
                )
        return True

    for row in id_rows:
        updated = apply_ranking(
            row["player_id"], row["full_name"],
            row["current_rank"], row["ranking_points"],
            row["sa_rank"], row["sa_points"], row["ranking_date"],
            source="ID",
        )
        stats["id_matched"] += 1
        if updated:
            stats["updated"] += 1

    # Strategy B: name match for remaining players without external_id
    cur.execute("""
        SELECT p.id AS player_id, p.full_name, p.current_rank, p.ranking_points
        FROM players p
        WHERE (p.current_rank IS NULL OR p.ranking_points IS NULL)
          AND p.id NOT IN (
              SELECT player_id FROM player_external_ids WHERE source = 'sackmann'
          )
    """)
    remaining = cur.fetchall()

    for player in remaining:
        cur.execute(
            """
            SELECT sp.player_id AS sa_player_id
            FROM sa_players sp
            WHERE LOWER(TRIM(sp.full_name)) = LOWER(TRIM(%s))
            """,
            (player["full_name"],),
        )
        sa_matches = cur.fetchall()

        if len(sa_matches) != 1:
            stats["no_match"] += 1
            continue

        sa_player_id = sa_matches[0]["sa_player_id"]

        cur.execute(
            """
            SELECT rank, points, ranking_date
            FROM sa_rankings
            WHERE player_id = %s
            ORDER BY ranking_date DESC
            LIMIT 1
            """,
            (sa_player_id,),
        )
        ranking = cur.fetchone()

        if not ranking:
            stats["no_match"] += 1
            continue

        stats["name_matched"] += 1
        updated = apply_ranking(
            player["player_id"], player["full_name"],
            player["current_rank"], player["ranking_points"],
            ranking["rank"], ranking["points"], ranking["ranking_date"],
            source="Name",
        )
        if updated:
            stats["updated"] += 1

    return stats


# ─────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────

def run(dry_run: bool, verbose: bool, skip_rankings: bool):
    log.info("=" * 60)
    log.info("Player Bio Backfill — ratethat.tennis")
    log.info(f"Mode: {'DRY RUN (no writes)' if dry_run else 'LIVE'}")
    log.info("=" * 60)

    conn = get_conn()
    try:
        cur = conn.cursor()

        # ── Phase 1: ID-based bio update ──────────────────────────
        log.info("")
        log.info("Phase 1: Backfill bio via sackmann external_id")
        id_stats = backfill_by_id(cur, dry_run, verbose)
        log.info(
            f"  Rows eligible:  {id_stats['matched']}"
        )
        log.info(f"  Updated:        {id_stats['updated']}")
        log.info(f"  Skipped:        {id_stats['skipped']}")

        # ── Phase 2: Name-based bio update ────────────────────────
        log.info("")
        log.info("Phase 2: Backfill bio via name match (no external_id)")
        name_stats = backfill_by_name(cur, dry_run, verbose)
        log.info(f"  Candidates:     {name_stats['candidates']}")
        log.info(f"  Name matched:   {name_stats['name_matched']}")
        log.info(f"  Updated:        {name_stats['updated']}")
        log.info(f"  Ambiguous:      {name_stats['ambiguous']}")
        log.info(f"  No Sackmann match: {name_stats['no_match']}")

        # ── Phase 3: Rankings ─────────────────────────────────────
        if not skip_rankings:
            log.info("")
            log.info("Phase 3: Backfill rankings from sa_rankings")
            rank_stats = backfill_rankings(cur, dry_run, verbose)
            if not rank_stats.get("skipped") and not rank_stats.get("empty"):
                log.info(f"  ID-matched:     {rank_stats['id_matched']}")
                log.info(f"  Name-matched:   {rank_stats['name_matched']}")
                log.info(f"  Updated:        {rank_stats['updated']}")
                log.info(f"  No match:       {rank_stats['no_match']}")
        else:
            log.info("")
            log.info("Phase 3: Rankings — skipped (--skip-rankings)")

        if not dry_run:
            conn.commit()
            log.info("")
            log.info("Changes committed to database.")
        else:
            conn.rollback()
            log.info("")
            log.info("Dry run — no changes written.")

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
        description="Backfill player height, hand, and ranking data from Sackmann tables."
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be updated without writing to the database.",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Log every individual player update.",
    )
    parser.add_argument(
        "--skip-rankings",
        action="store_true",
        help="Skip the sa_rankings phase (bio fields only).",
    )
    args = parser.parse_args()

    run(dry_run=args.dry_run, verbose=args.verbose, skip_rankings=args.skip_rankings)
