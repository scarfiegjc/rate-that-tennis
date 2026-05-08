"""
ratethat.tennis — Matchstat ingestion pipeline

Resolves production players → Matchstat IDs (via the rankings index, which is
the only ID-bearing endpoint), then upserts profile, matches, and per-match
stats into ms_* tables.

Idempotent — safe to re-run. Uses ON CONFLICT DO UPDATE everywhere.

Public entrypoints:
    backfill_one(conn, player_id, tour='atp')
    backfill_active(conn, tour='atp', limit=None, page_size=200)
    compute_career_stats(conn)

The module is psycopg2 + stdlib only — no heavy ML deps so it can sit in the
slim API container alongside the other lightweight pipeline files.
"""
from __future__ import annotations

import json
import logging
import os
import re
import time
from datetime import datetime, date
from typing import Any, Optional
from urllib import request as _urlreq
from urllib.parse import urlencode
from urllib.error import HTTPError, URLError

import psycopg2
import psycopg2.extras

log = logging.getLogger("matchstat_ingest")

API_HOST = "tennis-api-atp-wta-itf.p.rapidapi.com"
API_BASE = f"https://{API_HOST}"

# ─────────────────────────────────────────────────────────────────────────────
# HTTP
# ─────────────────────────────────────────────────────────────────────────────

def _headers() -> dict:
    return {
        "User-Agent": "Mozilla/5.0 (compatible; ratethat-tennis/1.0; +https://ratethat.tennis)",
        "X-RapidAPI-Key": (os.environ.get("MATCHSTAT_API_KEY") or "").strip(),
        "X-RapidAPI-Host": API_HOST,
        "Accept": "application/json",
    }


def _get(path: str, params: Optional[dict] = None, timeout: int = 15,
         retries: int = 2) -> dict:
    url = API_BASE + path
    if params:
        url += "?" + urlencode(params)
    last_error: dict = {}
    for attempt in range(retries + 1):
        req = _urlreq.Request(url, headers=_headers())
        try:
            with _urlreq.urlopen(req, timeout=timeout) as resp:
                body = resp.read().decode("utf-8")
                return {"ok": True, "status": resp.status,
                        "data": json.loads(body) if body else None}
        except HTTPError as e:
            body = ""
            try:
                body = e.read().decode("utf-8", errors="replace")
            except Exception:
                pass
            last_error = {"ok": False, "status": e.code, "body": body[:300]}
            # Retry on 429/5xx, fail fast on 4xx others
            if e.code in (429, 500, 502, 503, 504) and attempt < retries:
                time.sleep(1 + attempt * 2)
                continue
            return last_error
        except URLError as e:
            last_error = {"ok": False, "status": 0, "error": str(e)}
            if attempt < retries:
                time.sleep(1 + attempt)
                continue
            return last_error
        except Exception as e:
            return {"ok": False, "status": 0, "error": f"{type(e).__name__}: {e}"}
    return last_error


# ─────────────────────────────────────────────────────────────────────────────
# Rankings → name index (the resolver)
# ─────────────────────────────────────────────────────────────────────────────

_RANK_INDEX_CACHE: dict[str, dict] = {}


def _build_rankings_index(tour: str = "atp", page_size: int = 200,
                          max_pages: int = 30) -> dict:
    """Pull the full singles-ranking list for the tour, one page per call,
    and build a name → {id, name, currentRank, countryAcr} dict plus a
    surname bucket. Cached per-process for the lifetime of one ingestion run.
    """
    if tour in _RANK_INDEX_CACHE:
        return _RANK_INDEX_CACHE[tour]

    by_name: dict[str, dict] = {}
    by_surname: dict[str, list[dict]] = {}
    pages = 0
    for page_no in range(1, max_pages + 1):
        page = _get(f"/tennis/v2/{tour}/ranking/singles",
                    params={"pageSize": page_size, "pageNo": page_no})
        if not page.get("ok"):
            log.warning(f"Rankings page {page_no} failed: {page}")
            break
        body = page.get("data")
        rows = body if isinstance(body, list) else (
            body.get("data") if isinstance(body, dict) else None
        ) or []
        if not rows:
            break
        pages += 1
        for r in rows:
            if not isinstance(r, dict):
                continue
            inner = r.get("player") if isinstance(r.get("player"), dict) else r
            name = (inner.get("name") or "").strip()
            ms_id = inner.get("id")
            if not name or not ms_id:
                continue
            entry = {
                "id": ms_id,
                "name": name,
                "currentRank": r.get("currentRank") or r.get("position") or inner.get("currentRank"),
                "countryAcr": inner.get("countryAcr"),
            }
            by_name[name.lower()] = entry
            tokens = name.replace(".", "").split()
            if tokens:
                by_surname.setdefault(tokens[-1].lower(), []).append(entry)
        if len(rows) < page_size:
            break

    cache = {"by_name": by_name, "by_surname": by_surname, "pages": pages}
    _RANK_INDEX_CACHE[tour] = cache
    log.info(f"Rankings index for {tour}: {len(by_name)} names across {pages} pages")
    return cache


