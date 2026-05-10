#!/usr/bin/env python3
"""
ratethat.tennis — Data Pipeline
Fetches data from api-tennis.com and upserts into PostgreSQL.

Usage:
    python pipeline.py --job daily_fixtures        # fetch today's fixtures
    python pipeline.py --job daily_fixtures --date 2026-05-01
    python pipeline.py --job sync_event_types       # one-time: load all event types
    python pipeline.py --job sync_tournaments       # sync all tournaments
    python pipeline.py --job livescore              # fetch live matches (run every 2 min)
    python pipeline.py --job all                    # run daily_fixtures + livescore
"""

import os
import sys
import json
import time
import logging
import argparse
import requests
import psycopg2
import psycopg2.extras
from datetime import date, datetime, timedelta
from typing import Optional

# ─────────────────────────────────────────────
# CONFIG
# ─────────────────────────────────────────────

API_KEY  = os.environ.get("API_TENNIS_KEY", "7b2c30d69f93cbbaa699c7a65483e620ec4bf53adc0a105eb9d38876d307002a")
API_BASE = "https://api.api-tennis.com/tennis"
DB_URL   = (os.environ.get("DATABASE_PUBLIC_URL") or
            os.environ.get("DATABASE_URL") or
            "postgresql://postgres:DEKANqBEjmOvOGLCfzaQIBaKzhKcyKwS@switchyard.proxy.rlwy.net:39343/railway").strip()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)]
)
log = logging.getLogger("rtt-pipeline")

# Surface name normalisation
SURFACE_MAP = {
    "clay": "Clay", "hard": "Hard", "grass": "Grass",
    "carpet": "Carpet", "indoor hard": "Indoor Hard",
    "indoor clay": "Indoor Clay", "acrylic": "Hard",
}

# Tour category extraction from event_type_type string
def classify_event_type(type_str: str) -> tuple[str, str, bool]:
    """Returns (tour_category, gender, is_doubles)"""
    t = type_str.lower()
    is_doubles = "double" in t
    if "atp" in t:
        return "ATP", "Men", is_doubles
    if "wta" in t:
        return "WTA", "Women", is_doubles
    if "challenger men" in t:
        return "Challenger", "Men", is_doubles
    if "challenger women" in t:
        return "Challenger", "Women", is_doubles
    if "itf men" in t:
        return "ITF", "Men", is_doubles
    if "itf women" in t:
        return "ITF", "Women", is_doubles
    if "boys" in t:
        return "Junior", "Men", is_doubles
    if "girls" in t:
        return "Junior", "Women", is_doubles
    if "mixed" in t:
        return "Mixed", "Mixed", is_doubles
    if "exhibition" in t:
        return "Exhibition", "Mixed", is_doubles
    if "teams" in t:
        return "Teams", "Mixed", is_doubles
    return "Other", "Unknown", is_doubles


# ─────────────────────────────────────────────
# API CLIENT
# ─────────────────────────────────────────────

class TennisAPI:
    def __init__(self, api_key: str, rate_limit_delay: float = 0.5):
        self.api_key = api_key
        self.delay   = rate_limit_delay
        self.session = requests.Session()
        self._calls  = 0

    def _get(self, method: str, **params) -> dict:
        params["APIkey"] = self.api_key
        params["method"] = method
        try:
            resp = self.session.get(API_BASE, params=params, timeout=30)
            resp.raise_for_status()
            self._calls += 1
            time.sleep(self.delay)
            data = resp.json()
            if data.get("error"):
                log.warning(f"API error for {method}: {data}")
                return {}
            return data
        except Exception as e:
            log.error(f"API call failed [{method}]: {e}")
            return {}

    def get_events(self) -> list:
        data = self._get("get_events")
        return data.get("result", [])

    def get_tournaments(self, event_type: Optional[int] = None) -> list:
        kwargs = {}
        if event_type:
            kwargs["event_type"] = event_type
        data = self._get("get_tournaments", **kwargs)
        return data.get("result", [])

    def get_fixtures(self, date_start: str, date_stop: str) -> list:
        data = self._get("get_fixtures", date_start=date_start, date_stop=date_stop)
        return data.get("result", [])

    def get_livescore(self) -> list:
        data = self._get("get_livescore")
        return data.get("result", [])

    def get_player(self, player_key: int) -> Optional[dict]:
        data = self._get("get_players", player_key=player_key)
        results = data.get("result", [])
        return results[0] if results else None

    @property
    def calls_made(self) -> int:
        return self._calls


# ─────────────────────────────────────────────
# DATABASE HELPERS
# ─────────────────────────────────────────────

