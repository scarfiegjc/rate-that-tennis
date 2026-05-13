"""
ratethat.tennis API — Predictions tracker + systems routes.

GET /predictions/today
GET /predictions/history?date=YYYY-MM-DD&limit=…
GET /predictions/stats
GET /systems
GET /systems/{code}/picks?status=open|settled
GET /systems/{code}/stats

Resilience: every view-backed query is wrapped in safe_query so the page
shows "no data yet" instead of a 500 if the migrations haven't applied.
"""
import logging
from datetime import date, timedelta
from typing import Optional

from fastapi import APIRouter, HTTPException, Query

from api.db import query, query_one

log = logging.getLogger("api.predictions")

router = APIRouter(tags=["predictions"])


def safe_query(sql: str, params=None) -> list[dict]:
    """Run a query; if a view/table is missing, return [] instead of raising."""
    try:
        return query(sql, params)
    except Exception as e:
        msg = str(e).lower()
        if "does not exist" in msg or "undefined table" in msg or "undefined column" in msg:
            log.warning(f"safe_query: missing schema, returning []: {e}")
            return []
        raise


def safe_query_one(sql: str, params=None) -> Optional[dict]:
    try:
        return query_one(sql, params)
    except Exception as e:
        msg = str(e).lower()
        if "does not exist" in msg or "undefined table" in msg or "undefined column" in msg:
            log.warning(f"safe_query_one: missing schema, returning None: {e}")
            return None
        raise


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _serialise_prediction_row(r: dict) -> dict:
    """Normalise a row from v_predictions_with_results for frontend use."""
    p1_prob = float(r["prob_first_player"]) if r.get("prob_first_player") is not None else None
    p2_prob = float(r["prob_second_player"]) if r.get("prob_second_player") is not None else None
    return {
        "match_id": r["match_id"],
        "event_date": str(r["event_date"]) if r.get("event_date") else None,
        "event_time": str(r["event_time"]) if r.get("event_time") else None,
        "event_status": r.get("event_status"),
        "tournament": r.get("tournament_name"),
        "surface": r.get("surface_name"),
        "round": r.get("tournament_round"),
        "p1": {
            "id": r.get("p1_id"),
            "name": r.get("p1_name"),
            "country_code": r.get("p1_country"),
            "prob": p1_prob,
        },
        "p2": {
            "id": r.get("p2_id"),
            "name": r.get("p2_name"),
            "country_code": r.get("p2_country"),
            "prob": p2_prob,
        },
        "confidence": r.get("confidence"),
        "predicted_winner": r.get("predicted_winner"),
        "actual_winner": r.get("actual_winner"),
        "is_correct": r.get("is_correct"),
        "settled_at": str(r["settled_at"]) if r.get("settled_at") else None,
        "predicted_at": str(r["predicted_at"]) if r.get("predicted_at") else None,
        "predictor_version": r.get("predictor_version"),
        "rtt_gap": float(r["rtt_gap"]) if r.get("rtt_gap") is not None else None,
        "surface_gap": float(r["surface_gap"]) if r.get("surface_gap") is not None else None,
        "form_gap": float(r["form_gap"]) if r.get("form_gap") is not None else None,
        "total_logit": float(r["total_logit"]) if r.get("total_logit") is not None else None,
        "key_factors": r.get("key_factors"),
    }


