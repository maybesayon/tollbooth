import asyncio
import io
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import pytest
from conftest import ADMIN_TOKEN, persisted_bytes
from fastapi import FastAPI

from tollbooth.accounts import create_user
from tollbooth.auth import CSRF_HEADER, SESSION_COOKIE, token_hash
from tollbooth.cli import main
from tollbooth.db import create_engine
from tollbooth.domain import Role
from tollbooth.main import create_app
from tollbooth.repositories.sql_auth import SqlUserRepository
from tollbooth.settings import Settings
from tollbooth.state import AppState

PASSWORD = "correct horse battery"
CSRF = {CSRF_HEADER: "1"}


async def _user(state: AppState, email: str, role: Role = Role.VIEWER) -> str:
    user = await create_user(state.users, email, email.split("@")[0], role, PASSWORD)
    return user.id


async def _login(client: httpx.AsyncClient, email: str, password: str = PASSWORD) -> httpx.Response:
    return await client.post("/auth/login", json={"email": email, "password": password})


@pytest.fixture
async def other_client(app: FastAPI) -> httpx.AsyncClient:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://tollbooth") as client:
        yield client


class TestSetup:
    async def test_first_admin_is_created_with_the_admin_token(
        self, client: httpx.AsyncClient
    ) -> None:
        status = (await client.get("/auth/setup")).json()
        assert status == {"needs_setup": True, "setup_with_admin_token": True}

        body = {
            "admin_token": "wrong",
            "email": "Ada@Example.com",
            "name": "Ada",
            "password": PASSWORD,
        }
        assert (await client.post("/auth/setup", json=body)).status_code == 403

        created = await client.post("/auth/setup", json=body | {"admin_token": ADMIN_TOKEN})
        assert created.status_code == 201
        assert created.json()["user"]["email"] == "ada@example.com"
        assert created.json()["role"] == "admin"
        me = (await client.get("/auth/me")).json()
        assert (me["via"], me["user"]["name"]) == ("session", "Ada")

        again = await client.post("/auth/setup", json=body | {"admin_token": ADMIN_TOKEN})
        assert again.status_code == 409
        assert (await client.get("/auth/setup")).json()["needs_setup"] is False

    async def test_setup_needs_an_admin_token_configured(self, settings: Settings) -> None:
        app = create_app(settings.model_copy(update={"admin_token": None}))
        async with app.router.lifespan_context(app):
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(transport=transport, base_url="http://t") as client:
                assert (await client.get("/auth/setup")).json()["setup_with_admin_token"] is False
                response = await client.post(
                    "/auth/setup",
                    json={"admin_token": "x", "email": "a@b.co", "name": "A", "password": PASSWORD},
                )
                assert response.status_code == 409
                assert "create-user" in response.json()["detail"]
                assert (
                    await client.get("/admin/keys", headers={"Authorization": "Bearer x"})
                ).status_code == 401

    @pytest.mark.parametrize(
        ("field", "value"),
        [("password", "short"), ("password", "ada@example.com"), ("email", "not-an-email")],
    )
    async def test_setup_validates_input(
        self, client: httpx.AsyncClient, field: str, value: str
    ) -> None:
        body = {"admin_token": ADMIN_TOKEN, "email": "ada@example.com", "name": "Ada"}
        body = body | {"password": PASSWORD} | {field: value}
        assert (await client.post("/auth/setup", json=body)).status_code == 422


class TestLogin:
    async def test_session_cookie_is_http_only_and_strict(
        self, client: httpx.AsyncClient, state: AppState
    ) -> None:
        await _user(state, "vi@example.com")
        response = await _login(client, "  VI@example.com ")
        assert response.status_code == 200
        cookie = response.headers["set-cookie"]
        assert cookie.startswith(f"{SESSION_COOKIE}=tbs_")
        assert "HttpOnly" in cookie
        assert "SameSite=strict" in cookie
        assert "Max-Age=604800" in cookie
        assert "Secure" not in cookie  # plain http in tests; https requests get Secure

    async def test_secure_cookie_can_be_forced(self, settings: Settings, state: AppState) -> None:
        app = create_app(settings.model_copy(update={"cookie_secure": True}))
        async with app.router.lifespan_context(app):
            await _user(app.state.tollbooth, "s@example.com")
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(transport=transport, base_url="http://t") as client:
                assert "Secure" in (await _login(client, "s@example.com")).headers["set-cookie"]

    async def test_failures_are_indistinguishable(
        self, client: httpx.AsyncClient, state: AppState, admin_headers: dict[str, str]
    ) -> None:
        user_id = await _user(state, "vi@example.com")
        await client.patch(
            f"/admin/users/{user_id}", json={"disabled": True}, headers=admin_headers
        )
        wrong = await _login(client, "vi@example.com", "wrong password!!")
        unknown = await _login(client, "nobody@example.com")
        disabled = await _login(client, "vi@example.com")
        for response in (wrong, unknown, disabled):
            assert response.status_code == 401
            assert response.json() == {"detail": "invalid email or password"}
            assert "set-cookie" not in response.headers

    async def test_repeated_failures_are_throttled(
        self, client: httpx.AsyncClient, state: AppState
    ) -> None:
        await _user(state, "vi@example.com")
        for _ in range(5):
            assert (await _login(client, "vi@example.com", "nope nope nope")).status_code == 401
        blocked = await _login(client, "vi@example.com")
        assert blocked.status_code == 429
        assert 0 < int(blocked.headers["retry-after"]) <= 900
        other = await _user(state, "ed@example.com")
        assert other
        assert (await _login(client, "ed@example.com")).status_code == 200