def get_db_conn():
    if not DB_URL:
        raise ValueError("DATABASE_URL environment variable not set")
    conn = psycopg2.connect(DB_URL, cursor_factory=psycopg2.extras.RealDictCursor)
    conn.autocommit = False
    return conn


def get_surface_id(cur, surface_name: str) -> int:
    name = SURFACE_MAP.get(surface_name.lower(), "Unknown") if surface_name else "Unknown"
    cur.execute("SELECT id FROM surfaces WHERE name = %s", (name,))
    row = cur.fetchone()
    if row:
        return row["id"]
    cur.execute("INSERT INTO surfaces (name) VALUES (%s) ON CONFLICT (name) DO NOTHING RETURNING id", (name,))
    row = cur.fetchone()
    if row:
        return row["id"]
    cur.execute("SELECT id FROM surfaces WHERE name = %s", (name,))
    return cur.fetchone()["id"]


def upsert_event_type(cur, api_key: int, type_name: str) -> int:
    cat, gender, is_doubles = classify_event_type(type_name)
    cur.execute("""
        INSERT INTO event_types (api_key, type_name, tour_category, gender, is_doubles)
        VALUES (%s, %s, %s, %s, %s)
        ON CONFLICT (api_key) DO UPDATE SET
            type_name     = EXCLUDED.type_name,
            tour_category = EXCLUDED.tour_category,
            gender        = EXCLUDED.gender,
            is_doubles    = EXCLUDED.is_doubles
        RETURNING id
    """, (api_key, type_name, cat, gender, is_doubles))
    return cur.fetchone()["id"]


def upsert_tournament(cur, api_key: int, name: str, event_type_id: int, surface_id: int) -> int:
    """
    Upsert a tournament keyed on api_key.

    Surface preservation: api-tennis.com doesn't ship a surface field on
    tournament objects, so the daily_fixtures and livescore paths always
    pass surface_id = "Unknown". The real surface is filled in afterwards
    by pipeline.surface_backfill (Madrid → Clay, Wimbledon → Grass, etc.).
    Without the CASE below, every livescore tick (every 5 minutes) would
    overwrite the backfilled value back to "Unknown". So: only overwrite
    surface_id when the incoming value is NOT Unknown — i.e. the caller
    actually has new information.
    """
    cur.execute("""
        INSERT INTO tournaments (api_key, name, event_type_id, surface_id)
        VALUES (%s, %s, %s, %s)
        ON CONFLICT (api_key) DO UPDATE SET
            name          = EXCLUDED.name,
            event_type_id = EXCLUDED.event_type_id,
            surface_id    = CASE
                              WHEN EXCLUDED.surface_id IS NULL
                                THEN tournaments.surface_id
                              WHEN (SELECT name FROM surfaces WHERE id = EXCLUDED.surface_id) = 'Unknown'
                                   AND tournaments.surface_id IS NOT NULL
                                   AND (SELECT name FROM surfaces WHERE id = tournaments.surface_id) <> 'Unknown'
                                THEN tournaments.surface_id
                              ELSE EXCLUDED.surface_id
                            END,
            updated_at    = NOW()
        RETURNING id
    """, (api_key, name.strip(), event_type_id, surface_id))
    return cur.fetchone()["id"]


def upsert_player(cur, api_key: int, name: str, logo_url: Optional[str] = None) -> int:
    """
    Resolve `(api_key, name)` to a `players.id`.

    Resolution order:
      1. Existing row with this api_key → return that id (the api_key is
         the primary upstream identifier for this provider).
      2. No api_key match, but an existing row matches by NORMALISED name
         (lower-case, diacritics stripped, whitespace collapsed) → return that
         existing id WITHOUT inserting a new row. This prevents duplicate
         player records when api-tennis.com hands us a different api_key for
         the same physical player (typically a diacritic spelling variant).
      3. Otherwise — insert a fresh row.
    """
    # 1. Direct api_key lookup.
    cur.execute("""
        UPDATE players
           SET name       = COALESCE(%s, name),
               logo_url   = COALESCE(%s, logo_url),
               updated_at = NOW()
         WHERE api_key = %s
         RETURNING id
    """, (name, logo_url, api_key))
    row = cur.fetchone()
    if row:
        return row["id"]

    # 2. Normalised-name fallback — prevents diacritic-driven duplicates.
    if name:
        try:
            from pipeline.merge_duplicate_players import normalise_name
        except ImportError:
            from merge_duplicate_players import normalise_name  # when running from /app
        norm = normalise_name(name)
        if norm:
            # Compare normalisation server-side via Python-equivalent SQL.
            # Postgres: lower(unaccent(name)) ≈ Python normalise_name(name).
            # We build the candidate set via a less-strict LIKE filter then
            # confirm in Python to avoid requiring the unaccent extension.
            base = norm.split(" ")[-1] if " " in norm else norm
            like_param = f"%{base}%"
            cur.execute("""
                SELECT id, name FROM players
                 WHERE LENGTH(name) > 0
                   AND LOWER(name) LIKE %s
                 LIMIT 25
            """, (like_param,))
            for cand in cur.fetchall():
                if normalise_name(cand["name"]) == norm:
                    return cand["id"]

    # 3. Brand-new player — insert.
    cur.execute("""
        INSERT INTO players (api_key, name, logo_url)
        VALUES (%s, %s, %s)
        ON CONFLICT (api_key) DO UPDATE SET
            name       = COALESCE(EXCLUDED.name, players.name),
            logo_url   = COALESCE(EXCLUDED.logo_url, players.logo_url),
            updated_at = NOW()
        RETURNING id
    """, (api_key, name, logo_url))
    return cur.fetchone()["id"]


