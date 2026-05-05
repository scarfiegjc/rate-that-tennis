"""
ratethat.tennis API — Player routes.

GET /players/{id}
GET /players/{id}/form
GET /players/{p1_id}/h2h/{p2_id}
"""
from fastapi import APIRouter, HTTPException, Query
from typing import Optional

from api.db import query, query_one

router = APIRouter(prefix="/players", tags=["players"])


# ─────────────────────────────────────────────────────────────────────────────
# GET /players  — Player Database (list, sortable, filterable)
# ─────────────────────────────────────────────────────────────────────────────

_SORT_KEY_MAP = {
    "rtt":       "pr.rtt_score",
    "form":      "pr.form_score",
    "momentum":  "CASE pr.momentum WHEN 'rising' THEN 2 WHEN 'stable' THEN 1 WHEN 'falling' THEN 0 ELSE -1 END",
    "clay":      "pr.clay_rating",
    "hard":      "pr.hard_rating",
    "grass":     "pr.grass_rating",
    "indoor":    "pr.indoor_rating",
}

@router.get("")
def players_database(
    sort:    str           = Query(default="rtt", description="rtt|form|momentum|clay|hard|grass|indoor"),
    country: Optional[str] = Query(default=None, description="ISO country code filter, e.g. GBR"),
    search:  Optional[str] = Query(default=None, description="Substring of player name"),
    active_only: bool      = Query(default=True, description="Only players with a match in the last 6 months"),
    limit:   int           = Query(default=300, ge=10, le=2000),
):
    """
    Returns a flat list of players for the Player Database page. Each row carries
    the data the frontend needs to render a 2-column men/women layout with
    sort/filter/search.
    """
    sort_key = sort.lower()
    sort_sql = _SORT_KEY_MAP.get(sort_key, "pr.rtt_score")

    where = ["1=1"]
    params: list = []

    if country:
        where.append("p.country_code = %s")
        params.append(country.upper())

    if search:
        where.append("(p.name ILIKE %s OR p.full_name ILIKE %s)")
        params.extend([f"%{search}%", f"%{search}%"])

    if active_only:
        where.append(
            "EXISTS (SELECT 1 FROM matches m2 "
            "WHERE (m2.first_player_id = p.id OR m2.second_player_id = p.id) "
            "  AND m2.event_date >= CURRENT_DATE - INTERVAL '6 months' "
            "  AND m2.is_doubles = FALSE)"
        )

    sql = f"""
        WITH gender AS (
            SELECT
                m.first_player_id  AS player_id,
                MAX(et.gender)     AS gender
            FROM matches m
            JOIN event_types et ON et.id = m.event_type_id
            WHERE et.gender IN ('Men', 'Women')
              AND (et.is_doubles = FALSE OR et.is_doubles IS NULL)
              AND m.is_doubles = FALSE
              AND m.first_player_id IS NOT NULL
            GROUP BY m.first_player_id
            UNION ALL
            SELECT
                m.second_player_id AS player_id,
                MAX(et.gender)     AS gender
            FROM matches m
            JOIN event_types et ON et.id = m.event_type_id
            WHERE et.gender IN ('Men', 'Women')
              AND (et.is_doubles = FALSE OR et.is_doubles IS NULL)
              AND m.is_doubles = FALSE
              AND m.second_player_id IS NOT NULL
            GROUP BY m.second_player_id
        ),
        gender_pick AS (
            SELECT player_id,
                   MODE() WITHIN GROUP (ORDER BY gender) AS gender
            FROM gender
            GROUP BY player_id
        ),
        playing_today AS (
            SELECT DISTINCT player_id FROM (
                SELECT first_player_id  AS player_id FROM matches
                WHERE event_date BETWEEN CURRENT_DATE AND CURRENT_DATE + INTERVAL '2 days'
                  AND is_doubles = FALSE
                UNION
                SELECT second_player_id AS player_id FROM matches
                WHERE event_date BETWEEN CURRENT_DATE AND CURRENT_DATE + INTERVAL '2 days'
                  AND is_doubles = FALSE
            ) x
        ),
        rtt_30d AS (
            SELECT player_id,
                   (rtt_score - LAG(rtt_score) OVER (PARTITION BY player_id ORDER BY rated_at)) AS delta_30d,
                   ROW_NUMBER() OVER (PARTITION BY player_id ORDER BY rated_at DESC) AS rn
            FROM player_ratings_history
            WHERE rated_at >= CURRENT_DATE - INTERVAL '35 days'
        )
        SELECT
            p.id, p.name, p.full_name, p.country, p.country_code, p.hand,
            pr.rtt_score, pr.clay_rating, pr.hard_rating, pr.grass_rating, pr.indoor_rating,
            pr.form_score, pr.momentum,
            gp.gender,
            (pt.player_id IS NOT NULL) AS playing_today,
            COALESCE(r30.delta_30d, 0) AS rtt_delta_30d
        FROM players p
        LEFT JOIN player_ratings pr ON pr.player_id = p.id
        LEFT JOIN gender_pick gp    ON gp.player_id = p.id
        LEFT JOIN playing_today pt  ON pt.player_id = p.id
        LEFT JOIN rtt_30d r30       ON r30.player_id = p.id AND r30.rn = 1
        WHERE {' AND '.join(where)}
          AND pr.rtt_score IS NOT NULL
        ORDER BY {sort_sql} DESC NULLS LAST, pr.rtt_score DESC NULLS LAST
        LIMIT %s
    """
    params.append(limit)

    rows = query(sql, tuple(params))

    # Coerce numeric types
    out = []
    for r in rows:
        out.append({
            "id":            r["id"],
            "name":          r["name"],
            "full_name":     r["full_name"],
            "country":       r["country"],
            "country_code":  r["country_code"],
            "hand":          r["hand"],
            "gender":        "M" if r.get("gender") == "Men" else ("W" if r.get("gender") == "Women" else None),
            "rtt_score":     float(r["rtt_score"])    if r.get("rtt_score")    is not None else None,
            "clay_rating":   float(r["clay_rating"])  if r.get("clay_rating")  is not None else None,
            "hard_rating":   float(r["hard_rating"])  if r.get("hard_rating")  is not None else None,
            "grass_rating":  float(r["grass_rating"]) if r.get("grass_rating") is not None else None,
            "indoor_rating": float(r["indoor_rating"])if r.get("indoor_rating")is not None else None,
            "form_score":    float(r["form_score"])   if r.get("form_score")   is not None else None,
            "momentum":      r.get("momentum"),
            "playing_today": bool(r.get("playing_today")),
            "rtt_delta_30d": float(r["rtt_delta_30d"]) if r.get("rtt_delta_30d") is not None else 0.0,
        })

    # Counts for the page header
    men   = [p for p in out if p["gender"] == "M"]
    women = [p for p in out if p["gender"] == "W"]
    return {
        "sort":    sort_key,
        "country": country,
        "search":  search,
        "active_only": active_only,
        "summary": {
            "total":         len(out),
            "men":           len(men),
            "women":         len(women),
            "playing_today": sum(1 for p in out if p["playing_today"]),
        },
        "players": out,
    }


