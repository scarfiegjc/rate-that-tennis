"""
ratethat.tennis — Richer form_score computation
=================================================
Replaces the simple "win% over last N matches → 0-100" formula with a value-
weighted per-match score so the metric actually spreads players out instead
of clustering at 75.

Per-match value (last 10 matches, recency-weighted):

  value = result_score
        × opponent_factor
        × tournament_factor
        × round_factor
        × result_gap_factor

Where:
  result_score     : +60 win, -10 loss (so a base bad-loss = -10, base good-win = 60)
  opponent_factor  : 1.0 + (opponent_rtt - 60) / 40           # ~0.5 vs RTT 40, ~1.5 vs RTT 80
  tournament_factor: G=1.5, M=1.3, A=1.1, C=0.9, S=0.7
  round_factor     : F=1.4, SF=1.25, QF=1.15, R16=1.05, R32=1.0, R64=0.95, Q=0.85
  gap_factor       : 1.3 if 6-0/6-0 or 6-0/6-1 type win,
                     1.15 for 6-1/6-2 dominant,
                     1.0 for routine,
                     0.85 for 7-5/7-6/7-6 (close)

Final form_score = clip(50 + 0.6 * mean(weighted_match_value), 5, 95)

Run: python3 -m pipeline.form_score
Idempotent. Updates player_ratings.form_score for every active player.
"""

from __future__ import annotations

import logging
import math
import os
import re
from collections import defaultdict
from datetime import date, timedelta
from typing import Optional

import psycopg2
import psycopg2.extras

log = logging.getLogger("rtt-form-score")
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

DB_URL = (
    os.environ.get("DATABASE_PUBLIC_URL")
    or os.environ.get("DATABASE_URL")
    or "postgresql://postgres:DEKANqBEjmOvOGLCfzaQIBaKzhKcyKwS@switchyard.proxy.rlwy.net:39343/railway"
).strip()


# Tunable weights
RESULT_WIN = 60.0
RESULT_LOSS = -10.0

LEVEL_FACTOR = {"G": 1.5, "M": 1.3, "A": 1.1, "C": 0.9, "S": 0.7}
ROUND_FACTOR = {
    "F": 1.40, "FINAL": 1.40, "FINALS": 1.40,
    "SF": 1.25, "SEMI": 1.25, "SEMI-FINALS": 1.25, "SEMI-FINAL": 1.25,
    "QF": 1.15, "QUARTER": 1.15, "QUARTER-FINALS": 1.15, "QUARTER-FINAL": 1.15,
    "R16": 1.05, "R32": 1.00, "R64": 0.95, "R128": 0.90,
    "Q": 0.85, "QUAL": 0.85, "QUALIFICATION": 0.85, "QUALIFYING": 0.85,
}


def _level_code(tour_category: Optional[str], type_name: Optional[str]) -> str:
    tc = (tour_category or "").lower()
    tn = (type_name or "").lower()
    if "grand slam" in tn:
        return "G"
    if "masters" in tn or "premier mandatory" in tn or "premier 5" in tn:
        return "M"
    if "challenger" in tc or "challenger" in tn:
        return "C"
    if "itf" in tc:
        return "S"
    return "A"


def _round_factor(round_str: Optional[str]) -> float:
    if not round_str:
        return 1.0
    r = round_str.strip().upper()
    # Common patterns
    for key, val in ROUND_FACTOR.items():
        if r == key or r.startswith(key + " ") or r.endswith(" " + key) or key in r:
            return val
    if "ROUND OF 128" in r: return 0.90
    if "ROUND OF 64"  in r: return 0.95
    if "ROUND OF 32"  in r: return 1.00
    if "ROUND OF 16"  in r: return 1.05
    return 1.0


def _opponent_factor(opp_rtt: Optional[float]) -> float:
    """1.0 + (opp - 60)/40, clamped 0.4..1.6 — beating a top player worth more, beating <40 worth less."""
    if opp_rtt is None:
        return 1.0
    return max(0.4, min(1.6, 1.0 + (float(opp_rtt) - 60) / 40))


def _gap_factor(score: Optional[str], won: bool) -> float:
    """
    Look at the set score string ('6-0 6-1', '7-5 6-7 6-3', etc.) to gauge how
    dominant the result was. Returns multiplier in [0.85, 1.30].
    """
    if not score:
        return 1.0
    sets = re.findall(r"(\d+)\s*-\s*(\d+)", score)
    if not sets:
        return 1.0
    total_diff = 0
    breadsticks = 0     # 6-0 or 6-1
    sevens = 0          # 7-5 / 7-6
    sets_played = len(sets)
    for a, b in sets:
        a, b = int(a), int(b)
        diff = a - b if won else b - a
        total_diff += diff
        if (won and a == 6 and b <= 1) or (not won and b == 6 and a <= 1):
            breadsticks += 1
        if a == 7 or b == 7:
            sevens += 1
    avg_diff = total_diff / sets_played
    # Routine straight-sets win: avg_diff ~= 4
    if won:
        if breadsticks >= 2: return 1.30
        if avg_diff >= 4:    return 1.15
        if sevens >= 1 and avg_diff <= 1: return 0.85   # scrappy 7-6 7-6
        return 1.0
    else:
        # losses
        if breadsticks >= 2:  return 1.30  # heavy loss = penalty stronger
        if avg_diff >= 4:     return 1.15
        if sevens >= 1 and avg_diff <= 1: return 0.85   # very narrow loss — softer penalty
        return 1.0


