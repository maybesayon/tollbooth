import time
from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest
from conftest import MakeKey
from fake_webhooks import WebhookReceiver

from tollbooth.alerts import (
    SIGNATURE_HEADER,
    TIMESTAMP_HEADER,
    AlertManager,
    sign,
    slack_message,
    webhook_payload,
)
from tollbooth.budgets import BudgetUsage
from tollbooth.domain import (
    Alert,
    Budget,
    BudgetPeriod,
    BudgetScope,
    Enforcement,
    Provider,
)
from tollbooth.state import AppState

WEBHOOK_URL = "https://hooks.example.com/tollbooth/abc123-secret-path"
SLACK_URL = "https://hooks.slack.test/services/T000/B000/slack-secret-token"
OPENAI_BODY = {"model": "gpt-4o-mini", "messages": [{"role": "user", "content": "hi"}]}


def _read_files(directory: Path) -> bytes:
    return b"".join(p.read_bytes() for p in directory.iterdir() if p.is_file())


async def _channel(client: httpx.AsyncClient, headers: dict[str, str], **body: str) -> dict:
    payload = {"name": "ops webhook", "type": "webhook", "url": WEBHOOK_URL} | body
    response = await client.post("/admin/channels", json=payload, headers=headers)
    assert response.status_code == 201, response.text
    return response.json()


async def _budget(client: httpx.AsyncClient, headers: dict[str, str], **body: object) -> dict:
    payload = {
        "name": "search daily",
        "scope": {"type": "team", "value": "search"},
        "period": "day",
        "limit_usd": "0.001",
        "enforcement": "hard",
        "thresholds": [50, 100],
    } | body
    response = await client.post("/admin/budgets", json=payload, headers=headers)
    assert response.status_code == 201, response.text
    return response.json()


class TestChannels:
    async def test_webhook_secret_is_shown_once_and_url_stays_hidden(
        self,
        client: httpx.AsyncClient,
        admin_headers: dict[str, str],
        state: AppState,
        tmp_path: Path,
    ) -> None:
        created = await _channel(client, admin_headers)
        assert created["signing_secret"].startswith("whsec_")
        assert created["url_hint"] == "hooks.example.com"
        assert "url" not in created

        listed = (await client.get("/admin/channels", headers=admin_headers)).json()
        assert listed == [{k: v for k, v in created.items() if k != "signing_secret"}]

        await state.engine.dispose()
        stored = _read_files(tmp_path)
        assert b"abc123-secret-path" not in stored
        assert created["signing_secret"].encode() not in stored

    async def test_slack_channels_have_no_signing_secret(
        self, client: httpx.AsyncClient, admin_headers: dict[str, str]
    ) -> None:
        created = await _channel(client, admin_headers, name="slack", type="slack", url=SLACK_URL)
        assert created["signing_secret"] is None
        assert created["url_hint"] == "hooks.slack.test"

    @pytest.mark.parametrize(
        "body",
        [
            {"url": "ftp://example.com/x"},
            {"url": "not a url"},
            {"type": "email"},
            {"name": ""},
        ],
    )
    async def test_validation(
        self, client: httpx.AsyncClient, admin_headers: dict[str, str], body: dict
    ) -> None:
        payload = {"name": "c", "type": "webhook", "url": WEBHOOK_URL} | body
        response = await client.post("/admin/channels", json=payload, headers=admin_headers)
        assert response.status_code == 422

    async def test_duplicate_name(
        self, client: httpx.AsyncClient, admin_headers: dict[str, str]
    ) -> None:
        await _channel(client, admin_headers)
        response = await client.post(
            "/admin/channels",
            json={"name": "ops webhook", "type": "slack", "url": SLACK_URL},
            headers=admin_headers,
        )
        assert response.status_code == 409

    async def test_delete_detaches_from_budgets(
        self, client: httpx.AsyncClient, admin_headers: dict[str, str]
    ) -> None:
        channel = await _channel(client, admin_headers)
        budget = await _budget(client, admin_headers, channel_ids=[channel["id"]])
        assert budget["channel_ids"] == [channel["id"]]

        url = f"/admin/channels/{channel['id']}"
        assert (await client.delete(url, headers=admin_headers)).status_code == 204
        assert (await client.delete(url, headers=admin_headers)).status_code == 404
        refreshed = await client.get(f"/admin/budgets/{budget['id']}", headers=admin_headers)
        assert refreshed.json()["channel_ids"] == []

    async def test_budget_rejects_unknown_channel(
        self, client: httpx.AsyncClient, admin_headers: dict[str, str]
    ) -> None:
        response = await client.post(
            "/admin/budgets",
            json={
                "name": "b",
                "scope": {"type": "global"},
                "period": "month",
                "limit_usd": 10,
                "channel_ids": ["nope"],
            },
            headers=admin_headers,
        )
        assert response.status_code == 422

    async def test_send_test_webhook_is_signed(
        self,
        client: httpx.AsyncClient,
        admin_headers: dict[str, str],
        webhooks: WebhookReceiver,
    ) -> None:
        channel = await _channel(client, admin_headers)
        response = await client.post(f"/admin/channels/{channel['id']}/test", headers=admin_headers)
        assert response.json() == {"ok": True, "status_code": 200, "error": None}

        [received] = webhooks.received
        assert received.url == WEBHOOK_URL
        assert received.json["type"] == "test"
        timestamp = received.headers[TIMESTAMP_HEADER]
        assert abs(int(timestamp) - time.time()) < 60
        expected = sign(channel["signing_secret"], timestamp, received.body)
        assert received.headers[SIGNATURE_HEADER] == expected

    async def test_send_test_slack_uses_text(
        self,
        client: httpx.AsyncClient,
        admin_headers: dict[str, str],
        webhooks: WebhookReceiver,
    ) -> None:
        channel = await _channel(client, admin_headers, name="s", type="slack", url=SLACK_URL)
        await client.post(f"/admin/channels/{channel['id']}/test", headers=admin_headers)
        [received] = webhooks.received
        assert set(received.json) == {"text"}
        assert SIGNATURE_HEADER not in received.headers

    async def test_send_test_reports_failures_without_leaking_the_url(
        self,
        client: httpx.AsyncClient,
        admin_headers: dict[str, str],
        webhooks: WebhookReceiver,
    ) -> None:
        channel = await _channel(client, admin_headers)
        webhooks.failures_left["hooks.example.com"] = 1
        test_url = f"/admin/channels/{channel['id']}/test"
        failed = (await client.post(test_url, headers=admin_headers)).json()
        assert failed == {"ok": False, "status_code": 500, "error": "HTTP 500"}

        webhooks.unreachable.add("hooks.example.com")
        unreachable = (await client.post(test_url, headers=admin_headers)).json()
        assert unreachable == {"ok": False, "status_code": None, "error": "ConnectError"}


