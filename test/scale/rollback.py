"""
Nexent 测试数据回滚脚本

测试原理:
  通过前缀匹配 (scale-* / perf-*) 批量删除测试产生的数据。
  回滚顺序: 先删子数据 (会话/记忆) → 再删主数据 (Agent/KB/MCP/Skill) → 最后删租户/用户。

支持两种模式:
  1. 精确回滚: 只删除指定前缀的数据, 不影响生产数据
  2. 全量回滚: 删除所有非系统数据 (危险!)

运行:
  python -m test.scale.rollback            # 精确回滚 (只删 scale-*/perf-* 前缀)
  python -m test.scale.rollback --all      # 全量回滚 (危险!)
"""

import os
import time
import logging
import concurrent.futures
from typing import List

from utils import (
    logger, login,
    api_get, api_post, api_delete,
    delete_agent, delete_knowledge_base,
    delete_mcp_service, delete_skill,
    delete_conversation, delete_memory_record,
    delete_tenant,
)

# 测试数据前缀
TEST_PREFIXES = ("scale-", "perf-")

# 全量回滚时跳过的系统租户/用户 (环境变量覆盖)
SYSTEM_EMAILS = {os.getenv("NEXENT_TEST_EMAIL", ""), "suadmin@nexent.com"}
SYSTEM_TENANT_NAMES = {"默认租户", "default", os.getenv("NEXENT_TENANT_NAME", "ljy")}


def _is_test_name(name: str) -> bool:
    """判断是否是测试数据 (按前缀匹配)"""
    if not name:
        return False
    return any(name.startswith(p) for p in TEST_PREFIXES)


def _get_current_tenant_id() -> str:
    """从 /user/current_user_info 获取当前登录用户的 tenant_id"""
    try:
        resp = api_get("/user/current_user_info")
        return resp.get("data", {}).get("user", {}).get("tenant_id", "")
    except Exception as e:
        logger.warning("Failed to get current tenant_id: %s", e)
        return ""


# ─── 回滚: Agent ──────────────────────────────────────────────────

def rollback_agents(all_agents: bool = False):
    """删除测试 Agent"""
    logger.info("Rolling back agents...")
    # /agent/list 直接返回 list[dict], 每个 item 含 agent_id / name
    resp = api_get("/agent/list")
    agents = resp if isinstance(resp, list) else resp.get("data", [])

    deleted = 0
    for agent in agents:
        name = agent.get("name") or agent.get("agent_name", "")
        aid = agent.get("agent_id")
        if all_agents or _is_test_name(name):
            try:
                api_delete("/agent", json={"agent_id": aid})
                deleted += 1
            except Exception as e:
                logger.warning("Delete agent %s failed: %s", aid, e)
    logger.info("Deleted %d agents", deleted)
    return deleted


# ─── 回滚: 知识库 ────────────────────────────────────────────────

def rollback_knowledge_bases(all_kbs: bool = False):
    """删除测试知识库"""
    logger.info("Rolling back knowledge bases...")
    # /indices?pattern=*&include_stats=true 返回 {"indices": [...], "indices_info": [{name, display_name, ...}]}
    # 其中 indices 是 index_name 字符串列表, indices_info 是详细 dict 列表
    resp = api_get("/indices?pattern=*&include_stats=true")
    kbs = resp.get("indices_info", []) if isinstance(resp, dict) else []

    deleted = 0
    for kb in kbs:
        # display_name = 用户可见的知识库名 (knowledge_name); name = 内部 index_name (删除用)
        name = kb.get("display_name") or kb.get("name", "")
        index_name = kb.get("name") or kb.get("display_name", "")
        if all_kbs or _is_test_name(name):
            try:
                delete_knowledge_base(index_name)
                deleted += 1
            except Exception as e:
                logger.warning("Delete KB %s failed: %s", index_name, e)
    logger.info("Deleted %d knowledge bases", deleted)
    return deleted


# ─── 回滚: MCP 服务 ──────────────────────────────────────────────

def rollback_mcp_services(all_mcps: bool = False):
    """删除测试 MCP 服务"""
    logger.info("Rolling back MCP services...")
    # /mcp/list 返回 {"remote_mcp_server_list": [...], "status": "success"}
    # 每个 item 含 mcp_id / remote_mcp_server_name
    resp = api_get("/mcp/list")
    mcps = resp.get("remote_mcp_server_list", []) if isinstance(resp, dict) else []

    deleted = 0
    for mcp in mcps:
        name = mcp.get("remote_mcp_server_name") or mcp.get("mcp_name") or mcp.get("name", "")
        mid = mcp.get("mcp_id")
        if all_mcps or _is_test_name(name):
            try:
                delete_mcp_service(mid)
                deleted += 1
            except Exception as e:
                logger.warning("Delete MCP %s failed: %s", mid, e)
    logger.info("Deleted %d MCP services", deleted)
    return deleted


# ─── 回滚: Skills ────────────────────────────────────────────────

def rollback_skills(all_skills: bool = False):
    """删除测试 Skill"""
    logger.info("Rolling back skills...")
    # /skills 返回 {"skills": [...]}, 每个 item 含 name
    resp = api_get("/skills", timeout=60)
    skills = resp.get("skills", []) if isinstance(resp, dict) else []

    deleted = 0
    for skill in skills:
        name = skill.get("name") or skill.get("skill_name", "")
        if all_skills or _is_test_name(name):
            try:
                delete_skill(name)
                deleted += 1
            except Exception as e:
                logger.warning("Delete skill %s failed: %s", name, e)
    logger.info("Deleted %d skills", deleted)
    return deleted


