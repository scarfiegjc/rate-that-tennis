"""
GET /api/v1/stats/conflicts

Returns upcoming matches where two or more player stats are in direct
conflict — i.e. one player rates "great" on a dimension where the other
player rates "poor" on that same dimension.

Sorted by total conflict strength (strongest first).
"""

from datetime import date, timedelta
from fastapi import APIRouter
from api.db import query

router = APIRouter()

# ─────────────────────────────────────────────────────────────────────────────
# Thresholds
# ─────────────────────────────────────────────────────────────────────────────

GREAT = 65   # >= this → player is "great" at this stat
POOR  = 42   # <= this → player is "poor" at this stat


# ─────────────────────────────────────────────────────────────────────────────
# Stat definitions
# Each entry: (db_column, human label, great_phrase, poor_phrase)
# Surface stat is handled separately (varies per match).
# ─────────────────────────────────────────────────────────────────────────────

STAT_DEFS = [
    ("serve_rating",       "Serve",           "Powerful serve",      "Weak serve"),
    ("return_rating",      "Return",          "Elite returner",      "Poor returner"),
    ("pressure_rating",    "Clutch",          "Thrives under pressure", "Struggles under pressure"),
    ("consistency_score",  "Consistency",     "Highly consistent",   "Error-prone"),
    ("form_score",         "Current form",    "In excellent form",   "Out of form"),
    ("big_match_rating",   "Big match",       "Big-match performer", "Fades in big matches"),
    ("vs_top10_rating",    "vs Top 10",       "Dominates top players", "Struggles vs top players"),
]

SURFACE_LABELS = {
    "clay":        ("clay_rating",    "Clay",    "Excels on clay",        "Struggles on clay"),
    "hard":        ("hard_rating",    "Hard",    "Excels on hard courts", "Struggles on hard courts"),
    "grass":       ("grass_rating",   "Grass",   "Excels on grass",       "Struggles on grass"),
    "indoor hard": ("indoor_rating",  "Indoor",  "Strong indoors",        "Poor indoors"),
    "indoor":      ("indoor_rating",  "Indoor",  "Strong indoors",        "Poor indoors"),
    "carpet":      ("indoor_rating",  "Carpet",  "Strong on carpet",      "Poor on carpet"),
}

# Cross-stat conflicts: when player A is great at X and player B is poor at Y
# they create a tactical mismatch (not the same stat on both sides).
CROSS_DEFS = [
    # (p_great_col, p_poor_col, label, great_phrase, poor_phrase)
    ("serve_rating",   "return_rating",  "Serve vs Return",
     "Dominant server",  "Weak returner"),
    ("return_rating",  "serve_rating",   "Return vs Serve",
     "Elite returner",   "Weak server"),
]


def _strength(great_val, poor_val):
    """How extreme is this conflict? Extra points for being beyond threshold."""
    return max(0, great_val - GREAT) + max(0, POOR - poor_val)


