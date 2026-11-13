# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Build knowledge routing summaries and external Agent descriptors."""

import logging
from typing import List

from infrastructure.a2a_execution import (
    _build_auth_header_for_scheme as _build_auth_header_for_scheme,
    build_external_agent_config as _build_external_agent_config,
    _build_security_headers as _build_security_headers,
    _collect_auth_headers as _collect_auth_headers,
    extract_url_from_card as _extract_url_from_card,
    _resolve_scheme_field as _resolve_scheme_field,
)
from management.services.knowledge_base.service import ElasticSearchService
from nexent.core.agents.agent_model import ExternalA2AAgentConfig, ToolConfig

logger = logging.getLogger("create_agent_info")
logger.setLevel(logging.INFO)


def _build_effective_knowledge_base_summary(
    tool_list: List[ToolConfig],
    include_empty_message: bool = True,
) -> tuple[list[dict[str, str]], bool]:
    """Collect selected summaries without formatting prompt prose."""
    summaries: list[dict[str, str]] = []
    try:
        for tool in tool_list:
            if tool.class_name != "KnowledgeBaseSearchTool":
                continue
            metadata = tool.metadata if isinstance(tool.metadata, dict) else {}
            index_names = metadata.get("allowed_index_names") or []
            if not index_names:
                return [], include_empty_message
            display_map = metadata.get("index_name_to_display_map", {})
            for index_name in index_names:
                try:
                    display_name = display_map.get(index_name, index_name)
                    message = ElasticSearchService().get_summary(index_name=index_name)
                    summary = message.get("summary", "")
                    summaries.append(
                        {
                            "index_name": str(index_name),
                            "display_name": str(display_name),
                            "summary": str(summary),
                        }
                    )
                except Exception as exc:
                    logger.warning(
                        f"Failed to get summary for knowledge base {index_name}: {exc}"
                    )
            break
    except Exception as exc:
        logger.error(f"Failed to build knowledge base summary: {exc}")
    return summaries, False


def _get_external_a2a_agents(
    agent_id: int, tenant_id: str, version_no: int = 0
) -> List[ExternalA2AAgentConfig]:
    """Get external A2A agent configurations for an agent.

    Args:
        agent_id: Agent ID
        tenant_id: Tenant ID
        version_no: Version number

    Returns:
        List of ExternalA2AAgentConfig for external A2A sub-agents
    """
    try:
        from management.db.a2a import repository as a2a_agent_db

        external_agents = a2a_agent_db.query_external_sub_agents(
            local_agent_id=agent_id,
            tenant_id=tenant_id,
            version_no=version_no,
        )

        result = []
        for agent in external_agents:
            agent_url = agent.get("agent_url", "") or _extract_url_from_card(
                agent.get("raw_card")
            )
            if not agent_url:
                logger.warning(
                    f"Skipping agent '{agent.get('name')}' - no URL available"
                )
                continue

            result.append(_build_external_agent_config(agent, agent_url))

        return result
    except Exception as e:
        logger.error(f"Get external A2A agents failed: {e}", exc_info=True)
        return []
