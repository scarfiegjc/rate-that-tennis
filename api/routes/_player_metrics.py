"""
ratethat.tennis API — Per-player computed metrics.

All metrics are derived from production data (matches, tournaments, players,
player_ratings, player_hand_splits). No Sackmann references at runtime.

Each metric returns a dict shaped:
    {
      "value":   <number or string>,
      "label":   <human-readable e.g. '3W' or '52%'>,
      "tier":    'good' | 'average' | 'bad' | 'neutral',
      "context": <one-line explanation, optional>,
    }

The `tier` drives pastel-green / amber / red shading on the frontend.
"""
from __future__ import annotations

from datetime import date
from typing import Optional

from api.db import query, query_one


# ─────────────────────────────────────────────────────────────────────────────
# Tier helpers — convert a metric to a pastel band
# ─────────────────────────────────────────────────────────────────────────────

def _pct_tier(pct: Optional[float], good: float = 60, bad: float = 40) -> str:
    if pct is None:
        return "neutral"
    if pct >= good:
        return "good"
    if pct <= bad:
        return "bad"
    return "average"


def _streak_tier(value: int) -> str:
    if value >= 3:
        return "good"
    if value <= -3:
        return "bad"
    if abs(value) >= 2:
        return "average"
    return "neutral"


def _rest_tier(days: Optional[int]) -> str:
    if days is None:
        return "neutral"
    if days >= 2:
        return "good"
    if days == 0:
        return "bad"
    return "average"


# ─────────────────────────────────────────────────────────────────────────────
# THREE NEW RATINGS (vs-hand, endurance, tournament-level)
# Each returns a 0-100 rating score so the existing rating-bar UI can render it.
# ─────────────────────────────────────────────────────────────────────────────

def vs_hand_rating(player_id: int, opponent_hand: Optional[str]) -> Optional[float]:
    """
    Win% vs the opponent's hand (Right or Left). First tries player_hand_splits
    (production-derived). If that's thin/missing, falls back to a derived
    sa_matches lookup by player name.
    """
    if not opponent_hand:
        return None
    norm = "Right" if opponent_hand.lower().startswith("r") else "Left" if opponent_hand.lower().startswith("l") else None
    if not norm:
        return None
    row = query_one(
        """
        SELECT win_pct, matches
        FROM player_hand_splits
        WHERE player_id = %s AND vs_hand = %s
        """,
        (player_id, norm),
    )
    if row and row.get("win_pct") is not None and (row.get("matches") or 0) >= 3:
        return round(max(5.0, min(95.0, float(row["win_pct"]))), 1)

    # Fallback: derive from sa_matches by player name (scalar derived stat — allowed)
    p = query_one("SELECT name, full_name FROM players WHERE id = %s", (player_id,))
    if not p:
        return None
    name = (p.get("full_name") or p.get("name") or "").strip()
    last = (name.split() or [""])[-1].strip()
    if not last or len(last) < 3:
        return None
    sa_hand_letter = "R" if norm == "Right" else "L"
    try:
        sa = query_one(
            """
            WITH me AS (
                SELECT player_id FROM sa_players
                WHERE name_last ILIKE %s
                LIMIT 5
            )
            SELECT
                COUNT(*) AS n,
                SUM(CASE WHEN sm.winner_id IN (SELECT player_id FROM me) THEN 1 ELSE 0 END) AS wins
            FROM sa_matches sm
            WHERE sm.tourney_date >= CURRENT_DATE - INTERVAL '5 years'
              AND (
                (sm.winner_id IN (SELECT player_id FROM me) AND sm.loser_hand  = %s)
             OR (sm.loser_id  IN (SELECT player_id FROM me) AND sm.winner_hand = %s)
              )
            """,
            (last, sa_hand_letter, sa_hand_letter),
        )
        if sa and (sa.get("n") or 0) >= 5:
            pct = 100.0 * (sa["wins"] or 0) / sa["n"]
            return round(max(5.0, min(95.0, pct)), 1)
    except Exception:
        pass
    return None


