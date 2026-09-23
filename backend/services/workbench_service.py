"""Resolve Workbench declarations into immutable, request-scoped runtime overlays."""

from __future__ import annotations

import shutil
import tempfile
from copy import deepcopy
from dataclasses import dataclass, replace
from math import isfinite
from pathlib import Path
from typing import Any, Dict, Mapping, Optional, Tuple
from nexent.core.agents.agent_model import AgentConfig

from consts.exceptions import ValidationError, WorkbenchConfigVersionConflict, WorkbenchError
from consts.const import CAN_EDIT_ALL_USER_ROLES, PERMISSION_PRIVATE
from consts.model import WorkbenchSessionConfig
from database import skill_db
from database.tool_db import query_tools_by_ids
from database.agent_db import search_agent_info_by_agent_id
from database.model_management_db import get_model_by_model_id
from management.services.agent.system_agent_provider import system_agent_provider
from management.services.model.resolver import is_model_available
from management.services.skill.service import SkillService
from management.services.skill.support import can_view_skill, _get_user_role, _to_group_id_set
from database.group_db import query_group_ids_by_user
from utils.runtime_config_utils import clone_runtime_config
from services.knowledge_scope_service import (
    ResolvedKnowledgeScope,
    get_agent_knowledge_capabilities,
    resolve_root_version,
)


@dataclass(frozen=True)
class RuntimeAgentIdentity:
    runtime_ref: str
    agent_id: int | str | None
    version_no: int | None
    invocation_name: str
    display_name: str
    origin: str


@dataclass(frozen=True)
class PublishedRootDescriptor:
    """Authorized immutable input used only by the persisted-root preparation step."""

    identity: RuntimeAgentIdentity
    published_snapshot: Mapping[str, Any]


@dataclass(frozen=True)
class RuntimeRootDescriptor:
    """Executable root contract shared by persisted and external system roots."""

    identity: RuntimeAgentIdentity
    agent_config: AgentConfig


@dataclass(frozen=True)
class RootRuntimeOverlay:
    model_id: Optional[int]
    requested_output_tokens: Optional[int]
    skill_mounts: Tuple[Mapping[str, Any], ...]
    knowledge_scope: Optional[Mapping[str, Any]]


@dataclass(frozen=True)
class ResolvedSkillMount:
    skill_id: int
    name: str
    description: str
    tool_ids: Tuple[int, ...]
    config_values: Mapping[str, Any]
    tool_definitions: Tuple[Mapping[str, Any], ...] = ()
    files: Tuple[Tuple[str, bytes], ...] = ()


@dataclass(frozen=True)
class ResolvedAgentPlan:
    root: PublishedRootDescriptor
    overlay: RootRuntimeOverlay
    root_skills: Tuple[ResolvedSkillMount, ...]
    child_mounts: Tuple[RuntimeAgentIdentity, ...] = ()
    knowledge_tree: Tuple[Mapping[str, Any], ...] = ()


@dataclass(frozen=True)
class ResolvedAgentTree:
    root: RuntimeRootDescriptor
    overlay: RootRuntimeOverlay
    root_skills: Tuple[ResolvedSkillMount, ...]
    knowledge_tree: Tuple[Mapping[str, Any], ...] = ()


class RuntimeAgentTreeComposer:
    """Compose cloned child configs into a request-scoped root."""

    def compose(
        self,
        root: AgentConfig,
        children: list[AgentConfig] | tuple[AgentConfig, ...],
    ) -> AgentConfig:
        composed = clone_runtime_config(root)
        composed.managed_agents = [clone_runtime_config(child) for child in children]
        return composed


_MAX_SKILL_SNAPSHOT_FILES = 256
_MAX_SKILL_SNAPSHOT_BYTES = 16 * 1024 * 1024


def _capture_skill_file_snapshot(
    skill_name: str,
    tenant_id: str,
) -> Tuple[Tuple[str, bytes], ...]:
    """Capture a bounded immutable file set and remove the temporary source copy."""
    loaded = SkillService(tenant_id=tenant_id).load_skill_directory(skill_name)
    directory = loaded.get("directory") if isinstance(loaded, dict) else None
    if not directory:
        raise WorkbenchError("RUNTIME_SKILL_DEPENDENCY_UNAVAILABLE")
    root = Path(directory).resolve()
    temp_root = Path(tempfile.gettempdir()).resolve()
    if (
        not root.is_relative_to(temp_root)
        or not root.name.startswith(f"skill_{skill_name}_")
    ):
        raise WorkbenchError("RUNTIME_SKILL_DEPENDENCY_UNAVAILABLE")
    files: list[Tuple[str, bytes]] = []
    total_bytes = 0
    try:
        for path in sorted(root.rglob("*")):
            if not path.is_file() or path.is_symlink():
                continue
            relative = path.resolve().relative_to(root).as_posix()
            content = path.read_bytes()
            total_bytes += len(content)
            if (
                len(files) >= _MAX_SKILL_SNAPSHOT_FILES
                or total_bytes > _MAX_SKILL_SNAPSHOT_BYTES
            ):
                raise WorkbenchError("RUNTIME_SKILL_DEPENDENCY_UNAVAILABLE")
            files.append((relative, content))
    finally:
        shutil.rmtree(root, ignore_errors=True)
    if not any(path == "SKILL.md" for path, _content in files):
        raise WorkbenchError("RUNTIME_SKILL_DEPENDENCY_UNAVAILABLE")
    return tuple(files)


