"""
ratethat.tennis — Point analysis
==================================
Computes per-player point-by-point stats from production data (match_games +
match_points + match_scores). All derived; no Sackmann references.

Outputs to player_point_stats and refreshes player_ratings.serve_rating /
return_rating with new values derived from these stats.

Metrics (over last 24 months of production matches with point data):
  Service:
    - service_hold_pct           : games held when serving
    - bp_save_pct                : games held when at least one BP was faced
  Return:
    - break_pct                  : games broken when returning
    - bp_conversion_pct          : games broken in when at least one BP chance
  Clutch:
    - tiebreak_win_pct           : tiebreak sets won
    - set_point_save_pct         : games where set point was faced & saved
    - match_point_save_pct       : games where match point was faced & saved

Run: python3 -m pipeline.point_analysis
"""

from __future__ import annotations

import logging
import os
from typing import Optional

import psycopg2
import psycopg2.extras

log = logging.getLogger("rtt-points")
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

DB_URL = (
    os.environ.get("DATABASE_PUBLIC_URL")
    or os.environ.get("DATABASE_URL")
    or "postgresql://postgres:DEKANqBEjmOvOGLCfzaQIBaKzhKcyKwS@switchyard.proxy.rlwy.net:39343/railway"
).strip()

MIN_SERVICE_GAMES = 30   # require at least this many service games for stats to be meaningful


def _pct(num: int, denom: int) -> Optional[float]:
    if not denom:
        return None
    return round(100.0 * num / denom, 2)


def _serve_rating_from_pcts(hold_pct: Optional[float], bp_save_pct: Optional[float]) -> Optional[float]:
    """Map raw percentages to a 0-100 rating. Tour pros: hold% 60-90, bp save% 50-80."""
    if hold_pct is None:
        return None
    # Map hold% directly: 55→0, 75→50, 95→100
    base = (hold_pct - 55.0) * 2.5
    if bp_save_pct is not None:
        # Blend in BP save (50→0 base, 80→100 base contribution)
        bp_score = (bp_save_pct - 50.0) * 3.3
        rating = 0.65 * base + 0.35 * bp_score
    else:
        rating = base
    return round(max(5.0, min(95.0, rating)), 2)


def _return_rating_from_pcts(break_pct: Optional[float], conv_pct: Optional[float]) -> Optional[float]:
    """Tour pros: break% 10-35, conversion% 30-55."""
    if break_pct is None:
        return None
    base = (break_pct - 8.0) * 3.5    # 8→0, 30→77, 38→100
    if conv_pct is not None:
        conv_score = (conv_pct - 25.0) * 2.5    # 25→0, 65→100
        rating = 0.65 * base + 0.35 * conv_score
    else:
        rating = base
    return round(max(5.0, min(95.0, rating)), 2)


