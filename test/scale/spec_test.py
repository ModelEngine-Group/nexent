"""
Nexent 规格测试 — 数据量上限测试

测试原理:
  逐项创建数据到目标数量, 验证系统能否支撑规格定义的最大数据量。
  每项测试采用 "创建 → 计数验证 → (可选)回滚" 模式。
  使用批量创建 + 并发加速, 避免单条顺序创建超时。
  每项测试自动采样容器 CPU/内存, 输出到报告。

运行: python -m test.scale.spec_test
"""

import time
import sys
import os
import concurrent.futures
from typing import List

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

RUN_ID = time.strftime("%m%d%H%M")

from utils import (
    logger, TestReport, TestResult, ResourceMonitor, BaseTestCase,
    login, get_session,
    create_tenant, delete_tenant,
    create_invitation, create_user,
    create_group,
    create_agent, delete_agent,
    create_conversation, delete_conversation,
    create_knowledge_base, delete_knowledge_base,
    create_mcp_service, delete_mcp_service,
    create_skill, delete_skill,
    create_memory_record, delete_memory_record,
    api_get, api_post, api_delete,
    collect_db_metrics,
    BASE_URL, ADMIN_EMAIL,
)

# ─── 规格参数 ─────────────────────────────────────────────────────

MAX_TENANTS = 100
MAX_USERS_PER_TENANT = 10000
MAX_GROUPS_PER_TENANT = 1000
MAX_ADMINS_PER_TENANT = 1000
MAX_AGENTS_PER_TENANT = 1000
MAX_CONVERSATION_TURNS = 100
MAX_CONVERSATIONS_PER_USER = 1000
MAX_KBS_PER_TENANT = 10000
MAX_KBS_PER_USER = 1000
MAX_MCPS_PER_TENANT = 1000
MAX_SKILLS_PER_TENANT = 1000
MAX_MEMORIES_PER_AGENT = 5000

CONCURRENCY = 10


# ─── 测试用例 ─────────────────────────────────────────────────────

class TestMaxTenants(BaseTestCase):
    name = "max_tenants"
    target = MAX_TENANTS

    def _db_metric_key(self):
        return "tenants"

    def run(self) -> list:
        created_ids: List[str] = []

        def _create(idx):
            name = f"scale-tenant-{RUN_ID}-{idx:04d}"
            try:
                resp = create_tenant(name)
                tid = resp.get("tenant_id") or resp.get("data", {}).get("tenant_id")
                return tid
            except Exception as e:
                logger.warning("Create tenant %d failed: %s", idx, str(e)[:100])
                return None

        with concurrent.futures.ThreadPoolExecutor(max_workers=CONCURRENCY) as pool:
            futures = [pool.submit(_create, i) for i in range(self.target)]
            for f in concurrent.futures.as_completed(futures):
                tid = f.result()
                if tid:
                    created_ids.append(tid)
        return created_ids


class TestMaxUsersPerTenant(BaseTestCase):
    name = "max_users_per_tenant"
    target = MAX_USERS_PER_TENANT

    def __init__(self, report, monitor, tenant_id: str):
        super().__init__(report, monitor)
        self.tenant_id = tenant_id

    def _db_metric_key(self):
        return "users"

    def run(self) -> list:
        invite_code = create_invitation(self.tenant_id, capacity=self.target + 100)
        created_emails: List[str] = []

        def _create_user(idx):
            email = f"scale-user-{RUN_ID}-{idx:05d}@example.com"
            try:
                create_user(email, "Scale@123", invite_code)
                return email
            except Exception as e:
                logger.warning("Create user %d failed: %s", idx, str(e)[:80])
                return None

        with concurrent.futures.ThreadPoolExecutor(max_workers=CONCURRENCY) as pool:
            futures = [pool.submit(_create_user, i) for i in range(self.target)]
            for f in concurrent.futures.as_completed(futures):
                email = f.result()
                if email:
                    created_emails.append(email)
        return created_emails