# ─────────────────────────────────────────────────────────────────────────────
# GET /predictions/today
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/matches/{match_id}/intelligence")
def match_intelligence(match_id: int):
    """
    Returns the deep-reasoning intelligence text for a match (3 paragraphs).
    If not yet generated, returns has_intel=false and the rich match facts
    needed to generate it.
    """
    row = safe_query_one(
        """
        SELECT
            mp.match_id,
            mp.p1_intel, mp.p2_intel, mp.match_preview,
            mp.did_you_know, mp.confidence_line,
            mp.intel_generated_at, mp.intel_model,
            mp.prob_first_player, mp.prob_second_player,
            mp.confidence, mp.rtt_gap, mp.surface_gap, mp.form_gap,
            mp.predicted_winner,
            m.event_date, m.event_time, m.tournament_round,
            t.name AS tournament_name,
            s.name AS surface_name,
            p1.id AS p1_id, p1.name AS p1_name, p1.full_name AS p1_full,
            p1.country AS p1_country, p1.country_code AS p1_country_code,
            p1.hand AS p1_hand, p1.birthday AS p1_birthday,
            p2.id AS p2_id, p2.name AS p2_name, p2.full_name AS p2_full,
            p2.country AS p2_country, p2.country_code AS p2_country_code,
            p2.hand AS p2_hand, p2.birthday AS p2_birthday,
            pr1.rtt_score AS p1_rtt, pr1.clay_rating AS p1_clay,
            pr1.hard_rating AS p1_hard, pr1.grass_rating AS p1_grass,
            pr1.indoor_rating AS p1_indoor, pr1.form_score AS p1_form,
            pr1.momentum AS p1_momentum,
            pr2.rtt_score AS p2_rtt, pr2.clay_rating AS p2_clay,
            pr2.hard_rating AS p2_hard, pr2.grass_rating AS p2_grass,
            pr2.indoor_rating AS p2_indoor, pr2.form_score AS p2_form,
            pr2.momentum AS p2_momentum
        FROM matches m
        LEFT JOIN model_predictions mp ON mp.match_id = m.id
        LEFT JOIN tournaments t ON t.id = m.tournament_id
        LEFT JOIN surfaces s ON s.id = t.surface_id
        LEFT JOIN players p1 ON p1.id = m.first_player_id
        LEFT JOIN players p2 ON p2.id = m.second_player_id
        LEFT JOIN player_ratings pr1 ON pr1.player_id = m.first_player_id
        LEFT JOIN player_ratings pr2 ON pr2.player_id = m.second_player_id
        WHERE m.id = %s
        """,
        (match_id,),
    )
    if not row:
        raise HTTPException(status_code=404, detail="Match not found")

    has_intel = bool(row.get("p1_intel") and row.get("p2_intel") and row.get("match_preview"))

    # Recent form for both players (last 10 W/L with opponent + score)
    def _form(pid):
        return safe_query(
            """
            SELECT m.event_date, m.tournament_round AS round, t.name AS tournament,
                   s.name AS surface, m.final_result,
                   CASE WHEN m.first_player_id = %s THEN p2.name ELSE p1.name END AS opp,
                   CASE WHEN (m.winner = 'First Player'  AND m.first_player_id  = %s)
                          OR (m.winner = 'Second Player' AND m.second_player_id = %s)
                        THEN 'W' ELSE 'L' END AS result
            FROM matches m
            JOIN players p1 ON p1.id = m.first_player_id
            JOIN players p2 ON p2.id = m.second_player_id
            LEFT JOIN tournaments t ON t.id = m.tournament_id
            LEFT JOIN surfaces s ON s.id = t.surface_id
            WHERE (m.first_player_id = %s OR m.second_player_id = %s)
              AND m.event_status = 'Finished'
              AND m.winner IS NOT NULL
            ORDER BY m.event_date DESC
            LIMIT 10
            """,
            (pid, pid, pid, pid, pid),
        )

    p1_form = _form(row["p1_id"]) if row.get("p1_id") else []
    p2_form = _form(row["p2_id"]) if row.get("p2_id") else []

    def _enrich_form(form, p_rtt):
        """Pull out narrative-friendly signals from the recent form list."""
        wins = [f for f in form if f.get("result") == "W"]
        losses = [f for f in form if f.get("result") == "L"]
        # Best recent win = the highest-status W (Slam > Masters > 500 > 250 > Challenger > ITF)
        best_win = wins[0] if wins else None
        # Current streak
        streak_type, streak_len = ("W" if form and form[0]["result"] == "W" else "L"), 0
        for f in form:
            if f["result"] == streak_type:
                streak_len += 1
            else:
                break
        return {
            "win_loss_last_10":  f"{len(wins)}-{len(losses)}",
            "current_streak":    f"{streak_type}{streak_len}",
            "current_streak_type": streak_type,
            "current_streak_len": streak_len,
            "most_recent_win":   best_win,
            "most_recent_match": form[0] if form else None,
        }

    p1_summary = _enrich_form(p1_form, row.get("p1_rtt"))
    p2_summary = _enrich_form(p2_form, row.get("p2_rtt"))

    # Surface preference call-out: which surface is each player rated highest on
    def _best_surface(p):
        rts = {
            "clay":   p.get("clay_rating"),
            "hard":   p.get("hard_rating"),
            "grass":  p.get("grass_rating"),
            "indoor": p.get("indoor_rating"),
        }
        valid = {k: v for k, v in rts.items() if v is not None}
        if not valid:
            return None
        best_surf = max(valid, key=valid.get)
        return {"surface": best_surf, "rating": valid[best_surf]}

    p1_best = _best_surface({
        "clay_rating":   float(row["p1_clay"])   if row.get("p1_clay")   is not None else None,
        "hard_rating":   float(row["p1_hard"])   if row.get("p1_hard")   is not None else None,
        "grass_rating":  float(row["p1_grass"])  if row.get("p1_grass")  is not None else None,
        "indoor_rating": float(row["p1_indoor"]) if row.get("p1_indoor") is not None else None,
    })
    p2_best = _best_surface({
        "clay_rating":   float(row["p2_clay"])   if row.get("p2_clay")   is not None else None,
        "hard_rating":   float(row["p2_hard"])   if row.get("p2_hard")   is not None else None,
        "grass_rating":  float(row["p2_grass"])  if row.get("p2_grass")  is not None else None,
        "indoor_rating": float(row["p2_indoor"]) if row.get("p2_indoor") is not None else None,
    })

    # H2H — quick lookup
    h2h = safe_query_one(
        """
        SELECT
            SUM(CASE WHEN m.winner = 'First Player'  THEN
                    CASE WHEN m.first_player_id = %s  THEN 1 ELSE 0 END
                ELSE CASE WHEN m.second_player_id = %s THEN 1 ELSE 0 END
                END) AS p1_wins,
            SUM(CASE WHEN m.winner = 'First Player'  THEN
                    CASE WHEN m.first_player_id = %s  THEN 1 ELSE 0 END
                ELSE CASE WHEN m.second_player_id = %s THEN 1 ELSE 0 END
                END) AS p2_wins,
            COUNT(*) AS total
        FROM matches m
        WHERE ((m.first_player_id = %s AND m.second_player_id = %s)
            OR (m.first_player_id = %s AND m.second_player_id = %s))
          AND m.event_status = 'Finished'
        """,
        (row["p1_id"], row["p1_id"], row["p2_id"], row["p2_id"],
         row["p1_id"], row["p2_id"], row["p2_id"], row["p1_id"]),
    )

    return {
        "match_id":  match_id,
        "has_intel": has_intel,
        "intel": {
            "p1_intel":        row.get("p1_intel"),
            "p2_intel":        row.get("p2_intel"),
            "match_preview":   row.get("match_preview"),
            "did_you_know":    row.get("did_you_know"),
            "confidence_line": row.get("confidence_line"),
            "generated_at":    str(row["intel_generated_at"]) if row.get("intel_generated_at") else None,
            "model":           row.get("intel_model"),
        },
        "facts": {
            "match": {
                "tournament": row.get("tournament_name"),
                "round":      row.get("tournament_round"),
                "surface":    row.get("surface_name"),
                "event_date": str(row["event_date"]) if row.get("event_date") else None,
            },
            "prediction": {
                "prob_first_player":  float(row["prob_first_player"])  if row.get("prob_first_player")  is not None else None,
                "prob_second_player": float(row["prob_second_player"]) if row.get("prob_second_player") is not None else None,
                "confidence":         row.get("confidence"),
                "predicted_winner":   row.get("predicted_winner"),
                "rtt_gap":     float(row["rtt_gap"])     if row.get("rtt_gap")     is not None else None,
                "surface_gap": float(row["surface_gap"]) if row.get("surface_gap") is not None else None,
                "form_gap":    float(row["form_gap"])    if row.get("form_gap")    is not None else None,
            },
            "p1": {
                "id":           row["p1_id"],
                "name":         row.get("p1_name"),
                "full_name":    row.get("p1_full"),
                "country":      row.get("p1_country"),
                "country_code": row.get("p1_country_code"),
                "hand":         row.get("p1_hand"),
                "birthday":     str(row["p1_birthday"]) if row.get("p1_birthday") else None,
                "rtt":          float(row["p1_rtt"])    if row.get("p1_rtt") is not None else None,
                "form":         float(row["p1_form"])   if row.get("p1_form") is not None else None,
                "momentum":     row.get("p1_momentum"),
                "surface_ratings": {
                    "clay":   float(row["p1_clay"])   if row.get("p1_clay")   is not None else None,
                    "hard":   float(row["p1_hard"])   if row.get("p1_hard")   is not None else None,
                    "grass":  float(row["p1_grass"])  if row.get("p1_grass")  is not None else None,
                    "indoor": float(row["p1_indoor"]) if row.get("p1_indoor") is not None else None,
                },
                "recent_form": [
                    {"date": str(f["event_date"]) if f.get("event_date") else None,
                     "result": f["result"], "opp": f.get("opp"),
                     "score": f.get("final_result"), "tournament": f.get("tournament"),
                     "surface": f.get("surface"), "round": f.get("round")}
                    for f in p1_form
                ],
            },
            "p2": {
                "id":           row["p2_id"],
                "name":         row.get("p2_name"),
                "full_name":    row.get("p2_full"),
                "country":      row.get("p2_country"),
                "country_code": row.get("p2_country_code"),
                "hand":         row.get("p2_hand"),
                "birthday":     str(row["p2_birthday"]) if row.get("p2_birthday") else None,
                "rtt":          float(row["p2_rtt"])    if row.get("p2_rtt") is not None else None,
                "form":         float(row["p2_form"])   if row.get("p2_form") is not None else None,
                "momentum":     row.get("p2_momentum"),
                "surface_ratings": {
                    "clay":   float(row["p2_clay"])   if row.get("p2_clay")   is not None else None,
                    "hard":   float(row["p2_hard"])   if row.get("p2_hard")   is not None else None,
                    "grass":  float(row["p2_grass"])  if row.get("p2_grass")  is not None else None,
                    "indoor": float(row["p2_indoor"]) if row.get("p2_indoor") is not None else None,
                },
                "recent_form": [
                    {"date": str(f["event_date"]) if f.get("event_date") else None,
                     "result": f["result"], "opp": f.get("opp"),
                     "score": f.get("final_result"), "tournament": f.get("tournament"),
                     "surface": f.get("surface"), "round": f.get("round")}
                    for f in p2_form
                ],
            },
            "h2h": {
                "p1_wins": int(h2h.get("p1_wins") or 0) if h2h else 0,
                "p2_wins": int(h2h.get("p2_wins") or 0) if h2h else 0,
                "total":   int(h2h.get("total")   or 0) if h2h else 0,
                "last_meeting": _last_h2h_meeting(row["p1_id"], row["p2_id"]) if row.get("p1_id") and row.get("p2_id") else None,
            },
            "market": _latest_odds_for_match(match_id),
            "summaries": {
                "p1": p1_summary,
                "p2": p2_summary,
                "p1_best_surface": p1_best,
                "p2_best_surface": p2_best,
            },
            "did_you_know_candidates": _did_you_know_candidates(
                row, p1_summary, p2_summary, p1_best, p2_best, h2h, p1_form, p2_form
            ),
        },
    }