def _find_conflicts(p1: dict, p2: dict, surface: str, tourney_level: str):
    """
    Return a list of conflict dicts for a single match.
    p1/p2 are rating dicts keyed by column name.
    """
    conflicts = []

    def _add(stat_key, label, great_phrase, poor_phrase,
             p1_val, p2_val):
        """Add a conflict if the gap qualifies."""
        if p1_val is None or p2_val is None:
            return
        p1_v = float(p1_val)
        p2_v = float(p2_val)

        # P1 great, P2 poor
        if p1_v >= GREAT and p2_v <= POOR:
            conflicts.append({
                "stat": stat_key,
                "label": label,
                "favoured_player": "first",
                "favoured_value": round(p1_v, 1),
                "opponent_value": round(p2_v, 1),
                "gap": round(p1_v - p2_v, 1),
                "strength": _strength(p1_v, p2_v),
                "favoured_label": great_phrase,
                "opponent_label": poor_phrase,
            })
        # P2 great, P1 poor
        elif p2_v >= GREAT and p1_v <= POOR:
            conflicts.append({
                "stat": stat_key,
                "label": label,
                "favoured_player": "second",
                "favoured_value": round(p2_v, 1),
                "opponent_value": round(p1_v, 1),
                "gap": round(p2_v - p1_v, 1),
                "strength": _strength(p2_v, p1_v),
                "favoured_label": great_phrase,
                "opponent_label": poor_phrase,
            })

    # Surface stat
    surf_key = (surface or "").lower()
    if surf_key in SURFACE_LABELS:
        col, surf_label, gp, pp = SURFACE_LABELS[surf_key]
        _add(col, surf_label, gp, pp, p1.get(col), p2.get(col))

    # Standard per-stat comparisons
    for col, label, gp, pp in STAT_DEFS:
        # Skip big_match unless it's a Slam or Masters
        if col == "big_match_rating" and tourney_level not in ("GS", "Masters", "ATP Masters 1000", "M"):
            continue
        _add(col, label, gp, pp, p1.get(col), p2.get(col))

    # Cross-stat conflicts
    for p_great_col, p_poor_col, label, gp, pp in CROSS_DEFS:
        # Already covered serve_rating vs serve_rating above; skip duplicate signals
        if p_great_col == p_poor_col:
            continue
        p1g = p1.get(p_great_col)
        p2p = p2.get(p_poor_col)
        p2g = p2.get(p_great_col)
        p1p = p1.get(p_poor_col)

        # Avoid surfacing a cross-conflict that duplicates a same-stat conflict
        already_in = {c["stat"] for c in conflicts}

        if p1g is not None and p2p is not None:
            p1g_v, p2p_v = float(p1g), float(p2p)
            if p1g_v >= GREAT and p2p_v <= POOR:
                cross_key = f"{p_great_col}_vs_{p_poor_col}"
                if cross_key not in already_in:
                    conflicts.append({
                        "stat": cross_key,
                        "label": label,
                        "favoured_player": "first",
                        "favoured_value": round(p1g_v, 1),
                        "opponent_value": round(p2p_v, 1),
                        "gap": round(p1g_v - p2p_v, 1),
                        "strength": _strength(p1g_v, p2p_v),
                        "favoured_label": gp,
                        "opponent_label": pp,
                    })

        if p2g is not None and p1p is not None:
            p2g_v, p1p_v = float(p2g), float(p1p)
            if p2g_v >= GREAT and p1p_v <= POOR:
                cross_key = f"{p_great_col}_vs_{p_poor_col}_rev"
                if cross_key not in already_in:
                    conflicts.append({
                        "stat": cross_key,
                        "label": label,
                        "favoured_player": "second",
                        "favoured_value": round(p2g_v, 1),
                        "opponent_value": round(p1p_v, 1),
                        "gap": round(p2g_v - p1p_v, 1),
                        "strength": _strength(p2g_v, p1p_v),
                        "favoured_label": gp,
                        "opponent_label": pp,
                    })

    # Sort conflicts within match: strongest first
    conflicts.sort(key=lambda c: c["strength"], reverse=True)
    return conflicts


def _edge(model_prob, implied_prob):
    if model_prob is None or implied_prob is None or implied_prob <= 0:
        return None
    return round((model_prob - implied_prob) * 100, 1)


def _slug(s):
    import re, unicodedata
    s = unicodedata.normalize("NFD", s or "").encode("ascii", "ignore").decode()
    s = re.sub(r"[^a-z0-9]+", "-", s.lower())
    return s.strip("-")


