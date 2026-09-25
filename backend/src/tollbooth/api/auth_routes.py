from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, HTTPException, Request, Response, status

from tollbooth.accounts import create_user
from tollbooth.api.auth_schemas import (
    ApiTokenCreate,
    ApiTokenCreated,
    ApiTokenOut,
    LoginIn,
    MeOut,
    PasswordChange,
    SetupIn,
    SetupStatus,
)
from tollbooth.auth import (
    SESSION_COOKIE,
    Principal,
    Via,
    hash_password,
    new_api_token,
    new_session_token,
    token_hash,
    verify_password,
)
from tollbooth.deps import CurrentPrincipal, State
from tollbooth.domain import ApiToken, Role, User
from tollbooth.security import new_id, tokens_match

router = APIRouter(prefix="/auth", tags=["auth"])

INVALID_LOGIN = "invalid email or password"


@router.get("/setup")
async def setup_status(state: State) -> SetupStatus:
    return SetupStatus(
        needs_setup=await state.users.count() == 0,
        setup_with_admin_token=state.settings.admin_token is not None,
    )


@router.post("/setup", status_code=status.HTTP_201_CREATED)
async def setup(body: SetupIn, request: Request, response: Response, state: State) -> MeOut:
    """Create the first admin account; requires the admin token and an empty user table."""
    admin_token = state.settings.admin_token
    if admin_token is None:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "set TOLLBOOTH_ADMIN_TOKEN or use `tollbooth create-user` to create the first admin",
        )
    if not tokens_match(body.admin_token.get_secret_value(), admin_token.get_secret_value()):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "wrong admin token")
    if await state.users.count() > 0:
        raise HTTPException(status.HTTP_409_CONFLICT, "setup is already complete")
    user = await create_user(
        state.users, body.email, body.name, Role.ADMIN, body.password.get_secret_value()
    )
    return await _start_session(user, request, response, state)


@router.post("/login")
async def login(body: LoginIn, request: Request, response: Response, state: State) -> MeOut:
    address = request.client.host if request.client else "unknown"
    throttle = state.login_throttle
    if wait := throttle.retry_after(body.email, address):
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS,
            "too many failed sign-in attempts; try again later",
            headers={"Retry-After": str(wait)},
        )
    found = await state.users.get_with_password(body.email)
    user, password_hash = found if found else (None, None)
    valid = await verify_password(password_hash, body.password.get_secret_value())
    if user is None or not valid or not user.active:
        throttle.failed(body.email, address)
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, INVALID_LOGIN)
    throttle.succeeded(body.email)
    return await _start_session(user, request, response, state)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(principal: CurrentPrincipal, request: Request, state: State) -> Response:
    if principal.session_hash is not None:
        await state.sessions.delete(principal.session_hash)
    response = Response(status_code=status.HTTP_204_NO_CONTENT)
    response.delete_cookie(SESSION_COOKIE, path="/", samesite="strict", httponly=True)
    return response


@router.get("/me")
async def me(principal: CurrentPrincipal) -> MeOut:
    return MeOut.of(principal)


@router.post("/password", status_code=status.HTTP_204_NO_CONTENT)
async def change_password(
    body: PasswordChange, principal: CurrentPrincipal, state: State
) -> Response:
    user = _user_of(principal)
    current_hash = await state.users.get_password_hash(user.id)
    if not await verify_password(current_hash, body.current_password.get_secret_value()):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "current password is wrong")
    new_password = body.new_password.get_secret_value()
    if new_password.strip().lower() == user.email:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "password must not be the email")
    await state.users.set_password(user.id, await hash_password(new_password), datetime.now(UTC))
    await state.sessions.delete_for_user(user.id, keep=principal.session_hash)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/tokens")
async def list_tokens(principal: CurrentPrincipal, state: State) -> list[ApiTokenOut]:
    user = _user_of(principal)
    return [ApiTokenOut.of(t) for t in await state.api_tokens.list_for_user(user.id)]


@router.post("/tokens", status_code=status.HTTP_201_CREATED)
async def create_token(
    body: ApiTokenCreate, principal: CurrentPrincipal, state: State
) -> ApiTokenCreated:
    user = _user_of(principal)
    plaintext = new_api_token()
    token = ApiToken(
        id=new_id(),
        user_id=user.id,
        name=body.name,
        prefix=plaintext[:12],
        created_at=datetime.now(UTC),
    )
    await state.api_tokens.create(token, token_hash(plaintext))
    return ApiTokenCreated(**ApiTokenOut.of(token).model_dump(), token=plaintext)


@router.delete("/tokens/{token_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_token(token_id: str, principal: CurrentPrincipal, state: State) -> Response:
    user = _user_of(principal)
    if not await state.api_tokens.delete(user.id, token_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "token not found")
    return Response(status_code=status.HTTP_204_NO_CONTENT)


def _user_of(principal: Principal) -> User:
    if principal.user is None:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "the admin token has no account; sign in as a user"
        )
    return principal.user


async def _start_session(user: User, request: Request, response: Response, state: State) -> MeOut:
    now = datetime.now(UTC)
    ttl = timedelta(hours=state.settings.session_ttl_hours)
    token = new_session_token()
    await state.sessions.delete_expired(now)
    await state.sessions.create(token_hash(token), user.id, now, now + ttl)
    await state.users.record_login(user.id, now)
    secure = state.settings.cookie_secure
    response.set_cookie(
        SESSION_COOKIE,
        token,
        max_age=int(ttl.total_seconds()),
        path="/",
        httponly=True,
        samesite="strict",
        secure=request.url.scheme == "https" if secure is None else secure,
    )
    return MeOut.of(Principal(role=user.role, via=Via.SESSION, user=user))
