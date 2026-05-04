"""
ratethat.tennis — Tournament surface backfill
================================================
Tournaments imported from api-tennis often arrive with no surface or with
surface = "Unknown". That breaks every surface-specific feature in the
predictor (Wuxi → Hard, Roland Garros → Clay, Wimbledon → Grass, etc.).

This script applies a known-tournament map plus heuristics to infer the
surface and writes it back to tournaments.surface_id. Idempotent — only
updates rows where the current surface is NULL or "Unknown".

Run:
    python3 -m pipeline.surface_backfill
"""

from __future__ import annotations

import logging
import os
import re
from typing import Optional

import psycopg2
import psycopg2.extras

log = logging.getLogger("rtt-surface")
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")


DB_URL = (
    os.environ.get("DATABASE_PUBLIC_URL")
    or os.environ.get("DATABASE_URL")
    or "postgresql://postgres:DEKANqBEjmOvOGLCfzaQIBaKzhKcyKwS@switchyard.proxy.rlwy.net:39343/railway"
).strip()


# ─────────────────────────────────────────────────────────────────────────────
# Known tournament → surface map
# Lower-case substrings to match against tournament name OR city.
# Match priority: Clay > Grass > Indoor Hard > Hard (fastest match wins).
# ─────────────────────────────────────────────────────────────────────────────

CLAY_KEYWORDS = {
    # Slams + Masters
    "roland garros", "french open",
    "monte carlo", "monte-carlo", "rome", "italian open", "internazionali",
    "madrid",  # blue clay sometimes but standard clay
    # ATP/WTA 500/250 European clay swing
    "barcelona", "estoril", "munich", "bavarian", "geneva",
    "kitzbühel", "kitzbuhel", "umag", "gstaad", "båstad", "bastad",
    "hamburg", "stuttgart",  # WTA Stuttgart is INDOOR clay though
    "buenos aires", "rio open", "santiago", "córdoba", "cordoba",
    "marrakech", "marrakesh",
    "houston",  # US Men's Clay Court
    "charleston",  # green clay (volvo car)
    "iași", "iasi", "bucharest", "warsaw",
    "lyon",
    "parma",
    "valencia clay", "barcelona open", "rabat",
    "porto", "portugal open",
    "salzburg", "kitzbühel",
    # WTA clay
    "rabat", "strasbourg", "nottingham",  # nottingham is grass actually — handle below
    "palermo", "lausanne", "prague",
    "bogota", "bogotá",
    # Challenger circuit common clay venues
    "perugia", "rome challenger", "barletta", "francavilla",
    "split", "zagreb",
}

GRASS_KEYWORDS = {
    "wimbledon",
    "queen's", "queens club", "the queen's", "cinch championships",
    "halle", "terra wortmann",
    "eastbourne", "rothesay international",
    "stuttgart open",  # men's grass on grass court
    "boss open",
    "mallorca championships", "mallorca open",
    "newport", "hall of fame open",
    "den bosch", "rosmalen", "libéma open", "libema open",
    "birmingham", "rothesay classic",
    "bad homburg",
    "nottingham",  # grass
    "ilkley",
    "surbiton",
    "berlin open", "bett1 open",
}

INDOOR_HARD_KEYWORDS = {
    "atp finals", "nitto atp finals", "wta finals",
    "next gen finals",
    "paris masters", "rolex paris masters", "bnp paribas masters",
    "vienna", "erste bank open",
    "basel", "swiss indoors",
    "metz", "moselle open",
    "stockholm", "rotterdam", "abn amro",
    "marseille", "open 13",
    "sofia",
    "antwerp", "european open",
    "moscow", "kremlin cup",
    "san diego",
    "tel aviv",
    "astana",
    "florence",
    "gijón", "gijon",
    "milan",
    "linz", "upper austria",
    "ostrava", "agel open",
    "pune",  # outdoor hard but listed for completeness — handled below
    "saint petersburg",
    "diriyah tennis cup",
    "indoor",  # last-resort token
}

