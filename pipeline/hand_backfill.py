"""
ratethat.tennis — Backfill player handedness from sa_players
==============================================================
Many production players (api-tennis source) arrive with hand = NULL or
'Unknown'. sa_players (Sackmann historical) carries handedness for most
ATP/WTA pros. We match by full name and backfill.

The MAPPING uses scalar derived data (a single 'L' / 'R' character per player),
not raw Sackmann rows — this is allowed by the project's training-only rule.

Run:
    python3 -m pipeline.hand_backfill

Idempotent. Only updates players where hand is currently NULL or 'Unknown'.
"""

from __future__ import annotations

import logging
import os
from typing import Optional

import psycopg2
import psycopg2.extras

log = logging.getLogger("rtt-hand")
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")


DB_URL = (
    os.environ.get("DATABASE_PUBLIC_URL")
    or os.environ.get("DATABASE_URL")
    or "postgresql://postgres:DEKANqBEjmOvOGLCfzaQIBaKzhKcyKwS@switchyard.proxy.rlwy.net:39343/railway"
).strip()


def _normalise_hand(raw: Optional[str]) -> Optional[str]:
    if not raw:
        return None
    raw = str(raw).strip().lower()
    if raw.startswith("r"):
        return "Right"
    if raw.startswith("l"):
        return "Left"
    return None


def backfill_hands(conn) -> int:
    """Update production players whose hand is NULL/Unknown using sa_players. Returns rows updated."""
    log.info("Backfilling player handedness from sa_players…")
    prev_autocommit = conn.autocommit
    conn.autocommit = True

    # 1) Find all production players with no hand info
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(
            """
            SELECT id, name, full_name
            FROM players
            WHERE hand IS NULL OR hand = '' OR hand = 'Unknown'
            """
        )
        missing = cur.fetchall()
    log.info(f"  {len(missing)} players need hand data")
    if not missing:
        return 0

    updated = 0
    for p in missing:
        name = (p.get("full_name") or p.get("name") or "").strip()
        if not name:
            continue
        # Build a lookup: try exact full_name match first, then last-name + first-initial.
        tokens = name.replace(".", "").split()
        if not tokens:
            continue
        last = tokens[-1].strip()
        first_initial = tokens[0][:1] if tokens else ""

        try:
            with conn.cursor() as cur:
                # Strategy 1: exact full name match
                cur.execute(
                    """
                    SELECT hand
                    FROM sa_players
                    WHERE LOWER(TRIM(full_name)) = LOWER(TRIM(%s))
                       OR LOWER(TRIM(name_first || ' ' || name_last)) = LOWER(TRIM(%s))
                       OR LOWER(TRIM(name_last  || ' ' || name_first)) = LOWER(TRIM(%s))
                    LIMIT 1
                    """,
                    (name, name, name),
                )
                row = cur.fetchone()
                hand_norm = _normalise_hand(row[0] if row else None)

                if not hand_norm and len(last) >= 3 and first_initial:
                    # Strategy 2: last-name + first-initial
                    cur.execute(
                        """
                        SELECT hand
                        FROM sa_players
                        WHERE LOWER(name_last) = LOWER(%s)
                          AND LOWER(name_first) LIKE LOWER(%s)
                        LIMIT 1
                        """,
                        (last, first_initial + "%"),
                    )
                    row = cur.fetchone()
                    hand_norm = _normalise_hand(row[0] if row else None)

            if hand_norm:
                with conn.cursor() as cur:
                    cur.execute(
                        "UPDATE players SET hand = %s, updated_at = NOW() WHERE id = %s",
                        (hand_norm, p["id"]),
                    )
                updated += 1
        except Exception as e:
            log.warning(f"  player {p.get('id')} ({name}): {e}")
            continue

    conn.autocommit = prev_autocommit
    log.info(f"  ✅ Backfilled {updated} of {len(missing)} player hands")
    return updated


def main():
    conn = psycopg2.connect(DB_URL)
    try:
        backfill_hands(conn)
    finally:
        conn.close()


if __name__ == "__main__":
    main()
