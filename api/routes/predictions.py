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
            m.event_date, m.event_time, m.tournament_round, m.event_status,
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

    # For finished matches, suppress stale pre-match intel. The text was
    # written when the match was upcoming; reading it after the fact is
    # both confusing (it claims "the model picks X") and embarrassing
    # if the prose got the pick wrong against the actual winner.
    finished = (row.get("event_status") or "").lower() == "finished"
    has_intel = bool(
        row.get("p1_intel") and row.get("p2_intel") and row.get("match_preview")
    ) and not finished

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

    # Tighten has_data: a row exists in player_point_stats but with every
    # numeric column NULL/0 should NOT advertise itself as having data —
    # the frontend will pass the guard then render '—' everywhere. Require
    # at least one non-null serve metric on either side.
    def _has_meaningful_data(s):
        if not s:
            return False
        # Look for the canonical "we measured something" fields
        return any(s.get(k) is not None for k in
                   ("service_hold_pct", "bp_save_pct", "break_pct",
                    "bp_conversion_pct", "matches_analyzed"))

    return {
        "match_id": match_id,
        "p1": _norm(p1_stats),
        "p2": _norm(p2_stats),
        "has_data": bool(_has_meaningful_data(p1_stats) or _has_meaningful_data(p2_stats)),
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
    """Overall and segmented accuracy. Filters:
    - New-model only: event_date >= 2026-05-10
    - 50/50 picks excluded (prob between 0.499 and 0.501)
    - Doubles excluded
    """
    MODEL_CUTOVER = "2026-05-10"
    BASE_FILTER = """
        JOIN matches m ON m.id = mp.match_id
        WHERE m.event_date >= %(cutover)s::date
          AND (mp.prob_first_player < 0.499 OR mp.prob_first_player > 0.501)
          AND (m.is_doubles IS NULL OR m.is_doubles = FALSE)
          AND m.event_status NOT IN ('Cancelled','Walkover','Postponed','Retired')
    """

    overall = safe_query_one(
        f"""
        SELECT
            COUNT(*) FILTER (WHERE mp.settled_at IS NOT NULL) AS settled,
            COUNT(*) FILTER (WHERE mp.is_correct)             AS correct,
            ROUND(
                100.0 * COUNT(*) FILTER (WHERE mp.is_correct)
                      / NULLIF(COUNT(*) FILTER (WHERE mp.settled_at IS NOT NULL), 0), 2
            ) AS accuracy_pct
        FROM model_predictions mp
        {BASE_FILTER}
        """,
        {"cutover": MODEL_CUTOVER},
    ) or {}

    by_confidence = safe_query(
        f"""
        SELECT
            mp.confidence,
            COUNT(*) FILTER (WHERE mp.settled_at IS NOT NULL) AS settled,
            COUNT(*) FILTER (WHERE mp.is_correct)             AS correct,
            ROUND(
                100.0 * COUNT(*) FILTER (WHERE mp.is_correct)
                      / NULLIF(COUNT(*) FILTER (WHERE mp.settled_at IS NOT NULL), 0), 2
            ) AS accuracy_pct
        FROM model_predictions mp
        {BASE_FILTER}
          AND mp.confidence IS NOT NULL
        GROUP BY mp.confidence
        ORDER BY CASE mp.confidence WHEN 'high' THEN 0 WHEN 'medium' THEN 1 ELSE 2 END
        """,
        {"cutover": MODEL_CUTOVER},
    )

    by_surface = safe_query(
        f"""
        SELECT
            s.name AS surface,
            COUNT(*) FILTER (WHERE mp.settled_at IS NOT NULL) AS settled,
            COUNT(*) FILTER (WHERE mp.is_correct)             AS correct,
            ROUND(
                100.0 * COUNT(*) FILTER (WHERE mp.is_correct)
                      / NULLIF(COUNT(*) FILTER (WHERE mp.settled_at IS NOT NULL), 0), 2
            ) AS accuracy_pct
        FROM model_predictions mp
        {BASE_FILTER}
        JOIN tournaments t ON t.id = m.tournament_id
        LEFT JOIN surfaces s ON s.id = t.surface_id
          AND s.name IS NOT NULL
        GROUP BY s.name
        ORDER BY settled DESC
        """,
        {"cutover": MODEL_CUTOVER},
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
# GET /predictions/results — full results dashboard data
#   Powers the redesigned /predictions page (à la ratethat.dog results).
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/predictions/results")
def predictions_results():
    # Wrap the entire body so the actual exception comes back as JSON
    # instead of a generic 500 (Railway swallows tracebacks otherwise).
    import traceback
    try:
        return _predictions_results_impl()
    except Exception as e:
        log.error(f"predictions_results failed: {e}")
        log.error(traceback.format_exc())
        return {
            "error": str(e),
            "type":  type(e).__name__,
            "traceback": traceback.format_exc().splitlines()[-15:],
        }


def _predictions_results_impl():
    """
    One-shot payload for the results dashboard:
      - top stats (all-time / last 30d / last 7d) with picks, wins, win rate,
        P&L using RTT-implied odds (1/prob_pick), ROI%
      - streak indicator
      - best & worst pick of last 7 days
      - last 15 settled picks (for the scrollable table)
      - weekly bars (last 7 days, chronological)
      - surface breakdown (Clay / Hard / Grass / Indoor)
      - tour breakdown (ATP / WTA / Challenger / ITF)
      - edge buckets (model prob - market implied prob, where bookmaker odds exist)
      - calibration buckets (predicted % vs actual win %)
      - cumulative P&L trend (for the overlay chart)

    Conventions:
      - £1 flat stake per pick
      - "P&L using RTT odds" = profit at the model's own implied fair odds (1/prob)
      - 50/50 picks (49–51%) excluded — those aren't real predictions
      - Doubles excluded
      - **Predictions BEFORE 2026-05-10 are excluded** — that's when the new
        Elo+logistic LivePredictor replaced the additive-logit RttPredictor.
        Old-model results would mislead the dashboard.
    """
    # New-model cutover: filter on predicted_at >= this date.
    MODEL_CUTOVER = "2026-05-10"
    # Pre-aggregate bookmaker odds in a CTE (one pass, hash-joined) instead
    # of a correlated subquery (one round-trip per row). With ~1k+ settled
    # predictions the correlated form runs ~18s; the CTE version is sub-second.
    # Pre-aggregate bookmaker odds in a CTE (one pass, hash-joined) instead
    # of a correlated subquery (one round-trip per row). Restrict the result
    # set to the last 365 days — we don't need a 5-year cumulative trend on
    # the dashboard and including very old settled predictions on a small
    # Railway container makes the Python aggregation pass over hundreds of
    # rows pointlessly slow.
    rows = safe_query(
        """
        WITH pick_odds AS (
            SELECT match_id, player_ref, MAX(decimal_odds) AS odds
            FROM bookmaker_odds
            GROUP BY match_id, player_ref
        )
        SELECT
            mp.match_id,
            m.event_date,
            mp.prob_first_player,
            mp.prob_second_player,
            mp.predicted_winner,
            mp.actual_winner,
            mp.is_correct,
            mp.confidence,
            t.name AS tournament,
            s.name AS surface,
            et.tour_category,
            p1.id   AS p1_id,
            p1.name AS p1_name,
            p1.country_code AS p1_country,
            p2.id   AS p2_id,
            p2.name AS p2_name,
            p2.country_code AS p2_country,
            m.final_result AS score,
            po.odds AS pick_decimal_odds
        FROM model_predictions mp
        JOIN matches m ON m.id = mp.match_id
        LEFT JOIN tournaments t ON t.id = m.tournament_id
        LEFT JOIN surfaces s ON s.id = t.surface_id
        LEFT JOIN event_types et ON et.id = m.event_type_id
        LEFT JOIN players p1 ON p1.id = m.first_player_id
        LEFT JOIN players p2 ON p2.id = m.second_player_id
        LEFT JOIN pick_odds po
            ON po.match_id   = mp.match_id
           AND po.player_ref = mp.predicted_winner
        WHERE mp.settled_at IS NOT NULL
          AND mp.predicted_winner IS NOT NULL
          AND mp.actual_winner   IS NOT NULL
          AND mp.is_correct      IS NOT NULL
          -- Same 50/50 threshold as /predictions/today: exclude only the
          -- narrow 0.499..0.501 band so the two endpoints agree. The
          -- previous 0.49/0.51 band silently dropped real low-conviction
          -- picks and produced a different win rate.
          -- NB: do not write a literal pct sign here, psycopg2 treats it
          -- as a parameter placeholder even inside SQL comments.
          AND (mp.prob_first_player < 0.499 OR mp.prob_first_player > 0.501)
          AND (m.is_doubles IS NULL OR m.is_doubles = FALSE)
          -- Match the today endpoint's exclusions: ignore non-played statuses
          -- (cancelled/walkover/postponed/retired) so the two pages count
          -- the same set of settled matches.
          AND m.event_status NOT IN ('Cancelled','Walkover','Postponed','Retired')
          -- New-model cutover: filter on the EVENT date, not predicted_at.
          -- Some of today's matches were first predicted yesterday and
          -- weren't re-predicted before they started; filtering on
          -- predicted_at would drop them. The cutover semantically means
          -- "matches played on or after this date use the new model."
          AND m.event_date >= %s::date
        ORDER BY m.event_date DESC, mp.match_id DESC
        """,
        (MODEL_CUTOVER,),
    )

    today = date.today()
    d7  = today - timedelta(days=7)
    d30 = today - timedelta(days=30)

    def _surface_bucket(name: Optional[str]) -> str:
        s = (name or "").lower()
        if "indoor" in s or "carpet" in s: return "Indoor"
        if "clay"  in s: return "Clay"
        if "grass" in s: return "Grass"
        if "hard"  in s: return "Hard"
        return "Other"

    def _tour_bucket(cat: Optional[str]) -> str:
        c = (cat or "").upper()
        if "CHALLENGER" in c: return "Challenger"
        if "ITF"        in c: return "ITF"
        if "WTA"        in c: return "WTA"
        if "ATP"        in c: return "ATP"
        return "Other"

    items: list[dict] = []
    for r in rows:
        p1p = float(r["prob_first_player"])  if r.get("prob_first_player")  is not None else None
        p2p = float(r["prob_second_player"]) if r.get("prob_second_player") is not None else None
        if p1p is None or p2p is None:
            continue
        # Derive pick_side from probabilities directly, NOT from the
        # predicted_winner column. predicted_winner can be left stale by a
        # predictor-version swap (the row keeps an old pick while the
        # probabilities flip). Reading the probabilities is the source of
        # truth and is always consistent with what the model thinks now.
        pick_side = "first_player" if p1p >= p2p else "second_player"
        pick_prob = p1p if pick_side == "first_player" else p2p
        if pick_prob <= 0:
            continue
        pick_name = r["p1_name"] if pick_side == "first_player" else r["p2_name"]
        opp_name  = r["p2_name"] if pick_side == "first_player" else r["p1_name"]
        # Re-derive correctness too — actual_winner is fine, but is_correct
        # was computed against the (possibly stale) predicted_winner. Use
        # actual_winner == derived pick_side as the source of truth.
        actual = r.get("actual_winner")
        won = (actual is not None) and (actual == pick_side)

        # P&L at the model's own implied fair odds (1/prob_pick), £1 stake
        rtt_odds = 1.0 / pick_prob
        pl_rtt = round(rtt_odds - 1.0, 4) if won else -1.0

        # P&L at best bookmaker odds (only when we have a price)
        book_odds = float(r["pick_decimal_odds"]) if r.get("pick_decimal_odds") else None
        if book_odds and book_odds > 1.0:
            pl_book = round(book_odds - 1.0, 4) if won else -1.0
        else:
            pl_book = None

        # Edge in % points: model prob - market implied prob
        edge_pp = None
        if book_odds and book_odds > 1.0:
            mkt_implied = 1.0 / book_odds
            edge_pp = (pick_prob - mkt_implied) * 100.0

        items.append({
            "match_id":   r["match_id"],
            "event_date": str(r["event_date"]),
            "tournament": r.get("tournament"),
            "surface":    r.get("surface"),
            "surface_bucket": _surface_bucket(r.get("surface")),
            "tour_bucket":    _tour_bucket(r.get("tour_category")),
            "p1": {"id": r.get("p1_id"), "name": r.get("p1_name"), "country_code": r.get("p1_country")},
            "p2": {"id": r.get("p2_id"), "name": r.get("p2_name"), "country_code": r.get("p2_country")},
            "pick_side":  pick_side,
            "pick_name":  pick_name,
            "opp_name":   opp_name,
            "pick_prob":  pick_prob,
            "p1_prob":    p1p,
            "p2_prob":    p2p,
            "won":        won,
            "score":      r.get("score"),
            "rtt_odds":   round(rtt_odds, 3),
            "book_odds":  round(book_odds, 3) if book_odds else None,
            "edge_pp":    round(edge_pp, 1) if edge_pp is not None else None,
            "pl_rtt":     pl_rtt,
            "pl_book":    pl_book,
            "confidence": r.get("confidence"),
        })

    def _agg(picks: list[dict]) -> dict:
        n = len(picks)
        wins = sum(1 for p in picks if p["won"])

        # P&L using RTT-implied fair odds — every pick has this.
        pnl_rtt = sum(p["pl_rtt"] for p in picks)

        # P&L using best bookmaker odds — only the subset where we have a
        # market price. Denominator for ROI is the priced subset, NOT the
        # total bucket, otherwise ROI is artificially diluted.
        priced  = [p for p in picks if p["pl_book"] is not None]
        n_book  = len(priced)
        pnl_book = sum(p["pl_book"] for p in priced)
        wins_book = sum(1 for p in priced if p["won"])

        return {
            "picks":            n,
            "wins":             wins,
            "win_rate_pct":     round(100.0 * wins / n, 1) if n else None,
            # Default fields use RTT odds for backwards compatibility
            "pnl":              round(pnl_rtt, 2) if n else None,
            "roi_pct":          round(100.0 * pnl_rtt / n, 1) if n else None,
            # Per-mode breakdown for the frontend toggle
            "pnl_rtt":          round(pnl_rtt, 2) if n else None,
            "roi_rtt_pct":      round(100.0 * pnl_rtt / n, 1) if n else None,
            "priced_picks":     n_book,
            "wins_priced":      wins_book,
            "pnl_book":         round(pnl_book, 2) if n_book else None,
            "roi_book_pct":     round(100.0 * pnl_book / n_book, 1) if n_book else None,
        }

    items_30  = [i for i in items if date.fromisoformat(i["event_date"]) >= d30]
    items_7   = [i for i in items if date.fromisoformat(i["event_date"]) >= d7]
    items_tdy = [i for i in items if date.fromisoformat(i["event_date"]) == today]

    by_surface = {}
    for surf in ("Clay", "Hard", "Grass", "Indoor"):
        s_all = [i for i in items    if i["surface_bucket"] == surf]
        s_30  = [i for i in items_30 if i["surface_bucket"] == surf]
        s_7   = [i for i in items_7  if i["surface_bucket"] == surf]
        by_surface[surf] = {"all_time": _agg(s_all), "last_30d": _agg(s_30), "last_7d": _agg(s_7)}

    by_tour = {}
    for tour in ("ATP", "WTA", "Challenger", "ITF"):
        t_all = [i for i in items    if i["tour_bucket"] == tour]
        t_30  = [i for i in items_30 if i["tour_bucket"] == tour]
        t_7   = [i for i in items_7  if i["tour_bucket"] == tour]
        by_tour[tour] = {"all_time": _agg(t_all), "last_30d": _agg(t_30), "last_7d": _agg(t_7)}

    # Edge buckets — only items with bookmaker odds.
    # ROI must divide P&L by the count of picks WITH odds (the staked subset),
    # not the bucket headcount, otherwise ROI is understated.
    edge_items = [i for i in items if i["edge_pp"] is not None]
    bucket_defs = [
        (-999, 0,   "<0%"),    # model less confident than market
        (0,    3,   "0–3%"),
        (3,    6,   "3–6%"),
        (6,    10,  "6–10%"),
        (10,   999, "10%+"),
    ]
    edge_buckets = []
    for lo, hi, label in bucket_defs:
        b = [i for i in edge_items if lo <= i["edge_pp"] < hi]
        n = len(b)
        wins = sum(1 for i in b if i["won"])
        priced = [i for i in b if i["pl_book"] is not None]
        n_priced = len(priced)
        pnl_book = sum(i["pl_book"] for i in priced)
        edge_buckets.append({
            "label":         label,
            "picks":         n,
            "wins":          wins,
            "win_rate_pct":  round(100.0 * wins / n, 1) if n else None,
            "pnl_book":      round(pnl_book, 2)         if n_priced else None,
            "roi_pct":       round(100.0 * pnl_book / n_priced, 1) if n_priced else None,
        })

    # Calibration: bucket by predicted probability for the pick
    cal_defs = [(0.50, 0.60, "50–60%"), (0.60, 0.70, "60–70%"),
                (0.70, 0.80, "70–80%"), (0.80, 1.01, "80%+")]
    calibration = []
    for lo, hi, label in cal_defs:
        b = [i for i in items if lo <= i["pick_prob"] < hi]
        n = len(b)
        wins = sum(1 for i in b if i["won"])
        avg_pred = (sum(i["pick_prob"] for i in b) / n) if n else None
        calibration.append({
            "label":         label,
            "picks":         n,
            "predicted_pct": round(100.0 * avg_pred, 1) if avg_pred is not None else None,
            "actual_pct":    round(100.0 * wins / n, 1)  if n else None,
        })

    # Streak — items are already DESC by date
    streak_type, streak_len = None, 0
    for i in items:
        kind = "W" if i["won"] else "L"
        if streak_type is None:
            streak_type, streak_len = kind, 1
        elif kind == streak_type:
            streak_len += 1
        else:
            break

    # Best & worst pick of last 7 days, by realised P&L using RTT odds
    best_7  = max(items_7, key=lambda i: i["pl_rtt"], default=None)
    worst_7 = min(items_7, key=lambda i: i["pl_rtt"], default=None)

    # Last 15 settled picks (already DESC)
    recent_picks = items[:15]

    # Weekly bars — last 7 days, chronological
    weekly_bars = sorted(items_7, key=lambda i: (i["event_date"], i["match_id"]))

    # Cumulative P&L trend for the overlay chart
    pnl_trend = []
    cum_pl = 0.0
    cum_n  = 0
    for i in sorted(items, key=lambda x: (x["event_date"], x["match_id"])):
        cum_pl += i["pl_rtt"]
        cum_n  += 1
        pnl_trend.append({
            "date":              i["event_date"],
            "cumulative_pnl":    round(cum_pl, 2),
            "cumulative_picks":  cum_n,
            "roi_pct":           round(100.0 * cum_pl / cum_n, 1),
        })
    # Collapse to per-day endpoints (one point per date) — keeps payload small
    by_day = {}
    for p in pnl_trend:
        by_day[p["date"]] = p
    pnl_trend = list(by_day.values())

    return {
        "model_cutover": MODEL_CUTOVER,
        "today":         _agg(items_tdy),
        "all_time":      _agg(items),
        "last_30d":      _agg(items_30),
        "last_7d":       _agg(items_7),
        "streak":        {"type": streak_type, "len": streak_len} if streak_type else None,
        "best_7d":       best_7,
        "worst_7d":      worst_7,
        "recent_picks":  recent_picks,
        "weekly_bars":   weekly_bars,
        "by_surface":    by_surface,
        "by_tour":       by_tour,
        "edge_buckets":  edge_buckets,
        "calibration":   calibration,
        "pnl_trend":     pnl_trend,
        "note":          f"£1 flat stake. P&L at RTT-implied odds. 50/50 picks excluded. New model live from {MODEL_CUTOVER} — earlier predictions not included.",
    }


# ─────────────────────────────────────────────────────────────────────────────
# GET /systems
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/systems/dashboard")
def systems_dashboard():
    """
    One-shot payload for the systems tracker on the predictions page:
    every active system with its all-time stats AND its currently-open
    picks (matches today or in the next 2 days that haven't settled).
    """
    systems_rows = safe_query(
        """
        SELECT system_id AS id, code, name, description, icon, accent_colour,
               picks_total, picks_settled, picks_correct, accuracy_pct,
               profit_units, roi_pct
        FROM v_systems_stats
        WHERE is_active = TRUE
        ORDER BY picks_total DESC NULLS LAST, name
        """
    )

    out = []
    for s in systems_rows:
        picks = safe_query(
            """
            SELECT
                sp.id            AS pick_id,
                sp.match_id,
                sp.pick,
                sp.confidence,
                sp.reason,
                sp.pick_prob,
                sp.market_odds,
                m.event_date, m.event_time, m.event_status,
                t.name AS tournament,
                s.name AS surface,
                m.tournament_round AS round,
                p1.id AS p1_id, p1.name AS p1_name, p1.country_code AS p1_country,
                p2.id AS p2_id, p2.name AS p2_name, p2.country_code AS p2_country
            FROM system_picks sp
            JOIN matches m       ON m.id = sp.match_id
            LEFT JOIN tournaments t ON t.id = m.tournament_id
            LEFT JOIN surfaces s    ON s.id = t.surface_id
            LEFT JOIN players p1    ON p1.id = m.first_player_id
            LEFT JOIN players p2    ON p2.id = m.second_player_id
            WHERE sp.system_id = %s
              AND sp.settled_at IS NULL
              AND m.event_date BETWEEN CURRENT_DATE AND CURRENT_DATE + INTERVAL '3 days'
            ORDER BY m.event_date, m.event_time NULLS LAST
            """,
            (s["id"],),
        )

        picks_serialised = []
        for p in picks:
            pick_side = p["pick"]
            picked = {
                "id":           p["p1_id"] if pick_side == "first_player" else p["p2_id"],
                "name":         p["p1_name"] if pick_side == "first_player" else p["p2_name"],
                "country_code": p["p1_country"] if pick_side == "first_player" else p["p2_country"],
            }
            opp = {
                "id":           p["p2_id"] if pick_side == "first_player" else p["p1_id"],
                "name":         p["p2_name"] if pick_side == "first_player" else p["p1_name"],
                "country_code": p["p2_country"] if pick_side == "first_player" else p["p1_country"],
            }
            picks_serialised.append({
                "pick_id":     p["pick_id"],
                "match_id":    p["match_id"],
                "event_date":  str(p["event_date"]) if p.get("event_date") else None,
                "event_time":  str(p["event_time"]) if p.get("event_time") else None,
                "event_status": p.get("event_status"),
                "tournament":  p.get("tournament"),
                "surface":     p.get("surface"),
                "round":       p.get("round"),
                "confidence":  p.get("confidence"),
                "reason":      p.get("reason"),
                "pick_prob":   float(p["pick_prob"]) if p.get("pick_prob") is not None else None,
                "market_odds": float(p["market_odds"]) if p.get("market_odds") is not None else None,
                "pick":        picked,
                "opponent":    opp,
            })

        # Recent settled picks (last 8) — for the history view on the predictions page
        recent_rows = safe_query(
            """
            SELECT
                sp.id            AS pick_id,
                sp.match_id,
                sp.pick,
                sp.confidence,
                sp.reason,
                sp.pick_prob,
                sp.market_odds,
                sp.is_correct,
                sp.profit_loss,
                m.event_date, m.event_status,
                t.name AS tournament,
                s.name AS surface,
                m.tournament_round AS round,
                p1.id AS p1_id, p1.name AS p1_name, p1.country_code AS p1_country,
                p2.id AS p2_id, p2.name AS p2_name, p2.country_code AS p2_country
            FROM system_picks sp
            JOIN matches m       ON m.id = sp.match_id
            LEFT JOIN tournaments t ON t.id = m.tournament_id
            LEFT JOIN surfaces s    ON s.id = t.surface_id
            LEFT JOIN players p1    ON p1.id = m.first_player_id
            LEFT JOIN players p2    ON p2.id = m.second_player_id
            WHERE sp.system_id = %s
              AND sp.settled_at IS NOT NULL
            ORDER BY sp.settled_at DESC
            LIMIT 8
            """,
            (s["id"],),
        )

        recent_serialised = []
        for p in recent_rows:
            pick_side = p["pick"]
            picked = {
                "id":           p["p1_id"] if pick_side == "first_player" else p["p2_id"],
                "name":         p["p1_name"] if pick_side == "first_player" else p["p2_name"],
                "country_code": p["p1_country"] if pick_side == "first_player" else p["p2_country"],
            }
            opp = {
                "id":           p["p2_id"] if pick_side == "first_player" else p["p1_id"],
                "name":         p["p2_name"] if pick_side == "first_player" else p["p1_name"],
                "country_code": p["p2_country"] if pick_side == "first_player" else p["p1_country"],
            }
            recent_serialised.append({
                "pick_id":     p["pick_id"],
                "match_id":    p["match_id"],
                "event_date":  str(p["event_date"]) if p.get("event_date") else None,
                "tournament":  p.get("tournament"),
                "surface":     p.get("surface"),
                "round":       p.get("round"),
                "confidence":  p.get("confidence"),
                "reason":      p.get("reason"),
                "pick_prob":   float(p["pick_prob"]) if p.get("pick_prob") is not None else None,
                "market_odds": float(p["market_odds"]) if p.get("market_odds") is not None else None,
                "is_correct":  p.get("is_correct"),
                "profit_loss": float(p["profit_loss"]) if p.get("profit_loss") is not None else None,
                "pick":        picked,
                "opponent":    opp,
            })

        out.append({
            "id":            s["id"],
            "code":          s["code"],
            "name":          s["name"],
            "description":   s["description"],
            "icon":          s["icon"],
            "accent_colour": s["accent_colour"],
            "stats": {
                "picks_total":  s["picks_total"] or 0,
                "picks_settled": s["picks_settled"] or 0,
                "picks_correct": s["picks_correct"] or 0,
                "accuracy_pct":  float(s["accuracy_pct"]) if s.get("accuracy_pct") is not None else None,
                "profit_units":  float(s["profit_units"]) if s.get("profit_units") is not None else None,
                "roi_pct":       float(s["roi_pct"])      if s.get("roi_pct")      is not None else None,
            },
            "open_picks":    picks_serialised,
            "recent_picks":  recent_serialised,
        })

    return {"systems": out}


@router.get("/systems")
def list_systems(include_inactive: bool = False):
    where = "" if include_inactive else "WHERE is_active = TRUE"
    rows = safe_query(
        f"""
        SELECT system_id AS id, code, name, description, icon, accent_colour,
               picks_total, picks_settled, picks_correct, accuracy_pct,
               profit_units, roi_pct
        FROM v_systems_stats
        {where}
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
