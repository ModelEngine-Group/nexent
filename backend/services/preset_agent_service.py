"""
Preset Agent Service

Automatically seeds built-in preset agents for a new (or existing) tenant
when the tenant has zero enabled agents.  This mirrors the existing
`init_tool_list_for_tenant` / `init_skill_list_for_tenant` pattern.

Each preset agent maps to one of the 7 single-type built-in solutions shown
on the market-v2 page (solution ids 101-107).  Solution 108 (deep-research-team)
is a team type and does not need a single preset agent.

The seed is *idempotent*: if the tenant already has at least one enabled
agent, the function returns immediately without creating duplicates.

After creating each agent record, it is automatically published as version 1
so that it appears in the published agent list (used by the market-v2 page).
"""

import logging
from typing import Dict, List, Optional

from database.agent_db import (
    create_agent,
    query_all_agent_info_by_tenant_id,
)
from database.tool_db import (
    create_or_update_tool_by_tool_info,
    query_all_tools,
)
from database.model_management_db import get_model_records
from consts.model import ToolInstanceInfoRequest
from utils.str_utils import convert_list_to_string
from database.group_db import query_group_ids_by_user

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Preset agent templates
# ---------------------------------------------------------------------------

PRESET_AGENT_TEMPLATES: List[Dict] = [
    {
        "name": "kb-qa-assistant",
        "display_name": "知识库问答助手",
        "description": "基于 RAG 的企业知识库问答助手，直连向量知识库做语义检索与精准回答。适合内部文档问答、规章制度查询、产品手册检索等场景。",
        "business_description": "基于知识库的问答方案",
        "duty_prompt": "你是一个基于知识库的问答助手。回答用户问题时，优先使用知识库搜索工具检索相关文档，基于检索到的内容给出准确、简洁的回答。如果知识库中没有相关信息，请如实告知并建议用户补充知识。",
        "tool_names": ["knowledge_base_search"],
    },
    {
        "name": "web-research-assistant",
        "display_name": "网络调研助手",
        "description": "联网调研助手，从关键词出发自动完成检索、信息整理、要点归纳。适合市场调研、竞品分析、资料收集等场景。",
        "business_description": "网络调研方案",
        "duty_prompt": "你是一个网络调研助手。根据用户提出的研究主题，使用搜索工具进行多轮检索，收集并整理相关信息，归纳出要点和结论。输出应包含来源引用。",
        "tool_names": ["tavily_search", "exa_search", "linkup_search"],
    },
    {
        "name": "document-analysis-assistant",
        "display_name": "文档分析助手",
        "description": "多模态文档分析助手，支持 PDF/Word/TXT 等格式的文档理解、信息提取、摘要生成。适合合同审查、报告解读、文档摘要等场景。",
        "business_description": "文档分析方案",
        "duty_prompt": "你是一个文档分析助手。用户上传文档后，你可以读取文件内容、分析文本结构，提取关键信息、生成摘要或回答关于文档的问题。",
        "tool_names": ["read_file", "analyze_text_file"],
    },
    {
        "name": "multimodal-analysis-assistant",
        "display_name": "多模态分析助手",
        "description": "图像/音频/视频综合分析助手，支持图片识别、语音转写、视频内容理解。适合内容审核、媒体分析、质检等场景。",
        "business_description": "多模态分析方案",
        "duty_prompt": "你是一个多模态分析助手。可以对用户提供的图片、音频、视频文件进行内容识别、转写和分析，输出结构化的分析结果。",
        "tool_names": ["analyze_image", "analyze_audio", "analyze_video"],
    },
    {
        "name": "data-analyst-assistant",
        "display_name": "数据分析助手",
        "description": "数据库查询分析助手，支持自然语言转 SQL、数据查询、结果分析。适合业务数据查询、报表生成、数据洞察等场景。",
        "business_description": "数据分析方案",
        "duty_prompt": "你是一个数据分析助手。根据用户的自然语言提问，生成并执行 SQL 查询，对查询结果进行分析并给出数据洞察。请注意 SQL 注入防护。",
        "tool_names": ["mysql_database", "postgres_database", "mssql_database"],
    },
    {
        "name": "file-manager-assistant",
        "display_name": "文件管理助手",
        "description": "文件操作助手，支持文件读写、目录管理、文件整理。适合批量文件处理、目录整理、文件格式转换等场景。",
        "business_description": "文件管理方案",
        "duty_prompt": "你是一个文件管理助手。可以帮助用户创建、读取、删除文件和目录，移动和整理文件。操作前请确认路径，避免误删重要文件。",
        "tool_names": [
            "create_file", "read_file", "delete_file",
            "create_directory", "delete_directory", "move_item", "list_directory",
        ],
    },
    {
        "name": "email-assistant",
        "display_name": "邮件助手",
        "description": "邮件处理助手，支持通过 IMAP 读取邮件、发送 HTML 邮件（多收件人/抄送/密送）。适合邮件自动回复、邮件摘要、批量通知等场景。",
        "business_description": "邮件处理方案",
        "duty_prompt": "你是一个邮件助手。可以帮助用户读取邮件、撰写并发送邮件。发送前请与用户确认收件人、主题和正文内容。",
        "tool_names": ["get_email", "send_email"],
    },
]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _build_tool_name_to_id_map(tenant_id: str) -> Dict[str, int]:
    """Map tool logical name -> tool_id for available tools in this tenant."""
    tools = query_all_tools(tenant_id)
    mapping: Dict[str, int] = {}
    for tool in tools:
        # Skip soft-deleted tools
        if getattr(tool, "delete_flag", "N") == "Y":
            continue
        if getattr(tool, "is_available", True) is False:
            continue
        mapping[tool.name] = tool.tool_id
    return mapping


