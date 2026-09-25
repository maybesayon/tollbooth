from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, SecretStr

from tollbooth.api.fields import Name, Text
from tollbooth.domain import Provider, ProviderCredential, VirtualKey


class CredentialCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: Name
    provider: Provider
    api_key: SecretStr = Field(min_length=1)


class CredentialOut(BaseModel):
    id: str
    name: str
    provider: Provider
    created_at: datetime

    @classmethod
    def of(cls, credential: ProviderCredential) -> "CredentialOut":
        return cls(
            id=credential.id,
            name=credential.name,
            provider=credential.provider,
            created_at=credential.created_at,
        )


class KeyCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: Name
    team: Name
    credential_id: Text


class KeyOut(BaseModel):
    id: str
    name: str
    team: str
    key_prefix: str
    provider: Provider
    credential_id: Text
    created_at: datetime
    revoked_at: datetime | None

    @classmethod
    def of(cls, key: VirtualKey) -> "KeyOut":
        return cls(
            id=key.id,
            name=key.name,
            team=key.team,
            key_prefix=key.key_prefix,
            provider=key.provider,
            credential_id=key.credential_id,
            created_at=key.created_at,
            revoked_at=key.revoked_at,
        )


class KeyCreated(KeyOut):
    key: str = Field(description="The virtual key. Shown only once; store it now.")