def endurance_rating(player_id: int) -> Optional[float]:
    """
    Win% in long matches (3 or more sets). First tries production matches.
    If thin, supplements with a sa_matches lookup by player name (long matches:
    minutes >= 150 OR sets played >= 3). Returns 0-100, or None if no signal.
    """
    row = query_one(
        """
        SELECT
            COUNT(*) AS n,
            SUM(CASE
                  WHEN (winner = 'First Player'  AND first_player_id  = %s)
                    OR (winner = 'Second Player' AND second_player_id = %s)
                  THEN 1 ELSE 0 END) AS wins
        FROM matches
        WHERE (first_player_id = %s OR second_player_id = %s)
          AND event_status = 'Finished'
          AND winner IS NOT NULL
          AND event_date >= CURRENT_DATE - INTERVAL '24 months'
          AND final_result IN ('2 - 1', '1 - 2', '3 - 1', '3 - 2', '1 - 3', '2 - 3')
        """,
        (player_id, player_id, player_id, player_id),
    )
    n = (row or {}).get("n") or 0
    wins = (row or {}).get("wins") or 0

    # Supplement with sa_matches if production data is thin (< 4)
    if n < 4:
        p = query_one("SELECT name, full_name FROM players WHERE id = %s", (player_id,))
        if p:
            name = (p.get("full_name") or p.get("name") or "").strip()
            last = (name.split() or [""])[-1].strip()
            if last and len(last) >= 3:
                try:
                    sa = query_one(
                        """
                        WITH me AS (
                            SELECT player_id FROM sa_players WHERE name_last ILIKE %s LIMIT 5
                        )
                        SELECT
                            COUNT(*) AS n,
                            SUM(CASE WHEN sm.winner_id IN (SELECT player_id FROM me) THEN 1 ELSE 0 END) AS wins
                        FROM sa_matches sm
                        WHERE sm.tourney_date >= CURRENT_DATE - INTERVAL '5 years'
                          AND (sm.winner_id IN (SELECT player_id FROM me)
                            OR sm.loser_id  IN (SELECT player_id FROM me))
                          AND (sm.minutes >= 150
                               OR sm.score ~ '\\d+-\\d+ \\d+-\\d+ \\d+-\\d+'
                              OR sm.score ~ '\\d+-\\d+ \\d+-\\d+ \\d+-\\d+ \\d+-\\d+')
                        """,
                        (last,),
                    )
                    if sa and (sa.get("n") or 0) >= 4:
                        n += int(sa["n"])
                        wins += int(sa["wins"] or 0)
                except Exception:
                    pass

    if n < 3:
        return None
    pct = 100.0 * wins / n
    return round(max(5.0, min(95.0, pct)), 1)


# Tour-level coding lifted from CLAUDE.md
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