# Outdoor hard — long list because most tournaments default to this
HARD_KEYWORDS = {
    # Slams
    "australian open", "us open",
    # Masters / 1000
    "indian wells", "miami", "cincinnati", "canadian open", "rogers cup",
    "national bank open", "shanghai", "dubai", "doha", "qatar open",
    # Asia hard-court swing (Wuxi included)
    "wuxi", "chengdu", "zhuhai", "beijing", "china open",
    "tokyo", "osaka", "japan open",
    "seoul", "korea open",
    "hong kong",
    "guangzhou",
    "ningbo",
    "jiangxi", "nanchang",
    "hangzhou",
    # Australia / NZ swing
    "auckland", "asb classic", "adelaide", "brisbane", "sydney",
    "melbourne summer set", "hobart",
    "united cup",
    "perth",
    # Middle East
    "abu dhabi", "riyadh",
    # US hard
    "atlanta", "washington", "citi open",
    "winston-salem", "winston salem",
    "delray beach", "dallas", "memphis",
    "san jose", "newport beach",
    "los cabos",
    "acapulco", "abierto mexicano",
    # Europe hard
    "sofia",
    "almaty",
    "lugano",
    "rennes", "quimper",
    # WTA hard
    "monterrey", "merida",
    "san luis potosi",
    "linz",
    "cluj", "cluj-napoca",
    "budapest",  # actually clay sometimes
    "elite trophy",
    "tashkent",
    # Generic tokens (fallback, last)
    "open", "championships",  # extremely generic — only used after others fail
}


def infer_surface(name: str, city: Optional[str] = None) -> Optional[str]:
    """Return 'Clay' | 'Grass' | 'Indoor Hard' | 'Hard' or None."""
    if not name:
        return None
    haystack = (name + " " + (city or "")).lower()

    for kw in CLAY_KEYWORDS:
        if kw in haystack:
            return "Clay"
    for kw in GRASS_KEYWORDS:
        if kw in haystack:
            return "Grass"
    for kw in INDOOR_HARD_KEYWORDS:
        if kw in haystack:
            return "Indoor Hard"
    # Anything Asia-swing in Sept–Oct that's named "*Open" usually = Hard
    for kw in HARD_KEYWORDS:
        if kw in haystack:
            return "Hard"
    return None


def backfill_surfaces(conn) -> int:
    """Update tournaments rows whose surface is NULL or 'Unknown'. Returns rows updated."""
    log.info("Backfilling tournament surfaces…")

    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(
            """
            SELECT t.id, t.name, t.city, s.name AS current_surface
            FROM tournaments t
            LEFT JOIN surfaces s ON s.id = t.surface_id
            WHERE t.surface_id IS NULL
               OR s.name IS NULL
               OR s.name = 'Unknown'
            """
        )
        rows = cur.fetchall()

    log.info(f"  {len(rows)} tournaments missing surface")

    if not rows:
        return 0

    # Cache surface_id lookup
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute("SELECT id, name FROM surfaces")
        surface_id_by_name = {r["name"].lower(): r["id"] for r in cur.fetchall()}

    updated = 0
    unmatched: list[tuple[int, str]] = []

    for r in rows:
        inferred = infer_surface(r["name"] or "", r.get("city"))
        if not inferred:
            unmatched.append((r["id"], r["name"]))
            continue
        sid = surface_id_by_name.get(inferred.lower())
        if not sid:
            log.warning(f"  No surface_id for inferred '{inferred}' — skipping")
            continue
        with conn.cursor() as cur2:
            cur2.execute(
                "UPDATE tournaments SET surface_id = %s WHERE id = %s",
                (sid, r["id"]),
            )
        updated += 1

    conn.commit()
    log.info(f"  ✅ Updated {updated} tournament surfaces")
    if unmatched:
        log.info(f"  ⚠️  {len(unmatched)} unmatched (name → 'Hard' default applied):")
        # Default everything else to Hard rather than leaving unknown — outdoor
        # hard is the modal surface and breaks fewer features than NULL.
        hard_id = surface_id_by_name.get("hard")
        if hard_id:
            for tid, _name in unmatched[:200]:
                with conn.cursor() as cur3:
                    cur3.execute(
                        "UPDATE tournaments SET surface_id = %s WHERE id = %s",
                        (hard_id, tid),
                    )
            conn.commit()
            log.info(f"  ✅ Applied 'Hard' default to {len(unmatched)} unmatched tournaments")
            updated += len(unmatched)
            for tid, name in unmatched[:25]:
                log.info(f"     · #{tid}: {name}")

    return updated


def main():
    conn = psycopg2.connect(DB_URL)
    try:
        backfill_surfaces(conn)
    finally:
        conn.close()


if __name__ == "__main__":
    main()
