"""
ratethat.tennis — Bookmaker Odds Pipeline (odds-api.io)
========================================================
Fetches tennis odds from odds-api.io — covers ATP, WTA, Challengers, ITF.
Writes to the same bookmaker_odds table as pipeline/odds.py.

Free tier: 2 bookmakers per request. Configured via ODDS_API_IO_KEY env var.

Run:
    python3 -m pipeline.odds_io
    python3 -m pipeline.odds_io --dry-run
"""

from __future__ import annotations

import argparse
import logging
import os
import re
import unicodedata
from datetime import date, timedelta
from difflib import SequenceMatcher
from typing import Optional

import psycopg2
import psycopg2.extras
import requests

log = logging.getLogger("rtt-odds-io")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)

# ─── Config ──────────────────────────────────────────────────────────────────

ODDS_IO_KEY  = os.environ.get("ODDS_API_IO_KEY", "")
ODDS_IO_BASE = "https://api.odds-api.io/v3"

# Two bookmakers on the free tier — in priority order
BOOKMAKERS = ["Bet365", "Unibet"]

# Only pull events for these statuses
FETCH_STATUSES = ["pending", "live"]

# Only match events within this window (days)
MATCH_WINDOW_DAYS = 3

NAME_MATCH_THRESHOLD = 0.72

DB_URL = (
    os.environ.get("DATABASE_PUBLIC_URL")
    or os.environ.get("DATABASE_URL")
    or "postgresql://postgres:DEKANqBEjmOvOGLCfzaQIBaKzhKcyKwS@switchyard.proxy.rlwy.net:39343/railway"
).strip()


# ─── Helpers ─────────────────────────────────────────────────────────────────

def _normalise(name: str) -> str:
    """Lowercase, strip accents, collapse whitespace."""
    nfkd = unicodedata.normalize("NFKD", name)
    ascii_ = nfkd.encode("ascii", "ignore").decode("ascii")
    return re.sub(r"\s+", " ", ascii_).strip().lower()


def _similarity(a: str, b: str) -> float:
    return SequenceMatcher(None, _normalise(a), _normalise(b)).ratio()


def _best_name_match(query: str, candidates: dict[str, int], threshold: float) -> Optional[int]:
    """Return the player ID whose name best matches query, or None."""
    best_score = 0.0
    best_id = None
    q_norm = _normalise(query)
    for name, pid in candidates.items():
        score = SequenceMatcher(None, q_norm, _normalise(name)).ratio()
        if score > best_score:
            best_score = score
            best_id = pid
    return best_id if best_score >= threshold else None


# ─── API calls ───────────────────────────────────────────────────────────────

def _fetch_events(limit: int = 500) -> list[dict]:
    """Fetch all tennis events from odds-api.io."""
    if not ODDS_IO_KEY:
        return []
    try:
        r = requests.get(
            f"{ODDS_IO_BASE}/events",
            params={"apiKey": ODDS_IO_KEY, "sport": "tennis", "limit": limit},
            timeout=15,
        )
        if r.status_code != 200:
            log.warning(f"events fetch returned {r.status_code}: {r.text[:200]}")
            return []
        return r.json() if isinstance(r.json(), list) else []
    except Exception as e:
        log.warning(f"events fetch failed: {e}")
        return []


def _fetch_odds_multi(event_ids: list[int]) -> list[dict]:
    """Fetch odds for up to 10 events in one request (counts as 1 API call)."""
    if not ODDS_IO_KEY or not event_ids:
        return []
    try:
        r = requests.get(
            f"{ODDS_IO_BASE}/odds/multi",
            params={
                "apiKey": ODDS_IO_KEY,
                "eventIds": ",".join(str(i) for i in event_ids[:10]),
                "bookmakers": ",".join(BOOKMAKERS),
            },
            timeout=15,
        )
        if r.status_code == 403:
            log.warning(f"odds/multi 403: {r.text[:300]}")
            return []
        if r.status_code != 200:
            log.warning(f"odds/multi {r.status_code}: {r.text[:200]}")
            return []
        data = r.json()
        return data if isinstance(data, list) else []
    except Exception as e:
        log.warning(f"odds/multi fetch failed: {e}")
        return []