def tournament_level_rating(player_id: int, level_code: str) -> Optional[float]:
    """
    Win% at this tour level (G/M/A/C/S) over the last 24 months.
    Slam, Masters, ATP/WTA tour, Challenger, ITF.
    """
    if not level_code:
        return None
    # Map level_code to a tour_category / type_name predicate.
    # We rely on the event_types table.
    where_clause = ""
    params: list = []
    if level_code == "G":
        where_clause = "et.type_name ILIKE '%grand slam%'"
    elif level_code == "M":
        where_clause = "(et.type_name ILIKE '%masters%' OR et.type_name ILIKE '%premier mandatory%' OR et.type_name ILIKE '%premier 5%')"
    elif level_code == "C":
        where_clause = "(et.tour_category ILIKE '%challenger%' OR et.type_name ILIKE '%challenger%')"
    elif level_code == "S":
        where_clause = "et.tour_category ILIKE '%itf%'"
    else:  # A — main tour
        where_clause = "(et.tour_category IN ('ATP', 'WTA') AND et.type_name NOT ILIKE '%masters%' AND et.type_name NOT ILIKE '%grand slam%')"

    row = query_one(
        f"""
        SELECT
            COUNT(*) AS n,
            SUM(CASE
                  WHEN (m.winner = 'First Player'  AND m.first_player_id  = %s)
                    OR (m.winner = 'Second Player' AND m.second_player_id = %s)
                  THEN 1 ELSE 0 END) AS wins
        FROM matches m
        JOIN event_types et ON et.id = m.event_type_id
        WHERE (m.first_player_id = %s OR m.second_player_id = %s)
          AND m.event_status = 'Finished'
          AND m.winner IS NOT NULL
          AND m.event_date >= CURRENT_DATE - INTERVAL '24 months'
          AND {where_clause}
        """,
        (player_id, player_id, player_id, player_id),
    )
    n = (row or {}).get("n") or 0
    wins = (row or {}).get("wins") or 0

    # Supplement from sa_matches when production data is thin
    if n < 3:
        p = query_one("SELECT name, full_name FROM players WHERE id = %s", (player_id,))
        if p:
            name = (p.get("full_name") or p.get("name") or "").strip()
            last = (name.split() or [""])[-1].strip()
            if last and len(last) >= 3:
                try:
                    sa = query_one(
                        """
                        WITH me AS (
                            SELECT player_id FROM sa_players WHERE name_last ILIKE %s LIMIT 5
                        )
                        SELECT
                            COUNT(*) AS n,
                            SUM(CASE WHEN sm.winner_id IN (SELECT player_id FROM me) THEN 1 ELSE 0 END) AS wins
                        FROM sa_matches sm
                        WHERE sm.tourney_date >= CURRENT_DATE - INTERVAL '5 years'
                          AND (sm.winner_id IN (SELECT player_id FROM me)
                            OR sm.loser_id  IN (SELECT player_id FROM me))
                          AND sm.tourney_level = %s
                        """,
                        (last, level_code),
                    )
                    if sa and (sa.get("n") or 0) >= 3:
                        n += int(sa["n"])
                        wins += int(sa["wins"] or 0)
                except Exception:
                    pass

    if n < 2:
        return None
    pct = 100.0 * wins / n
    return round(max(5.0, min(95.0, pct)), 1)


# ─────────────────────────────────────────────────────────────────────────────
# STATISTICS — eight per-player metrics for the new tab
# ─────────────────────────────────────────────────────────────────────────────

def days_since_last_match(player_id: int, ref_date: Optional[date] = None) -> dict:
    if ref_date is None:
        ref_date = date.today()
    row = query_one(
        """
        SELECT MAX(event_date) AS last_date
        FROM matches
        WHERE (first_player_id = %s OR second_player_id = %s)
          AND event_status = 'Finished'
          AND event_date < %s
        """,
        (player_id, player_id, ref_date),
    )
    last = row.get("last_date") if row else None
    if not last:
        return {"value": None, "label": "—", "tier": "neutral",
                "context": "No prior match found"}
    days = (ref_date - last).days
    label = "Today" if days == 0 else f"{days} day{'s' if days != 1 else ''} ago"
    return {
        "value": days,
        "label": label,
        "tier": _rest_tier(days),
        "context": f"Last match: {last.isoformat()}",
    }


def current_streak(player_id: int) -> dict:
    """Returns the player's current win or loss streak."""
    rows = query(
        """
        SELECT m.winner, m.first_player_id, m.event_date
        FROM matches m
        WHERE (m.first_player_id = %s OR m.second_player_id = %s)
          AND m.event_status = 'Finished'
          AND m.winner IS NOT NULL
        ORDER BY m.event_date DESC, m.id DESC
        LIMIT 25
        """,
        (player_id, player_id),
    )
    if not rows:
        return {"value": 0, "label": "—", "tier": "neutral"}
    streak = 0
    streak_type = None
    for r in rows:
        won = (r["winner"] == "First Player" and r["first_player_id"] == player_id) or \
              (r["winner"] == "Second Player" and r["first_player_id"] != player_id)
        cur = "W" if won else "L"
        if streak_type is None:
            streak_type = cur
            streak = 1
        elif cur == streak_type:
            streak += 1
        else:
            break
    signed = streak if streak_type == "W" else -streak
    return {
        "value": signed,
        "label": f"{streak_type}{streak}",
        "tier": _streak_tier(signed),
    }