def _resolve_skill_mounts(
    mounts: Tuple[Mapping[str, Any], ...],
    tenant_id: str,
    published_instances: Tuple[Mapping[str, Any], ...] = (),
    user_id: Optional[str] = None,
) -> Tuple[ResolvedSkillMount, ...]:
    if not mounts and not published_instances:
        return ()
    runtime_mounts = {int(mount["skill_id"]): mount for mount in mounts}
    effective_mounts: list[Mapping[str, Any]] = []
    seen_skill_ids: set[int] = set()
    for instance in published_instances:
        skill_id = int(instance["skill_id"])
        if skill_id in seen_skill_ids:
            continue
        seen_skill_ids.add(skill_id)
        effective_mounts.append(
            runtime_mounts.pop(
                skill_id,
                {"skill_id": skill_id, "config_values": {}},
            )
        )
    effective_mounts.extend(runtime_mounts.values())

    resolved = []
    role = _get_user_role(user_id) if user_id else None
    groups = set(query_group_ids_by_user(user_id) or []) if user_id else set()
    for mount in effective_mounts:
        skill_id = int(mount["skill_id"])
        skill = skill_db.get_skill_by_id(skill_id, tenant_id)
        if skill is None:
            raise WorkbenchError("RUNTIME_SKILL_FORBIDDEN", status_code=403)
        if user_id and not can_view_skill(skill=skill, user_id=user_id, user_role=role, user_group_ids=groups):
            raise WorkbenchError("RUNTIME_SKILL_FORBIDDEN", status_code=403)
        instance = next((item for item in published_instances if item.get("skill_id") == skill_id), {})
        config_values = resolve_skill_config(
            skill.get("config_schemas") or [],
            skill.get("config_values") or {},
            instance.get("config_values") or {},
            mount.get("config_values") or {},
        )
        resolved.append(
            ResolvedSkillMount(
                skill_id=skill_id,
                name=str(skill.get("name") or skill_id),
                description=str(skill.get("description") or ""),
                tool_ids=tuple(int(value) for value in (skill.get("tool_ids") or [])),
                config_values=config_values,
                files=_capture_skill_file_snapshot(
                    str(skill.get("name") or skill_id),
                    tenant_id,
                ),
            )
        )
    tool_ids = sorted({tool_id for skill in resolved for tool_id in skill.tool_ids})
    definitions = {int(tool["tool_id"]): deepcopy(tool) for tool in query_tools_by_ids(tool_ids)} if tool_ids else {}
    for tool_id in tool_ids:
        tool = definitions.get(tool_id)
        if not tool or tool.get("is_available") is not True or str(tool.get("author")) != tenant_id:
            raise WorkbenchError("RUNTIME_SKILL_DEPENDENCY_UNAVAILABLE")
        values: Dict[str, Any] = {}
        parameter_names = {param.get("name") for param in tool.get("params") or []}
        for skill in resolved:
            if tool_id not in skill.tool_ids:
                continue
            for name, value in skill.config_values.items():
                if name not in parameter_names:
                    continue
                if name in values and values[name] != value:
                    raise WorkbenchError("RUNTIME_SKILL_TOOL_CONFLICT")
                values[name] = value
    return tuple(replace(skill, tool_definitions=tuple(deepcopy(definitions[tool_id]) for tool_id in skill.tool_ids)) for skill in resolved)


def build_workbench_main_profile(tenant_id: str) -> Dict[str, Any]:
    """Return public presentation metadata for the tenant system root."""
    ref = system_agent_provider.get_workbench_main_ref(tenant_id)
    skills = SkillService(tenant_id=tenant_id).get_enabled_skills_for_agent(
        agent_id=ref.agent_id,
        tenant_id=tenant_id,
        version_no=ref.version_no,
    )
    return {
        "agent_id": ref.agent_id,
        "version_no": ref.version_no,
        "display_name": "Nexent Workbench",
        "default_skill_resources": [
            {
                "skill_id": int(skill["skill_id"]),
                "name": str(skill.get("name") or skill["skill_id"]),
                "description": str(skill.get("description") or ""),
            }
            for skill in skills
        ],
    }


