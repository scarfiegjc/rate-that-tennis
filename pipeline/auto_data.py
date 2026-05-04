#!/usr/bin/env python3
"""
ratethat.tennis — auto_data.py

Standalone predictions + ratings engine.
Uses ONLY psycopg2 + Python stdlib (math, datetime, collections).
No pandas, numpy, scikit-learn, xgboost, or lightgbm required.

Two public entry points:
    run_predictions()  — compute Elo win probabilities for upcoming matches
                         and write to model_predictions table
    run_ratings()      — compute simplified player ratings from match history
                         and write to player_ratings + player_ratings_history
"""

import os
import math
import logging
import sys
from datetime import date, timedelta
from collections import defaultdict

import psycopg2
import psycopg2.extras

log = logging.getLogger("auto_data")

# ─────────────────────────────────────────────────────────────────────────────
# DB CONNECTION
# ─────────────────────────────────────────────────────────────────────────────

def _get_conn():
    url = os.environ.get("DATABASE_URL") or os.environ.get("DATABASE_PUBLIC_URL")
    if not url:
        raise RuntimeError("DATABASE_URL not set")
    return psycopg2.connect(url, cursor_factory=psycopg2.extras.RealDictCursor)


# ─────────────────────────────────────────────────────────────────────────────
# ELO ENGINE
# Builds surface-specific Elo ratings from sa_matches (Sackmann history)
# AND from production matches table.
# Only processes matches from the last 10 years to keep startup time reasonable.
# ─────────────────────────────────────────────────────────────────────────────

# Tournament-level baseline Elo for players with zero match history.
# If we've seen a player in a Grand Slam or Masters, they're clearly not a beginner.
TOURNEY_LEVEL_ELO = {
    "grand slam":    1650,
    "grandslam":     1650,
    "masters":       1620,
    "masters 1000":  1620,
    "atp 500":       1580,
    "wta 500":       1580,
    "atp 250":       1550,
    "wta 250":       1550,
    "challenger":    1520,
    "itf":           1490,
    "itf men":       1490,
    "itf women":     1490,
}

def _tourney_level_elo(event_type_name: str) -> float:
    """Return a baseline Elo given a tournament type name."""
    key = (event_type_name or "").lower().strip()
    for pattern, val in TOURNEY_LEVEL_ELO.items():
        if pattern in key:
            return val
    return ELO_BASE

ELO_K      = 32    # K-factor
ELO_BASE   = 1500  # starting rating for all players

SURFACE_MAP = {
    "clay":  "Clay",
    "hard":  "Hard",
    "grass": "Grass",
    "carpet":"Carpet",
}


def _elo_expected(r_a, r_b):
    return 1.0 / (1.0 + 10 ** ((r_b - r_a) / 400.0))


def _build_elo_from_history(conn, surface_filter=None, years_back=10):
    """
    Read sa_matches and compute current Elo ratings per player.
    Returns dict: player_name (lowercase) → elo_rating (float)
    If surface_filter is given (e.g. "Hard"), only that surface is used.
    """
    cutoff = (date.today() - timedelta(days=years_back * 365)).strftime("%Y-%m-%d")

    surface_clause = ""
    params = [cutoff]
    if surface_filter:
        surface_clause = "AND LOWER(surface) = LOWER(%s)"
        params.append(surface_filter)

    sql = f"""
        SELECT
            sp_w.full_name AS winner_name,
            sp_l.full_name AS loser_name,
            sm.tourney_date,
            sm.surface
        FROM sa_matches sm
        JOIN sa_players sp_w ON sp_w.player_id = sm.winner_id
        JOIN sa_players sp_l ON sp_l.player_id = sm.loser_id
        WHERE sm.tourney_date >= %s
          {surface_clause}
          AND sm.winner_id IS NOT NULL
          AND sm.loser_id  IS NOT NULL
        ORDER BY sm.tourney_date ASC
    """

    elo = defaultdict(lambda: ELO_BASE)

    with conn.cursor() as cur:
        cur.execute(sql, params)
        rows = cur.fetchall()

    for row in rows:
        w = (row["winner_name"] or "").strip().lower()
        l = (row["loser_name"] or "").strip().lower()
        if not w or not l or w == l:
            continue

        r_w = elo[w]
        r_l = elo[l]
        e_w = _elo_expected(r_w, r_l)
        e_l = 1.0 - e_w

        elo[w] = r_w + ELO_K * (1.0 - e_w)
        elo[l] = r_l + ELO_K * (0.0 - e_l)

    return dict(elo)