class TestSessions:
    async def test_cookie_requests_need_the_csrf_header_to_change_things(
        self, client: httpx.AsyncClient, state: AppState
    ) -> None:
        await _user(state, "ed@example.com", Role.EDITOR)
        await _login(client, "ed@example.com")
        budget = {
            "name": "b",
            "scope": {"type": "global"},
            "period": "month",
            "limit_usd": 5,
        }
        assert (await client.get("/admin/budgets")).status_code == 200
        forged = await client.post("/admin/budgets", json=budget)
        assert forged.status_code == 403
        assert forged.json()["detail"] == "missing CSRF header"
        assert (await client.post("/admin/budgets", json=budget, headers=CSRF)).status_code == 201

    async def test_logout_ends_the_session(
        self, client: httpx.AsyncClient, state: AppState
    ) -> None:
        await _user(state, "vi@example.com")
        cookie = (await _login(client, "vi@example.com")).cookies[SESSION_COOKIE]
        assert (await client.post("/auth/logout", headers=CSRF)).status_code == 204
        client.cookies.set(SESSION_COOKIE, cookie)
        assert (await client.get("/auth/me")).status_code == 401

    async def test_expired_sessions_are_rejected(
        self, client: httpx.AsyncClient, state: AppState
    ) -> None:
        user_id = await _user(state, "vi@example.com")
        now = datetime.now(UTC)
        await state.sessions.create(token_hash("tbs_old"), user_id, now - timedelta(days=8), now)
        client.cookies.set(SESSION_COOKIE, "tbs_old")
        response = await client.get("/auth/me")
        assert response.status_code == 401
        assert response.json()["detail"] == "session expired"

    async def test_garbage_credentials(self, client: httpx.AsyncClient) -> None:
        client.cookies.set(SESSION_COOKIE, "nonsense")
        assert (await client.get("/auth/me")).status_code == 401
        client.cookies.clear()
        for header in ("Bearer tbu_nope", "Bearer", "Token abc"):
            response = await client.get("/auth/me", headers={"Authorization": header})
            assert response.status_code == 401


ROLE_CASES = [
    ("GET", "/admin/spend", None, Role.VIEWER),
    ("GET", "/admin/requests", None, Role.VIEWER),
    ("GET", "/admin/keys", None, Role.VIEWER),
    ("GET", "/admin/budgets", None, Role.VIEWER),
    ("GET", "/admin/channels", None, Role.VIEWER),
    ("POST", "/admin/keys", {"name": "k", "team": "t", "credential_id": "none"}, Role.EDITOR),
    ("POST", "/admin/keys/none/revoke", None, Role.EDITOR),
    (
        "POST",
        "/admin/budgets",
        {"name": "b", "scope": {"type": "global"}, "period": "day", "limit_usd": 1},
        Role.EDITOR,
    ),
    ("DELETE", "/admin/budgets/none", None, Role.EDITOR),
    (
        "POST",
        "/admin/channels",
        {"name": "c", "type": "slack", "url": "https://x.y/z"},
        Role.EDITOR,
    ),
    ("POST", "/admin/channels/none/test", None, Role.EDITOR),
    (
        "POST",
        "/admin/credentials",
        {"name": "c", "provider": "openai", "api_key": "sk"},
        Role.ADMIN,
    ),
    ("GET", "/admin/users", None, Role.ADMIN),
    ("POST", "/admin/users/none/reset-password", None, Role.ADMIN),
]