def _last_h2h_meeting(p1_id: int, p2_id: int) -> Optional[dict]:
    return safe_query_one(
        """
        SELECT m.event_date, t.name AS tournament, s.name AS surface,
               m.tournament_round AS round, m.final_result,
               CASE WHEN m.winner = 'First Player'  AND m.first_player_id  = %s THEN 'p1'
                    WHEN m.winner = 'Second Player' AND m.second_player_id = %s THEN 'p1'
                    WHEN m.winner = 'First Player'  AND m.first_player_id  = %s THEN 'p2'
                    WHEN m.winner = 'Second Player' AND m.second_player_id = %s THEN 'p2'
                    ELSE NULL END AS winner
        FROM matches m
        LEFT JOIN tournaments t ON t.id = m.tournament_id
        LEFT JOIN surfaces s    ON s.id = t.surface_id
        WHERE ((m.first_player_id = %s AND m.second_player_id = %s)
            OR (m.first_player_id = %s AND m.second_player_id = %s))
          AND m.event_status = 'Finished'
          AND m.winner IS NOT NULL
        ORDER BY m.event_date DESC
        LIMIT 1
        """,
        (p1_id, p1_id, p2_id, p2_id, p1_id, p2_id, p2_id, p1_id),
    )


def _did_you_know_candidates(row, p1s, p2s, p1_best, p2_best, h2h, p1_form, p2_form):
    """Pre-cooked striking facts the AI can pick from."""
    cands = []
    p1_name = row.get("p1_name") or "P1"
    p2_name = row.get("p2_name") or "P2"
    surface = (row.get("surface_name") or "").lower()

    # 1. Win/loss over last 10
    cands.append({
        "code": "p1_recent_wl",
        "fact": f"{p1_name} is {p1s['win_loss_last_10']} in his last 10 matches.",
    })
    cands.append({
        "code": "p2_recent_wl",
        "fact": f"{p2_name} is {p2s['win_loss_last_10']} in his last 10 matches.",
    })
    # 2. Current streak (if 3+)
    if p1s["current_streak_len"] >= 3:
        verb = "winning" if p1s["current_streak_type"] == "W" else "losing"
        cands.append({"code": "p1_streak",
                      "fact": f"{p1_name} comes in {verb} {p1s['current_streak_len']} matches in a row."})
    if p2s["current_streak_len"] >= 3:
        verb = "winning" if p2s["current_streak_type"] == "W" else "losing"
        cands.append({"code": "p2_streak",
                      "fact": f"{p2_name} comes in {verb} {p2s['current_streak_len']} matches in a row."})
    # 3. Best surface match-up
    if p1_best and surface and p1_best["surface"] in surface:
        cands.append({
            "code": "p1_on_best_surface",
            "fact": f"{p1_name} is playing his strongest surface ({p1_best['surface']}, rated {round(p1_best['rating'])}).",
        })
    if p2_best and surface and p2_best["surface"] in surface:
        cands.append({
            "code": "p2_on_best_surface",
            "fact": f"{p2_name} is playing his strongest surface ({p2_best['surface']}, rated {round(p2_best['rating'])}).",
        })
    # 4. H2H
    total = (h2h.get("total") or 0) if h2h else 0
    p1w = (h2h.get("p1_wins") or 0) if h2h else 0
    p2w = (h2h.get("p2_wins") or 0) if h2h else 0
    if total >= 1:
        if p1w > p2w:
            cands.append({"code": "h2h",
                          "fact": f"{p1_name} leads the head-to-head {p1w}-{p2w} from {total} previous meetings."})
        elif p2w > p1w:
            cands.append({"code": "h2h",
                          "fact": f"{p2_name} leads the head-to-head {p2w}-{p1w} from {total} previous meetings."})
        else:
            cands.append({"code": "h2h",
                          "fact": f"They have met {total} time{'s' if total > 1 else ''} before with the head-to-head locked at {p1w}-{p2w}."})
    # 5. Big recent win
    def _big_win(form, name):
        if not form:
            return None
        for f in form[:5]:
            if f.get("result") != "W":
                continue
            tour = (f.get("tournament") or "").lower()
            if any(k in tour for k in ("masters","slam","wimbledon","roland","open","atp","wta","championship","finals")):
                return f"{name} beat {f.get('opp')} {f.get('score') or ''} in the {f.get('round') or 'previous round'} at {f.get('tournament')}."
        return None
    bw1 = _big_win(p1_form, p1_name)
    if bw1: cands.append({"code": "p1_big_win", "fact": bw1.strip()})
    bw2 = _big_win(p2_form, p2_name)
    if bw2: cands.append({"code": "p2_big_win", "fact": bw2.strip()})
    # 6. RTT gap call-out
    p1_rtt = float(row["p1_rtt"]) if row.get("p1_rtt") is not None else None
    p2_rtt = float(row["p2_rtt"]) if row.get("p2_rtt") is not None else None
    if p1_rtt is not None and p2_rtt is not None and abs(p1_rtt - p2_rtt) >= 12:
        leader, gap = (p1_name, p1_rtt - p2_rtt) if p1_rtt > p2_rtt else (p2_name, p2_rtt - p1_rtt)
        cands.append({
            "code": "rtt_gap",
            "fact": f"{leader} comes in with a {round(gap)}-point RTT advantage — a clear class gap.",
        })
    return cands


def _latest_odds_for_match(match_id: int) -> dict:
    """Latest bookmaker odds for a match — feeds into the AI's market sentence."""
    rows = safe_query(
        """
        SELECT DISTINCT ON (player_ref)
            player_ref, bookmaker, decimal_odds, implied_prob, fetched_at
        FROM bookmaker_odds
        WHERE match_id = %s
        ORDER BY player_ref, fetched_at DESC
        """,
        (match_id,),
    )
    out = {"p1": None, "p2": None}
    for r in rows:
        side = "p1" if r["player_ref"] == "first_player" else "p2"
        out[side] = {
            "bookmaker":    r.get("bookmaker"),
            "decimal_odds": float(r["decimal_odds"]) if r.get("decimal_odds") else None,
            "implied_prob": float(r["implied_prob"]) if r.get("implied_prob") else None,
        }
    return out


