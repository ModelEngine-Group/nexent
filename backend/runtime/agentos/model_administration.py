# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Bind explicitly supported model administration calls to Runtime."""

import logging

from fastapi import APIRouter, Request
from fastapi.encoders import jsonable_encoder
from pydantic import ValidationError
from starlette.responses import JSONResponse

from contracts.agentos import BODY_KEY, PRINCIPAL_KEY, ModelAdministrationOperation
from contracts.errors.exceptions import ModelProviderError
from contracts.model_administration import (
    ModelBatchUpdate,
    ModelHealthcheck,
    ModelProbe,
    ModelProfileProbe,
    ModelProviderDiscovery,
    ModelProviderImport,
    ModelProviderList,
    ModelRegistration,
    ModelSelection,
    ModelTenantDeactivation,
    ModelUpdate,
)
from infrastructure.rdb.model_records import deactivate_tenant_models, get_model_by_model_id
from nexent.core.concurrency import run_blocking
from runtime.model import health, registry

logger = logging.getLogger(__name__)


def _safe_result(value):
    if isinstance(value, dict):
        return {
            key: ("Model connectivity check failed" if key == "error" and item else _safe_result(item))
            for key, item in value.items()
            if key != "api_key"
        }
    if isinstance(value, list):
        return [_safe_result(item) for item in value]
    return value


_PROBE_DIAGNOSTIC_TEXT_FIELDS = (
    "category", "diagnostic_code", "message_source", "message", "scope", "request_id", "parameter",
)


def _public_probe_diagnostic(value):
    if value is None:
        return None
    diagnostic = {
        field: value[field] for field in _PROBE_DIAGNOSTIC_TEXT_FIELDS if isinstance(value.get(field), str)
    }
    http_status = value.get("http_status")
    if type(http_status) is int and 100 <= http_status <= 599:
        diagnostic["http_status"] = http_status
    messages = value.get("messages")
    if isinstance(messages, dict):
        diagnostic["messages"] = {
            locale: messages[locale] for locale in ("en", "zh") if isinstance(messages.get(locale), str)
        }
    return diagnostic


def _safe_profile_probe_result(result):
    return {"ok": result["ok"], "error": _public_probe_diagnostic(result["error"])}


def _safe_legacy_probe_result(result):
    safe = _safe_result(result)
    if "diagnostic" in result:
        safe["diagnostic"] = _public_probe_diagnostic(result["diagnostic"])
    return safe


async def _probe(payload: ModelProbe, actor):
    config = payload.model_dump(exclude={"probe_model_id"})
    if payload.probe_model_id is not None and payload.api_key in (None, "", "sk-no-api-key"):
        stored = get_model_by_model_id(payload.probe_model_id, tenant_id=actor.tenant_id)
        if (
            stored
            and stored.get("api_key")
            and (payload.base_url or "").rstrip("/") == (stored.get("base_url") or "").rstrip("/")
            and stored.get("model_type") == payload.model_type
        ):
            config.update(
                api_key=stored["api_key"],
                model_factory=stored.get("model_factory"),
                base_url=stored["base_url"],
            )
    return await health.verify_model_config_connectivity(config)


async def _deactivate_tenant(_payload: ModelTenantDeactivation, actor):
    return await run_blocking(
        "agentos-model-deactivate-tenant",
        deactivate_tenant_models,
        actor.user_id,
        actor.tenant_id,
        lane="control-io",
        owner="runtime.model",
    )


async def _profile_probe(payload, actor, request):
    from nexent.core.model_service.profiles.resolved_profile import ResolvedModelProfile
    from runtime.model.profile_probe import probe_until_disconnect

    profile = ResolvedModelProfile.model_validate(payload.profile)
    if profile.identity.tenant_id != actor.tenant_id:
        raise ValueError("Model profile tenant does not match the authenticated actor")
    return await probe_until_disconnect(profile, payload.api_key, payload.http_headers, request.is_disconnected)


