"""
ratethat.tennis — Pipeline email dispatch tasks.

Called from scheduler.py on a daily schedule:
    send_daily_predictions_digest()  — 08:00 UTC, top-20 predictions to opted-in users
    send_daily_picks_emails()        — 08:30 UTC, personalised picks + P&L to users with picks

Requires: RESEND_API_KEY env var set on the service.
"""
from __future__ import annotations

import logging
import os
import sys
from datetime import date, timedelta
from pathlib import Path

import psycopg2
import psycopg2.extras

# Allow importing api.email from the pipeline service (flat Docker copy)
_app_dir = Path(__file__).resolve().parent.parent
if str(_app_dir) not in sys.path:
    sys.path.insert(0, str(_app_dir))

log = logging.getLogger("rtt.email_tasks")

_SITE = "https://ratethat.tennis"


def _db():
    url = os.environ.get("DATABASE_URL") or os.environ.get("DATABASE_PUBLIC_URL") or ""
    conn = psycopg2.connect(url)
    conn.cursor_factory = psycopg2.extras.RealDictCursor
    return conn


def _send(to: str, subject: str, html: str) -> bool:
    """Send via api/email.py logic (urllib, no SDK needed)."""
    try:
        # Try package import first (local dev), fall back to flat file (Docker)
        try:
            from api.email import send_email
        except ImportError:
            from email_utils import send_email  # type: ignore
        send_email(to, subject, html)
        log.info("Sent '%s' → %s", subject, to)
        return True
    except Exception as e:
        log.error("Email failed '%s' → %s: %s", subject, to, e)
        return False


# ─────────────────────────────────────────────────────────────────────────────
# 1. Daily predictions digest
# ─────────────────────────────────────────────────────────────────────────────

def send_daily_predictions_digest() -> dict:
    """
    Fetch today's top 20 predictions (by confidence), build one email per opted-in user.
    Returns summary: {users_sent, skipped, errors}
    """
    log.info("Email task: daily predictions digest starting...")
    try:
        from api.email import render_daily_predictions
    except ImportError:
        log.error("Cannot import api.email — skipping digest")
        return {"users_sent": 0, "skipped": 0, "errors": 1}

    today = date.today()
    date_str = today.strftime("%A %-d %B")  # e.g. "Wednesday 14 May"

    conn = _db()
    try:
        with conn.cursor() as cur:
            # Top 20 predictions for today + tomorrow, ordered by model confidence
            cur.execute("""
                SELECT
                    mp.match_id,
                    mp.prob_first_player,
                    mp.prob_second_player,
                    mp.predicted_winner,
                    p1.player_name  AS p1_name,
                    p2.player_name  AS p2_name,
                    t.tournament_name AS tournament,
                    m.surface_name  AS surface,
                    m.tournament_round AS round,
                    m.event_date
                FROM model_predictions mp
                JOIN matches m   ON m.id = mp.match_id
                JOIN players p1  ON p1.id = m.first_player_id
                JOIN players p2  ON p2.id = m.second_player_id
                LEFT JOIN tournaments t ON t.id = m.tournament_id
                WHERE m.event_date BETWEEN %s AND %s
                  AND mp.prob_first_player IS NOT NULL
                  AND mp.prob_second_player IS NOT NULL
                  AND mp.prob_first_player NOT BETWEEN 0.49 AND 0.51
                  AND m.game_result IS NULL
                  AND m.singles_doubles = 'S'
                ORDER BY GREATEST(
                    ABS(mp.prob_first_player - 0.5),
                    ABS(mp.prob_second_player - 0.5)
                ) DESC
                LIMIT 20
            """, (str(today), str(today + timedelta(days=1))))
            predictions_raw = cur.fetchall()

            # Fetch opted-in users
            cur.execute("""
                SELECT id, email, display_name
                FROM users
                WHERE email_digest = TRUE
                  AND email IS NOT NULL AND email != ''
            """)
            users = cur.fetchall()
    finally:
        conn.close()

    if not predictions_raw:
        log.info("No predictions for digest today — skipping")
        return {"users_sent": 0, "skipped": len(users), "errors": 0}

    # Shape predictions for the template
    picks = []
    for r in predictions_raw:
        p1p = float(r["prob_first_player"] or 0)
        p2p = float(r["prob_second_player"] or 0)
        if p1p >= p2p:
            winner = r["p1_name"]
            prob = p1p
        else:
            winner = r["p2_name"]
            prob = p2p

        confidence = "high" if abs(p1p - p2p) >= 0.20 else ("medium" if abs(p1p - p2p) >= 0.10 else "low")
        picks.append({
            "match_id":        r["match_id"],
            "player1":         r["p1_name"] or "",
            "player2":         r["p2_name"] or "",
            "predicted_winner": winner,
            "prob":            prob,
            "edge_pct":        0.0,  # will add odds-based edge in future
            "confidence":      confidence,
            "surface":         (r["surface"] or "").capitalize(),
            "match_label":     f"{r['tournament'] or ''} · {r['round'] or ''}",
        })

    html = render_daily_predictions(picks, date_str)

    sent = skipped = errors = 0
    for u in users:
        ok = _send(u["email"], f"Today's tennis predictions — {date_str}", html)
        if ok:
            sent += 1
        else:
            errors += 1

    log.info("Predictions digest: sent=%d skipped=%d errors=%d", sent, skipped, errors)
    return {"users_sent": sent, "skipped": skipped, "errors": errors}


# ─────────────────────────────────────────────────────────────────────────────
# 2. Daily picks summary (personalised per user)
# ─────────────────────────────────────────────────────────────────────────────

