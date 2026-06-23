#!/usr/bin/env python3
"""
ratethat.tennis — bzzoiro.com sync pipeline
==========================================
Syncs matches, live scores, rankings, odds, H2H and predictions from bzzoiro API.

This module complements bzzoiro_ingest.py by adding:
  - BzzoiroClient class with rate limiting, pagination, error handling
  - sync_fixtures()     — upcoming matches (next 7 days) with tournament linkage
  - sync_live()         — live match updates with serve stats in live_data JSONB
  - sync_rankings()     — ATP+WTA rankings with movement (wraps bzzoiro_ingest)
  - sync_odds()         — per-match bookmaker odds (13+ bookmakers)
  - sync_predictions()  — O/U + match winner predictions → bzzoiro_predictions table
  - sync_h2h(match_id) — H2H + last 5 per player → bzzoiro_h2h table

Usage:
    python3 -m pipeline.bzzoiro --job fixtures          # upcoming 7 days
    python3 -m pipeline.bzzoiro --job live              # live matches
    python3 -m pipeline.bzzoiro --job rankings          # ATP+WTA rankings with movement
    python3 -m pipeline.bzzoiro --job odds              # per-match bookmaker odds
    python3 -m pipeline.bzzoiro --job predictions       # O/U + match winner predictions
    python3 -m pipeline.bzzoiro --job all               # run all jobs
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import time
from datetime import date, datetime, timedelta
from typing import Optional

import psycopg2
import psycopg2.extras
import requests

# Load .env if present (local dev)
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

# ─────────────────────────────────────────────────────────────────────────────
# CONFIG
# ─────────────────────────────────────────────────────────────────────────────

BZZ_TOKEN = (
    os.environ.get("BZZOIRO_API_KEY")
    or "4426945bd65f0798e817976bbef975bbb9d0e606"
)
BZZ_BASE = "https://sports.bzzoiro.com/tennis/api/v2"

DB_URL = (
    os.environ.get("DATABASE_PUBLIC_URL")
    or os.environ.get("DATABASE_URL")
    or ""
).strip()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
log = logging.getLogger("bzzoiro")


# ─────────────────────────────────────────────────────────────────────────────
# DATABASE CONNECTION
# ─────────────────────────────────────────────────────────────────────────────

def get_db_conn() -> psycopg2.extensions.connection:
    dsn = DB_URL
    if not dsn:
        raise SystemExit(
            "Neither DATABASE_PUBLIC_URL nor DATABASE_URL is set."
        )
    conn = psycopg2.connect(dsn)
    conn.cursor_factory = psycopg2.extras.RealDictCursor
    return conn


# ─────────────────────────────────────────────────────────────────────────────
# BZZOIRO CLIENT
# ─────────────────────────────────────────────────────────────────────────────

class BzzoiroClient:
    """
    HTTP client for the bzzoiro sports API.
    Handles auth, rate limiting, retries, and DRF-style cursor pagination.
    """

    def __init__(
        self,
        token: str = BZZ_TOKEN,
        base_url: str = BZZ_BASE,
        rate_limit_delay: float = 0.15,
        timeout: int = 30,
        max_retries: int = 2,
    ):
        self.base_url = base_url.rstrip("/")
        self.headers = {"Authorization": f"Token {token}"}
        self.delay = rate_limit_delay
        self.timeout = timeout
        self.max_retries = max_retries
        self.session = requests.Session()
        self.session.headers.update(self.headers)
        self._calls = 0

    def get(self, path: str, params: Optional[dict] = None) -> Optional[dict]:
        """
        GET {base_url}{path}.
        Returns parsed JSON on success, None on persistent failure.
        """
        url = self.base_url + path
        return self._fetch(url, params=params)

    def get_url(self, full_url: str) -> Optional[dict]:
        """GET an absolute URL (used for pagination 'next' links)."""
        return self._fetch(full_url)

    def _fetch(self, url: str, params: Optional[dict] = None) -> Optional[dict]:
        last_exc: Optional[Exception] = None
        for attempt in range(self.max_retries + 1):
            try:
                resp = self.session.get(url, params=params, timeout=self.timeout)
                resp.raise_for_status()
                self._calls += 1
                time.sleep(self.delay)
                return resp.json()
            except requests.HTTPError as exc:
                status = exc.response.status_code if exc.response is not None else 0
                log.warning(f"  HTTP {status} from {url} (attempt {attempt + 1})")
                last_exc = exc
                if status in (429, 500, 502, 503, 504) and attempt < self.max_retries:
                    time.sleep(2 + attempt * 3)
                    continue
                log.error(f"  Non-retryable HTTP {status}: {exc}")
                return None
            except (requests.ConnectionError, requests.Timeout) as exc:
                log.warning(f"  Network error on {url} (attempt {attempt + 1}): {exc}")
                last_exc = exc
                if attempt < self.max_retries:
                    time.sleep(2 + attempt * 2)
                continue
            except Exception as exc:
                log.error(f"  Unexpected error fetching {url}: {exc}")
                return None
        log.error(f"  All {self.max_retries + 1} attempts failed for {url}: {last_exc}")
        return None

    def paginate(self, path: str, params: Optional[dict] = None) -> list:
        """
        Walk DRF cursor pagination: {"count": N, "next": url|null, "results": [...]}
        Returns full results list.
        """
        all_results: list = []
        data = self.get(path, params=params)
        if data is None:
            return all_results

        results = data.get("results") or data if isinstance(data, list) else []
        if isinstance(results, list):
            all_results.extend(results)

        next_url = data.get("next") if isinstance(data, dict) else None
        while next_url:
            data = self.get_url(next_url)
            if data is None:
                log.warning("  Pagination interrupted — partial results returned")
                break
            batch = data.get("results") or []
            all_results.extend(batch)
            next_url = data.get("next")

        return all_results

    @property
    def calls_made(self) -> int:
        return self._calls


# ─────────────────────────────────────────────────────────────────────────────
# PLAYER RESOLUTION  (reuses bzzoiro_ingest logic via import)
# ─────────────────────────────────────────────────────────────────────────────

def _resolve_player(cur, bzz_player_id: int, name: str, full_name: Optional[str] = None,
                    country_code: Optional[str] = None) -> int:
    """
    Find or create a players row for a Bzzoiro player.
    Uses player_external_ids (source='bzzoiro') as primary lookup,
    then ILIKE name match, then INSERT.
    Returns internal players.id.
    """
    ext_id = str(bzz_player_id)

    # 1. External ID lookup
    cur.execute(
        "SELECT player_id FROM player_external_ids WHERE source = 'bzzoiro' AND external_id = %s",
        (ext_id,),
    )
    row = cur.fetchone()
    if row:
        return row["player_id"]

    # 2. Name-based fuzzy match
    search_name = (full_name or name or "").strip()
    our_player_id: Optional[int] = None

    if search_name:
        for field in ("full_name", "name"):
            cur.execute(
                f"SELECT id FROM players WHERE {field} ILIKE %s LIMIT 1",
                (search_name,),
            )
            row = cur.fetchone()
            if row:
                our_player_id = row["id"]
                break

    # 3. Create new player row
    if our_player_id is None:
        display_name = name or full_name or "Unknown"
        neg_api_key = -abs(int(bzz_player_id))
        cur.execute(
            """
            INSERT INTO players (api_key, name, full_name, country_code, is_active)
            VALUES (%s, %s, %s, %s, TRUE)
            ON CONFLICT (api_key) DO UPDATE SET
                full_name    = COALESCE(EXCLUDED.full_name, players.full_name),
                country_code = COALESCE(EXCLUDED.country_code, players.country_code),
                updated_at   = NOW()
            RETURNING id
            """,
            (neg_api_key, display_name, full_name or display_name, country_code),
        )
        row = cur.fetchone()
        our_player_id = row["id"]

    # Store external ID mapping
    cur.execute(
        """
        INSERT INTO player_external_ids (player_id, source, external_id)
        VALUES (%s, 'bzzoiro', %s)
        ON CONFLICT (player_id, source) DO UPDATE SET external_id = EXCLUDED.external_id
        """,
        (our_player_id, ext_id),
    )
    return our_player_id


def _map_status(bzz_status: str) -> tuple[str, bool]:
    """Map Bzzoiro status → (event_status, is_live)."""
    s = (bzz_status or "").lower().replace(" ", "_")
    if s in ("scheduled", "notstarted", "not_started", ""):
        return "1", False
    if s in ("inprogress", "in_progress", "live"):
        return "live", True
    if s in ("finished", "completed", "ended"):
        return "Finished", False
    if s in ("postponed",):
        return "Postponed", False
    if s in ("retired",):
        return "Retired", False
    if s in ("walkover", "w_o", "walkover_home", "walkover_away"):
        return "Walkover", False
    if s in ("cancelled", "canceled", "abandoned"):
        return "Cancelled", False
    return "1", False


# ─────────────────────────────────────────────────────────────────────────────
# SYNC FIXTURES
# ─────────────────────────────────────────────────────────────────────────────

def sync_fixtures(conn: psycopg2.extensions.connection, days_ahead: int = 7) -> dict:
    """
    Fetch upcoming matches for the next `days_ahead` days.
    Upserts into matches table using negative api_event_key namespace.
    Stores bzzoiro_id on the matches row.
    Returns {fetched, inserted, updated, errors}.
    """
    client = BzzoiroClient()
    today = date.today()
    date_from = today.isoformat()
    date_to = (today + timedelta(days=days_ahead)).isoformat()

    log.info(f"sync_fixtures: {date_from} → {date_to}")

    bzz_matches = client.paginate("/matches/", params={
        "date_from": date_from,
        "date_to": date_to,
        "status": "scheduled",
        "limit": 100,
    })
    log.info(f"  Fetched {len(bzz_matches)} scheduled matches from Bzzoiro")

    inserted = updated = errors = 0

    with conn.cursor() as cur:
        for bzz in bzz_matches:
            try:
                was_inserted = _upsert_fixture(cur, bzz)
                if was_inserted:
                    inserted += 1
                else:
                    updated += 1
            except Exception as exc:
                errors += 1
                log.error(f"  Fixture bzz_id={bzz.get('id')}: {type(exc).__name__}: {exc}")
                try:
                    conn.rollback()
                except Exception:
                    pass

    conn.commit()
    log.info(f"sync_fixtures done: fetched={len(bzz_matches)} inserted={inserted} updated={updated} errors={errors}")
    return {"fetched": len(bzz_matches), "inserted": inserted, "updated": updated, "errors": errors}


def _upsert_fixture(cur, bzz: dict) -> bool:
    """
    Upsert one Bzzoiro match into matches.
    Returns True if inserted, False if updated.
    """
    bzz_id = bzz.get("id")
    if not bzz_id:
        return False

    neg_event_key = -abs(int(bzz_id))

    p1 = bzz.get("player1") or {}
    p2 = bzz.get("player2") or {}
    if not p1.get("id") or not p2.get("id"):
        return False

    p1_id = _resolve_player(
        cur, int(p1["id"]),
        name=p1.get("short_name") or p1.get("name") or "Unknown",
        full_name=p1.get("name"),
        country_code=p1.get("country_code"),
    )
    p2_id = _resolve_player(
        cur, int(p2["id"]),
        name=p2.get("short_name") or p2.get("name") or "Unknown",
        full_name=p2.get("name"),
        country_code=p2.get("country_code"),
    )

    md = bzz.get("match_date") or bzz.get("date") or ""
    event_date: Optional[date] = None
    event_time = None
    try:
        dt = datetime.fromisoformat(md.replace("Z", "+00:00"))
        event_date = dt.date()
        event_time = dt.time().replace(microsecond=0)
    except Exception:
        try:
            event_date = datetime.strptime(md[:10], "%Y-%m-%d").date()
        except Exception:
            pass

    if event_date is None:
        return False

    event_status, is_live = _map_status(bzz.get("status") or "")
    season = str(event_date.year)
    round_name = bzz.get("round_name") or bzz.get("round") or ""

    cur.execute(
        """
        INSERT INTO matches (
            api_event_key,
            first_player_id, second_player_id,
            event_date, event_time,
            tournament_round, season,
            event_status, is_live,
            bzzoiro_id,
            raw_json
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb)
        ON CONFLICT (api_event_key) DO UPDATE SET
            first_player_id  = EXCLUDED.first_player_id,
            second_player_id = EXCLUDED.second_player_id,
            event_date       = EXCLUDED.event_date,
            event_time       = COALESCE(EXCLUDED.event_time, matches.event_time),
            tournament_round = COALESCE(EXCLUDED.tournament_round, matches.tournament_round),
            event_status     = EXCLUDED.event_status,
            is_live          = EXCLUDED.is_live,
            bzzoiro_id       = EXCLUDED.bzzoiro_id,
            raw_json         = EXCLUDED.raw_json,
            updated_at       = NOW()
        RETURNING id, (xmax = 0) AS was_inserted
        """,
        (
            neg_event_key,
            p1_id, p2_id,
            event_date, event_time,
            round_name, season,
            event_status, is_live,
            int(bzz_id),
            json.dumps(bzz),
        ),
    )
    row = cur.fetchone()
    if not row:
        return False
    return bool(row["was_inserted"] if isinstance(row, dict) else row[1])


# ─────────────────────────────────────────────────────────────────────────────
# SYNC LIVE
# ─────────────────────────────────────────────────────────────────────────────

def sync_live(conn: psycopg2.extensions.connection) -> dict:
    """
    Fetch live matches from Bzzoiro, update matches table with current scores,
    serve stats, and live_data JSONB.
    Returns {fetched, updated, errors}.
    """
    client = BzzoiroClient()
    log.info("sync_live: fetching live matches")

    data = client.get("/matches/", params={"status": "live", "limit": 100})
    if data is None:
        log.warning("  No data returned from live endpoint")
        return {"fetched": 0, "updated": 0, "errors": 0}

    live_matches = data.get("results") or (data if isinstance(data, list) else [])
    log.info(f"  Got {len(live_matches)} live matches")

    updated = errors = 0

    with conn.cursor() as cur:
        for bzz in live_matches:
            try:
                n = _update_live_match(cur, bzz)
                updated += n
            except Exception as exc:
                errors += 1
                log.error(f"  Live match bzz_id={bzz.get('id')}: {type(exc).__name__}: {exc}")
                try:
                    conn.rollback()
                except Exception:
                    pass

    conn.commit()
    log.info(f"sync_live done: fetched={len(live_matches)} updated={updated} errors={errors}")
    return {"fetched": len(live_matches), "updated": updated, "errors": errors}


def _update_live_match(cur, bzz: dict) -> int:
    """
    Update a live match's event_status, is_live, and live_data.
    Also upserts match_scores from current set data.
    Returns 1 if updated, 0 if match not found in DB.
    """
    bzz_id = bzz.get("id")
    if not bzz_id:
        return 0

    neg_event_key = -abs(int(bzz_id))

    # Build live_data payload with serve stats + current score
    live_data = {
        "current_set": bzz.get("current_set"),
        "current_game": bzz.get("current_game"),
        "current_point": bzz.get("current_point"),
        "player1_sets": bzz.get("player1_sets"),
        "player2_sets": bzz.get("player2_sets"),
        "player1_games": bzz.get("player1_games"),
        "player2_games": bzz.get("player2_games"),
        "serve": bzz.get("serve"),
        "serve_stats": {
            "p1_aces": bzz.get("p1_aces"),
            "p1_double_faults": bzz.get("p1_double_faults"),
            "p1_first_serve_pct": bzz.get("p1_first_serve_pct"),
            "p1_first_serve_won_pct": bzz.get("p1_first_serve_won_pct"),
            "p2_aces": bzz.get("p2_aces"),
            "p2_double_faults": bzz.get("p2_double_faults"),
            "p2_first_serve_pct": bzz.get("p2_first_serve_pct"),
            "p2_first_serve_won_pct": bzz.get("p2_first_serve_won_pct"),
        },
        "synced_at": datetime.utcnow().isoformat(),
    }

    cur.execute(
        """
        UPDATE matches
        SET event_status = 'live',
            is_live      = TRUE,
            live_data    = %s::jsonb,
            updated_at   = NOW()
        WHERE api_event_key = %s
        RETURNING id
        """,
        (json.dumps(live_data), neg_event_key),
    )
    row = cur.fetchone()
    if not row:
        # Match not in DB yet — try to upsert it
        try:
            _upsert_fixture(cur, bzz)
            return 1
        except Exception:
            return 0

    match_id = row["id"]

    # Upsert set scores if available
    sets_detail = bzz.get("sets_detail") or []
    if sets_detail:
        for s in sets_detail:
            set_num = s.get("set") or s.get("set_number")
            p1g = s.get("player1_games")
            p2g = s.get("player2_games")
            if set_num is None or p1g is None or p2g is None:
                continue
            tb_data = s.get("tiebreak")
            is_tb = isinstance(tb_data, dict)
            cur.execute(
                """
                INSERT INTO match_scores (match_id, set_number, score_first, score_second, is_tiebreak)
                VALUES (%s, %s, %s, %s, %s)
                ON CONFLICT (match_id, set_number) DO UPDATE SET
                    score_first  = EXCLUDED.score_first,
                    score_second = EXCLUDED.score_second,
                    is_tiebreak  = EXCLUDED.is_tiebreak
                """,
                (match_id, int(set_num), str(p1g), str(p2g), is_tb),
            )

    return 1


# ─────────────────────────────────────────────────────────────────────────────
# SYNC RANKINGS  (with movement columns)
# ─────────────────────────────────────────────────────────────────────────────

def sync_rankings(conn: psycopg2.extensions.connection) -> dict:
    """
    Fetch ATP and WTA rankings from Bzzoiro.
    Updates players with:
      - current_rank
      - ranking_points
      - ranking_movement  (previous_position - current_position, so positive = moved up)
      - ranking_career_best
    Returns {atp_updated, wta_updated, total}.
    """
    client = BzzoiroClient()
    log.info("sync_rankings: fetching ATP + WTA rankings")
    totals = {}

    for tour in ("ATP", "WTA"):
        rows = client.paginate("/rankings/", params={"type": tour, "limit": 200})
        log.info(f"  {tour}: {len(rows)} ranked players")

        updated = 0
        with conn.cursor() as cur:
            for r in rows:
                try:
                    n = _update_one_ranking(cur, r)
                    updated += n
                except Exception as exc:
                    log.warning(f"  Ranking row failed: {exc}")
                    try:
                        conn.rollback()
                    except Exception:
                        pass

        conn.commit()
        totals[tour.lower() + "_updated"] = updated
        log.info(f"  {tour}: {updated} players updated")

    totals["total"] = sum(v for k, v in totals.items() if k.endswith("_updated"))
    log.info(f"sync_rankings done: {totals['total']} players updated")
    return totals


def _update_one_ranking(cur, r: dict) -> int:
    """Update a single player's ranking fields. Returns 1 if updated, 0 if skipped."""
    p = r.get("player") or {}
    bzz_pid = p.get("id")
    pos = r.get("position") or r.get("rank")
    pts = r.get("points") or r.get("ranking_points")
    prev_pos = r.get("previous_position") or r.get("previous_rank")
    best_pos = r.get("best_position") or r.get("career_best")
    name = (p.get("name") or "").strip()

    if not bzz_pid or pos is None:
        return 0

    # Movement: previous - current (positive = moved up in rankings)
    movement = None
    if prev_pos is not None:
        try:
            movement = int(prev_pos) - int(pos)
        except (TypeError, ValueError):
            pass

    # Resolve player
    cur.execute(
        "SELECT player_id FROM player_external_ids WHERE source = 'bzzoiro' AND external_id = %s",
        (str(bzz_pid),),
    )
    row = cur.fetchone()
    our_player_id = row["player_id"] if row else None

    if our_player_id is None and name:
        cur.execute(
            """
            SELECT id FROM players
            WHERE LOWER(TRIM(full_name)) = LOWER(%s) OR LOWER(TRIM(name)) = LOWER(%s)
            LIMIT 1
            """,
            (name, name),
        )
        row = cur.fetchone()
        if row:
            our_player_id = row["id"]
            # Store external ID for future lookups
            cur.execute(
                """
                INSERT INTO player_external_ids (player_id, source, external_id)
                VALUES (%s, 'bzzoiro', %s)
                ON CONFLICT (player_id, source) DO UPDATE SET external_id = EXCLUDED.external_id
                """,
                (our_player_id, str(bzz_pid)),
            )

    if our_player_id is None:
        return 0

    cur.execute(
        """
        UPDATE players SET
            current_rank       = %s,
            ranking_points     = %s,
            ranking_movement   = %s,
            ranking_career_best = COALESCE(%s, ranking_career_best),
            updated_at         = NOW()
        WHERE id = %s
        """,
        (int(pos), int(pts) if pts is not None else None, movement,
         int(best_pos) if best_pos is not None else None, our_player_id),
    )
    return 1 if cur.rowcount else 0