def _build_elo_from_production(conn, existing_elo: dict) -> dict:
    """
    Update Elo dict using production matches table.
    Works by player_id so it covers everyone in our DB regardless of Sackmann coverage.
    Returns dict: player_id (int) → elo_rating (float)
    Also returns player_id → name mapping for merging with name-keyed Sackmann dict.
    """
    cutoff = (date.today() - timedelta(days=5 * 365)).strftime("%Y-%m-%d")

    with conn.cursor() as cur:
        cur.execute("""
            SELECT
                m.id,
                m.first_player_id,
                m.second_player_id,
                m.winner,
                m.event_date,
                s.name AS surface_name,
                COALESCE(p1.full_name, p1.name) AS p1_name,
                COALESCE(p2.full_name, p2.name) AS p2_name
            FROM matches m
            LEFT JOIN tournaments t  ON t.id = m.tournament_id
            LEFT JOIN surfaces s     ON s.id = t.surface_id
            LEFT JOIN players p1     ON p1.id = m.first_player_id
            LEFT JOIN players p2     ON p2.id = m.second_player_id
            WHERE m.event_date >= %s
              AND m.winner IN ('First Player', 'Second Player')
              AND m.first_player_id IS NOT NULL
              AND m.second_player_id IS NOT NULL
              AND (m.is_doubles IS NULL OR m.is_doubles = FALSE)
            ORDER BY m.event_date ASC
        """, (cutoff,))
        rows = cur.fetchall()

    # Build id-keyed Elo starting from existing name-keyed values where possible
    id_elo = defaultdict(lambda: ELO_BASE)
    id_to_name = {}

    for row in rows:
        p1_id = row["first_player_id"]
        p2_id = row["second_player_id"]
        # Use full_name if set, fall back to the short name stored in p1_name/p2_name
        p1_name = _name_key(row["p1_name"] or "")
        p2_name = _name_key(row["p2_name"] or "")

        # Seed from Sackmann Elo if available
        if p1_id not in id_to_name:
            id_to_name[p1_id] = p1_name
            if p1_name in existing_elo:
                id_elo[p1_id] = existing_elo[p1_name]
        if p2_id not in id_to_name:
            id_to_name[p2_id] = p2_name
            if p2_name in existing_elo:
                id_elo[p2_id] = existing_elo[p2_name]

        r1 = id_elo[p1_id]
        r2 = id_elo[p2_id]
        e1 = _elo_expected(r1, r2)
        e2 = 1.0 - e1

        if row["winner"] == "First Player":
            id_elo[p1_id] = r1 + ELO_K * (1.0 - e1)
            id_elo[p2_id] = r2 + ELO_K * (0.0 - e2)
        else:
            id_elo[p1_id] = r1 + ELO_K * (0.0 - e1)
            id_elo[p2_id] = r2 + ELO_K * (1.0 - e2)

    log.info(f"auto_data: production Elo built for {len(id_elo)} player IDs from {len(rows)} matches")
    return dict(id_elo), id_to_name


def _elo_win_prob(elo_a, elo_b):
    """P(a wins) given Elo ratings."""
    return _elo_expected(elo_a, elo_b)


def _name_key(name: str) -> str:
    return (name or "").strip().lower()


# ─────────────────────────────────────────────────────────────────────────────
# PREDICTIONS
# ─────────────────────────────────────────────────────────────────────────────