# ─────────────────────────────────────────────────────────────────────────────
# Helper: find Sackmann player IDs for an API player
# ─────────────────────────────────────────────────────────────────────────────

def _sa_ids_for(player_id: int) -> list[int]:
    """
    Return all sa_players.player_id values that correspond to our players.id.
    Matches by full_name (generated column: name_first || ' ' || name_last).
    Covers both Sackmann (ATP/WTA) and TML records.

    Production players are stored with abbreviated names like "A. Zverev" or "J. Sinner"
    (from api-tennis.com) while Sackmann stores full names "Alexander Zverev" / "Jannik Sinner".
    Multiple strategies are used to bridge this gap.
    """
    player = query_one(
        "SELECT name, full_name FROM players WHERE id = %s",
        (player_id,),
    )
    if not player:
        return []
    sa_ids: set[int] = set()

    for field in ("full_name", "name"):
        name = (player.get(field) or "").strip()
        if not name:
            continue

        # Strategy 1: substring match on generated full_name column
        rows = query(
            "SELECT player_id FROM sa_players WHERE full_name ILIKE %s LIMIT 10",
            (f"%{name}%",),
        )
        sa_ids.update(r["player_id"] for r in rows)

        tokens = name.split()
        last = tokens[-1] if tokens else None

        # Strategy 2: initial + last name (handles "A. Zverev" → name_first LIKE 'A%' AND name_last = 'Zverev')
        if last and len(last) > 2 and len(tokens) >= 2:
            first_token = tokens[0].rstrip(".")
            if len(first_token) == 1:
                rows2 = query(
                    """SELECT player_id FROM sa_players
                       WHERE LOWER(name_last) = LOWER(%s)
                         AND LOWER(name_first) LIKE LOWER(%s)
                       LIMIT 5""",
                    (last, first_token + "%"),
                )
                sa_ids.update(r["player_id"] for r in rows2)

        # Strategy 3: last name only (broadest fallback)
        if last and len(last) > 3:
            rows3 = query(
                "SELECT player_id FROM sa_players WHERE name_last ILIKE %s LIMIT 5",
                (last,),
            )
            sa_ids.update(r["player_id"] for r in rows3)

    return list(sa_ids)