class TestMaxGroupsPerTenant(BaseTestCase):
    name = "max_groups_per_tenant"
    target = MAX_GROUPS_PER_TENANT

    def __init__(self, report, monitor, tenant_id: str):
        super().__init__(report, monitor)
        self.tenant_id = tenant_id

    def _db_metric_key(self):
        return "groups"

    def run(self) -> list:
        created_ids: List[str] = []

        def _create(idx):
            name = f"scale-group-{RUN_ID}-{idx:04d}"
            try:
                resp = create_group(self.tenant_id, name)
                gid = resp.get("group_id") or resp.get("data", {}).get("group_id")
                return gid
            except Exception as e:
                logger.warning("Create group %d failed: %s", idx, str(e)[:80])
                return None

        with concurrent.futures.ThreadPoolExecutor(max_workers=CONCURRENCY) as pool:
            futures = [pool.submit(_create, i) for i in range(self.target)]
            for f in concurrent.futures.as_completed(futures):
                gid = f.result()
                if gid:
                    created_ids.append(gid)
        return created_ids


class TestMaxAdminsPerTenant(BaseTestCase):
    name = "max_admins_per_tenant"
    target = MAX_ADMINS_PER_TENANT

    def __init__(self, report, monitor, tenant_id: str):
        super().__init__(report, monitor)
        self.tenant_id = tenant_id

    def _db_metric_key(self):
        return "users"

    def run(self) -> list:
        invite_code = create_invitation(self.tenant_id, capacity=self.target + 100)
        created_emails: List[str] = []

        def _create(idx):
            email = f"scale-admin-{RUN_ID}-{idx:05d}@example.com"
            try:
                resp = create_user(email, "Scale@123", invite_code)
                user_id = resp.get("user_id") or resp.get("id") or ""
                if not user_id:
                    user_id = resp.get("data", {}).get("user_id", "")
                if user_id:
                    api_put(f"/users/{user_id}", json_body={"role": "ADMIN"})
                else:
                    logger.warning("Admin %d: no user_id in signup response", idx)
                return email
            except Exception as e:
                logger.warning("Create admin %d failed: %s", idx, str(e)[:80])
                return None

        with concurrent.futures.ThreadPoolExecutor(max_workers=CONCURRENCY) as pool:
            futures = [pool.submit(_create, i) for i in range(self.target)]
            for f in concurrent.futures.as_completed(futures):
                email = f.result()
                if email:
                    created_emails.append(email)
        return created_emails


class TestMaxAgentsPerTenant(BaseTestCase):
    name = "max_agents_per_tenant"
    target = MAX_AGENTS_PER_TENANT

    def _db_metric_key(self):
        return "agents"

    def run(self) -> list:
        login()
        # 预创建 MCP / Skill / KB
        mcp_ids = []
        for i in range(5):
            try:
                resp = create_mcp_service(f"scale-mcp-{RUN_ID}-{i:02d}")
                mid = resp.get("mcp_id") or resp.get("data", {}).get("mcp_id")
                if mid:
                    mcp_ids.append(mid)
            except Exception as e:
                logger.warning("Create MCP %d failed: %s", i, str(e)[:80])
        logger.info("Pre-created %d MCP services", len(mcp_ids))

        skill_ids = []
        for i in range(5):
            try:
                resp = create_skill(f"scale-skill-{RUN_ID}-{i:02d}")
                sid = resp.get("skill_id") or resp.get("data", {}).get("skill_id")
                if sid:
                    skill_ids.append(sid)
            except Exception as e:
                logger.warning("Create Skill %d failed: %s", i, str(e)[:80])
        logger.info("Pre-created %d Skills", len(skill_ids))

        kb_names = []
        try:
            from utils import get_embedding_model_id
            emb_id = get_embedding_model_id()
            for i in range(5):
                kb_name = f"scale-kb-{RUN_ID}-{i:02d}"
                resp = create_knowledge_base(kb_name, embedding_model_id=emb_id)
                index_name = resp.get("id", kb_name) if isinstance(resp, dict) else kb_name
                kb_names.append(index_name)
        except Exception as e:
            logger.warning("Create KB failed: %s", str(e)[:80])
        logger.info("Pre-created %d KBs", len(kb_names))

        # 创建 Agent, 每个随机挂载资源
        created_ids: List[int] = []
        for idx in range(self.target):
            try:
                tool_slice = mcp_ids[: (idx % max(len(mcp_ids), 1)) + 1] if mcp_ids else []
                skill_slice = skill_ids[: (idx % max(len(skill_ids), 1)) + 1] if skill_ids else []
                related = created_ids[:min(len(created_ids), idx % 3)] if len(created_ids) > 0 else []
                aid = create_agent(
                    f"scale_agent_{RUN_ID}_{idx:04d}",
                    tool_ids=tool_slice,
                    skill_ids=skill_slice,
                    related_agent_ids=related or None,
                )
                if aid:
                    created_ids.append(aid)
            except Exception as e:
                logger.warning("Create agent %d failed: %s", idx, str(e)[:100])

        if created_ids and kb_names:
            try:
                from utils import upload_text_to_kb, attach_kb_to_agent, KB_TEST_CONTENT
                upload_text_to_kb(kb_names[0], KB_TEST_CONTENT)
                attach_kb_to_agent(created_ids[0], kb_names[0])
            except Exception as e:
                logger.warning("Attach KB to first agent failed: %s", str(e)[:120])

        return created_ids