# ─────────────────────────────────────────────────────────────────────────────
# Endpoint
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/stats/conflicts")
def get_stat_conflicts(days_ahead: int = 2, min_conflicts: int = 1):
    """
    Upcoming matches with significant stat conflicts.
    Sorted by total conflict strength (strongest first).
    """
    today  = date.today().isoformat()
    cutoff = (date.today() + timedelta(days=days_ahead)).isoformat()

    rows = query(
        """
        SELECT
            m.id,
            m.first_player_id,
            m.second_player_id,
            m.event_date,
            m.event_time,
            m.tournament_round,
            m.event_status,
            t.name  AS tournament_name,
            et.type_name AS event_type_name,
            s.name  AS surface_name,
            p1.name AS p1_name,
            p1.country_code AS p1_country,
            p2.name AS p2_name,
            p2.country_code AS p2_country,
            -- All rating columns for both players
            pr1.rtt_score         AS p1_rtt,
            pr1.clay_rating       AS p1_clay,
            pr1.hard_rating       AS p1_hard,
            pr1.grass_rating      AS p1_grass,
            pr1.indoor_rating     AS p1_indoor,
            pr1.serve_rating      AS p1_serve,
            pr1.return_rating     AS p1_return,
            pr1.pressure_rating   AS p1_pressure,
            pr1.consistency_score AS p1_consistency,
            pr1.form_score        AS p1_form,
            pr1.big_match_rating  AS p1_bigmatch,
            pr1.vs_top10_rating   AS p1_vstop10,
            pr2.rtt_score         AS p2_rtt,
            pr2.clay_rating       AS p2_clay,
            pr2.hard_rating       AS p2_hard,
            pr2.grass_rating      AS p2_grass,
            pr2.indoor_rating     AS p2_indoor,
            pr2.serve_rating      AS p2_serve,
            pr2.return_rating     AS p2_return,
            pr2.pressure_rating   AS p2_pressure,
            pr2.consistency_score AS p2_consistency,
            pr2.form_score        AS p2_form,
            pr2.big_match_rating  AS p2_bigmatch,
            pr2.vs_top10_rating   AS p2_vstop10,
            -- Predictions
            mp.prob_first_player,
            mp.prob_second_player,
            -- Odds for edge calc
            bo1.decimal_odds AS odds_p1,
            bo1.implied_prob AS impl_p1,
            bo2.decimal_odds AS odds_p2,
            bo2.implied_prob AS impl_p2
        FROM matches m
        LEFT JOIN tournaments t   ON t.id = m.tournament_id
        LEFT JOIN event_types et  ON et.id = m.event_type_id
        LEFT JOIN surfaces s      ON s.id = t.surface_id
        LEFT JOIN players p1      ON p1.id = m.first_player_id
        LEFT JOIN players p2      ON p2.id = m.second_player_id
        LEFT JOIN player_ratings pr1 ON pr1.player_id = m.first_player_id
        LEFT JOIN player_ratings pr2 ON pr2.player_id = m.second_player_id
        LEFT JOIN model_predictions mp ON mp.match_id = m.id
        LEFT JOIN LATERAL (
            SELECT decimal_odds, implied_prob
            FROM bookmaker_odds
            WHERE match_id = m.id AND player_ref = 'first_player'
            ORDER BY fetched_at DESC LIMIT 1
        ) bo1 ON TRUE
        LEFT JOIN LATERAL (
            SELECT decimal_odds, implied_prob
            FROM bookmaker_odds
            WHERE match_id = m.id AND player_ref = 'second_player'
            ORDER BY fetched_at DESC LIMIT 1
        ) bo2 ON TRUE
        WHERE m.event_date >= %s
          AND m.event_date <= %s
          AND m.event_status NOT IN ('Cancelled', 'Postponed', 'Walkover', 'Finished')
          AND m.is_live IS NOT TRUE
          AND m.is_doubles IS NOT TRUE
          -- Must have ratings for at least one player to be worth checking
          AND (pr1.rtt_score IS NOT NULL OR pr2.rtt_score IS NOT NULL)
        ORDER BY m.event_date, m.event_time NULLS LAST
        """,
        (today, cutoff),
    )

    results = []
    for m in rows:
        surface = m.get("surface_name") or ""

        # Build per-player rating dicts keyed by column name
        p1_ratings = {
            "clay_rating":       m.get("p1_clay"),
            "hard_rating":       m.get("p1_hard"),
            "grass_rating":      m.get("p1_grass"),
            "indoor_rating":     m.get("p1_indoor"),
            "serve_rating":      m.get("p1_serve"),
            "return_rating":     m.get("p1_return"),
            "pressure_rating":   m.get("p1_pressure"),
            "consistency_score": m.get("p1_consistency"),
            "form_score":        m.get("p1_form"),
            "big_match_rating":  m.get("p1_bigmatch"),
            "vs_top10_rating":   m.get("p1_vstop10"),
        }
        p2_ratings = {
            "clay_rating":       m.get("p2_clay"),
            "hard_rating":       m.get("p2_hard"),
            "grass_rating":      m.get("p2_grass"),
            "indoor_rating":     m.get("p2_indoor"),
            "serve_rating":      m.get("p2_serve"),
            "return_rating":     m.get("p2_return"),
            "pressure_rating":   m.get("p2_pressure"),
            "consistency_score": m.get("p2_consistency"),
            "form_score":        m.get("p2_form"),
            "big_match_rating":  m.get("p2_bigmatch"),
            "vs_top10_rating":   m.get("p2_vstop10"),
        }

        event_type = (m.get("event_type_name") or "").lower()
        is_big_match = any(x in event_type for x in ("grand slam", "masters", "atp 1000", "wta 1000"))

        conflicts = _find_conflicts(
            p1_ratings, p2_ratings,
            surface,
            "Masters" if is_big_match else "",
        )

        if len(conflicts) < min_conflicts:
            continue

        total_strength = sum(c["strength"] for c in conflicts)

        p1_prob = float(m["prob_first_player"])  if m.get("prob_first_player")  else None
        p2_prob = float(m["prob_second_player"]) if m.get("prob_second_player") else None
        impl_p1 = float(m["impl_p1"])            if m.get("impl_p1")            else None
        impl_p2 = float(m["impl_p2"])            if m.get("impl_p2")            else None

        e_p1 = _edge(p1_prob, impl_p1)
        e_p2 = _edge(p2_prob, impl_p2)

        # Build SEO slug
        d   = str(m["event_date"])[:10] if m.get("event_date") else ""
        trn = _slug(m.get("tournament_name") or "")
        n1  = _slug(m.get("p1_name") or "player")
        n2  = _slug(m.get("p2_name") or "player")
        slug = f"{d}-{trn}-{n1}-vs-{n2}" if d else f"{trn}-{n1}-vs-{n2}"

        results.append({
            "match_id":      m["id"],
            "match_url":     f"/match/{m['id']}/{slug}",
            "tournament":    m.get("tournament_name"),
            "surface":       surface,
            "round":         m.get("tournament_round"),
            "event_date":    d,
            "event_time":    str(m["event_time"])[:5] if m.get("event_time") else None,
            "first_player": {
                "id":           m["first_player_id"],
                "name":         m.get("p1_name"),
                "country_code": m.get("p1_country"),
                "rtt_score":    float(m["p1_rtt"]) if m.get("p1_rtt") else None,
                "win_prob":     round(p1_prob * 100, 1) if p1_prob else None,
                "edge":         e_p1,
            },
            "second_player": {
                "id":           m["second_player_id"],
                "name":         m.get("p2_name"),
                "country_code": m.get("p2_country"),
                "rtt_score":    float(m["p2_rtt"]) if m.get("p2_rtt") else None,
                "win_prob":     round(p2_prob * 100, 1) if p2_prob else None,
                "edge":         e_p2,
            },
            "conflicts":       conflicts,
            "conflict_count":  len(conflicts),
            "total_strength":  total_strength,
        })

    # Sort by total conflict strength (strongest first)
    results.sort(key=lambda r: r["total_strength"], reverse=True)

    return {
        "count":     len(results),
        "conflicts": results,
    }
