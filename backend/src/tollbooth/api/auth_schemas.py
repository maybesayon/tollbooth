from datetime import datetime
from typing import Annotated, Self

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, SecretStr, model_validator

from tollbooth.api.fields import Name
from tollbooth.auth import EMAIL_PATTERN, Principal, Via, normalize_email, password_problem
from tollbooth.domain import ApiToken, Role, User

Email = Annotated[
    str,
    Field(max_length=320),
    AfterValidator(normalize_email),
    Field(pattern=EMAIL_PATTERN),
]


def _password(value: SecretStr) -> SecretStr:
    if problem := password_problem(value.get_secret_value()):
        raise ValueError(problem)
    return value


NewPassword = Annotated[SecretStr, AfterValidator(_password)]


class UserOut(BaseModel):
    id: str
    email: str
    name: str
    role: Role
    active: bool
    created_at: datetime
    last_login_at: datetime | None
    disabled_at: datetime | None

    @classmethod
    def of(cls, user: User) -> "UserOut":
        return cls(
            id=user.id,
            email=user.email,
            name=user.name,
            role=user.role,
            active=user.active,
            created_at=user.created_at,
            last_login_at=user.last_login_at,
            disabled_at=user.disabled_at,
        )


class MeOut(BaseModel):
    user: UserOut | None = Field(description="Null when authenticated with the admin token.")
    role: Role
    via: Via

    @classmethod
    def of(cls, principal: Principal) -> "MeOut":
        user = UserOut.of(principal.user) if principal.user else None
        return cls(user=user, role=principal.role, via=principal.via)


class LoginIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    email: Annotated[str, Field(max_length=320), AfterValidator(normalize_email)]
    password: Annotated[SecretStr, Field(max_length=256)]


class SetupStatus(BaseModel):
    needs_setup: bool
    setup_with_admin_token: bool = Field(
        description="Whether the first admin can be created here (TOLLBOOTH_ADMIN_TOKEN is set)."
    )


class SetupIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    admin_token: SecretStr
    email: Email
    name: Name
    password: NewPassword

    @model_validator(mode="after")
    def _not_email(self) -> Self:
        if password_problem(self.password.get_secret_value(), self.email):
            raise ValueError("password must not be the email address")
        return self


class PasswordChange(BaseModel):
    model_config = ConfigDict(extra="forbid")

    current_password: Annotated[SecretStr, Field(max_length=256)]
    new_password: NewPassword


class ApiTokenCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: Name


class ApiTokenOut(BaseModel):
    id: str
    name: str
    prefix: str
    created_at: datetime
    last_used_at: datetime | None

    @classmethod
    def of(cls, token: ApiToken) -> "ApiTokenOut":
        return cls(
            id=token.id,
            name=token.name,
            prefix=token.prefix,
            created_at=token.created_at,
            last_used_at=token.last_used_at,
        )


class ApiTokenCreated(ApiTokenOut):
    token: str = Field(description="Use as `Authorization: Bearer <token>`. Shown only once.")


class UserCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    email: Email
    name: Name
    role: Role
    password: NewPassword | None = Field(
        None, description="Omit to generate a temporary password, returned once."
    )


class UserCreated(UserOut):
    temporary_password: str | None


class UserUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: Name | None = None
    role: Role | None = None
    disabled: bool | None = None


class PasswordReset(BaseModel):
    temporary_password: str
