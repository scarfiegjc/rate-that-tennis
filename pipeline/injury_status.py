"""
ratethat.tennis — Player injury / status ingestion
====================================================
Pulls active injury / withdrawal / illness flags from a few public sources
and writes them into player_injury_status. The predictor reads from this
table to soften probabilities and surface warnings in the Intelligence tab.

Sources implemented:
  - infer_from_recent_matches: derives "physical concern" rows from recent
    retirements, walkovers, and short-match losses in our own matches table
    (no external dependency — works offline).

Sources stubbed (to be implemented):
  - scrape_atp_withdrawals: parse ATP withdrawal / walkover announcements
  - scrape_wta_withdrawals: same for WTA
  - api_tennis_status:      pull `player_status` field from api-tennis.com
                             (if available — currently the API exposes
                             `event_status` per match but not per player)

Run:
    python3 -m pipeline.injury_status                # all sources
    python3 -m pipeline.injury_status --source recent_matches
    python3 -m pipeline.injury_status --source manual --player-id 123 \
            --status injury --severity moderate --body-part wrist \
            --notes "Withdrew from Rome QF citing wrist soreness"
"""

from __future__ import annotations

import os
import sys
import argparse
import logging
import re
from datetime import datetime, timedelta
from typing import Optional

import psycopg2
import psycopg2.extras


DB_URL = (
    os.environ.get("DATABASE_PUBLIC_URL")
    or os.environ.get("DATABASE_URL")
    or "postgresql://postgres:DEKANqBEjmOvOGLCfzaQIBaKzhKcyKwS@switchyard.proxy.rlwy.net:39343/railway"
).strip()

log = logging.getLogger("rtt-injury")
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")


# ─── Schema bootstrap ────────────────────────────────────────────────────────

def ensure_schema(conn) -> None:
    """Apply player_injury_status schema if missing. Idempotent."""
    schema_path = os.path.join(os.path.dirname(__file__), "injury_status_schema.sql")
    if not os.path.exists(schema_path):
        log.warning(f"Schema file not found at {schema_path} — skipping bootstrap")
        return
    with open(schema_path) as f:
        sql = f.read()
    with conn.cursor() as cur:
        cur.execute(sql)
    conn.commit()


# ─── Source 1: infer from recent matches ─────────────────────────────────────

def infer_from_recent_matches(conn, lookback_days: int = 14) -> int:
    """
    Derive "physical concern" rows from the last N days of matches in our DB.
    Heuristics:
      • event_status = 'Retired'      → moderate concern, expires in 7 days
      • event_status = 'Walkover'     → moderate concern, expires in 5 days
      • Straight-set bagel (6-0 6-0)  → minor concern (could be a thrashing
                                         OR a player tanking due to physical issue),
                                         expires in 3 days
    Walkovers / retirements are recorded against the loser. We do NOT mark
    bagel-receivers automatically — the signal-to-noise on that is too low to
    auto-mark, but Level-1 market divergence will catch genuine cases.

    Returns the number of rows upserted.
    """
    cutoff = (datetime.utcnow() - timedelta(days=lookback_days)).date()
    inserted = 0

    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(
            """
            SELECT m.id, m.event_date, m.event_status, m.final_result, m.winner,
                   m.first_player_id, m.second_player_id
            FROM matches m
            WHERE m.event_date >= %s
              AND m.event_status IN ('Retired', 'Walkover', 'Finished')
              AND m.first_player_id IS NOT NULL
              AND m.second_player_id IS NOT NULL
            """,
            (cutoff,)
        )
        rows = cur.fetchall()

    log.info(f"Scanning {len(rows):,} recent matches for physical concerns...")

    with conn.cursor() as cur:
        for r in rows:
            status_raw = (r["event_status"] or "").strip()
            losing_pid = None
            severity = None
            expires_days = 7
            kind = None
            notes = None

            if status_raw == "Retired":
                # Loser retired — physical issue strongly implied
                losing_pid = (r["second_player_id"] if r["winner"] == "First Player"
                              else r["first_player_id"])
                severity = "moderate"
                kind = "injury"
                expires_days = 7
                notes = f"Retired during match on {r['event_date']}"
            elif status_raw == "Walkover":
                # Walkover — loser didn't show
                losing_pid = (r["second_player_id"] if r["winner"] == "First Player"
                              else r["first_player_id"])
                severity = "moderate"
                kind = "injury"
                expires_days = 5
                notes = f"Walkover on {r['event_date']}"
            else:
                continue

            if losing_pid is None:
                continue

            cur.execute(
                """
                INSERT INTO player_injury_status
                    (player_id, status, severity, body_part, notes, source, source_url,
                     noted_at, expires_at)
                VALUES (%s, %s, %s, NULL, %s, 'recent_matches', NULL,
                        %s::timestamptz, %s::timestamptz)
                ON CONFLICT DO NOTHING
                """,
                (
                    losing_pid, kind, severity, notes,
                    f"{r['event_date']} 12:00:00",
                    (datetime.combine(r['event_date'], datetime.min.time())
                     + timedelta(days=expires_days)),
                )
            )
            if cur.rowcount > 0:
                inserted += 1

    conn.commit()
    log.info(f"  Inserted {inserted} new injury rows from recent matches")
    return inserted