# ─────────────────────────────────────────────────────────────────────────────
# Helper: fetch player ratings row
# ─────────────────────────────────────────────────────────────────────────────

def _get_ratings(player_id: int) -> dict | None:
    return query_one(
        """
        SELECT
            rtt_score, clay_rating, hard_rating, grass_rating, indoor_rating,
            serve_rating, return_rating, net_game_rating, pressure_rating,
            consistency_score AS consistency_rating, form_score AS form_rating,
            big_match_rating, vs_top10_rating, momentum
        FROM player_ratings
        WHERE player_id = %s
        """,
        (player_id,),
    )


# ─────────────────────────────────────────────────────────────────────────────
# GET /players/{id}
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/{player_id}")
def get_player(player_id: int):
    player = query_one(
        """
        SELECT id, name, full_name, country, country_code, birthday,
               hand, turned_pro, height_cm, logo_url, is_active
        FROM players
        WHERE id = %s
        """,
        (player_id,),
    )
    if not player:
        raise HTTPException(status_code=404, detail="Player not found")

    ratings = _get_ratings(player_id)

    # Recent form from main matches table
    # matches.winner is TEXT: "First Player" | "Second Player"
    recent = query(
        """
        SELECT
            m.id AS match_id,
            m.event_date,
            m.winner,
            m.first_player_id,
            CASE WHEN m.first_player_id = %s THEN p2.name
                 ELSE p1.name END AS opp_name
        FROM matches m
        JOIN players p1 ON p1.id = m.first_player_id
        JOIN players p2 ON p2.id = m.second_player_id
        WHERE (m.first_player_id = %s OR m.second_player_id = %s)
          AND m.event_status = 'Finished'
          AND m.event_date IS NOT NULL
        ORDER BY m.event_date DESC
        LIMIT 10
        """,
        (player_id, player_id, player_id),
    )

    def _match_won(r: dict) -> bool:
        return (r["winner"] == "First Player" and r["first_player_id"] == player_id) or \
               (r["winner"] == "Second Player" and r["first_player_id"] != player_id)

    wins = sum(1 for r in recent if _match_won(r))
    losses = len(recent) - wins
    last_10 = " ".join("W" if _match_won(r) else "L" for r in recent)

    return {
        "player": player,
        "ratings": ratings,
        "recent_form": {
            "wins": wins,
            "losses": losses,
            "last_10": last_10,
        },
    }