def compute_for_player(conn, player_id: int) -> Optional[dict]:
    """
    Compute point stats for one player. Looks at every match in last 24 months
    where the player participated AND match_games rows exist.
    Returns a dict ready to upsert, or None if not enough data.
    """
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

    # Single aggregate query — does most of the work in PostgreSQL.
    cur.execute(
        """
        WITH player_position AS (
            SELECT
                m.id AS match_id,
                m.event_date,
                CASE WHEN m.first_player_id = %s THEN 'First Player' ELSE 'Second Player' END AS pos
            FROM matches m
            WHERE (m.first_player_id = %s OR m.second_player_id = %s)
              AND m.event_status = 'Finished'
              AND m.event_date >= CURRENT_DATE - INTERVAL '24 months'
        ),
        game_facts AS (
            SELECT
                pp.match_id,
                pp.event_date,
                mg.id AS game_id,
                mg.set_number,
                mg.game_number,
                mg.player_served,
                mg.serve_winner,
                pp.pos,
                (mg.player_served = pp.pos)            AS player_served,
                (mg.serve_winner = pp.pos)             AS player_won_game,
                (SELECT COUNT(*) FROM match_points mp WHERE mp.game_id = mg.id AND mp.is_break_point) AS bps_in_game,
                (SELECT COUNT(*) > 0 FROM match_points mp WHERE mp.game_id = mg.id AND mp.is_set_point) AS had_set_point,
                (SELECT COUNT(*) > 0 FROM match_points mp WHERE mp.game_id = mg.id AND mp.is_match_point) AS had_match_point
            FROM player_position pp
            JOIN match_games mg ON mg.match_id = pp.match_id
        )
        SELECT
            -- Service
            COUNT(*) FILTER (WHERE player_served)                                                                AS service_games,
            COUNT(*) FILTER (WHERE player_served AND player_won_game)                                            AS service_holds,
            COUNT(*) FILTER (WHERE player_served AND bps_in_game > 0)                                            AS games_facing_bp,
            COUNT(*) FILTER (WHERE player_served AND bps_in_game > 0 AND player_won_game)                        AS games_saving_all_bp,
            -- BP-level (approximation: if held, all BPs saved; if broken, all but the last BP saved)
            SUM(CASE WHEN player_served THEN bps_in_game ELSE 0 END)                                             AS bp_faced,
            SUM(CASE WHEN player_served THEN
                    CASE WHEN player_won_game THEN bps_in_game
                         ELSE GREATEST(bps_in_game - 1, 0) END
                ELSE 0 END)                                                                                      AS bp_saved,
            -- Return
            COUNT(*) FILTER (WHERE NOT player_served)                                                            AS return_games,
            COUNT(*) FILTER (WHERE NOT player_served AND player_won_game)                                        AS return_breaks,
            COUNT(*) FILTER (WHERE NOT player_served AND bps_in_game > 0)                                        AS games_with_bp_chance,
            COUNT(*) FILTER (WHERE NOT player_served AND bps_in_game > 0 AND player_won_game)                    AS games_converting_bp,
            SUM(CASE WHEN NOT player_served THEN bps_in_game ELSE 0 END)                                         AS bp_chances,
            SUM(CASE WHEN NOT player_served THEN
                    CASE WHEN player_won_game THEN 1 ELSE 0 END
                ELSE 0 END)                                                                                      AS bp_converted,
            -- Clutch
            COUNT(*) FILTER (WHERE player_served AND had_set_point AND bps_in_game > 0)                          AS set_points_against_when_serving,
            COUNT(*) FILTER (WHERE player_served AND had_set_point AND bps_in_game > 0 AND player_won_game)      AS set_points_saved_serving,
            COUNT(*) FILTER (WHERE player_served AND had_match_point AND bps_in_game > 0)                        AS match_points_against_when_serving,
            COUNT(*) FILTER (WHERE player_served AND had_match_point AND bps_in_game > 0 AND player_won_game)    AS match_points_saved_serving,
            COUNT(DISTINCT match_id)                                                                             AS matches_analyzed,
            MAX(event_date)                                                                                       AS last_match_date
        FROM game_facts
        """,
        (player_id, player_id, player_id),
    )
    row = cur.fetchone()

    if not row or (row["service_games"] or 0) < MIN_SERVICE_GAMES:
        return None

    # Tiebreak data
    cur.execute(
        """
        SELECT
            COUNT(*) FILTER (WHERE ms.is_tiebreak)                                                          AS tiebreaks_played,
            COUNT(*) FILTER (
                WHERE ms.is_tiebreak AND
                  CASE WHEN m.first_player_id = %s
                       THEN ms.score_first  ~ '^[0-9.]+$' AND ms.score_first::float > ms.score_second::float
                       ELSE ms.score_second ~ '^[0-9.]+$' AND ms.score_second::float > ms.score_first::float
                  END
            )                                                                                                AS tiebreaks_won
        FROM match_scores ms
        JOIN matches m ON m.id = ms.match_id
        WHERE (m.first_player_id = %s OR m.second_player_id = %s)
          AND m.event_status = 'Finished'
          AND m.event_date >= CURRENT_DATE - INTERVAL '24 months'
        """,
        (player_id, player_id, player_id),
    )
    tb = cur.fetchone() or {}

    service_games = int(row["service_games"] or 0)
    service_holds = int(row["service_holds"] or 0)
    games_facing_bp     = int(row["games_facing_bp"] or 0)
    games_saving_all_bp = int(row["games_saving_all_bp"] or 0)
    bp_faced  = int(row["bp_faced"]  or 0)
    bp_saved  = int(row["bp_saved"]  or 0)
    return_games = int(row["return_games"] or 0)
    return_breaks = int(row["return_breaks"] or 0)
    bp_chances = int(row["bp_chances"] or 0)
    bp_converted = int(row["bp_converted"] or 0)

    out = {
        "service_games":     service_games,
        "service_holds":     service_holds,
        "service_hold_pct":  _pct(service_holds, service_games),
        "bp_faced":          bp_faced,
        "bp_saved":          bp_saved,
        "bp_save_pct":       _pct(bp_saved, bp_faced),
        "return_games":      return_games,
        "return_breaks":     return_breaks,
        "break_pct":         _pct(return_breaks, return_games),
        "bp_chances":        bp_chances,
        "bp_converted":      bp_converted,
        "bp_conversion_pct": _pct(bp_converted, bp_chances),
        "tiebreaks_played":  int(tb.get("tiebreaks_played") or 0),
        "tiebreaks_won":     int(tb.get("tiebreaks_won")    or 0),
        "tiebreak_win_pct":  _pct(int(tb.get("tiebreaks_won") or 0), int(tb.get("tiebreaks_played") or 0)),
        "set_points_faced":  int(row["set_points_against_when_serving"] or 0),
        "set_points_saved":  int(row["set_points_saved_serving"]        or 0),
        "set_point_save_pct": _pct(
            int(row["set_points_saved_serving"]        or 0),
            int(row["set_points_against_when_serving"] or 0),
        ),
        "match_points_faced": int(row["match_points_against_when_serving"] or 0),
        "match_points_saved": int(row["match_points_saved_serving"]        or 0),
        "match_point_save_pct": _pct(
            int(row["match_points_saved_serving"]        or 0),
            int(row["match_points_against_when_serving"] or 0),
        ),
        "matches_analyzed":  int(row["matches_analyzed"] or 0),
        "last_match_date":   row.get("last_match_date"),
    }
    return out


