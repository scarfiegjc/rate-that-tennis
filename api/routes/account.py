"""
api/routes/account.py — User account: profile + email subscription prefs
"""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from typing import Optional

from api.db import query_one, query_many, execute
from api.routes.auth import get_current_user

router = APIRouter(prefix="/account", tags=["account"])


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _get_prefs(user_id: int) -> dict:
    """Return all email subscription prefs for a user as {type: bool}."""
    rows = query_many(
        "SELECT subscription_type, is_subscribed FROM email_subscriptions WHERE user_id = %s",
        (user_id,),
    )
    return {r["subscription_type"]: r["is_subscribed"] for r in rows}


def _upsert_pref(user_id: int, sub_type: str, subscribed: bool):
    execute(
        """
        INSERT INTO email_subscriptions (user_id, subscription_type, is_subscribed, updated_at)
        VALUES (%s, %s, %s, NOW())
        ON CONFLICT (user_id, subscription_type)
        DO UPDATE SET is_subscribed = EXCLUDED.is_subscribed, updated_at = NOW()
        """,
        (user_id, sub_type, subscribed),
    )


# ─── Profile ──────────────────────────────────────────────────────────────────

class ProfileOut(BaseModel):
    id: int
    email: str
    display_name: Optional[str]
    is_admin: bool
    created_at: str


class ProfileUpdate(BaseModel):
    display_name: Optional[str] = None


@router.get("/profile")
def get_profile(current_user=Depends(get_current_user)):
    row = query_one(
        "SELECT id, email, display_name, is_admin, created_at FROM users WHERE id = %s",
        (current_user["id"],),
    )
    if not row:
        raise HTTPException(status_code=404, detail="User not found")
    return {
        "id": row["id"],
        "email": row["email"],
        "display_name": row["display_name"],
        "is_admin": row["is_admin"],
        "created_at": row["created_at"].isoformat() if row.get("created_at") else None,
    }


@router.put("/profile")
def update_profile(body: ProfileUpdate, current_user=Depends(get_current_user)):
    if body.display_name is not None:
        execute(
            "UPDATE users SET display_name = %s WHERE id = %s",
            (body.display_name.strip() or None, current_user["id"]),
        )
    return {"ok": True}


# ─── Email prefs ──────────────────────────────────────────────────────────────

VALID_TYPES = {"daily_predictions", "my_picks_digest"}


class PrefsOut(BaseModel):
    daily_predictions: bool
    my_picks_digest: bool


class PrefsUpdate(BaseModel):
    daily_predictions: Optional[bool] = None
    my_picks_digest: Optional[bool] = None


@router.get("/email-prefs")
def get_email_prefs(current_user=Depends(get_current_user)):
    prefs = _get_prefs(current_user["id"])
    return {
        "daily_predictions": prefs.get("daily_predictions", False),
        "my_picks_digest": prefs.get("my_picks_digest", False),
    }


@router.put("/email-prefs")
def update_email_prefs(body: PrefsUpdate, current_user=Depends(get_current_user)):
    if body.daily_predictions is not None:
        _upsert_pref(current_user["id"], "daily_predictions", body.daily_predictions)
    if body.my_picks_digest is not None:
        _upsert_pref(current_user["id"], "my_picks_digest", body.my_picks_digest)
    return {"ok": True}
