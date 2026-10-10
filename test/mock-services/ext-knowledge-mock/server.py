"""Nexent external-knowledge mock service — single process, multiple route sets.

Layout of the single port (default 30090):

    /dify /datamate /idata /ragflow /haotian /assets   prefixed route sets
    /fault/v1/...                                       OpenAI-compatible fault provider
    /KnowledgeBase/... /ModelService/...                AIDP protocol (root mount)
    /health /_reset /_mock/* /_wire-log                unified control plane

The AIDP protocol family MUST stay at the root (no prefix):
backend/services/image_service.py reconstructs AIDP image URLs keeping only
scheme+netloc from AIDP_SERVER_URL (dropping any base path) and allowlists
paths starting with /KnowledgeBase/Tenants/, so a prefixed AIDP base would
break the image flow entirely. The same applies to the independent-AIDP
image fetch in backend/services/ind_aidp_service.py — which conveniently
means managed AIDP and ind-AIDP share these root routes, distinguished only
by credentials (ind-AIDP tests point server_url at this service and reuse
tenant "aidp" + the AIDP mock key).

Run standalone:
    python server.py --port 30090

Deploy with the mock-services dispatcher (product network attached):
    python test/mock-services/deploy.py up ext-knowledge
"""
import argparse
import asyncio
import importlib.util
import logging
import os
import sys
import time
from pathlib import Path
from typing import Optional

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

# Sibling modules are importable when this file runs as a script (script dir
# lands on sys.path) and when loaded via importlib from the fidelity tests.
# Make that explicit instead of relying on either convention.
_HERE = str(Path(__file__).resolve().parent)
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

from mock_common import (  # noqa: E402
    FaultInjector,
    StateStore,
    WireLog,
    service_for_path,
)
import assets_mock  # noqa: E402
import control  # noqa: E402
import datamate_mock  # noqa: E402
import dify_mock  # noqa: E402
import fault_provider_mock  # noqa: E402
import haotian_mock  # noqa: E402
import idata_mock  # noqa: E402
import ragflow_mock  # noqa: E402

logger = logging.getLogger("ext_knowledge_mock")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s  %(message)s",
)

# Repo-relative location of the existing AIDP management mock. Overridable
# via EXT_KNOWLEDGE_AIDP_MOCK_PATH for the Docker image, where the AIDP mock
# is copied to a different filesystem location (see Dockerfile).
_AIDP_MOCK_PATH_DEFAULT = (
    Path(__file__).resolve().parents[2]
    / "ext_components"
    / "aidp"
    / "mock_servers"
    / "aidp_mgmt_mock_server.py"
)