# ─────────────────────────────────────────────────────────────────────────────
# SYNC ODDS
# ─────────────────────────────────────────────────────────────────────────────

def sync_odds(conn: psycopg2.extensions.connection) -> dict:
    """
    For each upcoming match with a bzzoiro_id, fetch per-bookmaker odds.
    Upserts into bookmaker_odds table.
    Returns {matches_processed, odds_written, errors}.
    """
    client = BzzoiroClient()
    log.info("sync_odds: fetching bzzoiro odds for upcoming matches")

    # Get upcoming matches with bzzoiro_id
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT id, bzzoiro_id, first_player_id, second_player_id
            FROM matches
            WHERE bzzoiro_id IS NOT NULL
              AND event_status NOT IN ('Finished', 'Cancelled', 'Postponed', 'Walkover', 'Retired')
              AND event_date BETWEEN CURRENT_DATE - INTERVAL '1 day' AND CURRENT_DATE + INTERVAL '7 days'
            ORDER BY event_date ASC
            LIMIT 200
            """
        )
        matches = cur.fetchall()

    log.info(f"  {len(matches)} upcoming matches with bzzoiro_id")

    matches_processed = odds_written = errors = 0

    for match in matches:
        match_id = match["id"]
        bzz_id = match["bzzoiro_id"]

        try:
            data = client.get(f"/matches/{bzz_id}/odds/")
            if data is None:
                continue

            n = _write_odds(conn, match_id, data)
            if n > 0:
                matches_processed += 1
                odds_written += n

        except Exception as exc:
            errors += 1
            log.error(f"  Odds fetch failed for match_id={match_id} bzz_id={bzz_id}: {exc}")

    log.info(f"sync_odds done: matches_processed={matches_processed} odds_written={odds_written} errors={errors}")
    return {"matches_processed": matches_processed, "odds_written": odds_written, "errors": errors}


def _write_odds(conn, match_id: int, odds_data: dict) -> int:
    """
    Write bookmaker odds for a match.
    odds_data from /matches/{id}/odds/ contains a list of bookmakers with p1/p2 prices.
    Stores all bookmakers as JSONB in bookmaker_odds metadata field.
    Returns count of rows written.
    """
    bookmakers = odds_data.get("bookmakers") or odds_data.get("odds") or []
    if not bookmakers and isinstance(odds_data, list):
        bookmakers = odds_data

    if not bookmakers:
        return 0

    written = 0
    with conn.cursor() as cur:
        # Store full bookmakers payload as JSONB on first bookmaker row
        all_bookmakers_json = json.dumps(bookmakers)

        for bm in bookmakers:
            bm_name = (
                bm.get("bookmaker") or bm.get("name") or bm.get("bookmaker_key") or ""
            ).lower().replace(" ", "_")
            if not bm_name:
                continue

            p1_odds = bm.get("player1_odds") or bm.get("home_odds") or bm.get("odds_1")
            p2_odds = bm.get("player2_odds") or bm.get("away_odds") or bm.get("odds_2")

            for player_ref, odds_val in [("first_player", p1_odds), ("second_player", p2_odds)]:
                if odds_val is None:
                    continue
                try:
                    decimal_odds = float(odds_val)
                    if decimal_odds <= 1.0:
                        continue
                    implied_prob = round(1.0 / decimal_odds, 6)
                    cur.execute(
                        """
                        INSERT INTO bookmaker_odds
                            (match_id, bookmaker, player_ref, decimal_odds, implied_prob, fetched_at)
                        VALUES (%s, %s, %s, %s, %s, NOW())
                        ON CONFLICT (match_id, bookmaker, player_ref) DO UPDATE SET
                            decimal_odds = EXCLUDED.decimal_odds,
                            implied_prob = EXCLUDED.implied_prob,
                            fetched_at   = EXCLUDED.fetched_at
                        """,
                        (match_id, bm_name, player_ref, decimal_odds, implied_prob),
                    )
                    written += 1
                except (TypeError, ValueError):
                    continue

    if written > 0:
        conn.commit()
    return written


# ─────────────────────────────────────────────────────────────────────────────
# SYNC PREDICTIONS  (O/U markets → bzzoiro_predictions table)
# ─────────────────────────────────────────────────────────────────────────────

def sync_predictions(conn: psycopg2.extensions.connection) -> dict:
    """
    Fetch bzzoiro predictions (O/U markets + match winner) from:
      GET /predictions/?upcoming=true&limit=200
    Stores in bzzoiro_predictions table (supplements our own model_predictions).
    Returns {fetched, written, skipped, errors}.
    """
    client = BzzoiroClient()
    log.info("sync_predictions: fetching bzzoiro O/U predictions")

    preds = client.paginate("/predictions/", params={"upcoming": "true", "limit": 200})
    log.info(f"  Fetched {len(preds)} predictions from Bzzoiro")

    written = skipped = errors = 0

    with conn.cursor() as cur:
        for pred in preds:
            try:
                n = _upsert_bzzoiro_prediction(cur, pred)
                if n:
                    written += 1
                else:
                    skipped += 1
            except Exception as exc:
                errors += 1
                log.error(f"  Prediction bzz_match={pred.get('match')}: {type(exc).__name__}: {exc}")
                try:
                    conn.rollback()
                except Exception:
                    pass

    conn.commit()
    log.info(f"sync_predictions done: fetched={len(preds)} written={written} skipped={skipped} errors={errors}")
    return {"fetched": len(preds), "written": written, "skipped": skipped, "errors": errors}


def _upsert_bzzoiro_prediction(cur, pred: dict) -> bool:
    """
    Upsert a single Bzzoiro prediction into bzzoiro_predictions table.
    Also fetches full prediction detail if needed for O/U fields.
    Returns True if written, False if skipped.
    """
    bzz_pred_id = pred.get("id")
    bzz_match_raw = pred.get("match") or pred.get("match_id")
    if not bzz_match_raw:
        return False
    # "match" may be a nested dict (with id, player1, player2, ...) or a bare int
    if isinstance(bzz_match_raw, dict):
        bzz_match_id = bzz_match_raw.get("id")
    else:
        bzz_match_id = bzz_match_raw
    if not bzz_match_id:
        return False

    neg_event_key = -abs(int(bzz_match_id))

    # Find our internal match_id
    cur.execute(
        "SELECT id FROM matches WHERE api_event_key = %s OR bzzoiro_id = %s",
        (neg_event_key, int(bzz_match_id)),
    )
    row = cur.fetchone()
    our_match_id = row["id"] if row else None

    def _f(key) -> Optional[float]:
        v = pred.get(key)
        return float(v) if v is not None else None

    prob_p1 = _f("prob_player1_wins")
    prob_p2 = _f("prob_player2_wins")
    confidence = _f("confidence")

    # Determine predicted winner
    predicted_winner = None
    if prob_p1 is not None and prob_p2 is not None:
        if prob_p1 > prob_p2:
            predicted_winner = "First Player"
        elif prob_p2 > prob_p1:
            predicted_winner = "Second Player"

    cur.execute(
        """
        INSERT INTO bzzoiro_predictions (
            match_id, bzzoiro_match_id, bzzoiro_prediction_id,
            prob_player1_wins, prob_player2_wins,
            predicted_winner, confidence,
            expected_total_sets, prob_over_2_5_sets,
            expected_total_games, prob_over_20_5_games,
            prob_over_21_5_games, prob_over_22_5_games,
            prob_player1_wins_first_set,
            synced_at
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, NOW())
        ON CONFLICT (bzzoiro_prediction_id) DO UPDATE SET
            prob_player1_wins        = COALESCE(EXCLUDED.prob_player1_wins, bzzoiro_predictions.prob_player1_wins),
            prob_player2_wins        = COALESCE(EXCLUDED.prob_player2_wins, bzzoiro_predictions.prob_player2_wins),
            predicted_winner         = COALESCE(EXCLUDED.predicted_winner, bzzoiro_predictions.predicted_winner),
            confidence               = COALESCE(EXCLUDED.confidence, bzzoiro_predictions.confidence),
            expected_total_sets      = COALESCE(EXCLUDED.expected_total_sets, bzzoiro_predictions.expected_total_sets),
            prob_over_2_5_sets       = COALESCE(EXCLUDED.prob_over_2_5_sets, bzzoiro_predictions.prob_over_2_5_sets),
            expected_total_games     = COALESCE(EXCLUDED.expected_total_games, bzzoiro_predictions.expected_total_games),
            prob_over_20_5_games     = COALESCE(EXCLUDED.prob_over_20_5_games, bzzoiro_predictions.prob_over_20_5_games),
            prob_over_21_5_games     = COALESCE(EXCLUDED.prob_over_21_5_games, bzzoiro_predictions.prob_over_21_5_games),
            prob_over_22_5_games     = COALESCE(EXCLUDED.prob_over_22_5_games, bzzoiro_predictions.prob_over_22_5_games),
            prob_player1_wins_first_set = COALESCE(EXCLUDED.prob_player1_wins_first_set, bzzoiro_predictions.prob_player1_wins_first_set),
            synced_at                = NOW()
        """,
        (
            our_match_id, int(bzz_match_id),
            int(bzz_pred_id) if bzz_pred_id is not None else None,
            prob_p1, prob_p2, predicted_winner, confidence,
            _f("expected_total_sets"), _f("prob_over_2_5_sets"),
            _f("expected_total_games"), _f("prob_over_20_5_games"),
            _f("prob_over_21_5_games"), _f("prob_over_22_5_games"),
            _f("prob_player1_wins_first_set"),
        ),
    )
    return True


def sync_prediction_detail(
    conn: psycopg2.extensions.connection,
    bzzoiro_prediction_id: int,
) -> bool:
    """
    Fetch full prediction detail from /predictions/{id}/ and update bzzoiro_predictions.
    Call this to back-fill O/U fields if they weren't in the list endpoint.
    Returns True if updated.
    """
    client = BzzoiroClient()
    data = client.get(f"/predictions/{bzzoiro_prediction_id}/")
    if data is None:
        return False

    def _f(key):
        v = data.get(key)
        return float(v) if v is not None else None

    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE bzzoiro_predictions SET
                expected_total_sets         = COALESCE(%s, expected_total_sets),
                prob_over_2_5_sets          = COALESCE(%s, prob_over_2_5_sets),
                expected_total_games        = COALESCE(%s, expected_total_games),
                prob_over_20_5_games        = COALESCE(%s, prob_over_20_5_games),
                prob_over_21_5_games        = COALESCE(%s, prob_over_21_5_games),
                prob_over_22_5_games        = COALESCE(%s, prob_over_22_5_games),
                prob_player1_wins_first_set = COALESCE(%s, prob_player1_wins_first_set),
                synced_at                   = NOW()
            WHERE bzzoiro_prediction_id = %s
            """,
            (
                _f("expected_total_sets"), _f("prob_over_2_5_sets"),
                _f("expected_total_games"), _f("prob_over_20_5_games"),
                _f("prob_over_21_5_games"), _f("prob_over_22_5_games"),
                _f("prob_player1_wins_first_set"),
                bzzoiro_prediction_id,
            ),
        )
        updated = cur.rowcount
    conn.commit()
    return bool(updated)