def comeback_rate(player_id: int) -> dict:
    """
    Win % in matches where the player lost the first set.
    Uses match_scores. Looks at last 24 months.
    """
    row = query_one(
        """
        WITH first_sets AS (
            SELECT
                m.id AS match_id,
                m.winner,
                m.first_player_id,
                m.second_player_id,
                ms.score_first::int  AS p1_set1,
                ms.score_second::int AS p2_set1
            FROM matches m
            JOIN match_scores ms ON ms.match_id = m.id AND ms.set_number = 1
            WHERE (m.first_player_id = %s OR m.second_player_id = %s)
              AND m.event_status = 'Finished'
              AND m.winner IS NOT NULL
              AND m.event_date >= CURRENT_DATE - INTERVAL '24 months'
              AND ms.score_first ~ '^[0-9]+$'
              AND ms.score_second ~ '^[0-9]+$'
        ),
        lost_set1 AS (
            SELECT *,
                CASE
                  WHEN first_player_id = %s AND p1_set1 < p2_set1 THEN 'lost'
                  WHEN second_player_id = %s AND p2_set1 < p1_set1 THEN 'lost'
                  ELSE 'won'
                END AS s1
            FROM first_sets
        )
        SELECT
            COUNT(*) FILTER (WHERE s1 = 'lost') AS lost_set1_total,
            COUNT(*) FILTER (
                WHERE s1 = 'lost'
                  AND ((winner = 'First Player'  AND first_player_id  = %s)
                    OR (winner = 'Second Player' AND second_player_id = %s))
            ) AS came_back
        FROM lost_set1
        """,
        (player_id, player_id, player_id, player_id, player_id, player_id),
    )
    n = (row or {}).get("lost_set1_total") or 0
    won = (row or {}).get("came_back") or 0
    if n < 2:
        return {"value": None, "label": "—", "tier": "neutral",
                "context": f"Only {n} matches lost first set"}
    pct = round(100.0 * won / n, 1)
    return {
        "value": pct,
        "label": f"{pct}% ({won}/{n})",
        "tier": _pct_tier(pct, good=35, bad=15),
        "context": "Win % when losing first set",
    }


def closeout_rate(player_id: int) -> dict:
    """Win % when player wins the first set."""
    row = query_one(
        """
        WITH first_sets AS (
            SELECT
                m.id AS match_id,
                m.winner,
                m.first_player_id,
                m.second_player_id,
                ms.score_first::int  AS p1_set1,
                ms.score_second::int AS p2_set1
            FROM matches m
            JOIN match_scores ms ON ms.match_id = m.id AND ms.set_number = 1
            WHERE (m.first_player_id = %s OR m.second_player_id = %s)
              AND m.event_status = 'Finished'
              AND m.winner IS NOT NULL
              AND m.event_date >= CURRENT_DATE - INTERVAL '24 months'
              AND ms.score_first ~ '^[0-9]+$'
              AND ms.score_second ~ '^[0-9]+$'
        ),
        won_set1 AS (
            SELECT *,
                CASE
                  WHEN first_player_id  = %s AND p1_set1 > p2_set1 THEN 'won'
                  WHEN second_player_id = %s AND p2_set1 > p1_set1 THEN 'won'
                  ELSE 'lost'
                END AS s1
            FROM first_sets
        )
        SELECT
            COUNT(*) FILTER (WHERE s1 = 'won') AS won_set1_total,
            COUNT(*) FILTER (
                WHERE s1 = 'won'
                  AND ((winner = 'First Player'  AND first_player_id  = %s)
                    OR (winner = 'Second Player' AND second_player_id = %s))
            ) AS closed_out
        FROM won_set1
        """,
        (player_id, player_id, player_id, player_id, player_id, player_id),
    )
    n = (row or {}).get("won_set1_total") or 0
    won = (row or {}).get("closed_out") or 0
    if n < 2:
        return {"value": None, "label": "—", "tier": "neutral",
                "context": f"Only {n} matches won first set"}
    pct = round(100.0 * won / n, 1)
    return {
        "value": pct,
        "label": f"{pct}% ({won}/{n})",
        "tier": _pct_tier(pct, good=85, bad=70),
        "context": "Win % when winning first set",
    }