# ─── DB helpers ──────────────────────────────────────────────────────────────

def _build_player_index(conn) -> dict[str, int]:
    """Return {normalised_name: player_id} for all players."""
    with conn.cursor() as cur:
        cur.execute("SELECT id, name FROM players")
        return {_normalise(r[1]): r[0] for r in cur.fetchall()}


def _find_match(p1_id: int, p2_id: int, event_date: str, conn) -> Optional[int]:
    """Find the production match ID for two players on a given date (±1 day)."""
    try:
        d = date.fromisoformat(event_date[:10])
    except ValueError:
        return None
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT id FROM matches
            WHERE (
                (first_player_id = %s AND second_player_id = %s) OR
                (first_player_id = %s AND second_player_id = %s)
            )
            AND event_date BETWEEN %s AND %s
            ORDER BY ABS(event_date - %s::date) ASC
            LIMIT 1
            """,
            (p1_id, p2_id, p2_id, p1_id,
             d - timedelta(days=1), d + timedelta(days=1), d),
        )
        row = cur.fetchone()
        return row[0] if row else None


def _upsert_odds(match_id: int, bookmaker: str,
                 p1_role: str, p2_role: str,
                 p1_odds: float, p2_odds: float,
                 conn) -> int:
    """Upsert one bookmaker's odds for a match. Returns rows written."""
    written = 0
    with conn.cursor() as cur:
        for role, odds in ((p1_role, p1_odds), (p2_role, p2_odds)):
            if odds is None or odds <= 1.0:
                continue
            implied = round(1.0 / odds, 4)
            cur.execute(
                """
                INSERT INTO bookmaker_odds (match_id, bookmaker, player_ref, decimal_odds, implied_prob, fetched_at)
                VALUES (%s, %s, %s, %s, %s, NOW())
                ON CONFLICT (match_id, bookmaker, player_ref)
                DO UPDATE SET decimal_odds = EXCLUDED.decimal_odds,
                              implied_prob = EXCLUDED.implied_prob,
                              fetched_at   = NOW()
                """,
                (match_id, bookmaker, role, odds, implied),
            )
            written += 1
    return written


def _ensure_affiliates(bookmakers: list[str], conn):
    """Insert any new bookmakers into bookmaker_affiliates (upsert-safe)."""
    with conn.cursor() as cur:
        for bm in bookmakers:
            cur.execute(
                """
                INSERT INTO bookmaker_affiliates (bookmaker_key, display_name)
                VALUES (%s, %s)
                ON CONFLICT (bookmaker_key) DO NOTHING
                """,
                (bm, bm),
            )


# ─── Main ─────────────────────────────────────────────────────────────────────