# ─────────────────────────────────────────────────────────────────────────────
# GET /players/{id}/form
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/{player_id}/form")
def get_player_form(
    player_id: int,
    surface: Optional[str] = Query(default="all", description="all|clay|hard|grass"),
    limit: int = Query(default=15, ge=1, le=50),
):
    # Player ratings history (daily snapshots — use for the chart overlay)
    history_rows = query(
        """
        SELECT rated_at AS date, form_rating AS performance_index,
               rtt_score, momentum, match_count
        FROM player_ratings_history
        WHERE player_id = %s
        ORDER BY rated_at DESC
        LIMIT %s
        """,
        (player_id, limit),
    )

    # Per-match form from Sackmann data (richer individual match context)
    sa_ids = _sa_ids_for(player_id)
    match_rows: list[dict] = []

    if sa_ids:
        surface_clause = ""
        extra_params: list = []
        if surface and surface.lower() != "all":
            surface_map = {
                "clay": "Clay", "hard": "Hard",
                "grass": "Grass", "indoor": "Indoor Hard",
            }
            surface_name = surface_map.get(surface.lower(), surface)
            surface_clause = "AND sm.surface ILIKE %s"
            extra_params.append(f"%{surface_name}%")

        # Build param list: first 4× sa_ids for CASE WHEN, then 2× for WHERE
        q_params = [sa_ids, sa_ids, sa_ids, sa_ids, sa_ids, sa_ids, *extra_params, limit]

        match_rows = query(
            f"""
            SELECT
                sm.id AS match_id,
                sm.tourney_date AS date,
                sm.tourney_name AS tournament,
                sm.surface,
                CASE WHEN sm.winner_id = ANY(%s) THEN sm.loser_name ELSE sm.winner_name END AS opponent_name,
                CASE WHEN sm.winner_id = ANY(%s) THEN sm.loser_rank  ELSE sm.winner_rank  END AS opponent_rank,
                (sm.winner_id = ANY(%s)) AS won,
                -- Performance index 0-100: opponent quality + score gap drive most of the spread
                -- Wins: 50 base + opponent bonus (up to +35 for top-10, down to -5 for >300)
                --       + score-gap bonus (up to +10 for dominant, -5 for scrappy)
                -- Losses: 50 base + opponent absorption (close losses to top players soften)
                --         + score-gap penalty (heavy losses hit harder)
                CASE
                    WHEN sm.winner_id = ANY(%s) THEN
                        50
                        + CASE WHEN sm.loser_rank IS NULL THEN 0
                               WHEN sm.loser_rank <= 5    THEN 40
                               WHEN sm.loser_rank <= 10   THEN 33
                               WHEN sm.loser_rank <= 20   THEN 27
                               WHEN sm.loser_rank <= 50   THEN 20
                               WHEN sm.loser_rank <= 100  THEN 12
                               WHEN sm.loser_rank <= 200  THEN 5
                               WHEN sm.loser_rank <= 500  THEN 0
                               ELSE -5 END
                        + CASE
                              WHEN sm.score ~ '6-0 6-0|6-0 6-1|6-1 6-0' THEN 10
                              WHEN sm.score ~ '6-1 6-1|6-2 6-1|6-1 6-2|6-0 6-2|6-2 6-0' THEN 7
                              WHEN sm.score ~ '7-6.*7-6|7-5.*7-6|7-6.*7-5|7-5.*7-5' THEN -5
                              WHEN sm.score ~ '7-6|7-5' THEN -2
                              ELSE 0
                          END
                    ELSE
                        50
                        + CASE WHEN sm.winner_rank IS NULL THEN -10
                               WHEN sm.winner_rank <= 5    THEN -5
                               WHEN sm.winner_rank <= 10   THEN -8
                               WHEN sm.winner_rank <= 20   THEN -12
                               WHEN sm.winner_rank <= 50   THEN -18
                               WHEN sm.winner_rank <= 100  THEN -25
                               WHEN sm.winner_rank <= 200  THEN -30
                               ELSE -35 END
                        + CASE
                              WHEN sm.score ~ '6-0 6-0|6-0 6-1|6-1 6-0' THEN -10
                              WHEN sm.score ~ '7-6.*7-6|7-5.*7-6|7-6.*7-5|7-5.*7-5' THEN 8
                              WHEN sm.score ~ '7-6|7-5' THEN 4
                              ELSE 0
                          END
                END AS performance_index
            FROM sa_matches sm
            WHERE (sm.winner_id = ANY(%s) OR sm.loser_id = ANY(%s))
              {surface_clause}
              AND sm.tourney_date IS NOT NULL
            ORDER BY sm.tourney_date DESC
            LIMIT %s
            """,
            q_params,
        )

    return {
        "player_id": player_id,
        "surface_filter": surface,
        "matches": match_rows,
        "rating_history": history_rows,
    }


