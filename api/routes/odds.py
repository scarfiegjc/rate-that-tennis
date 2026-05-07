"""
ratethat.tennis API — Match odds & affiliate links.

GET /matches/{id}/odds
    Returns the latest bookmaker odds for one match, plus:
      - rtt_fair_odds   : our model's win-prob converted to fair decimal odds
      - best_value      : highest decimal odds per side (with edge vs fair)
      - all_bookmakers  : every bookmaker that priced the match (for compare)
      - show_odds       : feature flag — false for live matches until we
                          subscribe to in-play data

The frontend OddsComparison component on the match detail page consumes this.
"""
from __future__ import annotations
import os
from fastapi import APIRouter, HTTPException

from api.db import query, query_one

# Affiliate config lives in the pipeline package so the script and API agree.
try:
    from pipeline.affiliate_config import (
        BOOKMAKERS, display_name, click_url, is_affiliate, get_bookmaker,
    )
except ImportError:
    # Railway image flattens pipeline/ into /app — fall back to flat import
    from affiliate_config import (  # type: ignore
        BOOKMAKERS, display_name, click_url, is_affiliate, get_bookmaker,
    )

router = APIRouter(prefix="/matches", tags=["odds"])


# Feature flag — flip to True once we have a live-odds subscription that can
# absorb the credit cost of polling in-play matches every few seconds.
LIVE_ODDS_VISIBLE = os.environ.get("LIVE_ODDS_VISIBLE", "false").lower() in ("1", "true", "yes")


# ─── helpers ─────────────────────────────────────────────────────────────────

def _fair_odds(prob: float | None) -> float | None:
    """Convert a model win probability into fair decimal odds."""
    if prob is None or prob <= 0 or prob >= 1:
        return None
    return round(1.0 / prob, 2)


def _edge_pct(market_odds: float | None, fair_odds: float | None) -> float | None:
    """
    Edge as a percentage of fair value. Positive = market price is generous
    (value), negative = market is short.

    e.g. fair 1.54, market 1.85 → 1.85/1.54 - 1 = 0.20 → +20%
    """
    if not market_odds or not fair_odds or market_odds <= 1 or fair_odds <= 1:
        return None
    return round((market_odds / fair_odds - 1.0) * 100, 1)


def _enrich_bm(bm_key: str) -> dict:
    """Extract the public-facing fields for a bookmaker."""
    return {
        "key":           bm_key,
        "display_name":  display_name(bm_key),
        "is_affiliate":  is_affiliate(bm_key),
        "click_url":     click_url(bm_key),
    }


# ─── endpoint ────────────────────────────────────────────────────────────────

@router.get("/{match_id}/odds")
def get_match_odds(match_id: int):
    """
    Return the bookmaker odds + best-value computation for a single match.
    """
    m = query_one(
        """
        SELECT m.id, m.first_player_id, m.second_player_id,
               m.event_status, m.is_live,
               p1.name AS p1_name, p2.name AS p2_name,
               mp.prob_first_player, mp.prob_second_player
        FROM matches m
        LEFT JOIN players p1 ON p1.id = m.first_player_id
        LEFT JOIN players p2 ON p2.id = m.second_player_id
        LEFT JOIN model_predictions mp ON mp.match_id = m.id
        WHERE m.id = %s
        """,
        (match_id,),
    )
    if not m:
        raise HTTPException(status_code=404, detail="Match not found")

    is_live = bool(m.get("is_live")) or (m.get("event_status") or "").lower().startswith("set")
    is_finished = (m.get("event_status") or "").lower() == "finished"

    # Hide live odds until we have an in-play subscription that justifies the cost.
    show_odds = not is_live or LIVE_ODDS_VISIBLE

    # RTT fair odds = 1 / model probability
    p1_prob = float(m["prob_first_player"]) if m.get("prob_first_player") is not None else None
    p2_prob = float(m["prob_second_player"]) if m.get("prob_second_player") is not None else None
    fair = {
        "p1": _fair_odds(p1_prob),
        "p2": _fair_odds(p2_prob),
    }

    # Pull the latest odds row per (bookmaker, player_ref).
    # We DISTINCT ON to handle the case where the pipeline has refreshed
    # multiple times — only the most recent row per bookmaker matters.
    rows = query(
        """
        SELECT DISTINCT ON (bookmaker, player_ref)
            bookmaker, player_ref, decimal_odds, implied_prob, fetched_at
        FROM bookmaker_odds
        WHERE match_id = %s
          AND decimal_odds IS NOT NULL
          AND decimal_odds > 1.0
        ORDER BY bookmaker, player_ref, fetched_at DESC
        """,
        (match_id,),
    )

    # Group by bookmaker
    by_bm: dict[str, dict] = {}
    latest_fetch = None
    for r in rows:
        bm_key = r["bookmaker"]
        side = "p1" if r["player_ref"] == "first_player" else "p2"
        if bm_key not in by_bm:
            by_bm[bm_key] = {**_enrich_bm(bm_key), "p1": None, "p2": None}
        by_bm[bm_key][side] = {
            "decimal_odds": float(r["decimal_odds"]),
            "implied_prob": float(r["implied_prob"]) if r["implied_prob"] else None,
        }
        if not latest_fetch or r["fetched_at"] > latest_fetch:
            latest_fetch = r["fetched_at"]

    # Sort bookmakers — affiliates first, then alphabetical
    all_bookmakers = sorted(
        by_bm.values(),
        key=lambda b: (not b["is_affiliate"], b["display_name"].lower()),
    )

    # Best value per side = highest decimal_odds among bookmakers that quoted both sides.
    # We require both sides to be present so the user is comparing apples to apples
    # (a bookmaker with only p1 odds isn't a real contender for "best price").
    eligible = [b for b in all_bookmakers if b.get("p1") and b.get("p2")]

    def _best(side: str) -> dict | None:
        contenders = [b for b in eligible if b.get(side)]
        if not contenders:
            return None
        winner = max(contenders, key=lambda b: b[side]["decimal_odds"])
        market_odds = winner[side]["decimal_odds"]
        return {
            "key":           winner["key"],
            "display_name":  winner["display_name"],
            "is_affiliate":  winner["is_affiliate"],
            "click_url":     winner["click_url"],
            "decimal_odds":  market_odds,
            "implied_prob":  winner[side]["implied_prob"],
            "edge_pct":      _edge_pct(market_odds, fair.get(side)),
        }

    best_value = {
        "p1": _best("p1"),
        "p2": _best("p2"),
    }

    # Headline value pick — which side has bigger positive edge?
    headline = None
    e1 = (best_value["p1"] or {}).get("edge_pct")
    e2 = (best_value["p2"] or {}).get("edge_pct")
    if e1 is not None and e1 >= 2 and (e2 is None or e1 >= e2):
        headline = "p1"
    elif e2 is not None and e2 >= 2:
        headline = "p2"

    return {
        "match_id":       match_id,
        "is_live":        is_live,
        "is_finished":    is_finished,
        "show_odds":      show_odds,
        "live_hidden":    is_live and not LIVE_ODDS_VISIBLE,
        "players": {
            "p1": {"name": m.get("p1_name"), "prob": p1_prob},
            "p2": {"name": m.get("p2_name"), "prob": p2_prob},
        },
        "rtt_fair_odds":  fair,
        "best_value":     best_value,
        "headline_side":  headline,        # 'p1' | 'p2' | None
        "all_bookmakers": all_bookmakers,
        "fetched_at":     latest_fetch.isoformat() if latest_fetch else None,
        "bookmaker_count": len(all_bookmakers),
    }
