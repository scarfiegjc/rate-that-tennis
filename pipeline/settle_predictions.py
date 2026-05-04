"""
ratethat.tennis — Settle predictions
======================================
Reads finished matches, looks up the corresponding model_predictions row,
fills in actual_winner, is_correct, settled_at. Same for system_picks,
including profit/loss based on the snapshotted market_odds.

Run after pipeline.pipeline (which fills in match results), and during the
day to keep the live tracker honest.

Run:
    python3 -m pipeline.settle_predictions
    python3 -m pipeline.settle_predictions --since 2026-05-01
"""

from __future__ import annotations

import argparse
import logging
import os
from datetime import date, timedelta
from typing import Optional

import psycopg2
import psycopg2.extras

log = logging.getLogger("rtt-settle")
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")


DB_URL = (
    os.environ.get("DATABASE_PUBLIC_URL")
    or os.environ.get("DATABASE_URL")
    or "postgresql://postgres:DEKANqBEjmOvOGLCfzaQIBaKzhKcyKwS@switchyard.proxy.rlwy.net:39343/railway"
).strip()


def _winner_to_player_ref(winner_text: Optional[str]) -> Optional[str]:
    if winner_text == "First Player":
        return "first_player"
    if winner_text == "Second Player":
        return "second_player"
    return None


def settle_predictions(conn, since: Optional[date] = None) -> tuple[int, int]:
    """
    Update model_predictions for finished matches.
    Returns (updated_predictions, updated_systems).
    """
    cutoff = since or (date.today() - timedelta(days=14))

    log.info(f"Settling predictions for matches finished since {cutoff}...")

    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(
            """
            SELECT m.id AS match_id, m.winner, m.event_date,
                   mp.predicted_winner, mp.is_correct
            FROM matches m
            JOIN model_predictions mp ON mp.match_id = m.id
            WHERE m.event_status = 'Finished'
              AND m.winner IN ('First Player', 'Second Player')
              AND m.event_date >= %s
              AND (mp.actual_winner IS NULL OR mp.is_correct IS NULL)
            """,
            (cutoff,),
        )
        rows = cur.fetchall()

    log.info(f"  Found {len(rows)} predictions to settle")

    updated_pred = 0
    for r in rows:
        actual = _winner_to_player_ref(r["winner"])
        if not actual:
            continue
        # If predicted_winner missing, derive from probability after the fact —
        # but it should be filled. Treat None as 'unknown' (mark settled with
        # is_correct=False to avoid double-counting). Belt-and-braces: re-pull.
        pred_winner = r["predicted_winner"]
        if not pred_winner:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur2:
                cur2.execute(
                    "SELECT prob_first_player, prob_second_player FROM model_predictions WHERE match_id = %s",
                    (r["match_id"],),
                )
                pr = cur2.fetchone() or {}
            p1 = float(pr.get("prob_first_player") or 0)
            p2 = float(pr.get("prob_second_player") or 0)
            pred_winner = "first_player" if p1 >= p2 else "second_player"
        is_correct = (pred_winner == actual)
        with conn.cursor() as cur3:
            cur3.execute(
                """
                UPDATE model_predictions
                SET actual_winner = %s,
                    predicted_winner = COALESCE(predicted_winner, %s),
                    is_correct = %s,
                    settled_at = NOW()
                WHERE match_id = %s
                """,
                (actual, pred_winner, is_correct, r["match_id"]),
            )
        updated_pred += 1
    conn.commit()
    log.info(f"  ✅ Settled {updated_pred} predictions")

    # ── System picks
    log.info("Settling system picks...")
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(
            """
            SELECT sp.id, sp.match_id, sp.pick, sp.market_odds, m.winner
            FROM system_picks sp
            JOIN matches m ON m.id = sp.match_id
            WHERE m.event_status = 'Finished'
              AND m.winner IN ('First Player', 'Second Player')
              AND sp.settled_at IS NULL
              AND m.event_date >= %s
            """,
            (cutoff,),
        )
        sp_rows = cur.fetchall()

    updated_sys = 0
    for r in sp_rows:
        actual = _winner_to_player_ref(r["winner"])
        if not actual:
            continue
        is_correct = (r["pick"] == actual)
        # Profit/loss in units: +(odds-1) on win, -1 on loss.
        odds = float(r["market_odds"]) if r["market_odds"] else None
        if odds and odds > 1.0:
            pnl = round(odds - 1.0, 4) if is_correct else -1.0
        else:
            pnl = None  # we don't have odds — leave PnL blank
        with conn.cursor() as cur2:
            cur2.execute(
                """
                UPDATE system_picks
                SET is_correct = %s,
                    profit_loss = %s,
                    settled_at = NOW()
                WHERE id = %s
                """,
                (is_correct, pnl, r["id"]),
            )
        updated_sys += 1

    conn.commit()
    log.info(f"  ✅ Settled {updated_sys} system picks")
    return updated_pred, updated_sys


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--since", type=str, help="ISO date (YYYY-MM-DD) — settle from this date forward")
    args = parser.parse_args()

    since = None
    if args.since:
        since = date.fromisoformat(args.since)

    conn = psycopg2.connect(DB_URL)
    try:
        settle_predictions(conn, since=since)
    finally:
        conn.close()


if __name__ == "__main__":
    main()
