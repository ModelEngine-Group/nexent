# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Management wrappers for model commands and tenant default bindings."""

import json

from backend.http.client import create_httpx_client
from contracts.agentos import ModelAdministrationOperation as Operation
from contracts.constants.environment import RUNTIME_SERVICE_URL
from contracts.errors.exceptions import ModelProviderError, RuntimeUpstreamError
from contracts.model_administration import (
    ModelBatchUpdate,
    ModelHealthcheck,
    ModelProbe,
    ModelProviderDiscovery,
    ModelProviderImport,
    ModelProviderList,
    ModelRegistration,
    ModelSelection,
    ModelUpdate,
)
from management.clients.agentos import AgentOSClient
from management.services.model.management import _backfill_default_model_slots
from nexent.core.concurrency import run_blocking


async def _command(operation, payload, user_id, tenant_id):
    client = AgentOSClient(RUNTIME_SERVICE_URL, create_httpx_client)
    try:
        return await client.model_command(operation, payload, user_id, tenant_id)
    except RuntimeUpstreamError as exc:
        try:
            error = json.loads(exc.content)
        except (ValueError, UnicodeError):
            error = None
        if isinstance(error, dict) and error.get("code") == "MODEL_PROVIDER_ERROR":
            raise ModelProviderError(exc.status_code, "Provider model request failed") from exc
        if exc.status_code == 404:
            raise LookupError("Model configuration not found") from exc
        if exc.status_code in (400, 422):
            raise ValueError("Invalid or conflicting model configuration") from exc
        raise


async def _default_bindings(user_id, tenant_id, created_ids):
    return await run_blocking(
        "model-default-bindings",
        _backfill_default_model_slots,
        user_id,
        tenant_id,
        new_model_ids=set(created_ids),
        lane="control-io",
        owner="management",
    )


async def create_model_for_tenant(user_id, tenant_id, model_data, skip_default_backfill=False):
    created_ids = await _command(Operation.REGISTER, ModelRegistration(**model_data), user_id, tenant_id)
    bindings = [] if skip_default_backfill else await _default_bindings(user_id, tenant_id, created_ids)
    return {"auto_configured_defaults": bindings}


async def batch_create_models_for_tenant(user_id, tenant_id, batch):
    created_ids = await _command(Operation.IMPORT, ModelProviderImport(**batch), user_id, tenant_id)
    return {"auto_configured_defaults": await _default_bindings(user_id, tenant_id, created_ids)}


async def update_single_model_for_tenant(user_id, tenant_id, display_name, model_data):
    await _command(Operation.UPDATE, ModelUpdate(display_name=display_name, patch=model_data), user_id, tenant_id)


async def batch_update_models_for_tenant(user_id, tenant_id, model_list):
    await _command(Operation.BATCH_UPDATE, ModelBatchUpdate(patches=model_list), user_id, tenant_id)


async def delete_model_for_tenant(user_id, tenant_id, display_name):
    return await _command(Operation.DEACTIVATE, ModelSelection(display_name=display_name), user_id, tenant_id)


async def create_provider_models_for_tenant(tenant_id, provider_request, *, user_id):
    payload = ModelProviderDiscovery(**provider_request)
    return await _command(Operation.DISCOVER, payload, user_id, tenant_id)


async def list_provider_models_for_tenant(tenant_id, provider, model_type, *, user_id):
    payload = ModelProviderList(provider=provider, model_type=model_type)
    return await _command(Operation.LIST_PROVIDER, payload, user_id, tenant_id)


async def check_model_connectivity(display_name, tenant_id, model_type=None, *, user_id):
    payload = ModelHealthcheck(display_name=display_name, model_type=model_type)
    return await _command(Operation.HEALTHCHECK, payload, user_id, tenant_id)


async def verify_model_config_connectivity(model_config, *, user_id, tenant_id):
    return await _command(Operation.PROBE, ModelProbe(**model_config), user_id, tenant_id)