class TestMaxConversationTurns(BaseTestCase):
    name = "max_conversation_turns"
    target = MAX_CONVERSATION_TURNS

    def __init__(self, report, monitor, agent_id: int):
        super().__init__(report, monitor)
        self.agent_id = agent_id

    def run(self) -> list:
        import httpx
        conv = create_conversation(f"scale-turns-{RUN_ID}")
        conv_id = conv.get("conversation_id") or conv.get("data", {}).get("conversation_id")
        logger.info("Conversation created: id=%s", conv_id)
        agent_name = self._lookup_agent_name()
        if not agent_name:
            agent_name = "safe1"
            logger.warning("Agent name lookup failed, using fallback 'safe1'")
        nb_base = "http://localhost:5013"
        nb_headers = {"Authorization": "Bearer nexent-perftest-ddca790af3c2"}
        queries = [
            "What is the maximum number of tenants supported by Nexent?",
            "How many users can each tenant have?",
            "What is the rate limit of the northbound API?",
            "What is the maximum concurrent agent executions?",
            "What databases does Nexent use for deployment?",
        ]
        success_turns: List[int] = []
        for i in range(self.target):
            query = queries[i % len(queries)]
            try:
                with httpx.Client(timeout=300) as client:
                    with client.stream(
                        "POST",
                        f"{nb_base}/nb/v1/chat/run",
                        headers=nb_headers,
                        json={"agent_name": agent_name, "query": query,
                              "conversation_id": conv_id},
                    ) as resp:
                        if resp.status_code < 400:
                            for _ in resp.iter_lines():
                                pass
                            success_turns.append(i + 1)
                        elif resp.status_code == 429:
                            logger.warning("Turn %d rate limited, waiting 30s", i + 1)
                            time.sleep(30)
                        else:
                            body = resp.read().decode("utf-8", errors="replace")[:200]
                            logger.warning("Turn %d HTTP %d: %s", i, resp.status_code, body)
            except Exception as e:
                logger.warning("Turn %d failed: %s", i, str(e)[:120])
            time.sleep(1)
        return success_turns

    def _lookup_agent_name(self) -> str:
        try:
            resp = api_get(f"/agent/list")
            agents = resp.get("data", resp) if isinstance(resp, dict) else resp
            if isinstance(agents, list):
                for a in agents:
                    if a.get("agent_id") == self.agent_id:
                        return a.get("agent_name") or a.get("name", "")
        except Exception:
            pass
        return ""


class TestMaxConversationsPerUser(BaseTestCase):
    name = "max_conversations_per_user"
    target = MAX_CONVERSATIONS_PER_USER

    def run(self) -> list:
        created_ids: List[int] = []
        def _create(idx):
            try:
                resp = create_conversation(f"scale-conv-{RUN_ID}-{idx:04d}")
                cid = resp.get("conversation_id") or resp.get("data", {}).get("conversation_id")
                return cid
            except Exception as e:
                logger.warning("Create conv %d failed: %s", idx, str(e)[:80])
                return None
        with concurrent.futures.ThreadPoolExecutor(max_workers=CONCURRENCY) as pool:
            futures = [pool.submit(_create, i) for i in range(self.target)]
            for f in concurrent.futures.as_completed(futures):
                cid = f.result()
                if cid:
                    created_ids.append(cid)
        return created_ids


