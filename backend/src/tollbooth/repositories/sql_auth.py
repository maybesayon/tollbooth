from datetime import datetime
from typing import Any

from sqlalchemy import Row, delete, func, insert, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncEngine

from tollbooth.db import api_tokens, sessions, users
from tollbooth.domain import ApiToken, Role, User
from tollbooth.repositories.base import DuplicateNameError

_USER_COLUMNS = [c for c in users.c if c.name != "password_hash"]


class SqlUserRepository:
    def __init__(self, engine: AsyncEngine) -> None:
        self._engine = engine

    async def create(self, user: User, password_hash: str) -> None:
        try:
            async with self._engine.begin() as conn:
                await conn.execute(
                    insert(users).values(**_user_values(user), password_hash=password_hash)
                )
        except IntegrityError as e:
            raise DuplicateNameError(f"a user with email {user.email} already exists") from e

    async def get(self, user_id: str) -> User | None:
        async with self._engine.connect() as conn:
            row = (await conn.execute(select(*_USER_COLUMNS).where(users.c.id == user_id))).first()
        return _to_user(row) if row else None

    async def get_with_password(self, email: str) -> tuple[User, str] | None:
        async with self._engine.connect() as conn:
            row = (
                await conn.execute(
                    select(*_USER_COLUMNS, users.c.password_hash).where(users.c.email == email)
                )
            ).first()
        return (_to_user(row), row.password_hash) if row else None

    async def get_password_hash(self, user_id: str) -> str | None:
        async with self._engine.connect() as conn:
            return (
                await conn.execute(select(users.c.password_hash).where(users.c.id == user_id))
            ).scalar_one_or_none()

    async def list_all(self) -> list[User]:
        async with self._engine.connect() as conn:
            rows = await conn.execute(select(*_USER_COLUMNS).order_by(users.c.created_at))
        return [_to_user(r) for r in rows]

    async def count(self) -> int:
        async with self._engine.connect() as conn:
            return int((await conn.execute(select(func.count()).select_from(users))).scalar_one())

    async def count_active_admins(self) -> int:
        query = (
            select(func.count())
            .select_from(users)
            .where(users.c.role == Role.ADMIN.value, users.c.disabled_at.is_(None))
        )
        async with self._engine.connect() as conn:
            return int((await conn.execute(query)).scalar_one())

    async def update(self, user: User) -> bool:
        async with self._engine.begin() as conn:
            result = await conn.execute(
                update(users)
                .where(users.c.id == user.id)
                .values(
                    name=user.name,
                    role=user.role.value,
                    disabled_at=user.disabled_at,
                    updated_at=user.updated_at,
                )
            )
        return result.rowcount > 0

    async def set_password(self, user_id: str, password_hash: str, now: datetime) -> None:
        async with self._engine.begin() as conn:
            await conn.execute(
                update(users)
                .where(users.c.id == user_id)
                .values(password_hash=password_hash, updated_at=now)
            )

    async def record_login(self, user_id: str, now: datetime) -> None:
        async with self._engine.begin() as conn:
            await conn.execute(update(users).where(users.c.id == user_id).values(last_login_at=now))


