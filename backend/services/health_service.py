"""Process-local liveness and readiness endpoints."""

from fastapi import FastAPI


def install_health_contract(app: FastAPI) -> None:
    """Install dependency-free process health endpoints."""

    @app.get("/health/live", include_in_schema=False)
    async def health_live() -> dict[str, str]:
        return {"status": "alive"}

    @app.get("/health/ready", include_in_schema=False)
    async def health_ready() -> dict[str, str]:
        # Uvicorn does not accept traffic until the application lifespan has
        # completed, so reaching this handler is the readiness condition.
        return {"status": "ready"}
