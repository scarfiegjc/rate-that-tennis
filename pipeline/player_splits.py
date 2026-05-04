"""
ratethat.tennis — Player splits computation
============================================
Builds per-player record vs each opponent hand (Right/Left), the player's
overall expected win rate, and the edge (positive = "lefty killer", etc.).

Sources both production matches (live data) and sa_matches (Sackmann historical,
training-only). The OUTPUT — aggregate win rates by hand — is derived data and
safe to expose on the frontend.

Run:
    python3 -m pipeline.player_splits

Idempotent: re-running re-computes from source and upserts player_hand_splits.
"""

from __future__ import annotations

import logging
import os
from typing import Optional

import psycopg2
import psycopg2.extras

log = logging.getLogger("rtt-splits")
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")


DB_URL = (
    os.environ.get("DATABASE_PUBLIC_URL")
    or os.environ.get("DATABASE_URL")
    or "postgresql://postgres:DEKANqBEjmOvOGLCfzaQIBaKzhKcyKwS@switchyard.proxy.rlwy.net:39343/railway"
).strip()


def _normalise_hand(raw: Optional[str]) -> Optional[str]:
    """Map noisy hand strings into 'Right' | 'Left' | None."""
    if not raw:
        return None
    raw = str(raw).strip().lower()
    if raw.startswith("r"):
        return "Right"
    if raw.startswith("l"):
        return "Left"
    if raw == "u" or raw.startswith("u"):
        return None
    return None


def compute_hand_splits(conn) -> int:
    """
    Build per-player hand splits and upsert into player_hand_splits.
    Returns number of rows written.
    """
    log.info("Loading match results from production matches table...")

    # Production matches — same data we surface elsewhere (allowed)
    prod_sql = """
        SELECT
            m.first_player_id  AS p1_id,
            m.second_player_id AS p2_id,
            m.winner,
            p1.hand AS p1_hand,
            p2.hand AS p2_hand
        FROM matches m
        JOIN players p1 ON p1.id = m.first_player_id
        JOIN players p2 ON p2.id = m.second_player_id
        WHERE m.event_status = 'Finished'
          AND m.winner IS NOT NULL
          AND (m.is_doubles IS NULL OR m.is_doubles = FALSE)
    """

    # Per-player aggregation: {(player_id, vs_hand): [wins, losses]}
    splits: dict[tuple[int, str], list[int]] = {}
    # Overall record per player: {player_id: [wins, losses]}
    overall: dict[int, list[int]] = {}

    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(prod_sql)
        prod_rows = cur.fetchall()
    log.info(f"  Production matches: {len(prod_rows)}")

    def _bump(player_id, vs_hand, won):
        if vs_hand:
            key = (player_id, vs_hand)
            splits.setdefault(key, [0, 0])
            splits[key][0 if won else 1] += 1
        overall.setdefault(player_id, [0, 0])
        overall[player_id][0 if won else 1] += 1

    for r in prod_rows:
        p1, p2 = r["p1_id"], r["p2_id"]
        h1 = _normalise_hand(r["p1_hand"])
        h2 = _normalise_hand(r["p2_hand"])
        won_p1 = (r["winner"] == "First Player")

        # P1's record vs opponent's hand (h2)
        _bump(p1, h2, won_p1)
        # P2's record vs opponent's hand (h1)
        _bump(p2, h1, not won_p1)

    # ── Supplement from sa_matches via player name → players.id mapping.
    # We keep this scoped: only opponent_hand pulled from sa_players.hand,
    # never surfaced raw.
    log.info("Loading hand splits from sa_matches (training-only, aggregated)...")
    sa_sql = """
        SELECT
            sm.winner_id,
            sm.loser_id,
            sm.winner_hand AS w_hand,
            sm.loser_hand  AS l_hand,
            -- map sa_player → production player by name
            pw.id AS prod_winner_id,
            pl.id AS prod_loser_id
        FROM sa_matches sm
        LEFT JOIN sa_players spw ON spw.player_id = sm.winner_id
        LEFT JOIN sa_players spl ON spl.player_id = sm.loser_id
        LEFT JOIN players pw ON
              LOWER(TRIM(pw.full_name)) = LOWER(TRIM(spw.name_first || ' ' || spw.name_last))
           OR LOWER(TRIM(pw.full_name)) = LOWER(TRIM(spw.name_last  || ' ' || spw.name_first))
        LEFT JOIN players pl ON
              LOWER(TRIM(pl.full_name)) = LOWER(TRIM(spl.name_first || ' ' || spl.name_last))
           OR LOWER(TRIM(pl.full_name)) = LOWER(TRIM(spl.name_last  || ' ' || spl.name_first))
        WHERE sm.tourney_date >= CURRENT_DATE - INTERVAL '5 years'
          AND (pw.id IS NOT NULL OR pl.id IS NOT NULL)
    """
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(sa_sql)
            sa_rows = cur.fetchall()
        log.info(f"  Sackmann matches mapped to production players: {len(sa_rows)}")
        for r in sa_rows:
            wh = _normalise_hand(r["w_hand"])
            lh = _normalise_hand(r["l_hand"])
            pw = r["prod_winner_id"]
            pl = r["prod_loser_id"]
            # winner record vs loser hand
            if pw is not None:
                _bump(pw, lh, True)
            # loser record vs winner hand
            if pl is not None:
                _bump(pl, wh, False)
    except Exception as e:
        log.warning(f"  Sackmann split load skipped: {e}")
        conn.rollback()

    # ── Build rows for upsert
    rows = []
    for (player_id, vs_hand), (wins, losses) in splits.items():
        n = wins + losses
        if n < 5:
            # Too thin — skip, otherwise we get nonsense splits.
            continue
        win_pct = round(100.0 * wins / n, 2)
        ow, ol = overall.get(player_id, [0, 0])
        on = ow + ol
        expected = round(100.0 * ow / on, 2) if on else None
        edge = round(win_pct - expected, 2) if expected is not None else None
        rows.append((player_id, vs_hand, n, wins, losses, win_pct, expected, edge))

    if not rows:
        log.info("  No hand-split rows to write")
        return 0

    log.info(f"Upserting {len(rows)} hand-split rows...")
    with conn.cursor() as cur:
        psycopg2.extras.execute_values(
            cur,
            """
            INSERT INTO player_hand_splits
                (player_id, vs_hand, matches, wins, losses, win_pct, expected_pct, edge)
            VALUES %s
            ON CONFLICT (player_id, vs_hand) DO UPDATE SET
                matches      = EXCLUDED.matches,
                wins         = EXCLUDED.wins,
                losses       = EXCLUDED.losses,
                win_pct      = EXCLUDED.win_pct,
                expected_pct = EXCLUDED.expected_pct,
                edge         = EXCLUDED.edge,
                updated_at   = NOW()
            """,
            rows,
            page_size=200,
        )
    conn.commit()
    log.info(f"✅ Hand splits written: {len(rows)} rows")
    return len(rows)


def main():
    conn = psycopg2.connect(DB_URL)
    try:
        compute_hand_splits(conn)
    finally:
        conn.close()


if __name__ == "__main__":
    main()
