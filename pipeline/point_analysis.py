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


def _serve_rating_from_pcts(hold_pct, bp_save_pct, love_hold_pct=None) -> Optional[float]:
    """
    Spec: 0.5 × hold% + 0.3 × bp_save% + 0.2 × love_hold_rate
    Each component scaled to a tour-pro range first.
    """
    if hold_pct is None:
        return None
    hold_score      = max(0, min(100, (hold_pct      - 55.0) * 2.5))
    bp_save_score   = max(0, min(100, (bp_save_pct   - 50.0) * 3.3)) if bp_save_pct is not None else hold_score
    love_hold_score = max(0, min(100, (love_hold_pct - 10.0) * 2.5)) if love_hold_pct is not None else hold_score
    rating = 0.5 * hold_score + 0.3 * bp_save_score + 0.2 * love_hold_score
    return round(max(5.0, min(95.0, rating)), 2)


def _return_rating_from_pcts(break_pct, conv_pct, deuce_win_pct=None) -> Optional[float]:
    """
    Spec: 0.5 × break% + 0.3 × bp_conversion% + 0.2 × deuce_win_rate_as_returner
    """
    if break_pct is None:
        return None
    break_score    = max(0, min(100, (break_pct      - 8.0) * 3.5))
    conv_score     = max(0, min(100, (conv_pct       - 25.0) * 2.5)) if conv_pct       is not None else break_score
    deuce_score    = max(0, min(100, (deuce_win_pct  - 30.0) * 2.5)) if deuce_win_pct  is not None else break_score
    rating = 0.5 * break_score + 0.3 * conv_score + 0.2 * deuce_score
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

    # ─── Extras: love holds, avg service game length, pressure pts, set 1 recovery, longest run ───
    cur.execute(
        """
        WITH player_position AS (
            SELECT m.id AS match_id,
                   CASE WHEN m.first_player_id = %s THEN 'First Player' ELSE 'Second Player' END AS pos,
                   m.winner
            FROM matches m
            WHERE (m.first_player_id = %s OR m.second_player_id = %s)
              AND m.event_status = 'Finished'
              AND m.event_date >= CURRENT_DATE - INTERVAL '24 months'
        ),
        love_holds AS (
            SELECT mg.id
            FROM player_position pp
            JOIN match_games mg ON mg.match_id = pp.match_id
            WHERE mg.player_served = pp.pos
              AND mg.serve_winner  = pp.pos
              AND (SELECT COUNT(*) FROM match_points mp WHERE mp.game_id = mg.id) > 0
              AND NOT EXISTS (
                  SELECT 1 FROM match_points mp
                  WHERE mp.game_id = mg.id
                    AND (mp.is_break_point OR mp.score IN ('0-15','0-30','0-40','15-30','15-40','30-40'))
              )
        ),
        service_game_pts AS (
            SELECT mg.id AS game_id,
                   (SELECT COUNT(*) FROM match_points mp WHERE mp.game_id = mg.id) AS n_pts
            FROM player_position pp
            JOIN match_games mg ON mg.match_id = pp.match_id
            WHERE mg.player_served = pp.pos
        ),
        pressure_points AS (
            SELECT mp.id, mp.game_id, mp.is_break_point, mp.is_set_point, mp.is_match_point,
                   mg.player_served, mg.serve_winner, pp.pos
            FROM player_position pp
            JOIN match_games mg ON mg.match_id = pp.match_id
            JOIN match_points mp ON mp.game_id = mg.id
            WHERE mp.is_break_point OR mp.is_set_point OR mp.is_match_point
        ),
        set1_recovery AS (
            SELECT
                COUNT(*) AS n,
                SUM(CASE WHEN pp.winner = pp.pos THEN 1 ELSE 0 END) AS won
            FROM player_position pp
            JOIN match_scores ms1 ON ms1.match_id = pp.match_id AND ms1.set_number = 1
            WHERE ms1.score_first ~ '^[0-9.]+$'
              AND ms1.score_second ~ '^[0-9.]+$'
              AND CASE
                    WHEN pp.pos = 'First Player'  THEN ms1.score_first::float  < ms1.score_second::float
                    ELSE                                 ms1.score_second::float < ms1.score_first::float
                  END
        )
        SELECT
            (SELECT COUNT(*) FROM love_holds) AS love_holds,
            (SELECT AVG(n_pts) FROM service_game_pts WHERE n_pts > 0) AS avg_service_game_pts,
            (SELECT COUNT(*) FROM pressure_points) AS pressure_pts_total,
            (SELECT COUNT(*) FROM pressure_points
              WHERE (player_served = pos       AND serve_winner = pos)
                 OR (player_served != pos      AND serve_winner = pos)) AS pressure_pts_won_approx,
            (SELECT n FROM set1_recovery) AS set1_lost,
            (SELECT won FROM set1_recovery) AS set1_lost_recovered
        """,
        (player_id, player_id, player_id),
    )
    extras = cur.fetchone() or {}

    love_holds         = int(extras.get("love_holds") or 0)
    avg_svc_game_pts   = float(extras.get("avg_service_game_pts")) if extras.get("avg_service_game_pts") is not None else None
    pressure_total     = int(extras.get("pressure_pts_total") or 0)
    pressure_won       = int(extras.get("pressure_pts_won_approx") or 0)
    set1_lost          = int(extras.get("set1_lost") or 0)
    set1_recovered     = int(extras.get("set1_lost_recovered") or 0)

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
        # Extras
        "love_holds":          love_holds,
        "love_hold_pct":       _pct(love_holds, service_games),
        "avg_service_game_pts": round(avg_svc_game_pts, 2) if avg_svc_game_pts is not None else None,
        "pressure_pts_faced":  pressure_total,
        "pressure_pts_won":    pressure_won,
        "pressure_win_pct":    _pct(pressure_won, pressure_total),
        "set1_lost":           set1_lost,
        "set1_lost_recovered": set1_recovered,
        "set1_recovery_pct":   _pct(set1_recovered, set1_lost),
        "longest_game_run":    None,           # intentionally TBD — needs sequential pass; placeholder
        "deuce_pts_won_ret":   0,
        "deuce_pts_total_ret": 0,
        "deuce_win_pct_ret":   None,
        "matches_analyzed":    int(row["matches_analyzed"] or 0),
        "last_match_date":     row.get("last_match_date"),
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
            love_holds, love_hold_pct, avg_service_game_pts,
            pressure_pts_faced, pressure_pts_won, pressure_win_pct,
            set1_lost, set1_lost_recovered, set1_recovery_pct,
            longest_game_run, deuce_pts_won_ret, deuce_pts_total_ret, deuce_win_pct_ret,
            matches_analyzed, last_match_date, updated_at
        ) VALUES (
            %(player_id)s, %(service_games)s, %(service_holds)s, %(service_hold_pct)s,
            %(bp_faced)s, %(bp_saved)s, %(bp_save_pct)s,
            %(return_games)s, %(return_breaks)s, %(break_pct)s,
            %(bp_chances)s, %(bp_converted)s, %(bp_conversion_pct)s,
            %(tiebreaks_played)s, %(tiebreaks_won)s, %(tiebreak_win_pct)s,
            %(set_points_faced)s, %(set_points_saved)s, %(set_point_save_pct)s,
            %(match_points_faced)s, %(match_points_saved)s, %(match_point_save_pct)s,
            %(love_holds)s, %(love_hold_pct)s, %(avg_service_game_pts)s,
            %(pressure_pts_faced)s, %(pressure_pts_won)s, %(pressure_win_pct)s,
            %(set1_lost)s, %(set1_lost_recovered)s, %(set1_recovery_pct)s,
            %(longest_game_run)s, %(deuce_pts_won_ret)s, %(deuce_pts_total_ret)s, %(deuce_win_pct_ret)s,
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
            love_holds           = EXCLUDED.love_holds,
            love_hold_pct        = EXCLUDED.love_hold_pct,
            avg_service_game_pts = EXCLUDED.avg_service_game_pts,
            pressure_pts_faced   = EXCLUDED.pressure_pts_faced,
            pressure_pts_won     = EXCLUDED.pressure_pts_won,
            pressure_win_pct     = EXCLUDED.pressure_win_pct,
            set1_lost            = EXCLUDED.set1_lost,
            set1_lost_recovered  = EXCLUDED.set1_lost_recovered,
            set1_recovery_pct    = EXCLUDED.set1_recovery_pct,
            longest_game_run     = EXCLUDED.longest_game_run,
            deuce_pts_won_ret    = EXCLUDED.deuce_pts_won_ret,
            deuce_pts_total_ret  = EXCLUDED.deuce_pts_total_ret,
            deuce_win_pct_ret    = EXCLUDED.deuce_win_pct_ret,
            matches_analyzed     = EXCLUDED.matches_analyzed,
            last_match_date      = EXCLUDED.last_match_date,
            updated_at           = NOW()
        """,
        {**stats, "player_id": player_id},
    )

    # Update player_ratings.serve_rating / return_rating with the spec'd formula
    serve_r  = _serve_rating_from_pcts(
        stats.get("service_hold_pct"),
        stats.get("bp_save_pct"),
        stats.get("love_hold_pct"),
    )
    return_r = _return_rating_from_pcts(
        stats.get("break_pct"),
        stats.get("bp_conversion_pct"),
        stats.get("deuce_win_pct_ret"),
    )
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
