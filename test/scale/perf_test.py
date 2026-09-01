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


# ─── Registry (add new perf tests here) ────────────────────────

PERF_TEST_REGISTRY = [
    {"class": TestRateLimit, "requires": []},
    {"class": TestSingleAgentConcurrency, "requires": []},
    {"class": TestPlatformConcurrency, "requires": []},
]

SCENARIO_MAP = {
    "rate_limit": TestRateLimit,
    "single_agent": TestSingleAgentConcurrency,
    "platform": TestPlatformConcurrency,
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
                    choices=["all", "rate_limit", "single_agent", "platform"])
    args = ap.parse_args()
    run_all(args.scenario)