def upsert_match(cur, event: dict, tournament_id: int, event_type_id: int,
                 p1_id: int, p2_id: int) -> tuple[int, bool]:
    """Returns (match_id, was_inserted)"""
    raw = json.dumps(event)
    is_live = event.get("event_live") == "1"
    is_qual = (event.get("event_qualification") or "False").lower() == "true"
    is_doubles = "double" in (event.get("event_type_type") or "").lower()

    cur.execute("""
        INSERT INTO matches (
            api_event_key, tournament_id, event_type_id,
            first_player_id, second_player_id,
            event_date, event_time, tournament_round, season,
            is_qualification, is_doubles,
            final_result, game_result, serve, winner, event_status,
            is_live, raw_json
        ) VALUES (
            %s, %s, %s, %s, %s,
            %s, %s, %s, %s,
            %s, %s,
            %s, %s, %s, %s, %s,
            %s, %s::jsonb
        )
        ON CONFLICT (api_event_key) DO UPDATE SET
            tournament_id    = EXCLUDED.tournament_id,
            first_player_id  = EXCLUDED.first_player_id,
            second_player_id = EXCLUDED.second_player_id,
            final_result     = EXCLUDED.final_result,
            game_result      = EXCLUDED.game_result,
            serve            = EXCLUDED.serve,
            winner           = EXCLUDED.winner,
            event_status     = EXCLUDED.event_status,
            is_live          = EXCLUDED.is_live,
            raw_json         = EXCLUDED.raw_json,
            updated_at       = NOW()
        RETURNING id, (xmax = 0) AS inserted
    """, (
        event["event_key"], tournament_id, event_type_id,
        p1_id, p2_id,
        event["event_date"],
        event.get("event_time") or None,
        event.get("tournament_round"),
        event.get("tournament_season"),
        is_qual, is_doubles,
        event.get("event_final_result"),
        event.get("event_game_result"),
        event.get("event_serve"),
        event.get("event_winner"),
        event.get("event_status"),
        is_live, raw
    ))
    row = cur.fetchone()
    return row["id"], row["inserted"]


def upsert_scores(cur, match_id: int, scores: list):
    """Upsert set-by-set scores for a match."""
    for score in scores:
        set_num = score.get("score_set")
        s1 = str(score.get("score_first", ""))
        s2 = str(score.get("score_second", ""))
        is_tb = "." in s1 or "." in s2  # tiebreak scores come as "7.6" etc.
        cur.execute("""
            INSERT INTO match_scores (match_id, set_number, score_first, score_second, is_tiebreak)
            VALUES (%s, %s, %s, %s, %s)
            ON CONFLICT (match_id, set_number) DO UPDATE SET
                score_first  = EXCLUDED.score_first,
                score_second = EXCLUDED.score_second,
                is_tiebreak  = EXCLUDED.is_tiebreak
        """, (match_id, set_num, s1, s2, is_tb))