class TestMaxKbsPerTenant(BaseTestCase):
    name = "max_kbs_per_tenant"
    target = MAX_KBS_PER_TENANT

    def _db_metric_key(self):
        return "knowledge_bases"

    def run(self) -> list:
        login()
        from utils import get_embedding_model_id
        emb_id = get_embedding_model_id()
        created_names: List[str] = []

        def _create(idx):
            name = f"scale-kbt-{RUN_ID}-{idx:05d}"
            try:
                create_knowledge_base(name, embedding_model_id=emb_id)
                return name
            except Exception as e:
                logger.warning("Create KB %s failed: %s", name, str(e)[:100])
                return None

        with concurrent.futures.ThreadPoolExecutor(max_workers=CONCURRENCY) as pool:
            futures = [pool.submit(_create, i) for i in range(self.target)]
            for f in concurrent.futures.as_completed(futures):
                name = f.result()
                if name:
                    created_names.append(name)
        return created_names


class TestMaxKbsPerUser(BaseTestCase):
    name = "max_kbs_per_user"
    target = MAX_KBS_PER_USER

    def _db_metric_key(self):
        return "knowledge_bases"

    def run(self) -> list:
        login()
        from utils import get_embedding_model_id
        emb_id = get_embedding_model_id()
        created_names: List[str] = []

        def _create(idx):
            name = f"scale-kbu-{RUN_ID}-{idx:05d}"
            try:
                create_knowledge_base(name, embedding_model_id=emb_id)
                return name
            except Exception as e:
                logger.warning("Create KB %s failed: %s", name, str(e)[:100])
                return None

        with concurrent.futures.ThreadPoolExecutor(max_workers=CONCURRENCY) as pool:
            futures = [pool.submit(_create, i) for i in range(self.target)]
            for f in concurrent.futures.as_completed(futures):
                name = f.result()
                if name:
                    created_names.append(name)
        return created_names


class TestMaxMcpsPerTenant(BaseTestCase):
    name = "max_mcps_per_tenant"
    target = MAX_MCPS_PER_TENANT

    def _db_metric_key(self):
        return "mcp_services"

    def run(self) -> list:
        created_count = 0
        def _create(idx):
            nonlocal created_count
            try:
                resp = create_mcp_service(f"scale-mcp-{RUN_ID}-{idx:04d}")
                if isinstance(resp, dict) and resp.get("status") == "success":
                    created_count += 1
                    return True
                return None
            except Exception as e:
                logger.warning("Create MCP %d failed: %s", idx, e)
                return None

        with concurrent.futures.ThreadPoolExecutor(max_workers=CONCURRENCY) as pool:
            futures = [pool.submit(_create, i) for i in range(self.target)]
            for f in concurrent.futures.as_completed(futures):
                f.result()
        return list(range(created_count))


class TestMaxSkillsPerTenant(BaseTestCase):
    name = "max_skills_per_tenant"
    target = MAX_SKILLS_PER_TENANT

    def _db_metric_key(self):
        return "skills"

    def run(self) -> list:
        created_names: List[str] = []
        def _create(idx):
            name = f"scale-skill-{RUN_ID}-{idx:04d}"
            try:
                create_skill(name)
                return name
            except Exception as e:
                logger.warning("Create skill %d failed: %s", idx, e)
                return None

        with concurrent.futures.ThreadPoolExecutor(max_workers=CONCURRENCY) as pool:
            futures = [pool.submit(_create, i) for i in range(self.target)]
            for f in concurrent.futures.as_completed(futures):
                name = f.result()
                if name:
                    created_names.append(name)
        return created_names