# ─── Source 2/3: ATP / WTA withdrawal scrapers (stubs) ───────────────────────
#
# These are intentional placeholders. The right sources for live injury data
# vary: the ATP publishes withdrawals on https://www.atptour.com/en/news at
# times of major events; WTA does similar. tennis-explorer and other
# unofficial sites aggregate. A full scraper is a project-week task, so I'm
# leaving the function shape ready for someone to implement against the
# source they choose.

def scrape_atp_withdrawals(conn) -> int:
    """Stub. Should fetch the ATP withdrawal list and upsert rows.
    Returns 0 until implemented."""
    log.info("scrape_atp_withdrawals: not yet implemented (stub)")
    return 0


def scrape_wta_withdrawals(conn) -> int:
    """Stub. Should fetch the WTA withdrawal list and upsert rows.
    Returns 0 until implemented."""
    log.info("scrape_wta_withdrawals: not yet implemented (stub)")
    return 0


# ─── Manual entry ────────────────────────────────────────────────────────────

def add_manual(conn, *, player_id: int, status: str, severity: str,
               body_part: Optional[str] = None, notes: Optional[str] = None,
               expires_days: int = 14) -> int:
    """Add a single hand-entered injury row. Useful for breaking news where
    we know about an injury before any feed catches it."""
    expires_at = datetime.utcnow() + timedelta(days=expires_days)
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO player_injury_status
                (player_id, status, severity, body_part, notes, source, source_url,
                 noted_at, expires_at)
            VALUES (%s, %s, %s, %s, %s, 'manual', NULL, NOW(), %s)
            RETURNING id
            """,
            (player_id, status, severity, body_part, notes, expires_at)
        )
        new_id = cur.fetchone()[0]
    conn.commit()
    log.info(f"Inserted manual injury row id={new_id} for player_id={player_id}")
    return new_id


# ─── CLI entrypoint ──────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--source', choices=['all', 'recent_matches', 'atp', 'wta', 'manual'],
                        default='all')
    parser.add_argument('--player-id', type=int)
    parser.add_argument('--status', choices=['injury', 'illness', 'fatigue', 'doubt'])
    parser.add_argument('--severity', choices=['minor', 'moderate', 'major'])
    parser.add_argument('--body-part', type=str)
    parser.add_argument('--notes', type=str)
    parser.add_argument('--expires-days', type=int, default=14)
    parser.add_argument('--lookback-days', type=int, default=14)
    args = parser.parse_args()

    conn = psycopg2.connect(DB_URL)
    ensure_schema(conn)

    if args.source == 'manual':
        if not (args.player_id and args.status and args.severity):
            parser.error('manual source requires --player-id, --status, --severity')
        add_manual(conn,
                   player_id=args.player_id, status=args.status, severity=args.severity,
                   body_part=args.body_part, notes=args.notes,
                   expires_days=args.expires_days)
    else:
        if args.source in ('all', 'recent_matches'):
            infer_from_recent_matches(conn, lookback_days=args.lookback_days)
        if args.source in ('all', 'atp'):
            scrape_atp_withdrawals(conn)
        if args.source in ('all', 'wta'):
            scrape_wta_withdrawals(conn)

    conn.close()


if __name__ == '__main__':
    main()
