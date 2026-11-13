# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Bind the scheduled-task SDK tool to Management's signed AgentOS operation."""

import httpx

from contracts.agentos import AgentRunReference, ManagementOperation
from contracts.constants import environment
from infrastructure.agent_tool_config import AUTOMATION_PROPOSAL_TOOL, build_automation_proposal_tool
from infrastructure.agentos_identity import ServicePrincipal, sign_call

_TIMEOUT = httpx.Timeout(190, connect=10)


def materialize_automation_tool(resource, actor: ServicePrincipal, reference: AgentRunReference | None):
    bindings = [binding for binding in resource.tools if binding.tool_id == AUTOMATION_PROPOSAL_TOOL]
    if not bindings:
        return {}
    if (reference is None or len(bindings) != 1 or bindings[0].version != "1"
            or bindings[0].parameters or bindings[0].credential_ref is not None):
        raise ValueError("Unsupported prepared automation proposal binding")

    def create_proposal(_model_text):
        operation = ManagementOperation.AUTOMATION_PROPOSAL
        body = reference.model_dump_json().encode("utf-8")
        try:
            token = sign_call(operation, body, actor)
            with httpx.Client(timeout=_TIMEOUT, trust_env=False, follow_redirects=False) as client:
                response = client.post(
                    f"{environment.MANAGEMENT_AGENTOS_URL}/api{operation.value}", content=body,
                    headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
                )
                response.raise_for_status()
                payload = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise RuntimeError("Scheduled-task proposal service is unavailable") from exc
        if not isinstance(payload, dict) or not isinstance(payload.get("status"), str):
            raise RuntimeError("Scheduled-task proposal service returned an invalid result")
        return payload

    return {AUTOMATION_PROPOSAL_TOOL: build_automation_proposal_tool(create_proposal)}
