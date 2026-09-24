from fastapi import FastAPI


def create_app() -> FastAPI:
    app = FastAPI(title="Tollbooth")

    @app.get("/healthz")
    async def healthz() -> dict[str, str]:
        return {"status": "ok"}

    return app
