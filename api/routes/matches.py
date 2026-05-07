"""
ratethat.tennis API — Match routes.

GET /matches/today
GET /matches/{id}
"""
from datetime import date, timedelta
from fastapi import APIRouter, HTTPException, Query
from typing import Optional

from api.db import query, query_one

router = APIRouter(prefix="/matches", tags=["matches"])


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _ratings_for(player_id: int) -> dict:
    """
    Return RTT ratings for a player. If no ML ratings exist yet, fall back to
    a rough rank-based approximation so the match detail page shows something
    rather than all dashes. Fallback values are flagged with is_estimated=True.
    """
    try:
        row = query_one(
            """
            SELECT rtt_score, clay_rating, hard_rating, grass_rating, indoor_rating,
                   serve_rating, return_rating, net_game_rating, pressure_rating,
                   consistency_score, form_score,
                   big_match_rating, vs_top10_rating, momentum
            FROM player_ratings
            WHERE player_id = %s
            """,
            (player_id,),
        )
        if row:
            return dict(row)
    except Exception as e:
        import logging
        logging.getLogger("api.matches").warning(
            f"_ratings_for({player_id}) DB error: {e}"
        )

    # Fallback: estimate a headline RTT score from the player's most recent
    # ATP ranking found in sa_matches (joined via name). Skill breakdowns stay None.
    try:
        import math
        # Resolve the production player name → sa_players lookup
        p = query_one("SELECT name FROM players WHERE id = %s", (player_id,))
        if p and p.get("name"):
            # Use the last token of the name (family name) for matching
            last = (p["name"] or "").strip().split(".")[-1].strip()
            rank_row = query_one(
                """
                SELECT COALESCE(
                    MIN(sm.winner_rank) FILTER (WHERE sm.winner_id = sp.player_id),
                    MIN(sm.loser_rank)  FILTER (WHERE sm.loser_id  = sp.player_id)
                ) AS recent_rank
                FROM sa_players sp
                JOIN sa_matches sm ON (sm.winner_id = sp.player_id OR sm.loser_id = sp.player_id)
                WHERE sp.full_name ILIKE %s
                  AND sm.tourney_date >= CURRENT_DATE - INTERVAL '2 years'
                """,
                (f"%{last}%",),
            )
            rank = rank_row.get("recent_rank") if rank_row else None
            if rank:
                rank = int(rank)
                # log-scale: rank 1 → ~95, rank 50 → ~72, rank 200 → ~57, rank 1000 → ~40
                rtt_approx = max(15, min(95, 110 - 15 * math.log10(max(1, rank))))
                return {
                    "rtt_score":          round(rtt_approx, 1),
                    "clay_rating":        None,
                    "hard_rating":        None,
                    "grass_rating":       None,
                    "indoor_rating":      None,
                    "serve_rating":       None,
                    "return_rating":      None,
                    "net_game_rating":    None,
                    "pressure_rating":    None,
                    "consistency_score":  None,
                    "form_score":         None,
                    "big_match_rating":   None,
                    "vs_top10_rating":    None,
                    "momentum":           None,
                    "is_estimated":       True,
                }
    except Exception:
        pass
    return {}


def _latest_odds(match_id: int) -> dict:
    """
    Return the BEST AVAILABLE market price per side (highest decimal_odds)
    from the most recent fetch per bookmaker. This matches what the
    OddsComparison component shows on the match page so the legacy
    'market' / 'edge' fields stay in sync with the headline view.
    """
    rows = query(
        """
        WITH latest_per_bm AS (
            SELECT DISTINCT ON (bookmaker, player_ref)
                bookmaker, player_ref, decimal_odds, implied_prob, fetched_at
            FROM bookmaker_odds
            WHERE match_id = %s
              AND decimal_odds IS NOT NULL
              AND decimal_odds > 1.0
            ORDER BY bookmaker, player_ref, fetched_at DESC
        )
        SELECT DISTINCT ON (player_ref)
            player_ref, bookmaker, decimal_odds, implied_prob
        FROM latest_per_bm
        ORDER BY player_ref, decimal_odds DESC
        """,
        (match_id,),
    )
    result: dict = {}
    for r in rows:
        key = "p1" if r["player_ref"] == "first_player" else "p2"
        result[key] = {
            "bookmaker": r["bookmaker"],
            "decimal_odds": float(r["decimal_odds"]) if r["decimal_odds"] else None,
            "implied_prob": float(r["implied_prob"]) if r["implied_prob"] else None,
        }
    return result