def run_predictions():
    """
    Compute Elo win probabilities for all upcoming matches (next 7 days).
    Writes results to model_predictions (upsert on match_id).
    """
    log.info("auto_data: building Elo from history...")
    conn = _get_conn()
    try:
        # Build overall + surface-specific Elo dicts
        elo_overall = _build_elo_from_history(conn)
        elo_by_surface = {}
        for surf in ("Clay", "Hard", "Grass", "Carpet"):
            elo_by_surface[surf.lower()] = _build_elo_from_history(conn, surface_filter=surf)

        log.info(f"auto_data: Elo built for {len(elo_overall)} players")

        # Fetch upcoming matches (next 7 days, singles only)
        today     = date.today()
        end_date  = today + timedelta(days=7)

        # Also build production-match Elo keyed by player_id for better coverage
        prod_elo_pred, _ = _build_elo_from_production(conn, elo_overall)
        prod_surf_elo: dict = {}
        for surf_key in ("clay", "hard", "grass", "carpet"):
            prod_surf_elo[surf_key], _ = _build_elo_from_production(
                conn, elo_by_surface.get(surf_key, {})
            )

        with conn.cursor() as cur:
            cur.execute("""
                SELECT
                    m.id          AS match_id,
                    m.first_player_id,
                    m.second_player_id,
                    COALESCE(p1.full_name, p1.name) AS p1_name,
                    COALESCE(p2.full_name, p2.name) AS p2_name,
                    m.event_date,
                    s.name        AS surface_name
                FROM matches m
                LEFT JOIN tournaments t ON t.id = m.tournament_id
                LEFT JOIN surfaces s    ON s.id = t.surface_id
                JOIN players p1 ON p1.id = m.first_player_id
                JOIN players p2 ON p2.id = m.second_player_id
                WHERE m.event_date BETWEEN %s AND %s
                  AND m.event_status NOT IN ('Finished', 'Cancelled', 'Postponed', 'Walkover')
                  AND (m.is_doubles IS NULL OR m.is_doubles = FALSE)
                  AND m.first_player_id IS NOT NULL
                  AND m.second_player_id IS NOT NULL
                ORDER BY m.event_date ASC
            """, (today, end_date))
            matches = cur.fetchall()

        log.info(f"auto_data: found {len(matches)} upcoming matches to predict")

        upserted = 0
        for m in matches:
            p1_id  = m["first_player_id"]
            p2_id  = m["second_player_id"]
            p1_key = _name_key(m["p1_name"] or "")
            p2_key = _name_key(m["p2_name"] or "")
            surf   = (m["surface_name"] or "").strip().lower()

            # Use surface-specific Elo — prefer production (id-keyed), fall back to Sackmann (name-keyed)
            surf_elo      = elo_by_surface.get(surf, {})
            prod_s_elo    = prod_surf_elo.get(surf, {})

            elo1 = (prod_s_elo.get(p1_id) or prod_elo_pred.get(p1_id)
                    or surf_elo.get(p1_key) or elo_overall.get(p1_key, ELO_BASE))
            elo2 = (prod_s_elo.get(p2_id) or prod_elo_pred.get(p2_id)
                    or surf_elo.get(p2_key) or elo_overall.get(p2_key, ELO_BASE))

            prob1 = round(_elo_win_prob(elo1, elo2), 4)
            prob2 = round(1.0 - prob1, 4)

            # Confidence: high if Elo diff > 150, medium if > 50, else low
            diff = abs(elo1 - elo2)
            if diff > 150:
                confidence = "high"
            elif diff > 50:
                confidence = "medium"
            else:
                confidence = "low"

            # Simple narrative
            fav    = m["p1_name"] if prob1 >= 0.5 else m["p2_name"]
            fav_p  = max(prob1, prob2)
            narrative = (
                f"{fav} is the Elo-based favourite at {fav_p:.0%} "
                f"on {m['surface_name'] or 'this surface'}."
            )

            with conn.cursor() as cur:
                cur.execute("""
                    INSERT INTO model_predictions
                        (match_id, prob_first_player, prob_second_player,
                         confidence, narrative, model_version, predicted_at)
                    VALUES (%s, %s, %s, %s, %s, %s, NOW())
                    ON CONFLICT (match_id) DO UPDATE SET
                        prob_first_player  = EXCLUDED.prob_first_player,
                        prob_second_player = EXCLUDED.prob_second_player,
                        confidence         = EXCLUDED.confidence,
                        narrative          = EXCLUDED.narrative,
                        model_version      = EXCLUDED.model_version,
                        predicted_at       = NOW()
                """, (
                    m["match_id"], prob1, prob2,
                    confidence, narrative, "elo-v1"
                ))
            conn.commit()
            upserted += 1

        log.info(f"auto_data: predictions written for {upserted} matches")

    except Exception as e:
        log.error(f"auto_data run_predictions error: {e}")
        import traceback
        log.error(traceback.format_exc())
        try:
            conn.rollback()
        except Exception:
            pass
    finally:
        conn.close()