@pytest.mark.parametrize("role", list(Role))
async def test_role_permissions(client: httpx.AsyncClient, state: AppState, role: Role) -> None:
    await _user(state, "u@example.com", role)
    await _login(client, "u@example.com")
    for method, path, body, needed in ROLE_CASES:
        response = await client.request(method, path, json=body, headers=CSRF)
        if role.includes(needed):
            assert response.status_code != 403, (role, method, path, response.text)
        else:
            assert response.status_code == 403, (role, method, path)
            assert response.json()["detail"] == f"requires the {needed.value} role"


class TestApiTokens:
    async def test_lifecycle(
        self, client: httpx.AsyncClient, other_client: httpx.AsyncClient, state: AppState
    ) -> None:
        await _user(state, "vi@example.com")
        await _login(client, "vi@example.com")
        created = await client.post("/auth/tokens", json={"name": "ci"}, headers=CSRF)
        assert created.status_code == 201
        token = created.json()["token"]
        assert token.startswith("tbu_")
        assert token.startswith(created.json()["prefix"])

        bearer = {"Authorization": f"Bearer {token}"}
        me = (await other_client.get("/auth/me", headers=bearer)).json()
        assert (me["via"], me["role"]) == ("api_token", "viewer")
        assert (await other_client.get("/admin/spend", headers=bearer)).status_code == 200
        forbidden = await other_client.post(
            "/admin/keys", json={"name": "k", "team": "t", "credential_id": "c"}, headers=bearer
        )
        assert forbidden.status_code == 403

        listed = (await client.get("/auth/tokens")).json()
        assert [t["name"] for t in listed] == ["ci"]
        assert "token" not in listed[0]
        assert listed[0]["last_used_at"] is not None

        url = f"/auth/tokens/{listed[0]['id']}"
        assert (await client.delete(url, headers=CSRF)).status_code == 204
        assert (await other_client.get("/admin/spend", headers=bearer)).status_code == 401

    async def test_tokens_stop_working_when_the_user_is_disabled(
        self,
        client: httpx.AsyncClient,
        other_client: httpx.AsyncClient,
        state: AppState,
        admin_headers: dict[str, str],
    ) -> None:
        user_id = await _user(state, "vi@example.com")
        await _login(client, "vi@example.com")
        token = (await client.post("/auth/tokens", json={"name": "ci"}, headers=CSRF)).json()
        bearer = {"Authorization": f"Bearer {token['token']}"}
        await other_client.patch(
            f"/admin/users/{user_id}", json={"disabled": True}, headers=admin_headers
        )
        assert (await other_client.get("/admin/spend", headers=bearer)).status_code == 401
        assert (await client.get("/auth/me")).status_code == 401

    async def test_the_admin_token_has_no_account(
        self, client: httpx.AsyncClient, admin_headers: dict[str, str]
    ) -> None:
        me = (await client.get("/auth/me", headers=admin_headers)).json()
        assert me == {"user": None, "role": "admin", "via": "admin_token"}
        response = await client.post("/auth/tokens", json={"name": "x"}, headers=admin_headers)
        assert response.status_code == 400


class TestPasswords:
    async def test_change_password_revokes_other_sessions(
        self, client: httpx.AsyncClient, other_client: httpx.AsyncClient, state: AppState
    ) -> None:
        await _user(state, "vi@example.com")
        await _login(client, "vi@example.com")
        await _login(other_client, "vi@example.com")

        wrong = await client.post(
            "/auth/password",
            json={"current_password": "nope", "new_password": "another good password"},
            headers=CSRF,
        )
        assert wrong.status_code == 400
        short = await client.post(
            "/auth/password",
            json={"current_password": PASSWORD, "new_password": "short"},
            headers=CSRF,
        )
        assert short.status_code == 422

        changed = await client.post(
            "/auth/password",
            json={"current_password": PASSWORD, "new_password": "another good password"},
            headers=CSRF,
        )
        assert changed.status_code == 204
        assert (await client.get("/auth/me")).status_code == 200
        assert (await other_client.get("/auth/me")).status_code == 401
        assert (await _login(other_client, "vi@example.com")).status_code == 401
        assert (
            await _login(other_client, "vi@example.com", "another good password")
        ).status_code == 200