def resolve_skill_config(schemas, defaults, published, runtime):
    """Validate declared configuration after applying the three precedence layers."""
    fields = {item["name"]: item for item in schemas if isinstance(item, dict) and item.get("name")}
    values = deepcopy(defaults)
    values.update(deepcopy(published))
    values.update(deepcopy(runtime))
    if any(name not in fields for name in runtime):
        raise WorkbenchError("RUNTIME_SKILL_CONFIG_INVALID")
    types = {
        "string": str, "boolean": bool, "integer": int,
        "number": (int, float), "object": dict, "array": list,
    }
    for name, schema in fields.items():
        value = values.get(name)
        if value is None and "default" in schema:
            value = values[name] = deepcopy(schema["default"])
        if value is None or value == "":
            if schema.get("required"):
                raise WorkbenchError("RUNTIME_SKILL_CONFIG_INVALID")
            continue
        expected = types.get(schema.get("type"))
        if expected and (not isinstance(value, expected) or (
            schema.get("type") in {"integer", "number"} and isinstance(value, bool)
        )):
            raise WorkbenchError("RUNTIME_SKILL_CONFIG_INVALID")
        if isinstance(schema.get("enum"), list) and value not in schema["enum"]:
            raise WorkbenchError("RUNTIME_SKILL_CONFIG_INVALID")
        if schema.get("type") in {"integer", "number"}:
            if not isfinite(value):
                raise WorkbenchError("RUNTIME_SKILL_CONFIG_INVALID")
            if schema.get("minimum") is not None and value < schema["minimum"]:
                raise WorkbenchError("RUNTIME_SKILL_CONFIG_INVALID")
            if schema.get("maximum") is not None and value > schema["maximum"]:
                raise WorkbenchError("RUNTIME_SKILL_CONFIG_INVALID")
    return values


class RuntimeMountService:
    """Compile an already-authorized executable root without repository access."""

    def resolve_knowledge(
        self,
        tree: ResolvedAgentTree,
        *,
        tenant_id: str,
        user_id: str,
    ) -> tuple[ResolvedAgentTree, ResolvedKnowledgeScope]:
        """Resolve resource access for an executable root without loading Agent records.

        Callers consume the returned tree and scope summary before starting a
        model. Resource checks are separate from the pure root compilation.
        """
        from consts.model import ConversationKnowledgeScopeRequest
        from services.knowledge_scope_service import resolve_executable_knowledge_scope

        scope = ConversationKnowledgeScopeRequest.model_validate(dict(tree.overlay.knowledge_scope or {}))
        compiled, resolution = resolve_executable_knowledge_scope(
            tree.root.agent_config, scope, tenant_id=tenant_id, user_id=user_id,
        )
        return replace(tree, root=replace(tree.root, agent_config=compiled)), resolution

    def resolve_root(
        self,
        root: RuntimeRootDescriptor,
        overlay: RootRuntimeOverlay,
        *,
        resolved_skills: Tuple[ResolvedSkillMount, ...] = (),
        knowledge_tree: Tuple[Mapping[str, Any], ...] = (),
    ) -> ResolvedAgentTree:
        agent_config = clone_runtime_config(root.agent_config)
        identity = root.identity
        agent_config.agent_id = identity.agent_id
        agent_config.version_no = identity.version_no
        agent_config.invocation_name = identity.invocation_name
        agent_config.runtime_ref = identity.runtime_ref
        agent_config.display_name = identity.display_name
        agent_config.origin = identity.origin
        return ResolvedAgentTree(
            root=RuntimeRootDescriptor(
                identity=identity,
                agent_config=agent_config,
            ),
            overlay=RootRuntimeOverlay(
                model_id=overlay.model_id,
                requested_output_tokens=overlay.requested_output_tokens,
                skill_mounts=tuple(deepcopy(dict(item)) for item in overlay.skill_mounts),
                knowledge_scope=(
                    deepcopy(dict(overlay.knowledge_scope))
                    if overlay.knowledge_scope is not None
                    else None
                ),
            ),
            root_skills=tuple(deepcopy(resolved_skills)),
            knowledge_tree=tuple(deepcopy(knowledge_tree)),
        )


