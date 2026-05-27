"""
ratethat.tennis — Cloudbet Odds & Deep-Link Pipeline
=====================================================
Fetches tennis match-winner odds from Cloudbet's affiliate API, matches each
event to a match_id in our DB by player name, and writes:

  • bookmaker_odds       — Cloudbet's prices (bookmaker = 'cloudbet')
  • bookmaker_match_links — per-event deep-link affiliate URLs
  • bookmaker_affiliates  — ensures Cloudbet is registered as an affiliate

Cloudbet is unique among our bookmaker sources: it's both an odds feed AND
an affiliate, so the price we quote IS the price the punter gets when they
click through.

Setup:
  pip install requests psycopg2-binary
  export CLOUDBET_API_KEY=<JWT>
  python3 -m pipeline.cloudbet_odds
"""

from __future__ import annotations

import json
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

log = logging.getLogger("rtt-cloudbet")
if not log.handlers:
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')

# ── Config ───────────────────────────────────────────────────────────────────

API_KEY = os.environ.get(
    'CLOUDBET_API_KEY',
    'eyJhbGciOiJSUzI1NiIsImtpZCI6Img4LThRX1YwZnlUVHRPY2ZXUWFBNnV2bktjcnIyN1YzcURzQ2Z4bE44MGMiLCJ0eXAiOiJKV1QifQ.'
    'eyJhY2Nlc3NfdGllciI6ImFmZmlsaWF0ZSIsImV4cCI6MjA5NTE2NTQ4NywiaWF0IjoxNzc5ODA1NDg3LCJqdGkiOiI0OGE3N2E3YS1kYmIwLTQ1ZTAtODQ5ZC00YWZmZDgzZWRkODMiLCJzdWIiOiI2YzI3OWIwNC0xZjI2LTRiMjctYjQ1Ny1iNmM2ZjEyMmIzMTMiLCJ0ZW5hbnQiOiJjbG91ZGJldCIsInV1aWQiOiI2YzI3OWIwNC0xZjI2LTRiMjctYjQ1Ny1iNmM2ZjEyMmIzMTMifQ.'
    'RBk2vbjjO_bRFUtz2t6v6pOHUAbJOH04oTPagBreFTdW_ARr28zGzeFP-jm4KIV-0mdQtZrQ1nZbd3kJWUcyPkjDqyIfbPDEGVmOAj78dU9iuIXHdoS8-Oy5mcJdHIkuhhBauqikPmKKs4S0yva8nZHamo3Hf9tlOc5nxMnA1ve0IER6sRC5mcOxjYmfuNJgGJqZkRWMYfUvblnPuLYkOEGL75rMmxpM9yKTIM-ITLpVFfJocbojM_ywDkiDZE_wI3HAb3esalzwIpemzRxb6lIX8M8i_h3Znwnbbut0Hcy5eryWs4_zVhu1j8Fx2WcprRA7TRuxGCkJ9ug3G9Tg1w'
)
API_BASE  = 'https://sports-api.cloudbet.com/pub/v2/odds'
SPORT     = 'tennis'
MARKETS   = ['tennis.winner', 'tennis.total_sets', 'tennis.handicap', 'tennis.correct_score']

# Affiliate redirect base — wraps a path on cloudbet.com so clicks drop the
# Combatrics affiliate cookie before landing.
AFFILIATE_BASE      = 'https://cldbt.cloud/go'
AFFILIATE_TRACKING  = 'af_token=&aftm_campaign=ratethattennis&aftm_source=ratethattennis&aftm_medium=site'
PUBLIC_BASE         = 'https://www.cloudbet.com'  # used to build event URL we store

NAME_MATCH_THRESHOLD = 0.75
LOOK_AHEAD_DAYS      = 14

# DB connection — same fallback chain as the existing pipeline scripts
DB_URL = (
    os.environ.get('DATABASE_PUBLIC_URL')
    or os.environ.get('DATABASE_URL')
    or 'postgresql://postgres:DEKANqBEjmOvOGLCfzaQIBaKzhKcyKwS@switchyard.proxy.rlwy.net:39343/railway'
).strip()


# ── Name normalisation / matching ────────────────────────────────────────────

def _strip_accents(s: str) -> str:
    return ''.join(c for c in unicodedata.normalize('NFD', s or '') if unicodedata.category(c) != 'Mn')

def _normalise(name: str) -> str:
    n = _strip_accents(name or '').lower()
    return re.sub(r"[^a-z ]+", ' ', n).strip()

def _last_name(name: str) -> str:
    parts = _normalise(name).split()
    return parts[-1] if parts else ''