def upsert_stats(conn, player_id: int, stats: dict) -> None:
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO player_point_stats (
            player_id, service_games, service_holds, service_hold_pct,
            bp_faced, bp_saved, bp_save_pct,
            return_games, return_breaks, break_pct,
            bp_chances, bp_converted, bp_conversion_pct,
            tiebreaks_played, tiebreaks_won, tiebreak_win_pct,
            set_points_faced, set_points_saved, set_point_save_pct,
            match_points_faced, match_points_saved, match_point_save_pct,
            matches_analyzed, last_match_date, updated_at
        ) VALUES (
            %(player_id)s, %(service_games)s, %(service_holds)s, %(service_hold_pct)s,
            %(bp_faced)s, %(bp_saved)s, %(bp_save_pct)s,
            %(return_games)s, %(return_breaks)s, %(break_pct)s,
            %(bp_chances)s, %(bp_converted)s, %(bp_conversion_pct)s,
            %(tiebreaks_played)s, %(tiebreaks_won)s, %(tiebreak_win_pct)s,
            %(set_points_faced)s, %(set_points_saved)s, %(set_point_save_pct)s,
            %(match_points_faced)s, %(match_points_saved)s, %(match_point_save_pct)s,
            %(matches_analyzed)s, %(last_match_date)s, NOW()
        )
        ON CONFLICT (player_id) DO UPDATE SET
            service_games        = EXCLUDED.service_games,
            service_holds        = EXCLUDED.service_holds,
            service_hold_pct     = EXCLUDED.service_hold_pct,
            bp_faced             = EXCLUDED.bp_faced,
            bp_saved             = EXCLUDED.bp_saved,
            bp_save_pct          = EXCLUDED.bp_save_pct,
            return_games         = EXCLUDED.return_games,
            return_breaks        = EXCLUDED.return_breaks,
            break_pct            = EXCLUDED.break_pct,
            bp_chances           = EXCLUDED.bp_chances,
            bp_converted         = EXCLUDED.bp_converted,
            bp_conversion_pct    = EXCLUDED.bp_conversion_pct,
            tiebreaks_played     = EXCLUDED.tiebreaks_played,
            tiebreaks_won        = EXCLUDED.tiebreaks_won,
            tiebreak_win_pct     = EXCLUDED.tiebreak_win_pct,
            set_points_faced     = EXCLUDED.set_points_faced,
            set_points_saved     = EXCLUDED.set_points_saved,
            set_point_save_pct   = EXCLUDED.set_point_save_pct,
            match_points_faced   = EXCLUDED.match_points_faced,
            match_points_saved   = EXCLUDED.match_points_saved,
            match_point_save_pct = EXCLUDED.match_point_save_pct,
            matches_analyzed     = EXCLUDED.matches_analyzed,
            last_match_date      = EXCLUDED.last_match_date,
            updated_at           = NOW()
        """,
        {**stats, "player_id": player_id},
    )

    # Update player_ratings.serve_rating / return_rating with derived values
    serve_r  = _serve_rating_from_pcts(stats.get("service_hold_pct"), stats.get("bp_save_pct"))
    return_r = _return_rating_from_pcts(stats.get("break_pct"),       stats.get("bp_conversion_pct"))
    if serve_r is not None or return_r is not None:
        cur.execute(
            """
            UPDATE player_ratings SET
                serve_rating  = COALESCE(%s, serve_rating),
                return_rating = COALESCE(%s, return_rating),
                updated_at    = NOW()
            WHERE player_id = %s
            """,
            (serve_r, return_r, player_id),
        )


def run(conn) -> int:
    """Compute point stats for every player who has at least 30 service games. Returns rows updated."""
    log.info("Computing point analysis for all eligible players…")
    prev_autocommit = conn.autocommit
    conn.autocommit = True

    # Find players who participated in at least 1 match with point-by-point data
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT DISTINCT player_id FROM (
                SELECT m.first_player_id  AS player_id FROM matches m
                JOIN match_games mg ON mg.match_id = m.id
                WHERE m.event_date >= CURRENT_DATE - INTERVAL '24 months'
                UNION
                SELECT m.second_player_id FROM matches m
                JOIN match_games mg ON mg.match_id = m.id
                WHERE m.event_date >= CURRENT_DATE - INTERVAL '24 months'
            ) x
            WHERE player_id IS NOT NULL
            """
        )
        players = [r[0] for r in cur.fetchall()]

    log.info(f"  {len(players)} candidate players")

    written = 0
    for pid in players:
        try:
            stats = compute_for_player(conn, pid)
            if not stats:
                continue
            upsert_stats(conn, pid, stats)
            written += 1
        except Exception as e:
            log.warning(f"  player {pid}: {e}")

    conn.autocommit = prev_autocommit
    log.info(f"  ✅ Wrote point stats for {written} players")
    return written


def main():
    conn = psycopg2.connect(DB_URL)
    try:
        run(conn)
    finally:
        conn.close()


if __name__ == "__main__":
    main()
