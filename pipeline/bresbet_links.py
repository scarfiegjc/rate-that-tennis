"""
ratethat.tennis — Bresbet deep-link scraper
============================================
Scrapes bresbet.com/sport/tennis, extracts match event URLs, fuzzy-matches
player names to our production matches, and stores the affiliate deep links
in bookmaker_match_links so MatchDetail can show "Bet at Bresbet →".

Affiliate URL format:
  https://refer.bresbet.com/redirect?...&customParameter=<event_url>

Run:
  python3 -m pipeline.bresbet_links   OR  ./run_bresbet_links.command
"""

from __future__ import annotations

import os
import re
import logging
import unicodedata
from datetime import date, timedelta
from difflib import SequenceMatcher
from typing import Optional
from urllib.parse import quote

import requests
import psycopg2
import psycopg2.extras

log = logging.getLogger("rtt-bresbet")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)

# ─── Config ──────────────────────────────────────────────────────────────────

BRESBET_TENNIS_URL = "https://bresbet.com/sport/tennis"

# Affiliate redirect base — customParameter gets the event URL appended
AFFILIATE_BASE = (
    "https://refer.bresbet.com/redirect"
    "?cid=6a059e5518526c92a49928f3"
    "&oid=6499640c6e61a4ede687608b"
    "&bid=64996d6c6e61a4ede687609d"
    "&pid=649976346e61a4ede68760b1"
    "&customParameter="
)

NAME_MATCH_THRESHOLD = 0.72

# Match window: look for upcoming/recent matches within this many days
MATCH_WINDOW_DAYS = 4

DB_URL = (
    os.environ.get("DATABASE_PUBLIC_URL")
    or os.environ.get("DATABASE_URL")
    or "postgresql://postgres:DEKANqBEjmOvOGLCfzaQIBaKzhKcyKwS@switchyard.proxy.rlwy.net:39343/railway"
).strip()

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-GB,en;q=0.9",
}


# ─── Name normalisation ───────────────────────────────────────────────────────

def _norm(name: str) -> str:
    """Lowercase, remove accents, strip punctuation."""
    nfkd = unicodedata.normalize("NFKD", name or "")
    ascii_str = "".join(c for c in nfkd if not unicodedata.combining(c))
    return re.sub(r"[^a-z ]", "", ascii_str.lower()).strip()


def _similarity(a: str, b: str) -> float:
    return SequenceMatcher(None, _norm(a), _norm(b)).ratio()


def _slug_to_name(slug: str) -> str:
    """Convert 'jannik-sinner' → 'Jannik Sinner'."""
    return " ".join(w.capitalize() for w in slug.split("-"))


# ─── Scrape Bresbet tennis page ──────────────────────────────────────────────

def scrape_bresbet_events() -> list[dict]:
    """
    Fetch bresbet.com/sport/tennis and extract all event links.
    Returns list of {event_id, slug, p1_slug, p2_slug, event_url, affiliate_url}.
    """
    try:
        resp = requests.get(BRESBET_TENNIS_URL, headers=HEADERS, timeout=15)
        resp.raise_for_status()
    except requests.RequestException as e:
        log.error(f"Failed to fetch Bresbet tennis page: {e}")
        return []

    html = resp.text

    # Match pattern: href="/event/{id}/{player1-slug}-vs-{player2-slug}"
    pattern = re.compile(
        r'href=["\'](?:https?://(?:www\.)?bresbet\.com)?/event/(\d+)/([a-z0-9-]+-vs-[a-z0-9-]+)["\']',
        re.IGNORECASE,
    )

    seen = set()
    events = []

    for m in pattern.finditer(html):
        event_id = m.group(1)
        slug = m.group(2)

        if slug in seen:
            continue
        seen.add(slug)

        # Split on first occurrence of '-vs-'
        vs_idx = slug.find("-vs-")
        if vs_idx == -1:
            continue

        p1_slug = slug[:vs_idx]
        p2_slug = slug[vs_idx + 4:]  # skip '-vs-'

        if not p1_slug or not p2_slug:
            continue

        event_url = f"https://bresbet.com/event/{event_id}/{slug}"
        affiliate_url = AFFILIATE_BASE + quote(event_url, safe="")

        events.append({
            "event_id":      event_id,
            "slug":          slug,
            "p1_slug":       p1_slug,
            "p2_slug":       p2_slug,
            "p1_name":       _slug_to_name(p1_slug),
            "p2_name":       _slug_to_name(p2_slug),
            "event_url":     event_url,
            "affiliate_url": affiliate_url,
        })

    log.info(f"Scraped {len(events)} events from Bresbet tennis page")
    return events


# ─── Player + match matching ──────────────────────────────────────────────────

def build_player_index(conn) -> list[dict]:
    with conn.cursor() as cur:
        cur.execute("SELECT id, name, full_name FROM players ORDER BY id")
        rows = cur.fetchall()
    return [{"id": r[0], "name": r[1] or "", "full_name": r[2] or ""} for r in rows]


def find_player(guess: str, player_index: list[dict]) -> Optional[int]:
    norm_guess = _norm(guess)

    # Exact match
    for p in player_index:
        if _norm(p["full_name"]) == norm_guess or _norm(p["name"]) == norm_guess:
            return p["id"]

    # Last-name exact
    guess_last = guess.strip().split()[-1] if guess.strip() else ""
    candidates = []
    for p in player_index:
        for field in [p["full_name"], p["name"]]:
            if field.strip().split()[-1].lower() == guess_last.lower():
                score = _similarity(guess, field)
                candidates.append((score, p["id"]))

    if candidates:
        candidates.sort(reverse=True)
        best_score, best_id = candidates[0]
        if best_score >= NAME_MATCH_THRESHOLD:
            return best_id

    # Full fuzzy
    best_score, best_id = 0.0, None
    for p in player_index:
        for field in [p["full_name"], p["name"]]:
            s = _similarity(guess, field)
            if s > best_score:
                best_score, best_id = s, p["id"]

    if best_score >= NAME_MATCH_THRESHOLD:
        return best_id

    return None


