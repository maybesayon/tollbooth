import httpx
import pytest

from tollbooth.security import hash_virtual_key
from tollbooth.state import AppState


async def _credential(client: httpx.AsyncClient, headers: dict[str, str], **body: str) -> dict:
    payload = {"name": "openai-prod", "provider": "openai", "api_key": "sk-real-secret"} | body
    response = await client.post("/admin/credentials", json=payload, headers=headers)
    assert response.status_code == 201, response.text
    return response.json()


@pytest.mark.parametrize(
    "headers",
    [{}, {"Authorization": "Bearer wrong"}, {"Authorization": "Basic dGVzdA=="}],
)
async def test_admin_requires_token(client: httpx.AsyncClient, headers: dict[str, str]) -> None:
    response = await client.get("/admin/keys", headers=headers)
    assert response.status_code == 401


async def test_credential_is_encrypted_and_never_returned(
    client: httpx.AsyncClient, admin_headers: dict[str, str], state: AppState
) -> None:
    created = await _credential(client, admin_headers)
    assert "api_key" not in created
    stored = await state.credentials.get_encrypted_key(created["id"])
    assert stored is not None and "sk-real-secret" not in stored
    assert state.secret_box.decrypt(stored) == "sk-real-secret"

    listed = (await client.get("/admin/credentials", headers=admin_headers)).json()
    assert listed == [created]
    assert "sk-real-secret" not in str(listed)


async def test_duplicate_credential_name(
    client: httpx.AsyncClient, admin_headers: dict[str, str]
) -> None:
    await _credential(client, admin_headers)
    response = await client.post(
        "/admin/credentials",
        json={"name": "openai-prod", "provider": "openai", "api_key": "x"},
        headers=admin_headers,
    )
    assert response.status_code == 409


@pytest.mark.parametrize(
    "body",
    [
        {"name": "x", "provider": "gemini", "api_key": "k"},
        {"name": " ", "provider": "openai", "api_key": "k"},
        {"name": "x", "provider": "openai", "api_key": ""},
        {"name": "x", "provider": "openai", "api_key": "k", "extra": 1},
    ],
)
async def test_credential_validation(
    client: httpx.AsyncClient, admin_headers: dict[str, str], body: dict
) -> None:
    response = await client.post("/admin/credentials", json=body, headers=admin_headers)
    assert response.status_code == 422


async def test_key_lifecycle(
    client: httpx.AsyncClient, admin_headers: dict[str, str], state: AppState
) -> None:
    cred = await _credential(client, admin_headers, provider="anthropic", name="anthropic")
    response = await client.post(
        "/admin/keys",
        json={"name": "search-svc", "team": "search", "credential_id": cred["id"]},
        headers=admin_headers,
    )
    assert response.status_code == 201, response.text
    created = response.json()
    plaintext = created.pop("key")
    assert plaintext.startswith(created["key_prefix"])
    assert created["provider"] == "anthropic"
    assert created["revoked_at"] is None

    stored = await state.keys.get_by_hash(hash_virtual_key(plaintext))
    assert stored is not None and stored.id == created["id"]

    fetched = (await client.get(f"/admin/keys/{created['id']}", headers=admin_headers)).json()
    assert fetched == created
    assert "key" not in fetched

    listed = (await client.get("/admin/keys?team=search", headers=admin_headers)).json()
    assert [k["id"] for k in listed] == [created["id"]]
    assert (await client.get("/admin/keys?team=ads", headers=admin_headers)).json() == []

    revoked = await client.post(f"/admin/keys/{created['id']}/revoke", headers=admin_headers)
    assert revoked.status_code == 200
    assert revoked.json()["revoked_at"] is not None
    assert (await client.get("/admin/keys", headers=admin_headers)).json() == []
    with_revoked = await client.get("/admin/keys?include_revoked=true", headers=admin_headers)
    assert len(with_revoked.json()) == 1


async def test_key_requires_existing_credential(
    client: httpx.AsyncClient, admin_headers: dict[str, str]
) -> None:
    response = await client.post(
        "/admin/keys",
        json={"name": "n", "team": "t", "credential_id": "missing"},
        headers=admin_headers,
    )
    assert response.status_code == 404


async def test_unknown_key_is_404(client: httpx.AsyncClient, admin_headers: dict[str, str]) -> None:
    assert (await client.get("/admin/keys/nope", headers=admin_headers)).status_code == 404
    assert (await client.post("/admin/keys/nope/revoke", headers=admin_headers)).status_code == 404