class TestMaxMemoriesPerAgent(BaseTestCase):
    name = "max_memories_per_agent"
    target = MAX_MEMORIES_PER_AGENT

    def __init__(self, report, monitor, agent_id: int):
        super().__init__(report, monitor)
        self.agent_id = agent_id

    def _db_metric_key(self):
        return "memory_records"

    def run(self) -> list:
        created_ids: List[str] = []

        def _create(idx):
            try:
                resp = create_memory_record(
                    layer="agent",
                    content=f"scale-mem-{RUN_ID}-{idx}",
                    agent_id=self.agent_id,
                )
                mid = resp.get("memory_id") or resp.get("data", {}).get("memory_id")
                return mid
            except Exception as e:
                logger.warning("Create memory %d failed: %s", idx, e)
                return None

        with concurrent.futures.ThreadPoolExecutor(max_workers=CONCURRENCY) as pool:
            futures = [pool.submit(_create, i) for i in range(self.target)]
            for f in concurrent.futures.as_completed(futures):
                mid = f.result()
                if mid:
                    created_ids.append(mid)
        return created_ids


# ─── 功能测试 (核心接口验证) ──────────────────────────────────────

class TestHybridSearch(BaseTestCase):
    """Test knowledge base hybrid search (BM25 + kNN + embedding)."""
    name = "hybrid_search"
    target = 200

    def run(self) -> list:
        from utils import get_embedding_model_id, TIMEOUT_SLOW
        emb_id = get_embedding_model_id()

        kb_name = f"scale_search_{RUN_ID}"
        try:
            resp = api_post(f"/indices/{kb_name}", json_body={"embedding_model_id": emb_id}, timeout=TIMEOUT_SLOW)
            index_name = resp.get("id", kb_name)
        except Exception as e:
            logger.warning("Create search KB failed: %s", str(e)[:80])
            return []

        time.sleep(5)

        docs = [
            {"content": f"Test document {i}: Nexent platform supports multi-tenant architecture with tenant ID {i}.", "metadata": {"source": f"doc{i}"}}
            for i in range(10)
        ]
        try:
            api_post(f"/indices/{index_name}/documents", json_body=docs, timeout=TIMEOUT_SLOW)
            time.sleep(2)
        except Exception as e:
            logger.warning("Index documents failed: %s", str(e)[:80])

        queries = [
            "How many tenants does Nexent support?",
            "What is the multi-tenant architecture?",
            "Describe the platform features.",
            "What documents are available?",
            "Search for tenant information.",
        ]
        success = []
        for i in range(self.target):
            q = queries[i % len(queries)]
            try:
                resp = api_post("/indices/search/hybrid", json_body={
                    "index_names": [index_name], "query": q, "top_k": 5,
                }, timeout=TIMEOUT_SLOW)
                if isinstance(resp, dict) and resp.get("message") != "error":
                    success.append(i + 1)
                time.sleep(0.5)
            except Exception as e:
                logger.warning("Search %d failed: %s", i, str(e)[:80])
        return success


class TestDocumentIndexing(BaseTestCase):
    """Test document indexing (embedding generation + ES bulk write)."""
    name = "document_indexing"
    target = 100

    def run(self) -> list:
        from utils import get_embedding_model_id, TIMEOUT_SLOW
        emb_id = get_embedding_model_id()

        kb_name = f"scale_index_{RUN_ID}"
        try:
            resp = api_post(f"/indices/{kb_name}", json_body={"embedding_model_id": emb_id}, timeout=TIMEOUT_SLOW)
            index_name = resp.get("id", kb_name)
        except Exception as e:
            logger.warning("Create index KB failed: %s", str(e)[:80])
            return []

        time.sleep(5)

        success = []
        for i in range(self.target):
            docs = [
                {"content": f"Document batch {i}: This is a test document about Nexent platform feature {i}. " * 5, "metadata": {"batch": str(i)}}
            ]
            try:
                resp = api_post(f"/indices/{index_name}/documents", json_body=docs, timeout=TIMEOUT_SLOW)
                if isinstance(resp, dict):
                    success.append(i + 1)
                time.sleep(1)
            except Exception as e:
                logger.warning("Index batch %d failed: %s", i, str(e)[:80])
        return success


