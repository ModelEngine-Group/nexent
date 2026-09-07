"""
Nexent 测试框架 — 公共工具模块

职责:
  - 登录获取 cookie-based session
  - 封装通用 HTTP 请求 (GET/POST/PUT/DELETE)
  - 提供测试数据的批量创建/查询/删除辅助函数
  - 收集系统资源指标 (Docker 容器 CPU/内存, 数据库计数)
  - 生成测试报告
"""

import os
import time
import json
import logging
import threading
import requests
from typing import Optional, List, Dict, Any, Callable
from dataclasses import dataclass, field, asdict
from abc import ABC, abstractmethod

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("nexent_test")

# ─── 配置 (环境变量覆盖，带默认值) ────────────────────────────────

BASE_URL = os.getenv("NEXENT_BASE_URL", "http://localhost:3000/api")
ADMIN_EMAIL = os.getenv("NEXENT_TEST_EMAIL", "")
ADMIN_PASSWORD = os.getenv("NEXENT_TEST_PASSWORD", "")
NB_BASE = os.getenv("NEXENT_NB_BASE", "http://localhost:5013")
NB_KEY = os.getenv("NEXENT_NB_KEY", "nexent-perftest-ddca790af3c2")
DP_BASE = os.getenv("NEXENT_DP_BASE", "http://localhost:5012")

TIMEOUT_QUICK = 10
TIMEOUT_NORMAL = 30
TIMEOUT_SLOW = 120
TIMEOUT_AGENT = 300


def get_or_create_nb_key() -> str:
    """Auto-detect or create a northbound API key.

    1. If NEXENT_NB_KEY env var is set, use it.
    2. Otherwise, login and query existing tokens.
    3. If no token exists, create one via POST /user/tokens.
    """
    env_key = os.getenv("NEXENT_NB_KEY")
    if env_key:
        return env_key

    login()
    resp = api_get("/user/current_user_id")
    user_id = resp.get("data", {}).get("user_id")
    if not user_id:
        raise RuntimeError("Cannot get user_id for token creation")

    tokens = api_get(f"/user/tokens?user_id={user_id}")
    token_list = tokens.get("data", [])
    if isinstance(token_list, list) and token_list:
        key = token_list[0].get("access_key")
        if key:
            logger.info("Reusing existing NB key: %s", key[:20] + "...")
            return key

    resp = api_post("/user/tokens")
    key = resp.get("data", {}).get("access_key")
    if not key:
        raise RuntimeError("Failed to create NB key")
    logger.info("Created new NB key: %s", key[:20] + "...")
    return key

# ─── Session 管理 ──────────────────────────────────────────────────

_session_cache: dict = {}


def login(email: str = ADMIN_EMAIL, password: str = ADMIN_PASSWORD) -> requests.Session:
    if not email or not password:
        raise RuntimeError(
            "Test credentials not configured. Set environment variables:\n"
            "  export NEXENT_TEST_EMAIL=your_email@example.com\n"
            "  export NEXENT_TEST_PASSWORD=your_password"
        )
    session = requests.Session()
    resp = session.post(
        f"{BASE_URL}/user/signin",
        json={"email": email, "password": password},
        timeout=TIMEOUT_NORMAL,
    )
    resp.raise_for_status()
    if "nexent_access_token" not in session.cookies.get_dict():
        raise ValueError(f"Login failed: no auth cookie set. Response: {resp.json()}")
    _session_cache[email] = session
    logger.info("Logged in as %s", email)
    return session


def get_session(email: str = ADMIN_EMAIL) -> requests.Session:
    session = _session_cache.get(email)
    if not session:
        session = login(email)
    return session


_relogin_lock = threading.Lock()


def _request_with_retry(method: str, path: str, email: str, timeout: int, **kwargs) -> requests.Response:
    """Execute HTTP request with auto re-login on 401 (thread-safe).

    Only one thread performs re-login; others wait and reuse the refreshed session.
    """
    url = f"{BASE_URL}{path}"
    session = get_session(email)
    resp = session.request(method, url, timeout=timeout, **kwargs)

    if resp.status_code == 401:
        with _relogin_lock:
            current_session = _session_cache.get(email)
            if current_session is not session:
                session = current_session
            else:
                logger.warning("401 on %s %s, re-logining...", method, path)
                _session_cache.pop(email, None)
                session = login(email)
        resp = session.request(method, url, timeout=timeout, **kwargs)

    if resp.status_code >= 400:
        logger.error("%s %s -> %d: %s", method, path, resp.status_code, resp.text[:500])
    resp.raise_for_status()
    return resp


def api_get(path: str, email: str = ADMIN_EMAIL, timeout: int = TIMEOUT_QUICK, **kwargs) -> dict:
    resp = _request_with_retry("GET", path, email, timeout, **kwargs)
    return resp.json() if resp.content else {}