def resolve_ms_id(rank_idx: dict, full_name: str, short_name: str = "") -> Optional[dict]:
    """
    Match a player against the rankings index.
    Returns {ms_id, ms_name, strategy} on success, None on no-match.
    """
    full = (full_name or "").strip()
    short = (short_name or full).strip()
    if not full and not short:
        return None
    last_token = full.replace(".", "").split()[-1].lower() if full else (
        short.replace(".", "").split()[-1].lower() if short else "")
    first_initial = ((short or full)[:1] or "").lower()

    # 1: exact full name
    hit = rank_idx["by_name"].get(full.lower())
    if hit:
        return {"ms_id": hit["id"], "ms_name": hit["name"], "strategy": "rankings-exact"}

    # 2: surname + first initial
    bucket = rank_idx["by_surname"].get(last_token, [])
    if len(bucket) == 1:
        r = bucket[0]
        return {"ms_id": r["id"], "ms_name": r["name"], "strategy": "rankings-surname"}
    if len(bucket) > 1 and first_initial:
        narrowed = [b for b in bucket if (b["name"][:1] or "").lower() == first_initial]
        if len(narrowed) == 1:
            r = narrowed[0]
            return {"ms_id": r["id"], "ms_name": r["name"], "strategy": "rankings-initial"}
    return None


# ─────────────────────────────────────────────────────────────────────────────
# Parsing helpers
# ─────────────────────────────────────────────────────────────────────────────

def _parse_int(v) -> Optional[int]:
    if v is None or v == "":
        return None
    try:
        return int(v)
    except (TypeError, ValueError):
        try:
            return int(float(v))
        except (TypeError, ValueError):
            return None


def _parse_date(v) -> Optional[date]:
    if not v:
        return None
    try:
        return datetime.fromisoformat(str(v).replace("Z", "+00:00")).date()
    except (TypeError, ValueError):
        return None


def _parse_weight_kg(weight_str) -> Optional[float]:
    """Matchstat sends '77' (a kg integer-as-string) or '185 lbs. (84 kg)' depending on player."""
    if not weight_str:
        return None
    s = str(weight_str)
    # Look for "(X kg)"
    m = re.search(r"(\d+(?:\.\d+)?)\s*kg", s)
    if m:
        try:
            return float(m.group(1))
        except ValueError:
            pass
    # Fall back: bare number assumed kg if reasonable, else lbs
    m = re.match(r"^\s*(\d+(?:\.\d+)?)\s*(lbs?\.?)?\s*$", s, re.IGNORECASE)
    if m:
        try:
            n = float(m.group(1))
            if m.group(2):  # lbs
                return round(n * 0.453592, 2)
            # bare number — assume kg if 40-130, else assume lbs
            if 40 <= n <= 130:
                return n
            return round(n * 0.453592, 2)
        except ValueError:
            pass
    return None


def _parse_height_cm(height_str) -> Optional[int]:
    """'191' (cm) or '6'1\" (185 cm)' or just an integer."""
    if not height_str:
        return None
    s = str(height_str)
    m = re.search(r"(\d+)\s*cm", s)
    if m:
        return int(m.group(1))
    m = re.match(r"^\s*(\d+)\s*$", s)
    if m:
        n = int(m.group(1))
        # Plausible cm range; if a tiny number (5-7), assume feet — not handled here
        if 140 <= n <= 230:
            return n
    return None


