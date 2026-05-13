"""
ratethat.tennis API — Auth routes.

POST /auth/register   { email, password, display_name? }  → { token, user }
POST /auth/login      { email, password }                  → { token, user }
GET  /auth/me         (Bearer token required)              → { user }
"""
import logging
import re
from fastapi import APIRouter, HTTPException, Depends
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel, field_validator
from typing import Optional

from api.db import query_one, get_conn
from api.auth import hash_password, verify_password, create_access_token, decode_token
from api import email as rtt_email

log = logging.getLogger("api.auth")
router = APIRouter(prefix="/auth", tags=["auth"])
bearer = HTTPBearer(auto_error=False)

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


# ─────────────────────────────────────────────────────────────────────────────
# Pydantic models
# ─────────────────────────────────────────────────────────────────────────────

class RegisterRequest(BaseModel):
    email: str
    password: str
    display_name: Optional[str] = None

    @field_validator("email")
    @classmethod
    def validate_email(cls, v):
        if not EMAIL_RE.match(v.strip()):
            raise ValueError("Invalid email address")
        return v.strip().lower()

    @field_validator("password")
    @classmethod
    def validate_password(cls, v):
        if len(v) < 6:
            raise ValueError("Password must be at least 6 characters")
        return v


class LoginRequest(BaseModel):
    email: str
    password: str

    @field_validator("email")
    @classmethod
    def normalise_email(cls, v):
        return v.strip().lower()


# ─────────────────────────────────────────────────────────────────────────────
# Dependency: get current user from Bearer token
# ─────────────────────────────────────────────────────────────────────────────

def get_current_user(creds: HTTPAuthorizationCredentials = Depends(bearer)):
    """Raise 401 if token is missing or invalid. Returns user dict."""
    if not creds:
        raise HTTPException(status_code=401, detail="Not authenticated")
    payload = decode_token(creds.credentials)
    if not payload:
        raise HTTPException(status_code=401, detail="Invalid or expired token")
    user = query_one("SELECT id, email, display_name, created_at FROM users WHERE id = %s",
                     (int(payload["sub"]),))
    if not user:
        raise HTTPException(status_code=401, detail="User not found")
    return user


def get_optional_user(creds: HTTPAuthorizationCredentials = Depends(bearer)):
    """Like get_current_user but returns None instead of raising if not authed."""
    if not creds:
        return None
    payload = decode_token(creds.credentials)
    if not payload:
        return None
    return query_one("SELECT id, email, display_name FROM users WHERE id = %s",
                     (int(payload["sub"]),))


# ─────────────────────────────────────────────────────────────────────────────
# Routes
# ─────────────────────────────────────────────────────────────────────────────

@router.post("/register")
def register(req: RegisterRequest):
    existing = query_one("SELECT id FROM users WHERE email = %s", (req.email,))
    if existing:
        raise HTTPException(status_code=409, detail="An account with that email already exists")

    pw_hash = hash_password(req.password)
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """INSERT INTO users (email, password_hash, display_name)
                   VALUES (%s, %s, %s)
                   RETURNING id, email, display_name, created_at""",
                (req.email, pw_hash, req.display_name),
            )
            user = dict(cur.fetchone())

    token = create_access_token(user["id"], user["email"])

    # Send welcome email (fire-and-forget — failure must not break registration)
    try:
        html = rtt_email.render_welcome_email(user.get("display_name") or "")
        rtt_email.send_email(user["email"], "Welcome to RateThatTennis!", html)
        with get_conn() as _conn:
            with _conn.cursor() as _cur:
                _cur.execute("UPDATE users SET welcome_sent = TRUE WHERE id = %s", (user["id"],))
    except Exception as _e:
        log.warning("Welcome email failed for %s: %s", user["email"], _e)

    return {"token": token, "user": _fmt_user(user)}


@router.post("/login")
def login(req: LoginRequest):
    row = query_one("SELECT id, email, display_name, password_hash, created_at FROM users WHERE email = %s",
                    (req.email,))
    if not row or not verify_password(req.password, row["password_hash"]):
        raise HTTPException(status_code=401, detail="Incorrect email or password")

    # Update last_login_at
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("UPDATE users SET last_login_at = NOW() WHERE id = %s", (row["id"],))

    token = create_access_token(row["id"], row["email"])
    return {"token": token, "user": _fmt_user(row)}


@router.get("/me")
def me(current_user=Depends(get_current_user)):
    return {"user": _fmt_user(current_user)}


def _fmt_user(u: dict) -> dict:
    return {
        "id":           u["id"],
        "email":        u["email"],
        "display_name": u.get("display_name"),
        "created_at":   str(u.get("created_at", "")),
    }