def _name_score(a: str, b: str) -> float:
    """Combine SequenceMatcher ratio with last-name match heuristic."""
    if not (a and b): return 0.0
    base = SequenceMatcher(None, _normalise(a), _normalise(b)).ratio()
    if _last_name(a) and _last_name(a) == _last_name(b):
        base = max(base, 0.85)
    return base


# ── HTTP helper ──────────────────────────────────────────────────────────────

def _api_get(path: str) -> dict:
    url = f'{API_BASE}{path}'
    r = requests.get(url, headers={
        'X-API-Key':  API_KEY,
        'Accept':     'application/json',
        'User-Agent': 'rtt-cloudbet/1.0',
    }, timeout=20)
    r.raise_for_status()
    return r.json()


def fetch_tennis_events() -> list[dict]:
    """Walk every tennis competition and return the raw event records with markets."""
    log.info('Fetching tennis sport tree from Cloudbet')
    sport = _api_get(f'/sports/{SPORT}')
    out: list[dict] = []
    markets_qs = '&'.join(f'markets={quote(m)}' for m in MARKETS)
    for cat in sport.get('categories', []):
        for comp in cat.get('competitions', []):
            ck = comp.get('key')
            if not ck: continue
            try:
                data = _api_get(f'/competitions/{ck}?{markets_qs}')
            except Exception as e:
                log.warning(f'  comp {ck} failed: {e}')
                continue
            for ev in data.get('events', []):
                out.append(ev)
    log.info(f'  → {len(out)} total tennis events from Cloudbet')
    return out


# ── Market extractors ────────────────────────────────────────────────────────

def _enabled_selections(market: dict):
    for sm in (market.get('submarkets') or {}).values():
        for sel in sm.get('selections') or []:
            if sel.get('status') == 'SELECTION_ENABLED':
                yield sel

def extract_winner(event: dict) -> tuple[Optional[float], Optional[float]]:
    """Return (home_price, away_price) from tennis.winner."""
    m = (event.get('markets') or {}).get('tennis.winner')
    if not m: return None, None
    home = away = None
    for sel in _enabled_selections(m):
        if sel.get('outcome') == 'home':  home = sel.get('price')
        elif sel.get('outcome') == 'away': away = sel.get('price')
    return home, away


def extract_all_markets(event: dict, flipped: bool) -> dict:
    """
    Extract all available markets from a Cloudbet event into a structured dict,
    orienting prices to our DB player order (p1 = first_player, p2 = second_player).

    flipped=True means Cloudbet's home player == our second_player.

    Returns a dict with keys: winner, total_sets, handicap, correct_score.
    Each value is itself a dict of prices/lines; missing markets are omitted.
    """
    markets = event.get('markets') or {}
    out: dict = {}

    # ── Winner ──────────────────────────────────────────────────────────────
    winner_m = markets.get('tennis.winner')
    if winner_m:
        home = away = None
        for sel in _enabled_selections(winner_m):
            if sel.get('outcome') == 'home':  home = sel.get('price')
            elif sel.get('outcome') == 'away': away = sel.get('price')
        if home or away:
            p1, p2 = (away, home) if flipped else (home, away)
            out['winner'] = {'p1': p1, 'p2': p2}

    # ── Total sets ──────────────────────────────────────────────────────────
    totals_m = markets.get('tennis.total_sets')
    if totals_m:
        over_price = under_price = line = None
        for sm in (totals_m.get('submarkets') or {}).values():
            for sel in (sm.get('selections') or []):
                if sel.get('status') != 'SELECTION_ENABLED': continue
                params = sel.get('params') or {}
                if line is None:
                    line = params.get('total')
                outcome = sel.get('outcome')
                if outcome == 'over':  over_price  = sel.get('price')
                elif outcome == 'under': under_price = sel.get('price')
        if over_price or under_price:
            out['total_sets'] = {'over': over_price, 'under': under_price, 'line': line}

    # ── Handicap ────────────────────────────────────────────────────────────
    handicap_m = markets.get('tennis.handicap')
    if handicap_m:
        home = away = hdp_line = None
        for sm in (handicap_m.get('submarkets') or {}).values():
            for sel in (sm.get('selections') or []):
                if sel.get('status') != 'SELECTION_ENABLED': continue
                params = sel.get('params') or {}
                if hdp_line is None:
                    hdp_line = params.get('handicap')
                outcome = sel.get('outcome')
                if outcome == 'home':  home = sel.get('price')
                elif outcome == 'away': away = sel.get('price')
        if home or away:
            p1, p2 = (away, home) if flipped else (home, away)
            # Cloudbet's handicap line is from home's perspective; flip sign if needed
            if flipped and hdp_line is not None:
                try:
                    hdp_line = -float(hdp_line)
                except (TypeError, ValueError):
                    pass
            out['handicap'] = {'p1': p1, 'p2': p2, 'line': hdp_line}

    # ── Correct score ────────────────────────────────────────────────────────
    score_m = markets.get('tennis.correct_score')
    if score_m:
        scores: dict = {}
        for sel in _enabled_selections(score_m):
            outcome = (sel.get('outcome') or '').lower()
            params  = sel.get('params') or {}
            price   = sel.get('price')
            if not price: continue

            # Cloudbet uses outcome strings like 'home_2_0', 'home_2_1', 'away_0_2', 'away_1_2'
            # OR outcome='home'/'away' + params={'score': '2:0'} — handle both.
            score_str = str(params.get('score', '') or '').replace(':', '-')

            if 'home_2_0' in outcome or (outcome == 'home' and score_str == '2-0'):
                key = '0-2' if flipped else '2-0'
                scores[key] = price
            elif 'home_2_1' in outcome or (outcome == 'home' and score_str == '2-1'):
                key = '1-2' if flipped else '2-1'
                scores[key] = price
            elif 'away_2_0' in outcome or 'away_0_2' in outcome or (outcome == 'away' and score_str in ('2-0', '0-2')):
                key = '2-0' if flipped else '0-2'
                scores[key] = price
            elif 'away_2_1' in outcome or 'away_1_2' in outcome or (outcome == 'away' and score_str in ('2-1', '1-2')):
                key = '2-1' if flipped else '1-2'
                scores[key] = price

        if scores:
            out['correct_score'] = scores

    return out


