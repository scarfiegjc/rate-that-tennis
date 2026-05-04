"""
ratethat.tennis — api-tennis player roster sync
=================================================
Enriches the production `players` table by calling api-tennis's get_players
endpoint for any player whose record is incomplete (missing hand, full_name,
birthday, or country_code). Optionally discovers new players via the
get_players(tournament_key=...) call so the roster grows beyond just match
participants.

Run:
    python3 -m pipeline.player_sync                  # enrich existing players
    python3 -m pipeline.player_sync --tournaments    # also discover via tournaments

Idempotent. Each player api call is one API request (rate-limited at 0.5s).
"""

from __future__ import annotations

import argparse
import logging
import os
import time
from datetime import date
from typing import Optional

import psycopg2
import psycopg2.extras
import requests

log = logging.getLogger("rtt-player-sync")
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")


API_KEY = os.environ.get(
    "API_TENNIS_KEY",
    "7b2c30d69f93cbbaa699c7a65483e620ec4bf53adc0a105eb9d38876d307002a",
)
API_BASE = "https://api.api-tennis.com/tennis"
DB_URL = (
    os.environ.get("DATABASE_PUBLIC_URL")
    or os.environ.get("DATABASE_URL")
    or "postgresql://postgres:DEKANqBEjmOvOGLCfzaQIBaKzhKcyKwS@switchyard.proxy.rlwy.net:39343/railway"
).strip()

RATE_LIMIT_DELAY = 0.4    # seconds between API calls
MAX_PER_RUN      = 600    # safety cap so we don't burn an entire daily quota


# ─────────────────────────────────────────────────────────────────────────────
# api-tennis client
# ─────────────────────────────────────────────────────────────────────────────

class TennisAPI:
    def __init__(self, api_key: str = API_KEY):
        self.api_key = api_key
        self.session = requests.Session()
        self._calls = 0

    def _get(self, method: str, **params) -> dict:
        params["APIkey"] = self.api_key
        params["method"] = method
        try:
            resp = self.session.get(API_BASE, params=params, timeout=30)
            resp.raise_for_status()
            self._calls += 1
            time.sleep(RATE_LIMIT_DELAY)
            return resp.json()
        except Exception as e:
            log.warning(f"  api call {method} failed: {e}")
            return {}

    def get_player(self, player_key: int) -> Optional[dict]:
        data = self._get("get_players", player_key=player_key)
        results = data.get("result", [])
        return results[0] if results else None

    def get_players_by_tournament(self, tournament_key: int) -> list:
        data = self._get("get_players", tournament_key=tournament_key)
        return data.get("result", []) or []


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _normalise_hand(raw: Optional[str]) -> Optional[str]:
    if not raw:
        return None
    s = str(raw).strip().lower()
    if s.startswith("r"):
        return "Right"
    if s.startswith("l"):
        return "Left"
    return None


def _normalise_birthday(raw: Optional[str]) -> Optional[date]:
    if not raw:
        return None
    raw = str(raw).strip()
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d.%m.%Y", "%d-%m-%Y", "%Y/%m/%d"):
        try:
            from datetime import datetime
            return datetime.strptime(raw, fmt).date()
        except ValueError:
            continue
    return None


def _normalise_height(raw) -> Optional[int]:
    if raw is None or raw == "":
        return None
    try:
        h = int(str(raw).replace("cm", "").strip())
        return h if 130 <= h <= 230 else None
    except Exception:
        return None


def _to_int(raw) -> Optional[int]:
    if raw is None or raw == "":
        return None
    try:
        return int(str(raw).strip())
    except Exception:
        return None


# ─────────────────────────────────────────────────────────────────────────────
# Upsert
# ─────────────────────────────────────────────────────────────────────────────

def _upsert_enrichment(cur, api_key: int, p: dict) -> bool:
    """
    Apply enrichment fields to an existing player row, only filling NULLs.
    Returns True if any field was updated.
    """
    full_name = (p.get("player_name") or p.get("event_first_player") or "").strip() or None
    country   = (p.get("player_country") or "").strip() or None
    hand      = _normalise_hand(p.get("player_hand") or p.get("hand"))
    birthday  = _normalise_birthday(p.get("player_bday") or p.get("birthday"))
    height    = _normalise_height(p.get("player_height") or p.get("height"))
    turned_pro = _to_int(p.get("player_turned_pro") or p.get("turned_pro"))
    logo      = (p.get("player_logo") or p.get("logo_url") or "").strip() or None

    cur.execute(
        """
        UPDATE players SET
            full_name   = COALESCE(full_name, %s),
            country     = COALESCE(country, %s),
            hand        = COALESCE(NULLIF(hand,''), CASE WHEN hand = 'Unknown' THEN NULL ELSE hand END, %s),
            birthday    = COALESCE(birthday, %s),
            height_cm   = COALESCE(height_cm, %s),
            turned_pro  = COALESCE(turned_pro, %s),
            logo_url    = COALESCE(logo_url, %s),
            updated_at  = NOW()
        WHERE api_key = %s
        """,
        (full_name, country, hand, birthday, height, turned_pro, logo, api_key),
    )
    return cur.rowcount > 0