def send_daily_picks_emails() -> dict:
    """
    For every opted-in user who has pending/live picks or settled picks in the last 3 days,
    send a personalised digest showing their record and upcoming picks.
    """
    log.info("Email task: daily picks emails starting...")
    try:
        from api.email import render_my_picks_digest
    except ImportError:
        log.error("Cannot import api.email — skipping picks digest")
        return {"users_sent": 0, "skipped": 0, "errors": 0}

    today = date.today()
    three_days_ago = today - timedelta(days=3)

    conn = _db()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT DISTINCT u.id, u.email, u.display_name
                FROM users u
                JOIN user_picks up ON up.user_id = u.id
                WHERE u.email_picks = TRUE
                  AND u.email IS NOT NULL AND u.email != ''
                  AND (
                      up.status IN ('pending','live')
                      OR (up.status IN ('won','lost') AND up.settled_at >= %s)
                  )
            """, (str(three_days_ago),))
            users = cur.fetchall()
    finally:
        conn.close()

    if not users:
        log.info("No users with active/recent picks — skipping")
        return {"users_sent": 0, "skipped": 0, "errors": 0}

    sent = errors = 0
    for u in users:
        try:
            html = _build_picks_email(u["id"], u.get("display_name") or u["email"].split("@")[0])
            if html is None:
                continue
            ok = _send(u["email"], "Your picks update — ratethat.tennis", html)
            if ok:
                sent += 1
            else:
                errors += 1
        except Exception as e:
            log.error("Picks email failed for user %s: %s", u["id"], e)
            errors += 1

    log.info("Picks digest: sent=%d errors=%d", sent, errors)
    return {"users_sent": sent, "skipped": 0, "errors": errors}


def _build_picks_email(user_id: int, display_name: str):
    """Query DB for one user's picks and render the email. Returns None if nothing to report."""
    from api.email import render_my_picks_digest

    today = date.today()
    conn = _db()
    try:
        with conn.cursor() as cur:
            # Active (upcoming/live) picks
            cur.execute("""
                SELECT
                    up.confidence_stars,
                    up.status,
                    up.our_odds,
                    p.player_name AS my_pick,
                    p1.player_name AS player1,
                    p2.player_name AS player2,
                    t.tournament_name AS tournament,
                    m.tournament_round AS round,
                    m.surface_name AS surface,
                    m.event_date
                FROM user_picks up
                JOIN matches m   ON m.id = up.match_id
                JOIN players p   ON p.id = up.player_id
                JOIN players p1  ON p1.id = m.first_player_id
                JOIN players p2  ON p2.id = m.second_player_id
                LEFT JOIN tournaments t ON t.id = m.tournament_id
                WHERE up.user_id = %s
                  AND up.status IN ('pending','live')
                ORDER BY m.event_date, m.id
                LIMIT 10
            """, (user_id,))
            active_rows = cur.fetchall()

            # Recent settled picks (last 5 days)
            cur.execute("""
                SELECT
                    up.status,
                    up.profit_loss,
                    up.our_odds,
                    p.player_name AS my_pick,
                    p1.player_name AS player1,
                    p2.player_name AS player2,
                    t.tournament_name AS tournament,
                    m.final_result,
                    m.winner
                FROM user_picks up
                JOIN matches m   ON m.id = up.match_id
                JOIN players p   ON p.id = up.player_id
                JOIN players p1  ON p1.id = m.first_player_id
                JOIN players p2  ON p2.id = m.second_player_id
                LEFT JOIN tournaments t ON t.id = m.tournament_id
                WHERE up.user_id = %s
                  AND up.status IN ('won','lost')
                  AND up.settled_at >= NOW() - INTERVAL '5 days'
                ORDER BY up.settled_at DESC
                LIMIT 5
            """, (user_id,))
            recent_rows = cur.fetchall()

            # Overall stats
            cur.execute("""
                SELECT
                    COUNT(*) FILTER (WHERE status IN ('won','lost','void')) AS total,
                    COUNT(*) FILTER (WHERE status = 'won') AS wins,
                    COUNT(*) FILTER (WHERE status = 'lost') AS losses,
                    COALESCE(SUM(profit_loss), 0) AS total_pl
                FROM user_picks
                WHERE user_id = %s AND status IN ('won','lost','void')
            """, (user_id,))
            stats_row = cur.fetchone()
    finally:
        conn.close()

    if not active_rows and not recent_rows:
        return None

    # Shape for template
    upcoming = []
    for r in active_rows:
        opp = r["player2"] if r["my_pick"] == r["player1"] else r["player1"]
        upcoming.append({
            "my_pick":    r["my_pick"],
            "match_label": f"{r['player1']} vs {r['player2']}",
            "tournament": r.get("tournament") or "",
            "surface":    (r.get("surface") or "").capitalize(),
            "kickoff":    str(r["event_date"]) if r.get("event_date") else "",
        })

    recent_results = []
    for r in recent_rows:
        correct = r["status"] == "won"
        pl = float(r["profit_loss"] or 0)
        pl_str = f"+£{pl:.2f}" if pl >= 0 else f"-£{abs(pl):.2f}"
        recent_results.append({
            "my_pick":    r["my_pick"],
            "match_label": f"{r['player1']} vs {r['player2']}",
            "result":     pl_str,
            "correct":    correct,
        })

    total  = int(stats_row["total"]  or 0)
    wins   = int(stats_row["wins"]   or 0)
    losses = int(stats_row["losses"] or 0)
    total_pl = float(stats_row["total_pl"] or 0)
    roi = round(total_pl / max(total, 1) * 100, 1)   # simplified P&L per pick × 100

    stats = {"total_picks": total, "correct": wins, "roi_pct": roi}

    return render_my_picks_digest(display_name, upcoming, recent_results, stats)
