"""
api/routes/admin_marketing.py — Admin-only marketing & email management endpoints
"""

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from typing import Optional
from datetime import date

from api.db import query_one, query_many, execute
from api.routes.auth import get_current_user
from api import email as email_mod

router = APIRouter(prefix="/admin", tags=["admin"])


# ─── Guard ────────────────────────────────────────────────────────────────────

def require_admin(current_user=Depends(get_current_user)):
    row = query_one("SELECT is_admin FROM users WHERE id = %s", (current_user["id"],))
    if not row or not row.get("is_admin"):
        raise HTTPException(status_code=403, detail="Admin access required")
    return current_user


# ─── Users ────────────────────────────────────────────────────────────────────

@router.get("/users")
def list_users(
    search: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    _admin=Depends(require_admin),
):
    offset = (page - 1) * page_size
    if search:
        like = f"%{search}%"
        rows = query_many(
            """
            SELECT u.id, u.email, u.display_name, u.is_admin, u.created_at, u.last_login_at,
                   (SELECT COUNT(*) FROM email_subscriptions es
                    WHERE es.user_id = u.id AND es.is_subscribed = TRUE) AS sub_count
            FROM users u
            WHERE u.email ILIKE %s OR u.display_name ILIKE %s
            ORDER BY u.created_at DESC
            LIMIT %s OFFSET %s
            """,
            (like, like, page_size, offset),
        )
        total = query_one(
            "SELECT COUNT(*) AS n FROM users WHERE email ILIKE %s OR display_name ILIKE %s",
            (like, like),
        )["n"]
    else:
        rows = query_many(
            """
            SELECT u.id, u.email, u.display_name, u.is_admin, u.created_at, u.last_login_at,
                   (SELECT COUNT(*) FROM email_subscriptions es
                    WHERE es.user_id = u.id AND es.is_subscribed = TRUE) AS sub_count
            FROM users u
            ORDER BY u.created_at DESC
            LIMIT %s OFFSET %s
            """,
            (page_size, offset),
        )
        total = query_one("SELECT COUNT(*) AS n FROM users")["n"]

    def fmt(row):
        return {
            "id": row["id"],
            "email": row["email"],
            "display_name": row["display_name"],
            "is_admin": row["is_admin"],
            "sub_count": row["sub_count"],
            "created_at": row["created_at"].isoformat() if row.get("created_at") else None,
            "last_login_at": row["last_login_at"].isoformat() if row.get("last_login_at") else None,
        }

    return {"users": [fmt(r) for r in rows], "total": total, "page": page, "page_size": page_size}


# ─── Email history ────────────────────────────────────────────────────────────

@router.get("/email/history")
def email_history(
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    _admin=Depends(require_admin),
):
    offset = (page - 1) * page_size
    rows = query_many(
        """
        SELECT es.id, es.send_type, es.subject, es.body_preview,
               es.recipient_count, es.status, es.sent_at,
               u.email AS sent_by_email,
               ru.email AS recipient_email
        FROM email_sends es
        LEFT JOIN users u ON u.id = es.sent_by_user_id
        LEFT JOIN users ru ON ru.id = es.recipient_user_id
        ORDER BY es.sent_at DESC
        LIMIT %s OFFSET %s
        """,
        (page_size, offset),
    )
    total = query_one("SELECT COUNT(*) AS n FROM email_sends")["n"]

    def fmt(r):
        return {
            "id": r["id"],
            "send_type": r["send_type"],
            "subject": r["subject"],
            "body_preview": r["body_preview"],
            "recipient_count": r["recipient_count"],
            "recipient_email": r["recipient_email"],
            "status": r["status"],
            "sent_at": r["sent_at"].isoformat() if r.get("sent_at") else None,
            "sent_by_email": r["sent_by_email"],
        }

    return {"sends": [fmt(r) for r in rows], "total": total}


# ─── Send individual email ────────────────────────────────────────────────────

class SendIndividualBody(BaseModel):
    user_id: int
    subject: str
    body_html: str


@router.post("/email/send-individual")
def send_individual(body: SendIndividualBody, admin=Depends(require_admin)):
    user = query_one("SELECT id, email, display_name FROM users WHERE id = %s", (body.user_id,))
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    html = email_mod.render_announcement(body.subject, body.body_html, user["display_name"] or "")
    email_mod.send_email(user["email"], body.subject, html)

    execute(
        """
        INSERT INTO email_sends (send_type, subject, body_preview, recipient_count,
                                  recipient_user_id, sent_by_user_id, status)
        VALUES ('individual', %s, %s, 1, %s, %s, 'sent')
        """,
        (body.subject, body.body_html[:200], body.user_id, admin["id"]),
    )
    return {"ok": True, "sent_to": user["email"]}


# ─── Broadcast announcement ──────────────────────────────────────────────────

class BroadcastBody(BaseModel):
    subject: str
    body_html: str
    subscription_filter: Optional[str] = None  # e.g. "daily_predictions" — None = all users


