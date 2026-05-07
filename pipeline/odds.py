"""
ratethat.tennis — Bookmaker Odds Pipeline
==========================================
Fetches live tennis H2H odds from The Odds API (the-odds-api.com) and
writes them to the bookmaker_odds table.

Setup:
  1. Get a free API key at https://the-odds-api.com (500 req/month free)
  2. Set ODDS_API_KEY in your .env or Railway Variables
  3. Run: python3 -m pipeline.odds   or  ./run_odds.command

Free tier covers:
  - Sports: tennis_atp, tennis_wta, tennis_atp_aus_open_singles, etc.
  - Market: h2h (match winner)
  - Bookmakers: bet365, draftkings, fanduel, betmgm, pinnacle, unibet, …

The Odds API docs: https://the-odds-api.com/liveapi/guides/v4/
"""

from __future__ import annotations

import os
import re
import json
import logging
import requests
import unicodedata
from datetime import date, timedelta
from typing import Optional
from difflib import SequenceMatcher

import psycopg2
import psycopg2.extras

log = logging.getLogger("rtt-odds")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)

# ─── Config ──────────────────────────────────────────────────────────────────

ODDS_API_KEY = os.environ.get("ODDS_API_KEY", "")
ODDS_API_BASE = "https://api.the-odds-api.com/v4"

# Tennis sport keys to query — expand as needed
SPORT_KEYS = [
    "tennis_atp",
    "tennis_wta",
    "tennis_atp_french_open",
    "tennis_wta_french_open",
    "tennis_atp_wimbledon",
    "tennis_wta_wimbledon",
    "tennis_atp_us_open",
    "tennis_wta_us_open",
    "tennis_atp_aus_open_singles",
    "tennis_wta_aus_open_singles",
]

# Regions to fetch — each region multiplies API credit cost.
# Free tier (500 credits/month): start with "uk,eu" only (2 credits per call).
# Drop us to save ~33% of credits until US affiliate phase begins.
ODDS_REGIONS = os.environ.get("ODDS_API_REGIONS", "uk,eu")

# Which bookmaker to prefer when picking a single "headline" odds row for the
# match list / today endpoint. The match-detail comparison view uses ALL
# bookmakers regardless. Sharpest first.
PREFERRED_BOOKMAKERS = [
    "pinnacle",      # sharpest lines, useful as fair-price reference
    "leovegas",      # primary affiliate target
    "unibet",        # primary affiliate target
    "888sport",      # primary affiliate target
    "betvictor",
    "betway",
    "bet365",
    "williamhill",
    "betmgm",
    "fanduel",
    "draftkings",
    "bovada",
]

# Minimum similarity score for player name matching (0–1)
NAME_MATCH_THRESHOLD = 0.72

DB_URL = (
    os.environ.get("DATABASE_PUBLIC_URL")
    or os.environ.get("DATABASE_URL")
    or "postgresql://postgres:DEKANqBEjmOvOGLCfzaQIBaKzhKcyKwS@switchyard.proxy.rlwy.net:39343/railway"
).strip()


# ─── Name normalisation ───────────────────────────────────────────────────────

def _norm(name: str) -> str:
    """Lowercase, remove accents, strip punctuation for fuzzy matching."""
    nfkd = unicodedata.normalize("NFKD", name or "")
    ascii_str = "".join(c for c in nfkd if not unicodedata.combining(c))
    return re.sub(r"[^a-z ]", "", ascii_str.lower()).strip()


def _similarity(a: str, b: str) -> float:
    return SequenceMatcher(None, _norm(a), _norm(b)).ratio()


def _last_name(name: str) -> str:
    parts = name.strip().split()
    return parts[-1] if parts else name


# ─── Player matching ──────────────────────────────────────────────────────────

def build_player_index(conn) -> list[dict]:
    """Load all production players into a list for fuzzy matching."""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT id, name, full_name FROM players ORDER BY id"
        )
        rows = cur.fetchall()
    return [{"id": r[0], "name": r[1] or "", "full_name": r[2] or ""} for r in rows]


def find_player(odds_name: str, player_index: list[dict]) -> Optional[int]:
    """
    Return the production player_id best matching odds_name.
    Uses multi-strategy matching: exact → last-name exact → fuzzy.
    """
    norm_odds = _norm(odds_name)

    # Strategy 1: exact full_name or name match
    for p in player_index:
        if _norm(p["full_name"]) == norm_odds or _norm(p["name"]) == norm_odds:
            return p["id"]

    # Strategy 2: last-name exact match
    odds_last = _last_name(odds_name)
    matches = []
    for p in player_index:
        for field in [p["full_name"], p["name"]]:
            if _last_name(field).lower() == odds_last.lower():
                # Score by full-name similarity to pick best if multiple hits
                score = _similarity(odds_name, p["full_name"] or p["name"])
                matches.append((score, p["id"]))

    if matches:
        matches.sort(reverse=True)
        best_score, best_id = matches[0]
        if best_score >= NAME_MATCH_THRESHOLD:
            return best_id

    # Strategy 3: fuzzy full-name match over whole index
    best_score, best_id = 0.0, None
    for p in player_index:
        for field in [p["full_name"], p["name"]]:
            s = _similarity(odds_name, field)
            if s > best_score:
                best_score, best_id = s, p["id"]

    if best_score >= NAME_MATCH_THRESHOLD:
        return best_id

    return None