@router.get("/matches/{match_id}/point-analysis")
def match_point_analysis(match_id: int):
    """Returns both players' point stats for a match (service hold, break %, etc)."""
    m = safe_query_one(
        "SELECT first_player_id, second_player_id FROM matches WHERE id = %s",
        (match_id,),
    )
    if not m:
        raise HTTPException(status_code=404, detail="Match not found")

    def _stats_for(pid):
        if not pid:
            return None
        return safe_query_one(
            """
            SELECT * FROM player_point_stats WHERE player_id = %s
            """,
            (pid,),
        )

    p1_stats = _stats_for(m["first_player_id"])
    p2_stats = _stats_for(m["second_player_id"])

    def _norm(s):
        if not s:
            return None
        # Convert NUMERIC to float, dates to str
        return {
            k: (float(v) if hasattr(v, '__float__') and not isinstance(v, (bool, int)) else
                str(v) if hasattr(v, 'isoformat') else v)
            for k, v in s.items()
        }

    return {
        "match_id": match_id,
        "p1": _norm(p1_stats),
        "p2": _norm(p2_stats),
        "has_data": bool(p1_stats or p2_stats),
    }


@router.get("/admin/intel/queue")
def admin_intel_queue(days_ahead: int = Query(default=2, ge=1, le=7)):
    """List of matches in the next N days that don't yet have intelligence."""
    rows = safe_query(
        """
        SELECT m.id AS match_id, m.event_date, m.event_time,
               t.name AS tournament,
               s.name AS surface,
               p1.name AS p1_name, p2.name AS p2_name,
               mp.predictor_version
        FROM matches m
        LEFT JOIN tournaments t ON t.id = m.tournament_id
        LEFT JOIN surfaces s    ON s.id = t.surface_id
        LEFT JOIN players p1    ON p1.id = m.first_player_id
        LEFT JOIN players p2    ON p2.id = m.second_player_id
        LEFT JOIN model_predictions mp ON mp.match_id = m.id
        WHERE m.event_date BETWEEN CURRENT_DATE AND CURRENT_DATE + (%s || ' days')::interval
          AND m.event_status NOT IN ('Cancelled','Walkover','Postponed','Finished')
          AND m.first_player_id IS NOT NULL
          AND m.second_player_id IS NOT NULL
          AND (m.is_doubles IS NULL OR m.is_doubles = FALSE)
          AND mp.match_id IS NOT NULL
          AND (mp.match_preview IS NULL OR mp.match_preview = '')
        ORDER BY m.event_date, m.event_time NULLS LAST
        LIMIT 100
        """,
        (days_ahead,),
    )
    return {"queue": rows, "count": len(rows)}


from fastapi import Body

@router.post("/admin/intel/store/{match_id}")
def admin_intel_store(match_id: int, payload: dict = Body(...)):
    """Store generated intelligence text for a match."""
    p1_intel        = (payload.get("p1_intel") or "").strip()
    p2_intel        = (payload.get("p2_intel") or "").strip()
    match_preview   = (payload.get("match_preview") or "").strip()
    did_you_know    = (payload.get("did_you_know") or "").strip() or None
    confidence_line = (payload.get("confidence_line") or "").strip() or None
    model           = (payload.get("model") or "claude").strip()

    if not (p1_intel and p2_intel and match_preview):
        raise HTTPException(status_code=400, detail="p1_intel, p2_intel, match_preview are required")

    rows = safe_query(
        """
        UPDATE model_predictions
        SET p1_intel           = %s,
            p2_intel           = %s,
            match_preview      = %s,
            did_you_know       = %s,
            confidence_line    = %s,
            intel_generated_at = NOW(),
            intel_model        = %s
        WHERE match_id = %s
        RETURNING match_id
        """,
        (p1_intel, p2_intel, match_preview, did_you_know, confidence_line, model, match_id),
    )
    if not rows:
        raise HTTPException(status_code=404, detail=f"No prediction found for match {match_id}")
    return {"ok": True, "match_id": match_id}


@router.get("/predictions/today")
def predictions_today(
    days_ahead: int = Query(default=2, ge=0, le=7),
    include_settled: bool = Query(default=True),
):
    """
    Today + tomorrow's matches with their predictions joined in.
    LEFT JOIN style: matches without a prediction still appear (status = 'pending').
    """
    today = date.today()
    cutoff = today + timedelta(days=days_ahead)

    # Use a LEFT JOIN against matches so we show every upcoming match —
    # even those without a model prediction yet (so the user can see what's
    # happening today even if the predictor hasn't run for new fixtures).
    rows = safe_query(
        """
        SELECT
            m.id              AS match_id,
            m.event_date,
            m.event_time,
            m.event_status,
            m.winner          AS match_winner_text,
            t.name            AS tournament_name,
            s.name            AS surface_name,
            m.tournament_round,
            p1.id             AS p1_id,
            p1.name           AS p1_name,
            p1.country_code   AS p1_country,
            p2.id             AS p2_id,
            p2.name           AS p2_name,
            p2.country_code   AS p2_country,
            mp.prob_first_player,
            mp.prob_second_player,
            mp.confidence,
            mp.predicted_winner,
            mp.actual_winner,
            mp.is_correct,
            mp.settled_at,
            mp.predictor_version,
            mp.rtt_gap,
            mp.surface_gap,
            mp.form_gap,
            mp.total_logit,
            mp.predicted_at,
            mp.key_factors
        FROM matches m
        LEFT JOIN tournaments t       ON t.id = m.tournament_id
        LEFT JOIN surfaces s          ON s.id = t.surface_id
        LEFT JOIN players p1          ON p1.id = m.first_player_id
        LEFT JOIN players p2          ON p2.id = m.second_player_id
        LEFT JOIN model_predictions mp ON mp.match_id = m.id
        WHERE m.event_date BETWEEN %s AND %s
          AND m.event_status NOT IN ('Cancelled','Walkover','Postponed')
          AND m.first_player_id IS NOT NULL
          AND m.second_player_id IS NOT NULL
          AND (m.is_doubles IS NULL OR m.is_doubles = FALSE)
        ORDER BY m.event_date, m.event_time NULLS LAST, m.id
        """,
        (today, cutoff),
    )

    items = [_serialise_prediction_row(r) for r in rows]
    if not include_settled:
        items = [i for i in items if i["actual_winner"] is None]

    # A 50/50 isn't a real pick — exclude from accuracy counts.
    def _is_pick(i):
        p1 = (i.get("p1") or {}).get("prob")
        if p1 is None:
            return False
        return abs(p1 - 0.5) > 0.01     # outside the 49–51% band

    settled_count = sum(1 for i in items if i["is_correct"] is not None and _is_pick(i))
    correct_count = sum(1 for i in items if i["is_correct"] and _is_pick(i))
    accuracy_pct  = round(100.0 * correct_count / settled_count, 1) if settled_count else None
    pending_count = sum(1 for i in items if (i.get("p1") or {}).get("prob") is None)
    no_pick_count = sum(1 for i in items if not _is_pick(i) and (i.get("p1") or {}).get("prob") is not None)

    return {
        "date": str(today),
        "date_to": str(cutoff),
        "predictions": items,
        "summary": {
            "total":     len(items),
            "settled":   settled_count,
            "correct":   correct_count,
            "pending":   pending_count,
            "no_pick":   no_pick_count,
            "accuracy_pct": accuracy_pct,
        },
    }


