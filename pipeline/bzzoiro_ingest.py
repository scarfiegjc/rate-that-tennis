#!/usr/bin/env python3
"""
ratethat.tennis — Bzzoiro Tennis API Ingestion
===============================================
Pulls match fixtures, serve stats, win predictions, ATP/WTA rankings, and
player bio data from the Bzzoiro tennis v2 API and upserts them into the
production PostgreSQL database.

This is the file that api/main.py already expects to import from.  All four
admin endpoints (/admin/bzzoiro-matches, /admin/bzzoiro-live,
/admin/bzzoiro-matches/status, /admin/bzzoiro-bios) call functions exported
from this module.

Public API (callable from api/main.py)
---------------------------------------
    get_db_conn()
    sync_matches(conn, date_from, date_to)   → dict(inserted, updated, serve_stats_written)
    sync_predictions(conn, date_from, date_to) → int  (predictions written)
    sync_rankings(conn)                        → int  (players updated)
    sync_player_bios(conn)                     → int  (players updated)

Conventions
-----------
- Bzzoiro match IDs are stored in matches.api_event_key as -abs(bzz_id)
  (negative namespace to avoid collision with api-tennis.com positive keys).
- Player records are resolved via the player_external_ids table (source='bzzoiro').
  If no match is found, a new players row is created and the external_id is stored.
- All DB writes use ON CONFLICT DO UPDATE (idempotent — safe to rerun).

Environment variables
---------------------
    BZZOIRO_API_KEY   — Bzzoiro token (falls back to hardcoded token if missing)
    DATABASE_PUBLIC_URL or DATABASE_URL — PostgreSQL DSN

Usage (standalone)
------------------
    python -m pipeline.bzzoiro_ingest --job all
    python -m pipeline.bzzoiro_ingest --job matches --date-from 2026-05-20 --date-to 2026-05-25
    python -m pipeline.bzzoiro_ingest --job predictions --days-back 3
    python -m pipeline.bzzoiro_ingest --job rankings
    python -m pipeline.bzzoiro_ingest --job bios
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

# Load .env if present (local dev / .command runner — Railway injects env vars directly)
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass  # python-dotenv not installed — rely on env vars being set externally

# ─────────────────────────────────────────────────────────────────────────────
# CONFIG
# ─────────────────────────────────────────────────────────────────────────────

BZZ_TOKEN = (
    os.environ.get("BZZOIRO_API_KEY")
    or "4426945bd65f0798e817976bbef975bbb9d0e606"
)
BZZ_BASE = "https://sports.bzzoiro.com/tennis/api/v2"
BZZ_HEADERS = {"Authorization": f"Token {BZZ_TOKEN}"}

# Request settings
REQUEST_TIMEOUT = 30      # seconds per HTTP call
REQUEST_DELAY   = 0.15    # seconds between successive API calls (rate-limit headroom)
MAX_RETRIES     = 2       # retries on 5xx / network errors

# Finished statuses — only these trigger a /matches/{id}/ detail fetch for serve stats
FINISHED_STATUSES = frozenset(
    ["finished", "completed", "ended", "retired", "walkover", "w_o", "walkover_home", "walkover_away"]
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
log = logging.getLogger("bzzoiro-ingest")


# ─────────────────────────────────────────────────────────────────────────────
# DATABASE CONNECTION
# ─────────────────────────────────────────────────────────────────────────────

def get_db_conn() -> psycopg2.extensions.connection:
    """
    Return a psycopg2 connection using DATABASE_PUBLIC_URL or DATABASE_URL.
    The cursor factory is set to RealDictCursor so all rows are dict-like.
    Raises SystemExit if neither env var is set.
    """
    dsn = (
        os.environ.get("DATABASE_PUBLIC_URL")
        or os.environ.get("DATABASE_URL")
    )
    if not dsn:
        raise SystemExit(
            "Neither DATABASE_PUBLIC_URL nor DATABASE_URL is set. "
            "Export one of them before running bzzoiro_ingest."
        )
    conn = psycopg2.connect(dsn.strip())
    conn.cursor_factory = psycopg2.extras.RealDictCursor
    return conn


# ─────────────────────────────────────────────────────────────────────────────
# HTTP HELPERS
# ─────────────────────────────────────────────────────────────────────────────

def _get(path: str, params: Optional[dict] = None, retries: int = MAX_RETRIES) -> Optional[dict]:
    """
    GET {BZZ_BASE}{path} with authorisation header.
    Returns parsed JSON dict on success, or None on persistent failure.
    Logs errors but does NOT raise — callers should check for None.
    """
    url = BZZ_BASE.rstrip("/") + path
    last_exc: Optional[Exception] = None

    for attempt in range(retries + 1):
        try:
            resp = requests.get(url, params=params, headers=BZZ_HEADERS,
                                timeout=REQUEST_TIMEOUT)
            resp.raise_for_status()
            time.sleep(REQUEST_DELAY)
            return resp.json()
        except requests.HTTPError as exc:
            status = exc.response.status_code if exc.response is not None else 0
            log.warning(f"  HTTP {status} from {url} (attempt {attempt + 1}/{retries + 1})")
            last_exc = exc
            if status in (429, 500, 502, 503, 504) and attempt < retries:
                time.sleep(2 + attempt * 3)
                continue
            # 4xx other than 429 — don't retry
            log.error(f"  Non-retryable HTTP error {status}: {exc}")
            return None
        except (requests.ConnectionError, requests.Timeout) as exc:
            log.warning(f"  Network error on {url} (attempt {attempt + 1}/{retries + 1}): {exc}")
            last_exc = exc
            if attempt < retries:
                time.sleep(2 + attempt * 2)
            continue
        except Exception as exc:
            log.error(f"  Unexpected error fetching {url}: {type(exc).__name__}: {exc}")
            return None

    log.error(f"  All {retries + 1} attempts failed for {url}: {last_exc}")
    return None


def _paginate(path: str, params: Optional[dict] = None) -> list:
    """
    Walk through Bzzoiro's cursor-based pagination and return all results.
    Bzzoiro uses DRF-style pagination: {"count": N, "next": url|null, "results": [...]}
    """
    all_results: list = []
    url_or_path: Optional[str] = path
    first = True

    while url_or_path:
        if first:
            data = _get(url_or_path, params=params)
            first = False
        else:
            # "next" is a full URL — extract just the path+query
            data = _get_full_url(url_or_path)

        if data is None:
            log.warning("  Pagination interrupted — partial results returned")
            break

        results = data.get("results") or []
        all_results.extend(results)

        next_url = data.get("next")
        url_or_path = next_url  # None terminates the loop

    return all_results


def _get_full_url(full_url: str, retries: int = MAX_RETRIES) -> Optional[dict]:
    """GET an absolute URL (used for pagination 'next' links)."""
    last_exc: Optional[Exception] = None
    for attempt in range(retries + 1):
        try:
            resp = requests.get(full_url, headers=BZZ_HEADERS, timeout=REQUEST_TIMEOUT)
            resp.raise_for_status()
            time.sleep(REQUEST_DELAY)
            return resp.json()
        except requests.HTTPError as exc:
            status = exc.response.status_code if exc.response is not None else 0
            last_exc = exc
            if status in (429, 500, 502, 503, 504) and attempt < retries:
                time.sleep(2 + attempt * 3)
                continue
            log.error(f"  HTTP {status} fetching next page {full_url}")
            return None
        except Exception as exc:
            last_exc = exc
            if attempt < retries:
                time.sleep(1 + attempt)
            continue
    log.error(f"  All attempts failed for {full_url}: {last_exc}")
    return None


# ─────────────────────────────────────────────────────────────────────────────
# STATUS NORMALISATION
# ─────────────────────────────────────────────────────────────────────────────

def _map_status(bzz_status: str) -> tuple[str, bool]:
    """
    Map a Bzzoiro status string to (event_status, is_live).
    event_status matches the conventions already used in the matches table.
    """
    s = (bzz_status or "").lower().replace(" ", "_")
    if s in ("scheduled", "notstarted", "not_started", ""):
        return "1", False          # "1" = scheduled (api-tennis.com convention)
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
    return "1", False   # unknown → treat as scheduled


def _derive_winner(bzz: dict) -> Optional[str]:
    """Return 'First Player' / 'Second Player' / None from set counts."""
    p1s = bzz.get("player1_sets")
    p2s = bzz.get("player2_sets")
    if p1s is None or p2s is None:
        return None
    try:
        if int(p1s) > int(p2s):
            return "First Player"
        if int(p2s) > int(p1s):
            return "Second Player"
    except (TypeError, ValueError):
        pass
    return None


def _derive_final_result(bzz: dict) -> Optional[str]:
    """Return e.g. '2-1' from set counts, or None if unavailable."""
    p1s = bzz.get("player1_sets")
    p2s = bzz.get("player2_sets")
    if p1s is None or p2s is None:
        return None
    return f"{p1s}-{p2s}"


# ─────────────────────────────────────────────────────────────────────────────
# PLAYER RESOLUTION
# ─────────────────────────────────────────────────────────────────────────────

def _resolve_or_create_player(
    cur: psycopg2.extensions.cursor,
    bzz_player_id: int,
    name: str,
    full_name: Optional[str] = None,
    country_code: Optional[str] = None,
) -> int:
    """
    Find or create a players row for the given Bzzoiro player.

    Resolution order:
      1. player_external_ids WHERE source='bzzoiro' AND external_id=str(bzz_player_id)
      2. players WHERE full_name ILIKE %s  (fuzzy name match)
      3. INSERT a new players row (api_key = -abs(bzz_player_id))

    Returns our internal players.id.
    Always upserts a player_external_ids row linking source='bzzoiro' → players.id.
    """
    ext_id = str(bzz_player_id)

    # 1. External ID lookup (fastest path — no ambiguity)
    cur.execute(
        "SELECT player_id FROM player_external_ids WHERE source = 'bzzoiro' AND external_id = %s",
        (ext_id,),
    )
    row = cur.fetchone()
    if row:
        return row["player_id"]

    # 2. Name-based fuzzy match on players table
    search_name = (full_name or name or "").strip()
    our_player_id: Optional[int] = None

    if search_name:
        cur.execute(
            "SELECT id FROM players WHERE full_name ILIKE %s LIMIT 1",
            (search_name,),
        )
        row = cur.fetchone()
        if not row:
            # Try short name
            cur.execute(
                "SELECT id FROM players WHERE name ILIKE %s LIMIT 1",
                (search_name,),
            )
            row = cur.fetchone()
        if row:
            our_player_id = row["id"]

    # 3. Create new player row
    if our_player_id is None:
        display_name = name or full_name or "Unknown"
        # Use a negative api_key to namespace Bzzoiro-only players
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

    # Store external ID mapping (upsert — safe to rerun)
    cur.execute(
        """
        INSERT INTO player_external_ids (player_id, source, external_id)
        VALUES (%s, 'bzzoiro', %s)
        ON CONFLICT (player_id, source) DO UPDATE SET external_id = EXCLUDED.external_id
        """,
        (our_player_id, ext_id),
    )

    return our_player_id


# ─────────────────────────────────────────────────────────────────────────────
# MATCH SCORES — parse sets_detail array
# ─────────────────────────────────────────────────────────────────────────────

def _upsert_set_scores(cur: psycopg2.extensions.cursor, match_id: int, sets_detail: list):
    """
    Upsert match_scores rows from the Bzzoiro sets_detail array.

    Bzzoiro sets_detail is a list of objects, e.g.:
        [{"set": 1, "player1_games": 6, "player2_games": 3, "tiebreak": null},
         {"set": 2, "player1_games": 7, "player2_games": 6, "tiebreak": {"player1": 4, "player2": 7}}]
    """
    if not sets_detail:
        return

    rows = []
    for s in sets_detail:
        set_num = s.get("set") or s.get("set_number")
        p1g     = s.get("player1_games")
        p2g     = s.get("player2_games")
        if set_num is None or p1g is None or p2g is None:
            continue

        tb_data = s.get("tiebreak")
        is_tb   = tb_data is not None and isinstance(tb_data, dict)
        tb_score: Optional[str] = None
        if is_tb:
            tb_p1 = tb_data.get("player1")
            tb_p2 = tb_data.get("player2")
            if tb_p1 is not None and tb_p2 is not None:
                tb_score = f"{tb_p1}-{tb_p2}"

        rows.append((match_id, int(set_num), str(p1g), str(p2g), is_tb, tb_score))

    if not rows:
        return

    psycopg2.extras.execute_values(
        cur,
        """
        INSERT INTO match_scores (match_id, set_number, score_first, score_second, is_tiebreak, tiebreak_score)
        VALUES %s
        ON CONFLICT (match_id, set_number) DO UPDATE SET
            score_first    = EXCLUDED.score_first,
            score_second   = EXCLUDED.score_second,
            is_tiebreak    = EXCLUDED.is_tiebreak,
            tiebreak_score = EXCLUDED.tiebreak_score
        """,
        rows,
    )


# ─────────────────────────────────────────────────────────────────────────────
# SERVE STATS — write match_serve_stats
# ─────────────────────────────────────────────────────────────────────────────

def _upsert_serve_stats(
    cur: psycopg2.extensions.cursor,
    match_id: int,
    p1_id: int,
    p2_id: int,
    detail: dict,
) -> int:
    """
    Upsert a single match_serve_stats row from the /matches/{id}/ detail payload.

    The match_serve_stats table uses a p1/p2 column layout (not per-player rows):
        id, match_id, bzzoiro_match_id,
        p1_aces, p1_double_faults, p1_first_serve_pct, p1_first_serve_won_pct, p1_second_serve_won_pct,
        p2_aces, p2_double_faults, p2_first_serve_pct, p2_first_serve_won_pct, p2_second_serve_won_pct
        UNIQUE(match_id)

    Returns 1 if data was written, 0 if no stats found in payload.
    """
    def _float(val) -> Optional[float]:
        if val is None or val == "":
            return None
        try:
            return float(val)
        except (TypeError, ValueError):
            return None

    def _int(val) -> Optional[int]:
        if val is None or val == "":
            return None
        try:
            return int(val)
        except (TypeError, ValueError):
            return None

    p1_aces   = _int(detail.get("p1_aces"))
    p1_dfs    = _int(detail.get("p1_double_faults"))
    p1_1st    = _float(detail.get("p1_first_serve_pct"))
    p1_1st_w  = _float(detail.get("p1_first_serve_won_pct"))
    p1_2nd_w  = _float(detail.get("p1_second_serve_won_pct"))
    p2_aces   = _int(detail.get("p2_aces"))
    p2_dfs    = _int(detail.get("p2_double_faults"))
    p2_1st    = _float(detail.get("p2_first_serve_pct"))
    p2_1st_w  = _float(detail.get("p2_first_serve_won_pct"))
    p2_2nd_w  = _float(detail.get("p2_second_serve_won_pct"))

    # Only write if at least one stat is populated
    if all(v is None for v in (p1_aces, p1_dfs, p1_1st, p2_aces, p2_dfs, p2_1st)):
        return 0

    cur.execute(
        """
        INSERT INTO match_serve_stats
            (match_id,
             p1_aces, p1_double_faults, p1_first_serve_pct,
             p1_first_serve_won_pct, p1_second_serve_won_pct,
             p2_aces, p2_double_faults, p2_first_serve_pct,
             p2_first_serve_won_pct, p2_second_serve_won_pct)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (match_id) DO UPDATE SET
            p1_aces                = COALESCE(EXCLUDED.p1_aces,                match_serve_stats.p1_aces),
            p1_double_faults       = COALESCE(EXCLUDED.p1_double_faults,       match_serve_stats.p1_double_faults),
            p1_first_serve_pct     = COALESCE(EXCLUDED.p1_first_serve_pct,     match_serve_stats.p1_first_serve_pct),
            p1_first_serve_won_pct = COALESCE(EXCLUDED.p1_first_serve_won_pct, match_serve_stats.p1_first_serve_won_pct),
            p1_second_serve_won_pct= COALESCE(EXCLUDED.p1_second_serve_won_pct,match_serve_stats.p1_second_serve_won_pct),
            p2_aces                = COALESCE(EXCLUDED.p2_aces,                match_serve_stats.p2_aces),
            p2_double_faults       = COALESCE(EXCLUDED.p2_double_faults,       match_serve_stats.p2_double_faults),
            p2_first_serve_pct     = COALESCE(EXCLUDED.p2_first_serve_pct,     match_serve_stats.p2_first_serve_pct),
            p2_first_serve_won_pct = COALESCE(EXCLUDED.p2_first_serve_won_pct, match_serve_stats.p2_first_serve_won_pct),
            p2_second_serve_won_pct= COALESCE(EXCLUDED.p2_second_serve_won_pct,match_serve_stats.p2_second_serve_won_pct)
        """,
        (
            match_id,
            p1_aces, p1_dfs, p1_1st, p1_1st_w, p1_2nd_w,
            p2_aces, p2_dfs, p2_1st, p2_1st_w, p2_2nd_w,
        ),
    )
    return 1


# ─────────────────────────────────────────────────────────────────────────────
# sync_matches
# ─────────────────────────────────────────────────────────────────────────────

def sync_matches(
    conn: psycopg2.extensions.connection,
    date_from: str,
    date_to: str,
) -> dict:
    """
    Fetch all Bzzoiro matches for the given date window and upsert them into:
      - matches  (api_event_key = -abs(bzz_id))
      - match_scores  (set-by-set scores, from list endpoint or detail)
      - match_serve_stats  (serve stats — only for FINISHED matches)

    For FINISHED matches, hits /matches/{bzz_id}/ to get the 10 per-player
    serve-stat fields. Scheduled/in-progress matches skip the detail fetch.

    Returns dict: {inserted, updated, serve_stats_written, errors}
    """
    log.info(f"sync_matches: {date_from} → {date_to}")

    bzz_matches = _paginate("/matches/", params={
        "date_from": date_from,
        "date_to":   date_to,
        "limit":     100,
    })
    log.info(f"  Fetched {len(bzz_matches)} matches from Bzzoiro")

    inserted = updated = serve_stats_written = errors = 0

    with conn.cursor() as cur:
        for bzz in bzz_matches:
            try:
                was_ins, stats_written = _upsert_one_match(cur, bzz)
                if was_ins:
                    inserted += 1
                else:
                    updated += 1
                serve_stats_written += stats_written
            except Exception as exc:
                errors += 1
                log.error(
                    f"  Match bzz_id={bzz.get('id')} failed: "
                    f"{type(exc).__name__}: {exc}"
                )
                try:
                    conn.rollback()
                except Exception:
                    pass

    conn.commit()

    log.info(
        f"sync_matches done: inserted={inserted} updated={updated} "
        f"serve_stats_written={serve_stats_written} errors={errors}"
    )
    return {
        "inserted":            inserted,
        "updated":             updated,
        "serve_stats_written": serve_stats_written,
        "errors":              errors,
    }


def _upsert_one_match(
    cur: psycopg2.extensions.cursor,
    bzz: dict,
) -> tuple[bool, int]:
    """
    Upsert a single Bzzoiro match into matches / match_scores / match_serve_stats.

    Returns (was_inserted: bool, serve_stats_written: int).
    """
    bzz_id = bzz.get("id")
    if not bzz_id:
        return False, 0

    neg_event_key = -abs(int(bzz_id))

    # ── Players ──────────────────────────────────────────────────────────────
    p1 = bzz.get("player1") or {}
    p2 = bzz.get("player2") or {}

    if not p1.get("id") or not p2.get("id"):
        log.debug(f"  Match bzz_id={bzz_id}: missing player data, skipping")
        return False, 0

    p1_id = _resolve_or_create_player(
        cur,
        bzz_player_id=int(p1["id"]),
        name=p1.get("short_name") or p1.get("name") or "Unknown",
        full_name=p1.get("name"),
        country_code=p1.get("country_code"),
    )
    p2_id = _resolve_or_create_player(
        cur,
        bzz_player_id=int(p2["id"]),
        name=p2.get("short_name") or p2.get("name") or "Unknown",
        full_name=p2.get("name"),
        country_code=p2.get("country_code"),
    )

    # ── Dates / metadata ─────────────────────────────────────────────────────
    md = bzz.get("match_date") or bzz.get("date") or ""
    event_date: Optional[date] = None
    event_time = None
    try:
        dt = datetime.fromisoformat(md.replace("Z", "+00:00"))
        event_date = dt.date()
        event_time = dt.time().replace(microsecond=0)
    except Exception:
        # Try date-only string
        try:
            event_date = datetime.strptime(md[:10], "%Y-%m-%d").date()
        except Exception:
            pass

    if event_date is None:
        log.debug(f"  Match bzz_id={bzz_id}: unparseable date {md!r}, skipping")
        return False, 0

    season = str(event_date.year)
    round_name = bzz.get("round_name") or bzz.get("round") or ""
    tournament_name = bzz.get("tournament") or bzz.get("tournament_name") or ""

    event_status, is_live = _map_status(bzz.get("status") or "")
    winner       = _derive_winner(bzz)
    final_result = _derive_final_result(bzz)

    # ── Upsert into matches ───────────────────────────────────────────────────
    cur.execute(
        """
        INSERT INTO matches (
            api_event_key,
            first_player_id, second_player_id,
            event_date, event_time,
            tournament_round, season,
            final_result, winner,
            event_status, is_live,
            raw_json
        )
        VALUES (
            %s,
            %s, %s,
            %s, %s,
            %s, %s,
            %s, %s,
            %s, %s,
            %s::jsonb
        )
        ON CONFLICT (api_event_key) DO UPDATE SET
            first_player_id  = EXCLUDED.first_player_id,
            second_player_id = EXCLUDED.second_player_id,
            event_date       = EXCLUDED.event_date,
            event_time       = COALESCE(EXCLUDED.event_time, matches.event_time),
            tournament_round = COALESCE(EXCLUDED.tournament_round, matches.tournament_round),
            final_result     = COALESCE(EXCLUDED.final_result, matches.final_result),
            winner           = COALESCE(EXCLUDED.winner, matches.winner),
            event_status     = EXCLUDED.event_status,
            is_live          = EXCLUDED.is_live,
            raw_json         = EXCLUDED.raw_json,
            updated_at       = NOW()
        RETURNING id, (xmax = 0) AS was_inserted
        """,
        (
            neg_event_key,
            p1_id, p2_id,
            event_date, event_time,
            round_name, season,
            final_result, winner,
            event_status, is_live,
            json.dumps(bzz),
        ),
    )
    row = cur.fetchone()
    if not row:
        return False, 0

    our_match_id  = row["id"]
    was_inserted  = bool(row["was_inserted"] if isinstance(row, dict) else row[1])

    # ── Set scores from list endpoint ─────────────────────────────────────────
    sets_detail = bzz.get("sets_detail") or []
    if sets_detail:
        _upsert_set_scores(cur, our_match_id, sets_detail)

    # ── Serve stats — only for finished matches ───────────────────────────────
    stats_written = 0
    raw_status = (bzz.get("status") or "").lower()
    if raw_status in FINISHED_STATUSES:
        stats_written = _fetch_and_store_match_detail(
            cur, bzz_id=int(bzz_id), match_id=our_match_id,
            p1_id=p1_id, p2_id=p2_id,
        )

    return was_inserted, stats_written


def _fetch_and_store_match_detail(
    cur: psycopg2.extensions.cursor,
    bzz_id: int,
    match_id: int,
    p1_id: int,
    p2_id: int,
) -> int:
    """
    Fetch /matches/{bzz_id}/ and upsert serve stats + (richer) set scores.
    Returns the number of serve-stat rows written (0–2).
    """
    detail = _get(f"/matches/{bzz_id}/")
    if detail is None:
        return 0

    # Serve stats
    stats_written = _upsert_serve_stats(cur, match_id, p1_id, p2_id, detail)

    # Richer set scores from detail (overwrite with more authoritative data)
    sets_detail = detail.get("sets_detail") or []
    if sets_detail:
        _upsert_set_scores(cur, match_id, sets_detail)

    return stats_written


# ─────────────────────────────────────────────────────────────────────────────
# sync_predictions
# ─────────────────────────────────────────────────────────────────────────────

def sync_predictions(
    conn: psycopg2.extensions.connection,
    date_from: str,
    date_to: str,
) -> int:
    """
    Pull Bzzoiro win-probability predictions and upsert into model_predictions.

    Rules:
    - Only insert if no existing prediction with model_version != 'bzzoiro_v2' exists
      (our own ML predictions take priority and must not be overwritten).
    - If only a bzzoiro_v2 prediction exists, update it.
    - If no prediction exists at all, insert.

    Returns the number of predictions written.
    """
    log.info(f"sync_predictions: {date_from} → {date_to}")

    preds = _paginate("/predictions/", params={
        "date_from": date_from,
        "date_to":   date_to,
        "limit":     100,
    })
    log.info(f"  Fetched {len(preds)} predictions from Bzzoiro")

    written = skipped = errors = 0

    with conn.cursor() as cur:
        for pred in preds:
            try:
                n = _upsert_one_prediction(cur, pred)
                written  += n
                skipped  += (1 - n)
            except Exception as exc:
                errors += 1
                log.error(
                    f"  Prediction bzz_match={pred.get('match')} failed: "
                    f"{type(exc).__name__}: {exc}"
                )
                try:
                    conn.rollback()
                except Exception:
                    pass

    conn.commit()
    log.info(f"sync_predictions done: written={written} skipped={skipped} errors={errors}")
    return written


def _upsert_one_prediction(
    cur: psycopg2.extensions.cursor,
    pred: dict,
) -> int:
    """
    Upsert a single Bzzoiro prediction into model_predictions.
    Returns 1 if a row was written, 0 if skipped (our own model takes priority).
    """
    # Bzzoiro predictions reference a match by its bzz match ID
    bzz_match_id = pred.get("match") or pred.get("match_id")
    if not bzz_match_id:
        return 0

    neg_event_key = -abs(int(bzz_match_id))

    # Find our internal match_id
    cur.execute(
        "SELECT id FROM matches WHERE api_event_key = %s",
        (neg_event_key,),
    )
    row = cur.fetchone()
    if not row:
        # Match not yet ingested — skip silently
        return 0
    our_match_id = row["id"]

    # Check if our own (non-bzzoiro) model prediction already exists
    cur.execute(
        "SELECT model_version FROM model_predictions WHERE match_id = %s",
        (our_match_id,),
    )
    existing = cur.fetchone()
    if existing:
        existing_version = (existing["model_version"] or "").strip()
        if existing_version and existing_version != "bzzoiro_v2":
            # Our own model's prediction — don't overwrite
            return 0

    # Extract probabilities
    def _f(key) -> Optional[float]:
        v = pred.get(key)
        return float(v) if v is not None else None

    prob_p1     = _f("prob_player1_wins")
    prob_p2     = _f("prob_player2_wins")
    confidence  = _f("confidence")  # numeric 0–1 from Bzzoiro

    if prob_p1 is None or prob_p2 is None:
        return 0

    # Normalise confidence to our text scale
    conf_text: Optional[str] = None
    if confidence is not None:
        if confidence >= 0.7:
            conf_text = "high"
        elif confidence >= 0.5:
            conf_text = "medium"
        else:
            conf_text = "low"

    cur.execute(
        """
        INSERT INTO model_predictions
            (match_id, prob_first_player, prob_second_player, confidence, model_version)
        VALUES (%s, %s, %s, %s, 'bzzoiro_v2')
        ON CONFLICT (match_id) DO UPDATE SET
            prob_first_player  = EXCLUDED.prob_first_player,
            prob_second_player = EXCLUDED.prob_second_player,
            confidence         = EXCLUDED.confidence,
            model_version      = 'bzzoiro_v2',
            predicted_at       = NOW()
        """,
        (our_match_id, prob_p1, prob_p2, conf_text),
    )
    return 1


# ─────────────────────────────────────────────────────────────────────────────
# sync_rankings
# ─────────────────────────────────────────────────────────────────────────────

def sync_rankings(conn: psycopg2.extensions.connection) -> int:
    """
    Fetch ATP and WTA rankings from Bzzoiro (/rankings/?ranking_type=ATP|WTA)
    and update players.current_rank and players.ranking_points.

    Uses bulk CTE updates (not per-player transactions) to avoid deadlocks with
    Railway's concurrent scheduler processes.

    Resolution order per ranked player:
      1. player_external_ids WHERE source='bzzoiro'
      2. Fuzzy name match on players.full_name / players.name

    Returns total number of players updated.
    """
    log.info("sync_rankings: fetching ATP + WTA")
    total_updated = 0

    for tour in ("ATP", "WTA"):
        rows = _paginate("/rankings/", params={"ranking_type": tour, "limit": 500})
        log.info(f"  {tour}: {len(rows)} ranked players")

        # Collect all data upfront — no DB queries during API pagination
        data: list[tuple] = []
        for r in rows:
            p = r.get("player") or {}
            bzz_pid = p.get("id")
            pos     = r.get("position")
            pts     = r.get("points")
            name    = (p.get("name") or "").strip()
            if bzz_pid and pos is not None:
                data.append((str(bzz_pid), name, int(pos), int(pts) if pts is not None else None))

        if not data:
            continue

        with conn.cursor() as cur:
            # Fail fast on lock waits to avoid piling up behind concurrent writers
            cur.execute("SET LOCAL lock_timeout = '4s'")

            # ── Step 1: Bulk UPDATE via existing external_id mappings (single statement) ──
            psycopg2.extras.execute_values(
                cur,
                """
                UPDATE players p
                SET current_rank   = d.pos,
                    ranking_points = d.pts,
                    updated_at     = NOW()
                FROM (VALUES %s) AS d(bzz_pid, full_name, pos, pts)
                JOIN player_external_ids ei
                  ON ei.source = 'bzzoiro' AND ei.external_id = d.bzz_pid
                WHERE p.id = ei.player_id
                """,
                data,
                template="(%s, %s, %s, %s)",
            )
            known_updated = cur.rowcount

            # ── Step 2: Name-match new players not yet in external_ids ──
            # Build a set of bzz_pids we already have mapped to skip them
            cur.execute(
                "SELECT external_id FROM player_external_ids WHERE source = 'bzzoiro' AND external_id = ANY(%s)",
                ([d[0] for d in data],),
            )
            already_mapped = {r["external_id"] for r in cur.fetchall()}

            name_updated = 0
            for bzz_pid, name, pos, pts in data:
                if bzz_pid in already_mapped or not name:
                    continue
                try:
                    # Find player by name + store mapping + update rank in one shot
                    cur.execute(
                        """
                        WITH found AS (
                            SELECT id FROM players
                            WHERE (LOWER(TRIM(full_name)) = LOWER(%s)
                               OR  LOWER(TRIM(name))      = LOWER(%s))
                            LIMIT 1
                        ),
                        mapped AS (
                            INSERT INTO player_external_ids (player_id, source, external_id)
                            SELECT id, 'bzzoiro', %s FROM found
                            ON CONFLICT (player_id, source) DO UPDATE
                                SET external_id = EXCLUDED.external_id
                            RETURNING player_id
                        )
                        UPDATE players p
                        SET current_rank   = %s,
                            ranking_points = %s,
                            updated_at     = NOW()
                        FROM mapped
                        WHERE p.id = mapped.player_id
                        """,
                        (name, name, bzz_pid, pos, pts),
                    )
                    name_updated += cur.rowcount
                except Exception as exc:
                    log.warning(
                        f"  Ranking name-match failed for {name!r}: {type(exc).__name__}: {exc}"
                    )
                    try:
                        conn.rollback()
                        cur.execute("SET LOCAL lock_timeout = '4s'")
                    except Exception:
                        pass

        conn.commit()
        tour_total = known_updated + name_updated
        total_updated += tour_total
        log.info(f"  {tour} rankings committed: {known_updated} via ext-id, {name_updated} via name match")

    log.info(f"sync_rankings done: {total_updated} players updated")
    return total_updated


# ─────────────────────────────────────────────────────────────────────────────
# sync_player_bios
# ─────────────────────────────────────────────────────────────────────────────

def sync_player_bios(conn: psycopg2.extensions.connection) -> int:
    """
    Paginate through all Bzzoiro /players/ (≈5,129 players) and fill:
      - players.birthday  (where currently NULL and Bzzoiro has date_of_birth)
      - players.country_code (where currently NULL)

    Only fills nulls — never overwrites existing data.

    Returns count of players updated.
    """
    log.info("sync_player_bios: paginating Bzzoiro players (~5,129)")

    bzz_players = _paginate("/players/", params={"limit": 100})
    log.info(f"  Fetched {len(bzz_players)} players from Bzzoiro")

    updated = 0

    with conn.cursor() as cur:
        for bp in bzz_players:
            try:
                n = _update_one_player_bio(cur, bp)
                updated += n
            except Exception as exc:
                log.error(
                    f"  Bio update failed for bzz_pid={bp.get('id')}: "
                    f"{type(exc).__name__}: {exc}"
                )
                try:
                    conn.rollback()
                except Exception:
                    pass

        conn.commit()

    log.info(f"sync_player_bios done: {updated} players updated")
    return updated


def _update_one_player_bio(
    cur: psycopg2.extensions.cursor,
    bp: dict,
) -> int:
    """
    Update birthday, country_code and logo_url (player photo) for a single
    Bzzoiro player record.  Only touches NULL columns (photo can overwrite
    an existing value if the new one looks like a real URL).
    Returns 1 if any update was made, else 0.
    """
    bzz_pid      = bp.get("id")
    dob_str      = bp.get("date_of_birth")
    country_code = bp.get("country_code") or bp.get("country")
    full_name    = bp.get("name")
    # Bzzoiro may expose player photos under various field names
    photo_url    = (
        bp.get("photo_url")
        or bp.get("photo")
        or bp.get("image_url")
        or bp.get("image")
        or bp.get("avatar_url")
        or bp.get("avatar")
        or bp.get("headshot_url")
        or bp.get("headshot")
        or bp.get("picture_url")
    )
    # Only accept URLs that look legitimate (start with http)
    if photo_url and not str(photo_url).startswith("http"):
        photo_url = None

    if not bzz_pid:
        return 0

    # Parse DOB
    dob: Optional[date] = None
    if dob_str:
        for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%Y/%m/%d"):
            try:
                dob = datetime.strptime(dob_str[:10], fmt).date()
                break
            except ValueError:
                continue

    if dob is None and not country_code and not photo_url:
        # Nothing to fill
        return 0

    # Resolve our player
    our_player_id: Optional[int] = None

    cur.execute(
        "SELECT player_id FROM player_external_ids WHERE source = 'bzzoiro' AND external_id = %s",
        (str(bzz_pid),),
    )
    row = cur.fetchone()
    if row:
        our_player_id = row["player_id"]
    else:
        search_name = (full_name or "").strip()
        if search_name:
            cur.execute(
                "SELECT id FROM players WHERE full_name ILIKE %s LIMIT 1",
                (search_name,),
            )
            row = cur.fetchone()
            if not row:
                cur.execute(
                    "SELECT id FROM players WHERE name ILIKE %s LIMIT 1",
                    (search_name,),
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

    # Fetch current values for this player
    cur.execute(
        "SELECT birthday, country_code, logo_url FROM players WHERE id = %s",
        (our_player_id,),
    )
    current = cur.fetchone()
    if not current:
        return 0

    fields_to_set: list = []
    values: list = []

    if dob and current["birthday"] is None:
        fields_to_set.append("birthday = %s")
        values.append(dob)

    if country_code and current["country_code"] is None:
        fields_to_set.append("country_code = %s")
        values.append(country_code)

    # Update photo: write if we have one and the player has no photo yet
    if photo_url and not current["logo_url"]:
        fields_to_set.append("logo_url = %s")
        values.append(photo_url)

    if not fields_to_set:
        return 0

    fields_to_set.append("updated_at = NOW()")
    values.append(our_player_id)

    cur.execute(
        f"UPDATE players SET {', '.join(fields_to_set)} WHERE id = %s",
        tuple(values),
    )
    return 1 if cur.rowcount else 0


# ─────────────────────────────────────────────────────────────────────────────
# CLI ENTRY POINT
# ─────────────────────────────────────────────────────────────────────────────

def _build_date_window(date_from: Optional[str], date_to: Optional[str],
                       days_back: int) -> tuple[str, str]:
    """Return (date_from, date_to) strings, defaulting to days_back window."""
    today = date.today()
    df = date_from or (today - timedelta(days=days_back)).strftime("%Y-%m-%d")
    dt = date_to   or (today + timedelta(days=2)).strftime("%Y-%m-%d")
    return df, dt


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Bzzoiro tennis API ingestion — ratethat.tennis"
    )
    parser.add_argument(
        "--job",
        choices=["matches", "predictions", "rankings", "bios", "all"],
        default="all",
        help="Which job to run (default: all)",
    )
    parser.add_argument(
        "--date-from",
        metavar="YYYY-MM-DD",
        help="Start date for match/prediction fetch",
    )
    parser.add_argument(
        "--date-to",
        metavar="YYYY-MM-DD",
        help="End date for match/prediction fetch",
    )
    parser.add_argument(
        "--days-back",
        type=int,
        default=7,
        help="Days back from today (used when --date-from not specified). Default: 7",
    )
    args = parser.parse_args()

    conn = get_db_conn()
    log.info(f"Connected to database. Running job: {args.job}")

    try:
        if args.job in ("matches", "all"):
            df, dt = _build_date_window(args.date_from, args.date_to, args.days_back)
            result = sync_matches(conn, df, dt)
            log.info(f"matches result: {result}")

        if args.job in ("predictions", "all"):
            df, dt = _build_date_window(args.date_from, args.date_to, args.days_back)
            n = sync_predictions(conn, df, dt)
            log.info(f"predictions result: {n} written")

        if args.job in ("rankings", "all"):
            n = sync_rankings(conn)
            log.info(f"rankings result: {n} updated")

        if args.job in ("bios", "all"):
            n = sync_player_bios(conn)
            log.info(f"bios result: {n} updated")

    except KeyboardInterrupt:
        log.info("Interrupted by user")
    finally:
        conn.close()
        log.info("Database connection closed")