def api_post(path: str, json_body=None, email: str = ADMIN_EMAIL,
             timeout: int = TIMEOUT_NORMAL, **kwargs) -> dict:
    kwargs.setdefault("json", json_body)
    resp = _request_with_retry("POST", path, email, timeout, **kwargs)
    return resp.json() if resp.content else {}


def api_put(path: str, json_body=None, email: str = ADMIN_EMAIL, timeout: int = TIMEOUT_NORMAL, **kwargs) -> dict:
    kwargs.setdefault("json", json_body)
    resp = _request_with_retry("PUT", path, email, timeout, **kwargs)
    return resp.json() if resp.content else {}


def api_delete(path: str, email: str = ADMIN_EMAIL, timeout: int = TIMEOUT_NORMAL, **kwargs) -> dict:
    resp = _request_with_retry("DELETE", path, email, timeout, **kwargs)
    return resp.json() if resp.content else {}


# ─── 测试结果与报告 ─────────────────────────────────────────────────

@dataclass
class TestResult:
    name: str
    target: int
    actual: int = 0
    passed: bool = False
    duration_s: float = 0.0
    error: str = ""
    metrics: dict = field(default_factory=dict)
    resource_samples: list = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


class TestReport:
    def __init__(self):
        self.results: list[TestResult] = []

    def add(self, result: TestResult):
        self.results.append(result)
        status = "PASS" if result.passed else "FAIL"
        logger.info(
            "[%s] %s: target=%d actual=%d duration=%.1fs%s",
            status, result.name, result.target, result.actual,
            result.duration_s,
            f" error={result.error}" if result.error else "",
        )

    def summary(self) -> str:
        passed = sum(1 for r in self.results if r.passed)
        total = len(self.results)
        lines = [
            "=" * 60,
            f"Test Summary: {passed}/{total} passed",
            "=" * 60,
        ]
        for r in self.results:
            status = "[PASS]" if r.passed else "[FAIL]"
            lines.append(
                f"  {status} {r.name}: target={r.target} actual={r.actual} "
                f"duration={r.duration_s:.1f}s"
                + (f" error={r.error}" if r.error else "")
            )
            if r.metrics:
                for k, v in r.metrics.items():
                    if k not in ("status_distribution",):
                        lines.append(f"      {k}: {v}")
                if "status_distribution" in r.metrics:
                    lines.append(f"      status_distribution: {r.metrics['status_distribution']}")
            if r.resource_samples:
                lines.append(_format_resource_summary(r.resource_samples))
        lines.append("=" * 60)
        report = "\n".join(lines)
        logger.info("\n%s", report)
        return report

    def to_json(self) -> str:
        return json.dumps([r.to_dict() for r in self.results], indent=2, ensure_ascii=False)

    def save(self, filepath: str):
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(self.summary())
            f.write("\n\n--- JSON ---\n")
            f.write(self.to_json())
        logger.info("Report saved to %s", filepath)


# ─── 资源监控 ───────────────────────────────────────────────────────

class ResourceMonitor:
    """后台线程采样 Docker 容器 CPU/内存 + 数据库计数 + 可选宿主机/TCP/活跃计数."""

    def __init__(self, interval: float = 5.0, collect_host: bool = False,
                 tcp_container: Optional[str] = None,
                 active_counter: Optional[dict] = None):
        self.interval = interval
        self.collect_host = collect_host
        self.tcp_container = tcp_container
        self.active_counter = active_counter
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self.samples: list[dict] = []
        self._psutil_ok = False
        if collect_host:
            try:
                import psutil
                psutil.cpu_percent(interval=None)
                self._psutil_ok = True
            except ImportError:
                logger.warning("psutil not available, host metrics disabled")

    def start(self):
        if self._thread and self._thread.is_alive():
            return
        self.samples.clear()
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()
        logger.info("ResourceMonitor started (interval=%.0fs, host=%s, tcp=%s)",
                    self.interval, self.collect_host, self.tcp_container or "N/A")

    def stop(self) -> list[dict]:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=self.interval + 5)
        logger.info("ResourceMonitor stopped, %d samples collected", len(self.samples))
        return list(self.samples)

    def _loop(self):
        while not self._stop.is_set():
            sample = self._collect()
            if sample:
                self.samples.append(sample)
            self._stop.wait(self.interval)

    def _collect(self) -> Optional[dict]:
        ts = time.time()
        data: dict = {"timestamp": ts, "containers": {}, "db": {}}
        data["containers"] = collect_system_metrics()
        data["db"] = collect_db_metrics()

        if self.collect_host and self._psutil_ok:
            try:
                import psutil
                data["host"] = {
                    "cpu_percent": psutil.cpu_percent(interval=None),
                    "mem_percent": psutil.virtual_memory().percent,
                }
            except Exception:
                data["host"] = {"cpu_percent": -1, "mem_percent": -1}

        if self.tcp_container:
            data["tcp_established"] = _collect_tcp_established(self.tcp_container)

        if self.active_counter is not None:
            data["active_executions"] = self.active_counter.get("count", 0)

        return data

    def collect_once(self) -> dict:
        return self._collect() or {}


