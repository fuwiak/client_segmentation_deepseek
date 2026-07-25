"""Простая session-auth для CRM (логин / пароль из env)."""

from __future__ import annotations

import logging
import secrets
from typing import Any

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import RedirectResponse, Response

from app.config import Settings, get_settings

logger = logging.getLogger(__name__)

SESSION_USER_KEY = "auth_user"

# Публичные пути без логина
PUBLIC_PATH_PREFIXES = (
    "/static/",
    "/health",
    "/login",
    "/logout",
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
        # SessionMiddleware не подключён
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
        # kwargs игнорируем — settings читаем динамически через get_settings()
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
        next_url = path
        if request.url.query:
            next_url = f"{path}?{request.url.query}"
        if request.headers.get("hx-request"):
            response = Response(status_code=401)
            response.headers["HX-Redirect"] = f"/login?next={next_url}"
            return response
        return RedirectResponse(url=f"/login?next={next_url}", status_code=303)
