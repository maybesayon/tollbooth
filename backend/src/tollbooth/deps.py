from typing import Annotated

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from tollbooth.security import tokens_match
from tollbooth.state import AppState


def get_state(request: Request) -> AppState:
    return request.app.state.tollbooth


State = Annotated[AppState, Depends(get_state)]

_bearer = HTTPBearer(auto_error=False)


def require_admin(
    state: State,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
) -> None:
    expected = state.settings.admin_token.get_secret_value()
    if credentials is None or not tokens_match(credentials.credentials, expected):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="invalid or missing admin token",
            headers={"WWW-Authenticate": "Bearer"},
        )