# ─────────────────────────────────────────────────────────────────────────────
# Upserts
# ─────────────────────────────────────────────────────────────────────────────

def _upsert_player(conn, ms_id: int, tour: str, profile: dict) -> None:
    """Upsert one ms_players row from a /player/profile/{id} response."""
    # Profile responses are wrapped as {data: {...}}; unwrap if necessary.
    p = profile.get("data") if isinstance(profile.get("data"), dict) else profile
    if not isinstance(p, dict):
        log.warning(f"  ms_id {ms_id}: profile not a dict, skipping")
        return

    info = p.get("information") or {}
    cur_rank = (p.get("curRank") or {}).get("position")
    cur_rank_at = _parse_date((p.get("curRank") or {}).get("date"))
    best_rank = (p.get("bestRank") or {}).get("position")
    best_rank_at = _parse_date((p.get("bestRank") or {}).get("date"))
    form_arr = p.get("form")
    form_str = "".join(form_arr) if isinstance(form_arr, list) else None

    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO ms_players (
                ms_id, name, country_acr, tour,
                current_rank, current_rank_at, best_rank, best_rank_at, points,
                hard_points, ihard_points, clay_points, grass_points, carpet_points,
                birthday, height_cm, weight_kg, plays, coach, birthplace, residence,
                turned_pro, player_status,
                twitter, instagram, facebook, site, atp_page,
                wikidata_id, form_string, prize_usd,
                raw, last_synced_at
            ) VALUES (
                %s, %s, %s, %s,
                %s, %s, %s, %s, %s,
                %s, %s, %s, %s, %s,
                %s, %s, %s, %s, %s, %s, %s,
                %s, %s,
                %s, %s, %s, %s, %s,
                %s, %s, %s,
                %s::jsonb, NOW()
            )
            ON CONFLICT (ms_id) DO UPDATE SET
                name             = EXCLUDED.name,
                country_acr      = EXCLUDED.country_acr,
                tour             = EXCLUDED.tour,
                current_rank     = EXCLUDED.current_rank,
                current_rank_at  = EXCLUDED.current_rank_at,
                best_rank        = EXCLUDED.best_rank,
                best_rank_at     = EXCLUDED.best_rank_at,
                points           = EXCLUDED.points,
                hard_points      = EXCLUDED.hard_points,
                ihard_points     = EXCLUDED.ihard_points,
                clay_points      = EXCLUDED.clay_points,
                grass_points     = EXCLUDED.grass_points,
                carpet_points    = EXCLUDED.carpet_points,
                birthday         = COALESCE(EXCLUDED.birthday,    ms_players.birthday),
                height_cm        = COALESCE(EXCLUDED.height_cm,   ms_players.height_cm),
                weight_kg        = COALESCE(EXCLUDED.weight_kg,   ms_players.weight_kg),
                plays            = COALESCE(EXCLUDED.plays,       ms_players.plays),
                coach            = COALESCE(EXCLUDED.coach,       ms_players.coach),
                birthplace       = COALESCE(EXCLUDED.birthplace,  ms_players.birthplace),
                residence        = COALESCE(EXCLUDED.residence,   ms_players.residence),
                turned_pro       = COALESCE(EXCLUDED.turned_pro,  ms_players.turned_pro),
                player_status    = EXCLUDED.player_status,
                twitter          = COALESCE(EXCLUDED.twitter,     ms_players.twitter),
                instagram        = COALESCE(EXCLUDED.instagram,   ms_players.instagram),
                facebook         = COALESCE(EXCLUDED.facebook,    ms_players.facebook),
                site             = COALESCE(EXCLUDED.site,        ms_players.site),
                atp_page         = COALESCE(EXCLUDED.atp_page,    ms_players.atp_page),
                wikidata_id      = COALESCE(EXCLUDED.wikidata_id, ms_players.wikidata_id),
                form_string      = EXCLUDED.form_string,
                prize_usd        = COALESCE(EXCLUDED.prize_usd,   ms_players.prize_usd),
                raw              = EXCLUDED.raw,
                last_synced_at   = NOW()
            """,
            (
                ms_id, p.get("name") or "", p.get("countryAcr"), tour,
                cur_rank, cur_rank_at, best_rank, best_rank_at, _parse_int(p.get("points")),
                _parse_int(p.get("hardPoints")), _parse_int(p.get("ihardPoints")),
                _parse_int(p.get("clayPoints")), _parse_int(p.get("grassPoints")),
                _parse_int(p.get("carpetPoints")),
                _parse_date(p.get("birthday")),
                _parse_height_cm(info.get("height") or p.get("height")),
                _parse_weight_kg(info.get("weight")),
                info.get("plays"),
                info.get("coach"),
                info.get("birthplace"),
                info.get("residence"),
                _parse_int(info.get("turnedPro")),
                info.get("playerStatus") or p.get("playerStatus"),
                info.get("twitter"), info.get("instagram"),
                info.get("facebook"), info.get("site"),
                info.get("page"),
                p.get("wikidata_id"),
                form_str, _parse_int(p.get("prize")),
                json.dumps(p),
            ),
        )


def _upsert_match(conn, m: dict, tour: str) -> None:
    if not isinstance(m, dict) or m.get("id") is None:
        return
    tournament = m.get("tournament") or {}
    rnd = m.get("round") or {}
    court = tournament.get("court") or {}
    rank_obj = tournament.get("rank") or {}

    p1 = m.get("player1") or {}
    p2 = m.get("player2") or {}

    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO ms_matches (
                ms_match_id, tour, match_date, result, best_of,
                round_id, round_name, tournament_id, tournament_name,
                tournament_tier, court_id, court_name,
                p1_ms_id, p2_ms_id, p1_name, p2_name,
                odd1, odd2, raw, last_synced_at
            ) VALUES (
                %s, %s, %s, %s, %s,
                %s, %s, %s, %s,
                %s, %s, %s,
                %s, %s, %s, %s,
                %s, %s, %s::jsonb, NOW()
            )
            ON CONFLICT (ms_match_id) DO UPDATE SET
                tour             = EXCLUDED.tour,
                match_date       = EXCLUDED.match_date,
                result           = EXCLUDED.result,
                best_of          = EXCLUDED.best_of,
                round_id         = EXCLUDED.round_id,
                round_name       = EXCLUDED.round_name,
                tournament_id    = EXCLUDED.tournament_id,
                tournament_name  = EXCLUDED.tournament_name,
                tournament_tier  = EXCLUDED.tournament_tier,
                court_id         = EXCLUDED.court_id,
                court_name       = EXCLUDED.court_name,
                p1_ms_id         = EXCLUDED.p1_ms_id,
                p2_ms_id         = EXCLUDED.p2_ms_id,
                p1_name          = EXCLUDED.p1_name,
                p2_name          = EXCLUDED.p2_name,
                odd1             = COALESCE(EXCLUDED.odd1, ms_matches.odd1),
                odd2             = COALESCE(EXCLUDED.odd2, ms_matches.odd2),
                raw              = EXCLUDED.raw,
                last_synced_at   = NOW()
            """,
            (
                _parse_int(m.get("id")), tour, _parse_date(m.get("date")),
                m.get("result"), _parse_int(m.get("best_of")),
                _parse_int(m.get("roundId")), rnd.get("name"),
                _parse_int(m.get("tournamentId")), tournament.get("name"),
                rank_obj.get("name"),
                _parse_int(tournament.get("courtId")), court.get("name"),
                _parse_int(m.get("player1Id")), _parse_int(m.get("player2Id")),
                p1.get("name"), p2.get("name"),
                m.get("odd1"), m.get("odd2"),
                json.dumps(m),
            ),
        )

    # Match stats — two rows (player1/player2)
    stats = m.get("stats") or m.get("stat") or {}
    if not isinstance(stats, dict):
        return
    for side_idx, side_key in (("1", "player1"), ("2", "player2")):
        side = stats.get(side_key) or {}
        if not isinstance(side, dict):
            continue
        ms_match_id = _parse_int(m.get("id"))
        ms_player_id = _parse_int((m.get(f"player{side_idx}Id"))
                                  or ((m.get(side_key) or {}).get("id")))
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO ms_match_stats (
                    ms_match_id, side, ms_player_id,
                    aces, double_faults,
                    first_serve, first_serve_of,
                    winning_on_first_serve, winning_on_first_serve_of,
                    winning_on_second_serve, winning_on_second_serve_of,
                    break_points_converted, break_points_converted_of,
                    total_points_won,
                    winners, unforced_errors,
                    net_approaches, net_approaches_of,
                    fastest_serve, avg_first_serve_speed, avg_second_serve_speed,
                    rpw, rpw_of
                ) VALUES (
                    %s, %s, %s,
                    %s, %s,
                    %s, %s,
                    %s, %s,
                    %s, %s,
                    %s, %s,
                    %s,
                    %s, %s,
                    %s, %s,
                    %s, %s, %s,
                    %s, %s
                )
                ON CONFLICT (ms_match_id, side) DO UPDATE SET
                    ms_player_id              = EXCLUDED.ms_player_id,
                    aces                      = EXCLUDED.aces,
                    double_faults             = EXCLUDED.double_faults,
                    first_serve               = EXCLUDED.first_serve,
                    first_serve_of            = EXCLUDED.first_serve_of,
                    winning_on_first_serve    = EXCLUDED.winning_on_first_serve,
                    winning_on_first_serve_of = EXCLUDED.winning_on_first_serve_of,
                    winning_on_second_serve   = EXCLUDED.winning_on_second_serve,
                    winning_on_second_serve_of = EXCLUDED.winning_on_second_serve_of,
                    break_points_converted    = EXCLUDED.break_points_converted,
                    break_points_converted_of = EXCLUDED.break_points_converted_of,
                    total_points_won          = EXCLUDED.total_points_won,
                    winners                   = EXCLUDED.winners,
                    unforced_errors           = EXCLUDED.unforced_errors,
                    net_approaches            = EXCLUDED.net_approaches,
                    net_approaches_of         = EXCLUDED.net_approaches_of,
                    fastest_serve             = EXCLUDED.fastest_serve,
                    avg_first_serve_speed     = EXCLUDED.avg_first_serve_speed,
                    avg_second_serve_speed    = EXCLUDED.avg_second_serve_speed,
                    rpw                       = EXCLUDED.rpw,
                    rpw_of                    = EXCLUDED.rpw_of
                """,
                (
                    ms_match_id, side_idx, ms_player_id,
                    _parse_int(side.get("aces")), _parse_int(side.get("doubleFaults")),
                    _parse_int(side.get("firstServe")), _parse_int(side.get("firstServeOf")),
                    _parse_int(side.get("winningOnFirstServe")),
                    _parse_int(side.get("winningOnFirstServeOf")),
                    _parse_int(side.get("winningOnSecondServe")),
                    _parse_int(side.get("winningOnSecondServeOf")),
                    _parse_int(side.get("breakPointsConverted")),
                    _parse_int(side.get("breakPointsConvertedOf")),
                    _parse_int(side.get("totalPointsWon")),
                    _parse_int(side.get("winners")),
                    _parse_int(side.get("unforcedErrors")),
                    _parse_int(side.get("netApproaches")),
                    _parse_int(side.get("netApproachesOf")),
                    _parse_int(side.get("fastestServe")),
                    _parse_int(side.get("averageFirstServeSpeed")),
                    _parse_int(side.get("averageSecondServeSpeed")),
                    _parse_int(side.get("rpw")), _parse_int(side.get("rpwOf")),
                ),
            )


def _upsert_player_link(conn, player_id: int, ms_id: int, tour: str, strategy: str) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO ms_player_links (player_id, ms_id, tour, resolution_strategy, confidence)
            VALUES (%s, %s, %s, %s,
                    CASE WHEN %s = 'rankings-exact' THEN 'high' ELSE 'medium' END)
            ON CONFLICT (player_id) DO UPDATE SET
                ms_id               = EXCLUDED.ms_id,
                tour                = EXCLUDED.tour,
                resolution_strategy = EXCLUDED.resolution_strategy,
                confidence          = EXCLUDED.confidence,
                linked_at           = NOW()
            """,
            (player_id, ms_id, tour, strategy, strategy),
        )