def _edge(model_prob: float | None, implied_prob: float | None) -> float | None:
    if model_prob is None or implied_prob is None:
        return None
    return round(model_prob - implied_prob, 4)


def _bulk_form_dots(player_ids: list, n: int = 10) -> dict:
    """
    Return {player_id: ['W','L',...]} for a list of player IDs in one query.
    Production matches only — fast. Players with fewer than n matches in our
    production data show fewer dots; that's fine for the list view.
    """
    if not player_ids:
        return {}
    placeholders = ",".join(["%s"] * len(player_ids))
    rows = query(
        f"""
        SELECT ids.player_id, sub.winner, sub.first_player_id
        FROM (
            SELECT unnest(ARRAY[{placeholders}]::int[]) AS player_id
        ) ids
        CROSS JOIN LATERAL (
            SELECT m.winner, m.first_player_id
            FROM matches m
            WHERE (m.first_player_id = ids.player_id OR m.second_player_id = ids.player_id)
              AND m.event_status = 'Finished'
              AND m.event_date IS NOT NULL
            ORDER BY m.event_date DESC, m.id DESC
            LIMIT %s
        ) sub
        """,
        player_ids + [n],
    )
    result: dict = {pid: [] for pid in player_ids}
    for r in rows:
        pid = r["player_id"]
        won = (r["winner"] == "First Player" and r["first_player_id"] == pid) or \
              (r["winner"] == "Second Player" and r["first_player_id"] != pid)
        result[pid].append("W" if won else "L")
    return result


def _form_dots(player_id: int, n: int = 10) -> list[str]:
    """Last N match results as W/L list."""
    rows = query(
        """
        SELECT m.winner, m.first_player_id
        FROM matches m
        WHERE (m.first_player_id = %s OR m.second_player_id = %s)
          AND m.event_status = 'Finished'
          AND m.event_date IS NOT NULL
        ORDER BY m.event_date DESC, m.id DESC
        LIMIT %s
        """,
        (player_id, player_id, n),
    )
    def _won(r: dict) -> bool:
        return (r["winner"] == "First Player" and r["first_player_id"] == player_id) or \
               (r["winner"] == "Second Player" and r["first_player_id"] != player_id)
    return ["W" if _won(r) else "L" for r in rows]


def _surface_stats(player_id: int) -> dict:
    """
    Win/loss record by surface from live match data (api-tennis.com).
    This is our own data — safe to surface on the frontend.
    """
    try:
        rows = query(
            """
            SELECT s.name AS surface, pss.wins, pss.losses, pss.season
            FROM player_surface_stats pss
            JOIN surfaces s ON s.id = pss.surface_id
            WHERE pss.player_id = %s
            ORDER BY pss.season DESC NULLS LAST, s.name
            """,
            (player_id,),
        )
        by_surface: dict = {}
        for r in rows:
            surf = (r["surface"] or "Unknown").lower()
            season = r["season"]
            w = r["wins"] or 0
            l = r["losses"] or 0
            total = w + l
            entry = {
                "wins": w,
                "losses": l,
                "total": total,
                "win_pct": round(w / total * 100, 1) if total else None,
                "season": season,
            }
            if surf not in by_surface:
                by_surface[surf] = entry
            # all-time row (season=NULL) takes priority
            elif season is None:
                by_surface[surf] = entry
        return by_surface
    except Exception:
        return {}