def _decay_weight(days_ago: int, half_life_days: int = 180) -> float:
    """Exponential recency decay; half-life 6 months."""
    if days_ago < 0:
        return 0.0
    return math.exp(-days_ago * math.log(2) / half_life_days)


def compute_form_for_player(
    cur,
    player_id: int,
    n_matches: int = 10,
    today: Optional[date] = None,
) -> Optional[float]:
    """Return new form_score in 5..95, or None if not enough data."""
    if today is None:
        today = date.today()

    cur.execute(
        """
        SELECT
            m.winner,
            m.first_player_id,
            m.second_player_id,
            m.event_date,
            m.tournament_round AS round,
            ms.set_scores      AS score,
            et.tour_category, et.type_name,
            CASE WHEN m.first_player_id = %s
                 THEN pr2.rtt_score
                 ELSE pr1.rtt_score END AS opp_rtt
        FROM matches m
        LEFT JOIN event_types et ON et.id = m.event_type_id
        LEFT JOIN player_ratings pr1 ON pr1.player_id = m.first_player_id
        LEFT JOIN player_ratings pr2 ON pr2.player_id = m.second_player_id
        LEFT JOIN LATERAL (
            SELECT string_agg(score_first || '-' || score_second, ' ' ORDER BY set_number) AS set_scores
            FROM match_scores ms_inner
            WHERE ms_inner.match_id = m.id
        ) ms ON TRUE
        WHERE (m.first_player_id = %s OR m.second_player_id = %s)
          AND m.event_status = 'Finished'
          AND m.winner IS NOT NULL
          AND m.event_date >= CURRENT_DATE - INTERVAL '24 months'
        ORDER BY m.event_date DESC, m.id DESC
        LIMIT %s
        """,
        (player_id, player_id, player_id, n_matches),
    )
    rows = cur.fetchall()
    if len(rows) < 3:
        return None

    weighted_sum = 0.0
    weight_total = 0.0
    for r in rows:
        won = (r["winner"] == "First Player" and r["first_player_id"] == player_id) or \
              (r["winner"] == "Second Player" and r["second_player_id"] == player_id)
        result_score = RESULT_WIN if won else RESULT_LOSS
        opp_factor = _opponent_factor(r.get("opp_rtt"))
        level_factor = LEVEL_FACTOR.get(_level_code(r.get("tour_category"), r.get("type_name")), 1.0)
        round_factor = _round_factor(r.get("round"))
        gap_factor = _gap_factor(r.get("score"), won)

        match_value = result_score * opp_factor * level_factor * round_factor * gap_factor

        days_ago = (today - r["event_date"]).days if r.get("event_date") else 0
        w = _decay_weight(days_ago)
        weighted_sum += w * match_value
        weight_total += w

    if weight_total <= 0:
        return None

    avg_value = weighted_sum / weight_total
    # Center on 50, scale: a perfect run of weighted wins (avg_value ~ 90) → 50 + 0.5*90 = 95
    # An all-losses run (avg_value ~ -15) → 50 + 0.5*-15 = 42.5 — losses to good players are softer.
    # All-blowout-losses run (avg_value ~ -25) → 50 + 0.5*-25 = 37.5
    score = 50.0 + 0.5 * avg_value
    return round(max(5.0, min(95.0, score)), 2)


def update_all_form_scores(conn) -> int:
    """Compute and write form_score for every player who has a player_ratings row."""
    log.info("Computing richer form_score for all players…")
    prev_autocommit = conn.autocommit
    conn.autocommit = True

    # Find every player who has an existing player_ratings row.
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute("SELECT player_id FROM player_ratings")
        all_pids = [r["player_id"] for r in cur.fetchall()]

    log.info(f"  {len(all_pids)} players to score")

    today = date.today()
    written = 0
    skipped_thin = 0

    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        for pid in all_pids:
            try:
                score = compute_form_for_player(cur, pid, n_matches=10, today=today)
            except Exception as e:
                log.warning(f"  player {pid}: {e}")
                continue
            if score is None:
                skipped_thin += 1
                continue
            try:
                with conn.cursor() as wc:
                    wc.execute(
                        "UPDATE player_ratings SET form_score = %s, updated_at = NOW() WHERE player_id = %s",
                        (score, pid),
                    )
                written += 1
            except Exception as e:
                log.warning(f"  player {pid} write: {e}")

    conn.autocommit = prev_autocommit
    log.info(f"  ✅ Updated {written} form scores  ({skipped_thin} skipped — fewer than 3 recent matches)")
    return written


def main():
    conn = psycopg2.connect(DB_URL)
    try:
        update_all_form_scores(conn)
    finally:
        conn.close()


if __name__ == "__main__":
    main()
