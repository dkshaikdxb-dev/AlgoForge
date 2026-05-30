"""JWT email/password auth."""
import os
from datetime import datetime, timedelta, timezone
from typing import Optional

import bcrypt
import jwt
from fastapi import APIRouter, Cookie, Depends, HTTPException, Request, Response, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, EmailStr, Field

from auth_csrf import AUTH_COOKIE, clear_auth_cookies, set_auth_cookies
from db import BaseDocument, get_db, now_iso
from services.audit import AuditEventType, AuditSeverity, record_event

router = APIRouter(prefix="/auth", tags=["auth"])
security = HTTPBearer(auto_error=False)

JWT_SECRET = os.environ["JWT_SECRET"]
JWT_ALG = "HS256"
JWT_TTL_HOURS = 24 * 7


class User(BaseDocument):
    email: str
    name: str
    password_hash: str
    role: str = "trader"


class RegisterRequest(BaseModel):
    email: EmailStr
    name: str = Field(min_length=1, max_length=80)
    password: str = Field(min_length=6, max_length=200)


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: dict


def hash_password(p: str) -> str:
    return bcrypt.hashpw(p.encode(), bcrypt.gensalt()).decode()


def verify_password(p: str, h: str) -> bool:
    try:
        return bcrypt.checkpw(p.encode(), h.encode())
    except Exception:
        return False


def make_token(user_id: str, email: str) -> str:
    payload = {
        "sub": user_id,
        "email": email,
        "exp": datetime.now(timezone.utc) + timedelta(hours=JWT_TTL_HOURS),
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALG)


async def get_current_user(
    creds: Optional[HTTPAuthorizationCredentials] = Depends(security),
    auth_cookie: Optional[str] = Cookie(default=None, alias=AUTH_COOKIE),
) -> dict:
    # Prefer cookie (browser-side, HttpOnly); fall back to Bearer header for
    # curl/test-agent clients.
    token = auth_cookie or (creds.credentials if creds else None)
    if not token:
        raise HTTPException(status_code=401, detail="Not authenticated")
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALG])
    except jwt.PyJWTError:
        raise HTTPException(status_code=401, detail="Invalid token")
    db = get_db()
    user = await db.users.find_one({"_id": payload["sub"]})
    if not user:
        # fall back to email
        user = await db.users.find_one({"email": payload.get("email")})
    if not user:
        raise HTTPException(status_code=401, detail="User not found")
    return {
        "id": str(user.get("_id", user.get("id"))),
        "email": user["email"],
        "name": user.get("name", ""),
        "role": user.get("role", "trader"),
    }


def _public_user(u: dict) -> dict:
    return {
        "id": str(u.get("_id", u.get("id"))),
        "email": u["email"],
        "name": u.get("name", ""),
        "role": u.get("role", "trader"),
    }


@router.post("/register", response_model=TokenResponse)
async def register(req: RegisterRequest, response: Response):
    db = get_db()
    existing = await db.users.find_one({"email": req.email.lower()})
    if existing:
        raise HTTPException(status_code=409, detail="Email already registered")
    import uuid

    user_id = str(uuid.uuid4())
    doc = {
        "_id": user_id,
        "email": req.email.lower(),
        "name": req.name,
        "password_hash": hash_password(req.password),
        "role": "trader",
        "created_at": now_iso(),
        "updated_at": now_iso(),
    }
    await db.users.insert_one(doc)
    # seed default risk limits
    await db.risk_limits.insert_one(
        {
            "user_id": user_id,
            "max_drawdown_pct": 15.0,
            "daily_loss_cap": 25000.0,
            "position_limit": 5,
            "kill_switch": False,
            "updated_at": now_iso(),
        }
    )
    await record_event(user_id, AuditEventType.AUTH_REGISTER, actor="user",
                       summary=f"Registered {req.email.lower()}")
    token = make_token(user_id, req.email.lower())
    set_auth_cookies(response, token)
    return TokenResponse(access_token=token, user=_public_user(doc))


@router.post("/login", response_model=TokenResponse)
async def login(req: LoginRequest, response: Response):
    db = get_db()
    user = await db.users.find_one({"email": req.email.lower()})
    if not user or not verify_password(req.password, user["password_hash"]):
        await record_event(None, AuditEventType.AUTH_LOGIN, severity=AuditSeverity.WARN,
                           actor="user", summary=f"Failed login for {req.email.lower()}")
        raise HTTPException(status_code=401, detail="Invalid email or password")
    await record_event(str(user["_id"]), AuditEventType.AUTH_LOGIN, actor="user",
                       summary=f"Login {req.email.lower()}")
    token = make_token(str(user["_id"]), user["email"])
    set_auth_cookies(response, token)
    return TokenResponse(access_token=token, user=_public_user(user))


@router.post("/logout")
async def logout(response: Response, user: Optional[dict] = None):
    # Stateless JWT — clearing cookies is sufficient for browser-side logout.
    clear_auth_cookies(response)
    return {"ok": True}


@router.post("/migrate-token")
async def migrate_token(request: Request, response: Response):
    """One-shot bootstrap for clients with a legacy localStorage token.
    Reads Bearer, validates, and re-issues the same JWT as cookies."""
    auth = request.headers.get("Authorization", "")
    scheme, _, raw = auth.partition(" ")
    if scheme.lower() != "bearer" or not raw:
        raise HTTPException(status_code=401, detail="Missing Bearer token")
    try:
        payload = jwt.decode(raw, JWT_SECRET, algorithms=[JWT_ALG])
    except jwt.PyJWTError:
        raise HTTPException(status_code=401, detail="Invalid token")
    db = get_db()
    user = await db.users.find_one({"_id": payload["sub"]})
    if not user:
        raise HTTPException(status_code=401, detail="User not found")
    set_auth_cookies(response, raw)
    return {"ok": True, "user": _public_user(user)}


@router.get("/me")
async def me(user: dict = Depends(get_current_user)):
    return user