def collect_system_metrics() -> dict:
    """收集所有 nexent 容器的 CPU/内存."""
    import subprocess
    try:
        result = subprocess.run(
            ["docker", "stats", "--no-stream",
             "--format", "{{.Name}}\t{{.CPUPerc}}\t{{.MemUsage}}\t{{.MemPerc}}"],
            capture_output=True, text=True, timeout=15,
        )
        containers = {}
        for line in result.stdout.strip().split("\n"):
            if not line:
                continue
            parts = line.split("\t")
            if len(parts) >= 4:
                name = parts[0].strip()
                if not name.startswith("nexent") and not name.startswith("supabase"):
                    continue
                cpu_str = parts[1].strip().rstrip("%")
                mem_parts = parts[2].strip().split(" / ")
                mem_pct = parts[3].strip().rstrip("%")
                containers[name] = {
                    "cpu_pct": _safe_float(cpu_str),
                    "mem_usage": mem_parts[0] if mem_parts else parts[2].strip(),
                    "mem_pct": _safe_float(mem_pct),
                }
        return containers
    except Exception as e:
        logger.warning("Failed to collect docker stats: %s", e)
        return {}


def collect_db_metrics() -> dict:
    """收集数据库关键计数."""
    import subprocess
    try:
        queries = {
            "tenants": "SELECT count(DISTINCT tenant_id) FROM nexent.tenant_config_t WHERE delete_flag='N' AND config_key='TENANT_NAME'",
            "users": "SELECT count(*) FROM nexent.user_tenant_t WHERE delete_flag='N'",
            "groups": "SELECT count(*) FROM nexent.tenant_group_info_t WHERE delete_flag='N'",
            "agents": "SELECT count(*) FROM nexent.ag_tenant_agent_t WHERE delete_flag='N'",
            "conversations": "SELECT count(*) FROM nexent.conversation_record_t WHERE delete_flag='N'",
            "knowledge_bases": "SELECT count(*) FROM nexent.knowledge_record_t WHERE delete_flag='N'",
            "mcp_services": "SELECT count(*) FROM nexent.mcp_record_t WHERE delete_flag='N'",
            "skills": "SELECT count(*) FROM nexent.ag_skill_info_t WHERE delete_flag='N'",
            "memory_records": "SELECT count(*) FROM nexent.memory_records_t WHERE delete_flag='N'",
        }
        results = {}
        for key, sql in queries.items():
            r = subprocess.run(
                ["docker", "exec", "nexent-postgresql", "psql", "-U", "root", "-d", "nexent",
                 "-tAc", sql],
                capture_output=True, text=True, timeout=10,
            )
            results[key] = int(r.stdout.strip() or 0)
        return results
    except Exception as e:
        logger.warning("Failed to collect DB metrics: %s", e)
        return {}


def _safe_float(s: str) -> float:
    try:
        return float(s)
    except (ValueError, TypeError):
        return 0.0


def _collect_tcp_established(container: str) -> int:
    """Count TCP ESTABLISHED connections inside a container via /proc/net/tcp."""
    import subprocess
    try:
        out = subprocess.run(
            ["docker", "exec", container, "sh", "-c",
             "cat /proc/net/tcp /proc/net/tcp6 2>/dev/null"],
            capture_output=True, text=True, timeout=10,
        )
        return sum(1 for ln in out.stdout.splitlines()[1:]
                   if ln.split() and ln.split()[3] == "01")
    except Exception:
        return -1