def vs_higher_lower_rank(player_id: int, player_rtt: Optional[float]) -> tuple[dict, dict]:
    """
    Win% against opponents rated higher / lower than the player by 5+ RTT points.
    Returns (vs_higher, vs_lower).
    Uses player_ratings.rtt_score for both sides.
    """
    if player_rtt is None:
        empty = {"value": None, "label": "—", "tier": "neutral", "context": "No RTT score"}
        return empty, empty
    # vs higher
    hi = query_one(
        """
        SELECT
            COUNT(*) AS n,
            SUM(CASE WHEN (m.winner = 'First Player'  AND m.first_player_id  = %s)
                       OR (m.winner = 'Second Player' AND m.second_player_id = %s)
                     THEN 1 ELSE 0 END) AS wins
        FROM matches m
        JOIN player_ratings pr ON pr.player_id = CASE
                WHEN m.first_player_id = %s THEN m.second_player_id
                ELSE m.first_player_id END
        WHERE (m.first_player_id = %s OR m.second_player_id = %s)
          AND m.event_status = 'Finished'
          AND m.winner IS NOT NULL
          AND m.event_date >= CURRENT_DATE - INTERVAL '24 months'
          AND pr.rtt_score IS NOT NULL
          AND pr.rtt_score > %s
        """,
        (player_id, player_id, player_id, player_id, player_id, player_rtt + 5),
    )
    lo = query_one(
        """
        SELECT
            COUNT(*) AS n,
            SUM(CASE WHEN (m.winner = 'First Player'  AND m.first_player_id  = %s)
                       OR (m.winner = 'Second Player' AND m.second_player_id = %s)
                     THEN 1 ELSE 0 END) AS wins
        FROM matches m
        JOIN player_ratings pr ON pr.player_id = CASE
                WHEN m.first_player_id = %s THEN m.second_player_id
                ELSE m.first_player_id END
        WHERE (m.first_player_id = %s OR m.second_player_id = %s)
          AND m.event_status = 'Finished'
          AND m.winner IS NOT NULL
          AND m.event_date >= CURRENT_DATE - INTERVAL '24 months'
          AND pr.rtt_score IS NOT NULL
          AND pr.rtt_score < %s
        """,
        (player_id, player_id, player_id, player_id, player_id, player_rtt - 5),
    )

    def _stat(row, good, bad):
        n = (row or {}).get("n") or 0
        won = (row or {}).get("wins") or 0
        if n < 2:
            return {"value": None, "label": "—", "tier": "neutral",
                    "context": f"{n} matches"}
        pct = round(100.0 * won / n, 1)
        return {"value": pct, "label": f"{pct}% ({won}/{n})",
                "tier": _pct_tier(pct, good=good, bad=bad)}

    return _stat(hi, good=40, bad=20), _stat(lo, good=80, bad=60)


def endurance_stat(player_id: int) -> dict:
    """Same calc as endurance_rating but as a stat block."""
    row = query_one(
        """
        SELECT
            COUNT(*) AS n,
            SUM(CASE
                  WHEN (winner = 'First Player'  AND first_player_id  = %s)
                    OR (winner = 'Second Player' AND second_player_id = %s)
                  THEN 1 ELSE 0 END) AS wins
        FROM matches
        WHERE (first_player_id = %s OR second_player_id = %s)
          AND event_status = 'Finished'
          AND winner IS NOT NULL
          AND event_date >= CURRENT_DATE - INTERVAL '24 months'
          AND final_result IN ('2 - 1', '1 - 2', '3 - 1', '3 - 2', '1 - 3', '2 - 3')
        """,
        (player_id, player_id, player_id, player_id),
    )
    n = (row or {}).get("n") or 0
    won = (row or {}).get("wins") or 0
    if n < 2:
        return {"value": None, "label": "—", "tier": "neutral",
                "context": f"{n} long matches"}
    pct = round(100.0 * won / n, 1)
    return {"value": pct, "label": f"{pct}% ({won}/{n})",
            "tier": _pct_tier(pct, good=55, bad=40),
            "context": "Win % in 3+ set matches"}


