FROM node:26-slim AS dashboard
WORKDIR /dashboard
COPY dashboard/package.json dashboard/package-lock.json ./
RUN --mount=type=cache,target=/root/.npm npm ci
COPY dashboard/ ./
RUN npm run build

FROM python:3.12-slim AS builder
COPY --from=ghcr.io/astral-sh/uv:0.12.18 /uv /bin/uv
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    UV_PROJECT_ENVIRONMENT=/app/.venv
WORKDIR /src
COPY backend/pyproject.toml backend/uv.lock backend/.python-version ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --no-dev --no-install-project
COPY backend/ ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --no-dev --no-editable

FROM python:3.12-slim
RUN useradd --system --uid 10001 --home-dir /app tollbooth \
    && mkdir -p /app/data \
    && chown tollbooth /app/data
WORKDIR /app
COPY --from=builder /app/.venv /app/.venv
COPY backend/pricing.toml /app/pricing.toml
COPY --from=dashboard /dashboard/dist /app/dashboard
ENV PATH=/app/.venv/bin:$PATH \
    PYTHONUNBUFFERED=1 \
    TOLLBOOTH_PRICING_FILE=/app/pricing.toml \
    TOLLBOOTH_DATABASE_URL=sqlite+aiosqlite:////app/data/tollbooth.db \
    TOLLBOOTH_DASHBOARD_DIR=/app/dashboard
USER tollbooth
EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=3s --start-period=10s \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8080/healthz')"]
CMD ["uvicorn", "tollbooth.main:create_app", "--factory", "--host", "0.0.0.0", "--port", "8080"]