def _format_resource_summary(samples: list) -> str:
    """Format resource samples: containers, host, TCP, active executions."""
    if not samples:
        return ""
    lines = ["    Resource Summary:"]
    # Containers
    container_names = set()
    for s in samples:
        container_names.update(s.get("containers", {}).keys())
    for name in sorted(container_names):
        cpu_vals = []
        mem_vals = []
        for s in samples:
            c = s.get("containers", {}).get(name)
            if c:
                cpu_vals.append(c["cpu_pct"])
                mem_vals.append(c["mem_pct"])
        if cpu_vals:
            lines.append(
                f"      {name}: CPU avg={sum(cpu_vals)/len(cpu_vals):.1f}% "
                f"max={max(cpu_vals):.1f}% | Mem avg={sum(mem_vals)/len(mem_vals):.1f}% "
                f"max={max(mem_vals):.1f}%"
            )
    # Host metrics
    host_cpu = [s["host"]["cpu_percent"] for s in samples
                if s.get("host") and s["host"]["cpu_percent"] >= 0]
    host_mem = [s["host"]["mem_percent"] for s in samples
                if s.get("host") and s["host"]["mem_percent"] >= 0]
    if host_cpu:
        lines.append(
            f"      Host: CPU avg={sum(host_cpu)/len(host_cpu):.1f}% "
            f"max={max(host_cpu):.1f}% | Mem avg={sum(host_mem)/len(host_mem):.1f}% "
            f"max={max(host_mem):.1f}%"
        )
    # TCP connections
    tcp_vals = [s["tcp_established"] for s in samples
                if s.get("tcp_established", -1) >= 0]
    if tcp_vals:
        lines.append(
            f"      TCP ESTABLISHED: peak={max(tcp_vals)} avg={sum(tcp_vals)/len(tcp_vals):.0f}"
        )
    # Active executions
    active_vals = [s["active_executions"] for s in samples
                   if "active_executions" in s]
    if active_vals:
        lines.append(
            f"      Active executions: peak={max(active_vals)} avg={sum(active_vals)/len(active_vals):.0f}"
        )
    return "\n".join(lines)


# ─── 抽象测试用例基类 ──────────────────────────────────────────────

class BaseTestCase(ABC):
    """所有测试用例的基类. 子类实现 run(), 框架自动处理监控和报告."""

    name: str = ""
    target: int = 0

    def __init__(self, report: TestReport, monitor: ResourceMonitor):
        self.report = report
        self.monitor = monitor
        self.created_ids: list = []

    @abstractmethod
    def run(self) -> list:
        """执行测试, 返回创建的资源 ID 列表."""
        ...

    def execute(self) -> list:
        """框架调用: 启动监控 -> run() -> 停止监控 -> 生成 TestResult."""
        logger.info("=== Test: %s (target=%d) ===", self.name, self.target)
        start = time.time()
        self.monitor.start()
        try:
            self.created_ids = self.run()
        except Exception as e:
            logger.error("Test %s failed: %s", self.name, e)
            self.report.add(TestResult(
                name=self.name, target=self.target, actual=0,
                passed=False, duration_s=time.time() - start,
                error=str(e)[:200],
            ))
            return []
        finally:
            samples = self.monitor.stop()

        duration = time.time() - start
        db = collect_db_metrics()
        actual = db.get(self._db_metric_key(), len(self.created_ids))

        result = TestResult(
            name=self.name,
            target=self.target,
            actual=actual,
            passed=len(self.created_ids) >= self.target * 0.95,
            duration_s=duration,
            metrics=db,
            resource_samples=samples,
        )
        self.report.add(result)
        return self.created_ids

    def _db_metric_key(self) -> str:
        """子类可覆盖, 返回 collect_db_metrics() 里对应的 key."""
        return ""


class PerfTestCase(BaseTestCase):
    """Performance test base class for async (httpx) scenarios.

    Subclasses implement run_async() returning a dict:
      {"actual": int, "passed": bool, "metrics": dict}
    Framework handles monitor start/stop, TestResult, resource summary.
    """

    @abstractmethod
    async def run_async(self) -> dict:
        """Execute async test. Returns dict with 'actual', 'passed', 'metrics'."""
        ...

    def run(self) -> list:
        raise RuntimeError("PerfTestCase uses execute() directly, not run()")

    def execute(self) -> list:
        import asyncio
        logger.info("=== Perf Test: %s (target=%d) ===", self.name, self.target)
        start = time.time()
        self.monitor.start()
        try:
            perf_result = asyncio.run(self.run_async())
        except Exception as e:
            logger.error("Perf test %s failed: %s", self.name, e)
            self.report.add(TestResult(
                name=self.name, target=self.target, actual=0,
                passed=False, duration_s=time.time() - start,
                error=str(e)[:200],
            ))
            return []
        finally:
            samples = self.monitor.stop()

        duration = time.time() - start
        result = TestResult(
            name=self.name,
            target=self.target,
            actual=perf_result.get("actual", 0),
            passed=perf_result.get("passed", False),
            duration_s=duration,
            metrics=perf_result.get("metrics", {}),
            resource_samples=samples,
        )
        self.report.add(result)
        return []


# ─── 批量操作辅助 ──────────────────────────────────────────────────

def create_tenant(name: str) -> dict:
    return api_post("/tenants", json_body={"tenant_name": name})


def delete_tenant(tenant_id: str):
    api_delete(f"/tenants/{tenant_id}")