# ─── 回滚: 会话 ──────────────────────────────────────────────────

def rollback_conversations(all_convs: bool = False):
    """删除测试会话"""
    logger.info("Rolling back conversations...")
    # /conversation/list 返回 {"code":0, "data": {"items": [...], "metadata": {...}}}
    # 每个 item 含 conversation_id / conversation_title
    resp = api_get("/conversation/list?today_start_ms=0&week_start_ms=0")
    convs = resp.get("data", {}).get("items", []) if isinstance(resp, dict) else []

    deleted = 0
    for conv in convs:
        title = conv.get("conversation_title") or conv.get("title", "")
        cid = conv.get("conversation_id")
        if all_convs or _is_test_name(title):
            try:
                delete_conversation(cid)
                deleted += 1
            except Exception as e:
                logger.warning("Delete conversation %s failed: %s", cid, e)
    logger.info("Deleted %d conversations", deleted)
    return deleted


# ─── 回滚: 记忆 ──────────────────────────────────────────────────

def rollback_memories(agent_id: int = None, all_memories: bool = False):
    """删除测试记忆记录"""
    logger.info("Rolling back memory records...")
    # /memory/records 返回 {"items": [...], "count": N}, 每个 item 含 memory_id / content
    query = "layer=agent&limit=1000"
    if agent_id:
        query += f"&agent_id={agent_id}"

    resp = api_get(f"/memory/records?{query}")
    records = resp.get("items", []) if isinstance(resp, dict) else []

    deleted = 0
    for record in records:
        content = record.get("content", "")
        mid = record.get("memory_id")
        if all_memories or _is_test_name(content):
            try:
                delete_memory_record(mid)
                deleted += 1
            except Exception as e:
                logger.warning("Delete memory %s failed: %s", mid, e)
    logger.info("Deleted %d memory records", deleted)
    return deleted


# ─── 回滚: 用户组 ────────────────────────────────────────────────

def rollback_groups(all_groups: bool = False):
    """删除测试用户组"""
    logger.info("Rolling back groups...")
    # /groups/list 需要有效的 tenant_id (空串会 404), 返回 {"data": [...], "total": N}
    # 每个 item 含 group_id / group_name
    tenant_id = _get_current_tenant_id()
    try:
        resp = api_post("/groups/list", json_body={"tenant_id": tenant_id, "page": 1, "page_size": 100})
        groups = resp.get("data", []) if isinstance(resp, dict) else []
    except Exception as e:
        logger.warning("List groups failed: %s", e)
        groups = []

    deleted = 0
    for group in groups:
        name = group.get("group_name", "")
        gid = group.get("group_id")
        if all_groups or _is_test_name(name):
            try:
                api_delete(f"/groups/{gid}")
                deleted += 1
            except Exception as e:
                logger.warning("Delete group %s failed: %s", gid, e)
    logger.info("Deleted %d groups", deleted)
    return deleted


# ─── 回滚: 租户 ──────────────────────────────────────────────────

def rollback_tenants(all_tenants: bool = False):
    """删除测试租户 (级联删除租户下所有数据)"""
    logger.info("Rolling back tenants...")
    # /tenants/tenant-list 返回 {"data": [...], "total": N, ...}, 每个 item 含 tenant_id / tenant_name
    # 注意: 该接口仅 SU 超管可调用, 非 SU 会 403; page_size 上限为 100
    try:
        resp = api_post("/tenants/tenant-list", json_body={"page": 1, "page_size": 100})
        tenants = resp.get("data", []) if isinstance(resp, dict) else []
    except Exception as e:
        logger.warning("List tenants failed (need SU role): %s", e)
        tenants = []

    deleted = 0
    for tenant in tenants:
        name = tenant.get("tenant_name", "")
        tid = tenant.get("tenant_id")
        # 全量模式: 跳过系统租户; 测试模式: 只删测试前缀
        if all_tenants:
            if name not in SYSTEM_TENANT_NAMES:
                try:
                    delete_tenant(tid)
                    deleted += 1
                except Exception as e:
                    logger.warning("Delete tenant %s failed: %s", tid, e)
        elif _is_test_name(name):
            try:
                delete_tenant(tid)
                deleted += 1
            except Exception as e:
                logger.warning("Delete tenant %s failed: %s", tid, e)
    logger.info("Deleted %d tenants", deleted)
    return deleted


# ─── 主入口 ───────────────────────────────────────────────────────

def run_rollback(all_data: bool = False):
    """
    执行回滚
    
    Args:
        all_data: True=删除所有非系统数据, False=只删测试前缀数据
    """
    mode = "ALL (dangerous!)" if all_data else "test-prefix only"
    logger.info("=" * 60)
    logger.info("Nexent Test Data Rollback (mode=%s)", mode)
    logger.info("=" * 60)

    login()

    # 回滚顺序: 子数据 → 主数据 → 租户
    rollback_conversations(all_convs=all_data)
    rollback_memories(all_memories=all_data)
    rollback_agents(all_agents=all_data)
    rollback_knowledge_bases(all_kbs=all_data)
    rollback_mcp_services(all_mcps=all_data)
    rollback_skills(all_skills=all_data)
    rollback_groups(all_groups=all_data)
    rollback_tenants(all_tenants=all_data)

    logger.info("Rollback completed.")


if __name__ == "__main__":
    import sys
    sys.path.insert(0, "test/scale")
    
    all_mode = "--all" in sys.argv
    if all_mode:
        confirm = input("WARNING: This will delete ALL non-system data. Type 'yes' to confirm: ")
        if confirm.lower() != "yes":
            print("Aborted.")
            sys.exit(1)
    run_rollback(all_data=all_mode)
