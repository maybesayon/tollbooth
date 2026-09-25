from datetime import UTC, datetime

from tollbooth.auth import hash_password
from tollbooth.domain import Role, User
from tollbooth.repositories.base import UserRepository
from tollbooth.security import new_id


async def create_user(
    users: UserRepository, email: str, name: str, role: Role, password: str
) -> User:
    """Raises DuplicateNameError if the email is taken. Callers validate email and password."""
    now = datetime.now(UTC)
    user = User(id=new_id(), email=email, name=name, role=role, created_at=now, updated_at=now)
    await users.create(user, await hash_password(password))
    return user