def create_invitation(tenant_id: str, code_type: str = "USER_INVITE",
                      capacity: int = 10000) -> str:
    resp = api_post("/invitations", json_body={
        "tenant_id": tenant_id,
        "code_type": code_type,
        "capacity": capacity,
    })
    code = resp.get("data", {}).get("invitation_code", "")
    if not code:
        raise ValueError(f"Failed to create invitation: {resp}")
    logger.info("Created invitation code: %s (capacity=%d)", code, capacity)
    return code


def create_user(email: str, password: str, invite_code: str) -> dict:
    resp = requests.post(
        f"{BASE_URL}/user/signup",
        json={"email": email, "password": password, "invite_code": invite_code},
        timeout=TIMEOUT_NORMAL,
    )
    if resp.status_code >= 400:
        raise ValueError(f"Create user failed: {resp.text[:200]}")
    return resp.json()


def create_group(tenant_id: str, name: str) -> dict:
    return api_post("/groups", json_body={"tenant_id": tenant_id, "group_name": name})


def create_agent(name: str, agent_id: Optional[int] = None,
                 tool_ids: Optional[List[int]] = None,
                 skill_ids: Optional[List[int]] = None,
                 related_agent_ids: Optional[List[int]] = None) -> int:
    if agent_id is None:
        resp = api_get("/agent/get_creating_sub_agent_id")
        agent_id = resp.get("agent_id") or resp.get("data", {}).get("agent_id")
    try:
        model_id = get_llm_model_id()
    except ValueError:
        model_id = None
    body = {
        "agent_id": agent_id,
        "name": name,
        "duty_prompt": "Test agent for scale testing",
        "model_ids": [model_id] if model_id else [],
        "enabled_tool_ids": tool_ids or [],
        "enabled_skill_ids": skill_ids or [],
        "enabled": True,
    }
    if related_agent_ids:
        body["related_agent_ids"] = related_agent_ids
    api_post("/agent/update", json_body=body)
    return agent_id


def delete_agent(agent_id: int):
    api_delete("/agent", json={"agent_id": agent_id})


def publish_agent(agent_id: int) -> bool:
    try:
        api_post(f"/agent/{agent_id}/publish", json_body={})
        logger.info("Agent %s published for northbound access", agent_id)
        return True
    except Exception as e:
        logger.warning("Publish agent %s failed: %s", agent_id, str(e)[:80])
        return False


def create_conversation(title: str = "scale-test") -> dict:
    return api_put("/conversation/create", json_body={"title": title})


def delete_conversation(conversation_id: int):
    api_delete(f"/conversation/{conversation_id}")


_embedding_model_id_cache = None
_llm_model_id_cache = None

def get_embedding_model_id() -> int:
    global _embedding_model_id_cache
    if _embedding_model_id_cache is not None:
        return _embedding_model_id_cache
    r = api_get("/model/list")
    models = r.get("data", [])
    for m in models:
        if m.get("model_type") == "embedding":
            _embedding_model_id_cache = m["model_id"]
            return _embedding_model_id_cache
    raise ValueError("No embedding model found. Configure one in the UI first.")

def get_llm_model_id() -> int:
    global _llm_model_id_cache
    if _llm_model_id_cache is not None:
        return _llm_model_id_cache
    r = api_get("/model/list")
    models = r.get("data", [])
    for m in models:
        if m.get("model_type") == "llm":
            _llm_model_id_cache = m["model_id"]
            return _llm_model_id_cache
    raise ValueError("No LLM model found. Configure one in the UI first.")


def create_knowledge_base(name: str, embedding_model_id: Optional[int] = None) -> dict:
    if embedding_model_id is None:
        embedding_model_id = get_embedding_model_id()
    return api_post(f"/indices/{name}", json_body={"embedding_model_id": embedding_model_id})


def delete_knowledge_base(index_name: str):
    api_delete(f"/indices/{index_name}")


def create_mcp_service(name: str, server_url: str = "http://127.0.0.1:9999/sse") -> dict:
    resp = api_post("/mcp/add", json_body={
        "name": name,
        "server_url": server_url,
        "description": "scale test mcp",
        "skip_health_check": True,
    })
    if isinstance(resp, dict) and not resp.get("mcp_id") and not resp.get("data", {}).get("mcp_id"):
        try:
            lst = api_get("/mcp/list")
            items = lst.get("data", []) if isinstance(lst, dict) else lst
            if isinstance(items, list):
                for m in items:
                    if m.get("mcp_name") == name or m.get("name") == name:
                        resp["mcp_id"] = m.get("mcp_id")
                        break
        except Exception:
            pass
    return resp


def delete_mcp_service(mcp_id: int):
    api_delete(f"/mcp/{mcp_id}")


