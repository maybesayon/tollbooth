from dataclasses import replace
from datetime import UTC, datetime, timedelta

import httpx
import pytest

from tollbooth.domain import LedgerEntry, Outcome, Provider, Usage
from tollbooth.state import AppState

T0 = datetime(2026, 9, 1, 10, 15, tzinfo=UTC)
BASE = LedgerEntry(
    id="",
    created_at=T0,
    team="search",
    virtual_key_id="key_a",
    provider=Provider.OPENAI,
    model="gpt-4o-mini",
    streamed=False,
    status_code=200,
    outcome=Outcome.SUCCESS,
    latency_ms=100,
    usage=Usage(input_tokens=100, output_tokens=10),
    cost_nanousd=1000,
)


@pytest.fixture
async def seeded(state: AppState) -> list[LedgerEntry]:
    entries = [
        replace(BASE, id="e1"),
        replace(BASE, id="e2", created_at=T0 + timedelta(minutes=50), team="ads"),
        replace(
            BASE,
            id="e3",
            created_at=T0 + timedelta(hours=2),
            outcome=Outcome.UPSTREAM_ERROR,
            status_code=429,
            error_type="rate_limit_exceeded",
            usage=Usage(),
            cost_nanousd=0,
        ),
        replace(BASE, id="e4", created_at=T0 + timedelta(days=1), cost_nanousd=None),
        replace(BASE, id="e5", created_at=T0 + timedelta(days=1), model="gpt-4o"),
    ]
    for entry in entries:
        await state.ledger.record(entry)
    return entries


async def _get(client: httpx.AsyncClient, headers: dict[str, str], path: str, **params: str):
    response = await client.get(path, params=params, headers=headers)
    assert response.status_code == 200, response.text
    return response.json()


@pytest.mark.usefixtures("seeded")
async def test_timeseries_by_day(client: httpx.AsyncClient, admin_headers: dict[str, str]) -> None:
    report = await _get(
        client,
        admin_headers,
        "/admin/spend/timeseries",
        start="2026-09-01",
        end="2026-09-03",
    )
    assert report["interval"] == "day"
    assert [
        (p["bucket"], p["group"], p["requests"], p["cost_usd"], p["error_requests"])
        for p in report["points"]
    ] == [
        ("2026-09-01T00:00:00Z", None, 3, "0.000002", 1),
        ("2026-09-02T00:00:00Z", None, 2, "0.000001", 0),
    ]
    assert report["points"][1]["unpriced_requests"] == 1


@pytest.mark.usefixtures("seeded")
async def test_timeseries_by_hour_and_team(
    client: httpx.AsyncClient, admin_headers: dict[str, str]
) -> None:
    report = await _get(
        client,
        admin_headers,
        "/admin/spend/timeseries",
        start="2026-09-01T00:00:00Z",
        end="2026-09-02T00:00:00Z",
        interval="hour",
        group_by="team",
    )
    assert [(p["bucket"], p["group"], p["requests"]) for p in report["points"]] == [
        ("2026-09-01T10:00:00Z", "search", 1),
        ("2026-09-01T11:00:00Z", "ads", 1),
        ("2026-09-01T12:00:00Z", "search", 1),
    ]


@pytest.mark.usefixtures("seeded")
async def test_timeseries_filters(client: httpx.AsyncClient, admin_headers: dict[str, str]) -> None:
    report = await _get(
        client,
        admin_headers,
        "/admin/spend/timeseries",
        start="2026-09-01",
        end="2026-09-03",
        outcome="upstream_error",
    )
    assert [(p["bucket"], p["requests"]) for p in report["points"]] == [("2026-09-01T00:00:00Z", 1)]


