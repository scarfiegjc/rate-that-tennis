"""
ratethat.tennis API — My Picks routes.

POST   /picks                 create a pick (auth required)
DELETE /picks/{id}            remove a pick (only if still pending, auth required)
GET    /picks/active          pending + live picks with full card data (auth required)
GET    /picks/results         settled picks + P&L stats (auth required)
POST   /picks/{id}/settle     admin/pipeline: mark a pick won/lost/void
"""
import logging
import traceback
from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from typing import Optional

from api.db import query, query_one, get_conn
from api.routes.auth import get_current_user

log = logging.getLogger("api.picks")
router = APIRouter(prefix="/picks", tags=["picks"])


# ─────────────────────────────────────────────────────────────────────────────
# Pydantic models
# ─────────────────────────────────────────────────────────────────────────────

class CreatePickRequest(BaseModel):
    match_id:         int
    player_id:        int
    confidence_stars: int = 1       # 1-5
    our_odds:         Optional[float] = None
    best_odds:        Optional[float] = None
    best_odds_bookie: Optional[str]  = None


class SettlePickRequest(BaseModel):
    status:     str           # "won" | "lost" | "void"
    live_score: Optional[str] = None


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _enrich_pick(pick: dict) -> dict:
    """Attach full match + player + ratings + prediction data to a pick row."""
    mid = pick["match_id"]
    pid = pick["player_id"]

    # Match details
    match = query_one(
        """
        SELECT m.id, m.event_date, m.event_time, m.event_status,
               m.first_player_id, m.second_player_id,
               m.game_result, m.final_result, m.winner, m.is_live,
               t.name AS tournament_name,
               s.name AS surface,
               COALESCE(
                 (SELECT string_agg(score_first || '-' || score_second, ' ' ORDER BY set_number)
                  FROM match_scores ms WHERE ms.match_id = m.id),
                 NULL
               ) AS set_scores
        FROM matches m
        LEFT JOIN tournaments t ON t.id = m.tournament_id
        LEFT JOIN surfaces    s ON s.id = t.surface_id
        WHERE m.id = %s
        """,
        (mid,),
    ) or {}

    # Both players
    p1_id = match.get("first_player_id")
    p2_id = match.get("second_player_id")
    opp_id = p2_id if pid == p1_id else p1_id

    def _player(player_id):
        if not player_id:
            return {}
        return query_one(
            "SELECT id, name, country FROM players WHERE id = %s",
            (player_id,),
        ) or {}

    def _ratings(player_id):
        if not player_id:
            return {}
        return query_one(
            """SELECT rtt_score, clay_rating, hard_rating, grass_rating, indoor_rating,
                      serve_rating, return_rating, form_score, consistency_score,
                      pressure_rating, momentum
               FROM player_ratings WHERE player_id = %s""",
            (player_id,),
        ) or {}

    def _form_dots(player_id, limit=8):
        if not player_id:
            return []
        rows = query(
            """SELECT m.winner,
                      CASE WHEN m.first_player_id  = %s THEN 'First Player'
                           WHEN m.second_player_id = %s THEN 'Second Player' END AS side
               FROM matches m
               WHERE (m.first_player_id = %s OR m.second_player_id = %s)
                 AND m.event_status ILIKE 'Finished'
               ORDER BY m.event_date DESC, m.id DESC
               LIMIT %s""",
            (player_id, player_id, player_id, player_id, limit),
        )
        dots = []
        for r in rows:
            won = r.get("winner") == r.get("side")
            dots.append("W" if won else "L")
        return dots

    # H2H
    h2h_rows = query(
        """SELECT winner
           FROM matches
           WHERE ((first_player_id = %s AND second_player_id = %s)
               OR (first_player_id = %s AND second_player_id = %s))
             AND event_status ILIKE 'Finished'
           ORDER BY event_date DESC
           LIMIT 10""",
        (pid, opp_id, opp_id, pid),
    )
    h2h_wins   = sum(1 for r in h2h_rows if
                     (r["winner"] == "First Player"  and pid == p1_id) or
                     (r["winner"] == "Second Player" and pid == p2_id))
    h2h_losses = len(h2h_rows) - h2h_wins

    # Model prediction
    pred = query_one(
        """SELECT prob_first_player, prob_second_player,
                  rtt_gap, surface_gap, confidence
           FROM model_predictions WHERE match_id = %s""",
        (mid,),
    ) or {}

    # Compute edge from latest bookmaker odds
    def _implied(decimal_odds):
        if not decimal_odds or float(decimal_odds) <= 1:
            return None
        return 1.0 / float(decimal_odds)

    odds_rows = query(
        """SELECT player_ref, MIN(1.0/NULLIF(implied_prob,0)) AS best_decimal,
                  MAX(implied_prob) AS worst_impl
           FROM bookmaker_odds
           WHERE match_id = %s AND fetched_at > NOW() - INTERVAL '24 hours'
           GROUP BY player_ref""",
        (mid,),
    )
    odds_map = {r["player_ref"]: r for r in odds_rows}

    def _edge(model_prob, impl_prob):
        if model_prob is None or impl_prob is None:
            return None
        return float(model_prob) - float(impl_prob)

    p1_impl = odds_map.get("first_player", {}).get("worst_impl")
    p2_impl = odds_map.get("second_player", {}).get("worst_impl")
    e_p1 = _edge(pred.get("prob_first_player"), p1_impl)
    e_p2 = _edge(pred.get("prob_second_player"), p2_impl)

    is_first = (pid == p1_id)
    win_prob = pred.get("prob_first_player")  if is_first else pred.get("prob_second_player")
    # edge_val is already a percentage-point difference (e.g. 5.0 = 5% edge)
    edge_val = (e_p1 * 100) if is_first and e_p1 is not None else (
               (e_p2 * 100) if not is_first and e_p2 is not None else None)
    # NOTE: edge_val is already in percentage points, do NOT multiply by 100 again below
    opp_prob = pred.get("prob_second_player") if is_first else pred.get("prob_first_player")

    # Surface-specific rating for this match
    surface_key = {
        "clay":       "clay_rating",
        "hard":       "hard_rating",
        "grass":      "grass_rating",
        "indoor hard":"indoor_rating",
    }.get((match.get("surface") or "").lower(), "hard_rating")

    picked_ratings = _ratings(pid)
    opp_ratings    = _ratings(opp_id)
    picked_player  = _player(pid)
    opp_player     = _player(opp_id)

    # Status: override pick status based on live match state
    status = pick["status"]
    ms = (match.get("event_status") or "").lower()
    winner = match.get("winner")
    if status in ("pending", "live"):
        if "finished" in ms and winner:
            # Settle immediately — write to DB first, only update status if write succeeds
            winner_pid = (
                match.get("first_player_id")  if winner == "First Player"  else
                match.get("second_player_id") if winner == "Second Player" else
                None
            )
            if winner_pid is not None:
                new_status = "won" if pid == winner_pid else "lost"
                stake = float(pick.get("confidence_stars") or 1)
                if new_status == "won":
                    odds = float(pick.get("our_odds") or 2.0)
                    pl = round((odds - 1) * stake, 2)
                else:
                    pl = round(-stake, 2)
                try:
                    with get_conn() as _conn:
                        with _conn.cursor() as _cur:
                            _cur.execute(
                                """UPDATE user_picks
                                   SET status = %s, settled_at = NOW(), profit_loss = %s
                                   WHERE id = %s AND status IN ('pending','live')""",
                                (new_status, pl, pick["id"]),
                            )
                    status = new_status  # only update in-memory status if DB write succeeded
                except Exception as _e:
                    log.warning(f"inline settle failed for pick {pick['id']}: {_e}")
                    # Leave status as-is so pick stays visible in active tab
        elif any(k in ms for k in ("in play", "live", "set ", "game", "1st", "2nd", "3rd")):
            status = "live"

    return {
        **pick,
        "status": status,
        "is_first_player": is_first,
        "match": {
            "id":              mid,
            "event_date":      str(match.get("event_date", "")),
            "event_time":      match.get("event_time"),
            "event_status":    match.get("event_status"),
            "tournament_name": match.get("tournament_name"),
            "surface":         match.get("surface"),
            "is_live":         bool(match.get("is_live")),
            "set_scores":      match.get("set_scores"),
            "game_result":     match.get("game_result"),
            "live_score":      match.get("game_result") or match.get("final_result"),
            "winner":          match.get("winner"),
        },
        "picked_player": {
            **picked_player,
            "ratings":      picked_ratings,
            "surface_rating": picked_ratings.get(surface_key),
            "form_dots":    _form_dots(pid),
            "win_prob":     round(float(win_prob) * 100, 1) if win_prob is not None else None,
            "edge":         round(float(edge_val), 1) if edge_val is not None else None,
        },
        "opponent": {
            **opp_player,
            "ratings":      opp_ratings,
            "surface_rating": opp_ratings.get(surface_key),
            "form_dots":    _form_dots(opp_id),
            "win_prob":     round(float(opp_prob) * 100, 1) if opp_prob is not None else None,
        },
        "h2h": {
            "wins":   h2h_wins,
            "losses": h2h_losses,
            "total":  len(h2h_rows),
        },
        "prediction_confidence": pred.get("confidence"),
    }