# ─────────────────────────────────────────────────────────────────────────────
# GET /players/{id}/matches  — paginated match history
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/{player_id}/matches")
def get_player_matches(
    player_id: int,
    surface: Optional[str] = Query(default="all", description="all|clay|hard|grass|indoor"),
    limit: int  = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
):
    """
    Paginated match history for a player.

    First tries the production matches table (live + recent data), then
    falls back to Sackmann / TML historical data for older matches.
    Returns results sorted newest first.
    """
    player = query_one(
        "SELECT id, name, full_name FROM players WHERE id = %s",
        (player_id,),
    )
    if not player:
        raise HTTPException(status_code=404, detail="Player not found")

    # ── Surface filter ───────────────────────────────────────────────────────
    surface_map = {
        "clay":   "Clay",
        "hard":   "Hard",
        "grass":  "Grass",
        "indoor": "Indoor Hard",
    }
    surface_filter = surface_map.get((surface or "all").lower()) if surface and surface.lower() != "all" else None

    # ── 1. Production (live / recent) matches ────────────────────────────────
    surf_clause_live = "AND s.name ILIKE %s" if surface_filter else ""
    surf_params_live = [f"%{surface_filter}%"] if surface_filter else []

    live_matches = query(
        f"""
        SELECT
            m.id                           AS match_id,
            m.event_date                   AS date,
            t.name                         AS tournament,
            m.tournament_round             AS round,
            s.name                         AS surface,
            ms.score,
            CASE WHEN m.first_player_id = %s THEN p2.name ELSE p1.name END AS opponent_name,
            CASE WHEN m.first_player_id = %s THEN p2.id   ELSE p1.id   END AS opponent_id,
            CASE WHEN (m.winner = 'First Player' AND m.first_player_id = %s)
                   OR (m.winner = 'Second Player' AND m.second_player_id = %s)
                 THEN 'W' ELSE 'L' END     AS result,
            m.event_status,
            'live'                         AS source
        FROM matches m
        JOIN players p1 ON p1.id = m.first_player_id
        JOIN players p2 ON p2.id = m.second_player_id
        LEFT JOIN tournaments t ON t.id = m.tournament_id
        LEFT JOIN surfaces s   ON s.id = t.surface_id
        LEFT JOIN match_scores ms ON ms.match_id = m.id
        WHERE (m.first_player_id = %s OR m.second_player_id = %s)
          AND m.event_status IN ('Finished', 'Abandoned')
          AND m.event_date IS NOT NULL
          {surf_clause_live}
        ORDER BY m.event_date DESC
        """,
        [player_id, player_id, player_id, player_id, player_id, player_id, *surf_params_live],
    )

    # ── 2. Historical (Sackmann / TML) matches ───────────────────────────────
    sa_ids = _sa_ids_for(player_id)
    hist_matches: list[dict] = []

    if sa_ids:
        surf_clause_hist = "AND sm.surface ILIKE %s" if surface_filter else ""
        surf_params_hist = [f"%{surface_filter}%"] if surface_filter else []

        hist_matches = query(
            f"""
            SELECT
                sm.id                            AS match_id,
                sm.tourney_date                  AS date,
                sm.tourney_name                  AS tournament,
                sm.round,
                sm.surface,
                sm.score,
                CASE WHEN sm.winner_id = ANY(%s) THEN sm.loser_name  ELSE sm.winner_name END AS opponent_name,
                NULL::integer                    AS opponent_id,
                CASE WHEN sm.winner_id = ANY(%s) THEN 'W' ELSE 'L'  END AS result,
                'Finished'                       AS event_status,
                sm.tour                          AS source,
                sm.winner_rank,
                sm.loser_rank,
                sm.tourney_level,
                sm.w_ace, sm.w_df, sm.w_svpt, sm.w_1st_in, sm.w_1st_won,
                sm.w_bp_saved, sm.w_bp_faced,
                sm.l_ace, sm.l_df, sm.l_svpt, sm.l_1st_in, sm.l_1st_won,
                sm.l_bp_saved, sm.l_bp_faced
            FROM sa_matches sm
            WHERE (sm.winner_id = ANY(%s) OR sm.loser_id = ANY(%s))
              AND sm.tourney_date IS NOT NULL
              {surf_clause_hist}
            ORDER BY sm.tourney_date DESC
            """,
            [sa_ids, sa_ids, sa_ids, sa_ids, *surf_params_hist],
        )

    # ── 3. Merge: de-dup by approximate date + opponent, sort, paginate ──────
    # Build a lookup of live match dates to avoid double-counting recent matches
    # that appear in both live and historical data.
    live_date_opps: set[tuple] = set()
    merged: list[dict] = []

    for m in live_matches:
        key = (str(m.get("date") or ""), str(m.get("opponent_name") or "").lower()[:8])
        live_date_opps.add(key)
        merged.append(dict(m))

    for m in hist_matches:
        key = (str(m.get("date") or ""), str(m.get("opponent_name") or "").lower()[:8])
        if key in live_date_opps:
            continue  # Already represented in live data
        merged.append(dict(m))

    merged.sort(key=lambda x: str(x.get("date") or ""), reverse=True)

    total_count = len(merged)
    page = merged[offset: offset + limit]

    return {
        "player_id": player_id,
        "surface_filter": surface,
        "total": total_count,
        "offset": offset,
        "limit": limit,
        "matches": page,
    }