def ensure_markets_column(conn) -> None:
    """Create bookmaker_match_links if needed, then ensure markets_json column exists."""
    with conn.cursor() as cur:
        cur.execute("""
            CREATE TABLE IF NOT EXISTS bookmaker_match_links (
                id             SERIAL PRIMARY KEY,
                match_id       INTEGER NOT NULL REFERENCES matches(id) ON DELETE CASCADE,
                bookmaker_key  TEXT    NOT NULL,
                event_url      TEXT,
                affiliate_url  TEXT,
                markets_json   JSONB,
                fetched_at     TIMESTAMPTZ DEFAULT NOW(),
                UNIQUE (match_id, bookmaker_key)
            )
        """)
        cur.execute("""
            ALTER TABLE bookmaker_match_links
            ADD COLUMN IF NOT EXISTS markets_json JSONB
        """)
    conn.commit()
    log.info('  schema: bookmaker_match_links ensured (table + markets_json column)')


# ── Match Cloudbet event → DB match_id ───────────────────────────────────────

def _candidate_matches(conn) -> list[dict]:
    """Upcoming matches (status='Scheduled', date within window) with player names."""
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute("""
            SELECT m.id AS match_id,
                   p1.name AS p1_name,
                   p2.name AS p2_name,
                   m.match_date
            FROM matches m
            JOIN players p1 ON p1.id = m.first_player_id
            JOIN players p2 ON p2.id = m.second_player_id
            WHERE m.match_date BETWEEN CURRENT_DATE - INTERVAL '1 day'
                                    AND CURRENT_DATE + INTERVAL %s
              AND (m.winner IS NULL OR m.winner = '')
        """, (f'{LOOK_AHEAD_DAYS} days',))
        return list(cur.fetchall())


def match_cb_to_db(cb_events: list[dict], candidates: list[dict]) -> list[tuple]:
    """
    Returns list of (match_id, cb_event, flipped) tuples.
    `flipped` = True means Cloudbet's home == our second_player.
    """
    out = []
    for ev in cb_events:
        home = (ev.get('home') or {}).get('name') or ''
        away = (ev.get('away') or {}).get('name') or ''
        if not (home and away): continue

        best, best_score, flipped = None, 0.0, False
        for c in candidates:
            fwd = (_name_score(home, c['p1_name']) + _name_score(away, c['p2_name'])) / 2
            rev = (_name_score(home, c['p2_name']) + _name_score(away, c['p1_name'])) / 2
            if fwd >= NAME_MATCH_THRESHOLD and fwd >= rev:
                if fwd > best_score: best, best_score, flipped = c, fwd, False
            elif rev >= NAME_MATCH_THRESHOLD and rev > fwd:
                if rev > best_score: best, best_score, flipped = c, rev, True
        if best:
            out.append((best['match_id'], ev, flipped))
    return out


# ── DB writes ────────────────────────────────────────────────────────────────