def run(dry_run: bool = False) -> dict:
    """
    Full sync: fetch tennis events + odds, match to production DB, write.
    Returns summary dict.
    """
    if not ODDS_IO_KEY:
        log.error(
            "\n  !! ODDS_API_IO_KEY is not set.\n"
            "  !! Set it in Railway Variables → ODDS_API_IO_KEY\n"
        )
        return {"fetched": 0, "matched": 0, "written": 0, "skipped": 0}

    conn = psycopg2.connect(DB_URL)
    conn.autocommit = False

    try:
        player_index = _build_player_index(conn)
        log.info(f"Player index: {len(player_index):,} players")

        # 1. Fetch all tennis events
        all_events = _fetch_events(limit=500)
        log.info(f"Total events from odds-api.io: {len(all_events)}")

        # Filter to pending/live within MATCH_WINDOW_DAYS
        cutoff = date.today() + timedelta(days=MATCH_WINDOW_DAYS)
        events = [
            e for e in all_events
            if e.get("status") in FETCH_STATUSES
            and e.get("date", "")[:10] <= str(cutoff)
        ]
        log.info(f"Pending/live within {MATCH_WINDOW_DAYS} days: {len(events)}")

        stats = {"fetched": len(events), "matched": 0, "written": 0, "skipped": 0,
                 "no_player": 0, "no_match": 0}

        # 2. Match events to production players + matches
        matchable: list[tuple[dict, int, str, str]] = []  # (event, match_id, p1_role, p2_role)

        for e in events:
            home_name = e.get("home", "")
            away_name = e.get("away", "")
            event_date = e.get("date", "")[:10]

            p1_id = _best_name_match(home_name, player_index, NAME_MATCH_THRESHOLD)
            p2_id = _best_name_match(away_name, player_index, NAME_MATCH_THRESHOLD)

            if not p1_id or not p2_id:
                log.debug(f"  No player match: {home_name} vs {away_name}")
                stats["no_player"] += 1
                stats["skipped"] += 1
                continue

            match_id = _find_match(p1_id, p2_id, event_date, conn)
            if not match_id:
                log.debug(f"  No DB match: {home_name} ({p1_id}) vs {away_name} ({p2_id}) on {event_date}")
                stats["no_match"] += 1
                stats["skipped"] += 1
                continue

            # Determine which role is first/second player in the production match
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT first_player_id, second_player_id FROM matches WHERE id = %s",
                    (match_id,)
                )
                row = cur.fetchone()

            if not row:
                stats["skipped"] += 1
                continue

            db_p1, db_p2 = row
            # home_name → first_player if p1_id matches db first_player_id
            if p1_id == db_p1:
                p1_role, p2_role = "first_player", "second_player"
            else:
                p1_role, p2_role = "second_player", "first_player"

            matchable.append((e, match_id, p1_role, p2_role))
            stats["matched"] += 1

        log.info(f"Matched {stats['matched']} events to production matches")

        # 3. Fetch odds in batches of 10 (multi endpoint = 1 API call per batch)
        for batch_start in range(0, len(matchable), 10):
            batch = matchable[batch_start:batch_start + 10]
            event_ids = [e[0]["id"] for e in batch]

            odds_data = _fetch_odds_multi(event_ids)
            odds_by_id = {o["id"]: o for o in odds_data}

            for event, match_id, p1_role, p2_role in batch:
                event_id = event["id"]
                odds_event = odds_by_id.get(event_id, {})
                bookmakers_data = odds_event.get("bookmakers", {})

                if not bookmakers_data:
                    log.debug(f"  No odds returned for event {event_id}")
                    continue

                for bm_name, markets in bookmakers_data.items():
                    # Find the ML (match winner) market
                    ml_market = next((m for m in markets if m.get("name") == "ML"), None)
                    if not ml_market:
                        continue

                    odds_list = ml_market.get("odds", [{}])
                    if not odds_list:
                        continue

                    odds_row = odds_list[0]
                    # home = first side in the API event, away = second side
                    home_odds = float(odds_row.get("home", 0) or 0)
                    away_odds = float(odds_row.get("away", 0) or 0)

                    if not dry_run:
                        written = _upsert_odds(
                            match_id, bm_name,
                            p1_role, p2_role,
                            home_odds, away_odds,
                            conn,
                        )
                        stats["written"] += written
                    else:
                        log.info(f"  [dry-run] match {match_id} | {bm_name} | "
                                 f"home {home_odds} away {away_odds}")

        if not dry_run:
            _ensure_affiliates(BOOKMAKERS, conn)
            conn.commit()

        log.info(
            f"Done — fetched {stats['fetched']}, matched {stats['matched']}, "
            f"written {stats['written']}, skipped {stats['skipped']} "
            f"(no_player={stats['no_player']}, no_match={stats['no_match']})"
        )
        return stats

    finally:
        conn.close()


def main():
    parser = argparse.ArgumentParser(description="Fetch tennis odds from odds-api.io")
    parser.add_argument("--dry-run", action="store_true", help="Don't write to DB")
    args = parser.parse_args()
    run(dry_run=args.dry_run)


if __name__ == "__main__":
    main()
