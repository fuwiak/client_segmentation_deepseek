"""Простая session-auth для CRM (логин / пароль из env)."""

from __future__ import annotations

import logging
import secrets
from typing import Any
from urllib.parse import quote, urlparse

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import RedirectResponse, Response

from app.config import Settings, get_settings

logger = logging.getLogger(__name__)

SESSION_USER_KEY = "auth_user"

PUBLIC_PATH_PREFIXES = (
    "/static/",
    "/health",
    "/login",
    "/logout",
)

# HTMX-фрагменты — не ставить в ?next= и не делать HX-Redirect (петля на /login).
_FRAGMENT_PREFIXES = (
    "/messenger/",
    "/clients/page",
    "/clients/table",
    "/clients/ai/",
    "/clients/tag-rules",
    "/enrich/",
    "/segment/progress",
    "/segment/start",
    "/moysklad/status",
    "/moysklad/sync",
    "/moysklad/push",
    "/upload/",
    "/diagnostics/",
    "/ws/",
)


def auth_required(settings: Settings | None = None) -> bool:
    cfg = settings or get_settings()
    return bool(cfg.auth_enabled and cfg.auth_password)


def is_public_path(path: str) -> bool:
    if path == "/favicon.ico":
        return True
    for prefix in PUBLIC_PATH_PREFIXES:
        if path == prefix.rstrip("/") or path.startswith(prefix):
            return True
    return False


def is_fragment_path(path: str) -> bool:
    return any(path == p or path.startswith(p) for p in _FRAGMENT_PREFIXES)


def safe_next_url(raw: str | None, *, default: str = "/clients") -> str:
    """Разрешить только внутренние page-URL после логина."""
    text = (raw or "").strip() or default
    if not text.startswith("/") or text.startswith("//"):
        return default
    parsed = urlparse(text)
    path = parsed.path or "/"
    if is_public_path(path) or is_fragment_path(path):
        return default
    if parsed.query:
        return f"{path}?{parsed.query}"
    return path


def verify_credentials(settings: Settings, username: str, password: str) -> bool:
    expected_user = (settings.auth_username or "admin").strip()
    expected_pass = settings.auth_password or ""
    if not expected_pass:
        return False
    user_ok = secrets.compare_digest(username.strip(), expected_user)
    pass_ok = secrets.compare_digest(password, expected_pass)
    return user_ok and pass_ok


def current_user(request: Request) -> str | None:
    try:
        user = request.session.get(SESSION_USER_KEY)
    except AssertionError:
        return None
    if user and str(user).strip():
        return str(user).strip()
    return None


def login_user(request: Request, username: str) -> None:
    request.session[SESSION_USER_KEY] = username.strip()
    logger.info("AUTH login ok user=%s", username.strip())


def logout_user(request: Request) -> None:
    user = current_user(request)
    request.session.clear()
    logger.info("AUTH logout user=%s", user or "-")


class AuthMiddleware(BaseHTTPMiddleware):
    def __init__(self, app: Any, **kwargs: Any) -> None:
        super().__init__(app)

    async def dispatch(self, request: Request, call_next) -> Response:
        settings = get_settings()
        if not auth_required(settings):
            return await call_next(request)
        path = request.url.path
        if is_public_path(path):
            return await call_next(request)
        user = current_user(request)
        if user:
            return await call_next(request)
        logger.info("AUTH redirect path=%s", path)

        if request.headers.get("hx-request"):
            # Фрагменты (sidebar и т.п.) — тихий 401 без HX-Redirect, иначе петля.
            if is_fragment_path(path):
                return Response(status_code=401)
            next_url = safe_next_url(path)
            response = Response(status_code=401)
            response.headers["HX-Redirect"] = f"/login?next={quote(next_url, safe='/?=&')}"
            return response

        next_url = safe_next_url(path)
        return RedirectResponse(
            url=f"/login?next={quote(next_url, safe='/?=&')}",
            status_code=303,
        )
