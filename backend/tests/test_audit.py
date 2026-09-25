import json

import httpx
import pytest
from conftest import MakeKey
from fake_webhooks import WebhookReceiver

from tollbooth.accounts import create_user
from tollbooth.auth import CSRF_HEADER
from tollbooth.domain import Provider, Role
from tollbooth.state import AppState

PASSWORD = "correct horse battery"
CSRF = {CSRF_HEADER: "1"}
CHANNEL_URL = "https://hooks.example.com/services/very-secret-path"


async def _events(client: httpx.AsyncClient, headers: dict[str, str], **params: str) -> list[dict]:
    response = await client.get("/admin/audit", params=params, headers=headers)
    assert response.status_code == 200, response.text
    return response.json()


async def test_admin_actions_are_recorded_without_secrets(
    client: httpx.AsyncClient,
    admin_headers: dict[str, str],
    state: AppState,
    webhooks: WebhookReceiver,
) -> None:
    await create_user(state.users, "ed@example.com", "Ed", Role.EDITOR, PASSWORD)
    cred = await client.post(
        "/admin/credentials",
        json={"name": "openai", "provider": "openai", "api_key": "sk-live-SECRET-KEY"},
        headers=admin_headers,
    )
    user = await client.post(
        "/admin/users",
        json={"email": "vi@example.com", "name": "Vi", "role": "viewer"},
        headers=admin_headers,
    )
    temporary = user.json()["temporary_password"]
    await client.patch(
        f"/admin/users/{user.json()['id']}", json={"role": "editor"}, headers=admin_headers
    )
    reset = await client.post(
        f"/admin/users/{user.json()['id']}/reset-password", headers=admin_headers
    )

    assert (
        await client.post(
            "/auth/login", json={"email": "ed@example.com", "password": "nope nope nope"}
        )
    ).status_code == 401
    assert (
        await client.post("/auth/login", json={"email": "ed@example.com", "password": PASSWORD})
    ).status_code == 200
    key = await client.post(
        "/admin/keys",
        json={"name": "svc", "team": "search", "credential_id": cred.json()["id"]},
        headers=CSRF,
    )
    await client.post(f"/admin/keys/{key.json()['id']}/revoke", headers=CSRF)
    channel = await client.post(
        "/admin/channels",
        json={"name": "hook", "type": "webhook", "url": CHANNEL_URL},
        headers=CSRF,
    )
    await client.post(f"/admin/channels/{channel.json()['id']}/test", headers=CSRF)
    budget = await client.post(
        "/admin/budgets",
        json={
            "name": "search",
            "scope": {"type": "team", "value": "search"},
            "period": "month",
            "limit_usd": "100",
        },
        headers=CSRF,
    )
    await client.patch(
        f"/admin/budgets/{budget.json()['id']}",
        json={"limit_usd": "250.5", "enforcement": "hard"},
        headers=CSRF,
    )
    await client.delete(f"/admin/budgets/{budget.json()['id']}", headers=CSRF)
    await client.delete(f"/admin/channels/{channel.json()['id']}", headers=CSRF)
    token = await client.post("/auth/tokens", json={"name": "ci"}, headers=CSRF)
    await client.delete(f"/auth/tokens/{token.json()['id']}", headers=CSRF)
    await client.post(
        "/auth/password",
        json={"current_password": PASSWORD, "new_password": "a brand new password"},
        headers=CSRF,
    )
    await client.post("/auth/logout", headers=CSRF)

    events = list(reversed(await _events(client, admin_headers)))
    assert [(e["action"], e["actor_label"]) for e in events] == [
        ("credential.created", "admin token"),
        ("user.created", "admin token"),
        ("user.updated", "admin token"),
        ("user.password_reset", "admin token"),
        ("auth.login_failed", "ed@example.com"),
        ("auth.login", "ed@example.com"),
        ("key.created", "ed@example.com"),
        ("key.revoked", "ed@example.com"),
        ("channel.created", "ed@example.com"),
        ("channel.tested", "ed@example.com"),
        ("budget.created", "ed@example.com"),
        ("budget.updated", "ed@example.com"),
        ("budget.deleted", "ed@example.com"),
        ("channel.deleted", "ed@example.com"),
        ("api_token.created", "ed@example.com"),
        ("api_token.deleted", "ed@example.com"),
        ("auth.password_changed", "ed@example.com"),
        ("auth.logout", "ed@example.com"),
    ]
    by_action = {e["action"]: e for e in events}
    assert by_action["auth.login_failed"]["actor_type"] == "anonymous"
    assert by_action["auth.login"]["actor_type"] == "session"
    assert by_action["user.updated"]["details"]["changes"] == {
        "role": {"from": "viewer", "to": "editor"}
    }
    assert by_action["budget.updated"]["details"]["changes"] == {
        "limit_usd": {"from": "100", "to": "250.5"},
        "enforcement": {"from": "soft", "to": "hard"},
    }
    assert by_action["key.created"]["target_id"] == key.json()["id"]
    assert by_action["channel.created"]["details"]["url_hint"] == "hooks.example.com"
    assert by_action["user.created"]["details"]["temporary_password"] is True

    stored = json.dumps(events)
    for secret in (
        "sk-live-SECRET-KEY",
        temporary,
        reset.json()["temporary_password"],
        PASSWORD,
        "a brand new password",
        "very-secret-path",
        channel.json()["signing_secret"],
        token.json()["token"],
        key.json()["key"],
        "nope nope nope",
    ):
        assert secret not in stored


async def test_filters_and_paging(
    client: httpx.AsyncClient, admin_headers: dict[str, str], state: AppState
) -> None:
    ed = await create_user(state.users, "ed@example.com", "Ed", Role.EDITOR, PASSWORD)
    for _ in range(3):
        await client.post("/auth/login", json={"email": "ed@example.com", "password": PASSWORD})
    await client.post(
        "/admin/users",
        json={"email": "x@example.com", "name": "X", "role": "viewer"},
        headers=admin_headers,
    )
    logins = await _events(client, admin_headers, action="auth.login")
    assert len(logins) == 3
    assert len(await _events(client, admin_headers, actor_id=ed.id)) == 3

    first = await _events(client, admin_headers, limit="2")
    rest = await _events(client, admin_headers, before=first[-1]["created_at"])
    assert [e["id"] for e in first + rest] == [
        e["id"] for e in await _events(client, admin_headers)
    ]
    naive = await _events(client, admin_headers, before="2000-01-01T00:00:00")
    assert naive == []


async def test_only_admins_read_the_log(client: httpx.AsyncClient, state: AppState) -> None:
    await create_user(state.users, "ed@example.com", "Ed", Role.EDITOR, PASSWORD)
    await client.post("/auth/login", json={"email": "ed@example.com", "password": PASSWORD})
    assert (await client.get("/admin/audit")).status_code == 403


async def test_audit_failures_never_block_the_action(
    client: httpx.AsyncClient,
    admin_headers: dict[str, str],
    make_key: MakeKey,
    state: AppState,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    async def broken(_event: object) -> None:
        raise RuntimeError("audit store down")

    monkeypatch.setattr(state.audit, "record", broken)
    key = await make_key(Provider.OPENAI)
    assert key.startswith("tb_")
    assert "failed to write audit event" in caplog.text