@router.post("/email/send-announcement")
def send_announcement(body: BroadcastBody, admin=Depends(require_admin)):
    if body.subscription_filter:
        users = query_many(
            """
            SELECT u.id, u.email, u.display_name
            FROM users u
            JOIN email_subscriptions es ON es.user_id = u.id
            WHERE es.subscription_type = %s AND es.is_subscribed = TRUE
            """,
            (body.subscription_filter,),
        )
    else:
        users = query_many("SELECT id, email, display_name FROM users ORDER BY id", ())

    sent = 0
    errors = []
    for u in users:
        try:
            html = email_mod.render_announcement(body.subject, body.body_html, u["display_name"] or "")
            email_mod.send_email(u["email"], body.subject, html)
            sent += 1
        except Exception as e:
            errors.append({"email": u["email"], "error": str(e)})

    execute(
        """
        INSERT INTO email_sends (send_type, subject, body_preview, recipient_count,
                                  sent_by_user_id, status)
        VALUES ('announcement', %s, %s, %s, %s, 'sent')
        """,
        (body.subject, body.body_html[:200], sent, admin["id"]),
    )
    return {"ok": True, "sent": sent, "errors": errors}


# ─── Trigger daily predictions email ─────────────────────────────────────────

@router.post("/email/send-daily-predictions")
def send_daily_predictions(admin=Depends(require_admin)):
    """
    Pull today's predictions from model_predictions + matches,
    then email all users subscribed to daily_predictions.
    """
    today = date.today()
    date_str = today.strftime("%A %-d %B")

    # Fetch predictions for today
    picks_rows = query_many(
        """
        SELECT
            mp.prob_first_player,
            mp.prob_second_player,
            mp.confidence,
            mp.bet_recommendations,
            m.first_player_name,
            m.second_player_name,
            t.name AS tournament_name,
            s.name AS surface_name,
            bo_a.decimal_odds AS odds_a,
            bo_b.decimal_odds AS odds_b
        FROM model_predictions mp
        JOIN matches m ON m.id = mp.match_id
        JOIN tournaments t ON t.id = m.tournament_id
        JOIN surfaces s ON s.id = t.surface_id
        LEFT JOIN bookmaker_odds bo_a ON bo_a.match_id = m.id AND bo_a.player_ref = 'first_player'
            AND bo_a.bookmaker = (
                SELECT bookmaker FROM bookmaker_odds WHERE match_id = m.id
                ORDER BY fetched_at DESC LIMIT 1
            )
        LEFT JOIN bookmaker_odds bo_b ON bo_b.match_id = m.id AND bo_b.player_ref = 'second_player'
            AND bo_b.bookmaker = bo_a.bookmaker
        WHERE DATE(m.date) = %s
          AND mp.confidence IN ('high', 'medium')
        ORDER BY mp.confidence, mp.prob_first_player DESC
        LIMIT 10
        """,
        (today,),
    )

    picks = []
    for r in picks_rows:
        p1_prob = float(r["prob_first_player"] or 0.5)
        p2_prob = float(r["prob_second_player"] or 0.5)
        if p1_prob >= p2_prob:
            winner = r["first_player_name"]
            prob = p1_prob
            impl_prob = 1 / float(r["odds_a"]) if r.get("odds_a") else prob
        else:
            winner = r["second_player_name"]
            prob = p2_prob
            impl_prob = 1 / float(r["odds_b"]) if r.get("odds_b") else prob
        edge_pct = round((prob - impl_prob) * 100, 1)
        picks.append({
            "match_label": r["tournament_name"],
            "player1": r["first_player_name"],
            "player2": r["second_player_name"],
            "surface": r["surface_name"],
            "predicted_winner": winner,
            "prob": prob,
            "edge_pct": edge_pct,
            "confidence": r["confidence"],
        })

    # Get subscribers
    subscribers = query_many(
        """
        SELECT u.id, u.email, u.display_name
        FROM users u
        JOIN email_subscriptions es ON es.user_id = u.id
        WHERE es.subscription_type = 'daily_predictions' AND es.is_subscribed = TRUE
        """,
        (),
    )

    subject = f"ratethat.tennis — Today's Predictions ({date_str})"
    sent = 0
    errors = []
    for u in subscribers:
        try:
            html = email_mod.render_daily_predictions(picks, date_str)
            email_mod.send_email(u["email"], subject, html)
            sent += 1
        except Exception as e:
            errors.append({"email": u["email"], "error": str(e)})

    execute(
        """
        INSERT INTO email_sends (send_type, subject, body_preview, recipient_count,
                                  sent_by_user_id, status)
        VALUES ('daily_predictions', %s, %s, %s, %s, 'sent')
        """,
        (subject, f"{len(picks)} predictions for {date_str}", sent, admin["id"]),
    )
    return {"ok": True, "picks": len(picks), "sent": sent, "errors": errors}
