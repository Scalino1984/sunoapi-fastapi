from __future__ import annotations

import json
import time
import uuid
from collections.abc import Awaitable, Callable, MutableMapping
from typing import Any

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware

from app.config import get_settings
from app.database import SessionLocal
from app.services.action_status_fallback_service import (
    create_action_status_fallback,
    has_action_status_since,
    should_track_api_action,
    snapshot_action_status_marker,
)


class RequestContextMiddleware(BaseHTTPMiddleware):
    """Produktionsnahe Request-Kontext- und Security-Header-Middleware."""

    async def dispatch(self, request: Request, call_next: Callable[[Request], Awaitable[Response]]) -> Response:
        settings = get_settings()
        request_id = request.headers.get("x-request-id") or uuid.uuid4().hex
        start_time = time.perf_counter()
        request.state.request_id = request_id

        response = await call_next(request)

        duration_ms = int((time.perf_counter() - start_time) * 1000)
        response.headers["X-Request-ID"] = request_id
        response.headers["X-Process-Time-ms"] = str(duration_ms)

        if settings.security_headers_enabled:
            response.headers.setdefault("X-Content-Type-Options", "nosniff")
            response.headers.setdefault("X-Frame-Options", settings.security_frame_options)
            response.headers.setdefault("Referrer-Policy", settings.security_referrer_policy)
            response.headers.setdefault("Permissions-Policy", settings.security_permissions_policy)
            if settings.security_csp:
                response.headers.setdefault("Content-Security-Policy", settings.security_csp)

        return response


class ActionStatusFallbackMiddleware:
    """Legt Fallback-Statusmeldungen fuer erfolgreiche schreibende API-Aktionen an.

    Wichtig fuer kuenftige Aenderungen: Diese Middleware ersetzt keine fachlichen
    Statusprozesse. Wenn ein Endpoint bereits einen SunoTask oder eine
    StatusNotification erzeugt, passiert hier nichts. Nur "stumme" erfolgreiche
    Schreibaktionen bekommen eine generische, verlinkbare Meldung fuer /status.
    """

    def __init__(self, app: Callable[..., Awaitable[None]]) -> None:
        self.app = app

    async def __call__(self, scope: MutableMapping[str, Any], receive: Callable[[], Awaitable[dict]], send: Callable[[dict], Awaitable[None]]) -> None:
        if scope.get("type") != "http":
            await self.app(scope, receive, send)
            return

        method = str(scope.get("method") or "")
        path = str(scope.get("path") or "")
        track_action = should_track_api_action(method, path)
        if not track_action:
            await self.app(scope, receive, send)
            return

        marker = None
        db = SessionLocal()
        try:
            marker = snapshot_action_status_marker(db)
        finally:
            db.close()

        status_code = 500
        content_type = ""
        response_body = bytearray()
        capture_json_body = False

        async def send_wrapper(message: dict) -> None:
            nonlocal status_code, content_type, capture_json_body
            if message.get("type") == "http.response.start":
                status_code = int(message.get("status") or 500)
                headers = message.get("headers") or []
                for raw_key, raw_value in headers:
                    if raw_key.lower() == b"content-type":
                        content_type = raw_value.decode("latin1")
                        break
                capture_json_body = track_action and status_code < 400 and "application/json" in content_type.lower()
            elif message.get("type") == "http.response.body" and capture_json_body:
                body = message.get("body") or b""
                if body and len(response_body) < 262_144:
                    response_body.extend(body[: max(0, 262_144 - len(response_body))])
            await send(message)

        await self.app(scope, receive, send_wrapper)

        response_payload = None
        if capture_json_body and response_body:
            try:
                response_payload = json.loads(bytes(response_body).decode("utf-8"))
            except Exception:
                response_payload = None

        if track_action and status_code < 400:
            db = SessionLocal()
            try:
                if not has_action_status_since(db, marker):
                    create_action_status_fallback(
                        db,
                        method=method,
                        path=path,
                        status_code=status_code,
                        response_payload=response_payload,
                        path_params=scope.get("path_params") or {},
                    )
            finally:
                db.close()
