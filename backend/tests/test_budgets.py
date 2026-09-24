from dataclasses import replace
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from conftest import MakeKey
from mock_providers import MockProviders
from sqlalchemy.ext.asyncio import AsyncEngine

from tollbooth.budgets import BudgetTracker
from tollbooth.domain import (
    Budget,
    BudgetPeriod,
    BudgetScope,
    Enforcement,
    LedgerEntry,
    Outcome,
    Provider,
    Usage,
    VirtualKey,
)
from tollbooth.repositories.base import LedgerFilter
from tollbooth.repositories.sql import SqlBudgetRepository, SqlLedgerRepository
from tollbooth.security import hash_virtual_key, new_id
from tollbooth.state import AppState

NOW = datetime(2026, 9, 24, 12, tzinfo=UTC)
OPENAI_BODY = {"model": "gpt-4o-mini", "messages": [{"role": "user", "content": "hi"}]}


def _budget(**overrides: object) -> Budget:
    base = Budget(
        id=new_id(),
        name="search monthly",
        scope=BudgetScope.TEAM,
        scope_value="search",
        period=BudgetPeriod.MONTH,
        limit_nanousd=1_000_000,
        enforcement=Enforcement.HARD,
        thresholds=(50, 80, 100),
        enabled=True,
        created_at=NOW,
        updated_at=NOW,
    )
    return replace(base, **overrides)


def _entry(**overrides: object) -> LedgerEntry:
    base = LedgerEntry(
        id=new_id(),
        created_at=NOW,
        team="search",
        virtual_key_id="key_a",
        provider=Provider.OPENAI,
        model="gpt-4o-mini",
        streamed=False,
        status_code=200,
        outcome=Outcome.SUCCESS,
        latency_ms=10,
        usage=Usage(input_tokens=1),
        cost_nanousd=400_000,
    )
    return replace(base, **overrides)


def _key(team: str = "search", key_id: str = "key_a") -> VirtualKey:
    return VirtualKey(
        id=key_id,
        name="svc",
        team=team,
        key_prefix="tb_x",
        credential_id="c",
        provider=Provider.OPENAI,
        created_at=NOW,
    )


class Clock:
    def __init__(self, now: datetime) -> None:
        self.now = now

    def __call__(self) -> datetime:
        return self.now


class TestTracker:
    @pytest.fixture
    def repos(self, engine: AsyncEngine) -> tuple[SqlBudgetRepository, SqlLedgerRepository]:
        return SqlBudgetRepository(engine), SqlLedgerRepository(engine)

    async def test_blocks_only_exhausted_hard_budgets_in_scope(self, repos) -> None:
        budgets, ledger = repos
        await budgets.create(_budget())
        await budgets.create(_budget(scope_value="ads", limit_nanousd=1))
        await budgets.create(_budget(enforcement=Enforcement.SOFT, limit_nanousd=1))
        tracker = BudgetTracker(budgets, ledger, clock=Clock(NOW))

        assert await tracker.blocking(_key()) is None
        for _ in range(3):
            await ledger.record(_entry())
        tracker.invalidate()
        blocked = await tracker.blocking(_key())
        assert blocked is not None
        assert blocked.budget.name == "search monthly"
        assert blocked.spend_nanousd == 1_200_000
        assert await tracker.blocking(_key(team="other")) is None

    async def test_spend_counts_only_the_current_period(self, repos) -> None:
        budgets, ledger = repos
        budget = _budget(period=BudgetPeriod.DAY)
        await budgets.create(budget)
        await ledger.record(_entry(created_at=NOW - timedelta(days=1)))
        await ledger.record(_entry(created_at=NOW.replace(hour=0)))
        clock = Clock(NOW)
        tracker = BudgetTracker(budgets, ledger, clock=clock)
        assert (await tracker.usage(budget)).spend_nanousd == 400_000

        clock.now = NOW + timedelta(days=1)
        usage = await tracker.usage(budget)
        assert usage.spend_nanousd == 0
        assert usage.period_start == datetime(2026, 9, 25, tzinfo=UTC)

    async def test_record_advances_cached_spend_without_a_refetch(self, repos) -> None:
        budgets, ledger = repos
        budget = _budget(limit_nanousd=500_000)
        await budgets.create(budget)
        tracker = BudgetTracker(budgets, ledger, clock=Clock(NOW), ttl_seconds=3600)
        assert (await tracker.usage(budget)).spend_nanousd == 0

        entry = _entry()
        await ledger.record(entry)
        [usage] = await tracker.record(entry)
        assert usage.spend_nanousd == 400_000
        assert not usage.exhausted

        entry = _entry(cost_nanousd=None)
        await ledger.record(entry)
        [usage] = await tracker.record(entry)
        assert usage.spend_nanousd == 400_000

    async def test_key_and_global_scopes(self, repos) -> None:
        budgets, ledger = repos
        await budgets.create(_budget(scope=BudgetScope.KEY, scope_value="key_b"))
        await budgets.create(_budget(scope=BudgetScope.GLOBAL, scope_value=None))
        await budgets.create(_budget(enabled=False))
        tracker = BudgetTracker(budgets, ledger, clock=Clock(NOW))
        scopes = [b.scope for b in await tracker.applicable("search", "key_b")]
        assert sorted(scopes) == [BudgetScope.GLOBAL, BudgetScope.KEY]
        assert [b.scope for b in await tracker.applicable("ads", "key_a")] == [BudgetScope.GLOBAL]

    async def test_crossed_thresholds(self) -> None:
        from tollbooth.budgets import BudgetUsage

        usage = BudgetUsage(_budget(limit_nanousd=1000), NOW, NOW, spend_nanousd=800)
        assert usage.crossed(80)
        assert not usage.crossed(81)
        assert not usage.exhausted