def find_match(p1_id: int, p2_id: int, conn) -> Optional[int]:
    """
    Find an upcoming or very recent match between these two players.
    No date info from Bresbet scrape, so we look within a rolling window.
    """
    today = date.today()
    lo = today - timedelta(days=1)
    hi = today + timedelta(days=MATCH_WINDOW_DAYS)

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
            ORDER BY event_date ASC
            LIMIT 1
            """,
            (lo, hi, p1_id, p2_id, p2_id, p1_id),
        )
        row = cur.fetchone()
    return row[0] if row else None


# ─── DB write ─────────────────────────────────────────────────────────────────

def ensure_schema(conn):
    """Create bookmaker_match_links if it doesn't exist yet."""
    with conn.cursor() as cur:
        cur.execute("""
            CREATE TABLE IF NOT EXISTS bookmaker_match_links (
                id            SERIAL PRIMARY KEY,
                match_id      INTEGER NOT NULL REFERENCES matches(id) ON DELETE CASCADE,
                bookmaker_key TEXT    NOT NULL,
                event_url     TEXT    NOT NULL,
                affiliate_url TEXT,
                fetched_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                UNIQUE (match_id, bookmaker_key)
            )
        """)
        # Ensure Bresbet is in bookmaker_affiliates
        cur.execute("""
            INSERT INTO bookmaker_affiliates
                (bookmaker_key, display_name, homepage_url, affiliate_url, is_active, priority, notes)
            VALUES
                ('bresbet', 'BresBet', 'https://bresbet.com/sport/tennis',
                 %s, true, 15,
                 'Affiliate confirmed 2026-05-14 — deep links via customParameter')
            ON CONFLICT (bookmaker_key) DO UPDATE
                SET affiliate_url = EXCLUDED.affiliate_url,
                    is_active     = true,
                    notes         = EXCLUDED.notes,
                    updated_at    = NOW()
        """, (AFFILIATE_BASE + quote("https://bresbet.com/sport/tennis", safe=""),))
    conn.commit()
    log.info("Schema / bookmaker_affiliates ensured")


def upsert_link(match_id: int, event_url: str, affiliate_url: str, conn):
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO bookmaker_match_links
                (match_id, bookmaker_key, event_url, affiliate_url, fetched_at)
            VALUES (%s, 'bresbet', %s, %s, NOW())
            ON CONFLICT (match_id, bookmaker_key)
            DO UPDATE SET
                event_url     = EXCLUDED.event_url,
                affiliate_url = EXCLUDED.affiliate_url,
                fetched_at    = EXCLUDED.fetched_at
            """,
            (match_id, event_url, affiliate_url),
        )


# ─── Main pipeline ────────────────────────────────────────────────────────────

def run(dry_run: bool = False) -> dict:
    """
    Scrape Bresbet tennis page, match events to our DB, store affiliate deep links.
    Returns summary dict {scraped, matched, written, skipped}.
    """
    conn = psycopg2.connect(DB_URL)
    conn.autocommit = False

    try:
        ensure_schema(conn)

        events = scrape_bresbet_events()
        if not events:
            log.warning("No events scraped from Bresbet — page may be down or structure changed")
            return {"scraped": 0, "matched": 0, "written": 0, "skipped": 0}

        player_index = build_player_index(conn)
        log.info(f"Player index: {len(player_index):,} players")

        stats = {"scraped": len(events), "matched": 0, "written": 0, "skipped": 0}

        for ev in events:
            p1_id = find_player(ev["p1_name"], player_index)
            p2_id = find_player(ev["p2_name"], player_index)

            if not p1_id or not p2_id:
                log.debug(f"  No player match: {ev['p1_name']} vs {ev['p2_name']}")
                stats["skipped"] += 1
                continue

            match_id = find_match(p1_id, p2_id, conn)
            if not match_id:
                log.debug(f"  No DB match: {ev['p1_name']} ({p1_id}) vs {ev['p2_name']} ({p2_id})")
                stats["skipped"] += 1
                continue

            stats["matched"] += 1
            log.info(f"  ✓ match_id={match_id}: {ev['p1_name']} vs {ev['p2_name']} → {ev['event_url']}")

            if not dry_run:
                upsert_link(match_id, ev["event_url"], ev["affiliate_url"], conn)
                stats["written"] += 1
            else:
                log.info(f"    DRY-RUN: would store {ev['affiliate_url']}")

        if not dry_run:
            conn.commit()

        log.info(
            f"\n✓ Bresbet links: {stats['scraped']} scraped | "
            f"{stats['matched']} matched | {stats['written']} written | "
            f"{stats['skipped']} skipped"
        )
        return stats

    except Exception as e:
        conn.rollback()
        log.error(f"Bresbet links pipeline failed: {e}")
        raise
    finally:
        conn.close()


# ─── CLI ─────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Bresbet deep-link scraper")
    parser.add_argument("--dry-run", action="store_true", help="Scrape and match but don't write to DB")
    args = parser.parse_args()
    run(dry_run=args.dry_run)
