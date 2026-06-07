"""Cookie/CSRF helpers for the JWT-cookie auth migration.

- Two cookies set on login/register:
    algoforge_auth  (HttpOnly, Secure, SameSite=Lax, Path=/) — JWT
    algoforge_csrf  (non-HttpOnly, Secure, SameSite=Lax, Path=/) — random nonce
  Path=/ so document.cookie exposes algoforge_csrf to React on any route.
- Double-submit CSRF middleware enforces equality of `algoforge_csrf` cookie and
  `X-CSRF-Token` header on POST/PUT/PATCH/DELETE under /api, except for an
  exempt-path allowlist (auth endpoints + broker OAuth callback + postback).
- Skipping CSRF when no auth cookie is present preserves backwards compat
  for Bearer-token-only clients (curl, testing agent).
"""
from __future__ import annotations

import os
import hmac
import logging
import secrets
from typing import Callable

from fastapi import Response
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.types import ASGIApp

logger = logging.getLogger("algoforge.auth_csrf")

AUTH_COOKIE = "algoforge_auth"
CSRF_COOKIE = "algoforge_csrf"
CSRF_HEADER = "X-CSRF-Token"
COOKIE_PATH = "/"
COOKIE_MAX_AGE = 60 * 60 * 24 * 7  # 7 days — matches JWT TTL

SAFE_METHODS = {"GET", "HEAD", "OPTIONS", "TRACE"}

# Endpoints that must accept POST without a CSRF token.
# Auth bootstrap endpoints (no cookie yet) + broker→us webhooks.
EXEMPT_CSRF_PATHS_PREFIX = (
    "/api/auth/login",
    "/api/auth/register",
    "/api/auth/logout",
    "/api/auth/migrate-token",
)
# These callbacks are unauthenticated server→server / browser-redirect flows.
EXEMPT_CSRF_PATHS_CONTAINS = (
    "/oauth/callback",
    "/postback",
)


def generate_csrf_token() -> str:
    return secrets.token_urlsafe(32)

def set_auth_cookies(response: Response, jwt_token: str) -> str:
    """Set both auth + CSRF cookies. Returns the CSRF token (for tests)."""
    csrf = generate_csrf_token()

    COOKIE_SECURE = (
        os.getenv("COOKIE_SECURE", "true").lower() == "true"
    )

    common = {
        "max_age": COOKIE_MAX_AGE,
        "path": COOKIE_PATH,
        "secure": COOKIE_SECURE,
        "samesite": "lax",
    }

    response.set_cookie(AUTH_COOKIE, jwt_token, httponly=True, **common)
    response.set_cookie(CSRF_COOKIE, csrf, httponly=False, **common)
    return csrf


def clear_auth_cookies(response: Response) -> None:
    response.delete_cookie(AUTH_COOKIE, path=COOKIE_PATH)
    response.delete_cookie(CSRF_COOKIE, path=COOKIE_PATH)


def _is_exempt(path: str) -> bool:
    if any(path.startswith(p) for p in EXEMPT_CSRF_PATHS_PREFIX):
        return True
    return any(seg in path for seg in EXEMPT_CSRF_PATHS_CONTAINS)


class CSRFMiddleware(BaseHTTPMiddleware):
    """Double-submit cookie CSRF enforcement.

    Only enforces when the request is using cookie-based auth (i.e. the
    `algoforge_auth` cookie is present). Pure Bearer-token clients (curl,
    testing agents) pass through unaffected, preserving back-compat.
    """

    async def dispatch(self, request: Request, call_next: Callable):
        method = request.method.upper()
        path = request.url.path

        # Safe methods don't need CSRF.
        if method in SAFE_METHODS:
            return await call_next(request)

        # Only protect /api/* under cookie auth.
        if not path.startswith("/api/"):
            return await call_next(request)

        # Exempt: auth bootstrap + broker webhooks/callbacks.
        if _is_exempt(path):
            return await call_next(request)

        # Bearer-only clients (no auth cookie) → bypass; they're already
        # authenticated by their explicit Authorization header.
        if not request.cookies.get(AUTH_COOKIE):
            return await call_next(request)

        cookie = request.cookies.get(CSRF_COOKIE)
        header = request.headers.get(CSRF_HEADER)
        if not cookie or not header:
            return JSONResponse(
                {"detail": "Missing CSRF token"}, status_code=403,
            )
        # Constant-time compare to avoid trivial timing oracle.
        if not hmac.compare_digest(cookie, header):
            return JSONResponse(
                {"detail": "Invalid CSRF token"}, status_code=403,
            )
        return await call_next(request)


def attach_csrf_middleware(app) -> None:
    app.add_middleware(CSRFMiddleware)
