"""Process-local liveness and readiness endpoints."""

from fastapi import FastAPI, Response, status


def install_health_contract(app: FastAPI) -> None:
    """Install dependency-free process health endpoints."""

    @app.get("/health/live", include_in_schema=False)
    async def health_live() -> dict[str, str]:
        return {"status": "alive"}

    @app.get("/health/ready", include_in_schema=False)
    async def health_ready(response: Response) -> dict[str, str | int]:
        manager = getattr(app.state, "thread_manager", None)
        if manager is None:
            return {"status": "ready"}

        snapshot = manager.snapshot()
        manager_state = getattr(snapshot.state, "value", str(snapshot.state))
        if manager_state != "running" or snapshot.stuck_count > 0:
            response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
            return {
                "status": "not_ready",
                "manager_state": manager_state,
                "stuck_count": snapshot.stuck_count,
            }
        return {
            "status": "ready",
            "manager_state": manager_state,
            "stuck_count": 0,
        }