def ensure_affiliate_row(conn):
    """Make sure Cloudbet has a row in bookmaker_affiliates."""
    homepage_aff = f'{AFFILIATE_BASE}/en/sports/tennis?{AFFILIATE_TRACKING}'
    with conn.cursor() as cur:
        cur.execute("""
            INSERT INTO bookmaker_affiliates
                (bookmaker_key, display_name, homepage_url, affiliate_url,
                 is_active, priority, notes)
            VALUES
                ('cloudbet', 'Cloudbet', 'https://www.cloudbet.com/en/sports/tennis',
                 %s, true, 5,
                 'Native odds + affiliate (Combatrics deal — JWT via CLOUDBET_API_KEY)')
            ON CONFLICT (bookmaker_key) DO UPDATE
                SET affiliate_url = EXCLUDED.affiliate_url,
                    is_active     = true,
                    priority      = 5,
                    notes         = EXCLUDED.notes,
                    updated_at    = NOW()
        """, (homepage_aff,))
    conn.commit()


def upsert_odds(conn, match_id: int, p1_price: Optional[float], p2_price: Optional[float]):
    with conn.cursor() as cur:
        for player_ref, price in [('first_player', p1_price), ('second_player', p2_price)]:
            if not price: continue
            implied = round(1.0 / float(price), 4)
            cur.execute("""
                INSERT INTO bookmaker_odds
                    (match_id, bookmaker, player_ref, decimal_odds, implied_prob, fetched_at)
                VALUES (%s, 'cloudbet', %s, %s, %s, NOW())
                ON CONFLICT (match_id, bookmaker, player_ref) DO UPDATE
                    SET decimal_odds = EXCLUDED.decimal_odds,
                        implied_prob = EXCLUDED.implied_prob,
                        fetched_at   = EXCLUDED.fetched_at
            """, (match_id, player_ref, price, implied))


def upsert_link(conn, match_id: int, cb_event_key: str,
                markets_data: Optional[dict] = None):
    """Store per-match Cloudbet deep-link URL and full markets JSON."""
    if not cb_event_key: return
    event_path = f'/en/sports/tennis/{cb_event_key}'
    event_url  = f'{PUBLIC_BASE}{event_path}'
    affiliate  = f'{AFFILIATE_BASE}{event_path}?{AFFILIATE_TRACKING}'
    markets_json_str = json.dumps(markets_data) if markets_data else None
    with conn.cursor() as cur:
        cur.execute("""
            INSERT INTO bookmaker_match_links
                (match_id, bookmaker_key, event_url, affiliate_url, markets_json, fetched_at)
            VALUES (%s, 'cloudbet', %s, %s, %s::jsonb, NOW())
            ON CONFLICT (match_id, bookmaker_key) DO UPDATE
                SET event_url     = EXCLUDED.event_url,
                    affiliate_url = EXCLUDED.affiliate_url,
                    markets_json  = COALESCE(EXCLUDED.markets_json, bookmaker_match_links.markets_json),
                    fetched_at    = EXCLUDED.fetched_at
        """, (match_id, event_url, affiliate, markets_json_str))


# ── Entry point ──────────────────────────────────────────────────────────────

def run() -> None:
    log.info('── Cloudbet tennis odds + deep links ──────────────────────────')
    conn = psycopg2.connect(DB_URL)
    try:
        ensure_affiliate_row(conn)
        ensure_markets_column(conn)   # idempotent schema migration

        candidates = _candidate_matches(conn)
        log.info(f'  upcoming matches in DB: {len(candidates)}')

        events = fetch_tennis_events()
        pairs  = match_cb_to_db(events, candidates)
        log.info(f'  matched {len(pairs)} Cloudbet events to our matches')

        wrote_odds = wrote_links = 0
        for match_id, ev, flipped in pairs:
            # Extract all markets (structured, player-oriented)
            all_markets = extract_all_markets(ev, flipped)

            # Write to bookmaker_odds (winner prices only — backward compat)
            winner = all_markets.get('winner', {})
            p1_price = winner.get('p1')
            p2_price = winner.get('p2')
            if p1_price or p2_price:
                upsert_odds(conn, match_id, p1_price, p2_price)
                wrote_odds += 1

            # Write deep-link + full markets JSON
            if ev.get('key'):
                upsert_link(conn, match_id, ev['key'],
                            markets_data=all_markets if all_markets else None)
                wrote_links += 1

        conn.commit()
        log.info(f'  → wrote odds for {wrote_odds} matches, deep links for {wrote_links}')
    finally:
        conn.close()


if __name__ == '__main__':
    run()