# ─────────────────────────────────────────────────────────────────────────────
# GET /players/{id}/stats  — career statistics summary
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/{player_id}/stats")
def get_player_stats(player_id: int):
    """
    Career statistics summary: win/loss by surface, serve averages, rankings history.
    Draws primarily from Sackmann / TML historical data for depth.
    """
    player = query_one(
        "SELECT id, name, full_name FROM players WHERE id = %s",
        (player_id,),
    )
    if not player:
        raise HTTPException(status_code=404, detail="Player not found")

    sa_ids = _sa_ids_for(player_id)

    # Win/loss by surface
    surface_stats: list[dict] = []
    career_serve: dict = {}
    rankings_history: list[dict] = []

    if sa_ids:
        surface_stats = query(
            """
            SELECT
                sm.surface,
                COUNT(*) FILTER (WHERE sm.winner_id = ANY(%s)) AS wins,
                COUNT(*) FILTER (WHERE sm.loser_id  = ANY(%s)) AS losses,
                COUNT(*) AS total
            FROM sa_matches sm
            WHERE (sm.winner_id = ANY(%s) OR sm.loser_id = ANY(%s))
              AND sm.surface IS NOT NULL
              AND sm.tourney_date IS NOT NULL
            GROUP BY sm.surface
            ORDER BY total DESC
            """,
            [sa_ids, sa_ids, sa_ids, sa_ids],
        )

        # Career serve averages (where player was the winner — most complete stats)
        serve_row = query_one(
            """
            SELECT
                ROUND(AVG(sm.w_ace::float / NULLIF(sm.w_svpt,0)) * 100, 1) AS avg_ace_pct,
                ROUND(AVG(sm.w_df::float  / NULLIF(sm.w_svpt,0)) * 100, 1) AS avg_df_pct,
                ROUND(AVG(sm.w_1st_serve_pct) * 100, 1)                     AS avg_1st_serve_pct,
                ROUND(AVG(sm.w_1st_won_pct)   * 100, 1)                     AS avg_1st_won_pct,
                ROUND(AVG(sm.w_2nd_won_pct)   * 100, 1)                     AS avg_2nd_won_pct,
                ROUND(AVG(sm.w_bp_save_pct)   * 100, 1)                     AS avg_bp_save_pct,
                COUNT(*) AS sample_size
            FROM sa_matches sm
            WHERE sm.winner_id = ANY(%s)
              AND sm.w_svpt IS NOT NULL AND sm.w_svpt > 0
            """,
            [sa_ids],
        )
        career_serve = dict(serve_row) if serve_row else {}

        # Year-by-year best ranking
        rankings_history = query(
            """
            SELECT
                EXTRACT(YEAR FROM sm.tourney_date)::int AS season,
                MIN(sm.winner_rank) FILTER (WHERE sm.winner_id = ANY(%s)) AS best_rank_as_winner,
                MIN(sm.loser_rank)  FILTER (WHERE sm.loser_id  = ANY(%s)) AS best_rank_as_loser
            FROM sa_matches sm
            WHERE (sm.winner_id = ANY(%s) OR sm.loser_id = ANY(%s))
              AND sm.tourney_date IS NOT NULL
            GROUP BY season
            ORDER BY season DESC
            LIMIT 15
            """,
            [sa_ids, sa_ids, sa_ids, sa_ids],
        )
        # Compute best rank per season
        rankings_history = [
            {
                "season": r["season"],
                "best_rank": min(
                    v for v in [r["best_rank_as_winner"], r["best_rank_as_loser"]] if v
                ) if any(v for v in [r["best_rank_as_winner"], r["best_rank_as_loser"]] if v) else None,
            }
            for r in rankings_history
        ]

    # Surface stats from live production data too
    live_surface = query(
        """
        SELECT
            s.name AS surface,
            COUNT(*) FILTER (WHERE (m.winner = 'First Player' AND m.first_player_id = %s)
                                OR (m.winner = 'Second Player' AND m.second_player_id = %s)) AS wins,
            COUNT(*) FILTER (WHERE (m.winner = 'Second Player' AND m.first_player_id = %s)
                                OR (m.winner = 'First Player' AND m.second_player_id = %s)) AS losses
        FROM matches m
        LEFT JOIN tournaments t ON t.id = m.tournament_id
        LEFT JOIN surfaces s   ON s.id = t.surface_id
        WHERE (m.first_player_id = %s OR m.second_player_id = %s)
          AND m.event_status = 'Finished'
          AND s.name IS NOT NULL
        GROUP BY s.name
        """,
        [player_id, player_id, player_id, player_id, player_id, player_id],
    )

    return {
        "player_id": player_id,
        "surface_stats": surface_stats,
        "live_surface_stats": live_surface,
        "career_serve_averages": career_serve,
        "rankings_history": rankings_history,
    }