def upsert_pointbypoint(cur, match_id: int, pbp: list):
    """Upsert point-by-point game and point data."""
    for game_data in pbp:
        set_num  = game_data.get("set_number", "").replace("Set ", "")
        game_num = game_data.get("number_game")
        try:
            set_num  = int(set_num)
            game_num = int(game_num)
        except (ValueError, TypeError):
            continue

        cur.execute("""
            INSERT INTO match_games (match_id, set_number, game_number, player_served, serve_winner, score_after)
            VALUES (%s, %s, %s, %s, %s, %s)
            ON CONFLICT (match_id, set_number, game_number) DO UPDATE SET
                player_served = EXCLUDED.player_served,
                serve_winner  = EXCLUDED.serve_winner,
                score_after   = EXCLUDED.score_after
            RETURNING id
        """, (
            match_id, set_num, game_num,
            game_data.get("player_served"),
            game_data.get("serve_winner"),
            game_data.get("score"),
        ))
        game_id_row = cur.fetchone()
        if not game_id_row:
            continue
        game_id = game_id_row["id"]

        for point in game_data.get("points", []):
            pt_num = point.get("number_point")
            cur.execute("""
                INSERT INTO match_points (game_id, match_id, point_number, score, is_break_point, is_set_point, is_match_point)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (game_id, point_number) DO UPDATE SET
                    score          = EXCLUDED.score,
                    is_break_point = EXCLUDED.is_break_point,
                    is_set_point   = EXCLUDED.is_set_point,
                    is_match_point = EXCLUDED.is_match_point
            """, (
                game_id, match_id, pt_num,
                point.get("score"),
                bool(point.get("break_point")),
                bool(point.get("set_point")),
                bool(point.get("match_point")),
            ))


# ─────────────────────────────────────────────
# PIPELINE JOBS
# ─────────────────────────────────────────────

def process_events(cur, api: TennisAPI, events: list) -> tuple[int, int]:
    """Process a list of fixture/livescore events. Returns (inserted, updated)."""
    inserted = updated = 0

    # Pre-cache event types we've seen this run
    et_cache = {}
    t_cache  = {}

    for event in events:
        try:
            # Event type
            et_api_key  = None  # not available per-event; resolve from type string
            et_type_str = event.get("event_type_type") or "Unknown"
            t_api_key   = event.get("tournament_key")
            t_name      = event.get("tournament_name") or "Unknown"

            # We need event_type from tournaments table — look up or create
            if t_api_key not in t_cache:
                # Resolve surface
                surface_id = get_surface_id(cur, "Unknown")  # not in fixture; set when syncing tournaments

                # Resolve event type from string
                if et_type_str not in et_cache:
                    # We don't have api_key for event type in fixture data, so use name as key
                    cur.execute("SELECT id FROM event_types WHERE type_name = %s", (et_type_str,))
                    row = cur.fetchone()
                    if row:
                        et_cache[et_type_str] = row["id"]
                    else:
                        # Create with placeholder key (negative to avoid collision)
                        cat, gender, is_doubles = classify_event_type(et_type_str)
                        cur.execute("""
                            INSERT INTO event_types (api_key, type_name, tour_category, gender, is_doubles)
                            VALUES (-(nextval('event_types_id_seq')), %s, %s, %s, %s)
                            ON CONFLICT DO NOTHING
                            RETURNING id
                        """, (et_type_str, cat, gender, is_doubles))
                        r = cur.fetchone()
                        if r:
                            et_cache[et_type_str] = r["id"]
                        else:
                            cur.execute("SELECT id FROM event_types WHERE type_name = %s", (et_type_str,))
                            et_cache[et_type_str] = cur.fetchone()["id"]

                et_id = et_cache[et_type_str]
                t_cache[t_api_key] = upsert_tournament(cur, t_api_key, t_name, et_id, surface_id)

            tournament_id  = t_cache[t_api_key]
            et_id          = et_cache.get(et_type_str, 1)

            # Players
            p1_id = upsert_player(cur, event["first_player_key"],  event["event_first_player"],
                                   event.get("event_first_player_logo"))
            p2_id = upsert_player(cur, event["second_player_key"], event["event_second_player"],
                                   event.get("event_second_player_logo"))

            # Match
            match_id, was_inserted = upsert_match(cur, event, tournament_id, et_id, p1_id, p2_id)
            if was_inserted:
                inserted += 1
            else:
                updated += 1

            # Scores
            if event.get("scores"):
                upsert_scores(cur, match_id, event["scores"])

            # Point by point (live data)
            if event.get("pointbypoint"):
                upsert_pointbypoint(cur, match_id, event["pointbypoint"])

        except Exception as e:
            log.error(f"Error processing event {event.get('event_key')}: {e}")
            continue

    return inserted, updated


def job_sync_event_types(api: TennisAPI, conn) -> dict:
    log.info("Syncing event types...")
    events = api.get_events()
    cur = conn.cursor()
    count = 0
    for e in events:
        upsert_event_type(cur, e["event_type_key"], e["event_type_type"])
        count += 1
    conn.commit()
    log.info(f"Synced {count} event types")
    return {"records": count}