# ─────────────────────────────────────────────────────────────────────────────
# GET /predictions/history
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/predictions/history")
def predictions_history(
    target_date: Optional[str] = Query(default=None, alias="date",
                                       description="Single date — YYYY-MM-DD"),
    days: int = Query(default=14, ge=1, le=90,
                      description="If date omitted, the last N days"),
):
    """Per-day rollup with all predictions for a given date or window."""
    if target_date:
        rows = safe_query(
            """
            SELECT *
            FROM v_predictions_with_results
            WHERE event_date = %s
              AND settled_at IS NOT NULL
            ORDER BY event_time NULLS LAST, match_id
            """,
            (target_date,),
        )
        return {
            "date": target_date,
            "predictions": [_serialise_prediction_row(r) for r in rows],
        }

    today = date.today()
    earliest = today - timedelta(days=days)

    daily = safe_query(
        """
        SELECT event_date, predictions, settled, correct, incorrect, accuracy_pct,
               high_conf, high_conf_correct, high_conf_accuracy_pct
        FROM v_predictions_daily
        WHERE event_date BETWEEN %s AND %s
        ORDER BY event_date DESC
        """,
        (earliest, today),
    )

    return {
        "from": str(earliest),
        "to": str(today),
        "days": [
            {
                "date": str(d["event_date"]),
                "predictions": d["predictions"],
                "settled": d["settled"],
                "correct": d["correct"],
                "incorrect": d["incorrect"],
                "accuracy_pct": float(d["accuracy_pct"]) if d.get("accuracy_pct") is not None else None,
                "high_conf": d["high_conf"],
                "high_conf_correct": d["high_conf_correct"],
                "high_conf_accuracy_pct": float(d["high_conf_accuracy_pct"]) if d.get("high_conf_accuracy_pct") is not None else None,
            }
            for d in daily
        ],
    }


# ─────────────────────────────────────────────────────────────────────────────
# GET /predictions/stats
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/predictions/accuracy")
def predictions_accuracy():
    """
    Detailed live-data accuracy breakdown — by confidence tier, by surface,
    by tournament level, by RTT-gap band. Uses settled predictions only.
    Excludes 50/50 picks (≥0.49 and ≤0.51) since those aren't real predictions.
    """
    base = """
        AND mp.settled_at IS NOT NULL
        AND (mp.prob_first_player < 0.49 OR mp.prob_first_player > 0.51)
    """

    overall = safe_query_one(f"""
        SELECT COUNT(*) AS n,
               SUM(CASE WHEN mp.is_correct THEN 1 ELSE 0 END) AS correct,
               ROUND(100.0 * SUM(CASE WHEN mp.is_correct THEN 1 ELSE 0 END) / NULLIF(COUNT(*), 0), 2) AS pct
        FROM model_predictions mp
        WHERE 1=1 {base}
    """) or {}

    by_conf = safe_query(f"""
        SELECT mp.confidence,
               COUNT(*) AS n,
               SUM(CASE WHEN mp.is_correct THEN 1 ELSE 0 END) AS correct,
               ROUND(100.0 * SUM(CASE WHEN mp.is_correct THEN 1 ELSE 0 END) / NULLIF(COUNT(*), 0), 2) AS pct
        FROM model_predictions mp
        WHERE mp.confidence IS NOT NULL {base}
        GROUP BY mp.confidence
        ORDER BY CASE mp.confidence WHEN 'high' THEN 0 WHEN 'medium' THEN 1 ELSE 2 END
    """)

    by_surface = safe_query(f"""
        SELECT s.name AS surface,
               COUNT(*) AS n,
               SUM(CASE WHEN mp.is_correct THEN 1 ELSE 0 END) AS correct,
               ROUND(100.0 * SUM(CASE WHEN mp.is_correct THEN 1 ELSE 0 END) / NULLIF(COUNT(*), 0), 2) AS pct
        FROM model_predictions mp
        JOIN matches m ON m.id = mp.match_id
        LEFT JOIN tournaments t ON t.id = m.tournament_id
        LEFT JOIN surfaces s ON s.id = t.surface_id
        WHERE s.name IS NOT NULL {base}
        GROUP BY s.name
        ORDER BY n DESC
    """)

    by_rtt_gap = safe_query(f"""
        SELECT
            CASE
                WHEN ABS(mp.rtt_gap) >= 20 THEN '20+ pt gap'
                WHEN ABS(mp.rtt_gap) >= 12 THEN '12-19 pt gap'
                WHEN ABS(mp.rtt_gap) >= 6  THEN '6-11 pt gap'
                ELSE '0-5 pt gap'
            END AS gap_band,
            COUNT(*) AS n,
            SUM(CASE WHEN mp.is_correct THEN 1 ELSE 0 END) AS correct,
            ROUND(100.0 * SUM(CASE WHEN mp.is_correct THEN 1 ELSE 0 END) / NULLIF(COUNT(*), 0), 2) AS pct
        FROM model_predictions mp
        WHERE mp.rtt_gap IS NOT NULL {base}
        GROUP BY gap_band
        ORDER BY MIN(ABS(mp.rtt_gap)) DESC
    """)

    return {
        "overall": overall,
        "by_confidence": by_conf,
        "by_surface": by_surface,
        "by_rtt_gap": by_rtt_gap,
        "note": "50/50 predictions excluded. Live data only (post-deploy).",
    }


@router.get("/predictions/stats")
def predictions_stats():
    """Overall and segmented accuracy."""
    try:
        return _predictions_stats_inner()
    except Exception as e:
        log.error(f"predictions_stats error: {e}")
        return {
            "overall": {"settled": 0, "correct": 0, "accuracy_pct": None},
            "by_confidence": [],
            "by_surface": [],
        }


def _predictions_stats_inner():
    overall = safe_query_one(
        """
        SELECT
            COUNT(*) FILTER (WHERE settled_at IS NOT NULL) AS settled,
            COUNT(*) FILTER (WHERE is_correct)             AS correct,
            ROUND(
                100.0 * COUNT(*) FILTER (WHERE is_correct)
                      / NULLIF(COUNT(*) FILTER (WHERE settled_at IS NOT NULL), 0), 2
            ) AS accuracy_pct
        FROM model_predictions
        """,
    ) or {}

    by_confidence = safe_query(
        """
        SELECT
            confidence,
            COUNT(*) FILTER (WHERE settled_at IS NOT NULL) AS settled,
            COUNT(*) FILTER (WHERE is_correct)             AS correct,
            ROUND(
                100.0 * COUNT(*) FILTER (WHERE is_correct)
                      / NULLIF(COUNT(*) FILTER (WHERE settled_at IS NOT NULL), 0), 2
            ) AS accuracy_pct
        FROM model_predictions
        WHERE confidence IS NOT NULL
        GROUP BY confidence
        ORDER BY CASE confidence WHEN 'high' THEN 0 WHEN 'medium' THEN 1 ELSE 2 END
        """
    )

    by_surface = safe_query(
        """
        SELECT
            s.name AS surface,
            COUNT(*) FILTER (WHERE mp.settled_at IS NOT NULL) AS settled,
            COUNT(*) FILTER (WHERE mp.is_correct)             AS correct,
            ROUND(
                100.0 * COUNT(*) FILTER (WHERE mp.is_correct)
                      / NULLIF(COUNT(*) FILTER (WHERE mp.settled_at IS NOT NULL), 0), 2
            ) AS accuracy_pct
        FROM model_predictions mp
        JOIN matches m ON m.id = mp.match_id
        JOIN tournaments t ON t.id = m.tournament_id
        LEFT JOIN surfaces s ON s.id = t.surface_id
        WHERE s.name IS NOT NULL
        GROUP BY s.name
        ORDER BY settled DESC
        """
    )

    return {
        "overall": {
            "settled": overall.get("settled") or 0,
            "correct": overall.get("correct") or 0,
            "accuracy_pct": float(overall["accuracy_pct"]) if overall.get("accuracy_pct") is not None else None,
        },
        "by_confidence": [
            {
                "confidence": r["confidence"],
                "settled": r["settled"],
                "correct": r["correct"],
                "accuracy_pct": float(r["accuracy_pct"]) if r.get("accuracy_pct") is not None else None,
            }
            for r in by_confidence
        ],
        "by_surface": [
            {
                "surface": r["surface"],
                "settled": r["settled"],
                "correct": r["correct"],
                "accuracy_pct": float(r["accuracy_pct"]) if r.get("accuracy_pct") is not None else None,
            }
            for r in by_surface
        ],
    }