def _insert_or_get_id(cur, api_key: int, name: str) -> Optional[int]:
    cur.execute(
        """
        INSERT INTO players (api_key, name)
        VALUES (%s, %s)
        ON CONFLICT (api_key) DO UPDATE SET
            name = COALESCE(EXCLUDED.name, players.name),
            updated_at = NOW()
        RETURNING id
        """,
        (api_key, name),
    )
    row = cur.fetchone()
    return row[0] if row else None


# ─────────────────────────────────────────────────────────────────────────────
# Phase 1 — enrich existing players missing data
# ─────────────────────────────────────────────────────────────────────────────

def enrich_existing(conn, max_calls: int = MAX_PER_RUN) -> dict:
    """For every player missing hand/full_name/birthday/country, fetch from API."""
    log.info(f"Enriching existing players (max {max_calls} api calls)…")
    prev_autocommit = conn.autocommit
    conn.autocommit = True

    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(
            """
            SELECT id, api_key, name, full_name, hand, birthday, height_cm
            FROM players
            WHERE api_key IS NOT NULL
              AND (
                   full_name IS NULL
                OR hand IS NULL OR hand = '' OR hand = 'Unknown'
                OR birthday IS NULL
                OR height_cm IS NULL
              )
            ORDER BY updated_at NULLS FIRST
            LIMIT %s
            """,
            (max_calls,),
        )
        candidates = cur.fetchall()

    log.info(f"  {len(candidates)} players need enrichment")
    if not candidates:
        conn.autocommit = prev_autocommit
        return {"checked": 0, "enriched": 0}

    api = TennisAPI()
    enriched = 0

    for p in candidates:
        try:
            data = api.get_player(p["api_key"])
            if not data:
                continue
            with conn.cursor() as cur:
                if _upsert_enrichment(cur, p["api_key"], data):
                    enriched += 1
        except Exception as e:
            log.warning(f"  player {p['api_key']} ({p['name']}): {e}")
            continue

    conn.autocommit = prev_autocommit
    log.info(f"  ✅ Enriched {enriched} of {len(candidates)} players  ({api._calls} api calls)")
    return {"checked": len(candidates), "enriched": enriched, "api_calls": api._calls}


# ─────────────────────────────────────────────────────────────────────────────
# Phase 2 — discover new players via tournaments
# ─────────────────────────────────────────────────────────────────────────────

def discover_via_tournaments(conn, tournaments_limit: int = 200) -> dict:
    """
    For each tournament with recent or upcoming activity, call get_players
    with tournament_key and upsert any player we don't yet have.
    """
    log.info(f"Discovering players from up to {tournaments_limit} tournaments…")
    prev_autocommit = conn.autocommit
    conn.autocommit = True

    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(
            """
            SELECT DISTINCT t.api_key, t.name
            FROM tournaments t
            JOIN matches m ON m.tournament_id = t.id
            WHERE m.event_date >= CURRENT_DATE - INTERVAL '6 months'
            ORDER BY t.api_key DESC
            LIMIT %s
            """,
            (tournaments_limit,),
        )
        tournaments = cur.fetchall()

    log.info(f"  {len(tournaments)} tournaments to scan")
    if not tournaments:
        conn.autocommit = prev_autocommit
        return {"new": 0, "tournaments": 0}

    api = TennisAPI()
    new_players = 0
    tour_ok = 0

    for t in tournaments:
        try:
            players = api.get_players_by_tournament(t["api_key"])
            if not players:
                continue
            tour_ok += 1
            for p in players:
                api_key = _to_int(p.get("player_key"))
                name = (p.get("player_name") or "").strip()
                if not api_key or not name:
                    continue
                with conn.cursor() as cur:
                    cur.execute(
                        "SELECT 1 FROM players WHERE api_key = %s",
                        (api_key,),
                    )
                    exists = cur.fetchone() is not None
                with conn.cursor() as cur:
                    pid = _insert_or_get_id(cur, api_key, name)
                if not exists and pid:
                    new_players += 1
                # Always run enrichment — first time fills in everything.
                with conn.cursor() as cur:
                    _upsert_enrichment(cur, api_key, p)
        except Exception as e:
            log.warning(f"  tournament {t['api_key']} ({t['name']}): {e}")
            continue

    conn.autocommit = prev_autocommit
    log.info(f"  ✅ {new_players} new players added across {tour_ok} tournaments  "
             f"({api._calls} api calls)")
    return {"new": new_players, "tournaments_scanned": tour_ok, "api_calls": api._calls}


# ─────────────────────────────────────────────────────────────────────────────
# Public entry — run both phases
# ─────────────────────────────────────────────────────────────────────────────

def run_full_sync(conn, do_tournaments: bool = False) -> dict:
    out: dict = {}
    out["enrich"] = enrich_existing(conn)
    if do_tournaments:
        out["discover"] = discover_via_tournaments(conn)
    return out


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--tournaments", action="store_true",
                        help="Also discover new players via tournament rosters")
    args = parser.parse_args()

    conn = psycopg2.connect(DB_URL)
    try:
        run_full_sync(conn, do_tournaments=args.tournaments)
    finally:
        conn.close()


if __name__ == "__main__":
    main()