# ─────────────────────────────────────────────────────────────────────────────
# RATINGS
# Compute simplified 0-100 player ratings from match history and write to
# player_ratings + player_ratings_history.
#
# Strategy: for each player in the `players` table, look up their match
# history in sa_matches (by name match on sa_players.full_name) and compute:
#   - overall_rating  : derived from current Elo (log-scaled, normalised)
#   - rtt_score       : same as overall_rating
#   - surface ratings : from surface-specific Elo
#   - form_score      : win rate last 20 matches (quality-weighted by opponent Elo)
#   - serve_rating    : from sa_matches serve stats (ace rate, 1st-serve %, etc.)
#   - consistency_score: games won % across recent matches
#   - pressure_rating : tiebreak win %, deciding set win %
#   - momentum        : rising / stable / falling based on last 5 vs prior 5
# ─────────────────────────────────────────────────────────────────────────────

def _normalise_elo(elo_val: float, min_elo: float, max_elo: float) -> float:
    """Map Elo value to 0-100 scale."""
    if max_elo <= min_elo:
        return 50.0
    val = (elo_val - min_elo) / (max_elo - min_elo) * 100.0
    return max(5.0, min(95.0, round(val, 2)))


def _rank_to_rating(rank) -> float:
    """Fallback: derive approximate rating from ATP ranking (log scale)."""
    if rank is None or rank <= 0:
        return 40.0
    return max(10.0, min(95.0, round(110 - 15 * math.log10(max(1, rank)), 2)))


