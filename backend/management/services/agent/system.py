# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Release platform-owned definitions independently of tenant runtime resources."""

import json
import logging
from copy import deepcopy
from typing import Any

from packaging.version import InvalidVersion, Version

from contracts.agent import SystemAgentRef, WorkbenchReleaseManifest
from contracts.constants.constants import ASSET_OWNER_TENANT_ID, LANGUAGE
from contracts.constants.environment import APP_VERSION, ENABLE_AIDP_KNOWLEDGE
from contracts.errors.exceptions import WorkbenchAgentError
from management.db.agent.repository import search_system_agent
from management.db.skill import repository as skill_db
from management.db.tool.repository import query_all_tools
from management.services.skill.transfer import install_skills_from_zip_for_tenant
from nexent.core.prompts import load_prompt

logger = logging.getLogger(__name__)
WORKBENCH_MAIN_SYSTEM_KEY = "workbench_main"
WORKBENCH_MAIN_NAME = "workbench_main"
WORKBENCH_MAIN_DISPLAY_NAME = "Nexent Workbench"
NL2AGENT_MAIN_SYSTEM_KEY = "nl2agent_main"
SYSTEM_AGENT_USER_ID = "system"


def localized_system_prompt(snapshot: dict, language: str) -> str:
    """Select a frozen platform prompt; legacy plain-text snapshots remain readable."""
    prompt = str(snapshot.get("prompt") or "")
    if snapshot.get("agent_origin") == "SYSTEM":
        try:
            variants = json.loads(prompt)
        except (TypeError, ValueError):
            return prompt
        if isinstance(variants, dict) and set(variants) == {"zh", "en"}:
            return str(variants["en" if language == LANGUAGE["EN"] else "zh"])
    return prompt