# ─── Match matching ───────────────────────────────────────────────────────────

def find_match(
    p1_id: int,
    p2_id: int,
    event_date_str: str,
    conn,
    window_days: int = 2,
) -> Optional[int]:
    """
    Return match.id for a production match between these two players
    within ±window_days of event_date_str.
    """
    try:
        ev_date = date.fromisoformat(event_date_str[:10])
    except Exception:
        ev_date = date.today()

    lo = ev_date - timedelta(days=window_days)
    hi = ev_date + timedelta(days=window_days)

    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT id FROM matches
            WHERE event_date BETWEEN %s AND %s
              AND (
                    (first_player_id = %s AND second_player_id = %s)
                 OR (first_player_id = %s AND second_player_id = %s)
              )
              AND event_status NOT IN ('Cancelled','Postponed','Walkover')
            ORDER BY ABS(event_date - %s::date) ASC
            LIMIT 1
            """,
            (lo, hi, p1_id, p2_id, p2_id, p1_id, str(ev_date)),
        )
        row = cur.fetchone()
    return row[0] if row else None


# ─── Odds fetch ───────────────────────────────────────────────────────────────

def fetch_odds_for_sport(sport_key: str) -> list[dict]:
    """Fetch upcoming H2H odds for one sport key. Returns raw event list."""
    if not ODDS_API_KEY:
        log.error(
            "ODDS_API_KEY not set — set it in .env or Railway Variables. "
            "Get a free key at https://the-odds-api.com"
        )
        return []

    url = f"{ODDS_API_BASE}/sports/{sport_key}/odds"
    params = {
        "apiKey": ODDS_API_KEY,
        "regions": ODDS_REGIONS,        # configurable; default uk,eu for free tier
        "markets": "h2h",
        "oddsFormat": "decimal",
        "dateFormat": "iso",
    }
    try:
        resp = requests.get(url, params=params, timeout=20)
        remaining = resp.headers.get("x-requests-remaining", "?")
        used = resp.headers.get("x-requests-used", "?")
        log.info(f"  {sport_key}: HTTP {resp.status_code} | API requests used={used} remaining={remaining}")

        if resp.status_code == 404:
            # Sport not in season — expected for off-season Slams
            return []
        if resp.status_code == 401:
            log.error("  Invalid ODDS_API_KEY")
            return []
        if resp.status_code == 429:
            log.error("  Rate limit / quota exceeded")
            return []

        resp.raise_for_status()
        return resp.json()

    except requests.RequestException as e:
        log.warning(f"  {sport_key}: request failed — {e}")
        return []


# ─── Write to DB ──────────────────────────────────────────────────────────────

def write_odds(
    match_id: int,
    bookmaker: str,
    player_ref: str,     # 'first_player' | 'second_player'
    decimal_odds: float,
    conn,
) -> bool:
    """Upsert one odds row. Returns True if written."""
    if decimal_odds is None or decimal_odds <= 1.0:
        return False

    implied_prob = round(1.0 / decimal_odds, 6)

    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO bookmaker_odds
                (match_id, bookmaker, player_ref, decimal_odds, implied_prob, fetched_at)
            VALUES (%s, %s, %s, %s, %s, NOW())
            ON CONFLICT (match_id, bookmaker, player_ref)
            DO UPDATE SET
                decimal_odds = EXCLUDED.decimal_odds,
                implied_prob = EXCLUDED.implied_prob,
                fetched_at   = EXCLUDED.fetched_at
            """,
            (match_id, bookmaker, player_ref, decimal_odds, implied_prob),
        )
    return True


# ─── Main pipeline ────────────────────────────────────────────────────────────

