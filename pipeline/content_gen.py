#!/usr/bin/env python3
"""
ratethat.tennis — SEO match preview generator
=============================================
Generates 250-word match preview articles for upcoming matches using
the Anthropic API (claude-haiku-4-5-20251001 — fast, cheap).

Previews are stored in matches.seo_preview and persist after the match ends.
After a match completes, a result suffix is appended.

Usage:
    python3 -m pipeline.content_gen --job previews    # generate missing previews
    python3 -m pipeline.content_gen --job results     # append results to completed matches
    python3 -m pipeline.content_gen --job all         # both
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from datetime import date, timedelta
from typing import Optional

import psycopg2
import psycopg2.extras

# Load .env if present
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

# ─────────────────────────────────────────────────────────────────────────────
# CONFIG
# ─────────────────────────────────────────────────────────────────────────────

ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
MODEL = "claude-haiku-4-5-20251001"

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
log = logging.getLogger("content-gen")

# Surface display names
SURFACE_LABELS = {
    "clay": "clay",
    "hard": "hard",
    "grass": "grass",
    "carpet": "carpet",
    "indoor hard": "indoor hard",
    "indoor clay": "indoor clay",
}

# Tour level display names
LEVEL_LABELS = {
    "ATP": "ATP Tour",
    "WTA": "WTA Tour",
    "Challenger": "ATP Challenger",
    "ITF": "ITF",
    "Grand Slam": "Grand Slam",
}


# ─────────────────────────────────────────────────────────────────────────────
# DATABASE
# ─────────────────────────────────────────────────────────────────────────────

def get_db_conn() -> psycopg2.extensions.connection:
    if not DB_URL:
        raise SystemExit("Neither DATABASE_PUBLIC_URL nor DATABASE_URL is set.")
    conn = psycopg2.connect(DB_URL)
    conn.cursor_factory = psycopg2.extras.RealDictCursor
    return conn


# ─────────────────────────────────────────────────────────────────────────────
# ANTHROPIC CLIENT
# ─────────────────────────────────────────────────────────────────────────────

def _call_anthropic(prompt: str, max_tokens: int = 400) -> Optional[str]:
    """
    Call Anthropic API directly via requests (avoids anthropic SDK dependency).
    Returns the text content of the response, or None on failure.
    """
    if not ANTHROPIC_API_KEY:
        log.error("ANTHROPIC_API_KEY not set — cannot generate previews")
        return None

    import requests

    headers = {
        "x-api-key": ANTHROPIC_API_KEY,
        "anthropic-version": "2023-06-01",
        "content-type": "application/json",
    }
    body = {
        "model": MODEL,
        "max_tokens": max_tokens,
        "messages": [
            {"role": "user", "content": prompt}
        ],
    }
    try:
        resp = requests.post(
            "https://api.anthropic.com/v1/messages",
            headers=headers,
            json=body,
            timeout=30,
        )
        resp.raise_for_status()
        data = resp.json()
        content = data.get("content", [])
        if content and isinstance(content, list):
            return content[0].get("text", "").strip()
        return None
    except Exception as exc:
        log.error(f"Anthropic API error: {type(exc).__name__}: {exc}")
        return None


# ─────────────────────────────────────────────────────────────────────────────
# DATA FETCHING
# ─────────────────────────────────────────────────────────────────────────────

def _fetch_match_context(cur, match_id: int) -> Optional[dict]:
    """
    Fetch all data needed to generate a match preview.
    Returns a dict with player info, ratings, surface, tournament details.
    """
    cur.execute(
        """
        SELECT
            m.id AS match_id,
            m.event_date,
            m.tournament_round,
            m.final_result,
            m.winner,
            p1.id AS p1_id,
            p1.name AS p1_name,
            p1.full_name AS p1_full_name,
            p1.country_code AS p1_country,
            p1.current_rank AS p1_rank,
            p2.id AS p2_id,
            p2.name AS p2_name,
            p2.full_name AS p2_full_name,
            p2.country_code AS p2_country,
            p2.current_rank AS p2_rank,
            t.name AS tournament_name,
            s.name AS surface,
            et.tour_category AS tour_category
        FROM matches m
        JOIN players p1 ON p1.id = m.first_player_id
        JOIN players p2 ON p2.id = m.second_player_id
        LEFT JOIN tournaments t ON t.id = m.tournament_id
        LEFT JOIN surfaces s ON s.id = t.surface_id
        LEFT JOIN event_types et ON et.id = m.event_type_id
        WHERE m.id = %s
        """,
        (match_id,),
    )
    row = cur.fetchone()
    if not row:
        return None

    ctx = dict(row)

    # Fetch RTT ratings for both players
    for pnum, pid in [("p1", ctx["p1_id"]), ("p2", ctx["p2_id"])]:
        cur.execute(
            """
            SELECT rtt_score, clay_rating, hard_rating, grass_rating, indoor_rating,
                   serve_rating, return_rating, form_score, momentum
            FROM player_ratings
            WHERE player_id = %s
            """,
            (pid,),
        )
        ratings = cur.fetchone()
        if ratings:
            ctx[f"{pnum}_rtt"] = ratings["rtt_score"]
            ctx[f"{pnum}_serve_rating"] = ratings["serve_rating"]
            ctx[f"{pnum}_return_rating"] = ratings["return_rating"]
            ctx[f"{pnum}_form"] = ratings["form_score"]
            ctx[f"{pnum}_momentum"] = ratings["momentum"]
            # Surface-specific rating
            surface_lower = (ctx.get("surface") or "").lower()
            ctx[f"{pnum}_surface_rating"] = (
                ratings.get(f"{surface_lower}_rating")
                or ratings.get("hard_rating")
                or ratings.get("rtt_score")
            )
        else:
            ctx[f"{pnum}_rtt"] = None
            ctx[f"{pnum}_surface_rating"] = None
            ctx[f"{pnum}_serve_rating"] = None
            ctx[f"{pnum}_return_rating"] = None
            ctx[f"{pnum}_form"] = None
            ctx[f"{pnum}_momentum"] = None

    # Fetch recent form (last 5 results) for both players
    for pnum, pid in [("p1", ctx["p1_id"]), ("p2", ctx["p2_id"])]:
        cur.execute(
            """
            SELECT
                CASE WHEN winner = 'First Player' AND first_player_id = %s THEN 'W'
                     WHEN winner = 'Second Player' AND second_player_id = %s THEN 'W'
                     WHEN winner IS NOT NULL THEN 'L'
                     ELSE '?' END AS result
            FROM matches
            WHERE (first_player_id = %s OR second_player_id = %s)
              AND event_status IN ('Finished', 'Retired', 'Walkover')
              AND winner IS NOT NULL
            ORDER BY event_date DESC
            LIMIT 5
            """,
            (pid, pid, pid, pid),
        )
        results = [r["result"] for r in cur.fetchall()]
        ctx[f"{pnum}_form_last5"] = "".join(results) if results else "N/A"

    # Fetch H2H record
    cur.execute(
        """
        SELECT
            COUNT(*) FILTER (
                WHERE (first_player_id = %s AND winner = 'First Player')
                   OR (second_player_id = %s AND winner = 'Second Player')
            ) AS p1_wins,
            COUNT(*) FILTER (
                WHERE (first_player_id = %s AND winner = 'First Player')
                   OR (second_player_id = %s AND winner = 'Second Player')
            ) AS p2_wins,
            COUNT(*) AS total
        FROM matches
        WHERE (first_player_id = %s AND second_player_id = %s)
           OR (first_player_id = %s AND second_player_id = %s)
        """,
        (
            ctx["p1_id"], ctx["p1_id"],
            ctx["p2_id"], ctx["p2_id"],
            ctx["p1_id"], ctx["p2_id"],
            ctx["p2_id"], ctx["p1_id"],
        ),
    )
    h2h = cur.fetchone()
    if h2h and h2h["total"] > 0:
        ctx["h2h_record"] = f"{ctx['p1_name']} leads {h2h['p1_wins']}-{h2h['p2_wins']}"
        if h2h["p2_wins"] > h2h["p1_wins"]:
            ctx["h2h_record"] = f"{ctx['p2_name']} leads {h2h['p2_wins']}-{h2h['p1_wins']}"
        elif h2h["p1_wins"] == h2h["p2_wins"]:
            ctx["h2h_record"] = f"H2H level at {h2h['p1_wins']}-{h2h['p2_wins']}"
    else:
        ctx["h2h_record"] = "No previous meetings"

    # Fetch ML prediction if available
    cur.execute(
        """
        SELECT prob_first_player, prob_second_player, model_version
        FROM model_predictions
        WHERE match_id = %s
        ORDER BY predicted_at DESC LIMIT 1
        """,
        (match_id,),
    )
    pred = cur.fetchone()
    ctx["pred_p1"] = float(pred["prob_first_player"]) if pred and pred["prob_first_player"] else None
    ctx["pred_p2"] = float(pred["prob_second_player"]) if pred and pred["prob_second_player"] else None

    return ctx


# ─────────────────────────────────────────────────────────────────────────────
# PROMPT BUILDER
# ─────────────────────────────────────────────────────────────────────────────

def _build_prompt(ctx: dict) -> str:
    """Build the prompt for a match preview."""
    p1_name = ctx.get("p1_full_name") or ctx.get("p1_name") or "Player 1"
    p2_name = ctx.get("p2_full_name") or ctx.get("p2_name") or "Player 2"
    tournament = ctx.get("tournament_name") or "Unknown Tournament"
    surface = (ctx.get("surface") or "hard").lower()
    round_name = ctx.get("tournament_round") or ""
    tour = ctx.get("tour_category") or "ATP"
    level = LEVEL_LABELS.get(tour, tour)

    p1_rank = ctx.get("p1_rank")
    p2_rank = ctx.get("p2_rank")
    p1_rtt = ctx.get("p1_rtt")
    p2_rtt = ctx.get("p2_rtt")
    p1_surf = ctx.get("p1_surface_rating")
    p2_surf = ctx.get("p2_surface_rating")
    p1_form5 = ctx.get("p1_form_last5", "N/A")
    p2_form5 = ctx.get("p2_form_last5", "N/A")
    h2h = ctx.get("h2h_record", "No previous meetings")
    p1_country = ctx.get("p1_country") or ""
    p2_country = ctx.get("p2_country") or ""

    # Build player context lines
    p1_context_parts = []
    if p1_rank:
        p1_context_parts.append(f"current ranking #{p1_rank}")
    if p1_rtt:
        p1_context_parts.append(f"RTT Score {p1_rtt:.0f}/100")
    if p1_surf:
        p1_context_parts.append(f"{surface} rating {p1_surf:.0f}/100")
    p1_context_parts.append(f"recent form (last 5): {p1_form5}")

    p2_context_parts = []
    if p2_rank:
        p2_context_parts.append(f"current ranking #{p2_rank}")
    if p2_rtt:
        p2_context_parts.append(f"RTT Score {p2_rtt:.0f}/100")
    if p2_surf:
        p2_context_parts.append(f"{surface} rating {p2_surf:.0f}/100")
    p2_context_parts.append(f"recent form (last 5): {p2_form5}")

    round_info = f" ({round_name})" if round_name else ""

    prompt = f"""You are a tennis analyst writing match previews for a betting intelligence website.
