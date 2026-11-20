# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Reconstruct the SDK analysis tools from signed tenant-scoped bindings."""

from functools import partial

from contracts.agentos import AnalysisToolBinding, EvaluationAnalysisTool, ToolBinding
from contracts.constants import environment
from fastapi import HTTPException
from nexent.core.agents.contracts.config import ToolConfig
from nexent.core.utils.observer import MessageObserver
from nexent.multi_modal.utils import is_url
from runtime.text_cleanse import RunTextCleanser

from infrastructure.agent_model_config import (
    model_record_revision,
    normalize_model_revision,
)
from infrastructure.agentos_identity import ServicePrincipal
from infrastructure.model_adapter import get_adapter_from_config
from infrastructure.object_storage.analysis_files import AnalysisFileStorage
from infrastructure.object_storage.read_access import require_s3_read_access
from infrastructure.rdb.model_records import get_model_by_model_id


def _validate_analysis_urls(urls: list[str], *, actor: ServicePrincipal) -> None:
    """Apply object ACLs to every S3 form accepted by the SDK loader."""
    local = [url.strip() for url in urls if is_url(url) == "s3"]
    require_s3_read_access(local, user_id=actor.user_id, tenant_id=actor.tenant_id)


def _analysis_adapter(kind, binding, actor, cancellation_scope=None):
    reference = binding.model
    if binding.selected_model_id and (
        reference is None or reference.model_id != binding.selected_model_id
    ):
        raise ValueError("Selected analysis model does not match its binding")
    if reference is None:
        return None
    record = get_model_by_model_id(reference.model_id, actor.tenant_id)
    if (
        not record
        or record.get("tenant_id") != actor.tenant_id
        or record.get("delete_flag") != "N"
    ):
        raise HTTPException(
            status_code=404, detail={"code": "AGENTOS_ANALYSIS_MODEL_NOT_FOUND"}
        )
    if record.get("model_type") != kind.slot or model_record_revision(
        record
    ) != normalize_model_revision(reference.revision):
        raise HTTPException(
            status_code=409, detail={"code": "AGENTOS_ANALYSIS_MODEL_REVISION_MISMATCH"}
        )
    if kind is EvaluationAnalysisTool.TEXT and cancellation_scope is not None:
        from infrastructure.model_adapter import build_adapter_fresh

        return build_adapter_fresh(
            record,
            "llm_long_context",
            kind.slot,
            actor.tenant_id,
            observer=MessageObserver(),
            cancellation_scope=cancellation_scope,
        )
    if kind is EvaluationAnalysisTool.TEXT:
        return get_adapter_from_config(
            record,
            "llm_long_context",
            kind.slot,
            actor.tenant_id,
            observer=MessageObserver(),
        )
    return get_adapter_from_config(record, "vlm", kind.slot, actor.tenant_id)


def materialize_analysis_tools(
    bindings: list[ToolBinding],
    actor: ServicePrincipal,
    *,
    run_id=None,
    cancellation_scope=None,
) -> dict[str, ToolConfig]:
    if not bindings:
        return {}

    tools = {}
    validate = partial(_validate_analysis_urls, actor=actor)
    storage = AnalysisFileStorage(
        actor, role="runtime", cancelled=cancellation_scope.stop_event if cancellation_scope is not None else None,
    )
    for binding in bindings:
        if (
            binding.version != "1"
            or binding.credential_ref is not None
            or binding.tool_id in tools
        ):
            raise ValueError("Unsupported analysis tool binding")
        kind, catalog_name = EvaluationAnalysisTool.binding_identity(binding.tool_id)
        settings = AnalysisToolBinding.model_validate(binding.parameters)
        model = _analysis_adapter(kind, settings, actor, cancellation_scope)
        metadata = {"storage_client": storage, "validate_url_access": validate}
        if kind is EvaluationAnalysisTool.TEXT:
            import httpx

            from infrastructure.agentos_client import AgentOSClient

            metadata.update(
                llm_model=model,
                text_cleanser=RunTextCleanser(
                    actor,
                    run_id,
                    AgentOSClient(
                        environment.MANAGEMENT_AGENTOS_URL,
                        lambda **kwargs: httpx.AsyncClient(trust_env=False, **kwargs),
                    ),
                    max_bytes=environment.MAX_KNOWLEDGE_FILE_SIZE_BYTES,
                ),
            )
        else:
            metadata["vlm_model"] = model
        tools[binding.tool_id] = ToolConfig(
            class_name=kind.class_name,
            name=catalog_name,
            source="local",
            usage=settings.usage,
            params={"selected_model_id": settings.selected_model_id},
            metadata=metadata,
            **settings.description.model_dump(),
        )
    return tools