class SqlSessionRepository:
    def __init__(self, engine: AsyncEngine) -> None:
        self._engine = engine

    async def create(
        self, session_hash: str, user_id: str, now: datetime, expires_at: datetime
    ) -> None:
        async with self._engine.begin() as conn:
            await conn.execute(
                insert(sessions).values(
                    id=session_hash,
                    user_id=user_id,
                    created_at=now,
                    expires_at=expires_at,
                    last_seen_at=now,
                )
            )

    async def lookup(self, session_hash: str, now: datetime) -> tuple[User, datetime] | None:
        query = (
            select(*_USER_COLUMNS, sessions.c.last_seen_at)
            .join(users, users.c.id == sessions.c.user_id)
            .where(sessions.c.id == session_hash, sessions.c.expires_at > now)
        )
        async with self._engine.connect() as conn:
            row = (await conn.execute(query)).first()
        return (_to_user(row), row.last_seen_at) if row else None

    async def touch(self, session_hash: str, now: datetime) -> None:
        async with self._engine.begin() as conn:
            await conn.execute(
                update(sessions).where(sessions.c.id == session_hash).values(last_seen_at=now)
            )

    async def delete(self, session_hash: str) -> None:
        async with self._engine.begin() as conn:
            await conn.execute(delete(sessions).where(sessions.c.id == session_hash))

    async def delete_for_user(self, user_id: str, keep: str | None = None) -> None:
        query = delete(sessions).where(sessions.c.user_id == user_id)
        if keep is not None:
            query = query.where(sessions.c.id != keep)
        async with self._engine.begin() as conn:
            await conn.execute(query)

    async def delete_expired(self, now: datetime) -> None:
        async with self._engine.begin() as conn:
            await conn.execute(delete(sessions).where(sessions.c.expires_at <= now))


class SqlApiTokenRepository:
    def __init__(self, engine: AsyncEngine) -> None:
        self._engine = engine

    async def create(self, token: ApiToken, token_hash: str) -> None:
        async with self._engine.begin() as conn:
            await conn.execute(
                insert(api_tokens).values(
                    id=token.id,
                    user_id=token.user_id,
                    name=token.name,
                    token_hash=token_hash,
                    prefix=token.prefix,
                    created_at=token.created_at,
                    last_used_at=token.last_used_at,
                )
            )

    async def lookup(self, token_hash: str) -> tuple[ApiToken, User] | None:
        t = api_tokens.c
        query = (
            select(
                *_USER_COLUMNS,
                t.id.label("token_id"),
                t.name.label("token_name"),
                t.prefix,
                t.created_at.label("token_created_at"),
                t.last_used_at,
            )
            .join(users, users.c.id == t.user_id)
            .where(t.token_hash == token_hash)
        )
        async with self._engine.connect() as conn:
            row = (await conn.execute(query)).first()
        if row is None:
            return None
        token = ApiToken(
            id=row.token_id,
            user_id=row.id,
            name=row.token_name,
            prefix=row.prefix,
            created_at=row.token_created_at,
            last_used_at=row.last_used_at,
        )
        return token, _to_user(row)

    async def list_for_user(self, user_id: str) -> list[ApiToken]:
        t = api_tokens.c
        query = (
            select(t.id, t.user_id, t.name, t.prefix, t.created_at, t.last_used_at)
            .where(t.user_id == user_id)
            .order_by(t.created_at)
        )
        async with self._engine.connect() as conn:
            rows = await conn.execute(query)
        return [ApiToken(**dict(r._mapping)) for r in rows]

    async def delete(self, user_id: str, token_id: str) -> bool:
        async with self._engine.begin() as conn:
            result = await conn.execute(
                delete(api_tokens).where(
                    api_tokens.c.id == token_id, api_tokens.c.user_id == user_id
                )
            )
        return result.rowcount > 0

    async def touch(self, token_id: str, now: datetime) -> None:
        async with self._engine.begin() as conn:
            await conn.execute(
                update(api_tokens).where(api_tokens.c.id == token_id).values(last_used_at=now)
            )


def _user_values(user: User) -> dict[str, Any]:
    return {
        "id": user.id,
        "email": user.email,
        "name": user.name,
        "role": user.role.value,
        "created_at": user.created_at,
        "updated_at": user.updated_at,
        "disabled_at": user.disabled_at,
        "last_login_at": user.last_login_at,
    }


def _to_user(row: Row[Any]) -> User:
    m = row._mapping
    return User(
        id=m["id"],
        email=m["email"],
        name=m["name"],
        role=Role(m["role"]),
        created_at=m["created_at"],
        updated_at=m["updated_at"],
        disabled_at=m["disabled_at"],
        last_login_at=m["last_login_at"],
    )