# ─────────────────────────────────────────────────────────────────────────────
# SYNC H2H
# ─────────────────────────────────────────────────────────────────────────────

def sync_h2h(conn: psycopg2.extensions.connection, match_id: int) -> bool:
    """
    Fetch H2H data for a given internal match_id.
    Stores in bzzoiro_h2h table (h2h_data JSONB + last5 per player).
    Returns True if data was stored.
    """
    client = BzzoiroClient()

    with conn.cursor() as cur:
        cur.execute(
            "SELECT bzzoiro_id, first_player_id, second_player_id FROM matches WHERE id = %s",
            (match_id,),
        )
        match = cur.fetchone()

    if not match or not match["bzzoiro_id"]:
        log.warning(f"  sync_h2h: match_id={match_id} has no bzzoiro_id")
        return False

    bzz_id = match["bzzoiro_id"]
    data = client.get(f"/matches/{bzz_id}/h2h/")
    if data is None:
        log.warning(f"  sync_h2h: no H2H data for bzz_id={bzz_id}")
        return False

    h2h_data = data.get("h2h") or data
    player1_last5 = data.get("player1_last5") or data.get("last5_player1") or []
    player2_last5 = data.get("player2_last5") or data.get("last5_player2") or []

    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO bzzoiro_h2h (
                match_id, player1_id, player2_id,
                h2h_data, player1_last5, player2_last5,
                synced_at
            )
            VALUES (%s, %s, %s, %s::jsonb, %s::jsonb, %s::jsonb, NOW())
            ON CONFLICT (match_id) DO UPDATE SET
                h2h_data     = EXCLUDED.h2h_data,
                player1_last5 = EXCLUDED.player1_last5,
                player2_last5 = EXCLUDED.player2_last5,
                synced_at    = NOW()
            """,
            (
                match_id,
                match["first_player_id"],
                match["second_player_id"],
                json.dumps(h2h_data),
                json.dumps(player1_last5),
                json.dumps(player2_last5),
            ),
        )
    conn.commit()
    log.info(f"  sync_h2h: stored H2H for match_id={match_id} bzz_id={bzz_id}")
    return True


def sync_h2h_upcoming(conn: psycopg2.extensions.connection) -> dict:
    """
    Sync H2H for all upcoming matches with bzzoiro_id that don't have H2H yet.
    Returns {processed, written, errors}.
    """
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT m.id
            FROM matches m
            LEFT JOIN bzzoiro_h2h h ON h.match_id = m.id
            WHERE m.bzzoiro_id IS NOT NULL
              AND m.event_status NOT IN ('Finished', 'Cancelled', 'Postponed', 'Walkover')
              AND m.event_date BETWEEN CURRENT_DATE AND CURRENT_DATE + INTERVAL '3 days'
              AND h.id IS NULL
            ORDER BY m.event_date ASC
            LIMIT 50
            """
        )
        matches = cur.fetchall()

    processed = written = errors = 0
    for match in matches:
        processed += 1
        try:
            ok = sync_h2h(conn, match["id"])
            if ok:
                written += 1
        except Exception as exc:
            errors += 1
            log.error(f"  H2H sync failed for match_id={match['id']}: {exc}")

    return {"processed": processed, "written": written, "errors": errors}