class TestFileUpload(BaseTestCase):
    """Test file upload to MinIO storage."""
    name = "file_upload"
    target = 200

    def run(self) -> list:
        from utils import get_session, BASE_URL
        session = get_session()

        success = []
        for i in range(self.target):
            import io
            content = f"Test file {i} for scale testing. " * 20
            files = {"file": (f"scale_file_{RUN_ID}_{i:04d}.txt", io.BytesIO(content.encode()), "text/plain")}
            data = {"destination": "minio", "folder": f"knowledge_base/scale_upload_{RUN_ID}"}
            try:
                resp = session.post(f"{BASE_URL}/file/upload", files=files, data=data, timeout=60)
                if resp.status_code < 400:
                    success.append(i + 1)
                time.sleep(0.3)
            except Exception as e:
                logger.warning("Upload %d failed: %s", i, str(e)[:80])
        return success


class TestDataProcessTask(BaseTestCase):
    """Test data processing pipeline (upload -> process -> index in ES)."""
    name = "data_process_task"
    target = 30

    def run(self) -> list:
        from utils import get_embedding_model_id, upload_text_to_kb, TIMEOUT_SLOW
        emb_id = get_embedding_model_id()

        kb_name = f"scale_task_{RUN_ID}"
        try:
            resp = api_post(f"/indices/{kb_name}", json_body={"embedding_model_id": emb_id}, timeout=TIMEOUT_SLOW)
            index_name = resp.get("id", kb_name)
        except Exception as e:
            logger.warning("Create task KB failed: %s", str(e)[:80])
            return []

        text_content = """
Nexent is a zero-code platform for auto-generating AI agents.
It supports multi-tenant architecture with up to 100 tenants.
Each tenant can have up to 10000 users and 1000 agents.
The platform uses Elasticsearch for knowledge base storage.
Agents can be configured with MCP tools, skills, and knowledge bases.
"""

        success = []
        for i in range(self.target):
            try:
                ok = upload_text_to_kb(index_name, f"{text_content}\nBatch {i}: Additional test content for indexing pipeline.")
                if ok:
                    success.append(i + 1)
                time.sleep(5)
            except Exception as e:
                logger.warning("Task %d failed: %s", i, str(e)[:80])

        time.sleep(10)
        return success


class TestMemorySearch(BaseTestCase):
    """Test memory record search (embedding + kNN)."""
    name = "memory_search"
    target = 200

    def run(self) -> list:
        from utils import create_memory_record, TIMEOUT_SLOW

        success = []
        for i in range(self.target):
            queries = [
                "What is Nexent?",
                "How many tenants are supported?",
                "What is the rate limit?",
                "Describe the agent system.",
                "What databases are used?",
            ]
            q = queries[i % len(queries)]
            try:
                resp = api_post("/memory/records/search", json_body={
                    "query": q, "top_k": 5,
                }, timeout=TIMEOUT_SLOW)
                if isinstance(resp, dict):
                    success.append(i + 1)
                time.sleep(0.5)
            except Exception as e:
                logger.warning("Memory search %d failed: %s", i, str(e)[:80])
        return success


# ─── 测试注册表 (新增用例只需在此注册) ───────────────────────────

TEST_REGISTRY = [
    {"class": TestMaxTenants, "requires": []},
    {"class": TestMaxUsersPerTenant, "requires": ["tenant_ids"]},
    {"class": TestMaxAdminsPerTenant, "requires": ["tenant_ids"]},
    {"class": TestMaxGroupsPerTenant, "requires": ["tenant_ids"]},
    {"class": TestMaxAgentsPerTenant, "requires": []},
    {"class": TestMaxConversationTurns, "requires": ["agent_ids"]},
    {"class": TestMaxConversationsPerUser, "requires": []},
    {"class": TestMaxKbsPerTenant, "requires": []},
    {"class": TestMaxKbsPerUser, "requires": []},
    {"class": TestMaxMcpsPerTenant, "requires": []},
    {"class": TestMaxSkillsPerTenant, "requires": []},
    {"class": TestMaxMemoriesPerAgent, "requires": ["agent_ids"]},
    {"class": TestHybridSearch, "requires": []},
    {"class": TestDocumentIndexing, "requires": []},
    {"class": TestFileUpload, "requires": []},
    {"class": TestDataProcessTask, "requires": []},
    {"class": TestMemorySearch, "requires": []},
]


# ─── 主入口 ───────────────────────────────────────────────────────