# ─────────────────────────────────────────────────────────────────────────────
# Routes
# ─────────────────────────────────────────────────────────────────────────────

@router.post("")
def create_pick(req: CreatePickRequest, user=Depends(get_current_user)):
    if req.confidence_stars < 1 or req.confidence_stars > 5:
        raise HTTPException(status_code=400, detail="confidence_stars must be 1-5")

    # Verify match and player exist
    match = query_one("SELECT id, first_player_id, second_player_id, event_status FROM matches WHERE id = %s",
                      (req.match_id,))
    if not match:
        raise HTTPException(status_code=404, detail="Match not found")
    if req.player_id not in (match["first_player_id"], match["second_player_id"]):
        raise HTTPException(status_code=400, detail="Player is not in this match")

    # Can't pick finished matches
    if "finished" in (match.get("event_status") or "").lower():
        raise HTTPException(status_code=400, detail="Cannot pick a finished match")

    try:
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """INSERT INTO user_picks
                           (user_id, match_id, player_id, confidence_stars,
                            our_odds, best_odds, best_odds_bookie)
                       VALUES (%s, %s, %s, %s, %s, %s, %s)
                       ON CONFLICT (user_id, match_id, player_id) DO NOTHING
                       RETURNING id""",
                    (user["id"], req.match_id, req.player_id, req.confidence_stars,
                     req.our_odds, req.best_odds, req.best_odds_bookie),
                )
                row = cur.fetchone()
                if not row:
                    raise HTTPException(status_code=409, detail="Pick already exists for this player/match")
                pick_id = row["id"]

    except HTTPException:
        raise
    except Exception as e:
        log.error(f"create_pick INSERT error: {e}\n{traceback.format_exc()}")
        raise HTTPException(status_code=500, detail=f"Failed to create pick: {str(e)}")

    try:
        pick = query_one("SELECT * FROM user_picks WHERE id = %s", (pick_id,))
        enriched = _enrich_pick(dict(pick))
        return {"pick": enriched}
    except Exception as e:
        log.error(f"create_pick enrich error (pick_id={pick_id}): {e}\n{traceback.format_exc()}")
        # Pick was created successfully — return minimal response so the UI still works
        return {"pick": {"id": pick_id, "match_id": req.match_id, "player_id": req.player_id,
                         "status": "pending", "confidence_stars": req.confidence_stars}}