def create_skill(name: str) -> dict:
    return api_post("/skills", json_body={
        "name": name,
        "description": "scale test skill",
        "content": "def run(query):\n    return 'test'",
    })


def delete_skill(name: str):
    api_delete(f"/skills/{name}")


def create_memory_record(layer: str = "agent", content: str = "test memory",
                          agent_id: Optional[int] = None) -> dict:
    body = {"layer": layer, "content": content}
    if agent_id is not None:
        body["agent_id"] = str(agent_id)
    return api_post("/memory/records", json_body=body, timeout=TIMEOUT_SLOW)


def delete_memory_record(memory_id: str):
    api_delete(f"/memory/records/{memory_id}")


# DP_BASE is defined in the config section above

_KB_SEARCH_TOOL_ID_CACHE = None


def find_kb_search_tool_id() -> Optional[int]:
    global _KB_SEARCH_TOOL_ID_CACHE
    if _KB_SEARCH_TOOL_ID_CACHE is not None:
        return _KB_SEARCH_TOOL_ID_CACHE
    resp = api_get("/tool/list")
    tools = resp if isinstance(resp, list) else resp.get("data", resp)
    if isinstance(tools, list):
        for t in tools:
            nm = (t.get("name") or "").lower()
            cn = (t.get("class_name") or "").lower()
            if "knowledge" in nm or "knowledge" in cn:
                _KB_SEARCH_TOOL_ID_CACHE = t.get("tool_id")
                return _KB_SEARCH_TOOL_ID_CACHE
    return None


def upload_text_to_kb(kb_index_name: str, text_content: str) -> bool:
    session = get_session()
    import io
    files = {"file": ("test_doc.txt", io.BytesIO(text_content.encode("utf-8")), "text/plain")}
    data = {"destination": "minio", "folder": f"knowledge_base/{kb_index_name}", "index_name": kb_index_name}
    upload_resp = session.post(f"{BASE_URL}/file/upload", files=files, data=data)
    if upload_resp.status_code >= 400:
        logger.warning("Upload to KB failed: %s", upload_resp.text[:200])
        return False
    uploaded_paths = upload_resp.json().get("uploaded_file_paths", [])
    if not uploaded_paths:
        logger.warning("No uploaded file paths returned")
        return False
    source = uploaded_paths[0]
    emb_id = get_embedding_model_id()
    task_resp = session.post(f"{DP_BASE}/tasks", json={
        "source": source,
        "source_type": "minio",
        "chunking_strategy": "basic",
        "index_name": kb_index_name,
        "original_filename": "test_doc.txt",
        "embedding_model_id": emb_id,
    })
    if task_resp.status_code >= 400:
        logger.warning("DP task failed: %s", task_resp.text[:200])
        return False
    logger.info("KB '%s' document uploaded, task_id=%s", kb_index_name, task_resp.json().get("task_id"))
    return True


def attach_kb_to_agent(agent_id: int, kb_index_name: str, tool_id: Optional[int] = None) -> bool:
    if tool_id is None:
        tool_id = find_kb_search_tool_id()
    if not tool_id:
        logger.warning("KnowledgeBaseSearchTool not found, skipping KB attachment")
        return False
    try:
        api_post("/tool/update", json_body={
            "tool_id": tool_id,
            "agent_id": agent_id,
            "params": {"index_names": [kb_index_name], "rerank": False, "top_k": 5},
            "enabled": True,
        })
        logger.info("KB '%s' attached to agent %d", kb_index_name, agent_id)
        return True
    except Exception as e:
        logger.warning("Attach KB to agent %d failed: %s", agent_id, str(e)[:120])
        return False


KB_TEST_CONTENT = """
Nexent is a zero-code platform for auto-generating AI agents.
It supports multi-tenant architecture with up to 100 tenants per instance.
Each tenant can have up to 10000 users, 1000 groups, and 1000 agents.
The platform uses Elasticsearch for knowledge base storage and retrieval.
Agents can be configured with MCP tools, skills, and knowledge bases.
The northbound API supports streaming chat with rate limiting at 120 requests per minute.
Maximum concurrent agent executions is 200, with tested peak of 277.
The platform is deployed using Docker Compose with PostgreSQL, Redis, Elasticsearch, and MinIO.
"""


# ─── 最终报告生成 ─────────────────────────────────────────────────

def _parse_report_json(filepath: str) -> list:
    with open(filepath, "r", encoding="utf-8") as f:
        content = f.read()
    marker = "--- JSON ---"
    idx = content.find(marker)
    if idx < 0:
        return []
    return json.loads(content[idx + len(marker):].strip())


