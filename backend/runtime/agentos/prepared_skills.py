# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Verify evaluation skill bindings and stage the verified files for SDK tools."""

from hmac import compare_digest
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Lock
from uuid import uuid4

from fastapi import HTTPException

from contracts.agentos import EvaluationSkillTool, FileToolDescription, WorkbenchDebugSkillLookup, WorkbenchSkillLookup
from infrastructure.rdb import skill_candidate_records
from infrastructure.rdb.skill_execution_records import read_bound_skills
from infrastructure.rdb.workbench_skill_records import read_workbench_skill_rows
from infrastructure.skill_execution import capture_skill_files, skill_execution_revision, skill_path_segment, validate_skill_context
from nexent.core.agents.contracts.config import ToolConfig
from runtime.agentos.prepared_workbench import fetch_workbench_skill_mounts

_stage_lock = Lock()
_stage_directory: TemporaryDirectory | None = None


def root_without_target_skill(resource, actor, candidate_id):
    bound = skill_candidate_records.read_bound_skill_candidate(actor.tenant_id, resource.agent_id, resource.version_no, candidate_id)
    target = [ref for ref in resource.skill_refs if ref.package_candidate_id == candidate_id]
    if (not bound or resource.workbench_skill_refs or len(target) != 1 or target[0].package_variant != "base"
            or target[0].instance_id != bound["instance_id"] or resource.evaluation_options is None):
        raise ValueError("The control requires a pinned baseline Skill on the root Agent")
    remaining = [ref for ref in resource.skill_refs if ref.instance_id != bound["instance_id"]]
    removed_tools = set() if remaining else set(EvaluationSkillTool)
    tools = [binding for binding in resource.tools if binding.tool_id not in removed_tools]
    items = []
    for item in resource.evaluation_options.context_items or ():
        content = item.get("content")
        if isinstance(content, dict) and (
            (item.get("type") == "skill" and content.get("name") == bound["skill_name"])
            or (item.get("type") == "tool" and content.get("name") in removed_tools)
        ):
            continue
        items.append(item)
    options = resource.evaluation_options.model_copy(update={"context_items": items})
    return resource.model_copy(update={"skill_refs": remaining, "tools": tools, "evaluation_options": options})


def skill_trial_observation(payload, info, actor):
    """Inspect the mounted root Agent after Runtime has built its executable tools."""
    from contracts.agentos import SkillTrialObservation

    refs = [ref for ref in payload.resource.skill_refs if ref.package_candidate_id is not None]
    if not refs:
        return None, None
    if len(refs) != 1:
        raise ValueError("Expected one target Skill for a single-resource trial")
    ref = refs[0]
    bound = skill_candidate_records.read_bound_skill_candidate(actor.tenant_id, payload.resource.agent_id,
                                                              payload.resource.version_no, ref.package_candidate_id)
    if not bound or bound["instance_id"] != ref.instance_id:
        raise ValueError("Skill trial binding is no longer available")
    name = bound["skill_name"]
    config = info.agent_config
    listed = any(item.type == "skill" and item.content.get("name") == name for item in config.context_items or [])
    reader = next((t for t in config.tools if t.name == EvaluationSkillTool.GUIDE), None)
    path = None
    if reader:
        path = Path(reader.params["local_skills_dir"]) / skill_path_segment(actor.tenant_id) / skill_path_segment(name) / "SKILL.md"
        if path.is_file() != (name in reader.params["authorized_skill_names"]):
            raise ValueError("Skill reader permissions do not match the staged guide")
        if not path.is_file():
            path = None
    omitted = payload.omit_root_skill_candidate_id is not None
    if omitted == (path is not None) or (omitted and listed):
        raise ValueError("Mounted Skill does not match the trial arm")
    return SkillTrialObservation(candidate_id=ref.package_candidate_id, instance_id=ref.instance_id,
                                variant="no_skill" if omitted else ref.package_variant, listed=listed,
                                mounted_revision=None if omitted else ref.revision, guide_reads=0), path


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
    debug_run_id: str | None = None,
) -> tuple[dict[str, ToolConfig], list[dict]]:
    bindings = [binding for binding in resource.tools if binding.tool_id in set(EvaluationSkillTool)]
    context_items = resource.evaluation_options.context_items if resource.evaluation_options is not None else None
    workbench_refs = resource.workbench_skill_refs
    persisted_scope = public_reference is not None and workbench_version is not None
    if workbench_refs and (resource.skill_refs or not (persisted_scope or debug_run_id) or resource.origin != "SYSTEM"):
        raise ValueError("Workbench Skills require the admitted Workbench root")
    refs = workbench_refs or resource.skill_refs
    if not refs and not bindings:
        validate_skill_context(context_items, [])
        return {}, []
    ids = {ref.skill_id for ref in workbench_refs} if workbench_refs else {ref.instance_id for ref in refs}
    if not refs or len(ids) != len(refs) or {binding.tool_id for binding in bindings} != set(EvaluationSkillTool):
        raise ValueError("Inconsistent evaluation skill bindings")
    if len(bindings) != len(EvaluationSkillTool):
        raise ValueError("Duplicate evaluation skill tool")

    tenant = actor.tenant_id
    if workbench_refs:
        try:
            root = {"agent_id": resource.agent_id, "agent_version": resource.version_no}
            if debug_run_id is not None:
                lookup = WorkbenchDebugSkillLookup(run_id=debug_run_id, **root)
            else:
                lookup = WorkbenchSkillLookup(
                    **public_reference.model_dump(), **root, workbench_version=workbench_version,
                )
            mounts = fetch_workbench_skill_mounts(lookup, actor)
            rows = read_workbench_skill_rows(resource.agent_id, resource.version_no, actor, mounts, ids)
        except ValueError as exc:
            raise HTTPException(status_code=409, detail={"code": "AGENTOS_SKILL_REVISION_MISMATCH"}) from exc
    else:
        rows = {
            row["instance_id"]: row for row in read_bound_skills(resource.agent_id, resource.version_no, tenant)
            if row["instance_id"] in ids
        }
    if rows.keys() != ids:
        raise HTTPException(status_code=404, detail={"code": "AGENTOS_SKILL_NOT_FOUND"})

    if len({row["name"] for row in rows.values()}) != len(rows):
        raise ValueError("Duplicate evaluation skill name")
    validate_skill_context(context_items, rows.values())
    stage_root = skill_stage_path(workspace_path, create=True)
    stage = stage_root / uuid4().hex
    configs = {}
    stage.mkdir(parents=True, mode=0o700)
    for ref in refs:
        row = rows[ref.skill_id if workbench_refs else ref.instance_id]
        name = row["name"]
        try:
            revision_row = dict(row)
            owner = revision_row.pop("owner_tenant_id") if workbench_refs else tenant
            candidate = getattr(ref, "package_candidate_id", None)
            if candidate is None:
                files = capture_skill_files(owner, name)
            else:
                from infrastructure.skill_package import load_skill_package

                bound = skill_candidate_records.read_bound_skill_candidate(tenant, resource.agent_id, resource.version_no, candidate)
                if not bound or bound["instance_id"] != ref.instance_id:
                    raise ValueError("Skill candidate is outside the Agent binding")
                files = load_skill_package(tenant, bound["skill_id"], bound[ref.package_variant + "_digest"])
            revision = skill_execution_revision(tenant, resource.agent_id, resource.version_no, revision_row, files)
        except (KeyError, OSError, TypeError, ValueError) as exc:
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
    return tools, list(rows.values()) if workbench_refs else []