@router.delete("/{pick_id}")
def delete_pick(pick_id: int, user=Depends(get_current_user)):
    pick = query_one("SELECT * FROM user_picks WHERE id = %s AND user_id = %s",
                     (pick_id, user["id"]))
    if not pick:
        raise HTTPException(status_code=404, detail="Pick not found")
    if pick["status"] in ("live", "won", "lost"):
        raise HTTPException(status_code=400, detail="Cannot remove a live or settled pick")

    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM user_picks WHERE id = %s AND user_id = %s",
                        (pick_id, user["id"]))
    return {"ok": True}


@router.get("/active")
def get_active_picks(user=Depends(get_current_user)):
    rows = query(
        """SELECT * FROM user_picks
           WHERE user_id = %s AND status IN ('pending','live')
           ORDER BY created_at DESC""",
        (user["id"],),
    )
    enriched = []
    errors = []
    for row in rows:
        try:
            enriched.append(_enrich_pick(dict(row)))
        except Exception as e:
            log.warning(f"enrich_pick failed for pick {row['id']}: {e}\n{traceback.format_exc()}")
            errors.append({"pick_id": row["id"], "error": str(e)})
            # Return raw pick with minimal structure so UI shows something
            enriched.append({
                "id": row["id"],
                "match_id": row["match_id"],
                "player_id": row["player_id"],
                "status": row["status"],
                "confidence_stars": row["confidence_stars"],
                "_enrich_error": str(e),
                "match": {"id": row["match_id"]},
                "picked_player": {"name": "Loading...", "ratings": {}, "form_dots": []},
                "opponent": {"name": "Loading...", "ratings": {}, "form_dots": []},
                "h2h": {"wins": 0, "losses": 0, "total": 0},
            })
    return {"picks": enriched, "_errors": errors}