def _build_match_payload(match_id: int, m: dict) -> dict:
    """Build the full match detail payload."""
    p1_id = m["first_player_id"]
    p2_id = m["second_player_id"]

    # Players
    p1 = query_one(
        "SELECT id, name, full_name, country, country_code, birthday, hand, turned_pro, height_cm, logo_url FROM players WHERE id = %s",
        (p1_id,),
    ) or {}
    p2 = query_one(
        "SELECT id, name, full_name, country, country_code, birthday, hand, turned_pro, height_cm, logo_url FROM players WHERE id = %s",
        (p2_id,),
    ) or {}

    # Ratings
    p1_ratings = _ratings_for(p1_id)
    p2_ratings = _ratings_for(p2_id)

    # Form dots
    p1_form = _form_dots(p1_id)
    p2_form = _form_dots(p2_id)

    # Surface win/loss stats from live match data (api-tennis.com source — safe to surface)
    surface_name = m.get("surface_name") or ""
    p1_stats = _surface_stats(p1_id)
    p2_stats = _surface_stats(p2_id)

    # Per-player computed metrics: 3 new ratings + 8 statistics each.
    # Wrapped so any failure here can't break the match page.
    p1_metrics = {"ratings": {}, "stats": {}}
    p2_metrics = {"ratings": {}, "stats": {}}
    level_code = "A"
    try:
        from api.routes._player_metrics import player_match_metrics
        level_row = query_one(
            """
            SELECT et.tour_category, et.type_name
            FROM matches m
            LEFT JOIN event_types et ON et.id = m.event_type_id
            WHERE m.id = %s
            """,
            (match_id,),
        ) or {}

        def _level_code(tc, tn):
            tc = (tc or "").lower()
            tn = (tn or "").lower()
            if "grand slam" in tn:
                return "G"
            if "masters" in tn or "premier mandatory" in tn or "premier 5" in tn:
                return "M"
            if "challenger" in tc or "challenger" in tn:
                return "C"
            if "itf" in tc:
                return "S"
            return "A"

        level_code = _level_code(level_row.get("tour_category"), level_row.get("type_name"))

        if p1_id:
            p1_metrics = player_match_metrics(
                p1_id,
                opponent_hand=p2.get("hand"),
                surface=surface_name,
                level_code=level_code,
                player_rtt=float(p1_ratings.get("rtt_score")) if p1_ratings.get("rtt_score") is not None else None,
            )
        if p2_id:
            p2_metrics = player_match_metrics(
                p2_id,
                opponent_hand=p1.get("hand"),
                surface=surface_name,
                level_code=level_code,
                player_rtt=float(p2_ratings.get("rtt_score")) if p2_ratings.get("rtt_score") is not None else None,
            )
    except Exception as e:
        import logging
        logging.getLogger("api.matches").warning(f"player_match_metrics failed: {e}")

    # Prediction
    pred = query_one(
        """
        SELECT prob_first_player, prob_second_player, confidence,
               key_factors, narrative, analogue_description, bet_recommendations
        FROM model_predictions
        WHERE match_id = %s
        """,
        (match_id,),
    )

    # Market odds
    odds = _latest_odds(match_id)

    # Edge calculation
    edge: dict = {}
    if pred and odds:
        e_p1 = _edge(
            float(pred["prob_first_player"]) if pred.get("prob_first_player") else None,
            odds.get("p1", {}).get("implied_prob"),
        )
        e_p2 = _edge(
            float(pred["prob_second_player"]) if pred.get("prob_second_player") else None,
            odds.get("p2", {}).get("implied_prob"),
        )
        best = None
        if e_p1 is not None and e_p2 is not None:
            best = "p1" if abs(e_p1) > abs(e_p2) and e_p1 > 0.02 else (
                "p2" if e_p2 > 0.02 else None
            )
        edge = {"p1": e_p1, "p2": e_p2, "best_value": best}

    return {
        "match": {
            "match_id": m["id"],
            "tournament": m.get("tournament_name"),
            "surface": surface_name,
            "round": m.get("tournament_round"),
            "event_date": str(m["event_date"]) if m.get("event_date") else None,
            "event_time": str(m["event_time"]) if m.get("event_time") else None,
            "status": m.get("event_status"),
        },
        "players": {
            "first": {
                **p1,
                "ratings": {**p1_ratings, **p1_metrics["ratings"]},
                "form_dots": p1_form,
                "stats": p1_stats,
                "metrics": p1_metrics["stats"],
            },
            "second": {
                **p2,
                "ratings": {**p2_ratings, **p2_metrics["ratings"]},
                "form_dots": p2_form,
                "stats": p2_stats,
                "metrics": p2_metrics["stats"],
            },
        },
        "context": {
            "level_code": level_code,
            "p2_hand": p2.get("hand"),
            "p1_hand": p1.get("hand"),
        },
        "prediction": pred,
        "market": odds,
        "edge": edge,
    }


