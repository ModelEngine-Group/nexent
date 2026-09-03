"""
Nexent platform performance specification tests.

Specs:
  1. Single agent max concurrent: 50
  2. Platform max concurrent agents: 200
  3. API rate limit: 120/min (NORTHBOUND_RATE_LIMIT_PER_MINUTE)

Tests via northbound API POST /nb/v1/chat/run.
Uses PerfTestCase base class; framework handles resource monitoring and reporting.

Usage:
  python -m test.scale.perf_test [--scenario all|rate_limit|single_agent|platform]
"""

import asyncio
import time
import sys
import os
import argparse
import httpx
from typing import List

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from utils import (
    logger, TestReport, TestResult, ResourceMonitor, PerfTestCase,
)

# ─── Config (环境变量覆盖，自动获取 NB_KEY) ─────────────────────

NB_BASE = os.getenv("NEXENT_NB_BASE", "http://localhost:5013")
NB_KEY = None  # Lazily initialized in run_all()
NB_HEADERS = {}
TIMEOUT = httpx.Timeout(180, connect=10)

QUERY = "请详细分析人工智能在企业数字化转型中的作用，包括技术趋势、实施挑战、成功案例和未来展望"
QUERY_SHORT = "请用100字简要介绍人工智能的应用场景"
AGENTS = [
    "safe1", "a1", "a2", "a3", "bug2_original_01999_repro",
    "citation_highlight_verify", "arxrd1", "da",
    "lateral_thinking_tanku_assistant", "md_format_assistant",
]
INVALID_AGENT = "perf-no-such-agent-xyz"


# ─── Async request helpers ─────────────────────────────────────

async def _do_one(client, active_counter, results, idx, agent, query, t_start):
    """Send a request, track active count, record result.

    Uses streaming mode to read the full SSE response naturally.
    Latency reflects real LLM response time. No artificial sleep.
    """
    active_counter["count"] += 1
    t0 = time.time()
    try:
        async with client.stream(
            "POST",
            f"{NB_BASE}/nb/v1/chat/run",
            headers=NB_HEADERS,
            json={"agent_name": agent, "query": query},
        ) as r:
            code = str(r.status_code)
            if r.status_code < 400:
                async for _ in r.aiter_lines():
                    pass
    except Exception as e:
        code = "ERR:" + type(e).__name__
    finally:
        active_counter["count"] -= 1
    results.append({
        "i": idx, "code": code,
        "start": round(t0 - t_start, 2),
        "dt": round(time.time() - t0, 2),
    })


async def _burst_immediate(client, active_counter, results, agents, total, concurrency, query):
    """Fire total requests immediately with concurrency cap (semaphore)."""
    sem = asyncio.Semaphore(concurrency)
    t_start = time.time()

    async def worker(i):
        async with sem:
            agent = agents[i % len(agents)]
            await _do_one(client, active_counter, results, i, agent, query, t_start)

    await asyncio.gather(*[worker(i) for i in range(total)])


async def _burst_paced(client, active_counter, results, agents, total, rate_per_sec, query):
    """Fire requests at a fixed rate (rate_per_sec per second)."""
    t_start = time.time()
    interval = 1.0 / rate_per_sec
    tasks = []
    loop = asyncio.get_event_loop()
    next_time = loop.time()
    for i in range(total):
        agent = agents[i % len(agents)]
        tasks.append(asyncio.create_task(
            _do_one(client, active_counter, results, i, agent, query, t_start)
        ))
        next_time += interval
        delay = next_time - loop.time()
        if delay > 0:
            await asyncio.sleep(delay)
    await asyncio.gather(*tasks)