def _parse_mem_gib(s: str) -> float:
    """Parse memory string like '6.036GiB' or '133.6MiB' to GiB."""
    if not s:
        return 0.0
    s = s.strip()
    try:
        if s.endswith("GiB"):
            return round(float(s[:-3]), 2)
        if s.endswith("MiB"):
            return round(float(s[:-3]) / 1024, 2)
        if s.endswith("KiB"):
            return round(float(s[:-3]) / 1024 / 1024, 3)
    except ValueError:
        pass
    return 0.0


def _compute_resource_stats(samples: list) -> dict:
    if not samples:
        return {}
    container_names = set()
    for s in samples:
        container_names.update(s.get("containers", {}).keys())
    stats = {}
    # Detect total host memory from first sample with both mem_pct and mem_usage
    total_mem_gib = 0.0
    for s in samples:
        for name, c in s.get("containers", {}).items():
            pct = c.get("mem_pct", 0)
            usage = c.get("mem_usage", "")
            gib = _parse_mem_gib(usage)
            if pct > 1 and gib > 0.1:
                total_mem_gib = gib / (pct / 100)
                break
        if total_mem_gib:
            break

    for name in sorted(container_names):
        cpu_vals, mem_gibs = [], []
        for s in samples:
            c = s.get("containers", {}).get(name)
            if c:
                cpu_vals.append(c["cpu_pct"])
                gib = _parse_mem_gib(c.get("mem_usage", ""))
                if gib > 0:
                    mem_gibs.append(gib)
        if cpu_vals:
            stats[name] = {
                "cpu_avg": sum(cpu_vals) / len(cpu_vals),
                "cpu_max": max(cpu_vals),
                "mem_avg_gib": (sum(mem_gibs) / len(mem_gibs)) if mem_gibs else 0.0,
                "mem_max_gib": max(mem_gibs) if mem_gibs else 0.0,
            }
    host_cpu = [s["host"]["cpu_percent"] for s in samples
                if s.get("host") and s["host"]["cpu_percent"] >= 0]
    host_mem = [s["host"]["mem_percent"] for s in samples
                if s.get("host") and s["host"]["mem_percent"] >= 0]
    if host_cpu:
        stats["__host__"] = {
            "cpu_avg": sum(host_cpu) / len(host_cpu),
            "cpu_max": max(host_cpu),
            "mem_avg_gib": (sum(host_mem) / len(host_mem) * total_mem_gib / 100) if total_mem_gib else 0.0,
            "mem_max_gib": (max(host_mem) * total_mem_gib / 100) if total_mem_gib else 0.0,
        }
    tcp_vals = [s["tcp_established"] for s in samples
                if s.get("tcp_established", -1) >= 0]
    if tcp_vals:
        stats["__tcp_peak__"] = max(tcp_vals)
    active_vals = [s["active_executions"] for s in samples
                   if "active_executions" in s]
    if active_vals:
        stats["__active_peak__"] = max(active_vals)
    return stats