def load_aidp_app():
    """Load the existing AIDP management mock module and return its FastAPI app.

    Loaded in place (zero modifications) via importlib so the file keeps
    working standalone for the AIDP-minimal dev profile (DEV-GUIDE 3.2).
    """
    path = Path(os.environ.get("EXT_KNOWLEDGE_AIDP_MOCK_PATH") or _AIDP_MOCK_PATH_DEFAULT)
    if not path.is_file():
        raise FileNotFoundError(
            f"AIDP mock not found at {path}; set EXT_KNOWLEDGE_AIDP_MOCK_PATH"
        )
    spec = importlib.util.spec_from_file_location("ext_knowledge_aidp_mock", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    logger.info("AIDP MOCK  mounted from %s", path)
    return module.app


class FaultMiddleware(BaseHTTPMiddleware):
    """Applies scheduled failures and latency to the prefixed route sets only.

    AIDP paths are skipped on purpose: the AIDP sub-app carries its own
    FailNextMiddleware scoped to /KnowledgeBase, and its counters are driven
    through the control-plane proxy instead.
    """

    def __init__(self, app, faults: FaultInjector):
        super().__init__(app)
        self.faults = faults

    async def dispatch(self, request: Request, call_next):
        service = service_for_path(request.url.path)
        if service and service != "aidp":
            delay_ms = self.faults.get_latency(service)
            if delay_ms > 0:
                await asyncio.sleep(delay_ms / 1000.0)
            status = self.faults.pop_failure(service)
            if status is not None:
                logger.info(
                    "MOCK INJECT  service=%s status=%d path=%s",
                    service, status, request.url.path,
                )
                return JSONResponse(
                    status_code=status,
                    content={
                        "error": "mock-injected failure for retry testing",
                        "service": service,
                        "status": status,
                    },
                )
        return await call_next(request)


class WireLogMiddleware(BaseHTTPMiddleware):
    """Records every request (control plane and AIDP included) for evidence."""

    _MAX_BODY_BYTES = 4096

    def __init__(self, app, wire_log: WireLog):
        super().__init__(app)
        self.wire_log = wire_log

    async def dispatch(self, request: Request, call_next):
        started = time.perf_counter()
        body_preview: Optional[str] = None
        content_type = request.headers.get("content-type", "")
        # Only JSON bodies are captured, and never multipart uploads — reading
        # those in middleware would buffer file streams.
        if "application/json" in content_type:
            try:
                raw = await request.body()
                if len(raw) <= self._MAX_BODY_BYTES:
                    body_preview = raw.decode("utf-8", errors="replace")
            except Exception:  # pragma: no cover - defensive
                body_preview = None
        response = await call_next(request)
        duration_ms = round((time.perf_counter() - started) * 1000, 2)
        self.wire_log.record(
            service=service_for_path(request.url.path),
            method=request.method,
            path=request.url.path,
            status_code=response.status_code,
            duration_ms=duration_ms,
            body=body_preview,
        )
        return response


def create_app() -> FastAPI:
    """Assemble the service: control plane + prefixed route sets + AIDP root."""
    states = {name: StateStore(name) for name in
              ("dify", "datamate", "idata", "ragflow", "haotian", "assets")}
    faults = FaultInjector()
    wire_log = WireLog()
    asset_registry = assets_mock.AssetRegistry(states["assets"])
    fault_state = fault_provider_mock.FaultAttemptState()
    aidp_app = load_aidp_app()

    app = FastAPI(title="Nexent External Knowledge Mock", version="1.0.0")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    # Middleware order: the LAST added is the OUTERMOST. Fault first (inner),
    # wire log second (outer) so injected failures are logged too.
    app.add_middleware(FaultMiddleware, faults=faults)
    app.add_middleware(WireLogMiddleware, wire_log=wire_log)

    # Parent routes are matched before the root mount below, so these control
    # endpoints shadow the AIDP sub-app's own /health, /_reset and /_mock/*.
    app.include_router(
        control.create_control_router(
            states, faults, wire_log, aidp_app, asset_registry, fault_state
        )
    )
    app.include_router(fault_provider_mock.create_router(fault_state))
    app.include_router(dify_mock.create_router(states["dify"]))
    app.include_router(datamate_mock.create_router(states["datamate"]))
    app.include_router(idata_mock.create_router(states["idata"]))
    app.include_router(ragflow_mock.create_router(states["ragflow"]))
    app.include_router(haotian_mock.create_router(states["haotian"]))
    app.include_router(assets_mock.create_router(states["assets"]))

    # Root mount LAST: everything not matched above falls through to the AIDP
    # protocol (which brings its own scoped failure middleware and Bearer
    # auth). Single worker only — state lives in this process.
    app.mount("/", aidp_app)
    return app


app = create_app()


def main() -> None:
    parser = argparse.ArgumentParser(description="Nexent External Knowledge Mock")
    parser.add_argument("--host", default="0.0.0.0", help="Bind host (default 0.0.0.0)")
    parser.add_argument("--port", type=int, default=30090, help="Bind port (default 30090)")
    args = parser.parse_args()

    import uvicorn

    print(f"\nNexent External Knowledge Mock starting on http://{args.host}:{args.port}")
    print("  /dify /datamate /idata /ragflow /haotian /assets   prefixed route sets")
    print("  /fault/v1/...                                       OpenAI-compatible fault provider")
    print("  /KnowledgeBase/... /ModelService/...               AIDP protocol (root)")
    print("  /health /_reset /_mock/* /_wire-log                control plane")
    print("  POST /_reset to restore all seed state\n")

    # State is held in-process; never run with multiple workers.
    uvicorn.run(app, host=args.host, port=args.port, workers=1)


if __name__ == "__main__":
    main()
