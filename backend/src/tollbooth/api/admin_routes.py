from fastapi import APIRouter, Depends, HTTPException, status

from tollbooth.api.schemas import (
    CredentialCreate,
    CredentialOut,
    KeyCreate,
    KeyCreated,
    KeyOut,
)
from tollbooth.deps import State, require_admin
from tollbooth.repositories.base import DuplicateNameError
from tollbooth.security import generate_virtual_key

router = APIRouter(prefix="/admin", tags=["admin"], dependencies=[Depends(require_admin)])


@router.post("/credentials", status_code=status.HTTP_201_CREATED)
async def create_credential(body: CredentialCreate, state: State) -> CredentialOut:
    encrypted = state.secret_box.encrypt(body.api_key.get_secret_value())
    try:
        credential = await state.credentials.create(body.name, body.provider, encrypted)
    except DuplicateNameError as e:
        raise HTTPException(status.HTTP_409_CONFLICT, "credential name already exists") from e
    return CredentialOut.of(credential)


@router.get("/credentials")
async def list_credentials(state: State) -> list[CredentialOut]:
    return [CredentialOut.of(c) for c in await state.credentials.list_all()]


@router.post("/keys", status_code=status.HTTP_201_CREATED)
async def create_key(body: KeyCreate, state: State) -> KeyCreated:
    if await state.credentials.get(body.credential_id) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "credential not found")
    new_key = generate_virtual_key()
    key = await state.keys.create(
        name=body.name,
        team=body.team,
        key_hash=new_key.key_hash,
        key_prefix=new_key.display_prefix,
        credential_id=body.credential_id,
    )
    return KeyCreated(**KeyOut.of(key).model_dump(), key=new_key.plaintext)


@router.get("/keys")
async def list_keys(
    state: State, team: str | None = None, include_revoked: bool = False
) -> list[KeyOut]:
    keys = await state.keys.list_all(team=team, include_revoked=include_revoked)
    return [KeyOut.of(k) for k in keys]


@router.get("/keys/{key_id}")
async def get_key(key_id: str, state: State) -> KeyOut:
    key = await state.keys.get(key_id)
    if key is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "key not found")
    return KeyOut.of(key)


@router.post("/keys/{key_id}/revoke")
async def revoke_key(key_id: str, state: State) -> KeyOut:
    key = await state.keys.revoke(key_id)
    if key is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "key not found")
    return KeyOut.of(key)