# ─────────────────────────────────────────────────────────────────────────────
# GET /matches/today
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/today")
def get_today_matches(days_ahead: int = Query(default=2, ge=0, le=7)):
    today = date.today()
    cutoff = today + timedelta(days=days_ahead)

    matches = query(
        """
        SELECT
            m.id,
            m.first_player_id,
            m.second_player_id,
            m.event_date,
            m.event_time,
            m.tournament_round,
            m.event_status,
            m.winner,
            m.final_result,
            m.game_result,
            m.is_live,
            t.name AS tournament_name,
            s.name AS surface_name,
            p1.name AS p1_name,
            p1.country_code AS p1_country,
            p2.name AS p2_name,
            p2.country_code AS p2_country,
            pr1.rtt_score AS p1_rtt,
            pr2.rtt_score AS p2_rtt,
            mp.prob_first_player,
            mp.prob_second_player,
            mp.confidence,
            ms.set_scores,
            bo1.decimal_odds AS odds_p1,
            bo1.implied_prob AS impl_p1,
            bo2.decimal_odds AS odds_p2,
            bo2.implied_prob AS impl_p2,
            et.gender AS event_gender,
            m.is_doubles
        FROM matches m
        LEFT JOIN tournaments t  ON t.id = m.tournament_id
        LEFT JOIN event_types et ON et.id = m.event_type_id
        LEFT JOIN players p1    ON p1.id = m.first_player_id
        LEFT JOIN players p2    ON p2.id = m.second_player_id
        LEFT JOIN surfaces s    ON s.id = t.surface_id
        LEFT JOIN player_ratings pr1 ON pr1.player_id = m.first_player_id
        LEFT JOIN player_ratings pr2 ON pr2.player_id = m.second_player_id
        LEFT JOIN model_predictions mp ON mp.match_id = m.id
        LEFT JOIN LATERAL (
            SELECT string_agg(score_first || '-' || score_second, ' ' ORDER BY set_number) AS set_scores
            FROM match_scores ms_inner
            WHERE ms_inner.match_id = m.id
        ) ms ON TRUE
        LEFT JOIN LATERAL (
            -- Best available price for first player across all bookmakers
            SELECT decimal_odds, implied_prob
            FROM (
                SELECT DISTINCT ON (bookmaker)
                    decimal_odds, implied_prob
                FROM bookmaker_odds
                WHERE match_id = m.id AND player_ref = 'first_player'
                  AND decimal_odds IS NOT NULL AND decimal_odds > 1.0
                ORDER BY bookmaker, fetched_at DESC
            ) latest
            ORDER BY decimal_odds DESC
            LIMIT 1
        ) bo1 ON TRUE
        LEFT JOIN LATERAL (
            -- Best available price for second player across all bookmakers
            SELECT decimal_odds, implied_prob
            FROM (
                SELECT DISTINCT ON (bookmaker)
                    decimal_odds, implied_prob
                FROM bookmaker_odds
                WHERE match_id = m.id AND player_ref = 'second_player'
                  AND decimal_odds IS NOT NULL AND decimal_odds > 1.0
                ORDER BY bookmaker, fetched_at DESC
            ) latest
            ORDER BY decimal_odds DESC
            LIMIT 1
        ) bo2 ON TRUE
        WHERE m.event_date >= %s AND m.event_date <= %s
          AND m.event_status NOT IN ('Cancelled', 'Postponed', 'Walkover')
        ORDER BY m.event_date, m.event_time NULLS LAST, m.id
        """,
        (today, cutoff),
    )

    # Bulk-load form dots for all players in one query
    all_player_ids = list({m["first_player_id"] for m in matches} | {m["second_player_id"] for m in matches})
    form_dots_map = _bulk_form_dots(all_player_ids, n=10)

    result = []
    for m in matches:
        p1_prob = float(m["prob_first_player"]) if m.get("prob_first_player") else None
        p2_prob = float(m["prob_second_player"]) if m.get("prob_second_player") else None
        impl_p1 = float(m["impl_p1"]) if m.get("impl_p1") else None
        impl_p2 = float(m["impl_p2"]) if m.get("impl_p2") else None

        e_p1 = _edge(p1_prob, impl_p1)
        e_p2 = _edge(p2_prob, impl_p2)
        best = None
        if e_p1 is not None and e_p2 is not None:
            best = "p1" if e_p1 > 0.02 and (e_p2 is None or e_p1 >= e_p2) else (
                "p2" if e_p2 > 0.02 else None
            )

        result.append({
            "match_id": m["id"],
            "tournament": m["tournament_name"],
            "surface": m["surface_name"],
            "round": m["tournament_round"],
            "event_date": str(m["event_date"]) if m["event_date"] else None,
            "event_time": str(m["event_time"]) if m["event_time"] else None,
            "event_status": m["event_status"],
            "winner": m.get("winner"),
            "final_result": m.get("final_result"),
            "game_result": m.get("game_result"),
            "set_scores":   m.get("set_scores"),
            "is_live": m.get("is_live"),
            "is_doubles": bool(m.get("is_doubles")),
            "gender": m.get("event_gender"),  # 'Men' | 'Women' | None
            "first_player": {
                "id": m["first_player_id"],
                "name": m["p1_name"],
                "country_code": m["p1_country"],
                "rtt_score": float(m["p1_rtt"]) if m.get("p1_rtt") else None,
                "form_dots": form_dots_map.get(m["first_player_id"], []),
            },
            "second_player": {
                "id": m["second_player_id"],
                "name": m["p2_name"],
                "country_code": m["p2_country"],
                "rtt_score": float(m["p2_rtt"]) if m.get("p2_rtt") else None,
                "form_dots": form_dots_map.get(m["second_player_id"], []),
            },
            "prediction": {
                "prob_first_player": p1_prob,
                "prob_second_player": p2_prob,
                "confidence": m.get("confidence"),
                "edge_first":  e_p1,
                "edge_second": e_p2,
            },
            "market": {
                "odds_first_player": float(m["odds_p1"]) if m.get("odds_p1") else None,
                "odds_second_player": float(m["odds_p2"]) if m.get("odds_p2") else None,
                "implied_first": impl_p1,
                "implied_second": impl_p2,
            },
            "edge": {"p1": e_p1, "p2": e_p2, "best_value": best},
        })

    return {"date_range": {"from": str(today), "to": str(cutoff)}, "matches": result}


# ─────────────────────────────────────────────────────────────────────────────
# GET /matches/{id}
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/{match_id}")
def get_match(match_id: int):
    m = query_one(
        """
        SELECT
            m.id,
            m.first_player_id,
            m.second_player_id,
            m.event_date,
            m.event_time,
            m.tournament_round,
            m.event_status,
            m.winner,
            t.name AS tournament_name,
            s.name AS surface_name
        FROM matches m
        LEFT JOIN tournaments t ON t.id = m.tournament_id
        LEFT JOIN surfaces s ON s.id = t.surface_id
        WHERE m.id = %s
        """,
        (match_id,),
    )
    if not m:
        raise HTTPException(status_code=404, detail="Match not found")

    return _build_match_payload(match_id, m)
