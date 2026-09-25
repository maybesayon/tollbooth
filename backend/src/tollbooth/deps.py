from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from typing import Annotated

from fastapi import Depends, HTTPException, Request, status

from tollbooth.auth import (
    API_TOKEN_PREFIX,
    CSRF_HEADER,
    SESSION_COOKIE,
    Principal,
    Via,
    token_hash,
)
from tollbooth.domain import Role
from tollbooth.security import tokens_match
from tollbooth.state import AppState

SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})
TOUCH_INTERVAL = timedelta(minutes=5)


def get_state(request: Request) -> AppState:
    return request.app.state.tollbooth


State = Annotated[AppState, Depends(get_state)]


def _unauthorized(detail: str = "authentication required") -> HTTPException:
    return HTTPException(
        status.HTTP_401_UNAUTHORIZED, detail, headers={"WWW-Authenticate": "Bearer"}
    )


async def current_principal(request: Request, state: State) -> Principal:
    """Bearer credentials (admin token or a user's API token) or the dashboard session cookie.

    Cookie-authenticated requests that change state must carry the CSRF header; browsers only
    send it from our own pages (it forces a CORS preflight, which Tollbooth never grants).
    """
    authorization = request.headers.get("authorization")
    if authorization is not None:
        scheme, _, token = authorization.partition(" ")
        if scheme.lower() != "bearer" or not token.strip():
            raise _unauthorized()
        return await _bearer_principal(token.strip(), state)

    cookie = request.cookies.get(SESSION_COOKIE)
    if cookie is None:
        raise _unauthorized()
    principal = await _session_principal(cookie, state)
    if request.method not in SAFE_METHODS and request.headers.get(CSRF_HEADER) != "1":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "missing CSRF header")
    return principal


async def _bearer_principal(token: str, state: AppState) -> Principal:
    admin_token = state.settings.admin_token
    if admin_token is not None and tokens_match(token, admin_token.get_secret_value()):
        return Principal(role=Role.ADMIN, via=Via.ADMIN_TOKEN)
    if token.startswith(API_TOKEN_PREFIX):
        found = await state.api_tokens.lookup(token_hash(token))
        if found is not None and found[1].active:
            api_token, user = found
            now = datetime.now(UTC)
            if api_token.last_used_at is None or now - api_token.last_used_at > TOUCH_INTERVAL:
                await state.api_tokens.touch(api_token.id, now)
            return Principal(role=user.role, via=Via.API_TOKEN, user=user)
    raise _unauthorized("invalid token")


async def _session_principal(cookie: str, state: AppState) -> Principal:
    session_hash = token_hash(cookie)
    now = datetime.now(UTC)
    found = await state.sessions.lookup(session_hash, now)
    if found is None or not found[0].active:
        raise _unauthorized("session expired")
    user, last_seen = found
    if now - last_seen > TOUCH_INTERVAL:
        await state.sessions.touch(session_hash, now)
    return Principal(role=user.role, via=Via.SESSION, user=user, session_hash=session_hash)


CurrentPrincipal = Annotated[Principal, Depends(current_principal)]


def require(role: Role) -> Callable[[Principal], Awaitable[Principal]]:
    async def dependency(principal: CurrentPrincipal) -> Principal:
        if not principal.role.includes(role):
            raise HTTPException(status.HTTP_403_FORBIDDEN, f"requires the {role.value} role")
        return principal

    return dependency


require_viewer = require(Role.VIEWER)
require_editor = require(Role.EDITOR)
require_admin = require(Role.ADMIN)

Viewer = Annotated[Principal, Depends(require_viewer)]
Editor = Annotated[Principal, Depends(require_editor)]
Admin = Annotated[Principal, Depends(require_admin)]