def run_ratings():
    """
    Compute simplified player ratings and write to player_ratings +
    player_ratings_history tables. Safe to run daily; uses ON CONFLICT upsert.
    """
    log.info("auto_data: computing player ratings...")
    conn = _get_conn()
    try:
        # 1. Build Elo dicts
        log.info("auto_data: building Elo ratings for normalisation...")
        elo_overall = _build_elo_from_history(conn, years_back=5)
        elo_clay    = _build_elo_from_history(conn, surface_filter="Clay",   years_back=5)
        elo_hard    = _build_elo_from_history(conn, surface_filter="Hard",   years_back=5)
        elo_grass   = _build_elo_from_history(conn, surface_filter="Grass",  years_back=5)
        elo_carpet  = _build_elo_from_history(conn, surface_filter="Carpet", years_back=5)

        # 2. Build production-match Elo first so we can fall back to it if
        #    Sackmann data is absent (e.g. fresh Railway deploy, no sa_matches).
        log.info("auto_data: building Elo from production matches...")
        prod_elo, prod_id_to_name = _build_elo_from_production(conn, elo_overall)

        # Compute min/max for normalisation — prefer Sackmann range (wider),
        # fall back to production Elo range if sa_matches is empty.
        all_elos = list(elo_overall.values()) or list(prod_elo.values())
        if not all_elos:
            log.warning("auto_data: no Elo data at all — aborting ratings")
            return
        min_elo = min(all_elos)
        max_elo = max(all_elos)
        log.info(f"auto_data: Elo range {min_elo:.0f}–{max_elo:.0f} across {len(all_elos)} players")

        def _surf_min_max(elo_dict):
            vals = list(elo_dict.values()) or [ELO_BASE]
            return min(vals), max(vals)

        clay_min,   clay_max   = _surf_min_max(elo_clay)
        hard_min,   hard_max   = _surf_min_max(elo_hard)
        grass_min,  grass_max  = _surf_min_max(elo_grass)
        carpet_min, carpet_max = _surf_min_max(elo_carpet)

        # Build last-name-keyed Elo lookups for abbreviated production names
        # e.g. "a. zverev" won't match dict key "alexander zverev", but "zverev" will
        # match after we build a last-name-keyed version.
        def _build_last_dict(elo_dict: dict) -> dict:
            """Max Elo per last-name token — fallback for abbreviated player names."""
            d: dict = {}
            for full, val in elo_dict.items():
                last_k = full.split()[-1] if full else None
                if last_k and val > d.get(last_k, 0):
                    d[last_k] = val
            return d

        elo_overall_by_last = _build_last_dict(elo_overall)
        elo_clay_by_last    = _build_last_dict(elo_clay)
        elo_hard_by_last    = _build_last_dict(elo_hard)
        elo_grass_by_last   = _build_last_dict(elo_grass)
        elo_carpet_by_last  = _build_last_dict(elo_carpet)

        # (prod_elo already built above)

        # 3. Fetch all players + their most recent tournament type for fallback
        with conn.cursor() as cur:
            cur.execute("""
                SELECT
                    p.id,
                    COALESCE(p.full_name, p.name) AS full_name,
                    et.name AS event_type_name
                FROM players p
                LEFT JOIN LATERAL (
                    SELECT et2.name
                    FROM matches m2
                    JOIN event_types et2 ON et2.id = m2.event_type_id
                    WHERE (m2.first_player_id = p.id OR m2.second_player_id = p.id)
                      AND m2.event_date >= CURRENT_DATE - INTERVAL '2 years'
                    ORDER BY m2.event_date DESC
                    LIMIT 1
                ) et ON TRUE
                WHERE p.full_name IS NOT NULL OR p.name IS NOT NULL
                ORDER BY p.id
            """)
            players = cur.fetchall()

        log.info(f"auto_data: rating {len(players)} players...")
        today_str = date.today().isoformat()
        updated = 0

        for pl in players:
          try:
            pid  = pl["id"]
            name = pl["full_name"].strip()
            key  = name.lower()
            last = name.split()[-1].lower()   # e.g. "A. Zverev" → "zverev"

            def _best_elo(elo_dict, by_last_dict, fallback=ELO_BASE):
                # Try exact key first ("alexander zverev"), then last-name token ("zverev")
                return (elo_dict.get(key)
                        or elo_dict.get(last)
                        or by_last_dict.get(last)
                        or fallback)

            # Priority: 1) production match Elo (most current)
            #           2) Sackmann Elo (historical depth)
            #           3) tournament-level heuristic
            #           4) ELO_BASE
            prod_val = prod_elo.get(pid)
            sack_val = (elo_overall.get(key)
                        or elo_overall.get(last)
                        or elo_overall_by_last.get(last))

            if prod_val and prod_val != ELO_BASE:
                e_overall = prod_val
            elif sack_val:
                e_overall = sack_val
            else:
                # Fallback: derive from most recent tournament type seen
                e_overall = _tourney_level_elo(pl.get("event_type_name") or "")

            e_clay    = _best_elo(elo_clay,   elo_clay_by_last)
            e_hard    = _best_elo(elo_hard,   elo_hard_by_last)
            e_grass   = _best_elo(elo_grass,  elo_grass_by_last)
            e_carpet  = _best_elo(elo_carpet, elo_carpet_by_last)

            # For surface Elos, also try production if Sackmann has no data
            if e_clay == ELO_BASE and prod_val:
                e_clay = prod_val
            if e_hard == ELO_BASE and prod_val:
                e_hard = prod_val
            if e_grass == ELO_BASE and prod_val:
                e_grass = prod_val
            if e_carpet == ELO_BASE and prod_val:
                e_carpet = prod_val

            overall   = _normalise_elo(e_overall, min_elo, max_elo)
            clay_r    = _normalise_elo(e_clay,   clay_min,   clay_max)
            hard_r    = _normalise_elo(e_hard,   hard_min,   hard_max)
            grass_r   = _normalise_elo(e_grass,  grass_min,  grass_max)
            indoor_r  = _normalise_elo(e_carpet, carpet_min, carpet_max)

            # ── Serve, form, consistency from sa_matches ──────────────────────
            # Look up sa_player_id by name.
            # Try exact full_name match first ("alexander zverev"),
            # then last-name-only ("zverev") for abbreviated production names ("a. zverev").
            # Also try initial+lastname ("a%" + "zverev") to disambiguate siblings.
            sp_row = None
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT player_id FROM sa_players
                    WHERE LOWER(full_name) = %s
                    LIMIT 1
                """, (key,))
                sp_row = cur.fetchone()

            if not sp_row and last:
                # Try initial+lastname e.g. name="A. Zverev" → initial="a", last="zverev"
                tokens = key.split()
                initial = tokens[0].rstrip(".") if tokens else None
                if initial and len(initial) == 1:
                    with conn.cursor() as cur:
                        cur.execute("""
                            SELECT player_id FROM sa_players
                            WHERE LOWER(name_last) = %s
                              AND LOWER(name_first) LIKE %s
                            LIMIT 1
                        """, (last, initial + "%"))
                        sp_row = cur.fetchone()

            if not sp_row and last:
                # Final fallback: last name only
                with conn.cursor() as cur:
                    cur.execute("""
                        SELECT player_id FROM sa_players
                        WHERE LOWER(name_last) = %s
                        LIMIT 1
                    """, (last,))
                    sp_row = cur.fetchone()

            sa_pid = sp_row["player_id"] if sp_row else None

            serve_rating        = None
            form_score          = None
            consistency_score   = None
            pressure_rating     = None
            momentum            = "stable"
            form_wins           = None
            form_losses         = None

            if sa_pid:
                # Serve stats from recent matches (winner perspective)
                with conn.cursor() as cur:
                    cur.execute("""
                        SELECT
                            AVG(CASE WHEN w_svpt > 0 THEN w_ace::float / w_svpt ELSE NULL END)       AS ace_rate,
                            AVG(CASE WHEN w_svpt > 0 THEN w_1st_in::float / w_svpt ELSE NULL END)   AS first_in_rate,
                            AVG(CASE WHEN w_1st_in > 0 THEN w_1st_won::float / w_1st_in ELSE NULL END) AS first_won_rate,
                            AVG(CASE WHEN w_svpt > 0 THEN w_bp_saved::float / NULLIF(w_bp_faced,0) ELSE NULL END) AS bp_saved_rate,
                            COUNT(*) AS n_matches
                        FROM sa_matches
                        WHERE winner_id = %s
                          AND tourney_date >= CURRENT_DATE - INTERVAL '2 years'
                          AND w_svpt > 0
                    """, (sa_pid,))
                    serve_row = cur.fetchone()

                if serve_row and serve_row["n_matches"] and serve_row["n_matches"] > 5:
                    ace_r  = serve_row["ace_rate"]   or 0.05
                    fst_r  = serve_row["first_in_rate"] or 0.55
                    fst_w  = serve_row["first_won_rate"] or 0.68
                    bp_s   = serve_row["bp_saved_rate"] or 0.60
                    # Combine into 0-100 serve rating (roughly normalised)
                    raw_serve = (
                        (ace_r / 0.15)     * 20 +   # 15% ace rate = 20/20
                        (fst_r / 0.70)     * 25 +   # 70% 1st-in   = 25/25
                        (fst_w / 0.80)     * 30 +   # 80% 1st-won  = 30/30
                        (bp_s  / 0.75)     * 25     # 75% bp saved = 25/25
                    )
                    serve_rating = max(10.0, min(95.0, round(raw_serve, 2)))

                # Form: last 20 matches (wins/losses), quality-weighted by opponent Elo
                with conn.cursor() as cur:
                    cur.execute("""
                        SELECT 'win' AS result, loser_id AS opp_id, tourney_date
                        FROM sa_matches
                        WHERE winner_id = %s
                          AND tourney_date >= CURRENT_DATE - INTERVAL '2 years'
                        UNION ALL
                        SELECT 'loss' AS result, winner_id AS opp_id, tourney_date
                        FROM sa_matches
                        WHERE loser_id = %s
                          AND tourney_date >= CURRENT_DATE - INTERVAL '2 years'
                        ORDER BY tourney_date DESC
                        LIMIT 20
                    """, (sa_pid, sa_pid))
                    form_rows = cur.fetchall()

                if form_rows:
                    form_wins   = sum(1 for r in form_rows if r["result"] == "win")
                    form_losses = len(form_rows) - form_wins
                    form_score  = round((form_wins / len(form_rows)) * 100, 2)

                    # Momentum: compare last 5 vs prior 5
                    if len(form_rows) >= 10:
                        recent5 = sum(1 for r in form_rows[:5]  if r["result"] == "win")
                        prior5  = sum(1 for r in form_rows[5:10] if r["result"] == "win")
                        if recent5 > prior5 + 1:
                            momentum = "rising"
                        elif recent5 < prior5 - 1:
                            momentum = "falling"
                        else:
                            momentum = "stable"

                # Consistency: games won % (using available w_sv_gms vs l_sv_gms proxy)
                with conn.cursor() as cur:
                    cur.execute("""
                        SELECT
                            AVG(CASE WHEN w_sv_gms > 0 OR l_sv_gms > 0
                                THEN w_sv_gms::float / NULLIF(w_sv_gms + l_sv_gms, 0)
                                ELSE NULL END) AS games_pct
                        FROM sa_matches
                        WHERE winner_id = %s
                          AND tourney_date >= CURRENT_DATE - INTERVAL '2 years'
                    """, (sa_pid,))
                    cons_row = cur.fetchone()

                if cons_row and cons_row["games_pct"]:
                    # 60%+ games pct is excellent → scale 50%-70% → 0-100
                    gpct = cons_row["games_pct"]
                    consistency_score = max(10.0, min(95.0, round((gpct - 0.45) / 0.30 * 100, 2)))

                # Pressure: tiebreak win rate (rough proxy: winning matches in 3 sets)
                with conn.cursor() as cur:
                    cur.execute("""
                        SELECT
                            COUNT(*) FILTER (WHERE winner_id = %s) AS wins_3sets,
                            COUNT(*) AS total_3set_matches
                        FROM sa_matches
                        WHERE (winner_id = %s OR loser_id = %s)
                          AND best_of = 3
                          AND tourney_date >= CURRENT_DATE - INTERVAL '2 years'
                    """, (sa_pid, sa_pid, sa_pid))
                    press_row = cur.fetchone()

                if press_row and press_row["total_3set_matches"] and press_row["total_3set_matches"] > 10:
                    win_rate = press_row["wins_3sets"] / press_row["total_3set_matches"]
                    pressure_rating = max(10.0, min(95.0, round(win_rate * 100, 2)))

            # ── Fallback: rank-based overall if still at default ──────────────
            # (only hits if no production matches AND no Sackmann AND no tournament type)
            if e_overall == ELO_BASE:
                with conn.cursor() as cur:
                    cur.execute("""
                        SELECT COALESCE(
                            MIN(sm.winner_rank) FILTER (WHERE sp.player_id = sm.winner_id),
                            MIN(sm.loser_rank)  FILTER (WHERE sp.player_id = sm.loser_id)
                        ) AS recent_rank
                        FROM sa_players sp
                        JOIN sa_matches sm ON (sm.winner_id = sp.player_id OR sm.loser_id = sp.player_id)
                        WHERE LOWER(sp.full_name) LIKE %s
                          AND sm.tourney_date >= CURRENT_DATE - INTERVAL '2 years'
                    """, (f"%{last}%",))
                    rank_row = cur.fetchone()

                if rank_row and rank_row["recent_rank"]:
                    overall = _rank_to_rating(rank_row["recent_rank"])

            # ── rtt_score: weighted blend ──────────────────────────────────────
            surf_avg = (clay_r + hard_r + grass_r) / 3.0
            rtt = round(overall * 0.6 + surf_avg * 0.4, 2)

            # ── Write to player_ratings ────────────────────────────────────────
            with conn.cursor() as cur:
                cur.execute("""
                    INSERT INTO player_ratings
                        (player_id, overall_rating, rtt_score,
                         clay_rating, hard_rating, grass_rating, indoor_rating,
                         serve_rating, form_score, consistency_score, pressure_rating,
                         momentum, form_wins, form_losses,
                         model_version, calculated_at, updated_at)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                            %s, NOW(), NOW())
                    ON CONFLICT (player_id) DO UPDATE SET
                        overall_rating    = EXCLUDED.overall_rating,
                        rtt_score         = EXCLUDED.rtt_score,
                        clay_rating       = EXCLUDED.clay_rating,
                        hard_rating       = EXCLUDED.hard_rating,
                        grass_rating      = EXCLUDED.grass_rating,
                        indoor_rating     = EXCLUDED.indoor_rating,
                        serve_rating      = EXCLUDED.serve_rating,
                        form_score        = EXCLUDED.form_score,
                        consistency_score = EXCLUDED.consistency_score,
                        pressure_rating   = EXCLUDED.pressure_rating,
                        momentum          = EXCLUDED.momentum,
                        form_wins         = EXCLUDED.form_wins,
                        form_losses       = EXCLUDED.form_losses,
                        model_version     = EXCLUDED.model_version,
                        updated_at        = NOW()
                """, (
                    pid, overall, rtt,
                    clay_r, hard_r, grass_r, indoor_r,
                    serve_rating, form_score, consistency_score, pressure_rating,
                    momentum, form_wins, form_losses,
                    "auto-elo-v1"
                ))

            # ── Write to player_ratings_history ───────────────────────────────
            with conn.cursor() as cur:
                cur.execute("""
                    INSERT INTO player_ratings_history
                        (player_id, rated_at,
                         rtt_score, clay_rating, hard_rating, grass_rating, indoor_rating,
                         serve_rating, form_rating, consistency_rating, pressure_rating)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (player_id, rated_at) DO UPDATE SET
                        rtt_score          = EXCLUDED.rtt_score,
                        clay_rating        = EXCLUDED.clay_rating,
                        hard_rating        = EXCLUDED.hard_rating,
                        grass_rating       = EXCLUDED.grass_rating,
                        indoor_rating      = EXCLUDED.indoor_rating,
                        serve_rating       = EXCLUDED.serve_rating,
                        form_rating        = EXCLUDED.form_rating,
                        consistency_rating = EXCLUDED.consistency_rating,
                        pressure_rating    = EXCLUDED.pressure_rating
                """, (
                    pid, today_str,
                    rtt, clay_r, hard_r, grass_r, indoor_r,
                    serve_rating, form_score, consistency_score, pressure_rating
                ))

            conn.commit()
            updated += 1

          except Exception as player_err:
            log.warning(
                f"auto_data: skipping player id={pl.get('id')} "
                f"name={pl.get('full_name')!r}: {player_err}"
            )
            try:
                conn.rollback()
            except Exception:
                pass

        log.info(f"auto_data: ratings written for {updated} players")

    except Exception as e:
        log.error(f"auto_data run_ratings error: {e}")
        import traceback
        log.error(traceback.format_exc())
        try:
            conn.rollback()
        except Exception:
            pass
    finally:
        conn.close()


# ─────────────────────────────────────────────────────────────────────────────
# CLI entry point (for testing)
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s [%(levelname)s] %(message)s",
                        handlers=[logging.StreamHandler(sys.stdout)])

    parser = argparse.ArgumentParser(description="auto_data standalone runner")
    parser.add_argument("job", choices=["predictions", "ratings", "all"],
                        help="Job to run")
    args = parser.parse_args()

    if args.job in ("predictions", "all"):
        run_predictions()
    if args.job in ("ratings", "all"):
        run_ratings()
