# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Bind a verified tool build to a single direct MCP binding of a published agent."""

from contracts.agentos import MCPExecutionBinding
from infrastructure.mcp_execution import build_mcp_tool, select_mcp_server
from infrastructure.mcp_implementations import endpoint_identity, managed_deployment
from infrastructure.rdb.mcp_execution_records import read_bound_mcp_tools, read_mcp_execution_servers
from management.db.evaluation import experiments, tool_builds as builds
from management.services.evaluation.tool_set_candidates import invalid


def verified_build(tenant, agent, version, build_id):
    from management.services.evaluation.tool_builds import verification_plan

    record = builds.build_record(tenant, build_id)
    feedback = experiments.read_handoff(tenant, record["feedback_id"]) if record else None
    if not feedback or (feedback["agent_id"], feedback["version_no"]) != (agent, version):
        invalid("Select a reviewed build for this agent version")
    manifest, plan, digest = verification_plan(tenant, build_id)
    result = builds.latest_run(tenant, build_id, digest)
    if plan["uncovered"] or not result or result["status"] != "passed":
        invalid("The reviewed MCP build must pass verification for all current callers")
    return manifest, feedback


def pin_build(spec, tenant, build_id, arm):
    resource = spec.resource
    agent, version = resource.agent_id, resource.version_no
    manifest, feedback = verified_build(tenant, agent, version, build_id)
    name, server = feedback["tool_name"], manifest["server_id"]
    matches = [tool for tool in resource.tools if tool.tool_id == "mcp" and tool.version == "1"
               and tool.parameters.get("tool_name") == name]
    rows = read_bound_mcp_tools(agent, version, tenant, [name])
    if len(matches) != 1 or len(rows) != 1:
        invalid("The reviewed MCP tool must be directly bound to the agent")
    binding, row = matches[0], rows[0]
    ref = MCPExecutionBinding.model_validate(binding.parameters)
    if (ref.instance_id, ref.server_id, ref.revision) != (
        feedback["instance_id"], server, manifest["binding_revision"]
    ):
        invalid("The MCP binding differs from the verified build")

    servers = read_mcp_execution_servers(tenant)
    _, current = select_mcp_server(servers, build_mcp_tool(row).usage, tenant)
    try:
        old, new = (managed_deployment(tenant, server, manifest[key]) for key in ("base_image", "result_image"))
        # When first adopting a versioned tool, the old production route must be its existing endpoint.
        if ref.implementation is None and (old.production != current["url"] or current.get("headers")):
            invalid("Register the current production endpoint as the original MCP build")
        if ref.implementation is not None and ref.implementation != old.pin():
            invalid("The reviewed base image is not the currently released build")
        registered = {endpoint_identity(item["mcp_server"]) for item in servers if item["mcp_server"]}
        for deployment in (old, new):
            for mode in ("development", "confirmation"):
                if endpoint_identity(getattr(deployment, mode)) in registered:
                    invalid("Reviewed MCP replay must use a dedicated test service")
        if endpoint_identity(new.production) in registered:
            invalid("The replacement MCP image must have its own production service")
        if any((getattr(deployment, mode).endswith("/sse")) != (manifest["transport"] == "sse")
               for deployment in (old, new) for mode in ("production", "development", "confirmation")):
            invalid("Deployed MCP endpoints do not match the verified transport")
    except ValueError as exc:
        invalid(str(exc))

    binding.parameters = {**binding.parameters, "implementation": (old if arm == "base" else new).pin().model_dump()}
    return spec


def build_difference(base, result):
    def refs(resource):
        return {item.parameters["instance_id"]: MCPExecutionBinding.model_validate(item.parameters)
                for item in resource.tools if item.tool_id == "mcp" and item.version == "1"}

    before, after = refs(base), refs(result)
    changed = [key for key in before if before[key] != after.get(key)]
    if before.keys() != after.keys() or len(changed) != 1:
        invalid("Exactly one directly bound MCP implementation must change")
    key, = changed
    old, new = before[key], after[key]
    if (old.implementation is None or new.implementation is None
            or old.implementation.image == new.implementation.image
            or old.model_copy(update={"implementation": new.implementation}) != new):
        invalid("The confirmed candidate changed more than the MCP implementation")
    return dict(instance_id=key, tool=old.tool_name, base=old.implementation.model_dump(),
                result=new.implementation.model_dump())