# ─────────────────────────────────────────────────────────────────────────────
# GET /systems
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/systems")
def list_systems():
    rows = safe_query(
        """
        SELECT system_id AS id, code, name, description, icon, accent_colour,
               picks_total, picks_settled, picks_correct, accuracy_pct,
               profit_units, roi_pct
        FROM v_systems_stats
        ORDER BY picks_total DESC NULLS LAST, name
        """
    )
    return {
        "systems": [
            {
                "id": r["id"],
                "code": r["code"],
                "name": r["name"],
                "description": r["description"],
                "icon": r["icon"],
                "accent_colour": r["accent_colour"],
                "picks_total": r["picks_total"] or 0,
                "picks_settled": r["picks_settled"] or 0,
                "picks_correct": r["picks_correct"] or 0,
                "accuracy_pct": float(r["accuracy_pct"]) if r.get("accuracy_pct") is not None else None,
                "profit_units": float(r["profit_units"]) if r.get("profit_units") is not None else None,
                "roi_pct": float(r["roi_pct"]) if r.get("roi_pct") is not None else None,
            }
            for r in rows
        ]
    }


# ─────────────────────────────────────────────────────────────────────────────
# GET /systems/{code}/picks
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/systems/{code}/picks")
def system_picks(
    code: str,
    status: str = Query(default="all", regex="^(all|open|settled)$"),
    limit: int = Query(default=50, ge=1, le=200),
):
    sys_row = safe_query_one("SELECT id, name, description, icon, accent_colour FROM systems WHERE code = %s", (code,))
    if not sys_row:
        raise HTTPException(status_code=404, detail="System not found")

    where = ""
    if status == "open":
        where = "AND sp.settled_at IS NULL"
    elif status == "settled":
        where = "AND sp.settled_at IS NOT NULL"

    rows = safe_query(
        f"""
        SELECT
            sp.id AS pick_id,
            sp.match_id,
            sp.pick,
            sp.confidence,
            sp.reason,
            sp.rationale,
            sp.pick_prob,
            sp.market_odds,
            sp.is_correct,
            sp.profit_loss,
            sp.settled_at,
            sp.picked_at,
            m.event_date, m.event_time, m.event_status,
            t.name AS tournament_name,
            s.name AS surface_name,
            m.tournament_round,
            p1.id AS p1_id, p1.name AS p1_name, p1.country_code AS p1_country,
            p2.id AS p2_id, p2.name AS p2_name, p2.country_code AS p2_country
        FROM system_picks sp
        JOIN matches m       ON m.id = sp.match_id
        LEFT JOIN tournaments t ON t.id = m.tournament_id
        LEFT JOIN surfaces s    ON s.id = t.surface_id
        LEFT JOIN players p1    ON p1.id = m.first_player_id
        LEFT JOIN players p2    ON p2.id = m.second_player_id
        WHERE sp.system_id = %s
        {where}
        ORDER BY m.event_date DESC, m.event_time NULLS LAST
        LIMIT %s
        """,
        (sys_row["id"], limit),
    )

    return {
        "system": sys_row,
        "picks": [
            {
                "pick_id": r["pick_id"],
                "match_id": r["match_id"],
                "event_date": str(r["event_date"]) if r.get("event_date") else None,
                "event_time": str(r["event_time"]) if r.get("event_time") else None,
                "event_status": r.get("event_status"),
                "tournament": r.get("tournament_name"),
                "surface": r.get("surface_name"),
                "round": r.get("tournament_round"),
                "pick": r["pick"],
                "confidence": r.get("confidence"),
                "reason": r.get("reason"),
                "rationale": r.get("rationale"),
                "pick_prob": float(r["pick_prob"]) if r.get("pick_prob") is not None else None,
                "market_odds": float(r["market_odds"]) if r.get("market_odds") is not None else None,
                "is_correct": r.get("is_correct"),
                "profit_loss": float(r["profit_loss"]) if r.get("profit_loss") is not None else None,
                "settled_at": str(r["settled_at"]) if r.get("settled_at") else None,
                "picked_at": str(r["picked_at"]) if r.get("picked_at") else None,
                "p1": {"id": r["p1_id"], "name": r["p1_name"], "country_code": r["p1_country"]},
                "p2": {"id": r["p2_id"], "name": r["p2_name"], "country_code": r["p2_country"]},
            }
            for r in rows
        ],
    }


# ─────────────────────────────────────────────────────────────────────────────
# GET /systems/{code}/stats
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/systems/{code}/stats")
def system_stats(code: str):
    row = safe_query_one(
        """
        SELECT system_id AS id, code, name, description, icon, accent_colour,
               picks_total, picks_settled, picks_correct, accuracy_pct,
               profit_units, roi_pct
        FROM v_systems_stats
        WHERE code = %s
        """,
        (code,),
    )
    if not row:
        raise HTTPException(status_code=404, detail="System not found")
    # Trend: last 30 days
    trend = safe_query(
        """
        SELECT date_trunc('day', m.event_date)::date AS day,
               COUNT(*) FILTER (WHERE sp.settled_at IS NOT NULL) AS settled,
               COUNT(*) FILTER (WHERE sp.is_correct)             AS correct,
               SUM(sp.profit_loss) AS profit
        FROM system_picks sp
        JOIN systems sy ON sy.id = sp.system_id
        JOIN matches m  ON m.id = sp.match_id
        WHERE sy.code = %s
          AND m.event_date >= CURRENT_DATE - INTERVAL '60 days'
        GROUP BY day
        ORDER BY day
        """,
        (code,),
    )
    return {
        "system": {
            **{k: row[k] for k in ("id", "code", "name", "description", "icon", "accent_colour")},
            "picks_total": row["picks_total"] or 0,
            "picks_settled": row["picks_settled"] or 0,
            "picks_correct": row["picks_correct"] or 0,
            "accuracy_pct": float(row["accuracy_pct"]) if row.get("accuracy_pct") is not None else None,
            "profit_units": float(row["profit_units"]) if row.get("profit_units") is not None else None,
            "roi_pct": float(row["roi_pct"]) if row.get("roi_pct") is not None else None,
        },
        "trend": [
            {
                "day": str(t["day"]),
                "settled": t["settled"] or 0,
                "correct": t["correct"] or 0,
                "profit": float(t["profit"]) if t.get("profit") is not None else None,
            }
            for t in trend
        ],
    }


# ─────────────────────────────────────────────────────────────────────────────

