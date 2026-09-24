from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException
from starlette.responses import Response
from starlette.types import Scope

MOUNT_PATH = "/dashboard"


class _SinglePageApp(StaticFiles):
    """Serves built assets, falling back to index.html so client-side routes survive reloads."""

    async def get_response(self, path: str, scope: Scope) -> Response:
        try:
            response = await super().get_response(path, scope)
        except HTTPException as e:
            if e.status_code != 404:
                raise
            response = await super().get_response("index.html", scope)
        else:
            if response.status_code == 404:
                response = await super().get_response("index.html", scope)
        if not path.startswith("assets/"):
            response.headers["cache-control"] = "no-cache"
        return response


def mount_dashboard(app: FastAPI, directory: Path) -> None:
    if not (directory / "index.html").is_file():
        raise RuntimeError(f"dashboard build not found: {directory / 'index.html'}")
    app.mount(MOUNT_PATH, _SinglePageApp(directory=directory, html=True), name="dashboard")

    @app.get("/", include_in_schema=False)
    async def root() -> RedirectResponse:
        return RedirectResponse(f"{MOUNT_PATH}/")