class TestUserManagement:
    async def test_create_with_generated_password(
        self,
        client: httpx.AsyncClient,
        other_client: httpx.AsyncClient,
        admin_headers: dict[str, str],
    ) -> None:
        created = await client.post(
            "/admin/users",
            json={"email": "New@Example.com", "name": "New", "role": "editor"},
            headers=admin_headers,
        )
        assert created.status_code == 201
        body = created.json()
        assert body["email"] == "new@example.com"
        assert len(body["temporary_password"]) >= 16
        assert (
            await _login(other_client, "new@example.com", body["temporary_password"])
        ).status_code == 200

        duplicate = await client.post(
            "/admin/users",
            json={"email": "new@example.com", "name": "Dup", "role": "viewer"},
            headers=admin_headers,
        )
        assert duplicate.status_code == 409

        explicit = await client.post(
            "/admin/users",
            json={"email": "p@example.com", "name": "P", "role": "viewer", "password": PASSWORD},
            headers=admin_headers,
        )
        assert explicit.json()["temporary_password"] is None

    async def test_disable_and_reenable(
        self,
        client: httpx.AsyncClient,
        other_client: httpx.AsyncClient,
        state: AppState,
        admin_headers: dict[str, str],
    ) -> None:
        user_id = await _user(state, "vi@example.com")
        await _login(other_client, "vi@example.com")
        disabled = await client.patch(
            f"/admin/users/{user_id}", json={"disabled": True}, headers=admin_headers
        )
        assert disabled.json()["active"] is False
        assert (await other_client.get("/auth/me")).status_code == 401

        enabled = await client.patch(
            f"/admin/users/{user_id}",
            json={"disabled": False, "role": "editor"},
            headers=admin_headers,
        )
        assert (enabled.json()["active"], enabled.json()["role"]) == (True, "editor")
        assert (await _login(other_client, "vi@example.com")).json()["role"] == "editor"

    async def test_the_last_admin_cannot_be_removed(
        self, client: httpx.AsyncClient, state: AppState, admin_headers: dict[str, str]
    ) -> None:
        admin_id = await _user(state, "admin@example.com", Role.ADMIN)
        for change in ({"role": "viewer"}, {"disabled": True}):
            response = await client.patch(
                f"/admin/users/{admin_id}", json=change, headers=admin_headers
            )
            assert response.status_code == 409
            assert response.json()["detail"] == "at least one active admin must remain"

        second_id = await _user(state, "second@example.com", Role.ADMIN)
        await _login(client, "admin@example.com")
        self_demote = await client.patch(
            f"/admin/users/{admin_id}", json={"role": "viewer"}, headers=CSRF
        )
        assert self_demote.status_code == 409
        demote_other = await client.patch(
            f"/admin/users/{second_id}", json={"role": "viewer"}, headers=CSRF
        )
        assert demote_other.status_code == 200

    async def test_reset_password(
        self,
        client: httpx.AsyncClient,
        other_client: httpx.AsyncClient,
        state: AppState,
        admin_headers: dict[str, str],
    ) -> None:
        user_id = await _user(state, "vi@example.com")
        await _login(other_client, "vi@example.com")
        reset = await client.post(f"/admin/users/{user_id}/reset-password", headers=admin_headers)
        temporary = reset.json()["temporary_password"]
        assert (await other_client.get("/auth/me")).status_code == 401
        assert (await _login(other_client, "vi@example.com")).status_code == 401
        assert (await _login(other_client, "vi@example.com", temporary)).status_code == 200
        assert (
            await client.patch("/admin/users/none", json={}, headers=admin_headers)
        ).status_code == 404


async def test_no_passwords_or_tokens_are_stored_in_plaintext(
    client: httpx.AsyncClient, state: AppState, tmp_path: Path
) -> None:
    await _user(state, "vi@example.com")
    session = (await _login(client, "vi@example.com")).cookies[SESSION_COOKIE]
    api_token = (await client.post("/auth/tokens", json={"name": "t"}, headers=CSRF)).json()[
        "token"
    ]
    stored = await persisted_bytes(state.engine, tmp_path)
    for secret in (PASSWORD, session, api_token):
        assert secret.encode() not in stored
    assert b"$argon2id$" in stored


def test_cli_create_user(
    database_url: str, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr("sys.stdin", io.StringIO(PASSWORD + "\n"))
    args = ["create-user", "--email", "Root@Example.com", "--name", "Root", "--password-stdin"]
    assert main([*args, "--database-url", database_url]) == 0
    assert "created admin root@example.com" in capsys.readouterr().out

    async def check() -> None:
        engine = create_engine(database_url)
        found = await SqlUserRepository(engine).get_with_password("root@example.com")
        await engine.dispose()
        assert found is not None and found[0].role is Role.ADMIN

    asyncio.run(check())

    monkeypatch.setattr("sys.stdin", io.StringIO(PASSWORD + "\n"))
    assert main([*args, "--database-url", database_url]) == 1
    assert "already exists" in capsys.readouterr().err
    monkeypatch.setattr("sys.stdin", io.StringIO("short\n"))
    assert (
        main(
            [
                "create-user",
                "--email",
                "x@y.co",
                "--name",
                "X",
                "--password-stdin",
                "--database-url",
                database_url,
            ]
        )
        == 1
    )
