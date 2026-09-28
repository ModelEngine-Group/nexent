"""Provision and resolve platform-owned system Agents."""

import logging
from dataclasses import dataclass
from typing import Any

from packaging.version import InvalidVersion, Version
from sqlalchemy.exc import IntegrityError

from consts.const import APP_VERSION, ENABLE_AIDP_KNOWLEDGE, LANGUAGE
from consts.exceptions import WorkbenchAgentError
from consts.model import AgentInfoRequest, ToolInstanceInfoRequest
from database import skill_db
from database.agent_db import (
    clear_agent_new_mark,
    create_agent,
    search_system_agent,
    update_agent,
    update_system_agent_revision,
)
from database.skill_db import delete_skills_by_agent_id
from database.tool_db import (
    create_or_update_tool_by_tool_info,
    delete_tools_by_agent_id,
    query_all_tools,
    query_tool_instances_by_agent_id,
)
from services.agent_version_service import publish_version_impl
from services.prompt_template_service import (
    SYSTEM_PROMPT_TEMPLATE_ID,
    SYSTEM_PROMPT_TEMPLATE_NAME,
)
from management.services.skill.service import install_skills_from_zip_for_tenant
from utils.prompt_template_utils import get_prompt_template

logger = logging.getLogger(__name__)

WORKBENCH_MAIN_SYSTEM_KEY = "workbench_main"
WORKBENCH_MAIN_NAME = "workbench_main"
WORKBENCH_MAIN_DISPLAY_NAME = "Nexent Workbench"
SYSTEM_AGENT_USER_ID = "system"
WORKBENCH_OFFICIAL_SKILL_NAMES = (
    "docx",
    "pdf",
    "pptx",
    "xlsx",
    "canvas-design",
    "analyze-image",
)


@dataclass(frozen=True)
class SystemAgentRef:
    """Immutable reference to one published system Agent snapshot."""

    tenant_id: str
    system_key: str
    agent_id: int
    version_no: int


@dataclass(frozen=True)
class WorkbenchReleaseManifest:
    """Server-controlled capabilities for one Nexent release."""

    system_revision: str
    persistent_tool_names: tuple[str, ...]
    official_skill_names: tuple[str, ...] = WORKBENCH_OFFICIAL_SKILL_NAMES