@router.get("/results")
def get_results(user=Depends(get_current_user)):
    rows = query(
        """SELECT * FROM user_picks
           WHERE user_id = %s AND status IN ('won','lost','void')
           ORDER BY settled_at DESC NULLS LAST""",
        (user["id"],),
    )

    picks = []
    for row in rows:
        try:
            picks.append(_enrich_pick(dict(row)))
        except Exception as e:
            log.warning(f"enrich_pick (results) failed for pick {row['id']}: {e}")

    # ── Stats summary ──────────────────────────────────────────────────────────
    total   = len(picks)
    wins    = sum(1 for p in picks if p["status"] == "won")
    losses  = sum(1 for p in picks if p["status"] == "lost")
    voids   = sum(1 for p in picks if p["status"] == "void")
    win_rate = round(wins / (wins + losses) * 100, 1) if (wins + losses) > 0 else 0.0

    # P&L: stake = confidence_stars × £1
    total_pl = sum(
        float(p.get("profit_loss") or 0.0) for p in picks
    )

    # P&L over time (cumulative, for the chart)
    pl_series = []
    running = 0.0
    for p in reversed(picks):   # chronological order
        running += float(p.get("profit_loss") or 0.0)
        pl_series.append({
            "date":   p["match"].get("event_date"),
            "player": p["picked_player"].get("name"),
            "pl":     round(running, 2),
        })

    # Breakdown by surface
    surface_breakdown = {}
    for p in picks:
        surf = (p["match"].get("surface") or "Unknown").capitalize()
        if surf not in surface_breakdown:
            surface_breakdown[surf] = {"wins": 0, "losses": 0, "pl": 0.0}
        if p["status"] == "won":
            surface_breakdown[surf]["wins"] += 1
        elif p["status"] == "lost":
            surface_breakdown[surf]["losses"] += 1
        surface_breakdown[surf]["pl"] += float(p.get("profit_loss") or 0.0)

    # Breakdown by confidence stars
    stars_breakdown = {}
    for p in picks:
        stars = p.get("confidence_stars", 1)
        k = str(stars)
        if k not in stars_breakdown:
            stars_breakdown[k] = {"wins": 0, "losses": 0, "pl": 0.0}
        if p["status"] == "won":
            stars_breakdown[k]["wins"] += 1
        elif p["status"] == "lost":
            stars_breakdown[k]["losses"] += 1
        stars_breakdown[k]["pl"] += float(p.get("profit_loss") or 0.0)

    return {
        "picks": picks,
        "stats": {
            "total":    total,
            "wins":     wins,
            "losses":   losses,
            "voids":    voids,
            "win_rate": win_rate,
            "total_pl": round(total_pl, 2),
        },
        "pl_series":          pl_series,
        "surface_breakdown":  surface_breakdown,
        "stars_breakdown":    stars_breakdown,
    }


@router.post("/{pick_id}/settle")
def settle_pick(pick_id: int, req: SettlePickRequest):
    """Called by the pipeline/scheduler when a match result is known."""
    if req.status not in ("won", "lost", "void"):
        raise HTTPException(status_code=400, detail="status must be won, lost, or void")

    pick = query_one("SELECT * FROM user_picks WHERE id = %s", (pick_id,))
    if not pick:
        raise HTTPException(status_code=404, detail="Pick not found")

    stake = float(pick["confidence_stars"])
    if req.status == "won":
        odds = float(pick["our_odds"] or 2.0)
        pl = round((odds - 1) * stake, 2)
    elif req.status == "lost":
        pl = round(-stake, 2)
    else:
        pl = 0.0

    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """UPDATE user_picks
                   SET status = %s, settled_at = NOW(), profit_loss = %s,
                       live_score = COALESCE(%s, live_score)
                   WHERE id = %s""",
                (req.status, pl, req.live_score, pick_id),
            )
    return {"ok": True, "profit_loss": pl}


@router.post("/settle-by-match/{match_id}")
def settle_picks_by_match(match_id: int):
    """
    Settle all pending/live picks for a completed match.
    Called automatically when a match result is known (e.g. from the pipeline).
    """
    match = query_one(
        """SELECT id, first_player_id, second_player_id, winner, game_result, final_result
           FROM matches WHERE id = %s""",
        (match_id,),
    )
    if not match:
        raise HTTPException(status_code=404, detail="Match not found")
    if not match.get("winner"):
        raise HTTPException(status_code=400, detail="Match has no winner recorded yet")

    winner_player_id = (
        match["first_player_id"]  if match["winner"] == "First Player"  else
        match["second_player_id"] if match["winner"] == "Second Player" else
        None
    )

    picks = query(
        "SELECT * FROM user_picks WHERE match_id = %s AND status IN ('pending','live')",
        (match_id,),
    )
    settled = 0
    for pick in picks:
        if winner_player_id is None:
            status = "void"
        else:
            status = "won" if pick["player_id"] == winner_player_id else "lost"

        stake = float(pick["confidence_stars"])
        if status == "won":
            odds = float(pick["our_odds"] or 2.0)
            pl   = round((odds - 1) * stake, 2)
        elif status == "lost":
            pl   = round(-stake, 2)
        else:
            pl   = 0.0

        score_str = match.get("game_result") or match.get("final_result")

        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """UPDATE user_picks
                       SET status = %s, settled_at = NOW(),
                           profit_loss = %s, live_score = %s
                       WHERE id = %s""",
                    (status, pl, score_str, pick["id"]),
                )
        settled += 1

    return {"ok": True, "settled": settled, "match_id": match_id}