# GET /predictions/results — comprehensive results dashboard
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/predictions/results")
def predictions_results():
    try:
        return _predictions_results_inner()
    except Exception as e:
        log.error(f"predictions_results error: {e}")
        return {
            "model_cutover": None,
            "today": _empty_stat_block(),
            "all_time": _empty_stat_block(),
            "last_30d": _empty_stat_block(),
            "last_7d": _empty_stat_block(),
            "streak": None,
            "best_7d": None,
            "worst_7d": None,
            "weekly_bars": [],
            "recent_picks": [],
            "by_surface": {
                "Clay":   _breakdown_block(),
                "Hard":   _breakdown_block(),
                "Grass":  _breakdown_block(),
                "Indoor": _breakdown_block(),
            },
            "by_tour": {
                "ATP":        _breakdown_block(),
                "WTA":        _breakdown_block(),
                "Challenger": _breakdown_block(),
                "ITF":        _breakdown_block(),
            },
            "edge_buckets": [],
            "calibration": [],
            "pnl_trend": [],
            "error": str(e),
        }


def _empty_stat_block():
    """Single time-window stat block — field names match the frontend pickStats() helper."""
    return {
        "picks": 0,
        "wins": 0,
        "win_rate_pct": None,
        "pnl": None,
        "roi_pct": None,
        # bookmaker-odds variant (shown when user toggles to 'book' mode)
        "priced_picks": 0,
        "wins_priced": 0,
        "pnl_book": None,
        "roi_book_pct": None,
    }


def _breakdown_block():
    """BreakdownCard expects {all_time, last_30d, last_7d} — each a stat block."""
    return {
        "all_time": _empty_stat_block(),
        "last_30d": _empty_stat_block(),
        "last_7d":  _empty_stat_block(),
    }


def _stat_block_from_row(r) -> dict:
    if not r:
        return _empty_stat_block()
    settled = int(r.get("settled") or 0)
    correct = int(r.get("correct") or 0)
    win_rate = float(r["win_rate_pct"]) if r.get("win_rate_pct") is not None else None
    pnl  = float(r["pnl"])     if r.get("pnl")     is not None else None
    roi  = float(r["roi_pct"]) if r.get("roi_pct") is not None else None
    # bookmaker-priced variants (NULL until we have odds data)
    priced     = int(r.get("priced_picks") or 0)
    wins_priced= int(r.get("wins_priced") or 0)
    pnl_book   = float(r["pnl_book"])     if r.get("pnl_book")     is not None else None
    roi_book   = float(r["roi_book_pct"]) if r.get("roi_book_pct") is not None else None
    return {
        "picks": settled,
        "wins": correct,
        "win_rate_pct": win_rate,
        "pnl": pnl,
        "roi_pct": roi,
        "priced_picks": priced,
        "wins_priced": wins_priced,
        "pnl_book": pnl_book,
        "roi_book_pct": roi_book,
    }


# The core aggregate SQL — parameterised by an optional extra WHERE clause.
_BLOCK_SQL = """
    SELECT
        COUNT(*) FILTER (WHERE NOT (mp.prob_first_player BETWEEN 0.49 AND 0.51))
            AS settled,
        COUNT(*) FILTER (WHERE mp.is_correct = TRUE
                           AND NOT (mp.prob_first_player BETWEEN 0.49 AND 0.51))
            AS correct,
        ROUND(
            100.0
            * COUNT(*) FILTER (WHERE mp.is_correct = TRUE
                                 AND NOT (mp.prob_first_player BETWEEN 0.49 AND 0.51))
            / NULLIF(COUNT(*) FILTER (WHERE NOT (mp.prob_first_player BETWEEN 0.49 AND 0.51)), 0)
        , 1) AS win_rate_pct,
        ROUND(SUM(
            CASE
              WHEN mp.is_correct = TRUE
               AND NOT (mp.prob_first_player BETWEEN 0.49 AND 0.51)
               THEN (1.0 / GREATEST(mp.prob_first_player, mp.prob_second_player, 0.01)) - 1
              WHEN mp.is_correct = FALSE
               AND NOT (mp.prob_first_player BETWEEN 0.49 AND 0.51)
               THEN -1.0
              ELSE 0
            END), 2) AS pnl,
        ROUND(
            100.0
            * SUM(CASE
                WHEN mp.is_correct = TRUE
                 AND NOT (mp.prob_first_player BETWEEN 0.49 AND 0.51)
                 THEN (1.0 / GREATEST(mp.prob_first_player, mp.prob_second_player, 0.01)) - 1
                WHEN mp.is_correct = FALSE
                 AND NOT (mp.prob_first_player BETWEEN 0.49 AND 0.51)
                 THEN -1.0
                ELSE 0
              END)
            / NULLIF(COUNT(*) FILTER (
                WHERE NOT (mp.prob_first_player BETWEEN 0.49 AND 0.51)), 0)
        , 1) AS roi_pct,
        0 AS priced_picks,
        0 AS wins_priced,
        NULL::numeric AS pnl_book,
        NULL::numeric AS roi_book_pct
    FROM model_predictions mp
    JOIN matches m ON m.id = mp.match_id
    {joins}
    WHERE mp.is_correct IS NOT NULL
      {extra_where}
"""


def _fetch_block(extra_where="", params=None, joins=""):
    sql = _BLOCK_SQL.format(joins=joins, extra_where=extra_where)
    row = safe_query_one(sql, params)
    return _stat_block_from_row(row)


def _fetch_breakdown(extra_where="", params=None, joins=""):
    """Return {all_time, last_30d, last_7d} for a given filter."""
    return {
        "all_time": _fetch_block(extra_where, params, joins),
        "last_30d": _fetch_block(
            extra_where + " AND m.event_date >= CURRENT_DATE - INTERVAL '30 days'",
            params, joins),
        "last_7d":  _fetch_block(
            extra_where + " AND m.event_date >= CURRENT_DATE - INTERVAL '7 days'",
            params, joins),
    }


def _fmt_pick(r) -> dict:
    """Convert a model_predictions row to the shape expected by the frontend."""
    p1p = float(r["prob_first_player"])  if r.get("prob_first_player")  is not None else 0.5
    p2p = float(r["prob_second_player"]) if r.get("prob_second_player") is not None else 0.5
    p1_name = r.get("first_player_name") or ""
    p2_name = r.get("second_player_name") or ""
    pred = r.get("predicted_winner") or ""
    # pick = the player we predicted to win
    if pred == p1_name or (pred and pred.lower() == "first_player"):
        pick_name = p1_name
        opp_name  = p2_name
        pick_prob = p1p
    else:
        pick_name = p2_name
        opp_name  = p1_name
        pick_prob = p2p
    return {
        "match_id":   r["match_id"],
        "pick_name":  pick_name,
        "opp_name":   opp_name,
        "pick_prob":  round(pick_prob, 4),
        "won":        bool(r["is_correct"]) if r.get("is_correct") is not None else None,
        "is_correct": r.get("is_correct"),
        "confidence": r.get("confidence"),
        "score":      r.get("final_result"),
        "event_date": str(r["event_date"])  if r.get("event_date")  else None,
        "tournament": r.get("tournament_name"),
        "surface":    r.get("surface_name"),
        "settled_at": str(r["settled_at"])  if r.get("settled_at")  else None,
    }


_PICK_COLS = """
    mp.match_id,
    mp.predicted_winner, mp.is_correct,
    mp.prob_first_player, mp.prob_second_player,
    mp.confidence, mp.settled_at,
    p1.name AS first_player_name,
    p2.name AS second_player_name,
    m.event_date, m.final_result,
    t.name  AS tournament_name,
    s.name  AS surface_name
"""

_PICK_JOINS = """
    JOIN players p1 ON p1.id = m.first_player_id
    JOIN players p2 ON p2.id = m.second_player_id
    LEFT JOIN tournaments t ON t.id = m.tournament_id
    LEFT JOIN surfaces   s ON s.id  = t.surface_id
"""


