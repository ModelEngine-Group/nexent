# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Compile analysis tool model selections without constructing adapters."""

from contracts.agentos import AnalysisToolBinding, EvaluationAnalysisTool, FileToolDescription, RevisionedModelBinding
from infrastructure.agent_model_config import model_record_revision
from management.services.model.adapter import _fetch_slot_config
from nexent.core.agents.agent_model import ToolConfig


def prepare_analysis_tool(tool: ToolConfig, tenant_id: str) -> bool:
    kind = EvaluationAnalysisTool(tool.name)
    params = tool.params or {}
    if tool.source != "local" or tool.class_name != kind.class_name or set(params) - {"selected_model_id"}:
        return False
    selected = params.get("selected_model_id")
    if selected is not None and type(selected) not in {int, str}:
        return False
    record = _fetch_slot_config(tenant_id, selected, expected_type=kind.slot, slot_key=kind.slot)
    if record and (record.get("model_type") != kind.slot or not record.get("model_id")):
        return False
    model = RevisionedModelBinding(
        model_id=record["model_id"], revision=model_record_revision(record),
    ) if record else None
    tool.metadata = {"prepared_analysis": AnalysisToolBinding(
        description=FileToolDescription(**{
            name: getattr(tool, name) for name in FileToolDescription.model_fields
        }),
        selected_model_id=int(selected) if selected else None,
        model=model,
        usage=tool.usage,
    ).model_dump(mode="json")}
    return True