def compile_runtime_mount_plan(
    plan: ResolvedAgentPlan,
    agent_config: AgentConfig,
) -> ResolvedAgentTree:
    """Compile one request-local executable tree from the authorized plan."""
    return RuntimeMountService().resolve_root(
        RuntimeRootDescriptor(identity=plan.root.identity, agent_config=agent_config),
        plan.overlay,
        resolved_skills=plan.root_skills,
        knowledge_tree=plan.knowledge_tree,
    )


def attach_runtime_knowledge_tree(
    plan: ResolvedAgentPlan,
    knowledge_tree: list[Mapping[str, Any]],
) -> ResolvedAgentPlan:
    """Return a plan carrying the immutable knowledge projection for this run."""
    return replace(
        plan,
        knowledge_tree=tuple(deepcopy(dict(node)) for node in knowledge_tree),
    )


def resolve_workbench_config(
    config: WorkbenchSessionConfig,
    *,
    tenant_id: str,
    is_debug: bool = False,
    user_id: Optional[str] = None,
) -> tuple[WorkbenchSessionConfig, ResolvedAgentPlan]:
    """Lock the root version and compile the canonical Workbench declaration."""

    if config.mode in {"skill_create", "agent_create"}:
        raise WorkbenchError("WORKBENCH_MODE_RESOURCE_CONFLICT")
    canonical_payload = config.model_dump(mode="json")
    child_identities: list[RuntimeAgentIdentity] = []
    for index, mount in enumerate(config.agent_mounts):
        resolved_version = resolve_root_version(
            mount.agent_id,
            tenant_id,
            mount.version_no,
            is_debug,
        )
        if not is_debug and resolved_version <= 0:
            raise WorkbenchError("AGENT_VERSION_UNAVAILABLE")
        try:
            selected_snapshot = deepcopy(
                search_agent_info_by_agent_id(
                    mount.agent_id, tenant_id, resolved_version
                )
            )
        except ValueError as exc:
            raise WorkbenchError("AGENT_VERSION_UNAVAILABLE") from exc
        if user_id:
            authorize_workbench_agent(selected_snapshot, user_id)
        if selected_snapshot.get("enabled") is False:
            raise WorkbenchError("AGENT_NOT_RUNNABLE")
        if selected_snapshot.get("system_key") is not None:
            raise WorkbenchError("AGENT_NOT_RUNNABLE", status_code=403)
        canonical_payload["agent_mounts"][index]["version_no"] = resolved_version
        child_identities.append(
            RuntimeAgentIdentity(
                runtime_ref=f"agent:{mount.agent_id}:v{resolved_version}",
                agent_id=mount.agent_id,
                version_no=resolved_version,
                invocation_name=f"agent_{mount.agent_id}_v{resolved_version}",
                display_name=str(
                    selected_snapshot.get("display_name")
                    or selected_snapshot.get("name")
                    or mount.agent_id
                ),
                origin="PERSISTED",
            )
        )

    canonical = WorkbenchSessionConfig.model_validate(canonical_payload)
    try:
        system_ref = system_agent_provider.get_workbench_main_ref(tenant_id)
        snapshot = deepcopy(
            search_agent_info_by_agent_id(
                system_ref.agent_id,
                tenant_id,
                system_ref.version_no,
            )
        )
    except Exception as exc:
        raise WorkbenchError("WORKBENCH_SYSTEM_AGENT_UNAVAILABLE", status_code=503) from exc
    if snapshot.get("enabled") is False:
        raise WorkbenchError("WORKBENCH_SYSTEM_AGENT_UNAVAILABLE", status_code=503)
    root_identity = RuntimeAgentIdentity(
        runtime_ref=f"agent:{system_ref.agent_id}:v{system_ref.version_no}",
        agent_id=system_ref.agent_id,
        version_no=system_ref.version_no,
        invocation_name="workbench_main",
        display_name=str(
            snapshot.get("display_name")
            or snapshot.get("name")
            or "Nexent Workbench"
        ),
        origin="SYSTEM",
    )
    child_mounts = tuple(child_identities)
    if canonical.model_id is not None:
        model_info = get_model_by_model_id(
            canonical.model_id, tenant_id=tenant_id
        )
        if not is_model_available(model_info):
            raise WorkbenchError("WORKBENCH_MODEL_NOT_ALLOWED")

    snapshot["skill_instances"] = skill_db.search_skills_for_agent(
        agent_id=int(root_identity.agent_id),
        tenant_id=tenant_id,
        version_no=int(root_identity.version_no),
    )
    generation = canonical.generation_config
    root = PublishedRootDescriptor(
        identity=root_identity,
        published_snapshot=deepcopy(snapshot),
    )
    overlay = RootRuntimeOverlay(
        model_id=canonical.model_id,
        requested_output_tokens=generation.requested_output_tokens,
        skill_mounts=tuple(
            value.model_dump(mode="json") for value in canonical.skill_mounts
        ),
        knowledge_scope=(
            canonical.knowledge_scope.model_dump(mode="json")
            if canonical.knowledge_scope is not None
            else None
        ),
    )
    return canonical, ResolvedAgentPlan(
        root=root,
        overlay=overlay,
        root_skills=_resolve_skill_mounts(
            overlay.skill_mounts, tenant_id,
            tuple(root.published_snapshot.get("skill_instances") or []),
            user_id=user_id,
        ),
        child_mounts=child_mounts,
    )