async def _create(client: httpx.AsyncClient, headers: dict[str, str], **body: object) -> dict:
    payload = {
        "name": "search monthly",
        "scope": {"type": "team", "value": "search"},
        "period": "month",
        "limit_usd": "0.0005",
        "enforcement": "hard",
    } | body
    response = await client.post("/admin/budgets", json=payload, headers=headers)
    assert response.status_code == 201, response.text
    return response.json()


class TestAdminApi:
    async def test_create_list_update_delete(
        self, client: httpx.AsyncClient, admin_headers: dict[str, str]
    ) -> None:
        created = await _create(client, admin_headers)
        assert created["limit_usd"] == "0.0005"
        assert created["thresholds"] == [50, 80, 100]
        assert created["enabled"] is True
        assert created["usage"]["spend_usd"] == "0"
        assert created["usage"]["percent_used"] == 0
        assert created["usage"]["exhausted"] is False

        listed = (await client.get("/admin/budgets", headers=admin_headers)).json()
        assert [b["id"] for b in listed] == [created["id"]]

        patched = await client.patch(
            f"/admin/budgets/{created['id']}",
            json={"limit_usd": 25, "thresholds": [90, 75, 90], "enforcement": "soft"},
            headers=admin_headers,
        )
        assert patched.status_code == 200
        body = patched.json()
        assert (body["limit_usd"], body["thresholds"], body["enforcement"]) == (
            "25",
            [75, 90],
            "soft",
        )
        assert body["name"] == "search monthly"
        assert body["updated_at"] >= created["updated_at"]

        url = f"/admin/budgets/{created['id']}"
        assert (await client.delete(url, headers=admin_headers)).status_code == 204
        assert (await client.get(url, headers=admin_headers)).status_code == 404
        assert (await client.delete(url, headers=admin_headers)).status_code == 404

    @pytest.mark.parametrize(
        "body",
        [
            {"scope": {"type": "global", "value": "x"}},
            {"scope": {"type": "team"}},
            {"scope": {"type": "team", "value": "  "}},
            {"scope": {"type": "key", "value": "missing-key"}},
            {"limit_usd": 0},
            {"limit_usd": "-5"},
            {"limit_usd": "0.0000000001"},
            {"thresholds": [0]},
            {"thresholds": [1001]},
            {"period": "year"},
            {"enforcement": "maybe"},
            {"surprise": True},
        ],
    )
    async def test_validation(
        self, client: httpx.AsyncClient, admin_headers: dict[str, str], body: dict
    ) -> None:
        payload = {
            "name": "b",
            "scope": {"type": "team", "value": "search"},
            "period": "month",
            "limit_usd": "10",
        } | body
        response = await client.post("/admin/budgets", json=payload, headers=admin_headers)
        assert response.status_code == 422, response.text

    async def test_key_scope_requires_existing_key(
        self,
        client: httpx.AsyncClient,
        admin_headers: dict[str, str],
        make_key: MakeKey,
        state: AppState,
    ) -> None:
        plaintext = await make_key(Provider.OPENAI)
        key = await state.keys.get_by_hash(hash_virtual_key(plaintext))
        assert key is not None
        created = await _create(client, admin_headers, scope={"type": "key", "value": key.id})
        assert created["scope"] == {"type": "key", "value": key.id}

    async def test_usage_reflects_ledger_spend(
        self, client: httpx.AsyncClient, admin_headers: dict[str, str], state: AppState
    ) -> None:
        await state.ledger.record(_entry(created_at=datetime.now(UTC), cost_nanousd=400_000))
        created = await _create(client, admin_headers)
        assert created["usage"]["spend_usd"] == "0.0004"
        assert created["usage"]["percent_used"] == 80.0

    async def test_requires_admin(self, client: httpx.AsyncClient) -> None:
        assert (await client.get("/admin/budgets")).status_code == 401