@pytest.mark.parametrize(
    "params",
    [
        {},
        {"start": "2026-09-01"},
        {"start": "2026-09-02", "end": "2026-09-01"},
        {"start": "2026-01-01", "end": "2026-03-01", "interval": "hour"},
        {"start": "2016-01-01", "end": "2026-03-01"},
        {"start": "2026-09-01", "end": "2026-09-02", "interval": "minute"},
    ],
)
async def test_timeseries_rejects_bad_params(
    client: httpx.AsyncClient, admin_headers: dict[str, str], params: dict[str, str]
) -> None:
    response = await client.get("/admin/spend/timeseries", params=params, headers=admin_headers)
    assert response.status_code == 422


@pytest.mark.usefixtures("seeded")
async def test_spend_counts_errors_and_filters_by_outcome(
    client: httpx.AsyncClient, admin_headers: dict[str, str]
) -> None:
    report = await _get(client, admin_headers, "/admin/spend")
    assert report["total"]["error_requests"] == 1
    errors = await _get(client, admin_headers, "/admin/spend", outcome="upstream_error")
    assert errors["total"]["requests"] == 1


@pytest.mark.usefixtures("seeded")
async def test_requests_pages_newest_first(
    client: httpx.AsyncClient, admin_headers: dict[str, str]
) -> None:
    first = await _get(client, admin_headers, "/admin/requests", limit="2")
    assert [r["id"] for r in first["items"]] == ["e5", "e4"]
    assert first["next_cursor"]

    second = await _get(
        client, admin_headers, "/admin/requests", limit="2", cursor=first["next_cursor"]
    )
    assert [r["id"] for r in second["items"]] == ["e3", "e2"]

    third = await _get(
        client, admin_headers, "/admin/requests", limit="2", cursor=second["next_cursor"]
    )
    assert [r["id"] for r in third["items"]] == ["e1"]
    assert third["next_cursor"] is None


@pytest.mark.usefixtures("seeded")
async def test_requests_item_shape(
    client: httpx.AsyncClient, admin_headers: dict[str, str]
) -> None:
    page = await _get(client, admin_headers, "/admin/requests", outcome="upstream_error")
    [item] = page["items"]
    assert item == {
        "id": "e3",
        "created_at": "2026-09-01T12:15:00Z",
        "team": "search",
        "key_id": "key_a",
        "provider": "openai",
        "model": "gpt-4o-mini",
        "streamed": False,
        "status_code": 429,
        "outcome": "upstream_error",
        "latency_ms": 100,
        "ttfb_ms": None,
        "input_tokens": 0,
        "output_tokens": 0,
        "cache_read_tokens": 0,
        "cache_write_tokens": 0,
        "cost_usd": "0",
        "error_type": "rate_limit_exceeded",
        "upstream_request_id": None,
    }
    unpriced = await _get(
        client, admin_headers, "/admin/requests", start="2026-09-02", model="gpt-4o-mini"
    )
    assert [(r["id"], r["cost_usd"]) for r in unpriced["items"]] == [("e4", None)]


@pytest.mark.usefixtures("seeded")
async def test_requests_filters(client: httpx.AsyncClient, admin_headers: dict[str, str]) -> None:
    ads = await _get(client, admin_headers, "/admin/requests", team="ads")
    assert [r["id"] for r in ads["items"]] == ["e2"]
    day_two = await _get(client, admin_headers, "/admin/requests", start="2026-09-02")
    assert {r["id"] for r in day_two["items"]} == {"e4", "e5"}


@pytest.mark.parametrize("params", [{"cursor": "garbage!"}, {"limit": "0"}, {"limit": "500"}])
async def test_requests_rejects_bad_params(
    client: httpx.AsyncClient, admin_headers: dict[str, str], params: dict[str, str]
) -> None:
    response = await client.get("/admin/requests", params=params, headers=admin_headers)
    assert response.status_code == 422


async def test_ledger_routes_require_admin(client: httpx.AsyncClient) -> None:
    for path in ("/admin/requests", "/admin/spend/timeseries"):
        assert (await client.get(path)).status_code == 401