def run(dry_run: bool = False) -> dict:
    """
    Full odds sync: fetch → match → write.
    Returns summary dict {fetched, matched, written, skipped}.
    """
    if not ODDS_API_KEY:
        log.error(
            "\n  !! ODDS_API_KEY is not set.\n"
            "  !! Get a free key at https://the-odds-api.com\n"
            "  !! Then set it in .env:  ODDS_API_KEY=your_key_here\n"
            "  !! Or in Railway Variables → ODDS_API_KEY\n"
        )
        return {"fetched": 0, "matched": 0, "written": 0, "skipped": 0}

    conn = psycopg2.connect(DB_URL)
    conn.autocommit = False

    try:
        player_index = build_player_index(conn)
        log.info(f"Player index loaded: {len(player_index):,} players")

        stats = {"fetched": 0, "matched": 0, "written": 0, "skipped": 0}

        for sport_key in SPORT_KEYS:
            events = fetch_odds_for_sport(sport_key)
            if not events:
                continue

            log.info(f"  {sport_key}: {len(events)} events")
            stats["fetched"] += len(events)

            for event in events:
                home_name = event.get("home_team", "")
                away_name = event.get("away_team", "")
                commence  = event.get("commence_time", "")[:10]   # YYYY-MM-DD

                # Match player names to production IDs
                p1_id = find_player(home_name, player_index)
                p2_id = find_player(away_name, player_index)

                if not p1_id or not p2_id:
                    log.debug(f"    No player match: {home_name} vs {away_name}")
                    stats["skipped"] += 1
                    continue

                # Match to production match row
                match_id = find_match(p1_id, p2_id, commence, conn)
                if not match_id:
                    log.debug(
                        f"    No DB match: {home_name} ({p1_id}) vs {away_name} ({p2_id}) on {commence}"
                    )
                    stats["skipped"] += 1
                    continue

                stats["matched"] += 1

                # Write odds from EVERY bookmaker that quoted this event so the
                # match-detail comparison view has the full price spread to
                # show. The unique constraint (match_id, bookmaker, player_ref)
                # ensures one row per bookmaker per side per match.
                bookmakers = event.get("bookmakers", [])
                if not bookmakers:
                    stats["skipped"] += 1
                    continue

                wrote_any = False
                for bm in bookmakers:
                    bm_key = bm.get("key")
                    if not bm_key:
                        continue

                    h2h_markets = [m for m in bm.get("markets", []) if m["key"] == "h2h"]
                    if not h2h_markets:
                        continue

                    outcomes = h2h_markets[0].get("outcomes", [])
                    odds_by_name: dict[str, float] = {o["name"]: o["price"] for o in outcomes}

                    # Map odds API player names → first/second player role
                    # (home_team = first_player in The Odds API convention)
                    p1_odds = odds_by_name.get(home_name)
                    p2_odds = odds_by_name.get(away_name)

                    # Fallback: check similarity if exact name not found
                    if p1_odds is None:
                        for oname, oprice in odds_by_name.items():
                            if _similarity(home_name, oname) > 0.85:
                                p1_odds = oprice
                                break
                    if p2_odds is None:
                        for oname, oprice in odds_by_name.items():
                            if _similarity(away_name, oname) > 0.85:
                                p2_odds = oprice
                                break

                    if not dry_run:
                        if p1_odds:
                            write_odds(match_id, bm_key, "first_player", p1_odds, conn)
                            stats["written"] += 1
                            wrote_any = True
                        if p2_odds:
                            write_odds(match_id, bm_key, "second_player", p2_odds, conn)
                            stats["written"] += 1
                            wrote_any = True
                    else:
                        if p1_odds:
                            log.info(
                                f"    DRY-RUN: match_id={match_id} "
                                f"{home_name} odds={p1_odds} [{bm_key}]"
                            )
                        if p2_odds:
                            log.info(
                                f"    DRY-RUN: match_id={match_id} "
                                f"{away_name} odds={p2_odds} [{bm_key}]"
                            )

                if not wrote_any and not dry_run:
                    stats["skipped"] += 1
                    continue

                log.debug(
                    f"    Matched: {home_name} vs {away_name} → match_id={match_id} "
                    f"({len(bookmakers)} bookmaker(s))"
                )

        if not dry_run:
            conn.commit()
            log.info(
                f"\n✓ Odds sync complete: {stats['fetched']} events fetched | "
                f"{stats['matched']} matched | {stats['written']} odds written | "
                f"{stats['skipped']} skipped"
            )
        else:
            conn.rollback()
            log.info(f"\nDry run done — {stats}")

        return stats

    except Exception as e:
        conn.rollback()
        log.error(f"Odds pipeline failed: {e}")
        raise
    finally:
        conn.close()


# ─── CLI ─────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="ratethat.tennis odds pipeline")
    parser.add_argument("--dry-run", action="store_true",
                        help="Fetch and match but don't write to DB")
    parser.add_argument("--sport", default=None,
                        help="Only fetch one sport key (e.g. tennis_atp)")
    args = parser.parse_args()

    if args.sport:
        SPORT_KEYS[:] = [args.sport]

    run(dry_run=args.dry_run)