def generate_final_report_md(spec_path: str = "test/scale/spec_test_report.txt",
                            perf_path: str = "test/scale/perf_test_report.txt",
                            output_path: str = "test/scale/final_test_report.md"):
    spec_results = _parse_report_json(spec_path)
    perf_results = _parse_report_json(perf_path)

    lines = [
        "# Nexent 规格测试报告",
        "",
        f"日期: {time.strftime('%Y-%m-%d')} | 部署: Docker Desktop (WSL2)",
        "",
        "## 一、数据量规格测试",
        "",
        "### 结果总览",
        "",
    ]

    spec_pass = sum(1 for r in spec_results if r.get("passed"))
    spec_total = len(spec_results)
    lines.append(f"> {spec_pass}/{spec_total} 通过")
    lines.append("")
    lines.append("| # | 测试项 | 目标 | 结果 | 说明 |")
    lines.append("|---|--------|------|------|------|")

    spec_names_zh = {
        "max_tenants": "最大租户数",
        "max_users_per_tenant": "单租户用户数",
        "max_admins_per_tenant": "单租户管理员数",
        "max_groups_per_tenant": "单租户用户组数",
        "max_agents_per_tenant": "单租户 Agent 数",
        "max_conversation_turns": "单会话对话轮数",
        "max_conversations_per_user": "单用户会话条数",
        "max_kbs_per_tenant": "单租户知识库数",
        "max_kbs_per_user": "单用户知识库数",
        "max_mcps_per_tenant": "单租户 MCP 数",
        "max_skills_per_tenant": "单租户 Skill 数",
        "max_memories_per_agent": "单 Agent 记忆数",
    }

    for i, r in enumerate(spec_results):
        name = spec_names_zh.get(r["name"], r["name"])
        target = r["target"]
        actual = r["actual"]
        passed = "✅ 通过" if r["passed"] else "❌ 受限"
        note = r.get("error", "") or f"实测 {actual}"
        lines.append(f"| {i+1} | {name} | {target:,} | {passed} | {note} |")

    lines.append("")
    lines.append("### 资源消耗")
    lines.append("")

    all_spec_samples = []
    for r in spec_results:
        all_spec_samples.extend(r.get("resource_samples", []))
    spec_stats = _compute_resource_stats(all_spec_samples)

    if spec_stats:
        lines.append("| 容器 | CPU avg | CPU max | 内存 avg | 内存 max |")
        lines.append("|------|--------|---------|---------|---------|")
        host_stat = spec_stats.pop("__host__", None)
        for name in sorted(spec_stats.keys(),
                           key=lambda n: spec_stats[n]["cpu_max"], reverse=True):
            s = spec_stats[name]
            lines.append(f"| {name} | {s['cpu_avg']:.1f}% | {s['cpu_max']:.1f}% | {s['mem_avg_gib']:.2f}GiB | {s['mem_max_gib']:.2f}GiB |")
        if host_stat:
            lines.append(f"| **宿主机** | **{host_stat['cpu_avg']:.1f}%** | **{host_stat['cpu_max']:.1f}%** | **{host_stat['mem_avg_gib']:.1f}GiB** | **{host_stat['mem_max_gib']:.1f}GiB** |")
    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append("## 二、性能规格测试")
    lines.append("")
    lines.append("测试对象: 北向 API `POST http://localhost:5013/nb/v1/chat/run`")
    lines.append("")
    lines.append("### 测试结果")
    lines.append("")

    perf_pass = sum(1 for r in perf_results if r.get("passed"))
    perf_total = len(perf_results)
    lines.append(f"> {perf_pass}/{perf_total} 通过")
    lines.append("")
    lines.append("| # | 规格项 | 规格值 | 实测值 | 延迟 p50/p95/p99 | 结果 |")
    lines.append("|---|--------|--------|--------|-----------------|------|")

    perf_names_zh = {
        "rate_limit": "平台 API 速率限制",
        "single_agent_concurrency": "单 Agent 最大并发执行数",
        "platform_concurrency": "最大并发执行 Agent 并发数",
    }

    for i, r in enumerate(perf_results):
        name = perf_names_zh.get(r["name"], r["name"])
        target = r["target"]
        actual = r["actual"]
        passed = "✅ PASS" if r["passed"] else "❌ FAIL"
        latency = r.get("metrics", {}).get("latency_s", {})
        if isinstance(latency, dict) and latency.get("p50"):
            lat_str = f"{latency['p50']:.1f}s / {latency.get('p95', 0):.1f}s / {latency.get('p99', 0):.1f}s"
        else:
            lat_str = "—"
        actual_str = f"峰值 {actual}" if "concurrency" in r["name"] else str(actual)
        if r["name"] == "rate_limit":
            actual_str = f"第 {actual} 个请求起 429"
        elif r["name"] == "single_agent_concurrency":
            actual_str = f"{actual} 并发全部成功"
        lines.append(f"| {i+1} | {name} | {target} | {actual_str} | {lat_str} | {passed} |")

    lines.append("")
    lines.append("### 资源消耗")
    lines.append("")

    all_perf_samples = []
    for r in perf_results:
        all_perf_samples.extend(r.get("resource_samples", []))
    perf_stats = _compute_resource_stats(all_perf_samples)

    if perf_stats:
        tcp_peak = perf_stats.pop("__tcp_peak__", None)
        active_peak = perf_stats.pop("__active_peak__", None)
        lines.append("| 容器 | CPU avg | CPU max | 内存 avg | 内存 max |")
        lines.append("|------|--------|---------|---------|---------|")
        host_stat = perf_stats.pop("__host__", None)
        for name in sorted(perf_stats.keys(),
                           key=lambda n: perf_stats[n]["cpu_max"], reverse=True):
            s = perf_stats[name]
            lines.append(f"| {name} | {s['cpu_avg']:.1f}% | {s['cpu_max']:.1f}% | {s['mem_avg_gib']:.2f}GiB | {s['mem_max_gib']:.2f}GiB |")
        if host_stat:
            lines.append(f"| **宿主机** | **{host_stat['cpu_avg']:.1f}%** | **{host_stat['cpu_max']:.1f}%** | **{host_stat['mem_avg_gib']:.1f}GiB** | **{host_stat['mem_max_gib']:.1f}GiB** |")
        if tcp_peak or active_peak:
            lines.append("")
            extras = []
            if tcp_peak:
                extras.append(f"TCP 连接峰值: {tcp_peak}")
            if active_peak:
                extras.append(f"活跃执行峰值: {active_peak}")
            lines.append(" | ".join(extras))

    lines.append("")

    content = "\n".join(lines)
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(content)
    logger.info("Final report generated: %s", output_path)
    return content