# ─────────────────────────────────────────────────────────────────────────────
# Per-player ingestion
# ─────────────────────────────────────────────────────────────────────────────

def backfill_one(conn, player_id: int, tour: str = "atp",
                 max_match_pages: int = 5, page_size: int = 200) -> dict:
    """
    Resolve, fetch profile, fetch matches with stats, upsert everything.
    Returns a small summary dict.
    """
    rank_idx = _build_rankings_index(tour=tour)

    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(
            "SELECT id, name, full_name, country_code FROM players WHERE id = %s",
            (player_id,),
        )
        row = cur.fetchone()
    if not row:
        return {"player_id": player_id, "status": "not-in-players"}

    resolved = resolve_ms_id(rank_idx,
                             full_name=row.get("full_name") or "",
                             short_name=row.get("name") or "")
    if not resolved:
        return {"player_id": player_id, "name": row.get("full_name"),
                "status": "unresolved"}

    ms_id = resolved["ms_id"]
    strategy = resolved["strategy"]

    # 1. Profile
    profile = _get(f"/tennis/v2/{tour}/player/profile/{ms_id}",
                   params={"include": "form,ranking,country"})
    if not profile.get("ok"):
        return {"player_id": player_id, "ms_id": ms_id,
                "status": "profile-failed", "error": profile}
    _upsert_player(conn, ms_id, tour, profile["data"])

    # 2. Player link
    _upsert_player_link(conn, player_id, ms_id, tour, strategy)

    # 3. Matches with stats — paginate
    matches_seen = 0
    matches_with_stats = 0
    matches_with_premium = 0
    for page_no in range(1, max_match_pages + 1):
        page = _get(f"/tennis/v2/{tour}/player/past-matches/{ms_id}",
                    params={"include": "round,tournament.court,tournament.rank,stat",
                            "pageSize": page_size, "pageNo": page_no})
        if not page.get("ok"):
            break
        body = page.get("data") or {}
        rows = body.get("data") if isinstance(body, dict) else (body if isinstance(body, list) else [])
        if not rows:
            break
        for m in rows:
            try:
                _upsert_match(conn, m, tour)
                matches_seen += 1
                stats = (m.get("stats") or m.get("stat") or {})
                if isinstance(stats, dict) and (stats.get("player1") or stats.get("player2")):
                    matches_with_stats += 1
                    p1s = stats.get("player1") or {}
                    if isinstance(p1s, dict) and p1s.get("winners") is not None:
                        matches_with_premium += 1
            except Exception as e:
                log.warning(f"  match upsert failed for {m.get('id')}: {e}")
        if not body.get("hasNextPage"):
            break

    conn.commit()
    return {
        "player_id": player_id, "ms_id": ms_id, "ms_name": resolved.get("ms_name"),
        "strategy": strategy, "matches_ingested": matches_seen,
        "matches_with_stats": matches_with_stats,
        "matches_with_premium": matches_with_premium,
        "status": "ok",
    }


