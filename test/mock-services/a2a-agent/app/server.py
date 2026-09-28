"""Standalone official-SDK A2A mock with auth, fault scenarios, and observations."""

from __future__ import annotations

import asyncio
import hashlib
import json
from contextlib import asynccontextmanager
from typing import Any

from a2a.server.request_handlers import DefaultRequestHandler
from a2a.server.routes import create_agent_card_routes, create_jsonrpc_routes
from a2a.server.routes.rest_dispatcher import RestDispatcher
from a2a.server.tasks import InMemoryTaskStore
from a2a.types import (
    APIKeySecurityScheme,
    HTTPAuthSecurityScheme,
    AgentCapabilities,
    AgentCard,
    AgentInterface,
    AgentSkill,
    SecurityRequirement,
    SecurityScheme,
    StringList,
)
from starlette.applications import Starlette
from starlette.datastructures import Headers
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Mount, Route

from .auth import AUTH_PROFILES, JwtService, authenticate
from .cards import card_dict
from .config import Settings
from .executor import DeterministicExecutor
from .nacos_registry import NacosRegistry
from .observations import ObservationStore
from .redaction import redact_headers
from .scenarios import ScenarioCatalog


class A2AMiddleware(BaseHTTPMiddleware):
    def __init__(self, app: Any, profile_key: str, state: "ServiceState") -> None:
        super().__init__(app)
        self.profile_key = profile_key
        self.state = state

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        body = await request.body()
        headers = {key.lower(): value for key, value in request.headers.items()}
        authenticated = authenticate(AUTH_PROFILES[self.profile_key], headers, self.state.jwt)
        # Record fingerprints, never message text or arbitrary metadata secrets.
        try:
            payload = json.loads(body) if body else {}
            params = payload.get("params", payload)
            message = params.get("message", {})
            metadata = message.get("metadata", {})
            summary = {
                "rpc_method": payload.get("method"),
                "metadata_sha256": hashlib.sha256(json.dumps(metadata, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()).hexdigest(),
                "message_id": message.get("messageId", message.get("message_id")),
            }
        except (ValueError, TypeError, AttributeError):
            summary = {"invalid_json": True}
        self.state.observations.add(
            {
                "agent": self.profile_key,
                "method": request.method,
                "path": request.url.path,
                "headers": redact_headers(dict(Headers(scope=request.scope))),
                "body_sha256": hashlib.sha256(body).hexdigest(),
                "body_size": len(body),
                "scenario": self.state.scenarios.current_name,
                "authenticated": authenticated,
                "payload_summary": summary,
            }
        )
        scenario = self.state.scenarios.current()
        fault = scenario.get("fault", {})
        delay_ms = int(fault.get("delay_ms", 0))
        if delay_ms:
            await asyncio.sleep(delay_ms / 1000)
        if request.url.path.endswith("agent-card.json") and fault.get("malformed_card"):
            return Response("{not-json", media_type="application/json")
        status = fault.get("status")
        if status:
            return JSONResponse({"error": fault.get("message", "Injected fault")}, status_code=int(status))
        if not authenticated:
            return JSONResponse(
                {"status": 401, "source": "A2A-Mock-Gateway", "message": "Authorization failed"},
                status_code=401,
            )
        return await call_next(request)


class ServiceState:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.jwt = JwtService(settings.jwt_secret, settings.jwt_issuer, settings.jwt_ttl_seconds)
        self.scenarios = ScenarioCatalog(settings.scenario_catalog, settings.default_scenario)
        self.observations = ObservationStore(settings.observation_limit)
        self.registry = NacosRegistry(settings)
        self.registration_task: asyncio.Task[None] | None = None


def _sdk_card(settings: Settings, key: str) -> AgentCard:
    raw = card_dict(settings.advertised_base_url, key)
    security_schemes: dict[str, SecurityScheme] = {}
    for name, definition in raw.get("securitySchemes", {}).items():
        if "apiKeySecurityScheme" in definition:
            value = definition["apiKeySecurityScheme"]
            security_schemes[name] = SecurityScheme(
                api_key_security_scheme=APIKeySecurityScheme(
                    description=value["description"],
                    location=value["location"],
                    name=value["name"],
                )
            )
        elif "httpAuthSecurityScheme" in definition:
            value = definition["httpAuthSecurityScheme"]
            security_schemes[name] = SecurityScheme(
                http_auth_security_scheme=HTTPAuthSecurityScheme(
                    description=value["description"],
                    scheme=value["scheme"],
                    bearer_format=value["bearerFormat"],
                )
            )
    security_requirements = [
        SecurityRequirement(
            schemes={name: StringList() for name in definition["schemes"]}
        )
        for definition in raw.get("securityRequirements", [])
    ]
    return AgentCard(
        name=raw["name"],
        description=raw["description"],
        version=raw["version"],
        capabilities=AgentCapabilities(streaming=True, push_notifications=False),
        supported_interfaces=[
            AgentInterface(
                url=item["url"],
                protocol_binding=item["protocolBinding"],
                protocol_version=item["protocolVersion"],
            )
            for item in raw["supportedInterfaces"]
        ],
        default_input_modes=raw["defaultInputModes"],
        default_output_modes=raw["defaultOutputModes"],
        skills=[
            AgentSkill(
                id=skill["id"],
                name=skill["name"],
                description=skill["description"],
                tags=skill["tags"],
                examples=skill["examples"],
            )
            for skill in raw["skills"]
        ],
        security_schemes=security_schemes,
        security_requirements=security_requirements,
    )


def _agent_app(settings: Settings, key: str, state: ServiceState) -> Starlette:
    card = _sdk_card(settings, key)
    handler = DefaultRequestHandler(
        agent_executor=DeterministicExecutor(),
        task_store=InMemoryTaskStore(),
        agent_card=card,
    )
    routes = list(create_agent_card_routes(card))
    routes.extend(create_jsonrpc_routes(handler, rpc_url="/v1"))
    rest = RestDispatcher(request_handler=handler)
    routes.extend(
        [
            Route("/message:send", rest.on_message_send, methods=["POST"]),
            Route("/message:stream", rest.on_message_send_stream, methods=["POST"]),
        ]
    )
    child = Starlette(routes=routes)
    child.add_middleware(A2AMiddleware, profile_key=key, state=state)
    return child


def _authorized_control(request: Request, state: ServiceState) -> bool:
    return request.headers.get("x-a2a-control-token") == state.settings.control_token


def create_app(settings: Settings | None = None) -> Starlette:
    settings = settings or Settings.from_env()
    state = ServiceState(settings)

    @asynccontextmanager
    async def lifespan(_: Starlette):
        if settings.nacos_enabled:
            state.registration_task = asyncio.create_task(state.registry.register_with_retry())
        yield
        if state.registration_task and not state.registration_task.done():
            state.registration_task.cancel()
        await state.registry.deregister()

    async def health(_: Request) -> Response:
        return JSONResponse({"status": "healthy"})

    async def ready(_: Request) -> Response:
        ready_state = not settings.nacos_required or state.registry.state.registered
        return JSONResponse(
            {
                "status": "ready" if ready_state else "not-ready",
                "nacos": {
                    "enabled": settings.nacos_enabled,
                    "required": settings.nacos_required,
                    "registered": state.registry.state.registered,
                    "last_error": state.registry.state.last_error,
                },
            },
            status_code=200 if ready_state else 503,
        )

    async def scenarios(request: Request) -> Response:
        if not _authorized_control(request, state):
            return JSONResponse({"error": "unauthorized"}, status_code=401)
        if request.method == "GET":
            return JSONResponse(
                {"current": state.scenarios.current_name, "available": state.scenarios.names()}
            )
        payload = await request.json()
        try:
            selected = state.scenarios.select(str(payload["name"]))
        except (KeyError, TypeError):
            return JSONResponse({"error": "unknown scenario"}, status_code=400)
        return JSONResponse({"current": state.scenarios.current_name, "definition": selected})

    async def reset(request: Request) -> Response:
        if not _authorized_control(request, state):
            return JSONResponse({"error": "unauthorized"}, status_code=401)
        state.scenarios.reset()
        state.observations.clear()
        return JSONResponse({"status": "reset", "scenario": state.scenarios.current_name})

    async def observations(request: Request) -> Response:
        if not _authorized_control(request, state):
            return JSONResponse({"error": "unauthorized"}, status_code=401)
        if request.method == "DELETE":
            state.observations.clear()
            return JSONResponse({"status": "cleared"})
        return JSONResponse({"items": state.observations.list()})

    async def issue_jwt(request: Request) -> Response:
        agent_key = request.query_params.get("agent", "jwt")
        profile = AUTH_PROFILES.get(agent_key)
        if not profile or "jwt" not in profile.modes:
            return JSONResponse({"error": "unknown JWT agent"}, status_code=400)
        token = state.jwt.issue(profile.key, profile.hardware_id)
        return JSONResponse({"token": token, "token_type": "Bearer", "expires_in": settings.jwt_ttl_seconds})

    routes = [
        Route("/healthz", health, methods=["GET"]),
        Route("/readyz", ready, methods=["GET"]),
        Route("/__dev/jwt", issue_jwt, methods=["GET"]),
        Route("/__test/scenario", scenarios, methods=["GET", "POST"]),
        Route("/__test/reset", reset, methods=["POST"]),
        Route("/__test/observations", observations, methods=["GET", "DELETE"]),
    ]
    routes.extend(Mount(f"/{key}", app=_agent_app(settings, key, state)) for key in AUTH_PROFILES)
    app = Starlette(routes=routes, lifespan=lifespan)
    app.state.mock = state
    return app


app = create_app()
