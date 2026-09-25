from dataclasses import replace
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, status

from tollbooth.accounts import create_user
from tollbooth.api.auth_schemas import (
    PasswordReset,
    UserCreate,
    UserCreated,
    UserOut,
    UserUpdate,
)
from tollbooth.auth import hash_password, new_temporary_password
from tollbooth.deps import Admin, State, require_admin
from tollbooth.domain import Role, User
from tollbooth.repositories.base import DuplicateNameError

router = APIRouter(prefix="/admin/users", tags=["users"], dependencies=[Depends(require_admin)])


@router.get("")
async def list_users(state: State) -> list[UserOut]:
    return [UserOut.of(u) for u in await state.users.list_all()]


@router.post("", status_code=status.HTTP_201_CREATED)
async def add_user(body: UserCreate, state: State, principal: Admin) -> UserCreated:
    temporary = None if body.password else new_temporary_password()
    password = body.password.get_secret_value() if body.password else temporary
    assert password is not None
    try:
        user = await create_user(state.users, body.email, body.name, body.role, password)
    except DuplicateNameError as e:
        raise HTTPException(status.HTTP_409_CONFLICT, "a user with that email exists") from e
    return UserCreated(**UserOut.of(user).model_dump(), temporary_password=temporary)


@router.patch("/{user_id}")
async def update_user(user_id: str, body: UserUpdate, state: State, principal: Admin) -> UserOut:
    user = await _existing(user_id, state)
    now = datetime.now(UTC)
    disabled_at = user.disabled_at
    if body.disabled is True and disabled_at is None:
        disabled_at = now
    elif body.disabled is False:
        disabled_at = None
    updated = replace(
        user,
        name=body.name or user.name,
        role=body.role or user.role,
        disabled_at=disabled_at,
        updated_at=now,
    )
    loses_admin = (
        user.role is Role.ADMIN
        and user.active
        and not (updated.role is Role.ADMIN and updated.active)
    )
    if loses_admin:
        if principal.user is not None and principal.user.id == user.id:
            raise HTTPException(
                status.HTTP_409_CONFLICT, "you cannot demote or disable your own account"
            )
        if await state.users.count_active_admins() <= 1:
            raise HTTPException(status.HTTP_409_CONFLICT, "at least one active admin must remain")
    await state.users.update(updated)
    if not updated.active:
        await state.sessions.delete_for_user(user.id)
    return UserOut.of(updated)


@router.post("/{user_id}/reset-password")
async def reset_password(user_id: str, state: State, principal: Admin) -> PasswordReset:
    user = await _existing(user_id, state)
    temporary = new_temporary_password()
    await state.users.set_password(user.id, await hash_password(temporary), datetime.now(UTC))
    await state.sessions.delete_for_user(user.id)
    return PasswordReset(temporary_password=temporary)


async def _existing(user_id: str, state: State) -> User:
    user = await state.users.get(user_id)
    if user is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "user not found")
    return user