# ─────────────────────────────────────────────────────────────────────────────
# Bulk backfill
# ─────────────────────────────────────────────────────────────────────────────

def _pick_active_players(conn, limit: Optional[int] = None) -> list[dict]:
    """All active rated players, ordered by RTT."""
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        sql = """
            SELECT p.id, p.name, p.full_name
            FROM players p
            JOIN player_ratings pr ON pr.player_id = p.id
            WHERE pr.rtt_score IS NOT NULL
              AND p.is_active = TRUE
            ORDER BY pr.rtt_score DESC NULLS LAST
        """
        if limit:
            sql += " LIMIT %s"
            cur.execute(sql, (limit,))
        else:
            cur.execute(sql)
        return [dict(r) for r in cur.fetchall()]


def backfill_active(conn, tour: str = "atp", limit: Optional[int] = None,
                    max_match_pages: int = 3, page_size: int = 200,
                    skip_already_linked: bool = True) -> dict:
    """Run backfill_one() across every active rated player on the given tour.
    `skip_already_linked` means we don't refetch profile/matches for players
    we've already ingested — useful for a resumable backfill.
    """
    sample = _pick_active_players(conn, limit=limit)
    if skip_already_linked:
        with conn.cursor() as cur:
            cur.execute("SELECT player_id FROM ms_player_links WHERE tour = %s", (tour,))
            already = {r[0] for r in cur.fetchall()}
        sample = [p for p in sample if p["id"] not in already]

    summary: dict = {"resolved": 0, "unresolved": 0, "errored": 0,
                     "matches_ingested": 0, "matches_with_premium": 0,
                     "tour": tour, "candidates": len(sample), "details": []}
    t0 = time.time()
    for i, p in enumerate(sample, 1):
        try:
            res = backfill_one(conn, p["id"], tour=tour,
                               max_match_pages=max_match_pages,
                               page_size=page_size)
            # Include a compact per-player line so we can diagnose 0-match runs
            summary["details"].append({
                "player_id": p["id"],
                "name": p.get("full_name") or p.get("name"),
                "status": res.get("status"),
                "ms_id": res.get("ms_id"),
                "matches_ingested": res.get("matches_ingested", 0),
                "matches_with_premium": res.get("matches_with_premium", 0),
                "error": res.get("error"),
            })
            if res.get("status") == "ok":
                summary["resolved"] += 1
                summary["matches_ingested"] += res.get("matches_ingested", 0) or 0
                summary["matches_with_premium"] += res.get("matches_with_premium", 0) or 0
            elif res.get("status") == "unresolved":
                summary["unresolved"] += 1
            else:
                summary["errored"] += 1
        except Exception as e:
            summary["errored"] += 1
            summary["details"].append({
                "player_id": p["id"],
                "name": p.get("full_name") or p.get("name"),
                "status": "exception",
                "error": f"{type(e).__name__}: {e}",
            })
            log.warning(f"backfill_one failed for player {p['id']}: {e}")
        if i % 25 == 0:
            log.info(f"  progress {i}/{len(sample)} resolved={summary['resolved']} "
                     f"matches={summary['matches_ingested']}")
    summary["elapsed_sec"] = round(time.time() - t0, 1)
    return summary