# ─────────────────────────────────────────────────────────────────────────────
# CLI ENTRY POINT
# ─────────────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="ratethat.tennis bzzoiro pipeline")
    parser.add_argument(
        "--job",
        choices=["fixtures", "live", "rankings", "odds", "predictions", "h2h", "all"],
        default="all",
        help="Which job to run (default: all)",
    )
    parser.add_argument(
        "--days-ahead",
        type=int,
        default=7,
        help="Days ahead for fixture fetch (default: 7)",
    )
    args = parser.parse_args()

    conn = get_db_conn()
    log.info(f"Connected to database. Running bzzoiro job: {args.job}")

    try:
        if args.job in ("fixtures", "all"):
            result = sync_fixtures(conn, days_ahead=args.days_ahead)
            log.info(f"fixtures: {result}")

        if args.job in ("live", "all"):
            result = sync_live(conn)
            log.info(f"live: {result}")

        if args.job in ("rankings", "all"):
            result = sync_rankings(conn)
            log.info(f"rankings: {result}")

        if args.job in ("odds", "all"):
            result = sync_odds(conn)
            log.info(f"odds: {result}")

        if args.job in ("predictions", "all"):
            result = sync_predictions(conn)
            log.info(f"predictions: {result}")

        if args.job in ("h2h", "all"):
            result = sync_h2h_upcoming(conn)
            log.info(f"h2h: {result}")

    except KeyboardInterrupt:
        log.info("Interrupted")
    finally:
        conn.close()
        log.info("Done.")


if __name__ == "__main__":
    main()