class TestAlerting:
    async def test_thresholds_fire_once_and_deliver_everywhere(
        self,
        client: httpx.AsyncClient,
        admin_headers: dict[str, str],
        make_key: MakeKey,
        state: AppState,
        webhooks: WebhookReceiver,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        webhook = await _channel(client, admin_headers)
        slack = await _channel(client, admin_headers, name="slack", type="slack", url=SLACK_URL)
        budget = await _budget(client, admin_headers, channel_ids=[webhook["id"], slack["id"]])
        key = await make_key(Provider.OPENAI)
        auth = {"Authorization": f"Bearer {key}"}

        # Each request costs $0.0005178, i.e. 51.78% of the $0.001 limit.
        first = await client.post("/v1/chat/completions", json=OPENAI_BODY, headers=auth)
        second = await client.post("/v1/chat/completions", json=OPENAI_BODY, headers=auth)
        third = await client.post("/v1/chat/completions", json=OPENAI_BODY, headers=auth)
        assert [r.status_code for r in (first, second, third)] == [200, 200, 429]
        await state.alert_manager.drain()

        events = [r.json for r in webhooks.to("hooks.example.com")]
        assert [(e["threshold_percent"], e["spend_usd"]) for e in events] == [
            (50, "0.0005178"),
            (100, "0.0010356"),
        ]
        event = events[1]
        assert event["type"] == "budget.threshold_crossed"
        assert event["limit_usd"] == "0.001"
        assert event["budget"] == {
            "id": budget["id"],
            "name": "search daily",
            "scope": {"type": "team", "value": "search"},
            "enforcement": "hard",
        }
        assert event["period"]["type"] == "day"

        slack_texts = [r.json["text"] for r in webhooks.to("hooks.slack.test")]
        assert len(slack_texts) == 2
        assert "reached 50% of its daily limit" in slack_texts[0]
        assert "Requests are blocked until" in slack_texts[1]

        alerts = (await client.get("/admin/alerts", headers=admin_headers)).json()
        assert [a["threshold_percent"] for a in alerts] == [100, 50]
        for alert in alerts:
            assert {
                (d["channel_name"], d["status"], d["attempts"]) for d in alert["deliveries"]
            } == {
                ("ops webhook", "delivered", 1),
                ("slack", "delivered", 1),
            }
        assert "abc123-secret-path" not in caplog.text
        assert "slack-secret-token" not in caplog.text

    async def test_retries_then_records_failure(
        self,
        client: httpx.AsyncClient,
        admin_headers: dict[str, str],
        make_key: MakeKey,
        state: AppState,
        webhooks: WebhookReceiver,
    ) -> None:
        ok = await _channel(client, admin_headers, name="flaky")
        broken = await _channel(
            client, admin_headers, name="broken", url="https://down.example.com/hook"
        )
        await _budget(
            client,
            admin_headers,
            thresholds=[10],
            enforcement="soft",
            channel_ids=[ok["id"], broken["id"]],
        )
        webhooks.failures_left["hooks.example.com"] = 2
        webhooks.failures_left["down.example.com"] = 99
        key = await make_key(Provider.OPENAI)
        await client.post(
            "/v1/chat/completions", json=OPENAI_BODY, headers={"Authorization": f"Bearer {key}"}
        )
        await state.alert_manager.drain()

        [alert] = (await client.get("/admin/alerts", headers=admin_headers)).json()
        deliveries = {d["channel_name"]: d for d in alert["deliveries"]}
        assert (deliveries["flaky"]["status"], deliveries["flaky"]["attempts"]) == (
            "delivered",
            3,
        )
        assert deliveries["flaky"]["last_error"] is None
        assert (deliveries["broken"]["status"], deliveries["broken"]["attempts"]) == ("failed", 4)
        assert deliveries["broken"]["last_error"] == "HTTP 500"

    async def test_alert_history_survives_budget_deletion(
        self,
        client: httpx.AsyncClient,
        admin_headers: dict[str, str],
        make_key: MakeKey,
        state: AppState,
    ) -> None:
        budget = await _budget(client, admin_headers, thresholds=[10], enforcement="soft")
        key = await make_key(Provider.OPENAI)
        await client.post(
            "/v1/chat/completions", json=OPENAI_BODY, headers={"Authorization": f"Bearer {key}"}
        )
        await client.delete(f"/admin/budgets/{budget['id']}", headers=admin_headers)
        alerts = (
            await client.get(f"/admin/alerts?budget_id={budget['id']}", headers=admin_headers)
        ).json()
        assert [(a["budget_name"], a["deliveries"]) for a in alerts] == [("search daily", [])]

    async def test_a_fresh_manager_does_not_repeat_alerts(self, state: AppState) -> None:
        now = datetime.now(UTC)
        budget = Budget(
            id="b1",
            name="b",
            scope=BudgetScope.GLOBAL,
            scope_value=None,
            period=BudgetPeriod.MONTH,
            limit_nanousd=100,
            enforcement=Enforcement.SOFT,
            thresholds=(50,),
            enabled=True,
            created_at=now,
            updated_at=now,
        )
        usage = BudgetUsage(budget, now, now, spend_nanousd=60)
        async with httpx.AsyncClient() as http:
            first = AlertManager(state.alerts, state.channels, state.secret_box, http)
            second = AlertManager(state.alerts, state.channels, state.secret_box, http)
            assert len(await first.evaluate([usage])) == 1
            assert await first.evaluate([usage]) == []
            assert await second.evaluate([usage]) == []

    async def test_requires_admin(self, client: httpx.AsyncClient) -> None:
        for path in ("/admin/alerts", "/admin/channels"):
            assert (await client.get(path)).status_code == 401


def test_payload_formats() -> None:
    now = datetime(2026, 9, 24, 12, tzinfo=UTC)
    budget = Budget(
        id="b1",
        name="ads weekly",
        scope=BudgetScope.KEY,
        scope_value="key_1",
        period=BudgetPeriod.WEEK,
        limit_nanousd=100_000_000_000,
        enforcement=Enforcement.SOFT,
        thresholds=(80,),
        enabled=True,
        created_at=now,
        updated_at=now,
    )
    alert = Alert(
        id="a1",
        budget_id="b1",
        budget_name="ads weekly",
        threshold=80,
        period_start=datetime(2026, 9, 21, tzinfo=UTC),
        period_end=datetime(2026, 9, 28, tzinfo=UTC),
        spend_nanousd=80_120_000_000,
        limit_nanousd=100_000_000_000,
        created_at=now,
    )
    assert slack_message(alert, budget) == {
        "text": "Tollbooth budget *ads weekly* (key key_1) reached 80% of its weekly limit: "
        "$80.12 of $100."
    }
    payload = webhook_payload(alert, budget)
    assert payload["period"] == {
        "type": "week",
        "start": "2026-09-21T00:00:00Z",
        "end": "2026-09-28T00:00:00Z",
    }
    assert (payload["spend_usd"], payload["limit_usd"]) == ("80.12", "100")