def job_sync_tournaments(api: TennisAPI, conn) -> dict:
    log.info("Syncing all tournaments...")
    cur = conn.cursor()

    # Get all event types from DB first
    cur.execute("SELECT id, api_key, type_name FROM event_types WHERE api_key > 0")
    et_rows = cur.fetchall()

    total = 0
    for et in et_rows:
        tournaments = api.get_tournaments(event_type=et["api_key"])
        for t in tournaments:
            surface_id = get_surface_id(cur, t.get("tournament_sourface", ""))
            upsert_tournament(cur, t["tournament_key"], t["tournament_name"], et["id"], surface_id)
            total += 1
        conn.commit()
        log.info(f"  Synced {len(tournaments)} tournaments for {et['type_name']}")

    log.info(f"Total tournaments synced: {total}")
    return {"records": total}


def job_daily_fixtures(api: TennisAPI, conn, target_date: date) -> dict:
    # Fetch a 3-day window — the api-tennis.com API requires a range to return results
    date_start = target_date
    date_stop  = target_date + timedelta(days=2)
    log.info(f"Fetching fixtures for {date_start} to {date_stop}...")

    events = api.get_fixtures(
        date_start.strftime("%Y-%m-%d"),
        date_stop.strftime("%Y-%m-%d"),
    )
    log.info(f"  Got {len(events)} events from API")

    cur = conn.cursor()
    inserted, updated = process_events(cur, api, events)
    conn.commit()

    log.info(f"  Inserted: {inserted}, Updated: {updated}")
    return {"fetched": len(events), "inserted": inserted, "updated": updated}


def job_livescore(api: TennisAPI, conn) -> dict:
    log.info("Fetching livescore...")
    events = api.get_livescore()
    log.info(f"  Got {len(events)} live events")

    cur = conn.cursor()
    inserted, updated = process_events(cur, api, events)
    conn.commit()

    log.info(f"  Inserted: {inserted}, Updated: {updated}")
    return {"fetched": len(events), "inserted": inserted, "updated": updated}


# ─────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────

def run_job(job_name: str, target_date: Optional[date] = None):
    api  = TennisAPI(API_KEY)
    conn = get_db_conn()

    cur = conn.cursor()
    cur.execute("""
        INSERT INTO pipeline_runs (job_type, target_date, status)
        VALUES (%s, %s, 'running')
        RETURNING id
    """, (job_name, target_date))
    run_id = cur.fetchone()["id"]
    conn.commit()

    try:
        if job_name == "sync_event_types":
            result = job_sync_event_types(api, conn)
        elif job_name == "sync_tournaments":
            result = job_sync_tournaments(api, conn)
        elif job_name == "daily_fixtures":
            d = target_date or date.today()
            result = job_daily_fixtures(api, conn, d)
        elif job_name == "livescore":
            result = job_livescore(api, conn)
        elif job_name == "all":
            r1 = job_daily_fixtures(api, conn, target_date or date.today())
            r2 = job_livescore(api, conn)
            result = {**r1, "live_fetched": r2["fetched"], "live_inserted": r2["inserted"]}
        else:
            raise ValueError(f"Unknown job: {job_name}")

        cur = conn.cursor()
        cur.execute("""
            UPDATE pipeline_runs SET
                status          = 'success',
                completed_at    = NOW(),
                records_fetched = %s,
                records_inserted= %s,
                records_updated = %s,
                api_calls_made  = %s,
                metadata        = %s::jsonb
            WHERE id = %s
        """, (
            result.get("fetched", 0),
            result.get("inserted", 0),
            result.get("updated", 0),
            api.calls_made,
            json.dumps(result),
            run_id
        ))
        conn.commit()
        log.info(f"Job '{job_name}' completed successfully: {result}")

    except Exception as e:
        log.error(f"Job '{job_name}' failed: {e}")
        cur = conn.cursor()
        cur.execute("""
            UPDATE pipeline_runs SET
                status        = 'failed',
                completed_at  = NOW(),
                error_message = %s,
                api_calls_made= %s
            WHERE id = %s
        """, (str(e), api.calls_made, run_id))
        conn.commit()
        raise
    finally:
        conn.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="ratethat.tennis data pipeline")
    parser.add_argument("--job", required=True,
                        choices=["sync_event_types", "sync_tournaments", "daily_fixtures",
                                 "livescore", "all"],
                        help="Pipeline job to run")
    parser.add_argument("--date", default=None,
                        help="Target date for daily_fixtures (YYYY-MM-DD). Defaults to today.")
    args = parser.parse_args()

    target = None
    if args.date:
        target = datetime.strptime(args.date, "%Y-%m-%d").date()

    run_job(args.job, target)