async def _wait_minute_boundary():
    """Wait for the next minute boundary (rate limit window reset)."""
    now = time.time()
    nxt = (now // 60 + 1) * 60
    wait = nxt - now + 0.5
    logger.info("Waiting %.0fs for rate limit window reset...", wait)
    await asyncio.sleep(wait)


def _latency_stats(results: list) -> dict:
    """Calculate latency percentiles from successful (HTTP 200) responses."""
    ok = sorted(r["dt"] for r in results if r["code"] == "200")
    if not ok:
        return {}
    n = len(ok)
    return {
        "count": n,
        "p50": round(ok[n // 2], 1),
        "p95": round(ok[int(n * 0.95) - 1], 1),
        "p99": round(ok[int(n * 0.99) - 1], 1),
        "max": round(ok[-1], 1),
    }


def _status_dist(results: list) -> dict:
    dist = {}
    for r in results:
        dist[r["code"]] = dist.get(r["code"], 0) + 1
    return dist


def _first_429(results: list) -> int:
    for r in sorted(results, key=lambda x: x["i"]):
        if r["code"] == "429":
            return r["i"] + 1
    return 0


# ─── Test cases ─────────────────────────────────────────────────

class TestRateLimit(PerfTestCase):
    """Spec 3: API rate limit 120/min.

    Fire 150 invalid-agent requests at 20 concurrency.
    Each request consumes rate limit quota; expect 429 after ~120.
    """
    name = "rate_limit"
    target = 120

    async def run_async(self) -> dict:
        active_counter = self.monitor.active_counter or {"count": 0}
        active_counter["count"] = 0
        results: list = []
        limits = httpx.Limits(max_connections=400, max_keepalive_connections=100)

        t0 = time.time()
        async with httpx.AsyncClient(timeout=TIMEOUT, limits=limits) as client:
            await _burst_immediate(client, active_counter, results,
                                   [INVALID_AGENT], 150, 20, "hi")
        duration = round(time.time() - t0, 2)
        logger.info("Rate limit scenario done in %.1fs", duration)

        dist = _status_dist(results)
        first_429 = _first_429(results)
        actual = first_429 if first_429 else 150
        passed = first_429 > 0 and 90 <= first_429 <= 130

        return {
            "actual": actual,
            "passed": passed,
            "metrics": {
                "total_requests": 150,
                "status_distribution": dist,
                "first_429_index": first_429,
                "rate_limit_triggered": first_429 > 0,
                "duration_s": duration,
            },
        }


class TestSingleAgentConcurrency(PerfTestCase):
    """Spec 1: Single agent max concurrent 50.

    Fire 60 concurrent real requests to the same agent (safe1).
    All should succeed (200) — spec allows 50, we push to 60.
    """
    name = "single_agent_concurrency"
    target = 50

    async def run_async(self) -> dict:
        active_counter = self.monitor.active_counter or {"count": 0}
        active_counter["count"] = 0
        results: list = []
        limits = httpx.Limits(max_connections=400, max_keepalive_connections=100)

        t0 = time.time()
        async with httpx.AsyncClient(timeout=TIMEOUT, limits=limits) as client:
            await _burst_immediate(client, active_counter, results,
                                    ["safe1"], 60, 60, QUERY_SHORT)
        duration = round(time.time() - t0, 2)
        logger.info("Single agent scenario done in %.1fs", duration)

        dist = _status_dist(results)
        lat = _latency_stats(results)
        success_count = dist.get("200", 0)
        actual = success_count
        passed = success_count >= 50

        return {
            "actual": actual,
            "passed": passed,
            "metrics": {
                "total_requests": 60,
                "status_distribution": dist,
                "latency_s": lat,
                "duration_s": duration,
            },
        }


class TestPlatformConcurrency(PerfTestCase):
    """Spec 2: Platform max concurrent agents 200.

    Phase 1: 2/s x 150 requests (compliant rate, accumulates concurrency).
    Phase 2: 6/s x 120 requests (exceeds rate, observe limiting + peak).
    """
    name = "platform_concurrency"
    target = 200

    async def run_async(self) -> dict:
        active_counter = self.monitor.active_counter or {"count": 0}
        active_counter["count"] = 0
        results: list = []
        limits = httpx.Limits(max_connections=400, max_keepalive_connections=100)
        sem = asyncio.Semaphore(240)

        t0 = time.time()
        async with httpx.AsyncClient(timeout=TIMEOUT, limits=limits) as client:
            async def worker(i, agent, query):
                async with sem:
                    await _do_one(client, active_counter, results, i, agent, query, t0)

            # Phase 1: burst 120 (don't wait for completion)
            logger.info("-- Phase 1: burst 120 requests --")
            phase1_tasks = [asyncio.create_task(worker(i, AGENTS[i % len(AGENTS)], QUERY)) for i in range(120)]

            # Wait for rate limit window reset (Phase 1 still holding)
            await _wait_minute_boundary()

            # Phase 2: burst 120 (Phase 1 still active, overlap!)
            logger.info("-- Phase 2: burst 120 requests (overlap with Phase 1) --")
            phase2_tasks = [asyncio.create_task(worker(i + 120, AGENTS[(i + 120) % len(AGENTS)], QUERY)) for i in range(120)]

            # Now wait for all to complete
            await asyncio.gather(*phase1_tasks, *phase2_tasks)
            logger.info("All phases done in %.1fs", time.time() - t0)

        duration = round(time.time() - t0, 2)
        dist = _status_dist(results)
        lat = _latency_stats(results)
        first_429 = _first_429(results)

        active_vals = [s.get("active_executions", 0) for s in self.monitor.samples]
        peak_concurrent = max(active_vals) if active_vals else 0
        actual = peak_concurrent
        passed = peak_concurrent >= 200

        return {
            "actual": actual,
            "passed": passed,
            "metrics": {
                "total_requests": 240,
                "status_distribution": dist,
                "latency_s": lat,
                "first_429_index": first_429,
                "peak_concurrent": peak_concurrent,
                "duration_s": duration,
            },
        }


class TestComplexAgentConcurrency(PerfTestCase):
    """Spec: Complex agent with KB + Exa search + Skill + MCP, measure peak concurrency.

    Setup:
    1. Register MCP vis server (chart generation)
    2. Create sub-agent (visualization assistant) with MCP tools
    3. Create main agent (health report interpreter) with KB + Exa + sub-agent + Skill
    4. Publish both agents
    5. Send concurrent requests, measure peak concurrency
    """

    name = "complex_agent_concurrency"
    target = 50

    async def run_async(self) -> dict:
        active_counter = self.monitor.active_counter or {"count": 0}
        active_counter["count"] = 0
        results: list = []
        limits = httpx.Limits(max_connections=200, max_keepalive_connections=50)

        agent_names = await self._setup_complex_agents()
        if not agent_names:
            return {"actual": 0, "passed": False, "metrics": {"error": "Setup failed"}}

        query = "我的体检报告显示低密度脂蛋白3.8mmol/L，帮我解读并给出生活建议"
        total = 60
        sem = asyncio.Semaphore(60)
        t0 = time.time()

        async with httpx.AsyncClient(timeout=httpx.Timeout(300, connect=10), limits=limits) as client:

            async def worker(i):
                async with sem:
                    agent = agent_names[i % len(agent_names)]
                    await _do_one(client, active_counter, results, i, agent, query, t0)

            tasks = [asyncio.create_task(worker(i)) for i in range(total)]
            await asyncio.gather(*tasks)
            logger.info("Complex agent test done in %.1fs", time.time() - t0)

        duration = round(time.time() - t0, 2)
        dist = _status_dist(results)
        lat = _latency_stats(results)
        active_vals = [s.get("active_executions", 0) for s in self.monitor.samples]
        peak_concurrent = max(active_vals) if active_vals else 0

        return {
            "actual": peak_concurrent,
            "passed": peak_concurrent >= 50,
            "metrics": {
                "total_requests": total,
                "status_distribution": dist,
                "latency_s": lat,
                "peak_concurrent": peak_concurrent,
                "duration_s": duration,
                "agent_names": agent_names,
            },
        }

    async def _setup_complex_agents(self) -> list:
        """Create multiple agents (one per LLM model) with KB + Exa + Skill + sub-agent."""
        import asyncio as aio

        from utils import (
            login, api_get, api_post,
            get_embedding_model_id, publish_agent, create_skill,
            TIMEOUT_SLOW, get_session, BASE_URL,
        )

        login()
        emb_id = get_embedding_model_id()
        RUN_ID = time.strftime("%m%d%H%M")

        # --- Get all LLM models ---
        try:
            model_resp = api_get("/model/list")
            models = model_resp.get("data", [])
            llm_ids = [m["model_id"] for m in models if m.get("model_type") == "llm"]
        except Exception:
            llm_ids = []
        if not llm_ids:
            logger.warning("No LLM models found")
            return []

        logger.info("LLM models: %d (%s)", len(llm_ids), llm_ids)

        # --- Step 1: Register MCP vis server ---
        # MCP tools don't have tool_id in the DB — they're fetched dynamically at
        # runtime from the remote MCP server.  As long as the MCP record has
        # enabled=True and status=True, get_all_mcp_tools() will load them for
        # every agent in the tenant automatically (no enabled_tool_ids needed).
        mcp_name = f"perf_vis_{RUN_ID}"
        mcp_url = "https://mcp.api-inference.modelscope.net/02d25af142d74b/sse"
        mcp_id = None
        try:
            api_post("/mcp/add", json_body={
                "name": mcp_name,
                "server_url": mcp_url,
                "description": "Medical data visualization MCP",
                "skip_health_check": True,
                "enabled": True,
            })
            logger.info("MCP vis server registered (enabled): %s", mcp_name)
            await aio.sleep(2)

            mcp_list = api_get("/mcp/list")
            mcps = mcp_list.get("remote_mcp_server_list", []) if isinstance(mcp_list, dict) else []
            for m in mcps:
                if m.get("remote_mcp_server_name") == mcp_name:
                    mcp_id = m.get("mcp_id")
                    break

            if mcp_id:
                session = get_session()
                session.post(f"{BASE_URL}/mcp/refresh-tools", params={"mcp_id": mcp_id}, timeout=60)
                await aio.sleep(2)
                tools_resp = session.get(f"{BASE_URL}/mcp/tools", params={"mcp_id": mcp_id}, timeout=60)
                tools_data = tools_resp.json() if hasattr(tools_resp, "json") else {}
                mcp_tools = tools_data.get("tools", []) if isinstance(tools_data, dict) else []
                logger.info("MCP tools fetched: %d (names only, no tool_id)", len(mcp_tools))
            else:
                logger.warning("MCP server not found in list")
        except Exception as e:
            logger.warning("MCP setup failed: %s", str(e)[:100])

        # --- Step 2: Create KB with health data ---
        kb_name = f"perf_health_kb_{RUN_ID}"
        try:
            resp = api_post(f"/indices/{kb_name}", json_body={"embedding_model_id": emb_id}, timeout=TIMEOUT_SLOW)
            index_name = resp.get("id", kb_name)
            logger.info("Health KB created: %s", index_name)
        except Exception as e:
            logger.warning("Create health KB failed: %s", str(e)[:100])
            return []

        await aio.sleep(5)

        medical_docs = [
            {
                "content": "低密度脂蛋白(LDL)正常值<3.4mmol/L。偏高(3.4-4.1)建议饮食控制："
                           "减少饱和脂肪摄入、增加膳食纤维、控制体重、规律运动。"
                           "严重偏高(>4.1)需药物治疗：他汀类药物。",
                "metadata": {"source": "ldl-guideline"}
            },
            {
                "content": "血红蛋白正常值：男性130-175g/L，女性115-150g/L。"
                           "偏低(贫血)建议：增加铁质摄入(红肉、动物肝脏、菠菜)、"
                           "补充维生素B12和叶酸、避免浓茶咖啡影响铁吸收。",
                "metadata": {"source": "hemoglobin-guideline"}
            },
            {
                "content": "血糖正常值：空腹3.9-6.1mmol/L。偏高(6.1-7.0)为糖尿病前期，"
                           "建议：减少精制碳水、增加运动、控制体重、定期监测。"
                           ">=7.0需就医，可能需要药物控制。",
                "metadata": {"source": "glucose-guideline"}
            },
            {
                "content": "肝功能ALT正常值<40U/L。偏高提示肝损伤，"
                           "建议：戒酒、避免肝损药物、控制脂肪摄入、"
                           "复查肝功能全套和肝脏B超。",
                "metadata": {"source": "alt-guideline"}
            },
        ]

        try:
            api_post(f"/indices/{index_name}/documents", json_body=medical_docs, timeout=TIMEOUT_SLOW)
            logger.info("Health docs indexed: %d", len(medical_docs))
        except Exception as e:
            logger.warning("Index health docs failed: %s", str(e)[:100])

        await aio.sleep(3)

        # --- Step 3: Create skill ---
        skill_name = f"perf_report_skill_{RUN_ID}"
        try:
            create_skill(skill_name)
            skill_resp = api_get("/skills", timeout=60)
            skills_list = skill_resp.get("skills", [])
            skill_id = None
            for s in skills_list:
                if s.get("skill_name") == skill_name:
                    skill_id = s.get("skill_id")
                    break
            logger.info("Skill created: %s", skill_name)
        except Exception as e:
            logger.warning("Create skill failed: %s", str(e)[:100])
            skill_id = None

        # --- Step 4: Get tool IDs ---
        try:
            tool_resp = api_get("/tool/list")
            tools = tool_resp if isinstance(tool_resp, list) else tool_resp.get("data", [])
            kb_tool_id = None
            exa_tool_id = None
            img_tool_id = None
            text_tool_id = None
            for t in tools:
                nm = (t.get("name") or "").lower()
                if "knowledge" in nm:
                    kb_tool_id = t.get("tool_id")
                if nm == "exa_search":
                    exa_tool_id = t.get("tool_id")
                if nm == "analyze_image":
                    img_tool_id = t.get("tool_id")
                if nm == "analyze_text_file":
                    text_tool_id = t.get("tool_id")
        except Exception:
            kb_tool_id = exa_tool_id = img_tool_id = text_tool_id = None

        # --- Step 5: Create sub-agent (MCP vis tools auto-available) ---
        # MCP tools are loaded at runtime from the registered MCP server; no
        # tool_id is needed in enabled_tool_ids.  The sub-agent just needs a
        # duty prompt that instructs it to call the vis tools.
        sub_agent_id = None
        try:
            resp = api_get("/agent/get_creating_sub_agent_id")
            sub_agent_id = resp.get("agent_id") or resp.get("data", {}).get("agent_id")

            sub_body = {
                "agent_id": sub_agent_id,
                "name": f"perf_vis_agent_{RUN_ID}",
                "display_name": "体检数据可视化助手",
                "description": "医疗数据可视化专家",
                "duty_prompt": "你是一名医疗数据可视化专家，根据体检数据生成图表配置。",
                "constraint_prompt": "1. 雷达图需max组+真实数据组 2. 液态图0-1之间",
                "model_ids": [llm_ids[0]] if llm_ids else [],
                "enabled": True,
            }
            api_post("/agent/update", json_body=sub_body)
            publish_agent(sub_agent_id)
            logger.info("Sub-agent (vis) created and published")
        except Exception as e:
            logger.warning("Sub-agent creation failed: %s", str(e)[:100])
            sub_agent_id = None

        # --- Step 6: Create one agent per LLM model ---
        tool_ids = [tid for tid in [kb_tool_id, exa_tool_id, img_tool_id, text_tool_id] if tid]
        related_agents = [sub_agent_id] if sub_agent_id else []
        agent_names = []

        for idx, llm_id in enumerate(llm_ids):
            agent_name = f"perf_health_agent_{RUN_ID}_{idx}"
            try:
                resp = api_get("/agent/get_creating_sub_agent_id")
                agent_id = resp.get("agent_id") or resp.get("data", {}).get("agent_id")
            except Exception:
                continue

            body = {
                "agent_id": agent_id,
                "name": agent_name,
                "display_name": f"体检报告解读助手-{llm_ids[idx]}",
                "description": "报告解读助手，OCR识别体检报告，联网查询健康指南，调用可视化专家生成图表",
                "duty_prompt": (
                    "你是一个报告解读助手，负责生成图文并茂的体检报告解读，并提供生活建议。"
                    "你具备OCR识别、联网检索和数据分析能力。"
                ),
                "constraint_prompt": (
                    "1. 使用analyze_image/analyze_text_file识别体检报告\n"
                    "2. 使用exa_search查询异常指标指南\n"
                    "3. 使用knowledge_base_search检索本地健康知识库\n"
                    "4. 调用可视化专家生成2-3张图表\n"
                    "5. 输出：异常指标→健康建议→图表→解读报告"
                ),
                "few_shots_prompt": (
                    "任务：\"体检报告显示低密度脂蛋白3.8mmol/L\"\n"
                    "思考：调用knowledge_base_search检索LDL正常值和建议。\n"
                    "代码：\n<code>\n"
                    "result = knowledge_base_search(query=\"低密度脂蛋白正常值 饮食控制\", index_names=[\"健康知识库\"])\n"
                    "print(result)\n</code>\n"
                    "# 返回: LDL<3.4，3.8偏高\n"
                    "\n"
                    "思考：调用exa_search搜索最新指南。\n"
                    "代码：\n<code>\n"
                    "web = exa_search(query=\"低密度脂蛋白偏高 饮食控制\")\n"
                    "print(web)\n</code>\n"
                    "\n"
                    "思考：调用可视化专家生成图表。\n"
                    "代码：\n<code>\n"
                    "chart = report_data_vis_assistant(task=\"生成雷达图\")\n"
                    "print(chart)\n</code>\n"
                    "\n"
                    "解读报告：低密度脂蛋白3.8偏高，建议减少饱和脂肪、增加纤维、规律运动。"
                ),
                "model_ids": [llm_id],
                "enabled_tool_ids": tool_ids,
                "enabled_skill_ids": [skill_id] if skill_id else [],
                "related_agent_ids": related_agents if related_agents else None,
                "max_steps": 5,
                "enabled": True,
            }

            try:
                api_post("/agent/update", json_body=body)
                logger.info("Agent %d created: %s (model=%s)", idx, agent_name, llm_id)

                if kb_tool_id:
                    api_post("/tool/update", json_body={
                        "tool_id": kb_tool_id, "agent_id": agent_id,
                        "params": {"index_names": [index_name], "rerank": False, "top_k": 5, "search_mode": "hybrid"},
                        "enabled": True,
                    })
                if exa_tool_id:
                    try:
                        api_post("/tool/update", json_body={
                            "tool_id": exa_tool_id, "agent_id": agent_id,
                            "params": {"exa_api_key": "1a967894-b4a3-4f8e-9fdc-f1c89f9a5d4e", "max_results": 3, "image_filter": True},
                            "enabled": True,
                        })
                    except Exception:
                        pass
                if skill_id:
                    try:
                        api_post("/skills/instance/update", json_body={
                            "skill_id": skill_id, "agent_id": agent_id, "enabled": True,
                        })
                    except Exception:
                        pass

                publish_agent(agent_id)
                logger.info("Agent %d published: %s", idx, agent_name)
                agent_names.append(agent_name)
            except Exception as e:
                logger.warning("Agent %d setup failed: %s", idx, str(e)[:100])

        logger.info("Total agents created: %d", len(agent_names))
        return agent_names


# ─── Registry (add new perf tests here) ────────────────────────

PERF_TEST_REGISTRY = [
    {"class": TestRateLimit, "requires": []},
    {"class": TestSingleAgentConcurrency, "requires": []},
    {"class": TestPlatformConcurrency, "requires": []},
    {"class": TestComplexAgentConcurrency, "requires": []},
]

SCENARIO_MAP = {
    "rate_limit": TestRateLimit,
    "single_agent": TestSingleAgentConcurrency,
    "platform": TestPlatformConcurrency,
    "complex_agent": TestComplexAgentConcurrency,
}


# ─── Main entry ─────────────────────────────────────────────────

def run_all(scenario: str = "all"):
    logger.info("=" * 60)
    logger.info("Nexent Performance Specification Tests")
    logger.info("=" * 60)

    global NB_KEY, NB_HEADERS
    if not NB_KEY:
        from utils import get_or_create_nb_key
        NB_KEY = get_or_create_nb_key()
        NB_HEADERS = {"Authorization": f"Bearer {NB_KEY}"}

    report = TestReport()
    active_counter = {"count": 0}
    monitor = ResourceMonitor(
        interval=2.0,
        collect_host=True,
        tcp_container="nexent-northbound",
        active_counter=active_counter,
    )

    if scenario == "all":
        classes_to_run = [e["class"] for e in PERF_TEST_REGISTRY]
    else:
        if scenario not in SCENARIO_MAP:
            logger.error("Unknown scenario: %s", scenario)
            return
        classes_to_run = [SCENARIO_MAP[scenario]]

    for i, cls in enumerate(classes_to_run):
        instance = cls(report, monitor)
        instance.execute()
        if i < len(classes_to_run) - 1:
            asyncio.run(_wait_minute_boundary())

    summary = report.summary()
    report.save("test/scale/perf_test_report.txt")
    logger.info("All perf tests completed.")

    try:
        from utils import generate_final_report_md
        generate_final_report_md()
    except Exception as e:
        logger.warning("Failed to generate final report: %s", str(e)[:120])

    return report


if __name__ == "__main__":
    import sys
    sys.path.insert(0, "test/scale")
    ap = argparse.ArgumentParser()
    ap.add_argument("--scenario", default="all",
                    choices=["all", "rate_limit", "single_agent", "platform", "complex_agent"])
    args = ap.parse_args()
    run_all(args.scenario)