class TestEnforcement:
    async def test_hard_budget_blocks_once_spent(
        self,
        client: httpx.AsyncClient,
        admin_headers: dict[str, str],
        make_key: MakeKey,
        providers: MockProviders,
        state: AppState,
    ) -> None:
        key = await make_key(Provider.OPENAI)
        await _create(client, admin_headers, limit_usd="0.0005")
        auth = {"Authorization": f"Bearer {key}"}

        first = await client.post("/v1/chat/completions", json=OPENAI_BODY, headers=auth)
        assert first.status_code == 200

        second = await client.post("/v1/chat/completions", json=OPENAI_BODY, headers=auth)
        assert second.status_code == 429
        error = second.json()["error"]
        assert error["type"] == "budget_exceeded"
        assert "search monthly" in error["message"]
        assert int(second.headers["retry-after"]) > 0
        assert len(providers.received) == 1

        entries = await state.ledger.page(LedgerFilter())
        assert [(e.outcome, e.status_code) for e in entries] == [
            (Outcome.BUDGET_EXCEEDED, 429),
            (Outcome.SUCCESS, 200),
        ]
        assert entries[0].cost_nanousd == 0

    async def test_anthropic_gets_its_own_error_shape(
        self,
        client: httpx.AsyncClient,
        admin_headers: dict[str, str],
        make_key: MakeKey,
    ) -> None:
        key = await make_key(Provider.ANTHROPIC, team="ads")
        await _create(
            client,
            admin_headers,
            scope={"type": "team", "value": "ads"},
            limit_usd="0.000000001",
            period="day",
        )
        await client.get("/admin/budgets", headers=admin_headers)
        response = await client.post(
            "/v1/messages",
            json={"model": "claude-sonnet-4-6", "max_tokens": 5, "messages": []},
            headers={"x-api-key": key},
        )
        assert response.status_code == 200
        blocked = await client.post(
            "/v1/messages",
            json={"model": "claude-sonnet-4-6", "max_tokens": 5, "messages": []},
            headers={"x-api-key": key},
        )
        assert blocked.status_code == 429
        assert blocked.json()["type"] == "error"
        assert blocked.json()["error"]["type"] == "budget_exceeded"

    async def test_soft_and_disabled_budgets_never_block(
        self,
        client: httpx.AsyncClient,
        admin_headers: dict[str, str],
        make_key: MakeKey,
    ) -> None:
        key = await make_key(Provider.OPENAI)
        await _create(client, admin_headers, enforcement="soft", limit_usd="0.000000001")
        await _create(client, admin_headers, enabled=False, limit_usd="0.000000001")
        auth = {"Authorization": f"Bearer {key}"}
        for _ in range(3):
            response = await client.post("/v1/chat/completions", json=OPENAI_BODY, headers=auth)
            assert response.status_code == 200

    async def test_other_teams_are_unaffected(
        self,
        client: httpx.AsyncClient,
        admin_headers: dict[str, str],
        make_key: MakeKey,
    ) -> None:
        key = await make_key(Provider.OPENAI, team="ads")
        await _create(client, admin_headers, limit_usd="0.000000001")
        auth = {"Authorization": f"Bearer {key}"}
        for _ in range(2):
            response = await client.post("/v1/chat/completions", json=OPENAI_BODY, headers=auth)
            assert response.status_code == 200

    async def test_raising_the_limit_unblocks_immediately(
        self,
        client: httpx.AsyncClient,
        admin_headers: dict[str, str],
        make_key: MakeKey,
    ) -> None:
        key = await make_key(Provider.OPENAI)
        budget = await _create(client, admin_headers, limit_usd="0.0001")
        auth = {"Authorization": f"Bearer {key}"}
        await client.post("/v1/chat/completions", json=OPENAI_BODY, headers=auth)
        blocked = await client.post("/v1/chat/completions", json=OPENAI_BODY, headers=auth)
        assert blocked.status_code == 429

        await client.patch(
            f"/admin/budgets/{budget['id']}", json={"limit_usd": 100}, headers=admin_headers
        )
        allowed = await client.post("/v1/chat/completions", json=OPENAI_BODY, headers=auth)
        assert allowed.status_code == 200

    async def test_budget_check_failure_fails_open(
        self,
        client: httpx.AsyncClient,
        make_key: MakeKey,
        state: AppState,
        monkeypatch: pytest.MonkeyPatch,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        key = await make_key(Provider.OPENAI)

        async def broken(_key: VirtualKey) -> None:
            raise RuntimeError("database is locked")

        monkeypatch.setattr(state.budget_tracker, "blocking", broken)
        response = await client.post(
            "/v1/chat/completions", json=OPENAI_BODY, headers={"Authorization": f"Bearer {key}"}
        )
        assert response.status_code == 200
        assert "budget check failed" in caplog.text