def time_of_day_stat(player_id: int) -> dict:
    """
    Best win-rate session: morning (before 12), afternoon (12-18), evening (after 18).
    Returns the strongest session if any has 5+ matches.
    """
    rows = query(
        """
        SELECT
            CASE
                WHEN EXTRACT(HOUR FROM event_time) < 12 THEN 'morning'
                WHEN EXTRACT(HOUR FROM event_time) < 18 THEN 'afternoon'
                ELSE 'evening'
            END AS session,
            COUNT(*) AS n,
            SUM(CASE
                  WHEN (winner = 'First Player'  AND first_player_id  = %s)
                    OR (winner = 'Second Player' AND second_player_id = %s)
                  THEN 1 ELSE 0 END) AS wins
        FROM matches
        WHERE (first_player_id = %s OR second_player_id = %s)
          AND event_status = 'Finished'
          AND winner IS NOT NULL
          AND event_time IS NOT NULL
          AND event_date >= CURRENT_DATE - INTERVAL '24 months'
        GROUP BY session
        """,
        (player_id, player_id, player_id, player_id),
    )
    if not rows:
        return {"value": None, "label": "—", "tier": "neutral"}
    best = None
    for r in rows:
        n = r.get("n") or 0
        if n < 3:
            continue
        pct = 100.0 * (r.get("wins") or 0) / n
        if best is None or pct > best[1]:
            best = (r["session"], pct, n)
    if not best:
        return {"value": None, "label": "—", "tier": "neutral",
                "context": "Not enough data"}
    sess, pct, n = best
    return {
        "value": round(pct, 1),
        "label": f"{sess.title()} ({round(pct,0):.0f}%)",
        "tier": _pct_tier(pct, good=60, bad=45),
        "context": f"Best session over {n} matches",
    }


# ─────────────────────────────────────────────────────────────────────────────
# Public helper — collect everything for a player in a single payload
# ─────────────────────────────────────────────────────────────────────────────

def _safe(fn, *args, default=None, **kwargs):
    """Run a metric fn; on any error return default and log."""
    import logging, traceback
    log = logging.getLogger("api._player_metrics")
    try:
        return fn(*args, **kwargs)
    except Exception as e:
        tb = traceback.format_exc().splitlines()
        log.warning(f"metric {fn.__name__} failed: {e} | {tb[-2] if len(tb) >= 2 else ''}")
        return default


_EMPTY_STAT = {"value": None, "label": "—", "tier": "neutral"}


def player_match_metrics(
    player_id: int,
    opponent_hand: Optional[str],
    surface: Optional[str],
    level_code: str,
    player_rtt: Optional[float],
) -> dict:
    """
    Returns a dict containing:
      - ratings: { vs_hand, endurance, tournament_level }   (0-100 scale, like other RTT ratings)
      - stats:   { days_rest, streak, comeback, closeout, vs_higher, vs_lower, endurance, time_of_day }
    Each metric is wrapped — one failure doesn't take down the whole match page.
    """
    ratings = {
        "vs_hand":           _safe(vs_hand_rating, player_id, opponent_hand),
        "endurance":         _safe(endurance_rating, player_id),
        "tournament_level":  _safe(tournament_level_rating, player_id, level_code),
    }
    vs_pair = _safe(vs_higher_lower_rank, player_id, player_rtt,
                     default=(_EMPTY_STAT, _EMPTY_STAT))
    vs_higher, vs_lower = vs_pair if vs_pair else (_EMPTY_STAT, _EMPTY_STAT)
    stats = {
        "days_rest":   _safe(days_since_last_match, player_id, default=_EMPTY_STAT),
        "streak":      _safe(current_streak,        player_id, default=_EMPTY_STAT),
        "comeback":    _safe(comeback_rate,         player_id, default=_EMPTY_STAT),
        "closeout":    _safe(closeout_rate,         player_id, default=_EMPTY_STAT),
        "vs_higher":   vs_higher,
        "vs_lower":    vs_lower,
        "endurance":   _safe(endurance_stat,        player_id, default=_EMPTY_STAT),
        "time_of_day": _safe(time_of_day_stat,      player_id, default=_EMPTY_STAT),
    }
    return {"ratings": ratings, "stats": stats}