def _get_first_llm_model_id(tenant_id: str) -> Optional[int]:
    """Return the first available LLM model_id for the tenant, or None."""
    records = get_model_records({"model_type": "llm"}, tenant_id)
    for record in records:
        # Prefer connected models, but accept any non-deleted LLM
        connect_status = (record.get("connect_status") or "").lower()
        if connect_status in ("failed", "untested"):
            continue
        return record.get("model_id")
    # Fallback: if none connected, return the first record if any
    if records:
        return records[0].get("model_id")
    return None


def _get_user_group_ids(user_id: str, tenant_id: str) -> str:
    """Get user's group IDs as a comma-separated string."""
    try:
        group_ids = query_group_ids_by_user(user_id)
        return convert_list_to_string(group_ids)
    except Exception as e:
        logger.warning(f"Failed to get user groups for user {user_id}: {str(e)}")
        return ""


def _publish_agent(agent_id: int, tenant_id: str, user_id: str) -> bool:
    """
    Publish an agent (create version 1 snapshot) so it appears in the
    published agent list.  Returns True on success, False on failure.
    """
    try:
        from services.agent_version_service import publish_version_impl
        publish_version_impl(
            agent_id=agent_id,
            tenant_id=tenant_id,
            user_id=user_id,
        )
        return True
    except Exception as e:
        logger.error(
            f"Failed to publish preset agent {agent_id} for tenant {tenant_id}: {str(e)}"
        )
        return False


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def init_preset_agents_for_tenant(tenant_id: str, user_id: str) -> dict:
    """
    Seed default preset agents for a tenant if none exist.

    This function is idempotent: if the tenant already has at least one
    enabled agent, it returns immediately without creating duplicates.

    Each created agent is also published as version 1 so it shows up in the
    published agent list used by the market-v2 page.

    Args:
        tenant_id: Tenant ID
        user_id: User ID (for audit fields and group assignment)

    Returns:
        Dict with status and count of created agents.
    """
    # Idempotency check: only seed if tenant has zero enabled agents
    existing_agents = query_all_agent_info_by_tenant_id(tenant_id=tenant_id)
    enabled_agents = [a for a in existing_agents if a.get("enabled")]
    if enabled_agents:
        logger.info(f"Tenant {tenant_id} already has {len(enabled_agents)} enabled agents, skipping preset seed")
        return {"status": "already_initialized", "created": 0}

    # Check if preset agents already exist (by name) even if disabled
    existing_names = {a.get("name") for a in existing_agents if a.get("name")}

    # Resolve tool name -> tool_id mapping for this tenant
    tool_id_map = _build_tool_name_to_id_map(tenant_id)
    if not tool_id_map:
        logger.warning(f"No tools found for tenant {tenant_id}, preset agents will have no tools enabled")

    # Resolve default LLM model
    default_model_id = _get_first_llm_model_id(tenant_id)
    if default_model_id is None:
        logger.warning(f"No LLM model configured for tenant {tenant_id}, preset agents will have no model assigned")

    # Resolve user group ids
    group_ids_str = _get_user_group_ids(user_id, tenant_id)

    created_count = 0
    for template in PRESET_AGENT_TEMPLATES:
        # Skip if an agent with the same name already exists
        if template["name"] in existing_names:
            logger.info(f"Agent '{template['name']}' already exists for tenant {tenant_id}, skipping")
            continue

        try:
            # Step 1: create the agent record (draft, version_no=0)
            agent_info = {
                "name": template["name"],
                "display_name": template["display_name"],
                "description": template["description"],
                "business_description": template["business_description"],
                "duty_prompt": template["duty_prompt"],
                "is_main_agent": True,
                "provide_run_summary": False,
                "enabled": True,
                "max_steps": 50,
                "group_ids": group_ids_str,
            }
            if default_model_id is not None:
                agent_info["model_ids"] = [default_model_id]

            created = create_agent(
                agent_info=agent_info,
                tenant_id=tenant_id,
                user_id=user_id,
            )
            agent_id = created["agent_id"]

            # Step 2: enable tools for this agent
            resolved_tool_ids = []
            for tool_name in template["tool_names"]:
                tool_id = tool_id_map.get(tool_name)
                if tool_id is not None:
                    resolved_tool_ids.append(tool_id)
                else:
                    logger.warning(
                        f"Tool '{tool_name}' not found for tenant {tenant_id}, "
                        f"skipping for agent '{template['name']}'"
                    )

            for tool_id in resolved_tool_ids:
                try:
                    create_or_update_tool_by_tool_info(
                        tool_info=ToolInstanceInfoRequest(
                            tool_id=tool_id,
                            agent_id=agent_id,
                            params={},
                            enabled=True,
                        ),
                        tenant_id=tenant_id,
                        user_id=user_id,
                    )
                except Exception as e:
                    logger.error(
                        f"Failed to enable tool {tool_id} for agent '{template['name']}': {str(e)}"
                    )

            # Step 3: publish the agent so it shows up in published list
            _publish_agent(agent_id, tenant_id, user_id)

            created_count += 1
            logger.info(
                f"Created preset agent '{template['name']}' (id={agent_id}) "
                f"for tenant {tenant_id} with {len(resolved_tool_ids)} tools"
            )

        except Exception as e:
            logger.error(
                f"Failed to create preset agent '{template['name']}' for tenant {tenant_id}: {str(e)}"
            )

    logger.info(
        f"Preset agent seed complete for tenant {tenant_id}: "
        f"created {created_count}/{len(PRESET_AGENT_TEMPLATES)} agents"
    )
    return {"status": "success", "created": created_count}

