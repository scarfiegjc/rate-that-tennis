"""
ratethat.tennis — Fill missing player_ratings rows
====================================================
Every player in an upcoming match should have at least an estimated RTT score
so the match list shows a number rather than "—" for everyone.

This script finds all players in matches in the next 14 days who have no row
in player_ratings (or have rtt_score = NULL) and back-fills with the best
estimate available, in priority order:

  1. Production-data win rate (last 24 months) → blended with form
  2. Sackmann/TML rank-based estimate: 110 - 15*log10(rank)   (derived stat)
  3. Pure rank-based estimate from sa_matches (most recent ranking)
  4. Fall-through default (rtt = 50.0) so every player has SOMETHING

Idempotent — only writes rows that don't already have an rtt_score.

Run:
    python3 -m pipeline.fill_ratings
"""

from __future__ import annotations

import logging
import math
import os
from datetime import date, timedelta
from typing import Optional

import psycopg2
import psycopg2.extras

log = logging.getLogger("rtt-fill-ratings")
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")


DB_URL = (
    os.environ.get("DATABASE_PUBLIC_URL")
    or os.environ.get("DATABASE_URL")
    or "postgresql://postgres:DEKANqBEjmOvOGLCfzaQIBaKzhKcyKwS@switchyard.proxy.rlwy.net:39343/railway"
).strip()


def _rank_to_rtt(rank: Optional[int]) -> Optional[float]:
    if rank is None or rank <= 0:
        return None
    try:
        rtt = 110.0 - 15.0 * math.log10(int(rank))
        return round(max(15.0, min(95.0, rtt)), 2)
    except (TypeError, ValueError):
        return None