class SystemAgentProvider:
    """Read shared definitions and prepare release capability catalogs."""

    system_key = WORKBENCH_MAIN_SYSTEM_KEY

    def __init__(
        self, *, app_version: str | None = None, aidp_enabled: bool | None = None
    ):
        revision = str(APP_VERSION if app_version is None else app_version).strip()
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
        template_language = (
            LANGUAGE["EN"] if language == LANGUAGE["EN"] else LANGUAGE["ZH"]
        )
        return str(
            load_prompt(template_language, "agent/workbench_main").get(
                "system_prompt", ""
            )
        )

    def _get_ref(self, tenant_id: str, system_key: str) -> SystemAgentRef:
        self._validate_tenant_id(tenant_id)
        draft = search_system_agent(ASSET_OWNER_TENANT_ID, system_key)
        if draft is None or draft.get("enabled") is False:
            raise WorkbenchAgentError("system_agent_not_ready", retryable=True)
        version_no = int(draft.get("current_version_no") or 0)
        snapshot = search_system_agent(
            ASSET_OWNER_TENANT_ID, system_key, version_no=version_no
        )
        if (
            version_no < 1
            or snapshot is None
            or snapshot.get("enabled") is False
            or snapshot.get("agent_id") != draft["agent_id"]
        ):
            raise WorkbenchAgentError("system_agent_not_ready", retryable=True)
        return SystemAgentRef(
            ASSET_OWNER_TENANT_ID, system_key, int(draft["agent_id"]), version_no
        )

    def get_workbench_main_ref(self, tenant_id: str) -> SystemAgentRef:
        return self._get_ref(tenant_id, self.system_key)

    def get_creator_ref(self, tenant_id: str, system_key: str) -> SystemAgentRef:
        self._validate_tenant_id(tenant_id)
        if system_key not in ("nl2agent_main", "nl2skill_main"):
            raise ValueError("Unknown creator identity")
        identity = search_system_agent(ASSET_OWNER_TENANT_ID, system_key)
        if identity is None or identity.get("enabled") is False:
            raise WorkbenchAgentError("system_agent_not_ready", retryable=True)
        return SystemAgentRef(ASSET_OWNER_TENANT_ID, system_key, int(identity["agent_id"]), 0)

    def get_nl2agent_main_ref(self, tenant_id: str) -> SystemAgentRef:
        return self.get_creator_ref(tenant_id, "nl2agent_main")

    def get_nl2skill_main_ref(self, tenant_id: str) -> SystemAgentRef:
        return self.get_creator_ref(tenant_id, "nl2skill_main")

    def _prepare_official_skills(
        self, tenant_id: str, actor: str
    ) -> list[dict[str, Any]]:
        available = self.get_workbench_default_skills(tenant_id)
        installed = {
            self._official_skill_base_name(str(skill.get("name") or ""))
            for skill in available
        }
        missing = [
            name
            for name in self.release_manifest.official_skill_names
            if name not in installed
        ]
        if not missing:
            return available
        try:
            install_skills_from_zip_for_tenant(
                skill_names=missing,
                tenant_id=tenant_id,
                user_id=actor,
            )
        except Exception as exc:
            logger.warning(
                "Official Skill import unavailable for tenant %s: %s", tenant_id, exc
            )
        return self.get_workbench_default_skills(tenant_id)

    def _official_skill_base_name(self, skill_name: str) -> str | None:
        for name in self.release_manifest.official_skill_names:
            if skill_name == name or (
                skill_name.startswith(f"{name}_")
                and skill_name[len(name) + 1 :].isdigit()
            ):
                return name
        return None

    def get_workbench_default_skills(self, tenant_id: str) -> list[dict[str, Any]]:
        """Resolve official names in the caller's tenant without persisting Agent bindings."""
        self._validate_tenant_id(tenant_id)
        selected = {}
        for skill in skill_db.list_skills(tenant_id):
            if str(skill.get("source") or "").casefold() != "official":
                continue
            name = str(skill.get("name") or "")
            base = self._official_skill_base_name(name)
            if base and (base not in selected or name == base):
                selected[base] = skill
        return [
            selected[name]
            for name in self.release_manifest.official_skill_names
            if name in selected
        ]

    @staticmethod
    def _stable_tool_names(tool: dict[str, Any]) -> set[str]:
        return {
            str(tool.get(key) or "") for key in ("name", "origin_name", "class_name")
        }

    def get_workbench_default_tools(self, tenant_id: str) -> list[dict[str, Any]]:
        """Resolve the managed knowledge capability without writing shared Tool instances."""
        selected_name = self.release_manifest.persistent_tool_names[0]
        for tool in query_all_tools(tenant_id):
            if (
                selected_name in self._stable_tool_names(tool)
                and tool.get("is_available") is not False
            ):
                configured = deepcopy(tool)
                if selected_name == "knowledge_base_search":
                    for param in configured.get("params") or []:
                        if param.get("name") == "index_names":
                            param["default"] = []
                configured["enabled"] = True
                return [configured]
        return []

    @staticmethod
    def _validate_tenant_id(tenant_id: str) -> None:
        if not tenant_id or not tenant_id.strip():
            raise ValueError("tenant_id is required")

    def _is_newer_release(self, current_revision: str) -> bool:
        try:
            return Version(self.release_manifest.system_revision) > Version(
                current_revision
            )
        except InvalidVersion:
            return False

    @staticmethod
    def _editable_fields(locale: str | None = None) -> dict[str, Any]:
        return {
            "name": WORKBENCH_MAIN_NAME,
            "display_name": WORKBENCH_MAIN_DISPLAY_NAME,
            "description": "Protected general-purpose Agent for the intelligent workbench",
            "business_description": "General conversation and runtime capability orchestration",
            "author": "Nexent",
            "max_steps": 15,
            "is_main_agent": True,
            "provide_run_summary": False,
            "allow_chat_metadata": False,
            "is_a2a": False,
            "prompt": json.dumps(
                {
                    lang: SystemAgentProvider.get_system_prompt(lang)
                    for lang in ("zh", "en")
                },
                ensure_ascii=False,
            ),
            "enabled": True,
        }


system_agent_provider = SystemAgentProvider()
