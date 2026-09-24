from dataclasses import replace
from datetime import UTC, datetime, timedelta

import httpx
import pytest

from tollbooth.domain import LedgerEntry, Outcome, Provider, Usage
from tollbooth.security import new_id
from tollbooth.state import AppState

T0 = datetime(2026, 9, 1, 12, tzinfo=UTC)
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
    usage=Usage(input_tokens=1000, output_tokens=100, cache_read_tokens=10),
    cost_nanousd=517_800,
)


@pytest.fixture
async def seeded(state: AppState) -> None:
    entries = [
        BASE,
        replace(BASE, created_at=T0 + timedelta(days=1), cost_nanousd=1),
        replace(
            BASE,
            team="ads",
            virtual_key_id="key_b",
            provider=Provider.ANTHROPIC,
            model="claude-sonnet-4-6",
            usage=Usage(input_tokens=10, cache_write_tokens=2000, cache_write_1h_tokens=1000),
            cost_nanousd=19_530_000,
        ),
        replace(BASE, team="ads", virtual_key_id="key_c", model="mystery-model", cost_nanousd=None),
    ]
    for entry in entries:
        await state.ledger.record(replace(entry, id=new_id()))


async def _spend(client: httpx.AsyncClient, headers: dict[str, str], **params: str) -> dict:
    response = await client.get("/admin/spend", params=params, headers=headers)
    assert response.status_code == 200, response.text
    return response.json()


@pytest.mark.usefixtures("seeded")
async def test_spend_by_team(client: httpx.AsyncClient, admin_headers: dict[str, str]) -> None:
    report = await _spend(client, admin_headers)
    assert report["group_by"] == "team"
    assert report["currency"] == "USD"
    assert report["total"] == {
        "requests": 4,
        "input_tokens": 3010,
        "output_tokens": 300,
        "cache_read_tokens": 30,
        "cache_write_tokens": 3000,
        "cost_usd": "0.020047801",
        "unpriced_requests": 1,
        "error_requests": 0,
    }
    assert [(g["group"], g["cost_usd"], g["unpriced_requests"]) for g in report["groups"]] == [
        ("ads", "0.01953", 1),
        ("search", "0.000517801", 0),
    ]


@pytest.mark.usefixtures("seeded")
@pytest.mark.parametrize(
    ("group_by", "expected"),
    [
        ("provider", {"anthropic": "0.01953", "openai": "0.000517801"}),
        ("key", {"key_b": "0.01953", "key_a": "0.000517801", "key_c": "0"}),
        (
            "model",
            {"claude-sonnet-4-6": "0.01953", "gpt-4o-mini": "0.000517801", "mystery-model": "0"},
        ),
    ],
)
async def test_spend_group_by(
    client: httpx.AsyncClient, admin_headers: dict[str, str], group_by: str, expected: dict
) -> None:
    report = await _spend(client, admin_headers, group_by=group_by)
    assert {g["group"]: g["cost_usd"] for g in report["groups"]} == expected


@pytest.mark.usefixtures("seeded")
async def test_spend_date_range_is_start_inclusive_end_exclusive(
    client: httpx.AsyncClient, admin_headers: dict[str, str]
) -> None:
    day_one = await _spend(client, admin_headers, start="2026-09-01", end="2026-09-02")
    assert day_one["total"]["requests"] == 3
    assert day_one["start"] == "2026-09-01T00:00:00Z"

    from_noon = await _spend(client, admin_headers, start=T0.isoformat(), end="2026-09-02")
    assert from_noon["total"]["requests"] == 3

    day_two = await _spend(client, admin_headers, start="2026-09-02T00:00:00+00:00")
    assert day_two["total"]["cost_usd"] == "0.000000001"

    offset = await _spend(client, admin_headers, end="2026-09-01T14:00:00+02:00")
    assert offset["total"]["requests"] == 0


@pytest.mark.usefixtures("seeded")
async def test_spend_filters(client: httpx.AsyncClient, admin_headers: dict[str, str]) -> None:
    ads_openai = await _spend(client, admin_headers, team="ads", provider="openai")
    assert [g["group"] for g in ads_openai["groups"]] == ["ads"]
    assert ads_openai["total"]["requests"] == 1

    by_key = await _spend(client, admin_headers, key_id="key_a", group_by="model")
    assert by_key["total"]["requests"] == 2

    none = await _spend(client, admin_headers, model="nope")
    assert none["groups"] == []
    assert none["total"]["cost_usd"] == "0"


@pytest.mark.parametrize(
    "params",
    [
        {"group_by": "planet"},
        {"provider": "gemini"},
        {"start": "yesterday"},
        {"start": "2026-09-02", "end": "2026-09-01"},
        {"surprise": "1"},
    ],
)
async def test_spend_rejects_bad_params(
    client: httpx.AsyncClient, admin_headers: dict[str, str], params: dict[str, str]
) -> None:
    response = await client.get("/admin/spend", params=params, headers=admin_headers)
    assert response.status_code == 422


async def test_spend_requires_admin(client: httpx.AsyncClient) -> None:
    assert (await client.get("/admin/spend")).status_code == 401