def fill_missing_ratings(conn) -> int:
    """
    Fill player_ratings for every player without an RTT score.
    Targets:
      - Players in matches in the last 6 months OR next 14 days (covers active set)
      - Players appearing in any model_predictions row
    This is intentionally broad — over-filling is idempotent and harmless.
    """
    log.info("Filling missing player_ratings…")
    today = date.today()
    cutoff_back  = today - timedelta(days=180)
    cutoff_fwd   = today + timedelta(days=14)

    # CRITICAL: use autocommit so a silent SELECT failure on one player doesn't
    # leave the connection in an aborted-transaction state, killing every
    # subsequent INSERT for the rest of the run.
    prev_autocommit = conn.autocommit
    conn.autocommit = True

    # 1. Find all distinct player IDs without an RTT score from any of:
    #    - matches in the last 6 months
    #    - upcoming matches in the next 14 days
    #    - any model_predictions row
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(
            """
            WITH active_players AS (
                SELECT DISTINCT first_player_id  AS player_id FROM matches
                WHERE event_date BETWEEN %s AND %s
                  AND first_player_id IS NOT NULL
                UNION
                SELECT DISTINCT second_player_id AS player_id FROM matches
                WHERE event_date BETWEEN %s AND %s
                  AND second_player_id IS NOT NULL
                UNION
                SELECT DISTINCT m.first_player_id  FROM model_predictions mp
                  JOIN matches m ON m.id = mp.match_id
                  WHERE m.first_player_id IS NOT NULL
                UNION
                SELECT DISTINCT m.second_player_id FROM model_predictions mp
                  JOIN matches m ON m.id = mp.match_id
                  WHERE m.second_player_id IS NOT NULL
            )
            SELECT ap.player_id, p.name, p.full_name
            FROM active_players ap
            JOIN players p ON p.id = ap.player_id
            LEFT JOIN player_ratings pr ON pr.player_id = ap.player_id
            WHERE pr.rtt_score IS NULL OR pr.rtt_score < 10
            """,
            (cutoff_back, cutoff_fwd, cutoff_back, cutoff_fwd),
        )
        missing = cur.fetchall()

    log.info(f"  {len(missing)} players in upcoming matches lack RTT score")
    if not missing:
        return 0

    written = 0
    today_d = date.today()

    for p in missing:
        pid = p["player_id"]
        name = p.get("full_name") or p.get("name") or ""

        # ── Strategy 1: production-data win-rate over 24 months ──────────────
        win_rate = None
        match_count = 0
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT COUNT(*) AS n,
                           SUM(CASE
                                 WHEN (m.winner = 'First Player'  AND m.first_player_id = %s)
                                   OR (m.winner = 'Second Player' AND m.second_player_id = %s)
                                 THEN 1 ELSE 0 END) AS wins
                    FROM matches m
                    WHERE (m.first_player_id = %s OR m.second_player_id = %s)
                      AND m.event_status = 'Finished'
                      AND m.winner IS NOT NULL
                      AND m.event_date >= CURRENT_DATE - INTERVAL '24 months'
                    """,
                    (pid, pid, pid, pid),
                )
                row = cur.fetchone()
                match_count = row[0] if row and row[0] else 0
                wins = row[1] if row and row[1] else 0
                if match_count >= 5:
                    win_rate = wins / match_count
        except Exception:
            pass

        # ── Strategy 2: production ranking — players table has no rank column,
        # so this is a no-op. Kept for symmetry with the predictor's fallback.
        rank_est = None

        # ── Strategy 3: Sackmann/TML rank lookup ─────────────────────────────
        sa_rank_est = None
        last = (name.split()[-1] if name else "").strip()
        if last and len(last) >= 3:
            try:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        SELECT COALESCE(
                            MIN(sm.winner_rank) FILTER (WHERE sm.winner_id = sp.player_id),
                            MIN(sm.loser_rank)  FILTER (WHERE sm.loser_id  = sp.player_id)
                        ) AS rank
                        FROM sa_players sp
                        JOIN sa_matches sm ON (sm.winner_id = sp.player_id OR sm.loser_id = sp.player_id)
                        WHERE sp.full_name ILIKE %s
                          AND sm.tourney_date >= CURRENT_DATE - INTERVAL '2 years'
                        """,
                        (f"%{last}%",),
                    )
                    rr = cur.fetchone()
                    if rr and rr[0]:
                        sa_rank_est = _rank_to_rtt(rr[0])
            except Exception:
                pass

        # ── Combine: pick the best signal available ──────────────────────────
        rtt = None
        if rank_est is not None:
            # Production rank is the most authoritative signal we have
            rtt = rank_est
        elif sa_rank_est is not None:
            rtt = sa_rank_est
        elif win_rate is not None:
            # 50% win rate → 50 RTT; 80% → 75; capped 25–75 with no rank info
            rtt = round(max(25.0, min(75.0, 25 + 60 * win_rate)), 2)
        else:
            rtt = 45.0  # sensible default for unknown active player

        # If we ALSO have a win-rate signal, blend it slightly for finer scaling
        if win_rate is not None and rtt is not None:
            blend = round(rtt * 0.7 + (25 + 60 * win_rate) * 0.3, 2)
            rtt = round(max(15.0, min(95.0, blend)), 2)

        # Surface stub: assume balanced surface profile around RTT
        # (Will be replaced by real ratings.py when there's enough match data.)
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO player_ratings (
                        player_id, rtt_score,
                        clay_rating, hard_rating, grass_rating, indoor_rating,
                        form_score, momentum, calculated_at
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (player_id) DO UPDATE SET
                        rtt_score      = CASE
                            WHEN player_ratings.rtt_score IS NULL OR player_ratings.rtt_score < 10
                            THEN EXCLUDED.rtt_score
                            ELSE player_ratings.rtt_score
                        END,
                        clay_rating    = COALESCE(player_ratings.clay_rating, EXCLUDED.clay_rating),
                        hard_rating    = COALESCE(player_ratings.hard_rating, EXCLUDED.hard_rating),
                        grass_rating   = COALESCE(player_ratings.grass_rating, EXCLUDED.grass_rating),
                        indoor_rating  = COALESCE(player_ratings.indoor_rating, EXCLUDED.indoor_rating),
                        form_score     = COALESCE(player_ratings.form_score, EXCLUDED.form_score),
                        momentum       = COALESCE(player_ratings.momentum, EXCLUDED.momentum),
                        calculated_at  = EXCLUDED.calculated_at
                    """,
                    (
                        pid,
                        rtt,
                        # Surface-neutral defaults: rtt-3 / rtt / rtt-2 / rtt-1
                        # Avoids zeroes; lets the predictor pull surface_gap when one player
                        # has real surface ratings against an estimated player.
                        round(rtt - 3, 2),
                        round(rtt, 2),
                        round(rtt - 2, 2),
                        round(rtt - 1, 2),
                        round(50 + (rtt - 50) * 0.6, 2),       # form ≈ rtt but compressed
                        "stable",
                        today_d,
                    ),
                )
            written += 1
        except Exception as e:
            log.warning(f"  Could not fill {pid} ({name}): {e}")
            # Autocommit is on so no rollback needed — just continue
            continue

    # Restore previous autocommit setting
    conn.autocommit = prev_autocommit
    log.info(f"  ✅ Filled {written} of {len(missing)} player rating rows")
    return written


def main():
    conn = psycopg2.connect(DB_URL)
    try:
        fill_missing_ratings(conn)
    finally:
        conn.close()


if __name__ == "__main__":
    main()