def _parse_filter(filter_str: str, total: int) -> set:
    """Parse --filter string like '1-7', '1,3,5', 'all' into a set of indices."""
    if not filter_str or filter_str.lower() == "all":
        return set(range(total))
    indices = set()
    for part in filter_str.split(","):
        part = part.strip()
        if "-" in part:
            lo, hi = part.split("-", 1)
            indices.update(range(int(lo) - 1, int(hi)))
        else:
            indices.add(int(part) - 1)
    return {i for i in indices if 0 <= i < total}


def _parse_skip(skip_str: str) -> set:
    """Parse --skip string like 'memories,12,kbs' into a set of (index, name) to skip."""
    if not skip_str:
        return set(), set()
    parts = [p.strip().lower() for p in skip_str.split(",")]
    skip_names = set()
    skip_indices = set()
    for p in parts:
        if p.isdigit():
            skip_indices.add(int(p) - 1)
        else:
            skip_names.add(p)
    return skip_names, skip_indices


def run_all(filter_str: str = None, skip_str: str = None):
    logger.info("=" * 60)
    logger.info("Nexent Scale Specification Tests (run_id=%s)", RUN_ID)
    logger.info("=" * 60)

    # Build test list with filtering
    all_tests = list(TEST_REGISTRY)
    run_indices = _parse_filter(filter_str, len(all_tests))
    skip_names, skip_indices = _parse_skip(skip_str)

    selected = []
    for i, entry in enumerate(all_tests):
        tc_name = entry["class"].name.lower()
        if i not in run_indices:
            continue
        if i in skip_indices or tc_name in skip_names or any(s in tc_name for s in skip_names):
            logger.info("Skipping #%d %s (--skip)", i + 1, entry["class"].name)
            continue
        selected.append((i, entry))

    logger.info("Running %d/%d tests", len(selected), len(all_tests))
    for i, entry in selected:
        logger.info("  #%d %s", i + 1, entry["class"].name)

    login()
    report = TestReport()
    monitor = ResourceMonitor(interval=5.0, collect_host=True)

    ctx: dict = {"tenant_ids": [], "agent_ids": []}

    for i, entry in selected:
        tc_class = entry["class"]
        requires = entry["requires"]

        skip = False
        for req in requires:
            if not ctx.get(req):
                logger.warning("Skipping %s: missing dependency '%s'", tc_class.name, req)
                skip = True
                break
        if skip:
            continue

        kwargs = {}
        if "tenant_ids" in requires and ctx["tenant_ids"]:
            if tc_class == TestMaxUsersPerTenant:
                kwargs["tenant_id"] = ctx["tenant_ids"][0]
            elif tc_class == TestMaxAdminsPerTenant:
                kwargs["tenant_id"] = ctx["tenant_ids"][1] if len(ctx["tenant_ids"]) > 1 else ctx["tenant_ids"][0]
            elif tc_class == TestMaxGroupsPerTenant:
                kwargs["tenant_id"] = ctx["tenant_ids"][0]
        if "agent_ids" in requires and ctx["agent_ids"]:
            kwargs["agent_id"] = ctx["agent_ids"][0]

        instance = tc_class(report, monitor, **kwargs)
        result_ids = instance.execute()

        if tc_class == TestMaxTenants:
            ctx["tenant_ids"] = result_ids
        elif tc_class == TestMaxAgentsPerTenant:
            ctx["agent_ids"] = result_ids
            if result_ids:
                from utils import publish_agent
                publish_agent(result_ids[0])

    summary = report.summary()
    report.save("test/scale/spec_test_report.txt")

    try:
        from utils import generate_final_report_md
        generate_final_report_md()
    except Exception as e:
        logger.warning("Failed to generate final report: %s", str(e)[:120])

    logger.info("All spec tests completed.")
    return report


if __name__ == "__main__":
    import sys
    import argparse
    sys.path.insert(0, "test/scale")
    ap = argparse.ArgumentParser(description="Nexent Scale Specification Tests")
    ap.add_argument("--filter", default=None,
                    help="Filter tests by index: '1-7', '1,3,5', 'all' (default: all)")
    ap.add_argument("--skip", default=None,
                    help="Skip tests by name or index: 'memories,12,kbs'")
    args = ap.parse_args()
    run_all(filter_str=args.filter, skip_str=args.skip)
