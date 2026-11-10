# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Verify evaluation skill bindings and stage the verified files for SDK tools."""

from hmac import compare_digest
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Lock
from uuid import uuid4

from fastapi import HTTPException

from contracts.agentos import EvaluationSkillTool, FileToolDescription
from infrastructure.rdb.skill_execution_records import read_bound_skills
from infrastructure.rdb.workbench_skill_records import read_workbench_skill_rows
from infrastructure.skill_execution import capture_skill_files, skill_execution_revision, skill_path_segment, validate_skill_context
from nexent.core.agents.agent_model import ToolConfig

_stage_lock = Lock()
_stage_directory: TemporaryDirectory | None = None


def skill_stage_path(workspace_path: str, *, create: bool = False) -> Path | None:
    """Keep verified skill files outside the workspace copied or mounted into sandboxes."""
    global _stage_directory
    with _stage_lock:
        if _stage_directory is None:
            if not create:
                return None
            _stage_directory = TemporaryDirectory(prefix="nexent-evaluation-skills-")
        run_path = Path(workspace_path)
        stage_directory = Path(_stage_directory.name).resolve()
        if stage_directory.is_relative_to(run_path.parent.parent.resolve()):
            if create:
                raise ValueError("Skill staging must be outside the run workspace root")
            return None
        return stage_directory / run_path.name


def materialize_skill_tools(
    resource, actor, workspace_path: str, *, publish_artifacts: bool = False,
    public_reference=None, workbench_version: int | None = None,
) -> dict[str, ToolConfig]:
    bindings = [binding for binding in resource.tools if binding.tool_id in set(EvaluationSkillTool)]
    context_items = resource.evaluation_options.context_items if resource.evaluation_options is not None else None
    workbench_refs = resource.workbench_skill_refs
    if workbench_refs and (resource.skill_refs or public_reference is None or workbench_version is None
                           or resource.origin != "SYSTEM"):
        raise ValueError("Workbench Skills require the admitted Workbench root")
    refs = workbench_refs or resource.skill_refs
    if not refs and not bindings:
        validate_skill_context(context_items, [])
        return {}
    ids = {ref.skill_id for ref in workbench_refs} if workbench_refs else {ref.instance_id for ref in refs}
    if not refs or len(ids) != len(refs) or {binding.tool_id for binding in bindings} != set(EvaluationSkillTool):
        raise ValueError("Inconsistent evaluation skill bindings")
    if len(bindings) != len(EvaluationSkillTool):
        raise ValueError("Duplicate evaluation skill tool")

    tenant = actor.tenant_id
    if workbench_refs:
        try:
            rows = read_workbench_skill_rows(
                public_reference, actor, workbench_version, resource.agent_id, resource.version_no, ids,
            )
        except ValueError as exc:
            raise HTTPException(status_code=409, detail={"code": "AGENTOS_SKILL_REVISION_MISMATCH"}) from exc
    else:
        rows = {
            row["instance_id"]: row for row in read_bound_skills(resource.agent_id, resource.version_no, tenant)
            if row["instance_id"] in ids
        }
    if rows.keys() != ids:
        raise HTTPException(status_code=404, detail={"code": "AGENTOS_SKILL_NOT_FOUND"})

    stage_root = skill_stage_path(workspace_path, create=True)
    stage = stage_root / uuid4().hex
    validate_skill_context(context_items, rows.values())
    configs = {}
    stage.mkdir(parents=True, mode=0o700)
    for ref in refs:
        row = rows[ref.skill_id if workbench_refs else ref.instance_id]
        name = row["name"]
        if name in configs:
            raise ValueError("Duplicate evaluation skill name")
        try:
            files = capture_skill_files(tenant, name)
            revision = skill_execution_revision(tenant, resource.agent_id, resource.version_no, row, files)
        except (OSError, TypeError, ValueError) as exc:
            raise HTTPException(status_code=409, detail={"code": "AGENTOS_SKILL_REVISION_MISMATCH"}) from exc
        if not compare_digest(revision, ref.revision):
            raise HTTPException(status_code=409, detail={"code": "AGENTOS_SKILL_REVISION_MISMATCH"})
        configs[name] = row["config"]
        root = stage / skill_path_segment(tenant) / skill_path_segment(name)
        for relative_path, contents in files.items():
            path = root / relative_path
            path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            path.write_bytes(contents)

    metadata = {"agent_id": resource.agent_id, "version_no": resource.version_no, "tenant_id": tenant}
    params = {"local_skills_dir": str(stage), "isolated_skills_root": True, "authorized_skill_names": sorted(configs)}
    tools = {}
    for binding in bindings:
        if binding.version != "1" or binding.credential_ref is not None:
            raise ValueError("Unsupported evaluation skill tool binding")
        builtin = EvaluationSkillTool(binding.tool_id)
        builtin_params = dict(params)
        if builtin is EvaluationSkillTool.SCRIPT:
            builtin_params["workspace_path"] = workspace_path
            if publish_artifacts:
                builtin_params["publish_file_artifacts"] = True
        if builtin is EvaluationSkillTool.CONFIG:
            builtin_params["config_overrides"] = configs
        tools[binding.tool_id] = ToolConfig(
            class_name=builtin.class_name, name=builtin.value, source="builtin", usage="builtin",
            params=builtin_params, metadata=metadata, **FileToolDescription.model_validate(binding.parameters).model_dump(),
        )
    return tools