# ─────────────────────────────────────────────────────────────────────────────
# Career-stats aggregation
# ─────────────────────────────────────────────────────────────────────────────

def compute_career_stats(conn) -> dict:
    """
    Roll up ms_match_stats into ms_player_career_stats.
    - Slam-only career averages: only Grand Slam matches with winners populated
    - Universal averages: all matches with stat block
    """
    with conn.cursor() as cur:
        cur.execute("""
            INSERT INTO ms_player_career_stats (
                ms_player_id,
                slam_matches,
                slam_winners_per_match,
                slam_ue_per_match,
                slam_winner_ue_ratio,
                slam_net_won_pct,
                slam_avg_first_serve_kmh,
                slam_avg_second_serve_kmh,
                slam_fastest_serve_kmh,
                all_matches,
                all_first_serve_pct,
                all_first_serve_won_pct,
                all_second_serve_won_pct,
                all_aces_per_match,
                all_df_per_match,
                all_bp_conv_pct,
                all_total_pts_won_per_match,
                last_computed_at
            )
            SELECT
                s.ms_player_id,

                -- Slam-only
                COUNT(*) FILTER (WHERE m.tournament_tier = 'Grand Slam' AND s.winners IS NOT NULL),
                ROUND(AVG(s.winners) FILTER (WHERE m.tournament_tier = 'Grand Slam'
                                              AND s.winners IS NOT NULL)::numeric, 2),
                ROUND(AVG(s.unforced_errors) FILTER (WHERE m.tournament_tier = 'Grand Slam'
                                                      AND s.unforced_errors IS NOT NULL)::numeric, 2),
                ROUND(AVG(s.winners::numeric / GREATEST(s.unforced_errors, 1))
                       FILTER (WHERE m.tournament_tier = 'Grand Slam'
                               AND s.winners IS NOT NULL
                               AND s.unforced_errors IS NOT NULL), 3),
                ROUND(AVG(100.0 * s.net_approaches::numeric / NULLIF(s.net_approaches_of, 0))
                       FILTER (WHERE m.tournament_tier = 'Grand Slam'
                               AND s.net_approaches IS NOT NULL
                               AND s.net_approaches_of IS NOT NULL
                               AND s.net_approaches_of > 0), 2),
                ROUND(AVG(s.avg_first_serve_speed) FILTER (WHERE m.tournament_tier = 'Grand Slam'
                                                            AND s.avg_first_serve_speed IS NOT NULL)::numeric, 1),
                ROUND(AVG(s.avg_second_serve_speed) FILTER (WHERE m.tournament_tier = 'Grand Slam'
                                                             AND s.avg_second_serve_speed IS NOT NULL)::numeric, 1),
                MAX(s.fastest_serve) FILTER (WHERE m.tournament_tier = 'Grand Slam'
                                              AND s.fastest_serve IS NOT NULL),

                -- Universal (any match with stat block)
                COUNT(*) FILTER (WHERE s.first_serve IS NOT NULL),
                ROUND(AVG(100.0 * s.first_serve::numeric / NULLIF(s.first_serve_of, 0))
                       FILTER (WHERE s.first_serve IS NOT NULL AND s.first_serve_of > 0), 2),
                ROUND(AVG(100.0 * s.winning_on_first_serve::numeric / NULLIF(s.winning_on_first_serve_of, 0))
                       FILTER (WHERE s.winning_on_first_serve IS NOT NULL AND s.winning_on_first_serve_of > 0), 2),
                ROUND(AVG(100.0 * s.winning_on_second_serve::numeric / NULLIF(s.winning_on_second_serve_of, 0))
                       FILTER (WHERE s.winning_on_second_serve IS NOT NULL AND s.winning_on_second_serve_of > 0), 2),
                ROUND(AVG(s.aces) FILTER (WHERE s.aces IS NOT NULL)::numeric, 2),
                ROUND(AVG(s.double_faults) FILTER (WHERE s.double_faults IS NOT NULL)::numeric, 2),
                ROUND(AVG(100.0 * s.break_points_converted::numeric / NULLIF(s.break_points_converted_of, 0))
                       FILTER (WHERE s.break_points_converted IS NOT NULL AND s.break_points_converted_of > 0), 2),
                ROUND(AVG(s.total_points_won) FILTER (WHERE s.total_points_won IS NOT NULL)::numeric, 2),
                NOW()
            FROM ms_match_stats s
            JOIN ms_matches m ON m.ms_match_id = s.ms_match_id
            WHERE s.ms_player_id IS NOT NULL
            GROUP BY s.ms_player_id
            HAVING COUNT(*) > 0
            ON CONFLICT (ms_player_id) DO UPDATE SET
                slam_matches               = EXCLUDED.slam_matches,
                slam_winners_per_match     = EXCLUDED.slam_winners_per_match,
                slam_ue_per_match          = EXCLUDED.slam_ue_per_match,
                slam_winner_ue_ratio       = EXCLUDED.slam_winner_ue_ratio,
                slam_net_won_pct           = EXCLUDED.slam_net_won_pct,
                slam_avg_first_serve_kmh   = EXCLUDED.slam_avg_first_serve_kmh,
                slam_avg_second_serve_kmh  = EXCLUDED.slam_avg_second_serve_kmh,
                slam_fastest_serve_kmh     = EXCLUDED.slam_fastest_serve_kmh,
                all_matches                = EXCLUDED.all_matches,
                all_first_serve_pct        = EXCLUDED.all_first_serve_pct,
                all_first_serve_won_pct    = EXCLUDED.all_first_serve_won_pct,
                all_second_serve_won_pct   = EXCLUDED.all_second_serve_won_pct,
                all_aces_per_match         = EXCLUDED.all_aces_per_match,
                all_df_per_match           = EXCLUDED.all_df_per_match,
                all_bp_conv_pct            = EXCLUDED.all_bp_conv_pct,
                all_total_pts_won_per_match = EXCLUDED.all_total_pts_won_per_match,
                last_computed_at           = NOW()
        """)
        rowcount = cur.rowcount
    conn.commit()
    return {"players_aggregated": rowcount}