def authorize_workbench_agent(snapshot: Mapping[str, Any], user_id: str) -> None:
    """Apply the Agent list's creator/group visibility rules before resolving resources."""
    role = _get_user_role(user_id)
    if role in CAN_EDIT_ALL_USER_ROLES or str(snapshot.get("created_by")) == str(user_id):
        return
    groups = set(query_group_ids_by_user(user_id) or [])
    if snapshot.get("ingroup_permission") == PERMISSION_PRIVATE or not groups.intersection(_to_group_id_set(snapshot.get("group_ids"))):
        raise WorkbenchError("AGENT_NOT_RUNNABLE", status_code=403)


def build_workbench_capability_preview(
    *,
    agent_id: int,
    version_no: Optional[int],
    tenant_id: str,
    user_id: str,
) -> Dict[str, Any]:
    locked_version = resolve_root_version(agent_id, tenant_id, version_no, False)
    if locked_version <= 0:
        raise WorkbenchError("AGENT_VERSION_UNAVAILABLE")
    try:
        snapshot = search_agent_info_by_agent_id(agent_id, tenant_id, locked_version)
    except ValueError as exc:
        raise WorkbenchError("AGENT_VERSION_UNAVAILABLE") from exc
    authorize_workbench_agent(snapshot, user_id)
    if snapshot.get("enabled") is False:
        raise WorkbenchError("AGENT_NOT_RUNNABLE")
    capabilities = get_agent_knowledge_capabilities(
        agent_id=agent_id,
        tenant_id=tenant_id,
        version_no=locked_version,
        user_id=user_id,
    )
    locked_version = int(capabilities["version_no"])
    if locked_version <= 0:
        raise ValidationError("The selected Agent has no published version")
    default_skills = SkillService(tenant_id=tenant_id).get_enabled_skills_for_agent(
        agent_id=agent_id,
        tenant_id=tenant_id,
        version_no=locked_version,
    )
    role = _get_user_role(user_id)
    groups = set(query_group_ids_by_user(user_id) or [])
    for skill in default_skills:
        authorized_skill = skill_db.get_skill_by_id(int(skill["skill_id"]), tenant_id)
        if not authorized_skill or not can_view_skill(
            skill=authorized_skill,
            user_id=user_id,
            user_role=role,
            user_group_ids=groups,
        ):
            raise WorkbenchError("RUNTIME_SKILL_FORBIDDEN", status_code=403)
    return {
        "agent_id": int(agent_id),
        "version_no": locked_version,
        "default_skill_mounts": [
            {
                "skill_id": int(skill["skill_id"]),
                "config_values": deepcopy(skill.get("config_values") or {}),
            }
            for skill in default_skills
        ],
        "default_skill_resources": [
            {
                "skill_id": int(skill["skill_id"]),
                "name": str(skill.get("name") or skill["skill_id"]),
                "description": str(skill.get("description") or ""),
            }
            for skill in default_skills
        ],
        "knowledge": capabilities,
    }


def assert_workbench_version(
    conversation: Mapping[str, Any],
    expected_version: Optional[int],
) -> None:
    current_version = int(conversation.get("workbench_config_version") or 0)
    if expected_version is None or int(expected_version) != current_version:
        raise WorkbenchConfigVersionConflict(
            current_version,
            deepcopy(conversation.get("workbench_config")),
        )


def runtime_skill_snapshot(tree: ResolvedAgentPlan | ResolvedAgentTree) -> list[Dict[str, Any]]:
    return [
        {
            "skill_id": skill.skill_id,
            "name": skill.name,
            "description": skill.description,
            "tool_ids": list(skill.tool_ids),
            "config_values": deepcopy(dict(skill.config_values)),
            "tool_definitions": [deepcopy(dict(tool)) for tool in skill.tool_definitions],
            "files": [(path, bytes(content)) for path, content in skill.files],
        }
        for skill in tree.root_skills
    ]