Write a 250-word match preview for: {p1_name} vs {p2_name} at {tournament}{round_info} ({surface} court).

Context:
- {p1_name} ({p1_country}): {", ".join(p1_context_parts)}
- {p2_name} ({p2_country}): {", ".join(p2_context_parts)}
- H2H: {h2h}
- Tournament level: {level}

Write in the style of a Racing Post racing preview — analytical, factual, focused on value.
Cover: surface suitability for each player, recent form, the key tactical matchup, and which factors will decide the match.
End with one sentence naming the likely winner and why.
No bullet points. Flowing prose only. Aim for exactly 250 words."""

    return prompt


# ─────────────────────────────────────────────────────────────────────────────
# RESULT SUFFIX
# ─────────────────────────────────────────────────────────────────────────────

def _build_result_suffix(ctx: dict) -> Optional[str]:
    """Build a short result suffix to append to a completed match preview."""
    winner = ctx.get("winner")
    final_result = ctx.get("final_result") or ""
    p1_name = ctx.get("p1_name") or "Player 1"
    p2_name = ctx.get("p2_name") or "Player 2"

    if not winner:
        return None

    if winner == "First Player":
        winner_name = p1_name
        score = final_result
    elif winner == "Second Player":
        winner_name = p2_name
        score = final_result
    else:
        return None

    if score:
        return f"\n\nUPDATE: {winner_name} won {score}."
    return f"\n\nUPDATE: {winner_name} won."


# ─────────────────────────────────────────────────────────────────────────────
# MAIN JOBS
# ─────────────────────────────────────────────────────────────────────────────

def generate_previews(conn: psycopg2.extensions.connection, limit: int = 50) -> dict:
    """
    Generate 250-word SEO previews for upcoming matches that don't have one yet.
    Matches: next 7 days, seo_preview IS NULL.
    Returns {processed, generated, skipped, errors}.
    """
    if not ANTHROPIC_API_KEY:
        log.error("ANTHROPIC_API_KEY not set — skipping preview generation")
        return {"processed": 0, "generated": 0, "skipped": 0, "errors": 0}

    today = date.today()
    cutoff = today + timedelta(days=7)

    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT m.id
            FROM matches m
            WHERE m.seo_preview IS NULL
              AND m.event_date BETWEEN %s AND %s
              AND m.event_status NOT IN ('Cancelled', 'Postponed', 'Walkover')
              AND m.first_player_id IS NOT NULL
              AND m.second_player_id IS NOT NULL
            ORDER BY m.event_date ASC
            LIMIT %s
            """,
            (today.isoformat(), cutoff.isoformat(), limit),
        )
        match_ids = [r["id"] for r in cur.fetchall()]

    log.info(f"generate_previews: {len(match_ids)} matches need previews")

    generated = skipped = errors = 0

    for match_id in match_ids:
        try:
            with conn.cursor() as cur:
                ctx = _fetch_match_context(cur, match_id)
            if not ctx:
                skipped += 1
                continue

            prompt = _build_prompt(ctx)
            preview_text = _call_anthropic(prompt, max_tokens=400)

            if not preview_text:
                skipped += 1
                continue

            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE matches SET
                        seo_preview              = %s,
                        seo_preview_generated_at = NOW()
                    WHERE id = %s
                    """,
                    (preview_text, match_id),
                )
            conn.commit()
            generated += 1

            p1 = ctx.get("p1_name", "?")
            p2 = ctx.get("p2_name", "?")
            log.info(f"  Generated preview for match_id={match_id} ({p1} vs {p2})")

        except Exception as exc:
            errors += 1
            log.error(f"  Preview generation failed for match_id={match_id}: {type(exc).__name__}: {exc}")
            try:
                conn.rollback()
            except Exception:
                pass

    log.info(f"generate_previews done: generated={generated} skipped={skipped} errors={errors}")
    return {
        "processed": len(match_ids),
        "generated": generated,
        "skipped": skipped,
        "errors": errors,
    }


def append_results(conn: psycopg2.extensions.connection, days_back: int = 3) -> dict:
    """
    For recently completed matches that have a preview but no result suffix,
    append the match result to the preview text.
    Returns {processed, updated, errors}.
    """
    since = (date.today() - timedelta(days=days_back)).isoformat()

    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT m.id
            FROM matches m
            WHERE m.seo_preview IS NOT NULL
              AND m.seo_preview NOT LIKE '%%UPDATE:%%'
              AND m.winner IS NOT NULL
              AND m.event_status IN ('Finished', 'Retired', 'Walkover')
              AND m.event_date >= %s
            ORDER BY m.event_date DESC
            LIMIT 50
            """,
            (since,),
        )
        match_ids = [r["id"] for r in cur.fetchall()]

    log.info(f"append_results: {len(match_ids)} completed matches to update")
    updated = errors = 0

    for match_id in match_ids:
        try:
            with conn.cursor() as cur:
                ctx = _fetch_match_context(cur, match_id)
                if not ctx:
                    continue

                suffix = _build_result_suffix(ctx)
                if not suffix:
                    continue

                cur.execute(
                    """
                    UPDATE matches SET
                        seo_preview = seo_preview || %s
                    WHERE id = %s
                      AND seo_preview NOT LIKE '%%UPDATE:%%'
                    """,
                    (suffix, match_id),
                )
                if cur.rowcount:
                    updated += 1
                    p1 = ctx.get("p1_name", "?")
                    p2 = ctx.get("p2_name", "?")
                    log.info(f"  Appended result for match_id={match_id} ({p1} vs {p2})")

            conn.commit()

        except Exception as exc:
            errors += 1
            log.error(f"  Result append failed for match_id={match_id}: {exc}")
            try:
                conn.rollback()
            except Exception:
                pass

    log.info(f"append_results done: updated={updated} errors={errors}")
    return {"processed": len(match_ids), "updated": updated, "errors": errors}


# ─────────────────────────────────────────────────────────────────────────────
# CLI ENTRY POINT
# ─────────────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="ratethat.tennis SEO content generator")
    parser.add_argument(
        "--job",
        choices=["previews", "results", "all"],
        default="all",
        help="Which job to run (default: all)",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=50,
        help="Max previews to generate per run (default: 50)",
    )
    parser.add_argument(
        "--days-back",
        type=int,
        default=3,
        help="Days back for result append (default: 3)",
    )
    args = parser.parse_args()

    conn = get_db_conn()
    log.info(f"Connected to database. Running content_gen job: {args.job}")

    try:
        if args.job in ("previews", "all"):
            result = generate_previews(conn, limit=args.limit)
            log.info(f"previews: {result}")

        if args.job in ("results", "all"):
            result = append_results(conn, days_back=args.days_back)
            log.info(f"results: {result}")

    except KeyboardInterrupt:
        log.info("Interrupted")
    finally:
        conn.close()
        log.info("Done.")


if __name__ == "__main__":
    main()