# ─────────────────────────────────────────────────────────────────────────────
# GET /players/{p1_id}/h2h/{p2_id}
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/{p1_id}/h2h/{p2_id}")
def get_h2h(p1_id: int, p2_id: int):
    p1 = query_one("SELECT id, name, full_name, country_code FROM players WHERE id = %s", (p1_id,))
    p2 = query_one("SELECT id, name, full_name, country_code FROM players WHERE id = %s", (p2_id,))

    if not p1 or not p2:
        raise HTTPException(status_code=404, detail="One or both players not found")

    p1_sa_ids = _sa_ids_for(p1_id)
    p2_sa_ids = _sa_ids_for(p2_id)

    h2h_matches: list[dict] = []

    if p1_sa_ids and p2_sa_ids:
        h2h_matches = query(
            """
            SELECT
                sm.id AS match_id,
                sm.tourney_date AS date,
                sm.tourney_name AS tournament,
                sm.round,
                sm.surface,
                sm.score,
                CASE WHEN sm.winner_id = ANY(%s) THEN 'first_player' ELSE 'second_player' END AS winner
            FROM sa_matches sm
            WHERE (
                (sm.winner_id = ANY(%s) AND sm.loser_id = ANY(%s))
                OR
                (sm.winner_id = ANY(%s) AND sm.loser_id = ANY(%s))
            )
            ORDER BY sm.tourney_date DESC
            LIMIT 20
            """,
            (p1_sa_ids, p1_sa_ids, p2_sa_ids, p2_sa_ids, p1_sa_ids),
        )

    # Supplement with live/recent data from main matches table.
    # Crucially we attribute the winner based on the ACTUAL player ID, not the
    # 'First/Second Player' slot in the api-tennis ordering — that flips
    # depending on which player was loaded first.
    live_matches = query(
        """
        SELECT
            m.id AS match_id,
            m.event_date AS date,
            t.name AS tournament,
            m.tournament_round AS round,
            s.name AS surface,
            m.final_result AS final_result,
            COALESCE(ms.score, m.final_result) AS score,
            CASE
                WHEN (m.winner = 'First Player'  AND m.first_player_id  = %s)
                  OR (m.winner = 'Second Player' AND m.second_player_id = %s)
                THEN 'first_player'
                WHEN (m.winner = 'First Player'  AND m.first_player_id  = %s)
                  OR (m.winner = 'Second Player' AND m.second_player_id = %s)
                THEN 'second_player'
                ELSE NULL
            END AS winner
        FROM matches m
        LEFT JOIN tournaments t ON t.id = m.tournament_id
        LEFT JOIN surfaces s ON s.id = t.surface_id
        LEFT JOIN LATERAL (
            SELECT string_agg(score_first || '-' || score_second, ' ' ORDER BY set_number) AS score
            FROM match_scores
            WHERE match_id = m.id
        ) ms ON TRUE
        WHERE ((m.first_player_id = %s AND m.second_player_id = %s)
            OR (m.first_player_id = %s AND m.second_player_id = %s))
          AND m.event_status = 'Finished'
        ORDER BY m.event_date DESC
        LIMIT 10
        """,
        (p1_id, p1_id, p2_id, p2_id, p1_id, p2_id, p2_id, p1_id),
    )

    # Merge and sort, deduplicate by match_id
    seen_ids: set = set()
    all_matches: list[dict] = []
    for m in list(live_matches) + list(h2h_matches):
        mid = m.get("match_id")
        if mid in seen_ids:
            continue
        seen_ids.add(mid)
        all_matches.append(m)

    all_matches.sort(key=lambda x: str(x.get("date") or ""), reverse=True)
    all_matches = all_matches[:15]

    p1_wins = sum(1 for m in all_matches if m["winner"] == "first_player")
    p2_wins = sum(1 for m in all_matches if m["winner"] == "second_player")

    # Surface breakdown
    by_surface: dict[str, dict] = {}
    for m in all_matches:
        surf = str(m.get("surface") or "Unknown")
        if surf not in by_surface:
            by_surface[surf] = {"p1": 0, "p2": 0}
        if m["winner"] == "first_player":
            by_surface[surf]["p1"] += 1
        else:
            by_surface[surf]["p2"] += 1

    return {
        "p1": p1,
        "p2": p2,
        "summary": {
            "p1_wins": p1_wins,
            "p2_wins": p2_wins,
            "total": len(all_matches),
            "by_surface": by_surface,
        },
        "matches": all_matches,
    }