def _endpoint(schema, call, *, request_aware=False, serialize=_safe_result):
    async def endpoint(request: Request):
        actor = request.scope.get(PRINCIPAL_KEY)
        if actor is None:
            return JSONResponse({"code": "AGENTOS_UNAUTHORIZED"}, status_code=401)
        try:
            payload = schema.model_validate_json(request.scope[BODY_KEY])
        except ValidationError:
            return JSONResponse({"code": "AGENTOS_INVALID_REQUEST"}, status_code=422)
        try:
            result = await call(payload, actor, request) if request_aware else await call(payload, actor)
        except LookupError:
            return JSONResponse({"code": "MODEL_NOT_FOUND"}, status_code=404)
        except ValueError:
            return JSONResponse({"code": "MODEL_INVALID_CONFIGURATION"}, status_code=400)
        except ModelProviderError as exc:
            return JSONResponse({"code": "MODEL_PROVIDER_ERROR"}, status_code=exc.upstream_status)
        except Exception as exc:
            logger.warning("AgentOS model administration failed (%s)", type(exc).__name__)
            return JSONResponse({"code": "MODEL_REQUEST_FAILED"}, status_code=502)
        return {"result": jsonable_encoder(serialize(result))}

    return endpoint


def create_model_administration_router() -> APIRouter:
    router = APIRouter()
    operations = (
        (ModelAdministrationOperation.REGISTER, ModelRegistration,
         lambda p, a: registry.create_model_for_tenant(a.user_id, a.tenant_id, p.definition())),
        (ModelAdministrationOperation.UPDATE, ModelUpdate,
         lambda p, a: registry.update_single_model_for_tenant(a.user_id, a.tenant_id, p.display_name, p.patch)),
        (ModelAdministrationOperation.DEACTIVATE, ModelSelection,
         lambda p, a: registry.delete_model_for_tenant(a.user_id, a.tenant_id, p.display_name)),
        (ModelAdministrationOperation.DEACTIVATE_TENANT, ModelTenantDeactivation, _deactivate_tenant),
        (ModelAdministrationOperation.IMPORT, ModelProviderImport,
         lambda p, a: registry.batch_create_models_for_tenant(a.user_id, a.tenant_id, p.model_dump())),
        (ModelAdministrationOperation.BATCH_UPDATE, ModelBatchUpdate,
         lambda p, a: registry.batch_update_models_for_tenant(a.user_id, a.tenant_id, p.patches)),
        (ModelAdministrationOperation.DISCOVER, ModelProviderDiscovery,
         lambda p, a: registry.create_provider_models_for_tenant(a.tenant_id, p.model_dump())),
        (ModelAdministrationOperation.LIST_PROVIDER, ModelProviderList,
         lambda p, a: registry.list_provider_models_for_tenant(a.tenant_id, p.provider, p.model_type)),
        (ModelAdministrationOperation.HEALTHCHECK, ModelHealthcheck,
         lambda p, a: health.check_model_connectivity(p.display_name, a.tenant_id, p.model_type, persist_status=p.persist_status)),
        (ModelAdministrationOperation.PROBE, ModelProbe, _probe),
    )
    for operation, schema, call in operations:
        serialize = _safe_legacy_probe_result if operation in {
            ModelAdministrationOperation.HEALTHCHECK, ModelAdministrationOperation.PROBE,
        } else _safe_result
        router.add_api_route(
            operation.value, _endpoint(schema, call, serialize=serialize), methods=["POST"],
            include_in_schema=False, name=f"model_{operation.name.lower()}",
        )
    router.add_api_route(
        ModelAdministrationOperation.PROFILE_PROBE.value,
        _endpoint(ModelProfileProbe, _profile_probe, request_aware=True, serialize=_safe_profile_probe_result),
        methods=["POST"], include_in_schema=False, name="model_profile_probe",
    )
    return router