class SystemAgentProvider:
    """Provide the protected tenant-scoped workbench root Agent."""

    system_key = WORKBENCH_MAIN_SYSTEM_KEY

    def __init__(
        self,
        *,
        app_version: str | None = None,
        aidp_enabled: bool | None = None,
    ):
        revision = str(app_version if app_version is not None else APP_VERSION).strip()
        if not revision:
            raise ValueError("app_version is required")
        use_aidp = ENABLE_AIDP_KNOWLEDGE if aidp_enabled is None else aidp_enabled
        self.release_manifest = WorkbenchReleaseManifest(
            system_revision=revision,
            persistent_tool_names=(
                "aidp_search" if use_aidp else "knowledge_base_search",
            ),
        )

    @staticmethod
    def get_system_prompt(language: str) -> str:
        """Return the localized runtime prompt for the workbench root."""
        template_language = (
            LANGUAGE["EN"] if language == LANGUAGE["EN"] else LANGUAGE["ZH"]
        )
        return str(
            get_prompt_template("workbench_main", template_language).get(
                "system_prompt", ""
            )
        )

    def get_workbench_main_ref(self, tenant_id: str) -> SystemAgentRef:
        """Resolve the current published system Agent without mutating state."""
        self._validate_tenant_id(tenant_id)
        draft = search_system_agent(tenant_id, self.system_key)
        if draft is None:
            raise WorkbenchAgentError("system_agent_not_ready", retryable=True)
        return self._resolve_published_ref(tenant_id, draft)

    def ensure_workbench_main(
        self,
        tenant_id: str,
        user_id: str | None = None,
        locale: str | None = None,
    ) -> SystemAgentRef:
        """Initialize or release-upgrade the tenant workbench root Agent."""
        self._validate_tenant_id(tenant_id)
        actor = user_id or SYSTEM_AGENT_USER_ID
        existing = search_system_agent(tenant_id, self.system_key, version_no=0)
        if existing is None:
            self._create_draft(tenant_id, actor, locale=locale)
            existing = search_system_agent(tenant_id, self.system_key, version_no=0)
            if existing is None:
                raise WorkbenchAgentError(
                    "system_agent_not_ready",
                    retryable=True,
                    message="workbench_main draft was not created",
                )

        current_version = existing.get("current_version_no")
        current_revision = existing.get("system_revision")
        if current_version and current_revision == self.release_manifest.system_revision:
            if not self._release_state_matches(existing, tenant_id, locale=locale):
                logger.error(
                    "Detected same-revision workbench Agent drift for tenant %s",
                    tenant_id,
                )
                raise WorkbenchAgentError("system_agent_drift_detected")
            return self._resolve_published_ref(tenant_id, existing)
        if (
            current_version
            and current_revision
            and not self._is_newer_release(str(current_revision))
        ):
            raise WorkbenchAgentError(
                "system_agent_revision_ahead",
                message=(
                    "Stored system revision is not older than the running "
                    "Nexent release"
                ),
            )

        try:
            official_skills = self._prepare_official_skills(tenant_id, actor)
            self._replace_release_capabilities(
                agent_id=int(existing["agent_id"]),
                tenant_id=tenant_id,
                actor=actor,
                official_skills=official_skills,
            )
            update_agent(
                existing["agent_id"],
                AgentInfoRequest(**self._editable_fields(locale)),
                actor,
                version_no=0,
                allow_system=True,
            )
            published = publish_version_impl(
                agent_id=existing["agent_id"],
                tenant_id=tenant_id,
                user_id=actor,
                version_name="System",
                release_note=(
                    "Apply Nexent workbench system revision "
                    f"{self.release_manifest.system_revision}"
                ),
                allow_system=True,
            )
            update_system_agent_revision(
                agent_id=int(existing["agent_id"]),
                tenant_id=tenant_id,
                system_revision=self.release_manifest.system_revision,
                user_id=actor,
            )
        except WorkbenchAgentError:
            raise
        except Exception as exc:  # noqa: BLE001 - optional capability import is best effort
            raise WorkbenchAgentError(
                "system_agent_not_ready",
                retryable=True,
                message=str(exc),
            ) from exc

        resolved = search_system_agent(tenant_id, self.system_key, version_no=0)
        if resolved is None:
            raise WorkbenchAgentError("system_agent_not_ready", retryable=True)
        if not resolved.get("current_version_no") and isinstance(published, dict):
            resolved["current_version_no"] = published.get("version_no")
        return self._resolve_published_ref(tenant_id, resolved)

    def _create_draft(
        self,
        tenant_id: str,
        actor: str,
        *,
        locale: str | None = None,
    ) -> dict[str, Any]:
        payload = {
            **self._editable_fields(locale),
            "system_key": self.system_key,
            "agent_origin": "SYSTEM",
            "system_revision": None,
            "model_ids": [],
            "prompt_template_id": SYSTEM_PROMPT_TEMPLATE_ID,
            "prompt_template_name": SYSTEM_PROMPT_TEMPLATE_NAME,
            "group_ids": "",
            "ingroup_permission": "PRIVATE",
            "is_new": False,
        }
        try:
            created = create_agent(payload, tenant_id=tenant_id, user_id=actor)
            clear_agent_new_mark(created["agent_id"], tenant_id, actor)
            return created
        except IntegrityError:
            concurrent = search_system_agent(
                tenant_id, self.system_key, version_no=0
            )
            if concurrent is not None:
                logger.info(
                    "Reused concurrently provisioned workbench Agent for tenant %s",
                    tenant_id,
                )
                return concurrent
            raise

    def _prepare_official_skills(
        self,
        tenant_id: str,
        actor: str,
    ) -> list[dict[str, Any]]:
        required_names = self.release_manifest.official_skill_names
        try:
            installed_names = list(
                install_skills_from_zip_for_tenant(
                    skill_names=list(required_names),
                    tenant_id=tenant_id,
                    user_id=actor,
                )
            )
        except Exception as exc:
            installed_names = []
            logger.warning(
                "Official Skill import failed for workbench Agent in tenant %s; "
                "continuing with already available official Skills: %s",
                tenant_id,
                exc,
            )

        resolved: list[dict[str, Any]] = []
        for skill_name in required_names:
            prefix = f"{skill_name}_"
            aliases = sorted(
                (
                    name
                    for name in installed_names
                    if name.startswith(prefix) and name[len(prefix):].isdigit()
                ),
                key=lambda name: int(name[len(prefix):]),
            )
            candidates = [skill_name, *aliases]
            skill = None
            for candidate in candidates:
                candidate_skill = skill_db.get_skill_by_name(candidate, tenant_id)
                if not candidate_skill:
                    continue
                if str(candidate_skill.get("source") or "").casefold() == "official":
                    skill = candidate_skill
                    break
                logger.warning(
                    "Preserving non-official Skill '%s' in tenant %s while "
                    "resolving official workbench capability '%s'",
                    candidate,
                    tenant_id,
                    skill_name,
                )
            if skill is None:
                logger.warning(
                    "Official Skill '%s' is unavailable for workbench Agent in "
                    "tenant %s; bootstrap will continue without it (imported=%s)",
                    skill_name,
                    tenant_id,
                    skill_name in installed_names,
                )
                continue
            resolved.append(skill)
        return resolved

    def _replace_release_capabilities(
        self,
        *,
        agent_id: int,
        tenant_id: str,
        actor: str,
        official_skills: list[dict[str, Any]],
    ) -> None:
        """Replace the protected draft capability set for a release upgrade."""
        selected_name = self.release_manifest.persistent_tool_names[0]
        selected_tool = self._find_available_tool(
            selected_name,
            tenant_id,
            required=False,
        )

        delete_tools_by_agent_id(
            agent_id,
            tenant_id,
            actor,
            version_no=0,
            allow_system=True,
        )
        if selected_tool is not None:
            params = (
                {"index_names": []}
                if selected_name == "knowledge_base_search"
                else {}
            )
            create_or_update_tool_by_tool_info(
                ToolInstanceInfoRequest(
                    tool_id=int(selected_tool["tool_id"]),
                    agent_id=agent_id,
                    params=params,
                    enabled=True,
                ),
                tenant_id=tenant_id,
                user_id=actor,
                version_no=0,
                allow_system=True,
            )
        else:
            logger.warning(
                "Tool '%s' is unavailable for workbench Agent in tenant %s; "
                "bootstrap will continue without it",
                selected_name,
                tenant_id,
            )

        delete_skills_by_agent_id(
            agent_id,
            tenant_id,
            actor,
            version_no=0,
            allow_system=True,
        )
        for skill in official_skills:
            skill_db.create_or_update_skill_by_skill_info(
                {
                    "skill_id": int(skill["skill_id"]),
                    "agent_id": agent_id,
                    "enabled": True,
                    "config_values": {},
                },
                tenant_id=tenant_id,
                user_id=actor,
                version_no=0,
                allow_system=True,
            )

    def _release_state_matches(
        self,
        existing: dict[str, Any],
        tenant_id: str,
        *,
        locale: str | None = None,
    ) -> bool:
        if any(
            existing.get(key) != value
            for key, value in self._editable_fields(locale).items()
        ):
            return False

        expected_tool = self._find_available_tool(
            self.release_manifest.persistent_tool_names[0],
            tenant_id,
            required=False,
        )
        enabled_tool_ids = {
            int(item["tool_id"])
            for item in query_tool_instances_by_agent_id(
                int(existing["agent_id"]), tenant_id, version_no=0
            )
            if item.get("enabled") is True and item.get("tool_id") is not None
        }
        allowed_tool_ids = (
            {int(expected_tool["tool_id"])} if expected_tool is not None else set()
        )
        if not enabled_tool_ids.issubset(allowed_tool_ids):
            return False

        enabled_skill_ids = [
            int(item["skill_id"])
            for item in skill_db.query_skill_instances_by_agent_id(
                int(existing["agent_id"]), tenant_id, version_no=0
            )
            if item.get("enabled") is True and item.get("skill_id") is not None
        ]
        resolved_bases: set[str] = set()
        for skill_id in enabled_skill_ids:
            skill = skill_db.get_skill_by_id(skill_id, tenant_id)
            if not skill or str(skill.get("source") or "").casefold() != "official":
                return False
            skill_name = str(skill.get("name") or skill.get("skill_name") or "")
            base_name = self._official_skill_base_name(skill_name)
            if base_name is None or base_name in resolved_bases:
                return False
            resolved_bases.add(base_name)
        return True

    def _official_skill_base_name(self, skill_name: str) -> str | None:
        for base_name in self.release_manifest.official_skill_names:
            if skill_name == base_name:
                return base_name
            prefix = f"{base_name}_"
            if skill_name.startswith(prefix) and skill_name[len(prefix):].isdigit():
                return base_name
        return None

    @staticmethod
    def _stable_tool_names(tool: dict[str, Any]) -> set[str]:
        return {
            str(tool.get("name") or ""),
            str(tool.get("origin_name") or ""),
            str(tool.get("class_name") or ""),
        }

    def _find_available_tool(
        self,
        tool_name: str,
        tenant_id: str,
        *,
        required: bool = True,
    ) -> dict[str, Any] | None:
        for tool in query_all_tools(tenant_id):
            if (
                tool_name in self._stable_tool_names(tool)
                and tool.get("is_available") is not False
            ):
                return tool
        if required:
            raise WorkbenchAgentError(
                "system_agent_not_ready",
                retryable=True,
                message=f"Required Tool is unavailable: {tool_name}",
            )
        return None

    def _resolve_published_ref(
        self,
        tenant_id: str,
        draft: dict[str, Any],
    ) -> SystemAgentRef:
        version_no = int(draft.get("current_version_no") or 0)
        if version_no < 1:
            raise WorkbenchAgentError("system_agent_not_ready", retryable=True)
        snapshot = search_system_agent(
            tenant_id,
            self.system_key,
            version_no=version_no,
        )
        if (
            snapshot is None
            or int(snapshot.get("agent_id") or 0) != int(draft["agent_id"])
            or snapshot.get("enabled") is False
        ):
            raise WorkbenchAgentError("system_agent_not_ready", retryable=True)
        return SystemAgentRef(
            tenant_id=tenant_id,
            system_key=self.system_key,
            agent_id=int(draft["agent_id"]),
            version_no=version_no,
        )

    @staticmethod
    def _validate_tenant_id(tenant_id: str) -> None:
        if not tenant_id or not tenant_id.strip():
            raise ValueError("tenant_id is required")

    def _is_newer_release(self, current_revision: str) -> bool:
        """Return whether this provider represents a strictly newer release."""
        try:
            return Version(self.release_manifest.system_revision) > Version(
                current_revision
            )
        except InvalidVersion:
            return False

    @staticmethod
    def _editable_fields(locale: str | None = None) -> dict[str, Any]:
        canonical_prompt = SystemAgentProvider.get_system_prompt(locale or "")
        return {
            "name": WORKBENCH_MAIN_NAME,
            "display_name": WORKBENCH_MAIN_DISPLAY_NAME,
            "description": (
                "Protected general-purpose Agent for the intelligent workbench"
            ),
            "business_description": (
                "General conversation and runtime capability orchestration"
            ),
            "author": "Nexent",
            "max_steps": 15,
            "is_main_agent": True,
            "provide_run_summary": False,
            "allow_chat_metadata": False,
            "is_a2a": False,
            "duty_prompt": canonical_prompt,
            "constraint_prompt": "",
            "few_shots_prompt": "",
            "enabled": True,
        }


system_agent_provider = SystemAgentProvider()


def ensure_workbench_main_agent(
    tenant_id: str,
    user_id: str | None = None,
    locale: str | None = None,
) -> SystemAgentRef:
    """Convenience entrypoint for tenant bootstrap and Workbench runtime."""
    return system_agent_provider.ensure_workbench_main(
        tenant_id,
        user_id,
        locale=locale,
    )