def _predictions_results_inner():
    # ── Model cutover date ────────────────────────────────────────────────────
    cutover_row = safe_query_one(
        """SELECT MIN(m.event_date) AS cutover
        FROM model_predictions mp
        JOIN matches m ON m.id = mp.match_id
        WHERE mp.is_correct IS NOT NULL"""
    )
    model_cutover = str(cutover_row["cutover"]) if cutover_row and cutover_row.get("cutover") else None

    # ── Top-level time windows ────────────────────────────────────────────────
    all_time   = _fetch_block()
    last_30d   = _fetch_block("AND m.event_date >= CURRENT_DATE - INTERVAL '30 days'")
    last_7d    = _fetch_block("AND m.event_date >= CURRENT_DATE - INTERVAL '7 days'")
    today_block = _fetch_block("AND m.event_date = CURRENT_DATE")

    # ── By surface ────────────────────────────────────────────────────────────
    surf_joins = """
        JOIN tournaments t2s ON t2s.id = m.tournament_id
        JOIN surfaces    s2s ON s2s.id = t2s.surface_id
    """
    by_surface = {
        "Clay":   _fetch_breakdown("AND s2s.name ILIKE %s", ("%Clay%",),   joins=surf_joins),
        "Hard":   _fetch_breakdown("AND s2s.name ILIKE %s", ("%Hard%",),   joins=surf_joins),
        "Grass":  _fetch_breakdown("AND s2s.name ILIKE %s", ("%Grass%",),  joins=surf_joins),
        "Indoor": _fetch_breakdown("AND s2s.name ILIKE %s", ("%Indoor%",), joins=surf_joins),
    }

    # ── By tour ───────────────────────────────────────────────────────────────
    tour_joins = """
        JOIN tournaments t2t ON t2t.id  = m.tournament_id
        JOIN event_types et2t ON et2t.id = t2t.event_type_id
    """
    by_tour = {
        "ATP":        _fetch_breakdown("AND et2t.name ILIKE %s", ("%ATP%",),        joins=tour_joins),
        "WTA":        _fetch_breakdown("AND et2t.name ILIKE %s", ("%WTA%",),        joins=tour_joins),
        "Challenger": _fetch_breakdown("AND et2t.name ILIKE %s", ("%Challenger%",), joins=tour_joins),
        "ITF":        _fetch_breakdown("AND et2t.name ILIKE %s", ("%ITF%",),        joins=tour_joins),
    }

    # ── Recent picks (last 20 settled, individual rows) ───────────────────────
    recent_rows = safe_query(f"""
        SELECT {_PICK_COLS}
        FROM model_predictions mp
        JOIN matches m ON m.id = mp.match_id
        {_PICK_JOINS}
        WHERE mp.is_correct IS NOT NULL
          AND NOT (mp.prob_first_player BETWEEN 0.49 AND 0.51)
        ORDER BY m.event_date DESC, mp.match_id DESC
        LIMIT 20
    """)
    recent_picks = [_fmt_pick(r) for r in recent_rows]

    # ── Weekly bars = last 7 days individual picks (bar per pick) ────────────
    weekly_rows = safe_query(f"""
        SELECT {_PICK_COLS}
        FROM model_predictions mp
        JOIN matches m ON m.id = mp.match_id
        {_PICK_JOINS}
        WHERE mp.is_correct IS NOT NULL
          AND m.event_date >= CURRENT_DATE - INTERVAL '7 days'
          AND NOT (mp.prob_first_player BETWEEN 0.49 AND 0.51)
        ORDER BY m.event_date DESC, mp.match_id DESC
    """)
    weekly_bars = [_fmt_pick(r) for r in weekly_rows]

    # ── Current streak ────────────────────────────────────────────────────────
    streak_rows = safe_query("""
        SELECT mp.is_correct FROM model_predictions mp
        JOIN matches m ON m.id = mp.match_id
        WHERE mp.is_correct IS NOT NULL
          AND NOT (mp.prob_first_player BETWEEN 0.49 AND 0.51)
        ORDER BY m.event_date DESC, mp.match_id DESC
        LIMIT 20
    """)
    streak = None
    if streak_rows:
        streak_type = "W" if streak_rows[0]["is_correct"] else "L"
        streak_len = 0
        for r in streak_rows:
            if (r["is_correct"] and streak_type == "W") or (not r["is_correct"] and streak_type == "L"):
                streak_len += 1
            else:
                break
        if streak_len >= 2:
            streak = {"type": streak_type, "len": streak_len}

    # ── Calibration ───────────────────────────────────────────────────────────
    calib_rows = safe_query("""
        SELECT
            ROUND(GREATEST(mp.prob_first_player, mp.prob_second_player) * 10) / 10 AS prob_bucket,
            COUNT(*) AS n,
            ROUND(100.0 * SUM(CASE WHEN mp.is_correct THEN 1 ELSE 0 END) / COUNT(*), 1) AS actual_pct
        FROM model_predictions mp
        WHERE mp.is_correct IS NOT NULL
          AND mp.is_correct IS NOT NULL
          AND NOT (mp.prob_first_player BETWEEN 0.49 AND 0.51)
        GROUP BY prob_bucket
        HAVING COUNT(*) >= 5
        ORDER BY prob_bucket
    """)
    calibration = [
        {
            "prob_bucket": float(r["prob_bucket"]) if r.get("prob_bucket") is not None else None,
            "n": int(r["n"]),
            "actual_pct": float(r["actual_pct"]) if r.get("actual_pct") is not None else None,
        }
        for r in calib_rows
    ]

    # ── P&L trend (cumulative, last 60 days) ──────────────────────────────────
    pnl_rows = safe_query("""
        SELECT
            DATE(m.event_date) AS day,
            SUM(CASE
                  WHEN mp.is_correct = TRUE
                   AND NOT (mp.prob_first_player BETWEEN 0.49 AND 0.51)
                   THEN (1.0 / GREATEST(mp.prob_first_player, mp.prob_second_player, 0.01)) - 1
                  WHEN mp.is_correct = FALSE
                   AND NOT (mp.prob_first_player BETWEEN 0.49 AND 0.51)
                   THEN -1.0
                  ELSE 0
                END) AS daily_pnl
        FROM model_predictions mp
        JOIN matches m ON m.id = mp.match_id
        WHERE m.event_date >= CURRENT_DATE - INTERVAL '60 days'
          AND mp.is_correct IS NOT NULL
        GROUP BY day
        ORDER BY day
    """)
    cumulative = 0.0
    pnl_trend = []
    for r in pnl_rows:
        cumulative += float(r["daily_pnl"] or 0)
        pnl_trend.append({
            "day": str(r["day"]),
            "daily_pnl": round(float(r["daily_pnl"] or 0), 3),
            "cumulative_pnl": round(cumulative, 3),
        })

    return {
        "model_cutover": model_cutover,
        "today":    today_block,
        "all_time": all_time,
        "last_30d": last_30d,
        "last_7d":  last_7d,
        "streak":   streak,
        "best_7d":  None,
        "worst_7d": None,
        "weekly_bars":   weekly_bars,
        "recent_picks":  recent_picks,
        "by_surface":    by_surface,
        "by_tour":       by_tour,
        "edge_buckets":  [],
        "calibration":   calibration,
        "pnl_trend":     pnl_trend,
    }
