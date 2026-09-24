from collections.abc import AsyncIterator
from pathlib import Path

import httpx
import pytest

from tollbooth.main import create_app
from tollbooth.settings import Settings


@pytest.fixture
async def served(settings: Settings, tmp_path: Path) -> AsyncIterator[httpx.AsyncClient]:
    dist = tmp_path / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text("<div id=root></div>")
    (dist / "assets" / "app-abc123.js").write_text("console.log('hi')")
    app = create_app(settings.model_copy(update={"dashboard_dir": dist}))
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://t") as client:
            yield client


async def test_serves_index_and_assets(served: httpx.AsyncClient) -> None:
    index = await served.get("/dashboard/")
    assert index.status_code == 200
    assert index.text == "<div id=root></div>"
    assert index.headers["cache-control"] == "no-cache"

    asset = await served.get("/dashboard/assets/app-abc123.js")
    assert asset.text == "console.log('hi')"
    assert "cache-control" not in asset.headers


async def test_client_routes_fall_back_to_index(served: httpx.AsyncClient) -> None:
    response = await served.get("/dashboard/keys")
    assert response.status_code == 200
    assert response.text == "<div id=root></div>"


async def test_root_redirects_to_dashboard(served: httpx.AsyncClient) -> None:
    response = await served.get("/")
    assert response.status_code == 307
    assert response.headers["location"] == "/dashboard/"


async def test_api_routes_still_work(served: httpx.AsyncClient) -> None:
    assert (await served.get("/healthz")).json() == {"status": "ok"}
    assert (await served.get("/admin/keys")).status_code == 401


async def test_dashboard_disabled_by_default(client: httpx.AsyncClient) -> None:
    assert (await client.get("/dashboard/")).status_code == 404


def test_missing_build_fails_fast(settings: Settings, tmp_path: Path) -> None:
    with pytest.raises(RuntimeError, match="dashboard build not found"):
        create_app(settings.model_copy(update={"dashboard_dir": tmp_path / "nope"}))
